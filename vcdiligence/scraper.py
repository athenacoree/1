import os
import re
import json
import requests
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

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
    def scrape_url(cls, url):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
            }
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                return f"Failed to retrieve URL: HTTP {response.status_code}"

            soup = BeautifulSoup(response.text, "html.parser")
            for script_or_style in soup(["script", "style", "nav", "footer"]):
                script_or_style.decompose()

            return cls.clean_text(soup.get_text())
        except Exception as e:
            return f"Error scraping {url}: {str(e)}"

    @classmethod
    def get_internal_links(cls, base_url):
        links = set()
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
            }
            response = requests.get(base_url, headers=headers, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
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
        except Exception:
            pass
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
        except Exception:
            pass
        return results

    @classmethod
    def analyze_startup(cls, url):
        domain = cls.get_domain(url)
        cache_dir = os.path.join(os.path.dirname(__file__), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, f"{domain}.json")

        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as file:
                    return json.load(file)
            except Exception:
                pass

        homepage_content = cls.scrape_url(url)
        company_name = domain.split('.')[0].capitalize()

        internal_content = {}
        internal_links = cls.get_internal_links(url)
        for link in internal_links:
            link_path = urlparse(link).path
            internal_content[link_path] = cls.scrape_url(link)[:1500]

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
