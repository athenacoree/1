import datetime
import re
from concurrent.futures import ThreadPoolExecutor
from vcdiligence.logging_config import logger
from vcdiligence.public_apis import (
    search_sec_edgar,
    search_opencorporates,
    search_uspto,
    search_courtlistener,
    query_github_repo,
    check_ofac_sanctions,
    search_whois,
    search_sec_litigation,
    search_ftc_enforcement,
    search_cfpb_complaints,
    search_wipo_brands,
    search_uk_companies_house,
    search_wayback_snapshots,
    search_gdelt_news
)

# Registry of all necessary sources and their functions
NECESSARY_SOURCES = {
    "sec_edgar": search_sec_edgar,
    "opencorporates": search_opencorporates,
    "uspto": search_uspto,
    "courtlistener": search_courtlistener,
    "github": query_github_repo,
    "ofac": check_ofac_sanctions,
    "whois": search_whois,
}

# Registry of all conditional sources and their functions
CONDITIONAL_SOURCES = {
    "sec_litigation": search_sec_litigation,
    "ftc_enforcement": search_ftc_enforcement,
    "cfpb_complaints": search_cfpb_complaints,
    "wipo_brands": search_wipo_brands,
    "uk_companies_house": search_uk_companies_house,
    "wayback": search_wayback_snapshots,
    "gdelt_news": search_gdelt_news,
}

class CircuitBreaker:
    consecutive_failures = {}
    paused_until = {}

    @classmethod
    def check(cls, source_name: str) -> bool:
        """Returns True if the source is active (not paused), False otherwise."""
        paused_time = cls.paused_until.get(source_name)
        if paused_time and datetime.datetime.utcnow() < paused_time:
            return False
        return True

    @classmethod
    def record_success(cls, source_name: str):
        cls.consecutive_failures[source_name] = 0

    @classmethod
    def record_failure(cls, source_name: str):
        cls.consecutive_failures[source_name] = cls.consecutive_failures.get(source_name, 0) + 1
        if cls.consecutive_failures[source_name] >= 3:
            cls.paused_until[source_name] = datetime.datetime.utcnow() + datetime.timedelta(hours=2)
            logger.warning(f"Circuit breaker triggered for '{source_name}'. Pausing execution for 2 hours.")

