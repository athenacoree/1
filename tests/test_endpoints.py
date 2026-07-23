import unittest
from unittest import mock
from fastapi.testclient import TestClient
from crewai import LLM
from vcdiligence.app import app
from vcdiligence.database import SessionLocal, init_db, User, Organization, Report
from vcdiligence.security import hash_password

class TestAppEndpoints(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = TestClient(app)
        self.db = SessionLocal()

        # Ensure test organization and users exist
        org = self.db.query(Organization).filter_by(id=1).first()
        if not org:
            org = Organization(id=1, company_name="DealScout Capital")
            self.db.add(org)
            self.db.commit()

        user = self.db.query(User).filter_by(email="analyst@dealscout.ai").first()
        if not user:
            user = User(
                email="analyst@dealscout.ai",
                hashed_password=hash_password("analystpassword"),
                role="analista",
                organization_id=1
            )
            self.db.add(user)
            self.db.commit()

    def tearDown(self):
        self.db.close()

    @mock.patch("vcdiligence.llm_manager.LLMProviderManager.get_llm")
    def test_health_endpoint(self, mock_get_llm):
        mock_get_llm.return_value = (LLM(model="openai/gpt-4o-mini", api_key="dummy"), "openai")
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_index_page(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("DealScout AI", resp.text)

    def test_login_success(self):
        resp = self.client.post("/login", json={
            "email": "analyst@dealscout.ai",
            "password": "analystpassword"
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access_token", resp.json())
        self.assertEqual(resp.json()["user"]["role"], "analista")

    def test_login_failure(self):
        resp = self.client.post("/login", json={
            "email": "analyst@dealscout.ai",
            "password": "wrongpassword"
        })
        self.assertEqual(resp.status_code, 401)

    def test_ssrf_blocked(self):
        # Authenticate first
        login_resp = self.client.post("/login", json={
            "email": "analyst@dealscout.ai",
            "password": "analystpassword"
        })
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Send localhost analysis request
        resp = self.client.post("/analyze", json={"url": "http://localhost"}, headers=headers)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Access to private or local IP address is prohibited", resp.json()["detail"])

    def test_pdf_download_with_query_token(self):
        # Authenticate
        login_resp = self.client.post("/login", json={
            "email": "analyst@dealscout.ai",
            "password": "analystpassword"
        })
        token = login_resp.json()["access_token"]

        # Insert a dummy report into db
        report = self.db.query(Report).filter_by(domain="test_domain.com", organization_id=1).first()
        if not report:
            report = Report(
                domain="test_domain.com",
                company_name="Test Company",
                url="https://test_domain.com",
                score=90,
                sub_scores={"market": 90, "team": 90, "product": 90, "traction": 90, "risk_legal_omissions": 90},
                recommendation="GO",
                report_md="# Investment Memo",
                pdf_path=None, # on the fly regeneration
                organization_id=1
            )
            self.db.add(report)
            self.db.commit()

        # Try to download using query token ?token=...
        resp = self.client.get(f"/reports/test_domain.com/pdf?token={token}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/pdf")

        # Clean up report
        self.db.delete(report)
        self.db.commit()

if __name__ == "__main__":
    import unittest
    unittest.main()
