import os
import unittest
os.environ["JWT_SECRET"] = "test-secret-value-verdictiq-2026-minimum-length-32-chars-long"

from fastapi.testclient import TestClient
from vcdiligence.app import app
from vcdiligence.database import SessionLocal, Base, engine, User, Organization, Report, Task
from vcdiligence.security import create_access_token

class TestV2Features(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.client = TestClient(app)
        self.db = SessionLocal()

        # Ensure Org & User
        self.org = self.db.query(Organization).filter_by(id=1).first()
        if not self.org:
            self.org = Organization(id=1, company_name="VerdictIQ Capital")
            self.db.add(self.org)
            self.db.commit()

        self.user = self.db.query(User).filter_by(email="analyst@verdictiq.ai").first()
        if not self.user:
            self.user = User(
                email="analyst@verdictiq.ai",
                hashed_password="test_hashed_password",
                role="analista",
                organization_id=self.org.id,
                account_type="personal"
            )
            self.db.add(self.user)
            self.db.commit()

        self.token = create_access_token({"sub": "analyst@verdictiq.ai"})
        self.headers = {"Authorization": f"Bearer {self.token}"}

        # Create a mock report for testing features
        self.report = self.db.query(Report).filter_by(domain="testv2.com").first()
        if not self.report:
            self.report = Report(
                domain="testv2.com",
                company_name="Test V2 Startup",
                url="https://testv2.com",
                score=85,
                sub_scores={"market": 85, "team": 90, "product": 80, "traction": 85, "risk_legal_omissions": 80},
                recommendation="GO",
                report_md="# Due Diligence Report for Test V2 Startup",
                organization_id=self.org.id
            )
            self.db.add(self.report)
            self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_audio_briefing(self):
        resp = self.client.post("/reports/testv2.com/audio-briefing", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("audio_script", data)
        self.assertEqual(data["company_name"], "Test V2 Startup")

    def test_esg_screener(self):
        resp = self.client.post("/reports/testv2.com/esg-screener", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("esg_analysis", data)

    def test_synergies(self):
        resp = self.client.post("/reports/testv2.com/synergies", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("synergies", data)

    def test_battlecard(self):
        resp = self.client.post("/reports/testv2.com/battlecard", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("battlecard", data)

    def test_founder_background(self):
        resp = self.client.post("/reports/testv2.com/founder-background", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("founder_background", data)

    def test_pptx_outline(self):
        resp = self.client.post("/reports/testv2.com/pptx-outline", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("slides", data)
        self.assertEqual(len(data["slides"]), 10)

    def test_valuation_multiples(self):
        resp = self.client.post("/reports/testv2.com/valuation-multiples", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("valuation_benchmark", data)

    def test_due_diligence_checklist(self):
        resp = self.client.post("/reports/testv2.com/due-diligence-checklist", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("checklist", data)

    def test_runway_simulator(self):
        payload = {"monthly_burn_usd": 50000, "current_cash_usd": 600000, "monthly_mrr_usd": 10000}
        resp = self.client.post("/reports/testv2.com/runway-simulator", json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("scenarios", data)

    def test_dataroom_check(self):
        payload = {"documents": ["Cap Table 2026.pdf", "Financial_Statements_2025.xlsx", "IP_Assignment.pdf"]}
        resp = self.client.post("/analyze/dataroom-check", json=payload, headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("checklist_verification", data)

    def test_export_report_data(self):
        resp_json = self.client.get("/reports/testv2.com/export?format=json", headers=self.headers)
        self.assertEqual(resp_json.status_code, 200)
        self.assertIn("score", resp_json.json())

        resp_csv = self.client.get("/reports/testv2.com/export?format=csv", headers=self.headers)
        self.assertEqual(resp_csv.status_code, 200)
        self.assertIn("Test V2 Startup", resp_csv.text)

if __name__ == "__main__":
    unittest.main()
