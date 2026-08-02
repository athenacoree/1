import os
import yaml
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from typing import List
from vcdiligence.llm_manager import LLMProviderManager

@CrewBase
class MarketResearchCrew():
    def __init__(self, task_callback=None, user_priorities=None, custom_focus_keywords=None):
        base_path = os.path.dirname(__file__)
        agents_yaml_path = os.path.join(base_path, "config", "agents.yaml")
        tasks_yaml_path = os.path.join(base_path, "config", "tasks.yaml")

        with open(agents_yaml_path, "r", encoding="utf-8") as f:
            self.agents_config = yaml.safe_load(f)
        with open(tasks_yaml_path, "r", encoding="utf-8") as f:
            self.tasks_config = yaml.safe_load(f)

        self.llm, self.provider_name = LLMProviderManager.get_llm()
        self.task_callback = task_callback

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
            config=self.tasks_config["market_research_task"]
        )

    @task
    def competitive_intelligence_task(self) -> Task:
        return Task(
            config=self.tasks_config["competitive_intelligence_task"]
        )

    @task
    def customer_insights_task(self) -> Task:
        return Task(
            config=self.tasks_config["customer_insights_task"]
        )

    @task
    def product_strategy_task(self) -> Task:
        return Task(
            config=self.tasks_config["product_strategy_task"]
        )

    @task
    def omission_analyst_task(self) -> Task:
        return Task(
            config=self.tasks_config["omission_analyst_task"]
        )

    @task
    def business_analyst_task(self) -> Task:
        return Task(
            config=self.tasks_config["business_analyst_task"],
            callback=self.task_callback
        )

    @task
    def devils_advocate_task(self) -> Task:
        return Task(
            config=self.tasks_config["devils_advocate_task"]
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
