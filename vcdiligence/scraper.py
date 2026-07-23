import os
import re
import json
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from playwright.sync_api import sync_playwright
from vcdiligence.logging_config import logger

class SmartScraper:
    @staticmethod
    def get_domain(url):
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    @staticmethod
    def clean_text(text):
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    @classmethod
    def scrape_with_requests(cls, url):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
            }
            response = requests.get(url, headers=headers, timeout=12)
            if response.status_code != 200:
                logger.warning(f"Requests scrape failed with HTTP {response.status_code} for {url}")
                return None

            soup = BeautifulSoup(response.text, "html.parser")
            for script_or_style in soup(["script", "style", "nav", "footer"]):
                script_or_style.decompose()

            cleaned = cls.clean_text(soup.get_text())
            if len(cleaned) < 300:
                logger.warning(f"Requests scrape returned very short content ({len(cleaned)} chars) for {url}")
                return None
            return cleaned
        except Exception as e:
            logger.error(f"Error scraping with requests on {url}: {str(e)}")
            return None

    @classmethod
    def scrape_with_playwright(cls, url):
        logger.info(f"Using Playwright headless fallback for {url}")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                # Create a context with custom User-Agent
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                page.goto(url, timeout=20000, wait_until="load")
                # Wait 1s for any dynamically-rendered text
                page.wait_for_timeout(1000)
                content = page.content()
                browser.close()

                soup = BeautifulSoup(content, "html.parser")
                for script_or_style in soup(["script", "style", "nav", "footer"]):
                    script_or_style.decompose()

                cleaned = cls.clean_text(soup.get_text())
                if len(cleaned) < 100:
                    return f"[Could not verify content for {url} - page load returned insufficient text]"
                return cleaned
        except Exception as e:
            logger.error(f"Playwright fallback also failed for {url}: {str(e)}")
            return f"[Could not verify content for {url} due to connection error or security block]"

    @classmethod
    def scrape_url(cls, url):
        # First try requests
        text = cls.scrape_with_requests(url)
        if text:
            return text
        # If requests fails or returns very short text, try Playwright
        return cls.scrape_with_playwright(url)

    @classmethod
    def get_internal_links(cls, base_url):
        links = set()
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
            }
            # Attempt to fetch links using requests, fallback to Playwright if needed
            response = requests.get(base_url, headers=headers, timeout=10)
            html = response.text if response.status_code == 200 else ""
            if not html or len(html) < 2000:
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        page = browser.new_page()
                        page.goto(base_url, timeout=15000, wait_until="load")
                        html = page.content()
                        browser.close()
                except Exception:
                    pass

            if html:
                soup = BeautifulSoup(html, "html.parser")
                domain = cls.get_domain(base_url)
                for anchor in soup.find_all("a", href=True):
                    href = anchor["href"]
                    full_url = urljoin(base_url, href)
                    parsed_full = urlparse(full_url)
                    full_domain = parsed_full.netloc
                    if full_domain.startswith("www."):
                        full_domain = full_domain[4:]

                    if full_domain == domain:
                        path_lower = parsed_full.path.lower()
                        if any(kw in path_lower for kw in ["about", "team", "pricing", "product", "features", "career", "contact"]):
                            links.add(full_url)
        except Exception as e:
            logger.error(f"Error getting internal links for {base_url}: {str(e)}")
        return list(links)[:4]

    @classmethod
    def search_duckduckgo(cls, query, count=3):
        results = []
        try:
            with DDGS() as ddgs:
                for result in ddgs.text(query, max_results=count):
                    results.append({
                        "title": result.get("title", ""),
                        "link": result.get("href", ""),
                        "snippet": result.get("body", "")
                    })
        except Exception as e:
            logger.error(f"DuckDuckGo search error for query '{query}': {str(e)}")

        # If absolutely no results, return explicit trace to prevent LLM assuming details
        if not results:
            return [{"title": "No public search results", "link": "", "snippet": f"[No public search records found under specific query: {query}]"}]
        return results

    @classmethod
    def analyze_startup(cls, url):
        domain = cls.get_domain(url)
        cache_dir = os.path.join(os.path.dirname(__file__), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"{domain}.json")

        # Check local cache first
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as file:
                    return json.load(file)
            except Exception:
                pass

        logger.info(f"Starting analysis for startup: {url}")
        homepage_content = cls.scrape_url(url)
        company_name = domain.split('.')[0].capitalize()

        internal_content = {}
        internal_links = cls.get_internal_links(url)
        for link in internal_links:
            link_path = urlparse(link).path
            internal_content[link_path] = cls.scrape_url(link)[:1500]

        # Explicitly record missing sub-pages so Omission Analyst is aware
        expected_keywords = ["pricing", "team", "about", "features"]
        found_keywords = [kw for kw in expected_keywords if any(kw in path.lower() for path in internal_content.keys())]
        for kw in expected_keywords:
            if kw not in found_keywords:
                internal_content[f"/{kw}-missing-page"] = f"[Could not verify {kw} details: no dedicated /{kw} page found or loaded]"

        ddg_results = {}
        search_queries = {
            "competitors": f"{company_name} competitors alternative SaaS",
            "team_and_founders": f"{company_name} founders team LinkedIn",
            "market_and_funding": f"{company_name} Crunchbase funding traction",
            "pricing_and_product": f"{company_name} pricing product reviews"
        }

        for category, query in search_queries.items():
            ddg_results[category] = cls.search_duckduckgo(query)

        analysis_payload = {
            "company_name": company_name,
            "company_url": url,
            "homepage_summary": homepage_content[:3000],
            "internal_pages": internal_content,
            "search_insights": ddg_results
        }

        try:
            with open(cache_path, "w", encoding="utf-8") as file:
                json.dump(analysis_payload, file, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return analysis_payload
