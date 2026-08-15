import os
os.environ["JWT_SECRET"] = "test-secret-value-dealscout-2026-minimum-length-32-chars-long"

import unittest
from unittest import mock
from fastapi.testclient import TestClient

from vcdiligence.app import app
from vcdiligence.database import SessionLocal, init_db, Organization, User, Report, ReportChange, Decision, PrecisionBenchmark, Task
from vcdiligence.security import hash_password, create_access_token

class TestNewFeatures(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = TestClient(app)
        self.db = SessionLocal()

        # Create/find organization and user
        self.org = self.db.query(Organization).filter_by(id=1).first()
        if not self.org:
            self.org = Organization(id=1, company_name="VerdictIQ Capital")
            self.db.add(self.org)
            self.db.commit()

        # Analyst User
        self.analyst = self.db.query(User).filter_by(email="analyst@verdictiq.ai").first()
        if not self.analyst:
            self.analyst = User(
                email="analyst@verdictiq.ai",
                hashed_password=hash_password("analystpassword"),
                role="analista",
                organization_id=1
            )
            self.db.add(self.analyst)
            self.db.commit()
        else:
            self.analyst.hashed_password = hash_password("analystpassword")
            self.db.commit()

        # Admin User
        self.admin = self.db.query(User).filter_by(email="admin_test@verdictiq.ai").first()
        if not self.admin:
            self.admin = User(
                email="admin_test@verdictiq.ai",
                hashed_password=hash_password("adminpassword"),
                role="administrador",
                organization_id=1
            )
            self.db.add(self.admin)
            self.db.commit()

        # Generate tokens
        self.analyst_token = create_access_token({"sub": "analyst@verdictiq.ai"})
        self.admin_token = create_access_token({"sub": "admin_test@verdictiq.ai"})

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
        from vcdiligence.database import Testimonial, ErrorReport
        self.db.query(Decision).filter_by(organization_id=1).delete()
        self.db.query(ReportChange).delete()
        self.db.query(PrecisionBenchmark).delete()
        self.db.query(Testimonial).delete()
        self.db.query(ErrorReport).delete()
        self.db.query(User).filter(User.email.in_(["director@spacex.com", "partner@stripe.com"])).delete()
        self.db.query(Organization).filter(Organization.company_name.in_(["SpaceX Inc", "Stripe Inc"])).delete()
        self.db.query(Task).delete()
        if self.report:
            try:
                self.db.delete(self.report)
            except Exception:
                pass
        self.db.commit()
        self.db.close()

    @mock.patch("vcdiligence.app.BackgroundTasks.add_task")
    def test_background_tasks_flow(self, mock_add_task):
        """Verify that /analyze endpoint triggers FastAPI BackgroundTasks instead of Celery."""
        headers = {"Authorization": f"Bearer {self.analyst_token}"}
        resp = self.client.post("/analyze", json={
            "url": "https://newstartup.com",
            "notify_email": "test@notify.com"
        }, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "running")
        self.assertTrue(mock_add_task.called)

        # Verify that task was created in DB with starting status
        task = self.db.query(Task).filter_by(id="1_newstartup.com").first()
        self.assertIsNotNone(task)
        self.assertEqual(task.status, "starting")
        self.assertEqual(task.progress, 5)
        self.db.delete(task)
        self.db.commit()

    @mock.patch("vcdiligence.app.BackgroundTasks.add_task")
    def test_language_selection_flow(self, mock_add_task):
        """Verify that /analyze endpoint accepts custom language and saves it to Task."""
        headers = {"Authorization": f"Bearer {self.analyst_token}"}
        resp = self.client.post("/analyze", json={
            "url": "https://example.com",
            "notify_email": "test@notify.com",
            "language": "en"
        }, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "running")
        self.assertTrue(mock_add_task.called)

        # Verify that task was created in DB with language 'en'
        task = self.db.query(Task).filter_by(id="1_example.com").first()
        self.assertIsNotNone(task)
        self.assertEqual(task.status, "starting")
        self.assertEqual(task.language, "en")
        self.db.delete(task)
        self.db.commit()

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

    @mock.patch("vcdiligence.scraper.SmartScraper.search_duckduckgo")
    def test_search_company_endpoint(self, mock_ddg):
        """Verify that /search-company returns search candidates successfully."""
        headers = {"Authorization": f"Bearer {self.analyst_token}"}
        mock_ddg.return_value = [
            {"title": "Stripe | Official Site", "link": "https://stripe.com", "body": "Payments infrastructure"}
        ]
        resp = self.client.post("/search-company", json={"company_name": "Stripe"}, headers=headers)
        self.assertEqual(resp.status_code, 200)
        options = resp.json()["options"]
        self.assertTrue(len(options) >= 1)
        self.assertEqual(options[0]["domain"], "stripe.com")

    @mock.patch("vcdiligence.app.BackgroundTasks.add_task")
    @mock.patch("vcdiligence.scraper.SmartScraper.extract_text_from_pdf")
    def test_analyze_upload_pdf(self, mock_extract, mock_add_task):
        """Verify that uploading a pitch deck PDF triggers background tasks and extracts URLs."""
        headers = {"Authorization": f"Bearer {self.analyst_token}"}
        mock_extract.return_value = "Check out our website at airbnb.com or contacts us."

        # Create a dummy PDF bytes content
        import io
        pdf_file = io.BytesIO(b"%PDF-1.4 dummy content")

        resp = self.client.post(
            "/analyze/upload",
            headers=headers,
            files={"pitch_deck": ("deck.pdf", pdf_file, "application/pdf")},
            data={"notify_email": "pitch@test.com"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "running")
        self.assertTrue(mock_add_task.called)

    @mock.patch("vcdiligence.app.BackgroundTasks.add_task")
    @mock.patch("vcdiligence.scraper.SmartScraper.scrape_linkedin")
    def test_analyze_linkedin_only(self, mock_linkedin, mock_add_task):
        """Verify that starting analysis with only a LinkedIn URL infers website and runs task."""
        headers = {"Authorization": f"Bearer {self.analyst_token}"}
        mock_linkedin.return_value = {
            "linkedin_data": "Stripe is a payments company founded in...",
            "inferred_url": "https://stripe.com",
            "company_name": "stripe"
        }
        resp = self.client.post("/analyze", json={
            "linkedin_url": "https://www.linkedin.com/company/stripe",
            "notify_email": "linkedin@test.com"
        }, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "running")
        self.assertTrue(mock_add_task.called)

    def test_opt_in_privacy_testimonials(self):
        """Verify that feedback comment defaults to strict opt-in privacy, making nothing public without active consent."""
        headers = {"Authorization": f"Bearer {self.analyst_token}"}

        # Submit comment-only feedback with default opt-out values (all False)
        resp = self.client.post("/testimonials", data={
            "comment": "Totally confidential feedback!",
            "share_comment": "false",
            "share_photo": "false",
            "share_name": "false"
        }, headers=headers)
        self.assertEqual(resp.status_code, 200)

        # Confirm nothing is public
        pub_resp = self.client.get("/testimonials")
        self.assertEqual(pub_resp.status_code, 200)
        self.assertEqual(len(pub_resp.json()), 0)

        # Submit with opt-in share comment but anonymous name/photo
        resp2 = self.client.post("/testimonials", data={
            "comment": "I want to share my thoughts anonymously!",
            "share_comment": "true",
            "share_photo": "false",
            "share_name": "false"
        }, headers=headers)
        self.assertEqual(resp2.status_code, 200)

        pub_resp2 = self.client.get("/testimonials")
        self.assertEqual(len(pub_resp2.json()), 1)
        self.assertEqual(pub_resp2.json()[0]["user_name"], "Anonymous User")
        self.assertIsNone(pub_resp2.json()[0]["profile_photo_path"])

    @mock.patch.dict(os.environ, {"MIN_USERS_TO_SHOW_STATS": "15"})
    def test_stats_threshold(self):
        """Verify statistics hide when total registered users are below MIN_USERS_TO_SHOW_STATS."""
        # Total registered users in setUp is 3 (seeded admin, test analyst, test admin)
        resp = self.client.get("/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["show_stats"])
        self.assertIn("hidden", resp.json()["message"])

        # Change threshold dynamically using mock to 2
        with mock.patch.dict(os.environ, {"MIN_USERS_TO_SHOW_STATS": "2"}):
            resp_show = self.client.get("/stats")
            self.assertEqual(resp_show.status_code, 200)
            self.assertTrue(resp_show.json()["show_stats"])
            self.assertTrue(resp_show.json()["total_users"] >= 2)

    def test_automated_domain_verification(self):
        """Verify register endpoint and profile update trigger automated domain matching for company accounts."""
        # Register a company account with matching email/website domain
        resp_reg = self.client.post("/register", json={
            "email": "director@spacex.com",
            "password": "spacexpassword",
            "account_type": "empresa",
            "company_name": "SpaceX Inc",
            "company_website": "https://spacex.com"
        })
        self.assertEqual(resp_reg.status_code, 200)
        self.assertTrue(resp_reg.json()["user"]["verified_domain"])

        token = resp_reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Update company website to a non-matching domain -> verify_domain becomes False
        resp_update = self.client.post("/profile/update", data={
            "company_website": "https://blueorigin.com"
        }, headers=headers)
        self.assertEqual(resp_update.status_code, 200)
        self.assertFalse(resp_update.json()["verified_domain"])

    def test_admin_config_validation(self):
        """Verify that updating config validates the key against CONFIG_REGISTRY."""
        admin_headers = {"Authorization": f"Bearer {self.admin_token}"}
        analyst_headers = {"Authorization": f"Bearer {self.analyst_token}"}

        # 1. Non-admin user tries to access -> 403 Forbidden
        resp_analyst = self.client.post("/admin/config", data={"key": "platform_name", "value": "New Scout"}, headers=analyst_headers)
        self.assertEqual(resp_analyst.status_code, 403)

        # 2. Admin tries to update valid key -> 200 Success
        resp_valid = self.client.post("/admin/config", data={"key": "platform_name", "value": "VerdictIQ Pro"}, headers=admin_headers)
        self.assertEqual(resp_valid.status_code, 200)
        self.assertEqual(resp_valid.json()["value"], "VerdictIQ Pro")

        # 3. Admin tries to update invalid/arbitrary key -> 400 Bad Request
        resp_invalid = self.client.post("/admin/config", data={"key": "arbitrary_evil_key", "value": "hack"}, headers=admin_headers)
        self.assertEqual(resp_invalid.status_code, 400)
        self.assertIn("no es una de las conocidas en el CONFIG_REGISTRY", resp_invalid.json()["detail"])

    def test_user_audit_logs(self):
        """Verify GET /me/audit-logs retrieves logs with multi-tenant isolation."""
        from vcdiligence.database import AuditLog
        analyst_headers = {"Authorization": f"Bearer {self.analyst_token}"}

        # 1. Populate log for Org 1
        log_record = AuditLog(
            user_id=self.analyst.id,
            user_email=self.analyst.email,
            organization_id=self.analyst.organization_id,
            action="test_isolated_action",
            target_company="Stripe Inc"
        )
        self.db.add(log_record)
        self.db.commit()

        # 2. Query endpoint -> Should return the record
        resp = self.client.get("/me/audit-logs", headers=analyst_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(len(resp.json()) >= 1)
        self.assertEqual(resp.json()[0]["action"], "test_isolated_action")
        self.assertEqual(resp.json()[0]["target_company"], "Stripe Inc")

        # 3. Query from isolated user in another org -> should NOT see Org 1 log
        other_user_token = create_access_token({"sub": "director@spacex.com"})
        other_user = User(
            email="director@spacex.com",
            hashed_password=hash_password("spacexpass"),
            role="analista",
            organization_id=999 # Isolated Org
        )
        self.db.add(other_user)
        self.db.commit()

        resp_isolated = self.client.get("/me/audit-logs", headers={"Authorization": f"Bearer {other_user_token}"})
        self.assertEqual(resp_isolated.status_code, 200)
        # Should be empty since SpaceX user has no actions yet
        self.assertEqual(len(resp_isolated.json()), 0)

        # Cleanup SpaceX user
        self.db.delete(other_user)
        self.db.delete(log_record)
        self.db.commit()

    def test_generate_hype_and_qa_logic(self):
        """Verify the rule-based and structure of generate_hype_and_qa helper."""
        from vcdiligence.parser import generate_hype_and_qa

        scraped_text = (
            "We are a pioneering and revolutionary company with a cutting-edge next-gen "
            "AI-powered solution. Our disruptive world-class SaaS is a total game-changer "
            "triggering a paradigm shift."
        )
        company_name = "HyperTech"

        # Test generation (will use fallback/rule-based locally since no live API keys are provided in tests)
        res = generate_hype_and_qa(scraped_text, company_name)

        self.assertIn("hype_score", res)
        self.assertTrue(res["hype_score"] > 20)
        self.assertTrue(len(res["detected_cliches"]) > 0)

        # Check specific detected cliché keys
        words_detected = [c["word"] for c in res["detected_cliches"]]
        self.assertIn("Next-Gen", words_detected)
        self.assertIn("AI-Powered", words_detected)
        self.assertIn("Disrupt", words_detected)

        # Check simulated questions
        self.assertTrue(len(res["simulated_questions"]) >= 3)
        self.assertIn("question", res["simulated_questions"][0])
        self.assertIn("answer", res["simulated_questions"][0])


if __name__ == "__main__":
    unittest.main()
