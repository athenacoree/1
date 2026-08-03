import unittest
import os
import datetime
from unittest import mock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from vcdiligence.database import Base, ApiKeyPool
from vcdiligence.llm_manager import LLMProviderManager

class TestLLMProviderManager(unittest.TestCase):
    def setUp(self):
        # Set up an in-memory SQLite database for testing
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Patch SessionLocal to return our in-memory DB or Session
        self.session_patcher = mock.patch("vcdiligence.llm_manager.SessionLocal", return_value=self.db)
        self.mock_session_local = self.session_patcher.start()

    def tearDown(self):
        self.session_patcher.stop()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_get_llm_raises_value_error_without_keys(self):
        with self.assertRaises(ValueError) as ctx:
            LLMProviderManager.get_llm()
        self.assertIn("No API key found", str(ctx.exception))

    def test_get_llm_from_pool_fallback_to_env(self):
        # When pool is empty, it falls back to environment variables
        with mock.patch.dict(os.environ, {"API_KEY_OPENROUTER": "sk-env-key", "LLM_PROVIDER": "openrouter"}):
            llm_obj, provider, key_id = LLMProviderManager.get_llm_from_pool(provider="openrouter", db_session=self.db)
            self.assertEqual(provider, "openrouter")
            self.assertIsNone(key_id)
            self.assertEqual(llm_obj.api_key, "sk-env-key")

    def test_get_llm_from_pool_rotation(self):
        # Insert keys into pool
        key1 = ApiKeyPool(provider="openrouter", api_key="sk-pool-key1", is_active=True, status="healthy", last_used_at=datetime.datetime.utcnow() - datetime.timedelta(minutes=10))
        key2 = ApiKeyPool(provider="openrouter", api_key="sk-pool-key2", is_active=True, status="healthy", last_used_at=datetime.datetime.utcnow() - datetime.timedelta(minutes=20))
        key3 = ApiKeyPool(provider="openrouter", api_key="sk-pool-key3", is_active=True, status="healthy", last_used_at=None) # No last_used_at sorts first
        self.db.add_all([key1, key2, key3])
        self.db.commit()

        # First query should pick key3 (since last_used_at is None/oldest)
        llm_obj, provider, key_id = LLMProviderManager.get_llm_from_pool(provider="openrouter", db_session=self.db)
        self.assertEqual(key_id, key3.id)
        self.assertEqual(llm_obj.api_key, "sk-pool-key3")

        # Second query should pick key2 (last_used_at is 20m ago)
        llm_obj, provider, key_id = LLMProviderManager.get_llm_from_pool(provider="openrouter", db_session=self.db)
        self.assertEqual(key_id, key2.id)
        self.assertEqual(llm_obj.api_key, "sk-pool-key2")

        # Third query should pick key1 (last_used_at is 10m ago)
        llm_obj, provider, key_id = LLMProviderManager.get_llm_from_pool(provider="openrouter", db_session=self.db)
        self.assertEqual(key_id, key1.id)
        self.assertEqual(llm_obj.api_key, "sk-pool-key1")

    def test_mark_key_result_exhaustion(self):
        key = ApiKeyPool(provider="openrouter", api_key="sk-pool-key1", is_active=True, status="healthy")
        self.db.add(key)
        self.db.commit()

        # 1st failure
        LLMProviderManager.mark_key_result(key.id, success=False, error_message="Rate limit", db_session=self.db)
        self.db.refresh(key)
        self.assertEqual(key.consecutive_failures, 1)
        self.assertEqual(key.status, "healthy")

        # 2nd failure
        LLMProviderManager.mark_key_result(key.id, success=False, error_message="Rate limit", db_session=self.db)
        self.db.refresh(key)
        self.assertEqual(key.consecutive_failures, 2)
        self.assertEqual(key.status, "healthy")

        # 3rd failure -> should mark as exhausted
        LLMProviderManager.mark_key_result(key.id, success=False, error_message="Insufficient quota", db_session=self.db)
        self.db.refresh(key)
        self.assertEqual(key.consecutive_failures, 3)
        self.assertEqual(key.status, "exhausted")
        self.assertEqual(key.last_failure_reason, "Insufficient quota")

        # After success -> should recover
        LLMProviderManager.mark_key_result(key.id, success=True, db_session=self.db)
        self.db.refresh(key)
        self.assertEqual(key.consecutive_failures, 0)
        self.assertEqual(key.status, "healthy")

    def test_recover_exhausted_api_keys_job(self):
        from vcdiligence.monitoring import recover_exhausted_api_keys

        key = ApiKeyPool(provider="openrouter", api_key="sk-pool-key1", is_active=True, status="exhausted", consecutive_failures=3)
        self.db.add(key)
        self.db.commit()

        # To prevent the test from closing self.db, let's mock db.close as a no-op
        original_close = self.db.close
        self.db.close = mock.MagicMock()

        try:
            # Run recovery
            with mock.patch("vcdiligence.monitoring.SessionLocal", return_value=self.db):
                recover_exhausted_api_keys()

            self.db.refresh(key)
            self.assertEqual(key.status, "healthy")
            self.assertEqual(key.consecutive_failures, 0)
        finally:
            self.db.close = original_close

if __name__ == "__main__":
    unittest.main()
