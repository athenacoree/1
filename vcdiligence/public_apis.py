import os
import csv
import json
import datetime
import requests
import difflib
from bs4 import BeautifulSoup
from urllib.parse import quote
from vcdiligence.logging_config import logger

PUBLIC_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache", "public_apis")
os.makedirs(PUBLIC_CACHE_DIR, exist_ok=True)

def get_cached_response(api_name: str, query: str, ttl_hours: int = 24) -> dict:
    """Returns cached response if it exists and is less than ttl_hours old."""
    safe_query = "".join([c if c.isalnum() else "_" for c in query])
    cache_path = os.path.join(PUBLIC_CACHE_DIR, f"{api_name}_{safe_query}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
                timestamp = datetime.datetime.fromisoformat(cached["timestamp"])
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)
                if datetime.datetime.now(datetime.timezone.utc) - timestamp < datetime.timedelta(hours=ttl_hours):
                    return cached["data"]
        except Exception:
            pass
    return None

def set_cached_response(api_name: str, query: str, data: dict, ttl_hours: int = 24):
    """Saves API response to the local JSON cache."""
    safe_query = "".join([c if c.isalnum() else "_" for c in query])
    cache_path = os.path.join(PUBLIC_CACHE_DIR, f"{api_name}_{safe_query}.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "data": data
            }, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to write cache for {api_name}: {str(e)}")

def search_sec_edgar(company_name: str, force_refresh: bool = False) -> dict:
    """
    Queries api.sec.gov for submissions or filings.
    Requires proper User-Agent string as per SEC guidelines.
    """
    if not force_refresh:
        cached = get_cached_response("sec_edgar", company_name)
        if cached:
            return cached

    # SEC EDGAR requires a specific User-Agent format: Organization ContactEmail
    headers = {
        "User-Agent": "DealScoutAI Team info@vcdiligenceagent.com"
    }

    try:
        # Step 1: Search company ticker/CIK mapping
        url = "https://data.sec.gov/files/company_tickers.json"
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"SEC API returned HTTP {response.status_code}"}

        data = response.json()
        matched_cik = None
        for key, value in data.items():
            if company_name.lower() in value["title"].lower():
                matched_cik = str(value["cik_str"]).zfill(10)
                break

        if not matched_cik:
            result = {"status": "not_found", "message": "No CIK found in SEC company directory for this name"}
            set_cached_response("sec_edgar", company_name, result)
            return result

        # Step 2: Query company submissions
        sub_url = f"https://data.sec.gov/submissions/CIK{matched_cik}.json"
        sub_resp = requests.get(sub_url, headers=headers, timeout=10)
        if sub_resp.status_code == 200:
            sub_data = sub_resp.json()
            recent_filings = sub_data.get("filings", {}).get("recent", {})
            filings_list = []
            if recent_filings:
                # Extract first 5 filings
                for i in range(min(5, len(recent_filings.get("form", [])))):
                    filings_list.append({
                        "form": recent_filings["form"][i],
                        "filingDate": recent_filings["filingDate"][i],
                        "reportDate": recent_filings["reportDate"][i],
                        "primaryDocDescription": recent_filings["primaryDocDescription"][i]
                    })
            result = {
                "status": "found",
                "cik": matched_cik,
                "name": sub_data.get("name", company_name),
                "stateOfIncorporation": sub_data.get("stateOfIncorporation", "Unknown"),
                "recent_filings": filings_list
            }
        else:
            result = {"status": "found_cik_only", "cik": matched_cik, "message": f"CIK found but failed to retrieve filings: HTTP {sub_resp.status_code}"}

        set_cached_response("sec_edgar", company_name, result)
        return result
    except Exception as e:
        logger.error(f"SEC Edgar query error for {company_name}: {str(e)}")
        return {"status": "error", "message": f"Connection/Parsing error: {str(e)}"}

