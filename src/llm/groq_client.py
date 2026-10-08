"""
Groq provider for the Stage 7 LLM interface, using the official Groq Python SDK.

- The SDK's own retries are disabled (max_retries=0); retries come only from GenerationSettings via LLMClient.
- Reasoning is requested to be excluded (include_reasoning=False). If the provider still returns a reasoning field,
  it is discarded and only flagged (LLMResponse.provider_returned_reasoning).
- Groq exceptions are mapped to LLMError without their message text, so nothing from the request leaks out.
"""
from typing import Any, List, Optional

import groq

from src.llm.base import GenerationSettings, LLMClient, LLMError, LLMResponse, Message

SUPPORTED_MODELS = ("openai/gpt-oss-20b", "openai/gpt-oss-120b")
DEFAULT_MODEL = "openai/gpt-oss-20b"


def _request_id(error: Exception) -> Optional[str]:
    response = getattr(error, "response", None)
    return response.headers.get("x-request-id") if response is not None else None


def map_groq_error(error: Exception) -> LLMError:
    # order matters: APITimeoutError is a subclass of APIConnectionError
    kinds = [(groq.AuthenticationError, "authentication"), (groq.PermissionDeniedError, "permission"),
             (groq.NotFoundError, "model_not_found"), (groq.RateLimitError, "rate_limit"),
             (groq.BadRequestError, "bad_request"), (groq.UnprocessableEntityError, "bad_request"),
             (groq.InternalServerError, "server"), (groq.APITimeoutError, "timeout"),
             (groq.APIConnectionError, "connection")]
    kind = next((k for cls, k in kinds if isinstance(error, cls)), None)
    status = getattr(error, "status_code", None)
    if kind is None:
        kind = "server" if status is not None and status >= 500 else "unknown"
    detail = f" (HTTP {status})" if status is not None else ""
    return LLMError(kind, f"Groq request failed: {kind}{detail}", status_code=status, request_id=_request_id(error))


class GroqClient(LLMClient):
    provider = "groq"

    def __init__(self, api_key: Optional[str], sdk_client: Any = None, **kwargs):
        super().__init__(**kwargs)
        if sdk_client is None:
            if not api_key:
                raise LLMError("configuration", "GROQ_API_KEY is not configured")
            sdk_client = groq.Groq(api_key=api_key, max_retries=0)
        self._client = sdk_client

    def _complete(self, messages: List[Message], settings: GenerationSettings) -> LLMResponse:
        if settings.model not in SUPPORTED_MODELS:
            raise LLMError("configuration", f"model {settings.model!r} is not supported; use one of {SUPPORTED_MODELS}")
        request = {"model": settings.model, "messages": [{"role": m.role, "content": m.content} for m in messages],
                   "temperature": settings.temperature, "max_completion_tokens": settings.max_completion_tokens,
                   "include_reasoning": False, "timeout": settings.timeout_s}
        if settings.reasoning_effort is not None:
            request["reasoning_effort"] = settings.reasoning_effort
        try:
            completion = self._client.chat.completions.create(**request)
        except groq.GroqError as error:
            raise map_groq_error(error) from None
        if not completion.choices:
            raise LLMError("empty_response", "Groq returned no choices")
        choice = completion.choices[0]
        text = (choice.message.content or "").strip()
        if not text:
            reason = f" (finish_reason={choice.finish_reason})" if choice.finish_reason else ""
            raise LLMError("empty_response", f"Groq returned no final answer{reason}")
        usage = completion.usage.model_dump(exclude_none=True) if completion.usage is not None else {}
        x_groq = getattr(completion, "x_groq", None)
        return LLMResponse(
            text=text, provider=self.provider, requested_model=settings.model, returned_model=completion.model,
            finish_reason=choice.finish_reason, usage=usage,
            request_id=getattr(x_groq, "id", None) or getattr(completion, "id", None),
            reasoning_requested_excluded=True,
            provider_returned_reasoning=bool(getattr(choice.message, "reasoning", None)))
