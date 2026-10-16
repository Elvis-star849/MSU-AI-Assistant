"""
Router + eligibility checker flow: one entry point for every chat message (no UI code).

    handle_message(chat, assistant, question, form=None, log_path=QUESTION_LOG, log_text=False) -> Turn

route() -> ELIGIBILITY  -> the admissions adviser (src/admissions_adviser.py): the applicant profile is updated from the
                           message (deterministic; the model only attaches A Level grades it cannot), then one follow-up
                           question or a short shortlist from the eligibility engine and the entry-route evaluator
        -> INFO         -> chat.ask(assistant, question): the existing RAG pipeline (with structured programme lookup)
        -> OUT_OF_SCOPE -> fixed reply; for a deadline question about a programme whose advert entry states a deadline,
                           that statement is quoted with its page (no model answer)
Each turn records its path (Turn.path) and a debug record (Turn.flow; shown only in developer mode).

Question log (one JSONL line per question): privacy-preserving metadata by default - timestamp, route, router reason,
status, counts, question length, latency. The question text (e-mail addresses and phone numbers removed) only when
log_text=True (MSU_QUESTION_LOG_TEXT=1). Applicant results are never logged.
"""
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.conversation import ChatSession, Resolution, Turn
from src.admissions_adviser import advise
from src.applicant_profile import ApplicantProfile
from src.extract_grades import Extraction
from src.llm.base import LLMError
from src.router import ELIGIBILITY, INFO, OUT_OF_SCOPE, OUT_OF_SCOPE_REPLY, SHOW_ALL, route_with_reason

QUESTION_LOG = Path("logs/questions.jsonl")          # logs/ is git-ignored
EXTRACTION_BUSY = ("The answer service is busy right now, so I could not read your results from the message. "
                   "Please try again in a moment, or enter them in the form in the sidebar.")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?:\+?\d[\d\s()-]{6,}\d)")
_DEADLINE = re.compile(r"\b(?:deadline|closing date|last (?:day|date)|applications? close|until when|by when|too late)\b", re.I)


@dataclass
class FlowResult:
    """What a non-RAG turn shows, plus the debug record (developer mode only)."""
    path: str
    answer: Optional[str] = None
    status: str = "answered"            # answered | follow_up | out_of_scope | error
    caption: str = ""
    debug: Dict[str, Any] = field(default_factory=dict)
    asked: Optional[str] = None          # the question the assistant asked the applicant, if any
    data: Any = None                     # EligibilityAnswer for eligibility answers (full lists for the tabs)


def redact(text: str) -> str:
    return _PHONE.sub("[phone]", _EMAIL.sub("[email]", text or ""))


