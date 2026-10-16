"""
MSU AI Assistant service layer (no UI code here).

Profile c3_intake_0006 (default; src/profiles.py): question -> KB StagingRetriever on the verified version 0006
(yearbooks + 2027 road map + 2027 intake advert; accepted Stage 6 configuration: routed search -> top 10 -> MiniLM
heading + text -> top 5) -> G2 grounding prompt + F2 evidence formatting -> openai/gpt-oss-20b -> AssistantResult.
Profile c3_public_0005: the same on the public version 0005 (no intake advert).
Profile baseline (rollback): Stage6Retriever("main") over faiss_store_v2 -> s7-0-baseline-v1 prompt -> same model.

- Safeguards (src/safeguards.py): bounded question text; retrieved passages with instruction-like text are withheld
  from the model; review notes (missing/invalid citations, admissions caution, advert mentions) are attached for
  display. C3/C4 profiles: unsupported full-time/part-time descriptors are removed (original kept as raw_answer);
  unverified facts, unadvertised campus-mode pairs and advert/yearbook duration conflicts get visible notes.
- An empty or degenerate model answer is retried once with light reasoning on the same evidence.

- Course-code ambiguity notes come from src/ambiguity.py and are returned for display only; they are not added to the
  prompt (ambiguity-aware answering is the unevaluated S7-4).
- No evidence -> no LLM call; a fixed insufficient-evidence message is returned.
- An LLM failure never hides the retrieved evidence: the result carries both the friendly error and the sources.
- Offline (retrieval-only) mode: no LLM client is created at all (MSU_ASSISTANT_OFFLINE=1 in the app).
"""
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from src.context import PROMPT_VERSION
from src.llm import LLMError, create_client, load_config
from src.llm.base import GenerationSettings
from src.profiles import (BASELINE, C3, C4_PROMPT_VERSION, INTAKE, KB_PROFILES, build_c4_messages, current_profile,
                          open_profile_retriever)
from src.query_normalise import normalise_query
from src.safeguards import (NOTE_INJECTION, clean_question, is_not_found, miss_tip, present_answer, review_answer,
                            screen_evidence)

# The accepted Stage 7 generation configuration (S7-0/S7-1). Credentials, timeout and retries come from load_config().
ACCEPTED_MODEL = "openai/gpt-oss-20b"
ACCEPTED_GENERATION = {"model": ACCEPTED_MODEL, "temperature": 0.0, "reasoning_effort": "medium",
                       "max_completion_tokens": 4096}

