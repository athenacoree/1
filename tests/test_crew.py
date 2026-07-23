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

            # Check for exactly 6 agents
            self.assertEqual(len(agents), 6)
            agent_roles = [a.role.strip() for a in agents]
            self.assertIn("Omission Analyst", agent_roles)
            self.assertIn("Lead Venture Capital Business Analyst", agent_roles)

            # Check for exactly 6 tasks
            self.assertEqual(len(tasks), 6)
            print("Successfully initialized crew with 6 agents and 6 tasks.")
        except Exception as e:
            self.fail(f"Crew initialization failed: {str(e)}")

if __name__ == "__main__":
    unittest.main()
