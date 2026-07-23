import os
from crewai import LLM

class LLMProviderManager:
    @staticmethod
    def get_llm():
        selected_provider = os.getenv("LLM_PROVIDER", "openrouter").lower()
        trial_order = [selected_provider]
        for item in ["openrouter", "grok", "openai"]:
            if item not in trial_order:
                trial_order.append(item)

        errors = []
        for provider in trial_order:
            try:
                if provider == "openrouter":
                    api_key = os.getenv("API_KEY_OPENROUTER")
                    model = os.getenv("MODEL_OPENROUTER", "meta-llama/llama-3.3-70b-instruct")
                    if api_key:
                        model_str = f"openrouter/{model}" if not model.startswith("openrouter/") else model
                        return LLM(model=model_str, api_key=api_key), "openrouter"
                elif provider == "grok":
                    api_key = os.getenv("API_KEY_GROK")
                    model = os.getenv("MODEL_GROK", "grok-2-1212")
                    if api_key:
                        model_str = f"grok/{model}" if not model.startswith("grok/") else model
                        return LLM(model=model_str, api_key=api_key), "grok"
                elif provider == "openai":
                    api_key = os.getenv("API_KEY_OPENAI")
                    model = os.getenv("MODEL_OPENAI", "gpt-4o-mini")
                    if api_key:
                        model_str = f"openai/{model}" if not model.startswith("openai/") else model
                        return LLM(model=model_str, api_key=api_key), "openai"
            except Exception as e:
                errors.append(f"{provider}: {str(e)}")
                continue

        # Try to find any available key
        for provider in ["openrouter", "grok", "openai"]:
            if provider == "openrouter" and os.getenv("API_KEY_OPENROUTER"):
                model = os.getenv("MODEL_OPENROUTER", "meta-llama/llama-3.3-70b-instruct")
                return LLM(model=f"openrouter/{model}", api_key=os.getenv("API_KEY_OPENROUTER")), "openrouter"
            if provider == "grok" and os.getenv("API_KEY_GROK"):
                model = os.getenv("MODEL_GROK", "grok-2-1212")
                return LLM(model=f"grok/{model}", api_key=os.getenv("API_KEY_GROK")), "grok"
            if provider == "openai" and os.getenv("API_KEY_OPENAI"):
                model = os.getenv("MODEL_OPENAI", "gpt-4o-mini")
                return LLM(model=f"openai/{model}", api_key=os.getenv("API_KEY_OPENAI")), "openai"

        # Explicitly fail if no valid API key is present anywhere. Never return a fake/dummy demo key silently!
        raise ValueError(
            "No API key found for any of the supported LLM providers (OpenRouter, Grok, OpenAI). "
            "Please configure the appropriate environment variable (API_KEY_OPENROUTER, API_KEY_GROK, or API_KEY_OPENAI) in your environment or .env file."
        )