def run_orchestrated_analysis(
    company_name: str,
    domain: str,
    scraped_text: str,
    user_enabled_sources: list = None,
    force_refresh: bool = False
) -> dict:
    """
    Executes and coordinates necessary and conditional public sources based on heuristic criteria.
    Supports concurrency using a ThreadPoolExecutor with max_workers=3 and a local circuit breaker.
    """
    scraped_text = scraped_text or ""
    user_enabled_sources = user_enabled_sources or []

    # 1. Determine which Necessary sources to run
    # Exclude any necessary source only if user explicitly passed a list that does not include it
    necessary_to_run = {}
    for name, func in NECESSARY_SOURCES.items():
        if user_enabled_sources and name not in user_enabled_sources:
            logger.info(f"Source '{name}' skipped because it is not explicitly enabled by the user preferences.")
            continue
        necessary_to_run[name] = func

    # Execute Necessary Sources concurrently
    necessary_results = {}

    def run_source(name, func, query_param):
        if not CircuitBreaker.check(name):
            return {"status": "skipped_circuit_breaker", "message": f"Source '{name}' is temporarily paused due to consecutive failures."}
        try:
            res = func(query_param, force_refresh=force_refresh)
            # Check if it returned error
            if isinstance(res, dict) and res.get("status") == "error":
                CircuitBreaker.record_failure(name)
            else:
                CircuitBreaker.record_success(name)
            return res
        except Exception as e:
            logger.error(f"Error executing source '{name}': {str(e)}")
            CircuitBreaker.record_failure(name)
            return {"status": "error", "message": str(e)}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {}
        for name, func in necessary_to_run.items():
            # For whois and wayback, query is domain; for others, it is company_name
            query_param = domain if name in ["whois", "wayback"] else company_name
            futures[name] = executor.submit(run_source, name, func, query_param)

        for name, future in futures.items():
            necessary_results[name] = future.result()

    # 2. Evaluate heuristics for Conditional Sources
    triggered_conditionals = []

    # Heuristic A: If courtlistener or sec_edgar return "found" with litigation/filings -> activate sec_litigation and ftc_enforcement
    cl_found = necessary_results.get("courtlistener", {}).get("status") == "found"
    sec_found = necessary_results.get("sec_edgar", {}).get("status") == "found"
    if cl_found or sec_found:
        reason = "Litigation records or SEC filings detected in necessary search phase."
        triggered_conditionals.append(("sec_litigation", reason))
        triggered_conditionals.append(("ftc_enforcement", reason))

    # Heuristic B: If scraped_text contains fintech-related keywords -> activate cfpb_complaints
    fintech_keywords = ["fintech", "payments", "lending", "banking", "pagos", "préstamos", "banca"]
    if any(keyword in scraped_text.lower() for keyword in fintech_keywords):
        reason = "Fintech or payment-related keywords identified in scraped website content."
        triggered_conditionals.append(("cfpb_complaints", reason))

    # Heuristic C: If domain does not end in .com/.us/.io OR scraped_text mentions countries outside US -> activate wipo_brands
    non_us_domain = not any(domain.endswith(ext) for ext in [".com", ".us", ".io"])
    non_us_keywords = ["spain", "mexico", "colombia", "españa", "uk", "london", "europe", "méxico", "reino unido", "canadá", "brazil"]
    has_non_us_keywords = any(k in scraped_text.lower() for k in non_us_keywords)
    if non_us_domain or has_non_us_keywords:
        reason = "Non-US domain extension or references to foreign regions found."
        triggered_conditionals.append(("wipo_brands", reason))

    # Heuristic D: If domain contains .co.uk OR scraped_text mentions UK/London -> activate uk_companies_house
    uk_domain = ".co.uk" in domain
    uk_keywords = ["united kingdom", "reino unido", "london", "londres"]
    has_uk_keywords = any(k in scraped_text.lower() for k in uk_keywords)
    if uk_domain or has_uk_keywords:
        reason = "UK domain or United Kingdom references detected."
        triggered_conditionals.append(("uk_companies_house", reason))

    # Heuristic E: If whois.creation_date differs by > 2 years from any "founded"/"fundada en" year in scraped_text -> activate wayback
    whois_date = necessary_results.get("whois", {}).get("creation_date")
    if whois_date:
        # Extract 4-digit year from WHOIS creation date
        whois_match = re.search(r'\b(19\d{2}|20\d{2})\b', whois_date)
        if whois_match:
            whois_year = int(whois_match.group(1))
            # Search scraped_text for years near founded words
            founded_pattern = re.compile(
                r'(?:founded|fundada|est\.|creada|inicio|desde|constituted|incorporated|since)[^.\n]{0,30}\b(19\d{2}|20\d{2})\b',
                re.IGNORECASE
            )
            scraped_years = [int(yr) for yr in founded_pattern.findall(scraped_text)]
            if scraped_years:
                diffs = [abs(whois_year - yr) for yr in scraped_years]
                if any(d > 2 for d in diffs):
                    reason = f"Mismatch of >2 years between WHOIS registration ({whois_year}) and declared founded year(s) {scraped_years}."
                    triggered_conditionals.append(("wayback", reason))

    # Heuristic F: If courtlistener, sec_litigation, or ofac returns status "found" -> activate gdelt_news
    cl_found_now = necessary_results.get("courtlistener", {}).get("status") == "found"
    ofac_found_now = necessary_results.get("ofac", {}).get("status") == "found"
    # We also check if sec_litigation is already triggered
    sec_lit_triggered = any(tc[0] == "sec_litigation" for tc in triggered_conditionals)
    if cl_found_now or ofac_found_now or sec_lit_triggered:
        reason = "Potential litigation, regulatory issues, or sanctions found in primary analysis."
        triggered_conditionals.append(("gdelt_news", reason))

    # 3. Incorporate user explicit overrides
    for cond_name in CONDITIONAL_SOURCES.keys():
        if user_enabled_sources and cond_name in user_enabled_sources:
            # Check if already triggered, otherwise force-enable it
            if not any(tc[0] == cond_name for tc in triggered_conditionals):
                triggered_conditionals.append((cond_name, "Forced by user preference setting overrides."))

    # Deduplicate triggered conditionals
    triggered_dict = {}
    for s_name, r_reason in triggered_conditionals:
        triggered_dict[s_name] = r_reason

    # Execute Active Conditional Sources concurrently
    conditional_results = {}
    if triggered_dict:
        with ThreadPoolExecutor(max_workers=3) as executor:
            cond_futures = {}
            for name in triggered_dict.keys():
                func = CONDITIONAL_SOURCES[name]
                query_param = domain if name in ["whois", "wayback"] else company_name
                cond_futures[name] = executor.submit(run_source, name, func, query_param)

            for name, future in cond_futures.items():
                conditional_results[name] = future.result()

    # Consolidate triggered list for explanation
    triggered_list_explained = []
    for name, reason in triggered_dict.items():
        triggered_list_explained.append({
            "source": name,
            "reason": reason
        })

    # Combine all results
    combined_results = {}
    combined_results.update(necessary_results)

    # Fill non-executed conditional sources with descriptive "not_triggered" dicts
    for name in CONDITIONAL_SOURCES.keys():
        if name in conditional_results:
            combined_results[name] = conditional_results[name]
        else:
            combined_results[name] = {
                "status": "not_triggered",
                "message": "Source was not triggered because heuristics did not apply and user preference did not override."
            }

    combined_results["triggered_conditional_sources"] = triggered_list_explained
    return combined_results

