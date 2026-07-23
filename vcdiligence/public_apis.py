import os
import json
import datetime
import requests
from vcdiligence.logging_config import logger

PUBLIC_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache", "public_apis")
os.makedirs(PUBLIC_CACHE_DIR, exist_ok=True)

def get_cached_response(api_name: str, query: str) -> dict:
    """Returns cached response if it exists and is less than 24 hours old."""
    safe_query = "".join([c if c.isalnum() else "_" for c in query])
    cache_path = os.path.join(PUBLIC_CACHE_DIR, f"{api_name}_{safe_query}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
                timestamp = datetime.datetime.fromisoformat(cached["timestamp"])
                if datetime.datetime.utcnow() - timestamp < datetime.timedelta(hours=24):
                    return cached["data"]
        except Exception:
            pass
    return None

def set_cached_response(api_name: str, query: str, data: dict):
    safe_query = "".join([c if c.isalnum() else "_" for c in query])
    cache_path = os.path.join(PUBLIC_CACHE_DIR, f"{api_name}_{safe_query}.json")
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "data": data
            }, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to write cache for {api_name}: {str(e)}")

def search_sec_edgar(company_name: str) -> dict:
    """
    Queries api.sec.gov for submissions or filings.
    Requires proper User-Agent string as per SEC guidelines.
    """
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

def search_opencorporates(company_name: str) -> dict:
    """Queries OpenCorporates for company registration details."""
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

def search_uspto(company_name: str) -> dict:
    """Queries USPTO for trademark or patent availability/registration indicators."""
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

def search_courtlistener(company_name: str) -> dict:
    """
    Queries CourtListener (RECAP) API for federal litigations associated with the company name.
    Does NOT draw legal conclusions or decide guilt. Reports matches as findings needing human review.
    """
    cached = get_cached_response("courtlistener", company_name)
    if cached:
        return cached

    url = "https://www.courtlistener.com/api/rest/v3/search/"
    params = {"q": company_name, "type": "r"} # 'r' stands for RECAP documents / filings
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            # Try fallback endpoint or report error
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

def query_github_repo(company_name: str) -> dict:
    """
    Queries GitHub API to seek repos or organization details.
    """
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

def get_all_public_insights(company_name: str) -> dict:
    """Aggregates all public API search insights for the given company."""
    return {
        "sec_edgar": search_sec_edgar(company_name),
        "opencorporates": search_opencorporates(company_name),
        "uspto": search_uspto(company_name),
        "courtlistener": search_courtlistener(company_name),
        "github": query_github_repo(company_name)
    }