def search_opencorporates(company_name: str, force_refresh: bool = False) -> dict:
    """Queries OpenCorporates for company registration details."""
    if not force_refresh:
        cached = get_cached_response("opencorporates", company_name)
        if cached:
            return cached

    # Optional API key from environment
    api_key = os.getenv("OPENCORPORATES_API_KEY")
    url = "https://api.opencorporates.com/v0.4/companies/search"
    params = {"q": company_name}
    if api_key:
        params["api_token"] = api_key

    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"OpenCorporates returned HTTP {response.status_code}"}

        data = response.json()
        results = data.get("results", {}).get("companies", [])
        if not results:
            result = {"status": "not_found", "message": "No registrations found under these specific search terms"}
        else:
            company_info = results[0].get("company", {})
            result = {
                "status": "found",
                "name": company_info.get("name"),
                "company_number": company_info.get("company_number"),
                "jurisdiction_code": company_info.get("jurisdiction_code"),
                "incorporation_date": company_info.get("incorporation_date"),
                "current_status": company_info.get("current_status"),
                "registry_url": company_info.get("registry_url")
            }
        set_cached_response("opencorporates", company_name, result)
        return result
    except Exception as e:
        logger.error(f"OpenCorporates search error: {str(e)}")
        return {"status": "error", "message": f"Connection/Parsing error: {str(e)}"}

def search_uspto(company_name: str, force_refresh: bool = False) -> dict:
    """Queries USPTO for trademark or patent availability/registration indicators."""
    if not force_refresh:
        cached = get_cached_response("uspto", company_name)
        if cached:
            return cached

    # USPTO Open Data Portal Patent Application API
    url = "https://developer.uspto.gov/ibd-api/v1/patent/application"
    params = {"searchText": company_name, "start": 0, "rows": 3}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"USPTO API returned HTTP {response.status_code}"}

        data = response.json()
        records = data.get("results", [])
        if not records:
            result = {"status": "not_found", "message": "No active patent registrations found under these search terms"}
        else:
            patents_found = []
            for item in records:
                patents_found.append({
                    "title": item.get("inventionTitle"),
                    "applicationNumber": item.get("applicationNumber"),
                    "filingDate": item.get("filingDate"),
                    "applicantName": item.get("applicantName")
                })
            result = {
                "status": "found",
                "patents": patents_found
            }
        set_cached_response("uspto", company_name, result)
        return result
    except Exception as e:
        logger.error(f"USPTO search error: {str(e)}")
        return {"status": "error", "message": f"Connection/Parsing error: {str(e)}"}

def search_courtlistener(company_name: str, force_refresh: bool = False) -> dict:
    """
    Queries CourtListener (RECAP) API for federal litigations associated with the company name.
    Does NOT draw legal conclusions or decide guilt. Reports matches as findings needing human review.
    """
    if not force_refresh:
        cached = get_cached_response("courtlistener", company_name)
        if cached:
            return cached

    url = "https://www.courtlistener.com/api/rest/v3/search/"
    params = {"q": company_name, "type": "r"} # 'r' stands for RECAP documents / filings
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"CourtListener API returned HTTP {response.status_code}"}

        data = response.json()
        results = data.get("results", [])
        if not results:
            result = {"status": "not_found", "message": "No public litigation records found under these specific search terms"}
        else:
            cases = []
            for item in results[:3]:
                cases.append({
                    "caseName": item.get("caseName", "Unknown"),
                    "court": item.get("court", "Unknown"),
                    "dateFiled": item.get("dateFiled", "Unknown"),
                    "absoluteUrl": item.get("absolute_url")
                })
            result = {
                "status": "found",
                "message": "Potential litigation records identified. Recommended for professional legal review.",
                "cases": cases
            }
        set_cached_response("courtlistener", company_name, result)
        return result
    except Exception as e:
        logger.error(f"CourtListener search error: {str(e)}")
        return {"status": "error", "message": f"Connection/Parsing error: {str(e)}"}

