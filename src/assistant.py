"""
MSU AI Assistant service layer (presentation prototype; no UI code here).

question -> accepted Stage 6 retrieval (Stage6Retriever("main"): T1 -> faiss_store_v2 -> top 10 -> MiniLM heading + text
-> top 5) -> accepted s7-0-baseline-v1 prompt -> openai/gpt-oss-20b via the Stage 7 LLM layer -> AssistantResult.

- Course-code ambiguity notes come from src/ambiguity.py and are returned for display only; they are not added to the
  prompt (ambiguity-aware answering is the unevaluated S7-4).
- No evidence -> no LLM call; a fixed insufficient-evidence message is returned.
- An LLM failure never hides the retrieved evidence: the result carries both the friendly error and the sources.
- Offline (retrieval-only) mode: no LLM client is created at all (MSU_ASSISTANT_OFFLINE=1 in the app).
"""
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.context import PROMPT_VERSION
from src.llm import LLMError, create_client, load_config
from src.llm.base import GenerationSettings

# The accepted Stage 7 generation configuration (S7-0/S7-1). Credentials, timeout and retries come from load_config().
ACCEPTED_MODEL = "openai/gpt-oss-20b"
ACCEPTED_GENERATION = {"model": ACCEPTED_MODEL, "temperature": 0.0, "reasoning_effort": "medium",
                       "max_completion_tokens": 4096}

# Stage 5 development questions only (eval/stage5_questions.json); never Stage 6 held-out questions.
EXAMPLE_QUESTIONS = [
    "Who chairs Council meetings when the Chancellor is not there?",
    "If I repeat a module, which marks will count?",
    "Describe BM134",
    "How many credits is MECDP704 worth, and which semester is it taught in?",
    "SEMA 204",
    "What is the WiFi password for the MSU library?",
]

NO_EVIDENCE_MESSAGE = ("I could not find any passages in the MSU yearbooks that match this question, so I cannot "
                       "answer it from the yearbook evidence. Try rephrasing the question or checking the course code.")
EVIDENCE_STILL_SHOWN = "The relevant yearbook passages found for your question are still shown below."
FRIENDLY_ERRORS = {
    "configuration": "Answer generation is not configured (for example, the Groq API key is missing).",
    "authentication": "The answer service rejected the configured credentials.",
    "permission": "The answer service rejected the configured credentials.",
    "rate_limit": "The answer service is busy right now (rate limit reached). Please wait a moment and try again.",
    "timeout": "The answer service took too long to respond. Please try again.",
    "connection": "Could not reach the answer service. Please check the internet connection and try again.",
    "server": "The answer service is temporarily unavailable. Please try again shortly.",
}
DEFAULT_FRIENDLY_ERROR = "The answer service could not produce an answer for this question."
OFFLINE_MESSAGE = "Answer generation is switched off (retrieval-only mode)."
_CITATION_HEADER = re.compile(r"^\[[^\]\n]*\]\n")
_MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]<>()#+\-.!|~$])")


def passage_body(text: str) -> str:
    """Chunk text without the citation header the index adds ("[MSU Humanities Yearbook, p. 404]")."""
    return _CITATION_HEADER.sub("", text, count=1).strip()


def escape_markdown(text: str) -> str:
    """Show yearbook text literally in a Markdown renderer (e.g. '1.' or '*' must not become list syntax)."""
    return _MARKDOWN_SPECIAL.sub(r"\\\1", text).replace("\n", "  \n")


def friendly_error(kind: Optional[str]) -> str:
    return FRIENDLY_ERRORS.get(kind or "", DEFAULT_FRIENDLY_ERROR)


def to_source(number: int, item: Dict[str, Any]) -> Dict[str, Any]:
    return {"number": number, "document": item["source"], "pdf_page": item["page"],
            "heading": (item.get("heading") or "").removeprefix("Section: ").strip() or None,
            "passage": passage_body(item["text"]), "chunk_id": item["chunk_id"], "rank": item["rank"],
            "retrieval_rank": item.get("retrieval_rank"), "retrieval_score": item.get("retrieval_score"),
            "rerank_score": item.get("rerank_score"), "route": item.get("route")}