def log_question(path: Path, record: Dict[str, Any]) -> None:
    """Append one JSONL line; logging problems never break the chat."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


def router_history(chat: ChatSession) -> List[Dict[str, Any]]:
    out = []
    for t in chat.turns[-3:]:
        asked = t.flow.asked if t.flow is not None else None
        out.append({"user": t.question, "path": t.path, "asked": asked,
                    "asked_for_grades": asked in ("a_level_subjects", "a_level_grades", "opener"),
                    "asked_for_o_level": asked in ("o_level_grades", "o_level_details"),
                    "confirm": bool(t.flow is not None and t.flow.status == "confirm")})
    return out


def _conversation(chat: ChatSession, question: str) -> List[Any]:
    """The applicant's messages since the last non-eligibility turn, with the questions the assistant asked in
    between (only used when the model has to attach A Level grades to subjects)."""
    items: List[Any] = []
    for t in reversed(chat.turns):
        if t.path != ELIGIBILITY:
            break
        block: List[Any] = [t.question]
        if t.flow is not None and t.flow.asked:
            block.append(("assistant", t.flow.asked))
        items[0:0] = block
    return items


def _llm(assistant: Any):
    return (assistant.llm, assistant.settings) if getattr(assistant, "llm", None) is not None else (None, None)


def _eligibility(chat: ChatSession, assistant: Any, question: str, form: Optional[Extraction], router: Dict,
                 confirmed_reset: bool = False) -> FlowResult:
    """The admissions adviser (src/admissions_adviser.py): profile, one question at a time, shortlist."""
    llm, settings = _llm(assistant)
    if chat.applicant is None:
        chat.applicant = ApplicantProfile()
    try:
        reply = advise(chat.applicant, question, len(chat.turns), _conversation(chat, question), llm, settings,
                       form=form, confirmed_reset=confirmed_reset)
    except LLMError as error:
        return FlowResult(ELIGIBILITY, EXTRACTION_BUSY, "error", "Admissions adviser",
                          {"router": router, "extraction_error": error.kind})
    debug = {"router": router, **reply.debug, "status": reply.status, "asked": reply.asked,
             "shortlist": [(r.id, r.route, r.status) for r in reply.shortlist],
             "counts": reply.detail.counts if reply.detail else None}
    return FlowResult(ELIGIBILITY, reply.text, reply.status, "Admissions adviser", debug, asked=reply.asked, data=reply)


def _out_of_scope(question: str, router: Dict) -> FlowResult:
    """The fixed reply; a deadline question about a programme whose advert entry states a deadline also quotes it."""
    answer = OUT_OF_SCOPE_REPLY
    if _DEADLINE.search(question or ""):
        from src.programme_lookup import find_programmes
        stated = [(r, r["programme_note"]) for r in find_programmes(question)
                  if "deadline" in (r.get("programme_note") or "").lower()]
        if stated:
            lines = [f"- **{r['programme']}**: “{note.strip()}” (2027 intake advert, p. {r['source_page']})"
                     for r, note in stated[:3]]
            answer = ("The 2027 intake advert states:\n" + "\n".join(lines) +
                      "\n\nFor any other application dates, please contact the Admissions Office: "
                      "admissions@admin.msu.ac.zw or (054) 2260496.")
    return FlowResult(OUT_OF_SCOPE, answer, "out_of_scope", "Out of scope · fixed reply", {"router": router})


def handle_message(chat: ChatSession, assistant: Any, question: str, form: Optional[Extraction] = None,
                   log_path: Optional[Path] = QUESTION_LOG, log_text: bool = False,
                   action: Optional[str] = None) -> Turn:
    """action="reset_confirmed": the applicant confirmed "Start new assessment" in the interface."""
    started = time.perf_counter()
    question = (question or "").strip()
    llm, settings = _llm(assistant)
    if action == "reset_confirmed":
        label, reason = ELIGIBILITY, "new_assessment_button"
    else:
        label, reason = route_with_reason(question, router_history(chat), llm, settings,
                                          has_results=chat.has_assessment())
    router = {"label": label, "reason": reason}
    if label == INFO:
        turn = chat.ask(assistant, question)            # the existing RAG pipeline
        turn.path, turn.flow = INFO, FlowResult(INFO, debug={"router": router})
        r = turn.result
        record = {"status": r.status, "not_found": bool(getattr(r, "not_found", False)), "sources": len(r.sources)}
    else:
        flow = _out_of_scope(question, router) if label == OUT_OF_SCOPE else _eligibility(
            chat, assistant, question, form, router, confirmed_reset=action == "reset_confirmed")
        turn = Turn(question, Resolution(question, question, False, "standalone"), result=None, path=label, flow=flow)
        chat.turns.append(turn)                         # follow-up context for INFO questions is left unchanged
        record = {"status": flow.status, "asked": flow.debug.get("asked"), "focus": flow.debug.get("focus"),
                  "shortlist": len(flow.debug.get("shortlist") or []),
                  "results_method": flow.debug.get("results_method")}
    if log_path is not None:
        entry = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "route": label,
                 "router_reason": reason, "question_chars": len(question),
                 "latency_ms": round((time.perf_counter() - started) * 1000), **record}
        if log_text:
            entry["question"] = redact(question)
        log_question(log_path, entry)
    return turn
