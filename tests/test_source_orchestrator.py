import unittest
from unittest import mock
import datetime
from vcdiligence.source_orchestrator import run_orchestrated_analysis, CircuitBreaker, NECESSARY_SOURCES, CONDITIONAL_SOURCES

class TestSourceOrchestrator(unittest.TestCase):
    def setUp(self):
        # Reset circuit breaker before each test
        CircuitBreaker.consecutive_failures.clear()
        CircuitBreaker.paused_until.clear()

        # Backup original dicts
        self.orig_necessary = dict(NECESSARY_SOURCES)
        self.orig_conditional = dict(CONDITIONAL_SOURCES)

    def tearDown(self):
        # Restore original dicts
        NECESSARY_SOURCES.clear()
        NECESSARY_SOURCES.update(self.orig_necessary)
        CONDITIONAL_SOURCES.clear()
        CONDITIONAL_SOURCES.update(self.orig_conditional)

    def test_necessary_sources_run_by_default(self):
        mock_sec = mock.Mock(return_value={"status": "not_found"})
        mock_github = mock.Mock(return_value={"status": "not_found"})

        NECESSARY_SOURCES["sec_edgar"] = mock_sec
        NECESSARY_SOURCES["github"] = mock_github

        # Run orchestrated analysis with only "sec_edgar" and "github" in enabled sources to keep it simple and testable
        res = run_orchestrated_analysis("Stripe", "stripe.com", "SaaS", user_enabled_sources=["sec_edgar", "github"])

        mock_sec.assert_called_once()
        mock_github.assert_called_once()

    def test_necessary_sources_can_be_excluded_by_user(self):
        mock_sec = mock.Mock(return_value={"status": "not_found"})
        mock_github = mock.Mock(return_value={"status": "not_found"})

        NECESSARY_SOURCES["sec_edgar"] = mock_sec
        NECESSARY_SOURCES["github"] = mock_github

        # User only enables github, excluding sec_edgar
        res = run_orchestrated_analysis("Stripe", "stripe.com", "SaaS", user_enabled_sources=["github"])

        mock_sec.assert_not_called()
        mock_github.assert_called_once()

    def test_conditional_source_does_not_execute_if_heuristics_do_not_apply(self):
        mock_lit = mock.Mock(return_value={"status": "not_found"})
        CONDITIONAL_SOURCES["sec_litigation"] = mock_lit

        # Standard text, no heuristics, user only enabled sec_edgar (excluding conditional litigation)
        res = run_orchestrated_analysis("Stripe", "stripe.com", "Standard SaaS", user_enabled_sources=["sec_edgar"])

        mock_lit.assert_not_called()
        self.assertEqual(res["sec_litigation"]["status"], "not_triggered")

    def test_conditional_source_executes_if_explicitly_requested_by_user(self):
        mock_lit = mock.Mock(return_value={"status": "found"})
        CONDITIONAL_SOURCES["sec_litigation"] = mock_lit

        # Run with user override (forcing litigation)
        res = run_orchestrated_analysis("Stripe", "stripe.com", "Standard SaaS", user_enabled_sources=["sec_litigation"])

        mock_lit.assert_called_once()
        self.assertEqual(res["sec_litigation"]["status"], "found")

    def test_circuit_breaker_pauses_after_three_failures(self):
        for _ in range(3):
            CircuitBreaker.record_failure("test_source")
        self.assertFalse(CircuitBreaker.check("test_source"))

    def test_search_founders_and_team(self):
        from vcdiligence.source_orchestrator import search_founders_and_team

        search_results = [
            {"title": "Marlon Baez Mendez - Founder & CEO - DealScout AI | LinkedIn", "link": "https://www.linkedin.com/in/marlon-baez-mendez?foo=bar", "snippet": "... Marlon is the founder ..."},
            {"title": "Suresh Beekhani - Co-Founder & CTO - DealScout AI | LinkedIn", "link": "https://www.linkedin.com/in/suresh-beekhani", "snippet": "... Suresh ..."}
        ]
        scraped_text = "Nuestra empresa fue fundada por Marlon Baez Mendez, CEO y Fundador, y Suresh Beekhani, CTO."

        people = search_founders_and_team("DealScout AI", scraped_text, search_results)

        self.assertTrue(len(people) >= 2)
        self.assertEqual(people[0]["name"], "Marlon Baez Mendez")
        self.assertEqual(people[0]["role"], "Founder & CEO")
        self.assertEqual(people[0]["linkedin_url"], "https://www.linkedin.com/in/marlon-baez-mendez")
        self.assertEqual(people[1]["name"], "Suresh Beekhani")
        self.assertEqual(people[1]["role"], "Co-Founder & CTO")

if __name__ == "__main__":
    unittest.main()
