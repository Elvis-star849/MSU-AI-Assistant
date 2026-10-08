"""
Provider-independent LLM interface (Stage 7).

The rest of the application depends only on this module: Message, GenerationSettings, LLMResponse, LLMError and
LLMClient. A provider (src/llm/groq_client.py, later Gemini, Ollama, ...) implements LLMClient._complete; retries,
latency and attempt counting live here so they behave the same for every provider.
"""
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Callable, Dict, List, Optional

REASONING_EFFORTS = ("low", "medium", "high")


@dataclass(frozen=True)
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class GenerationSettings:
    """Everything that controls one generation request. Recorded with every response; never holds credentials."""
    model: str
    temperature: float = 0.0
    reasoning_effort: Optional[str] = "medium"
    max_completion_tokens: int = 4096
    timeout_s: float = 60.0
    max_retries: int = 2  # retries after the first attempt, only for retryable errors
    retry_backoff_s: float = 1.0  # waits backoff, 2*backoff, 4*backoff, ...

    def __post_init__(self):
        if not self.model:
            raise ValueError("model must be set")
        if not 0.0 <= self.temperature <= 2.0:
            raise ValueError("temperature must be between 0 and 2")
        if self.reasoning_effort is not None and self.reasoning_effort not in REASONING_EFFORTS:
            raise ValueError(f"reasoning_effort must be one of {REASONING_EFFORTS} or None")
        if self.max_completion_tokens < 1 or self.timeout_s <= 0 or self.max_retries < 0 or self.retry_backoff_s < 0:
            raise ValueError("max_completion_tokens, timeout_s, max_retries and retry_backoff_s must be positive")

    def with_changes(self, **changes) -> "GenerationSettings":
        return replace(self, **changes)

    def to_record(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LLMResponse:
    """The final answer only. Provider reasoning / chain-of-thought is never stored here."""
    text: str
    provider: str
    requested_model: str
    returned_model: Optional[str]
    finish_reason: Optional[str]
    usage: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    reasoning_requested_excluded: bool = True
    provider_returned_reasoning: bool = False  # True if the provider sent reasoning anyway (it is discarded)
    latency_ms: Optional[float] = None
    attempts: int = 1
    settings: Dict[str, Any] = field(default_factory=dict)


class LLMError(Exception):
    """Provider-neutral failure. Messages never contain credentials or request headers."""
    KINDS = ("configuration", "authentication", "permission", "model_not_found", "bad_request", "rate_limit",
             "timeout", "connection", "server", "empty_response", "unknown")
    RETRYABLE = {"rate_limit", "timeout", "connection", "server"}

    def __init__(self, kind: str, message: str, status_code: Optional[int] = None, request_id: Optional[str] = None):
        assert kind in self.KINDS, kind
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.request_id = request_id
        self.attempts = 0

    @property
    def retryable(self) -> bool:
        return self.kind in self.RETRYABLE

    def to_record(self) -> Dict[str, Any]:
        return {"kind": self.kind, "message": str(self), "status_code": self.status_code,
                "request_id": self.request_id, "retryable": self.retryable, "attempts": self.attempts}


class LLMClient(ABC):
    provider: str = "abstract"

    def __init__(self, sleep: Callable[[float], None] = time.sleep):
        self._sleep = sleep

    @abstractmethod
    def _complete(self, messages: List[Message], settings: GenerationSettings) -> LLMResponse:
        """One request to the provider. Must raise LLMError (never a provider exception) on failure."""

    def generate(self, messages: List[Message], settings: GenerationSettings) -> LLMResponse:
        """Send the messages, retrying retryable errors up to settings.max_retries times."""
        if not messages:
            raise LLMError("bad_request", "no messages to send")
        start = time.perf_counter()
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._complete(messages, settings)
            except LLMError as error:
                error.attempts = attempt
                if not error.retryable or attempt > settings.max_retries:
                    raise
                self._sleep(settings.retry_backoff_s * 2 ** (attempt - 1))
                continue
            response.attempts = attempt
            response.latency_ms = round((time.perf_counter() - start) * 1000, 1)
            response.settings = settings.to_record()
            return response
