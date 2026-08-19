import os
os.environ["JWT_SECRET"] = "test-secret-value-dealscout-2026-minimum-length-32-chars-long"

import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from vcdiligence.database import Base, User, Organization
from vcdiligence.security import hash_password, create_access_token, verify_password
from vcdiligence.auth import get_current_user

class TestAuthSecurity(unittest.TestCase):
    def setUp(self):
        # Use an in-memory SQLite for testing
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

        # Seed organization
        self.org = Organization(id=1, company_name="Test Org")
        self.db.add(self.org)

        # Seed user
        self.hashed = hash_password("testpass")
        self.user = User(
            email="test@example.com",
            hashed_password=self.hashed,
            role="analista",
            organization_id=1
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_password_verification(self):
        self.assertTrue(verify_password("testpass", self.hashed))
        self.assertFalse(verify_password("wrongpass", self.hashed))

    def test_jwt_generation_and_decoding(self):
        token = create_access_token({"sub": "test@example.com"})
        user = get_current_user(token=token, db=self.db)
        self.assertEqual(user.email, "test@example.com")
        self.assertEqual(user.role, "analista")

class TestRegistrationEndpoints(unittest.TestCase):
    def _clean_db(self):
        from vcdiligence.database import User, Organization
        emails = [
            "empresa1_test@example.com",
            "empresa2_test@example.com",
            "personal1_test@example.com",
            "personal2_test@example.com",
            "personal_nocompany@example.com"
        ]
        self.db.query(User).filter(User.email.in_(emails)).delete(synchronize_session=False)
        self.db.query(Organization).filter(
            Organization.company_name.in_([
                "Acme Enterprise",
                "Personal - Personal Company (personal1_test@example.com)",
                "Personal - Personal Company (personal2_test@example.com)",
                "Personal Organization - personal_nocompany@example.com"
            ])
        ).delete(synchronize_session=False)
        self.db.commit()

    def setUp(self):
        from fastapi.testclient import TestClient
        from vcdiligence.app import app
        from vcdiligence.database import SessionLocal
        self.client = TestClient(app)
        self.db = SessionLocal()
        self._clean_db()

    def tearDown(self):
        self._clean_db()
        self.db.close()

    def test_register_empresa_duplicate_company_name(self):
        # Register user 1 with company "Acme Enterprise"
        res1 = self.client.post("/register", json={
            "email": "empresa1_test@example.com",
            "password": "password123",
            "account_type": "empresa",
            "company_name": "Acme Enterprise"
        })
        self.assertEqual(res1.status_code, 200)
        user1_data = res1.json()["user"]

        # Register user 2 with SAME company name
        res2 = self.client.post("/register", json={
            "email": "empresa2_test@example.com",
            "password": "password123",
            "account_type": "empresa",
            "company_name": "Acme Enterprise"
        })
        self.assertEqual(res2.status_code, 200)
        user2_data = res2.json()["user"]

        # Both users should share the same organization_id
        self.assertEqual(user1_data["organization_id"], user2_data["organization_id"])

    def test_register_personal_duplicate_company_name(self):
        # Register personal user 1
        res1 = self.client.post("/register", json={
            "email": "personal1_test@example.com",
            "password": "password123",
            "account_type": "personal",
            "company_name": "Personal Company"
        })
        self.assertEqual(res1.status_code, 200)
        user1_data = res1.json()["user"]

        # Register personal user 2 with same company name
        res2 = self.client.post("/register", json={
            "email": "personal2_test@example.com",
            "password": "password123",
            "account_type": "personal",
            "company_name": "Personal Company"
        })
        self.assertEqual(res2.status_code, 200)
        user2_data = res2.json()["user"]

        # Personal users should have distinct organization_ids
        self.assertNotEqual(user1_data["organization_id"], user2_data["organization_id"])

    def test_register_personal_missing_company_name(self):
        res = self.client.post("/register", json={
            "email": "personal_nocompany@example.com",
            "password": "password123",
            "account_type": "personal"
        })
        self.assertEqual(res.status_code, 200)
        self.assertIn("access_token", res.json())

if __name__ == "__main__":
    unittest.main()
