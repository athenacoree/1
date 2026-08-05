import unittest
from unittest import mock
from crewai import LLM
from vcdiligence.crew import MarketResearchCrew, TokenBudgetExceededError, run_crew_with_rotation

class TestCrewConfig(unittest.TestCase):
    @mock.patch("vcdiligence.llm_manager.LLMProviderManager.get_llm")
    def test_crew_initialization(self, mock_get_llm):
        mock_get_llm.return_value = (LLM(model="openai/gpt-4o-mini", api_key="dummy"), "openai")
        try:
            crew_obj = MarketResearchCrew()
            agents = crew_obj.crew().agents
            tasks = crew_obj.crew().tasks

            # Check for exactly 7 agents
            self.assertEqual(len(agents), 7)
            agent_roles = [a.role.strip() for a in agents]
            self.assertIn("Omission Analyst", agent_roles)
            self.assertIn("Lead Venture Capital Business Analyst", agent_roles)
            self.assertIn("Devil's Advocate", agent_roles)

            # Check for exactly 7 tasks
            self.assertEqual(len(tasks), 7)
            print("Successfully initialized crew with 7 agents and 7 tasks.")
        except Exception as e:
            self.fail(f"Crew initialization failed: {str(e)}")

    @mock.patch("vcdiligence.llm_manager.LLMProviderManager.get_llm")
    def test_crew_priorities_block(self, mock_get_llm):
        mock_get_llm.return_value = (LLM(model="openai/gpt-4o-mini", api_key="dummy"), "openai")

        # Test with priorities and custom keywords
        crew_obj = MarketResearchCrew(
            user_priorities=["legal_risk", "product_traction"],
            custom_focus_keywords="GDPR compliance"
        )

        self.assertIn("Riesgo legal y regulaciones", crew_obj.user_priorities_block)
        self.assertIn("Tracción de producto y métricas", crew_obj.user_priorities_block)
        self.assertIn("GDPR compliance", crew_obj.user_priorities_block)
        self.assertTrue(crew_obj.user_priorities_block.startswith("INSTRUCCIONES DE PRIORIDAD DEL USUARIO:"))

    @mock.patch("vcdiligence.llm_manager.LLMProviderManager.get_llm")
    def test_token_budget_limit_enforcement(self, mock_get_llm):
        """Verify that max_tokens_per_analysis triggers an error if exceeded."""
        mock_get_llm.return_value = (LLM(model="openai/gpt-4o-mini", api_key="dummy"), "openai")

        crew_obj = MarketResearchCrew()
        crew_obj.max_tokens_per_analysis = 100 # very low budget

        mock_output = mock.MagicMock()
        mock_output.raw = "dummy"

        mock_agent = mock.MagicMock()
        mock_agent._token_process.get_summary.return_value = mock.MagicMock(
            prompt_tokens=100, completion_tokens=50, total_tokens=150
        )

        with self.assertRaises(TokenBudgetExceededError) as context:
            crew_obj._log_and_check_budget("market_research_specialist", mock_agent, mock_output)

        self.assertIn("presupuesto de tokens", str(context.exception))

    @mock.patch("vcdiligence.llm_manager.LLMProviderManager.mark_key_result")
    @mock.patch("vcdiligence.llm_manager.LLMProviderManager.get_llm_from_pool")
    @mock.patch("vcdiligence.crew.MarketResearchCrew.crew")
    def test_run_crew_with_rotation_on_token_budget_exceeded(self, mock_crew_method, mock_get_llm_from_pool, mock_mark_key_result):
        """Verify that TokenBudgetExceededError fails immediately without calling mark_key_result and without retries."""
        mock_llm = LLM(model="openai/gpt-4o-mini", api_key="dummy")
        mock_get_llm_from_pool.return_value = (mock_llm, "openai", 42)

        # Mock the crew and its kickoff to raise TokenBudgetExceededError
        mock_crew_instance = mock.MagicMock()
        mock_crew_instance.kickoff.side_effect = TokenBudgetExceededError("Presupuesto de tokens excedido")
        mock_crew_method.return_value = mock_crew_instance

        inputs = {"company_name": "TestCorp", "company_url": "https://testcorp.com"}

        with self.assertRaises(TokenBudgetExceededError):
            run_crew_with_rotation(inputs)

        # Ensure that mark_key_result was never called since the API key was not the issue
        mock_mark_key_result.assert_not_called()

        # Ensure that crew.kickoff was only called once, i.e., rotation did not retry
        self.assertEqual(mock_crew_instance.kickoff.call_count, 1)

    def test_agent_finding_schema_validation(self):
        """Verify that AgentFinding Pydantic model correctly validates fields."""
        from vcdiligence.agent_schemas import AgentFinding

        finding = AgentFinding(
            category="market",
            score=85,
            key_points=["Bullet 1", "Bullet 2", "Bullet 3"],
            red_flags=[],
            is_clean=True
        )
        self.assertEqual(finding.category, "market")
        self.assertEqual(finding.score, 85)
        self.assertTrue(finding.is_clean)

        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            AgentFinding(
                score=85,
                key_points=["Bullet 1"],
                red_flags=[],
                is_clean=True
            )

if __name__ == "__main__":
    unittest.main()
