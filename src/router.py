"""
Question router for the MSU AI Assistant: every user message goes to exactly one path.

    route(question, history, llm, settings) -> "ELIGIBILITY" | "INFO" | "OUT_OF_SCOPE"

- ELIGIBILITY   the user gives or asks about their own subjects/grades and wants to know what they can study.
- INFO          programmes, entry requirements for a named programme, campuses, contacts, calendar, services
                (the existing RAG pipeline, unchanged).
- OUT_OF_SCOPE  fees of any kind, payments, bank details, application deadlines, scholarships, cut-off points.
                Answered with OUT_OF_SCOPE_REPLY; no model is asked for an answer.

Order: (1) a deterministic keyword guard for out-of-scope topics (no model call at all), (2) "show all" right after
an eligibility answer, (3) the Groq model (GROQ_MODEL, temperature 0, label only). Anything that is not exactly one
label, a model error, or no configured model -> "INFO", the existing behaviour.
"""
import re
from typing import Any, Dict, List, Optional

from src.llm.base import GenerationSettings, LLMError, Message

ELIGIBILITY, INFO, OUT_OF_SCOPE = "ELIGIBILITY", "INFO", "OUT_OF_SCOPE"
LABELS = (ELIGIBILITY, INFO, OUT_OF_SCOPE)
OUT_OF_SCOPE_REPLY = ("I don't have verified information on that. Please contact the Admissions Office: "
                      "admissions@admin.msu.ac.zw or (054) 2260496.")

# Word-bounded on purpose: "Banking and Finance" (a programme) and "face-to-face tuition" must not match.
OUT_OF_SCOPE_TOPICS = re.compile(
    r"\b(?:fees?|levy|levies|payments?|pay|paying|paid|costs?|price|bank (?:details|account|transfer)|banking details"
    r"|account number|deadlines?|closing date|due date|last (?:day|date) (?:to|for) (?:apply|applying|submit\w*|applications?)"
    r"|applications? (?:close|closes|closing|end|ends)|until when can (?:i|we|you) (?:apply|submit)"
    r"|by when (?:should|must|do|can) (?:i|we|you) (?:apply|submit)|how much\b[^?.]{0,30}\btuition"
    r"|scholarships?|bursar(?:y|ies)|cut[- ]?off(?: points?)?)\b", re.I)
SHOW_ALL = re.compile(r"\b(?:show (?:me )?(?:all|everything|the full list)|full list|list all)\b", re.I)

ROUTER_PROMPT = """You classify one message sent to the Midlands State University (MSU) admissions assistant.
Reply with exactly one label and nothing else: ELIGIBILITY, INFO or OUT_OF_SCOPE.

ELIGIBILITY: the user gives or asks about their own subjects or grades and wants to know what they can study or qualify for. This includes a reply that supplies subjects, grades or O Level results after the assistant asked for them.
INFO: questions about programmes, entry requirements for a named programme, campuses, contacts, the academic calendar (including face-to-face tuition, teaching and examination dates) or services, and any other question, even if the documents may not cover it.
OUT_OF_SCOPE: only money and deadline topics: tuition fees or any other fees, costs, payments, bank details, application deadlines, scholarships or bursaries, cut-off points, residence fees. "Face-to-face tuition" means teaching sessions, not fees."""
# The model's OUT_OF_SCOPE is accepted only when the question has one of these words; otherwise the question goes to
# INFO, where the RAG pipeline answers or says the documents do not cover it (sending a real question to the fixed
# reply would lose an answer the documents have).
MONEY_OR_DEADLINE_WORDS = re.compile(
    r"\b(?:fees?|costs?|charges?|price|money|pay\w*|expensive|cheap|afford\w*|dollars?|usd|zig|bank (?:details|account|transfer)|deadlines?"
    r"|close[sd]?|closing|due|scholarships?|bursar\w*|grants?|loans?|sponsor\w*|funding|cut[- ]?off|points?"
    r"|how much|last (?:day|date)|until when|by when|apply by|(?:too )?late|in time|how long do (?:i|we|you) have|submi\w+|(?<!face-to-face )(?<!face to face )tuition)\b",
    re.I)


def model_settings(base: GenerationSettings, max_tokens: int) -> GenerationSettings:
    """The app's model (GROQ_MODEL) at temperature 0 with light reasoning; one short retry on rate limits."""
    return base.with_changes(temperature=0.0, reasoning_effort="low", max_completion_tokens=max_tokens,
                             max_retries=1, retry_backoff_s=2.0)


def ask_model(llm: Any, settings: GenerationSettings, system: str, user: str, max_tokens: int) -> str:
    """One model call; raises LLMError (rate limit, timeout, ...) after the short retry."""
    response = llm.generate([Message("system", system), Message("user", user)], model_settings(settings, max_tokens))
    return (response.text or "").strip()


def _labels_in(text: str) -> List[str]:
    return [label for label in LABELS if re.search(rf"\b{label}\b", (text or "").upper())]


def parse_label(text: str) -> str:
    """Exactly one of the three labels, else INFO."""
    found = _labels_in(text)
    return found[0] if len(found) == 1 else INFO


def is_valid_label(text: str) -> bool:
    return len(_labels_in(text)) == 1


