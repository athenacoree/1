import unittest
from unittest import mock
from crewai import LLM
from vcdiligence.crew import MarketResearchCrew

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

if __name__ == "__main__":
    unittest.main()