def query_github_repo(company_name: str, force_refresh: bool = False) -> dict:
    """
    Queries GitHub API to seek repos or organization details.
    """
    if not force_refresh:
        cached = get_cached_response("github", company_name)
        if cached:
            return cached

    url = f"https://api.github.com/search/repositories"
    params = {"q": company_name, "sort": "stars", "order": "desc"}
    headers = {"Accept": "application/vnd.github.v3+json"}

    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"GitHub API returned HTTP {response.status_code}"}

        data = response.json()
        items = data.get("items", [])
        if not items:
            result = {"status": "not_found", "message": "No public GitHub repositories found under these search terms"}
        else:
            repos = []
            for item in items[:2]:
                repos.append({
                    "name": item.get("full_name"),
                    "description": item.get("description"),
                    "stars": item.get("stargazers_count"),
                    "forks": item.get("forks_count"),
                    "language": item.get("language"),
                    "url": item.get("html_url")
                })
            result = {
                "status": "found",
                "repositories": repos
            }
        set_cached_response("github", company_name, result)
        return result
    except Exception as e:
        logger.error(f"GitHub search error: {str(e)}")
        return {"status": "error", "message": f"Connection/Parsing error: {str(e)}"}


# ====================================================================
# FUNCIONALIDAD 2: Nuevas fuentes públicas
# ====================================================================

def refresh_ofac_local_list() -> bool:
    """Downloads the official OFAC SDN CSV and stores it locally."""
    url = "https://www.treasury.gov/ofac/downloads/sdn.csv"
    os.makedirs(os.path.join(os.path.dirname(__file__), "cache"), exist_ok=True)
    csv_path = os.path.join(os.path.dirname(__file__), "cache", "ofac_sdn_list.csv")
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write(response.text)
            logger.info("Successfully refreshed local OFAC SDN list CSV.")
            return True
        else:
            logger.error(f"Failed to download OFAC list: HTTP {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"Error refreshing OFAC list: {str(e)}")
        return False

def check_ofac_sanctions(company_name: str, force_refresh: bool = False) -> dict:
    """
    Checks OFAC SDN List for possible fuzzy matches of the company name.
    Does NOT call an external API for each query.
    """
    csv_path = os.path.join(os.path.dirname(__file__), "cache", "ofac_sdn_list.csv")
    if not os.path.exists(csv_path):
        logger.warning("OFAC sdn.csv local file missing. Triggering synchronous download fallback.")
        success = refresh_ofac_local_list()
        if not success:
            return {"status": "error", "message": "OFAC SDN CSV file could not be retrieved locally or remotely."}

    # Load entries
    names = []
    try:
        with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) > 1:
                    name = row[1].strip()
                    if name:
                        names.append(name)
    except Exception as e:
        logger.error(f"Error parsing local OFAC sdn.csv: {str(e)}")
        return {"status": "error", "message": f"Error parsing OFAC local data: {str(e)}"}

    # Perform fuzzy match
    matches = difflib.get_close_matches(company_name, names, n=1, cutoff=0.8)
    if matches:
        return {
            "status": "found",
            "matched_name": matches[0],
            "message": "Posible coincidencia en lista de sanciones OFAC — requiere verificación manual, puede ser falso positivo por nombre similar."
        }
    return {"status": "not_found", "message": "No matches found on the OFAC SDN list."}

def search_whois(domain: str, force_refresh: bool = False) -> dict:
    """Queries WHOIS records for domain creation dates. Cached for 30 days (720 hours)."""
    if not force_refresh:
        cached = get_cached_response("whois", domain, ttl_hours=720)
        if cached:
            return cached

    try:
        import whois
        w = whois.whois(domain)
        creation_date = w.creation_date
        if isinstance(creation_date, list) and len(creation_date) > 0:
            creation_date = creation_date[0]

        creation_date_str = None
        if isinstance(creation_date, datetime.datetime):
            creation_date_str = creation_date.isoformat()
        elif creation_date:
            creation_date_str = str(creation_date)

        result = {
            "status": "found" if creation_date_str else "not_found",
            "domain": domain,
            "creation_date": creation_date_str,
            "registrar": w.registrar if hasattr(w, 'registrar') else None
        }
        set_cached_response("whois", domain, result, ttl_hours=720)
        return result
    except Exception as e:
        logger.error(f"WHOIS lookup failed for {domain}: {str(e)}")
        return {"status": "error", "message": f"WHOIS error: {str(e)}"}