@dataclass
class AssistantResult:
    question: str
    status: str  # "answered" | "no_evidence" | "generation_error" | "retrieval_error"
    answer: Optional[str] = None
    sources: List[Dict[str, Any]] = field(default_factory=list)
    ambiguity: List[Dict[str, Any]] = field(default_factory=list)
    error_kind: Optional[str] = None
    error_message: Optional[str] = None
    timings_ms: Dict[str, float] = field(default_factory=dict)
    model: Optional[str] = None
    prompt_version: str = PROMPT_VERSION
    usage: Dict[str, Any] = field(default_factory=dict)
    route: Optional[str] = None


class Assistant:
    def __init__(self, retriever: Any, llm: Any = None, settings: Optional[GenerationSettings] = None,
                 ambiguous_codes: Optional[Dict[str, Any]] = None, llm_unavailable_reason: Optional[str] = None,
                 answer_fn: Optional[Callable] = None, ambiguity_fn: Optional[Callable] = None):
        self.retriever = retriever
        self.llm = llm
        self.settings = settings
        self.ambiguous_codes = ambiguous_codes or {}
        self.llm_unavailable_reason = llm_unavailable_reason if llm is None else None
        if answer_fn is None:
            from src.answer import answer_question as answer_fn
        if ambiguity_fn is None:
            from src.ambiguity import ambiguity_note as ambiguity_fn
        self._answer = answer_fn
        self._ambiguity = ambiguity_fn

    @classmethod
    def create(cls, offline: bool = False, config_loader: Callable = load_config) -> "Assistant":
        """Load the accepted retrieval pipeline (plus one warm-up search) and ambiguity metadata once (about a
        minute), then the LLM client."""
        from src.ambiguity import ambiguous_codes, code_titles
        from src.evidence import Stage6Retriever

        retriever = Stage6Retriever("main")
        retriever._load()
        retriever.retrieve("MSU yearbook warm-up")  # loads the query embedding model now, not on the first question
        ambiguous = ambiguous_codes(code_titles(retriever._store.records))
        if offline:
            return cls(retriever, ambiguous_codes=ambiguous, llm_unavailable_reason=OFFLINE_MESSAGE)
        config = config_loader()
        settings = config.settings.with_changes(**ACCEPTED_GENERATION)
        try:
            llm = create_client(config)
        except LLMError as error:
            return cls(retriever, settings=settings, ambiguous_codes=ambiguous,
                       llm_unavailable_reason=friendly_error(error.kind))
        return cls(retriever, llm=llm, settings=settings, ambiguous_codes=ambiguous)

    def ask(self, question: str) -> AssistantResult:
        question = (question or "").strip()
        if not question:
            raise ValueError("question is empty")
        start = time.perf_counter()
        result = AssistantResult(question=question, status="answered",
                                 model=self.settings.model if self.settings else None)
        try:
            evidence = self.retriever.retrieve(question)
        except Exception:
            result.status, result.error_kind = "retrieval_error", "retrieval"
            result.error_message = "Searching the yearbooks failed. Please try again."
            result.timings_ms["total"] = round((time.perf_counter() - start) * 1000, 1)
            return result
        result.timings_ms["retrieval"] = round((time.perf_counter() - start) * 1000, 1)
        result.sources = [to_source(n, item) for n, item in enumerate(evidence, 1)]
        result.route = evidence[0].get("route") if evidence else None
        try:
            result.ambiguity = self._ambiguity(question, evidence, self.ambiguous_codes)
        except Exception:
            result.ambiguity = []  # display-only metadata; never blocks an answer

        if not evidence:
            result.status, result.answer = "no_evidence", NO_EVIDENCE_MESSAGE
        elif self.llm is None:
            result.status, result.error_kind = "generation_error", "unavailable"
            result.error_message = f"{self.llm_unavailable_reason or DEFAULT_FRIENDLY_ERROR} {EVIDENCE_STILL_SHOWN}"
        else:
            generation_start = time.perf_counter()
            try:
                answered = self._answer(question, self.retriever, self.llm, self.settings, evidence=evidence)
                result.answer = answered.answer
                result.usage = answered.llm.usage
                result.model = answered.llm.returned_model or result.model
            except LLMError as error:
                result.status, result.error_kind = "generation_error", error.kind
                result.error_message = f"{friendly_error(error.kind)} {EVIDENCE_STILL_SHOWN}"
            except Exception:
                result.status, result.error_kind = "generation_error", "unknown"
                result.error_message = f"{DEFAULT_FRIENDLY_ERROR} {EVIDENCE_STILL_SHOWN}"
            result.timings_ms["generation"] = round((time.perf_counter() - generation_start) * 1000, 1)
        result.timings_ms["total"] = round((time.perf_counter() - start) * 1000, 1)
        return result
