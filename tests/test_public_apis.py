import unittest
from unittest import mock
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

    @mock.patch("vcdiligence.public_apis.query_github_repo")
    @mock.patch("vcdiligence.public_apis.search_sec_edgar")
    @mock.patch("vcdiligence.public_apis.search_opencorporates")
    @mock.patch("vcdiligence.public_apis.search_uspto")
    @mock.patch("vcdiligence.public_apis.search_courtlistener")
    def test_get_all_public_insights_filtering(self, mock_cl, mock_uspto, mock_oc, mock_sec, mock_github):
        mock_github.return_value = {"status": "found"}
        mock_sec.return_value = {"status": "found"}

        # Call get_all_public_insights with sources=['github']
        insights = get_all_public_insights("Stripe", sources=["github"])

        # Only github should be called
        mock_github.assert_called_once_with("Stripe", force_refresh=False)
        mock_sec.assert_not_called()
        mock_oc.assert_not_called()
        mock_uspto.assert_not_called()
        mock_cl.assert_not_called()

        self.assertIn("github", insights)
        self.assertNotIn("sec_edgar", insights)

if __name__ == "__main__":
    unittest.main()
