import os
import datetime
from crewai import LLM
from vcdiligence.database import SessionLocal, ApiKeyPool
from vcdiligence.logging_config import logger

class LLMProviderManager:
    @staticmethod
    def get_llm_from_pool(provider=None, db_session=None):
        """
        Retrieves an LLM from the ApiKeyPool.
        Rounds robin through the active and healthy keys by picking the oldest last_used_at.
        Falls back to environment variables if no keys are found in the pool.
        """
        if not provider:
            provider = os.getenv("LLM_PROVIDER", "openrouter").lower()
        else:
            provider = provider.lower()

        own_session = False
        if db_session is None:
            db_session = SessionLocal()
            own_session = True

        try:
            # Query for active, healthy keys for the provider, ordering by last_used_at asc
            # In SQLite / PostgreSQL, None values sort first (nulls first), which acts as round-robin for unused keys
            key_record = db_session.query(ApiKeyPool).filter(
                ApiKeyPool.provider == provider,
                ApiKeyPool.is_active == True,
                ApiKeyPool.status == "healthy"
            ).order_by(ApiKeyPool.last_used_at.asc()).first()

            if key_record:
                # Update last_used_at
                key_record.last_used_at = datetime.datetime.utcnow()
                db_session.commit()

                # Instantiate LLM
                api_key = key_record.api_key
                if provider == "openrouter":
                    model = os.getenv("MODEL_OPENROUTER", "meta-llama/llama-3.3-70b-instruct")
                    model_str = f"openrouter/{model}" if not model.startswith("openrouter/") else model
                    logger.info(f"Using API Key ID {key_record.id} from pool for provider {provider}")
                    return LLM(model=model_str, api_key=api_key), "openrouter", key_record.id
                elif provider == "grok":
                    model = os.getenv("MODEL_GROK", "grok-2-1212")
                    model_str = f"grok/{model}" if not model.startswith("grok/") else model
                    logger.info(f"Using API Key ID {key_record.id} from pool for provider {provider}")
                    return LLM(model=model_str, api_key=api_key), "grok", key_record.id
                elif provider == "openai":
                    model = os.getenv("MODEL_OPENAI", "gpt-4o-mini")
                    model_str = f"openai/{model}" if not model.startswith("openai/") else model
                    logger.info(f"Using API Key ID {key_record.id} from pool for provider {provider}")
                    return LLM(model=model_str, api_key=api_key), "openai", key_record.id

        except Exception as e:
            logger.error(f"Error selecting API key from pool: {str(e)}", exc_info=True)
        finally:
            if own_session:
                db_session.close()

        # Fallback to current environment variables (calls get_llm to preserve any test mocks)
        llm_obj, provider_name = LLMProviderManager.get_llm()
        return llm_obj, provider_name, None

    @staticmethod
    def get_llm_from_env(provider=None):
        if not provider:
            provider = os.getenv("LLM_PROVIDER", "openrouter").lower()
        else:
            provider = provider.lower()

        trial_order = [provider]
        for item in ["openrouter", "grok", "openai"]:
            if item not in trial_order:
                trial_order.append(item)

        errors = []
        for p in trial_order:
            try:
                if p == "openrouter":
                    api_key = os.getenv("API_KEY_OPENROUTER")
                    model = os.getenv("MODEL_OPENROUTER", "meta-llama/llama-3.3-70b-instruct")
                    if api_key:
                        model_str = f"openrouter/{model}" if not model.startswith("openrouter/") else model
                        return LLM(model=model_str, api_key=api_key), "openrouter"
                elif p == "grok":
                    api_key = os.getenv("API_KEY_GROK")
                    model = os.getenv("MODEL_GROK", "grok-2-1212")
                    if api_key:
                        model_str = f"grok/{model}" if not model.startswith("grok/") else model
                        return LLM(model=model_str, api_key=api_key), "grok"
                elif p == "openai":
                    api_key = os.getenv("API_KEY_OPENAI")
                    model = os.getenv("MODEL_OPENAI", "gpt-4o-mini")
                    if api_key:
                        model_str = f"openai/{model}" if not model.startswith("openai/") else model
                        return LLM(model=model_str, api_key=api_key), "openai"
            except Exception as e:
                errors.append(f"{p}: {str(e)}")
                continue

        # Try to find any available key
        for p in ["openrouter", "grok", "openai"]:
            if p == "openrouter" and os.getenv("API_KEY_OPENROUTER"):
                model = os.getenv("MODEL_OPENROUTER", "meta-llama/llama-3.3-70b-instruct")
                return LLM(model=f"openrouter/{model}", api_key=os.getenv("API_KEY_OPENROUTER")), "openrouter"
            if p == "grok" and os.getenv("API_KEY_GROK"):
                model = os.getenv("MODEL_GROK", "grok-2-1212")
                return LLM(model=f"grok/{model}", api_key=os.getenv("API_KEY_GROK")), "grok"
            if p == "openai" and os.getenv("API_KEY_OPENAI"):
                model = os.getenv("MODEL_OPENAI", "gpt-4o-mini")
                return LLM(model=f"openai/{model}", api_key=os.getenv("API_KEY_OPENAI")), "openai"

        # Explicitly fail if no valid API key is present anywhere. Never return a fake/dummy demo key silently!
        raise ValueError(
            "No API key found for any of the supported LLM providers (OpenRouter, Grok, OpenAI). "
            "Please configure the appropriate environment variable (API_KEY_OPENROUTER, API_KEY_GROK, or API_KEY_OPENAI) in your environment or .env file."
        )

    @staticmethod
    def mark_key_result(key_id, success: bool, error_message: str = None, db_session=None):
        """
        Marks the execution result of a key.
        - success=True: resets consecutive_failures to 0 and ensures status="healthy"
        - success=False: increments consecutive_failures. If failures >= 3, sets status to "exhausted"
        """
        if key_id is None:
            return

        own_session = False
        if db_session is None:
            db_session = SessionLocal()
            own_session = True

        try:
            key_record = db_session.query(ApiKeyPool).filter_by(id=key_id).first()
            if key_record:
                if success:
                    key_record.consecutive_failures = 0
                    key_record.status = "healthy"
                    logger.info(f"API Key {key_id} marked as healthy and consecutive failures reset to 0.")
                else:
                    key_record.consecutive_failures += 1
                    logger.warning(f"API Key {key_id} failed. Consecutive failures: {key_record.consecutive_failures}.")
                    if key_record.consecutive_failures >= 3:
                        key_record.status = "exhausted"
                        key_record.last_failure_reason = error_message or "Consecutive failures threshold met."
                        logger.error(f"API Key {key_id} has been marked as EXHAUSTED due to 3 consecutive failures. Reason: {error_message}")
                db_session.commit()
        except Exception as e:
            logger.error(f"Error marking API key result: {str(e)}", exc_info=True)
        finally:
            if own_session:
                db_session.close()

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
