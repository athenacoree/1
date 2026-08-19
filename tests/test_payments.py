import os
os.environ["JWT_SECRET"] = "test-secret-value-dealscout-2026-minimum-length-32-chars-long"

import unittest
import datetime
from unittest import mock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from vcdiligence.app import app
from vcdiligence.database import (
    Base, get_db, User, Organization, UserWallet, SystemConfig, Report, Task
)
from vcdiligence.security import hash_password, create_access_token

class TestPaymentsAndCredits(unittest.TestCase):
    def setUp(self):
        # Setup clean shared in-memory SQLite database for payments testing using StaticPool
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Mock app's DB dependency and SessionLocal to return our mocked DB
        self.db_patcher = mock.patch("vcdiligence.app.SessionLocal", return_value=self.db)
        self.db_patcher.start()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # Seed Organization and User
        self.org = Organization(id=1, company_name="VerdictIQ Capital")
        self.user = User(
            id=1,
            email="payments_analyst@verdictiq.ai",
            hashed_password=hash_password("testpassword123"),
            role="analista",
            organization_id=1
        )
        self.db.add_all([self.org, self.user])
        self.db.commit()

        # Generate authentication token
        self.token = create_access_token(data={"sub": self.user.email})
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db_patcher.stop()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_analyze_free_if_payments_disabled(self):
        # 1. Ensure payments are disabled in SystemConfig
        cfg = SystemConfig(key="payments_enabled", value="false")
        self.db.add(cfg)
        self.db.commit()

        # Mock rate limit and background task trigger to prevent running actual Crew
        with mock.patch("vcdiligence.app.check_rate_limit"), \
             mock.patch("vcdiligence.app.BackgroundTasks.add_task") as mock_add_task:

            resp = self.client.post("/analyze", json={"url": "https://example.com"}, headers=self.headers)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("task_id", resp.json())
            mock_add_task.assert_called_once()

    def test_analyze_402_if_payments_enabled_and_no_credits_no_subscription(self):
        # 1. Enable payments
        cfg = SystemConfig(key="payments_enabled", value="true")
        self.db.add(cfg)

        # 2. No wallet exists or wallet has 0 credits and inactive subscription
        wallet = UserWallet(user_id=self.user.id, credits_balance=0, subscription_active=False)
        self.db.add(wallet)
        self.db.commit()

        resp = self.client.post("/analyze", json={"url": "https://example.com"}, headers=self.headers)
        self.assertEqual(resp.status_code, 402)
        self.assertIn("Créditos insuficientes", resp.json()["detail"])

    def test_analyze_deducts_one_credit_if_payments_enabled_and_has_credits(self):
        # 1. Enable payments
        cfg = SystemConfig(key="payments_enabled", value="true")
        self.db.add(cfg)

        # 2. Add 2 credits to user wallet
        wallet = UserWallet(user_id=self.user.id, credits_balance=2, subscription_active=False)
        self.db.add(wallet)
        self.db.commit()

        # Mock rate limit and background task trigger
        with mock.patch("vcdiligence.app.check_rate_limit"), \
             mock.patch("vcdiligence.app.BackgroundTasks.add_task"):

            resp = self.client.post("/analyze", json={"url": "https://example.com"}, headers=self.headers)
            self.assertEqual(resp.status_code, 200)

            # Verify credit was deducted
            self.db.refresh(wallet)
            self.assertEqual(wallet.credits_balance, 1)

    def test_analyze_no_deduction_if_payments_enabled_and_has_active_subscription(self):
        # 1. Enable payments
        cfg = SystemConfig(key="payments_enabled", value="true")
        self.db.add(cfg)

        # 2. Setup subscription expiring in 10 days, and 5 credits
        expires = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(days=10)
        wallet = UserWallet(user_id=self.user.id, credits_balance=5, subscription_active=True, subscription_expires_at=expires)
        self.db.add(wallet)
        self.db.commit()

        # Mock rate limit and background task trigger
        with mock.patch("vcdiligence.app.check_rate_limit"), \
             mock.patch("vcdiligence.app.BackgroundTasks.add_task"):

            resp = self.client.post("/analyze", json={"url": "https://example.com"}, headers=self.headers)
            self.assertEqual(resp.status_code, 200)

            # Verify credits_balance remains exactly 5 (untouched because of active subscription)
            self.db.refresh(wallet)
            self.assertEqual(wallet.credits_balance, 5)

if __name__ == "__main__":
    unittest.main()