def search_sec_litigation(company_name: str, force_refresh: bool = False) -> dict:
    """Scrapes SEC litigation releases looking for mentions of the company name."""
    if not force_refresh:
        cached = get_cached_response("sec_litigation", company_name)
        if cached:
            return cached

    headers = {
        "User-Agent": "DealScoutAI Team info@vcdiligenceagent.com"
    }
    url = "https://www.sec.gov/litigations/litreleases"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"SEC litigation returned HTTP {response.status_code}"}

        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text()

        # Simple search
        if company_name.lower() in text.lower():
            result = {
                "status": "found",
                "message": f"Potential mentions of '{company_name}' identified on the SEC litigation page.",
                "link": url
            }
        else:
            result = {"status": "not_found", "message": "No direct mentions found on the active SEC litigation release log."}

        set_cached_response("sec_litigation", company_name, result)
        return result
    except Exception as e:
        logger.error(f"SEC Litigation search error for {company_name}: {str(e)}")
        return {"status": "error", "message": f"Error: {str(e)}"}

def search_ftc_enforcement(company_name: str, force_refresh: bool = False) -> dict:
    """Scrapes FTC enforcement cases browsing page for company name mentions."""
    if not force_refresh:
        cached = get_cached_response("ftc_enforcement", company_name)
        if cached:
            return cached

    url = "https://www.ftc.gov/legal-library/browse/cases-proceedings"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"FTC cases returned HTTP {response.status_code}"}

        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text()

        if company_name.lower() in text.lower():
            result = {
                "status": "found",
                "message": f"Potential mentions of '{company_name}' found on FTC cases browse log.",
                "link": url
            }
        else:
            result = {"status": "not_found", "message": "No active FTC enforcement cases found matching company name."}

        set_cached_response("ftc_enforcement", company_name, result)
        return result
    except Exception as e:
        logger.error(f"FTC enforcement search error for {company_name}: {str(e)}")
        return {"status": "error", "message": f"Error: {str(e)}"}

def search_cfpb_complaints(company_name: str, force_refresh: bool = False) -> dict:
    """Queries official CFPB Complaints Database API filtering by company name."""
    if not force_refresh:
        cached = get_cached_response("cfpb_complaints", company_name)
        if cached:
            return cached

    url = "https://api.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
    params = {
        "size": 5,
        "field": "company",
        "search_term": company_name
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"CFPB API returned HTTP {response.status_code}"}

        data = response.json()
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        hits = data.get("hits", {}).get("hits", [])

        if total > 0 or len(hits) > 0:
            complaints = []
            for item in hits[:3]:
                source = item.get("_source", {})
                complaints.append({
                    "product": source.get("product"),
                    "sub_product": source.get("sub_product"),
                    "issue": source.get("issue"),
                    "state": source.get("state"),
                    "date_received": source.get("date_received")
                })
            result = {
                "status": "found",
                "total_complaints": total,
                "complaints": complaints
            }
        else:
            result = {"status": "not_found", "message": "No complaints registered with the CFPB for this company."}

        set_cached_response("cfpb_complaints", company_name, result)
        return result
    except Exception as e:
        logger.error(f"CFPB complaints search error for {company_name}: {str(e)}")
        return {"status": "error", "message": f"Error: {str(e)}"}

def search_wipo_brands(company_name: str, force_refresh: bool = False) -> dict:
    """Generates prefilled search link for manual check in WIPO Global Brand Database."""
    return {
        "status": "manual_check_required",
        "message": "Manual verification recommended in the WIPO Global Brand Database.",
        "link": f"https://branddb.wipo.int/en/branddb/brand/search?q={quote(company_name)}"
    }

