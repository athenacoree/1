import unittest
from vcdiligence.public_apis import (
    search_sec_edgar,
    search_opencorporates,
    search_uspto,
    search_courtlistener,
    query_github_repo,
    get_all_public_insights
)

class TestPublicAPIs(unittest.TestCase):
    def test_sec_edgar_stripe(self):
        # Let's search a well-known name
        res = search_sec_edgar("Stripe")
        self.assertIn("status", res)
        self.assertIsNotNone(res["status"])

    def test_opencorporates_stripe(self):
        res = search_opencorporates("Stripe")
        self.assertIn("status", res)

    def test_uspto_stripe(self):
        res = search_uspto("Stripe")
        self.assertIn("status", res)

    def test_courtlistener_stripe(self):
        res = search_courtlistener("Stripe")
        self.assertIn("status", res)

    def test_github_stripe(self):
        res = query_github_repo("Stripe")
        self.assertIn("status", res)

    def test_get_all_public_insights(self):
        insights = get_all_public_insights("Stripe")
        self.assertIn("sec_edgar", insights)
        self.assertIn("opencorporates", insights)
        self.assertIn("uspto", insights)
        self.assertIn("courtlistener", insights)
        self.assertIn("github", insights)

if __name__ == "__main__":
    unittest.main()
