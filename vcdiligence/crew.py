import os
import yaml
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from typing import List
from vcdiligence.llm_manager import LLMProviderManager
from vcdiligence.agent_schemas import AgentFinding

from vcdiligence.logging_config import logger

class WrappedCallback:
    def __init__(self, crew, agent_name, agent_obj, original_callback=None):
        self.crew = crew
        self.agent_name = agent_name
        self.agent_obj = agent_obj
        self.original_callback = original_callback

    def __call__(self, output):
        self.crew._log_and_check_budget(self.agent_name, self.agent_obj, output)
        if self.original_callback:
            self.original_callback(output)

    def __eq__(self, other):
        return other is self.original_callback or other == self.original_callback

def run_crew_with_rotation(inputs, task_callback=None, user_priorities=None, custom_focus_keywords=None, db_session=None, task_id=None):
    """
    Executes the MarketResearchCrew.kickoff() with automatic API key rotation and retries up to 3 times.
    """
    max_attempts = 3
    for attempt in range(max_attempts):
        crew_obj = MarketResearchCrew(
            task_callback=task_callback,
            user_priorities=user_priorities,
            custom_focus_keywords=custom_focus_keywords,
            db_session=db_session,
            task_id=task_id
        )
        inputs["user_priorities_block"] = crew_obj.user_priorities_block
        try:
            logger.info(f"Kicking off MarketResearchCrew (attempt {attempt + 1}/3) using provider: {crew_obj.provider_name}, key_id: {crew_obj.key_id}")
            result = crew_obj.crew().kickoff(inputs=inputs)
            if crew_obj.key_id is not None:
                LLMProviderManager.mark_key_result(crew_obj.key_id, success=True, db_session=db_session)
            return result, crew_obj.provider_name
        except Exception as e:
            err_str = str(e)
            logger.warning(f"Crew kickoff failed on attempt {attempt + 1} with error: {err_str}")

            if crew_obj.key_id is not None:
                LLMProviderManager.mark_key_result(crew_obj.key_id, success=False, error_message=err_str, db_session=db_session)

            if attempt == max_attempts - 1:
                logger.error("Maximum retries with key rotation reached. Failing analysis.")
                raise e
            logger.info("Retrying with a different key from the pool...")

