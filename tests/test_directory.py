import os
os.environ["JWT_SECRET"] = "test-secret-value-dealscout-2026-minimum-length-32-chars-long"

import datetime
import unittest
from unittest import mock
from fastapi.testclient import TestClient
from vcdiligence.app import app
from vcdiligence.database import SessionLocal, init_db, User, Organization, Report, CompanyListing, ListingInterest
from vcdiligence.security import hash_password

class TestDirectoryFeatures(unittest.TestCase):
    def setUp(self):
        init_db()
        self.client = TestClient(app)
        self.db = SessionLocal()

        # Seed initial data
        org = self.db.query(Organization).filter_by(id=1).first()
        if not org:
            org = Organization(id=1, company_name="VerdictIQ Capital")
            self.db.add(org)
            self.db.commit()

        # Users
        self.founder_user = self.db.query(User).filter_by(email="founder@test.com").first()
        if not self.founder_user:
            self.founder_user = User(
                email="founder@test.com",
                hashed_password=hash_password("founderpassword"),
                role="analista",
                organization_id=1,
                account_type="empresa"
            )
            self.db.add(self.founder_user)
            self.db.commit()

        self.vc_user = self.db.query(User).filter_by(email="vc@test.com").first()
        if not self.vc_user:
            self.vc_user = User(
                email="vc@test.com",
                hashed_password=hash_password("vcpassword"),
                role="analista",
                organization_id=1,
                account_type="personal"
            )
            self.db.add(self.vc_user)
            self.db.commit()

        self.admin_user = self.db.query(User).filter_by(email="admin_dir@test.com").first()
        if not self.admin_user:
            self.admin_user = User(
                email="admin_dir@test.com",
                hashed_password=hash_password("adminpassword"),
                role="administrador",
                organization_id=1,
                account_type="personal"
            )
            self.db.add(self.admin_user)
            self.db.commit()

        # Report for founder
        self.report = self.db.query(Report).filter_by(domain="directorytest.com", organization_id=1).first()
        if not self.report:
            self.report = Report(
                domain="directorytest.com",
                company_name="Directory Test Company",
                url="https://directorytest.com",
                score=88,
                sub_scores={"market": 85, "team": 85, "product": 90, "traction": 90, "risk_legal_omissions": 90},
                recommendation="GO",
                report_md="# Great company",
                organization_id=1
            )
            self.db.add(self.report)
            self.db.commit()

    def tearDown(self):
        # Clean up database entries created during testing
        self.db.query(ListingInterest).delete()
        self.db.query(CompanyListing).delete()
        self.db.commit()
        self.db.close()

    def get_token(self, email, password):
        resp = self.client.post("/login", json={"email": email, "password": password})
        return resp.json()["access_token"]

    def test_listing_not_public_without_optin(self):
        # Check that there are no listings initially
        resp = self.client.get("/listings")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["total"], 0)

    def test_optin_and_moderation_flow(self):
        founder_token = self.get_token("founder@test.com", "founderpassword")
        headers = {"Authorization": f"Bearer {founder_token}"}

        # Founder submits listing opt-in
        optin_payload = {
            "report_id": self.report.id,
            "category": "investment",
            "visible_name": "Directory Test Ltd",
            "visible_industry": "Fintech",
            "visible_country": "Colombia",
            "visible_description": "We build next-gen banking APIs",
            "show_numerical_score": True
        }
        resp = self.client.post("/listings", json=optin_payload, headers=headers)
        self.assertEqual(resp.status_code, 200)
        listing_id = resp.json()["listing_id"]
        slug = resp.json()["slug"]
        self.assertEqual(resp.json()["listing_status"], "pending_review")

        # It must NOT be visible publicly yet because it is pending_review
        pub_resp = self.client.get("/listings")
        self.assertEqual(pub_resp.json()["total"], 0)

        # Serve public individual page: must say inactive
        indiv_resp = self.client.get(f"/empresa/{slug}")
        self.assertEqual(indiv_resp.status_code, 403)

        # Admin approves the listing
        admin_token = self.get_token("admin_dir@test.com", "adminpassword")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Approve listing via POST Form
        approve_resp = self.client.post(
            f"/admin/listings/{listing_id}/approve",
            data={"approve": True},
            headers=admin_headers
        )
        self.assertEqual(approve_resp.status_code, 200)
        self.assertEqual(approve_resp.json()["listing_status"], "approved")

        # Now it must be visible publicly
        pub_resp = self.client.get("/listings")
        self.assertEqual(pub_resp.json()["total"], 1)
        self.assertEqual(pub_resp.json()["listings"][0]["visible_name"], "Directory Test Ltd")
        # Numerical score should be shown as configured
        self.assertEqual(pub_resp.json()["listings"][0]["score"], 88)

        # Serve public individual page: must be success (200) and contain visible details
        indiv_resp = self.client.get(f"/empresa/{slug}")
        self.assertEqual(indiv_resp.status_code, 200)
        self.assertIn("Directory Test Ltd", indiv_resp.text)
        self.assertIn("Fintech", indiv_resp.text)

    def test_expired_listings_are_hidden(self):
        # Create an approved listing but set expires_at in the past
        listing = CompanyListing(
            report_id=self.report.id,
            user_id=self.founder_user.id,
            category="acquisition",
            slug="expired-test-company",
            visible_name="Expired Startup",
            visible_industry="Edtech",
            visible_country="Peru",
            visible_description="Old edtech startup",
            show_numerical_score=False,
            status="approved",
            created_at=datetime.datetime.utcnow() - datetime.timedelta(days=70),
            approved_at=datetime.datetime.utcnow() - datetime.timedelta(days=70),
            expires_at=datetime.datetime.utcnow() - datetime.timedelta(days=10) # 10 days ago expired
        )
        self.db.add(listing)
        self.db.commit()

        # It must NOT show in public listings because it is expired
        pub_resp = self.client.get("/listings")
        self.assertEqual(pub_resp.status_code, 200)
        self.assertEqual(pub_resp.json()["total"], 0)

        # Serving individual page should reject it as inactive
        indiv_resp = self.client.get("/empresa/expired-test-company")
        self.assertEqual(indiv_resp.status_code, 403)

        # Founder renews the listing
        founder_token = self.get_token("founder@test.com", "founderpassword")
        headers = {"Authorization": f"Bearer {founder_token}"}
        renew_resp = self.client.post(f"/listings/{listing.id}/renew", headers=headers)
        self.assertEqual(renew_resp.status_code, 200)
        self.assertEqual(renew_resp.json()["listing_status"], "approved")

        # Now it is extended and visible!
        pub_resp2 = self.client.get("/listings")
        self.assertEqual(pub_resp2.json()["total"], 1)
        self.assertEqual(pub_resp2.json()["listings"][0]["visible_name"], "Expired Startup")

    @mock.patch("vcdiligence.monitoring.send_smtp_alert")
    def test_express_interest_notifies_founder_without_exposing_vc_contact(self, mock_smtp):
        # Setup approved active listing
        listing = CompanyListing(
            report_id=self.report.id,
            user_id=self.founder_user.id,
            category="investment",
            slug="interest-test-co",
            visible_name="Hot Tech",
            visible_industry="Deep Tech",
            visible_country="Mexico",
            visible_description="AI robotics",
            show_numerical_score=True,
            status="approved",
            created_at=datetime.datetime.utcnow(),
            approved_at=datetime.datetime.utcnow(),
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=60)
        )
        self.db.add(listing)
        self.db.commit()

        # Public listings don't expose VC or founder contact info directly in response
        pub_resp = self.client.get("/listings")
        self.assertNotIn("vc@test.com", pub_resp.text)
        self.assertNotIn("founder@test.com", pub_resp.text)

        # VC user registers interest ("Me interesa")
        vc_token = self.get_token("vc@test.com", "vcpassword")
        headers = {"Authorization": f"Bearer {vc_token}"}

        resp = self.client.post(f"/listings/{listing.id}/interest", headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "success")

        # Founder should be notified via email containing VC contact info
        mock_smtp.assert_called_once()
        subject, body = mock_smtp.call_args[0]
        self.assertIn("Hot Tech", subject)
        self.assertIn("vc@test.com", body)

        # Interest is correctly saved in the database
        interests = self.db.query(ListingInterest).filter_by(listing_id=listing.id).all()
        self.assertEqual(len(interests), 1)
        self.assertEqual(interests[0].vc_user_id, self.vc_user.id)

    def test_non_vc_cannot_express_interest(self):
        # Setup approved active listing
        listing = CompanyListing(
            report_id=self.report.id,
            user_id=self.founder_user.id,
            category="investment",
            slug="non-vc-interest-test",
            visible_name="Hot Tech",
            visible_industry="Deep Tech",
            visible_country="Mexico",
            visible_description="AI robotics",
            show_numerical_score=True,
            status="approved",
            created_at=datetime.datetime.utcnow(),
            approved_at=datetime.datetime.utcnow(),
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(days=60)
        )
        self.db.add(listing)
        self.db.commit()

        # Founder user attempts to register interest (account_type = 'empresa')
        founder_token = self.get_token("founder@test.com", "founderpassword")
        headers = {"Authorization": f"Bearer {founder_token}"}

        resp = self.client.post(f"/listings/{listing.id}/interest", headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Only VCs", resp.json()["detail"])

if __name__ == "__main__":
    unittest.main()
