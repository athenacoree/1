import unittest
from fastapi import HTTPException
from vcdiligence.validator import validate_url_for_ssrf

class TestValidatorSSRF(unittest.TestCase):
    def test_localhost_and_loopback_blocked(self):
        blocked_urls = [
            "http://localhost",
            "https://127.0.0.1",
            "http://127.0.0.2",
            "http://[::1]",
            "http://192.168.1.1",
            "http://10.0.0.1"
        ]
        for url in blocked_urls:
            with self.assertRaises(HTTPException) as ctx:
                validate_url_for_ssrf(url)
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertTrue("private or local IP" in ctx.exception.detail or "Could not resolve" in ctx.exception.detail)

    def test_public_url_allowed(self):
        allowed_urls = [
            "https://stripe.com",
            "http://google.com"
        ]
        for url in allowed_urls:
            try:
                res = validate_url_for_ssrf(url)
                self.assertTrue(res.startswith("http"))
            except HTTPException as e:
                self.fail(f"Public URL {url} should have been allowed, failed with {e.detail}")

if __name__ == "__main__":
    unittest.main()