def search_founders_and_team(
    company_name: str,
    scraped_text: str,
    search_results: list = None
) -> list:
    """
    Searches for and identifies the name of the founder/CEO and executive team
    using scraped website content and search results. Saves: name, role, LinkedIn URL.
    Does NOT store photos of people.
    """
    found_people = []
    seen_linkedins = set()

    # Process DuckDuckGo/LinkedIn search results if available
    if search_results and isinstance(search_results, list):
        for r in search_results:
            link = r.get("link", "") or ""
            title = r.get("title", "") or ""
            snippet = r.get("snippet", "") or ""

            # Check for individual LinkedIn profile
            if "linkedin.com/in/" in link.lower():
                clean_link = link.split("?")[0].split("#")[0]
                if clean_link in seen_linkedins:
                    continue
                seen_linkedins.add(clean_link)

                name = ""
                role = "Executive"

                # Split title by usual delimiters to extract name and role
                parts = re.split(r'\s+[\-\|–]\s+', title)
                if parts:
                    candidate_name = parts[0].strip()
                    # Ensure candidate name isn't just the company name
                    if len(candidate_name) > 2 and company_name.lower() not in candidate_name.lower():
                        name = candidate_name

                    # Search for role in other title parts
                    for part in parts[1:]:
                        part_clean = part.lower()
                        if any(kw in part_clean for kw in ["founder", "ceo", "cto", "co-founder", "cfo", "director", "vp", "president", "lead", "manager", "head", "fundador", "fundadora"]):
                            role = part.strip()
                            role = re.sub(r'\s*[\-\|]\s*LinkedIn.*$', '', role, flags=re.IGNORECASE).strip()
                            break

                # Fallback to URL path for name if title extraction failed or was too short
                if not name:
                    match = re.search(r'/in/([a-zA-Z0-9\-–_]+)', clean_link)
                    if match:
                        name = match.group(1).replace("-", " ").replace("_", " ").title()

                # Clean name if it contains "LinkedIn" or generic strings
                if name:
                    name = re.sub(r'\b(?:linkedin|profile|perfil|on linkedin)\b.*$', '', name, flags=re.IGNORECASE).strip()

                if name and company_name.lower() not in name.lower():
                    found_people.append({
                        "name": name,
                        "role": role,
                        "linkedin_url": clean_link
                    })

    # Fallback to scraping team info directly from website text if few people found
    if len(found_people) < 3 and scraped_text:
        # Look for typical executive/founder patterns
        patterns = [
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\s*,\s*(?:CEO|CTO|Founder|Co-Founder|CFO|Director|CEO y Fundador|Fundador)\b',
            r'(?:CEO|CTO|Founder|Co-Founder|CFO|Director|Fundador|Fundadora)\s+(?:de|and CEO of)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})'
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, scraped_text):
                name = match.group(1).strip()
                # Exclude common noise words
                if not any(w in name.lower() for w in ["the", "this", "our", "we", "company", "startup", "venture", "team", "about", "pricing", "product"]):
                    # Deduplicate by name
                    if not any(p["name"].lower() == name.lower() for p in found_people):
                        matched_str = match.group(0).lower()
                        role = "Executive / Team Member"
                        if "ceo" in matched_str:
                            role = "CEO & Founder"
                        elif "cto" in matched_str:
                            role = "CTO"
                        elif "founder" in matched_str or "fundador" in matched_str:
                            role = "Founder"

                        found_people.append({
                            "name": name,
                            "role": role,
                            "linkedin_url": None
                        })

    return found_people
