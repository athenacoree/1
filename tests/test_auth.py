import unittest
import os
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

if __name__ == "__main__":
    unittest.main()