def search_uk_companies_house(company_name: str, force_refresh: bool = False) -> dict:
    """Queries official UK Companies House API if API key is configured."""
    if not force_refresh:
        cached = get_cached_response("uk_companies_house", company_name)
        if cached:
            return cached

    api_key = os.getenv("COMPANIES_HOUSE_API_KEY")
    if not api_key:
        return {"status": "not_configured", "message": "UK Companies House API key is not configured."}

    url = "https://api.company-information.service.gov.uk/search/companies"
    params = {"q": company_name, "items_per_page": 2}
    try:
        # Companies House API uses HTTP Basic Authentication with the API Key as the username and an empty password
        response = requests.get(url, params=params, auth=(api_key, ""), timeout=10)
        if response.status_code == 401:
            return {"status": "error", "message": "Companies House authorization failed: Invalid API key"}
        elif response.status_code != 200:
            return {"status": "error", "message": f"Companies House returned HTTP {response.status_code}"}

        data = response.json()
        items = data.get("items", [])
        if not items:
            result = {"status": "not_found", "message": "No companies found on UK register matching search term."}
        else:
            matches = []
            for item in items:
                matches.append({
                    "company_number": item.get("company_number"),
                    "title": item.get("title"),
                    "company_status": item.get("company_status"),
                    "date_of_creation": item.get("date_of_creation"),
                    "address_snippet": item.get("address_snippet")
                })
            result = {
                "status": "found",
                "companies": matches
            }
        set_cached_response("uk_companies_house", company_name, result)
        return result
    except Exception as e:
        logger.error(f"UK Companies House lookup failed for {company_name}: {str(e)}")
        return {"status": "error", "message": f"Error: {str(e)}"}

def search_wayback_snapshots(domain: str, force_refresh: bool = False) -> dict:
    """Queries Wayback Machine API for oldest/available snapshots."""
    if not force_refresh:
        cached = get_cached_response("wayback", domain)
        if cached:
            return cached

    url = f"https://archive.org/wayback/available"
    params = {"url": domain}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"Wayback Machine API returned HTTP {response.status_code}"}

        data = response.json()
        snapshot = data.get("archived_snapshots", {}).get("closest", {})
        if snapshot and snapshot.get("available"):
            result = {
                "status": "found",
                "snapshot_url": snapshot.get("url"),
                "timestamp": snapshot.get("timestamp")
            }
        else:
            result = {"status": "not_found", "message": "No archived snapshots available for this domain."}

        set_cached_response("wayback", domain, result)
        return result
    except Exception as e:
        logger.error(f"Wayback Machine lookup failed for {domain}: {str(e)}")
        return {"status": "error", "message": f"Error: {str(e)}"}

def search_gdelt_news(company_name: str, force_refresh: bool = False) -> dict:
    """Queries the public GDELT News API for recent press coverage."""
    if not force_refresh:
        cached = get_cached_response("gdelt_news", company_name)
        if cached:
            return cached

    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": company_name,
        "mode": "artlist",
        "format": "json"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return {"status": "error", "message": f"GDELT returned HTTP {response.status_code}"}

        data = response.json()
        articles = data.get("articles", [])
        if articles:
            news_items = []
            for item in articles[:3]:
                news_items.append({
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "source": item.get("sourcecountry"),
                    "seendate": item.get("seendate")
                })
            result = {
                "status": "found",
                "news": news_items
            }
        else:
            result = {"status": "not_found", "message": "No recent news coverage detected in the GDELT database."}

        set_cached_response("gdelt_news", company_name, result)
        return result
    except Exception as e:
        logger.error(f"GDELT news lookup failed for {company_name}: {str(e)}")
        return {"status": "error", "message": f"Error: {str(e)}"}


def get_all_public_insights(company_name: str, force_refresh: bool = False, sources: list = None) -> dict:
    """Aggregates all public API search insights for the given company (Backward Compatibility)."""
    all_funcs = {
        "sec_edgar": search_sec_edgar,
        "opencorporates": search_opencorporates,
        "uspto": search_uspto,
        "courtlistener": search_courtlistener,
        "github": query_github_repo
    }
    insights = {}
    for name, func in all_funcs.items():
        if sources is not None and name not in sources:
            continue
        insights[name] = func(company_name, force_refresh=force_refresh)
    return insights
