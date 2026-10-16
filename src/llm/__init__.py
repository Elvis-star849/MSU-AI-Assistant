"""Stage 7 LLM layer. Application code uses create_client() and the types in src.llm.base, never a provider SDK."""
from src.llm.base import GenerationSettings, LLMClient, LLMError, LLMResponse, Message
from src.llm.config import LLMConfig, ModelSelectionError, load_config

PROVIDERS = ("groq",)


def create_client(config: LLMConfig, **kwargs) -> LLMClient:
    if config.provider == "groq":
        from src.llm.groq_client import GroqClient
        return GroqClient(config.api_key, **kwargs)
    raise LLMError("configuration", f"unknown LLM provider {config.provider!r}; available: {PROVIDERS}")


__all__ = ["GenerationSettings", "LLMClient", "LLMConfig", "LLMError", "LLMResponse", "Message", "ModelSelectionError", "PROVIDERS",
           "create_client", "load_config"]
