import unittest
from vcdiligence.scraper import SmartScraper

class TestSmartScraper(unittest.TestCase):
    def test_get_domain(self):
        self.assertEqual(SmartScraper.get_domain("https://stripe.com/abc"), "stripe.com")
        self.assertEqual(SmartScraper.get_domain("http://www.vcdiligence.com"), "vcdiligence.com")

    def test_scrape_and_playwright_fallback(self):
        # Scrape a real public page to verify both requests and playwright sync API
        url = "https://example.com"
        content = SmartScraper.scrape_url(url)
        self.assertIsNotNone(content)
        self.assertTrue(len(content) > 100)
        self.assertTrue("Example Domain" in content)

    def test_analyze_startup_structure(self):
        # Run analyze startup on example.com and verify payload contains omission blocks
        url = "https://example.com"
        payload = SmartScraper.analyze_startup(url)
        self.assertIn("company_name", payload)
        self.assertIn("homepage_summary", payload)
        self.assertIn("internal_pages", payload)

        # Check that missing expected sub-pages are explicitly identified
        internal_pages = payload["internal_pages"]
        has_pricing_missing = False
        for path, text in internal_pages.items():
            if "pricing-missing-page" in path:
                has_pricing_missing = True
                self.assertIn("Could not verify pricing details", text)
        self.assertTrue(has_pricing_missing)

if __name__ == "__main__":
    unittest.main()
