import unittest
import os
from unittest import mock
from vcdiligence.llm_manager import LLMProviderManager

class TestLLMProviderManager(unittest.TestCase):
    @mock.patch.dict(os.environ, {}, clear=True)
    def test_get_llm_raises_value_error_without_keys(self):
        with self.assertRaises(ValueError) as ctx:
            LLMProviderManager.get_llm()
        self.assertIn("No API key found", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