def selected_model_env(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """The model variable selected for the app (MSU_ASSISTANT_MODEL_ENV, e.g. GROQ_MODEL_2), or None (default)."""
    return ((os.environ if env is None else env).get("MSU_ASSISTANT_MODEL_ENV") or "").strip() or None


def generation_settings(config: Any, model_env: Optional[str] = None) -> GenerationSettings:
    """The accepted generation settings. With an explicitly selected model variable only the model changes; temperature,
    reasoning effort and the completion-token cap stay identical so that a model comparison isolates the model."""
    settings = config.settings.with_changes(**ACCEPTED_GENERATION)
    return settings.with_changes(model=config.settings.model) if model_env else settings


# Stage 5 development questions only (eval/stage5_questions.json); never Stage 6 held-out questions.
EXAMPLE_QUESTIONS = [
    "Who chairs Council meetings when the Chancellor is not there?",
    "If I repeat a module, which marks will count?",
    "Describe BM134",
    "How many credits is MECDP704 worth, and which semester is it taught in?",
    "SEMA 204",
    "What is the WiFi password for the MSU library?",
]

NO_EVIDENCE_MESSAGE = ("I could not find any passages in the MSU documents that match this question, so I cannot "
                       "answer it from the official evidence. Try rephrasing the question or checking the course code.")
EVIDENCE_STILL_SHOWN = "The relevant MSU document passages found for your question are still shown below."
FRIENDLY_ERRORS = {
    "configuration": "Answer generation is not configured (for example, the Groq API key is missing).",
    "authentication": "The answer service rejected the configured credentials.",
    "permission": "The answer service rejected the configured credentials.",
    "rate_limit": "The answer service is busy right now (rate limit reached). Please wait a moment and try again.",
    "timeout": "The answer service took too long to respond. Please try again.",
    "connection": "Could not reach the answer service. Please check the internet connection and try again.",
    "server": "The answer service is temporarily unavailable. Please try again shortly.",
    "empty_response": "The answer service did not finish an answer for this question. Please try again or ask a "
                      "more specific question.",
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


_DEGENERATE = re.compile(r"(\S)\1{199,}")


def degenerate(text: Optional[str]) -> bool:
    """A model failure mode: a run of 200+ copies of one character (e.g. a table rule of dashes that fills the token
    budget). Ordinary Markdown table rules are far shorter."""
    return bool(_DEGENERATE.search(text or ""))


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
    profile: str = BASELINE
    safety_notes: List[Dict[str, str]] = field(default_factory=list)
    normalised_question: Optional[str] = None   # set when spelling/intake clean-up changed the searched question
    raw_answer: Optional[str] = None            # model text before the wording correction (present_answer)
    not_found: bool = False                     # no answer in the knowledge base: UI shows the answer only
    retried_empty: bool = False                 # the first generation returned no final answer and was retried once


class Assistant:
    def __init__(self, retriever: Any, llm: Any = None, settings: Optional[GenerationSettings] = None,
                 ambiguous_codes: Optional[Dict[str, Any]] = None, llm_unavailable_reason: Optional[str] = None,
                 answer_fn: Optional[Callable] = None, ambiguity_fn: Optional[Callable] = None,
                 message_builder: Optional[Callable] = None, prompt_version: str = PROMPT_VERSION,
                 profile: str = BASELINE):
        self.retriever = retriever
        self.message_builder = message_builder
        self.prompt_version = prompt_version
        self.profile = profile
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
    def create(cls, offline: bool = False, config_loader: Callable = load_config,
               profile: Optional[str] = None, model_env: Optional[str] = None) -> "Assistant":
        """Load the retrieval pipeline of the selected profile (plus one warm-up search) and ambiguity metadata once
        (about a minute), then the LLM client. profile=None reads MSU_ASSISTANT_PROFILE (default c3_public_0005).
        model_env=None reads MSU_ASSISTANT_MODEL_ENV; if that is unset too, the accepted model is used as before.
        model_env="GROQ_MODEL_2" uses the model named by that variable with otherwise identical settings; a missing
        or invalid variable raises ModelSelectionError (checked before the slow model loading)."""
        from src.ambiguity import ambiguous_codes, code_titles
        from src.evidence import Stage6Retriever

        profile = profile or current_profile()
        model_env = model_env or selected_model_env()
        config = None if offline else (config_loader(model_env=model_env) if model_env else config_loader())
        models = Stage6Retriever("main")      # yearbook index, embedding model and MiniLM reranker
        models._load()
        ambiguous = ambiguous_codes(code_titles(models._store.records))
        if profile in KB_PROFILES:
            retriever = open_profile_retriever(profile, models)
            extra = {"message_builder": build_c4_messages, "prompt_version": C4_PROMPT_VERSION, "profile": profile}
        else:
            retriever, extra = models, {"profile": BASELINE}
        retriever.retrieve("MSU yearbook warm-up")  # loads the query embedding model now, not on the first question
        if offline:
            return cls(retriever, ambiguous_codes=ambiguous, llm_unavailable_reason=OFFLINE_MESSAGE, **extra)
        settings = generation_settings(config, model_env)
        try:
            llm = create_client(config)
        except LLMError as error:
            return cls(retriever, settings=settings, ambiguous_codes=ambiguous,
                       llm_unavailable_reason=friendly_error(error.kind), **extra)
        return cls(retriever, llm=llm, settings=settings, ambiguous_codes=ambiguous, **extra)

    def ask(self, question: str) -> AssistantResult:
        question = (question or "").strip()
        if not question:
            raise ValueError("question is empty")
        start = time.perf_counter()
        result = AssistantResult(question=question, status="answered",
                                 model=self.settings.model if self.settings else None,
                                 prompt_version=self.prompt_version, profile=self.profile)
        try:
            question = clean_question(question)
        except ValueError as error:
            result.status, result.error_kind, result.error_message = "rejected", "input", str(error)
            result.timings_ms["total"] = round((time.perf_counter() - start) * 1000, 1)
            return result
        c3_profile = self.profile in KB_PROFILES          # baseline (rollback) keeps the previous behaviour exactly
        if c3_profile:
            normalised, changes = normalise_query(question)
            if changes:
                question, result.normalised_question = normalised, normalised
        try:
            evidence, withheld = screen_evidence(self.retriever.retrieve(question))
        except Exception:
            result.status, result.error_kind = "retrieval_error", "retrieval"
            result.error_message = "Searching the yearbooks failed. Please try again."
            result.timings_ms["total"] = round((time.perf_counter() - start) * 1000, 1)
            return result
        result.timings_ms["retrieval"] = round((time.perf_counter() - start) * 1000, 1)
        if withheld:
            result.safety_notes.append({"kind": "injection", "text": NOTE_INJECTION.format(n=len(withheld))})
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
                kwargs = {"message_builder": self.message_builder} if self.message_builder else {}
                try:
                    answered = self._answer(question, self.retriever, self.llm, self.settings, evidence=evidence,
                                            **kwargs)
                    if degenerate(answered.answer):
                        raise LLMError("empty_response", "the answer degenerated into a repeated character")
                except LLMError as error:
                    if error.kind != "empty_response" or self.settings is None:
                        raise
                    # no usable answer (token budget spent on reasoning, or a run of one repeated character):
                    # one retry with light reasoning, same evidence
                    answered = self._answer(question, self.retriever, self.llm,
                                            self.settings.with_changes(reasoning_effort="low"), evidence=evidence,
                                            **kwargs)
                    if degenerate(answered.answer):
                        raise LLMError("empty_response", "the answer degenerated into a repeated character")
                    result.retried_empty = True
                result.answer = answered.answer
                try:
                    if c3_profile:
                        from src.safeguards import remove_unsupported_descriptors
                        result.raw_answer = answered.answer
                        result.answer = remove_unsupported_descriptors(present_answer(answered.answer),
                                                                       [e.get("text") or "" for e in evidence])
                    result.safety_notes += review_answer(question, result.answer, len(evidence),
                                                         public_profile=self.profile == C3,
                                                         intake=self.profile == INTAKE,
                                                         sources=[e.get("source") for e in evidence])
                    if c3_profile:
                        result.safety_notes += miss_tip(result.answer, "intake" if self.profile == INTAKE else "public")
                        if not is_not_found("answered", result.answer):
                            from src.conflicts import evidence_conflicts
                            from src.safeguards import fact_notes
                            result.safety_notes += fact_notes(result.answer, evidence, question)
                            result.safety_notes += evidence_conflicts(evidence)
                except Exception:
                    pass  # display-only notes and wording; never block an answer
                result.usage = answered.llm.usage
                result.model = answered.llm.returned_model or result.model
            except LLMError as error:
                result.status, result.error_kind = "generation_error", error.kind
                result.error_message = f"{friendly_error(error.kind)} {EVIDENCE_STILL_SHOWN}"
            except Exception:
                result.status, result.error_kind = "generation_error", "unknown"
                result.error_message = f"{DEFAULT_FRIENDLY_ERROR} {EVIDENCE_STILL_SHOWN}"
            result.timings_ms["generation"] = round((time.perf_counter() - generation_start) * 1000, 1)
        result.not_found = is_not_found(result.status, result.answer)
        result.timings_ms["total"] = round((time.perf_counter() - start) * 1000, 1)
        return result