@CrewBase
class MarketResearchCrew():
    def __init__(self, task_callback=None, user_priorities=None, custom_focus_keywords=None, db_session=None, task_id=None):
        base_path = os.path.dirname(__file__)
        agents_yaml_path = os.path.join(base_path, "config", "agents.yaml")
        tasks_yaml_path = os.path.join(base_path, "config", "tasks.yaml")

        with open(agents_yaml_path, "r", encoding="utf-8") as f:
            self.agents_config = yaml.safe_load(f)
        with open(tasks_yaml_path, "r", encoding="utf-8") as f:
            self.tasks_config = yaml.safe_load(f)

        self.db_session = db_session
        self.task_id = task_id
        self.accumulated_tokens_by_agent = {}

        self.llm, self.provider_name, self.key_id = LLMProviderManager.get_llm_from_pool(db_session=db_session)
        self.task_callback = task_callback

        if db_session:
            from vcdiligence.system_config import get_config
            self.max_tokens_per_agent_call = get_config(db_session, "max_tokens_per_agent_call") or 0
            self.max_tokens_per_analysis = get_config(db_session, "max_tokens_per_analysis") or 0
        else:
            self.max_tokens_per_agent_call = 0
            self.max_tokens_per_analysis = 0

        if self.max_tokens_per_agent_call > 0 and self.llm:
            self.llm.max_tokens = self.max_tokens_per_agent_call

        # Generate dynamic user priorities instruction block
        block_lines = []
        if user_priorities:
            priority_labels = {
                "legal_risk": "Riesgo legal y regulaciones",
                "product_traction": "Tracción de producto y métricas",
                "founding_team": "Experiencia del equipo fundador",
                "competition": "Análisis competitivo y competidores",
                "financials": "Métricas financieras y viabilidad de precios"
            }
            readable_priorities = [priority_labels.get(p, p) for p in user_priorities if (p in priority_labels or p)]
            if readable_priorities:
                block_lines.append(f"Este análisis debe dar énfasis especial a: {', '.join(readable_priorities)}.")

        if custom_focus_keywords:
            block_lines.append(f"Presta atención adicional a las siguientes palabras clave o temas de interés específicos del usuario: {custom_focus_keywords}.")

        if block_lines:
            self.user_priorities_block = "INSTRUCCIONES DE PRIORIDAD DEL USUARIO: " + " ".join(block_lines)
        else:
            self.user_priorities_block = ""

    def _log_and_check_budget(self, agent_name: str, agent_obj: Agent, task_output):
        """
        Extracts token usage after a task has completed, records a TokenUsageLog,
        and enforces max_tokens_per_analysis budget.
        """
        from crewai.tasks.task_output import TaskOutput

        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        try:
            if hasattr(agent_obj, "_token_process") and agent_obj._token_process is not None:
                summary = agent_obj._token_process.get_summary()
                prompt_tokens = getattr(summary, "prompt_tokens", 0)
                completion_tokens = getattr(summary, "completion_tokens", 0)
                total_tokens = getattr(summary, "total_tokens", 0)
            elif hasattr(agent_obj, "llm") and hasattr(agent_obj.llm, "get_token_usage_summary"):
                summary = agent_obj.llm.get_token_usage_summary()
                prompt_tokens = getattr(summary, "prompt_tokens", 0)
                completion_tokens = getattr(summary, "completion_tokens", 0)
                total_tokens = getattr(summary, "total_tokens", 0)
        except Exception as e:
            logger.warning(f"Failed to retrieve token usage for {agent_name}: {str(e)}")

        self.accumulated_tokens_by_agent[agent_name] = total_tokens

        if self.db_session:
            try:
                from vcdiligence.database import TokenUsageLog

                model_name = "unknown"
                if hasattr(self.llm, "model") and self.llm.model:
                    model_name = self.llm.model

                log = TokenUsageLog(
                    task_id=self.task_id,
                    agent_name=agent_name,
                    provider=self.provider_name or "unknown",
                    model_name=model_name,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens
                )
                self.db_session.add(log)
                self.db_session.commit()
                logger.info(f"Logged {total_tokens} tokens for agent {agent_name} in task {self.task_id}")
            except Exception as dberr:
                logger.error(f"Failed to log tokens to database: {str(dberr)}")

        cumulative_total = sum(self.accumulated_tokens_by_agent.values())
        if self.max_tokens_per_analysis > 0 and cumulative_total > self.max_tokens_per_analysis:
            err_msg = f"Se ha alcanzado el presupuesto de tokens configurado: {cumulative_total} consumidos de {self.max_tokens_per_analysis} permitidos."
            logger.error(err_msg)
            raise ValueError(err_msg)

    @agent
    def market_research_specialist(self) -> Agent:
        return Agent(
            config=self.agents_config["market_research_specialist"],
            llm=self.llm,
            verbose=True
        )

    @agent
    def competitive_intelligence_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["competitive_intelligence_analyst"],
            llm=self.llm,
            verbose=True
        )

    @agent
    def customer_insights_researcher(self) -> Agent:
        return Agent(
            config=self.agents_config["customer_insights_researcher"],
            llm=self.llm,
            verbose=True
        )

    @agent
    def product_strategy_advisor(self) -> Agent:
        return Agent(
            config=self.agents_config["product_strategy_advisor"],
            llm=self.llm,
            verbose=True
        )

    @agent
    def omission_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["omission_analyst"],
            llm=self.llm,
            verbose=True
        )

    @agent
    def business_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["business_analyst"],
            llm=self.llm,
            verbose=True
        )

    @agent
    def devils_advocate(self) -> Agent:
        return Agent(
            config=self.agents_config["devils_advocate"],
            llm=self.llm,
            verbose=True
        )

    @task
    def market_research_task(self) -> Task:
        return Task(
            config=self.tasks_config["market_research_task"],
            callback=WrappedCallback(self, "market_research_specialist", self.market_research_specialist()),
            output_pydantic=AgentFinding
        )

    @task
    def competitive_intelligence_task(self) -> Task:
        return Task(
            config=self.tasks_config["competitive_intelligence_task"],
            callback=WrappedCallback(self, "competitive_intelligence_analyst", self.competitive_intelligence_analyst()),
            output_pydantic=AgentFinding
        )

    @task
    def customer_insights_task(self) -> Task:
        return Task(
            config=self.tasks_config["customer_insights_task"],
            callback=WrappedCallback(self, "customer_insights_researcher", self.customer_insights_researcher()),
            output_pydantic=AgentFinding
        )

    @task
    def product_strategy_task(self) -> Task:
        return Task(
            config=self.tasks_config["product_strategy_task"],
            callback=WrappedCallback(self, "product_strategy_advisor", self.product_strategy_advisor()),
            output_pydantic=AgentFinding
        )

    @task
    def omission_analyst_task(self) -> Task:
        return Task(
            config=self.tasks_config["omission_analyst_task"],
            callback=WrappedCallback(self, "omission_analyst", self.omission_analyst()),
            output_pydantic=AgentFinding
        )

    @task
    def business_analyst_task(self) -> Task:
        return Task(
            config=self.tasks_config["business_analyst_task"],
            callback=WrappedCallback(self, "business_analyst", self.business_analyst(), self.task_callback)
        )

    @task
    def devils_advocate_task(self) -> Task:
        return Task(
            config=self.tasks_config["devils_advocate_task"],
            callback=WrappedCallback(self, "devils_advocate", self.devils_advocate())
        )

    @crew
    def crew(self) -> Crew:
        return Crew(
            agents=[
                self.market_research_specialist(),
                self.competitive_intelligence_analyst(),
                self.customer_insights_researcher(),
                self.product_strategy_advisor(),
                self.omission_analyst(),
                self.business_analyst(),
                self.devils_advocate()
            ],
            tasks=[
                self.market_research_task(),
                self.competitive_intelligence_task(),
                self.customer_insights_task(),
                self.product_strategy_task(),
                self.omission_analyst_task(),
                self.business_analyst_task(),
                self.devils_advocate_task()
            ],
            process=Process.sequential,
            verbose=True
        )