def history_text(history: List[Dict[str, Any]], turns: int = 3) -> str:
    lines = []
    for h in (history or [])[-turns:]:
        lines.append(f"User: {h.get('user', '')}")
        if h.get("asked_for_grades"):
            lines.append("Assistant: asked the user for their A Level subjects and grades.")
        elif h.get("asked_for_o_level"):
            lines.append("Assistant: gave an eligibility result and asked the user for their O Level results.")
        elif h.get("path"):
            lines.append(f"Assistant: answered ({h['path']}).")
    return "\n".join(lines) or "(none)"


ELIGIBILITY_PHRASE = re.compile(
    r"\b(?:what|which)\s+(?:programmes?\s+|courses?\s+|degrees?\s+)?(?:can|could)\s+i\s+(?:study|do|apply\s+for|take|enrol)"
    r"|\bdo\s+i\s+qualify\b|\bam\s+i\s+eligible\b|\bwhat\s+do\s+i\s+qualify\s+for\b|\bwith\s+my\s+(?:results|grades|points)\b",
    re.I)
WHY_NOT = re.compile(r"\bwhy\s+(?:can'?t|cannot|can\s+not|don'?t)\s+i\b|\bwhy\s+not\b", re.I)


CAN_I_STUDY = re.compile(r"\b(?:can|could|may)\s+i\s+(?:study|do|take|apply\s+(?:for|to)|get\s+into|enrol\s+(?:in|for)"
                         r"|be\s+admitted\s+to)\b", re.I)


def adviser_reason(q: str, last: Dict[str, Any], in_assessment: bool) -> Optional[str]:
    """Deterministic routing to the admissions adviser (no model call), or None.
    - a reply to the adviser's question or confirmation (unless it is clearly a different question);
    - a new-assessment request, "those were my brother's results", mature entry, "what if I don't have A Levels";
    - the applicant describing their own qualifications, age or work experience;
    - "Can I study <programme>?"."""
    from src.applicant_profile import read_message
    u = read_message(q, last.get("asked"))
    intents = set(u.intents)
    if last.get("path") == ELIGIBILITY and (last.get("asked") or last.get("confirm")):
        if u.has_facts or intents or (len(q.split()) <= 8 and "?" not in q):
            return "adviser_reply"
    if "reset" in intents and (in_assessment or re.search(r"\bassessment\b", q, re.I)):
        return "new_assessment"
    if "not_mine" in intents and in_assessment:
        return "correction"
    if {"mature", "without_a_level"} & intents:
        return "admission_route"
    if u.work_years is not None or u.qualifications or u.a_level_status == "none":
        return "applicant_profile"
    if (u.age is not None or u.a_level_status) and \
            (u.o_level or u.o_passes is not None or u.qualifications or u.a_level_status or in_assessment
             or ELIGIBILITY_PHRASE.search(q)):
        return "applicant_profile"
    if CAN_I_STUDY.search(q) and u.interests:
        from src.admissions_adviser import _study_programmes
        if _study_programmes(u.interests):
            return "programme_question"
    if in_assessment and (u.has_facts or "show_all" in intents or ("why_not" in intents and last.get("path") == ELIGIBILITY)):
        return "adviser_reply"
    return None


def route(question: str, history: Optional[List[Dict[str, Any]]] = None, llm: Any = None,
          settings: Optional[GenerationSettings] = None, has_results: bool = False) -> str:
    return route_with_reason(question, history, llm, settings, has_results)[0]


def route_with_reason(question: str, history: Optional[List[Dict[str, Any]]] = None, llm: Any = None,
                      settings: Optional[GenerationSettings] = None, has_results: bool = False):
    """(label, reason) where reason is keyword | show_all | results_in_message | eligibility_phrase | why_not | model |
    model_invalid_output | model_out_of_scope_not_confirmed | model_error | no_model.
    Deterministic first (no model call): out-of-scope keywords, "show all", messages that contain exam results, clear
    "what can I study / do I qualify" phrasing, "why can't I ..." after an eligibility answer. The model only
    classifies what is left. has_results: this chat already holds the applicant's results."""
    from src.results_parser import parse_results
    q = question or ""
    if OUT_OF_SCOPE_TOPICS.search(q):
        return OUT_OF_SCOPE, "keyword"
    last = history[-1] if history else {}
    if SHOW_ALL.search(q) and last.get("path") == ELIGIBILITY:
        return ELIGIBILITY, "show_all"
    adviser = adviser_reason(q, last, has_results)
    if adviser:
        return ELIGIBILITY, adviser
    parsed = parse_results(q, o_level_context=bool(last.get("asked_for_o_level")))
    if parsed.a_level or (parsed.o_level and (last.get("asked_for_o_level") or has_results or "passes" in parsed.o_level)):
        return ELIGIBILITY, "results_in_message"
    if last.get("asked_for_grades") and parsed.subjects_without_grade:
        return ELIGIBILITY, "results_in_message"
    if ELIGIBILITY_PHRASE.search(q):
        return ELIGIBILITY, "eligibility_phrase"
    if has_results and last.get("path") == ELIGIBILITY and WHY_NOT.search(q):
        return ELIGIBILITY, "why_not"
    if llm is None or settings is None:
        return INFO, "no_model"
    user = f"Recent conversation:\n{history_text(history)}\n\nMessage to classify:\n{question}"
    try:
        text = ask_model(llm, settings, ROUTER_PROMPT, user, max_tokens=512)
    except LLMError:
        return INFO, "model_error"
    label = parse_label(text)
    if label == OUT_OF_SCOPE and not MONEY_OR_DEADLINE_WORDS.search(question or ""):
        return INFO, "model_out_of_scope_not_confirmed"
    return label, "model" if is_valid_label(text) else "model_invalid_output"
