import os
os.environ["JWT_SECRET"] = "test-secret-value-dealscout-2026-minimum-length-32-chars-long"

import unittest
from unittest import mock
from fastapi.testclient import TestClient

from vcdiligence.app import app
from vcdiligence.database import SessionLocal, init_db, Organization, User, Report, ReportChange, Decision, PrecisionBenchmark
from vcdiligence.security import hash_password, create_access_token
from vcdiligence.celery_app import celery_app

class TestNewFeatures(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = TestClient(app)
        self.db = SessionLocal()

        # Create/find organization and user
        self.org = self.db.query(Organization).filter_by(id=1).first()
        if not self.org:
            self.org = Organization(id=1, company_name="DealScout Capital")
            self.db.add(self.org)
            self.db.commit()

        # Analyst User
        self.analyst = self.db.query(User).filter_by(email="analyst@dealscout.ai").first()
        if not self.analyst:
            self.analyst = User(
                email="analyst@dealscout.ai",
                hashed_password=hash_password("analystpassword"),
                role="analista",
                organization_id=1
            )
            self.db.add(self.analyst)
            self.db.commit()

        # Admin User
        self.admin = self.db.query(User).filter_by(email="admin_test@dealscout.ai").first()
        if not self.admin:
            self.admin = User(
                email="admin_test@dealscout.ai",
                hashed_password=hash_password("adminpassword"),
                role="administrador",
                organization_id=1
            )
            self.db.add(self.admin)
            self.db.commit()

        # Generate tokens
        self.analyst_token = create_access_token({"sub": "analyst@dealscout.ai"})
        self.admin_token = create_access_token({"sub": "admin_test@dealscout.ai"})

        # Setup dummy report
        self.report = self.db.query(Report).filter_by(domain="test_features.com", organization_id=1).first()
        if not self.report:
            self.report = Report(
                domain="test_features.com",
                company_name="Test Features",
                url="https://test_features.com",
                score=80,
                sub_scores={"market": 85, "team": 80, "product": 75, "traction": 70, "risk_legal_omissions": 90},
                recommendation="GO",
                report_md="# Test Memo",
                organization_id=1
            )
            self.db.add(self.report)
            self.db.commit()

    def tearDown(self):
        # Clear database records added during test
        self.db.query(Decision).filter_by(organization_id=1).delete()
        self.db.query(ReportChange).delete()
        self.db.query(PrecisionBenchmark).delete()
        if self.report:
            self.db.delete(self.report)
        self.db.commit()
        self.db.close()

    def test_celery_configuration(self):
        """Verify Celery registers tasks and defaults to task_always_eager when no REDIS_URL exists."""
        self.assertTrue(celery_app.conf.task_always_eager)
        self.assertIn("vcdiligence.tasks.run_due_diligence_task", celery_app.tasks)

    def test_monitoring_endpoints(self):
        """Verify we can configure monitoring settings and get monitoring history."""
        headers = {"Authorization": f"Bearer {self.analyst_token}"}

        # Configure monitoring
        resp = self.client.post("/reports/test_features.com/monitoring", json={
            "enabled": True,
            "interval_days": 10
        }, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["monitoring_enabled"])
        self.assertEqual(resp.json()["monitoring_interval_days"], 10)

        # Get monitoring history (empty changes initially)
        resp = self.client.get("/reports/test_features.com/monitoring", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["monitoring_enabled"])
        self.assertEqual(len(resp.json()["changes"]), 0)

        # Add a dummy change manually and verify retrieval
        change = ReportChange(
            report_id=self.report.id,
            change_type="score_change",
            description="Overall score went from 80 to 85",
            old_value="80",
            new_value="85"
        )
        self.db.add(change)
        self.db.commit()

        resp = self.client.get("/reports/test_features.com/monitoring", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["changes"]), 1)
        self.assertEqual(resp.json()["changes"][0]["change_type"], "score_change")

    def test_decision_and_stats_endpoints(self):
        """Verify decision registration, stats, and weight calibration."""
        headers = {"Authorization": f"Bearer {self.analyst_token}"}

        # Post decision
        resp = self.client.post("/reports/test_features.com/decision", json={
            "decision": "invertimos",
            "notas": "Very high traccion and product fit."
        }, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["decision"], "invertimos")

        # Get stats
        resp = self.client.get("/organizations/1/decision-stats", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total_decisions"], 1)
        self.assertIn("calibrated_weights", resp.json())
        self.assertIn("market", resp.json()["calibrated_weights"])

    def test_precision_benchmark_admin_only(self):
        """Verify benchmark scorecard is restricted to administrator."""
        analyst_headers = {"Authorization": f"Bearer {self.analyst_token}"}
        admin_headers = {"Authorization": f"Bearer {self.admin_token}"}

        # Add a dummy benchmark
        bench = PrecisionBenchmark(
            startup_name="Known Startup",
            url="https://known.com",
            score=90,
            recommendation="GO",
            known_outcome="success",
            matched=True
        )
        self.db.add(bench)
        self.db.commit()

        # Analyst request -> Forbidden
        resp = self.client.get("/admin/benchmark", headers=analyst_headers)
        self.assertEqual(resp.status_code, 403)

        # Admin request -> Success
        resp = self.client.get("/admin/benchmark", headers=admin_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)
        self.assertEqual(resp.json()[0]["startup_name"], "Known Startup")

    @mock.patch("vcdiligence.public_apis.requests.get")
    def test_force_refresh_public_apis(self, mock_get):
        """Verify that force_refresh = True bypasses get_cached_response."""
        from vcdiligence.public_apis import (
            search_sec_edgar,
            get_cached_response,
            set_cached_response
        )
        # Mock requests.get response
        mock_resp = mock.MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"0": {"cik_str": "123456", "title": "TestCompany"}}
        mock_get.return_value = mock_resp

        # Pre-seed cache with dummy data
        set_cached_response("sec_edgar", "TestCompany", {"status": "found", "cik": "999999", "name": "Cached Company"})

        # Call with force_refresh=False (should return cached data)
        res_cached = search_sec_edgar("TestCompany", force_refresh=False)
        self.assertEqual(res_cached.get("cik"), "999999")

        # Call with force_refresh=True (should bypass cache and call live API)
        res_fresh = search_sec_edgar("TestCompany", force_refresh=True)
        self.assertEqual(res_fresh.get("cik"), "0000123456")

    def test_merge_devils_advocate_logic(self):
        """Verify that merge_devils_advocate merges business report and counter-arguments correctly."""
        from vcdiligence.parser import merge_devils_advocate

        business_report = (
            "INVESTMENT_SCORE: 85\n"
            "RECOMMENDATION: GO\n"
            "SUB_SCORES: {\"market\": 80, \"team\": 80, \"product\": 80, \"traction\": 80, \"risk_legal_omissions\": 80}\n"
            "\n"
            "# Executive Summary\n"
            "We believe this is a strong investment."
        )
        devils_section = (
            "# Caso a Favor vs. Caso en Contra\n"
            "Here is the counter-argument about lack of clear target market."
        )

        merged = merge_devils_advocate(business_report, devils_section)

        # Check that top lines are preserved
        self.assertTrue(merged.startswith("INVESTMENT_SCORE: 85"))
        self.assertIn("RECOMMENDATION: GO", merged)
        self.assertIn("## Caso a Favor vs. Caso en Contra", merged)
        self.assertIn("Here is the counter-argument", merged)
        self.assertIn("# Executive Summary", merged)

    @mock.patch("vcdiligence.llm_manager.LLMProviderManager.get_llm")
    def test_crew_task_callback(self, mock_get_llm):
        """Verify that task_callback parameter is supported and executed after business_analyst_task."""
        from vcdiligence.crew import MarketResearchCrew
        from crewai import LLM
        mock_get_llm.return_value = (LLM(model="openai/gpt-4o-mini", api_key="dummy"), "openai")

        callback_called = False
        def dummy_callback(task_output):
            nonlocal callback_called
            callback_called = True

        crew_obj = MarketResearchCrew(task_callback=dummy_callback)
        self.assertEqual(crew_obj.task_callback, dummy_callback)

        tasks = crew_obj.crew().tasks
        business_task = [t for t in tasks if t.callback == dummy_callback][0]
        self.assertEqual(business_task.callback, dummy_callback)


if __name__ == "__main__":
    unittest.main()
