"""
LLM configuration from the environment.

Values come from the process environment first, then from the local, Git-ignored .env file (read without changing
os.environ). The API key is held only in LLMConfig.api_key, which is excluded from repr() and from every record.

Variables: LLM_PROVIDER (default groq), GROQ_API_KEY, GROQ_MODEL, LLM_TEMPERATURE, LLM_REASONING_EFFORT,
LLM_MAX_COMPLETION_TOKENS, LLM_TIMEOUT_S, LLM_MAX_RETRIES.

Optional second model: GROQ_MODEL_2 (for example openai/gpt-oss-120b). It is used only when selected explicitly with
load_config(model_env="GROQ_MODEL_2"); the default (model_env=None) reads GROQ_MODEL exactly as before. An explicitly
selected variable that is not set, or a name that is not GROQ_MODEL / GROQ_MODEL_<n>, raises ModelSelectionError
instead of silently falling back to another model.
"""
import os
import re
from dataclasses import dataclass, field
from typing import Mapping, Optional

from dotenv import dotenv_values

from src.llm.base import GenerationSettings
from src.llm.groq_client import DEFAULT_MODEL

DEFAULTS = GenerationSettings(model=DEFAULT_MODEL)
DEFAULT_MODEL_ENV = "GROQ_MODEL"
MODEL_ENV_NAME = re.compile(r"GROQ_MODEL(?:_[2-9])?")


class ModelSelectionError(ValueError):
    """An explicitly selected model variable is invalid or not set."""


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    settings: GenerationSettings
    api_key: Optional[str] = field(default=None, repr=False)
    model_env: str = DEFAULT_MODEL_ENV

    @property
    def key_configured(self) -> bool:
        return bool(self.api_key)


def load_config(env: Optional[Mapping[str, str]] = None, dotenv_path: Optional[str] = ".env",
                model_env: Optional[str] = None) -> LLMConfig:
    """env=None reads os.environ; dotenv_path=None skips the .env file (tests use both to stay isolated).
    model_env=None reads GROQ_MODEL (default behaviour); model_env="GROQ_MODEL_2" selects the second model and
    requires that variable to be set."""
    if model_env is not None and not MODEL_ENV_NAME.fullmatch(model_env):
        raise ModelSelectionError(f"unknown model variable {model_env!r}; use GROQ_MODEL or GROQ_MODEL_2")
    values = {k: v for k, v in (dotenv_values(dotenv_path) if dotenv_path and os.path.exists(dotenv_path) else {}).items()
              if v is not None}
    values.update(os.environ if env is None else env)

    def get(name, default, cast=str):
        raw = values.get(name)
        return default if raw is None or raw.strip() == "" else cast(raw.strip())

    if model_env is not None and get(model_env, None) is None:
        raise ModelSelectionError(f"{model_env} was selected but is not set (add it to the environment or .env)")
    effort = get("LLM_REASONING_EFFORT", DEFAULTS.reasoning_effort)
    settings = GenerationSettings(
        model=get(model_env or DEFAULT_MODEL_ENV, DEFAULTS.model),
        temperature=get("LLM_TEMPERATURE", DEFAULTS.temperature, float),
        reasoning_effort=None if effort == "none" else effort,
        max_completion_tokens=get("LLM_MAX_COMPLETION_TOKENS", DEFAULTS.max_completion_tokens, int),
        timeout_s=get("LLM_TIMEOUT_S", DEFAULTS.timeout_s, float),
        max_retries=get("LLM_MAX_RETRIES", DEFAULTS.max_retries, int),
        retry_backoff_s=DEFAULTS.retry_backoff_s)
    return LLMConfig(provider=get("LLM_PROVIDER", "groq").lower(), settings=settings,
                     api_key=values.get("GROQ_API_KEY") or None, model_env=model_env or DEFAULT_MODEL_ENV)
