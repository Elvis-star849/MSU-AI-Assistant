"""
Extract an applicant's results from the conversation for the eligibility checker.

    extract_grades(user_messages, llm, settings) -> Extraction
    from_form(a_level_rows, english, mathematics, passes) -> Extraction   (sidebar form; no model call)

The model (GROQ_MODEL) is asked for strict JSON only. Its output is then validated in code and nothing it returns is
trusted blindly: grades must be valid letters, subjects are normalised with the checker's own aliases, and every
value must actually appear in what the user wrote (a subject the user never named, or a number of passes they never
gave, is dropped). Unknown fields stay out. Missing details are reported in code:
- no A Level subjects/grades -> the chatbot asks one short question instead of running the checker;
- O Level details missing -> the checker reports them as "to confirm".
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.eligibility import RULES, norm
from src.llm.base import GenerationSettings
from src.router import ask_model

A_GRADES = ("A", "B", "C", "D", "E", "F", "O")          # A-E pass; F and O are fails (checker meta.pass_grades)
O_GRADES = ("A", "B", "C", "D", "E", "U")
SUBJECTS = sorted(RULES["taxonomy"])
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15}

ASK_SUBJECTS = ("Which A Level subjects did you get those grades in? For example: Mathematics A, Physics B, "
                "Chemistry C. You can also enter them in the form in the sidebar.")
ASK_RESULTS = ("To check what you can study, please tell me your A Level subjects and grades, for example: "
               "Mathematics A, Physics B, Chemistry C. If you know them, add your O Level English and Mathematics "
               "grades and number of O Level passes. You can also use the form in the sidebar.")
ASK_GRADES = "What grade did you get in {subjects} at A Level? For example: {example}."

EXTRACT_PROMPT = """You extract an applicant's exam results from their messages to the Midlands State University admissions assistant.
Return ONLY a JSON object, no other text, in exactly this shape:
{"a_level": [{"subject": "<subject>", "grade": "<A|B|C|D|E|F|O or null>"}], "o_level": {"english": "<A|B|C|D|E|U>", "mathematics": "<A|B|C|D|E|U>", "passes": <integer>}}
Rules:
- Use only values the applicant clearly stated. Never guess or invent a subject, grade or number.
- Subjects with grades are A Level results unless the applicant says they are O Level. Only English, Mathematics and the number of passes go in "o_level", and only when the applicant says they are O Level results.
- A Level grade "O" (an O Level pass awarded at A Level) and "F" are valid A Level grades; keep them in "a_level".
- Leave out any field that was not stated (omit unknown o_level keys; use "a_level": [] if no A Level subjects were named).
- A grade without a named subject must not be attached to any subject. A subject without a stated grade gets "grade": null.
- If the applicant corrects a value, use the latest one.
- "passes" is the number of O Level subjects passed, only if the applicant gave that number.
- Lines starting "Assistant asked:" show what the assistant asked. If it asked for O Level results, the applicant's reply after it gives O Level results (English, Mathematics, number of passes), not A Level results."""


@dataclass
class Extraction:
    a_level: Dict[str, str] = field(default_factory=dict)          # subject -> grade (A-F, O)
    o_level: Dict[str, Any] = field(default_factory=dict)          # English / Mathematics -> grade, passes -> int
    missing: List[str] = field(default_factory=list)               # required details still missing
    to_confirm: List[str] = field(default_factory=list)            # optional details not given
    follow_up: Optional[str] = None                                 # one short question when A Level data is missing
    source: str = "conversation"                                    # conversation | form
    method: str = "model"                                           # parsed | model | form | earlier
    dropped: List[str] = field(default_factory=list)                # model values rejected by validation
    error: Optional[str] = None

    @property
    def ready(self) -> bool:
        return bool(self.a_level) and not self.missing

    def checker_o_level(self) -> Optional[Dict[str, Any]]:
        """The checker's o_level argument: None when nothing is known (everything 'to confirm')."""
        return dict(self.o_level) or None

    def summary(self) -> Dict[str, Any]:
        return {"a_level": self.a_level, "o_level": self.o_level, "missing": self.missing,
                "to_confirm": self.to_confirm, "source": self.source, "method": self.method,
                "dropped": self.dropped, "error": self.error}


def parse_json_object(text: str) -> Optional[dict]:
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _mentions_subject(subject: str, raw: str, text: str) -> bool:
    names = {subject.lower(), (raw or "").strip().lower()} | {a for a, s in RULES["aliases"].items() if s == subject}
    return any(n and re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", text) for n in names)


def _mentions_grade(grade: str, original: str) -> bool:
    """An upper-case letter on its own ('Maths A') or after = or : ('maths=a')."""
    return bool(re.search(rf"(?<![A-Za-z]){grade}(?![A-Za-z])", original) or
                re.search(rf"[=:]\s*{grade.lower()}(?![a-z])", original))


def _mentions_number(n: int, text: str) -> bool:
    return bool(re.search(rf"(?<!\d){n}(?!\d)", text)) or any(w in text.split() and v == n for w, v in NUMBER_WORDS.items())


def validate(data: Optional[dict], user_text: str) -> Extraction:
    """Keep only well-formed values that appear in what the user wrote; then work out what is missing."""
    ex, low = Extraction(), (user_text or "").lower()
    data = data or {}
    ungraded = []
    for row in data.get("a_level") or []:
        if not isinstance(row, dict) or not isinstance(row.get("subject"), str) or not row["subject"].strip():
            continue
        raw, subject = row["subject"], norm(row["subject"])
        grade = str(row.get("grade") or "").strip().upper()
        if not _mentions_subject(subject, raw, low):
            ex.dropped.append(f"A Level subject not in the conversation: {raw}")
            continue
        if grade in A_GRADES and _mentions_grade(grade, user_text):
            ex.a_level[subject] = grade
        elif grade:
            ex.dropped.append(f"A Level grade not valid or not in the conversation: {raw} {grade}")
            ungraded.append(subject)
        else:
            ungraded.append(subject)
    o = data.get("o_level") if isinstance(data.get("o_level"), dict) else {}
    for key, name, words in (("english", "English", ("english",)), ("mathematics", "Mathematics", ("math",))):
        g = str(o.get(key) or "").strip().upper()
        if g and g in O_GRADES and any(w in low for w in words):
            ex.o_level[name] = g
        elif g:
            ex.dropped.append(f"O Level {name} grade not valid or not in the conversation: {g}")
    passes = o.get("passes")
    if passes is not None:
        try:
            n = int(passes)
        except (TypeError, ValueError):
            n = -1
        if 0 <= n <= 20 and _mentions_number(n, low):
            ex.o_level["passes"] = n
        else:
            ex.dropped.append(f"number of O Level passes not valid or not in the conversation: {passes}")
    ungraded = [s for s in ungraded if s not in ex.a_level]
    if not ex.a_level and not ungraded:
        ex.missing.append("A Level subjects and grades")
        ex.follow_up = ASK_SUBJECTS if re.search(r"(?<![A-Za-z])[A-E](?![A-Za-z])", user_text or "") else ASK_RESULTS
    elif ungraded:
        ex.missing.append("A Level grades for " + ", ".join(ungraded))
        names = ungraded[0] if len(ungraded) == 1 else ", ".join(ungraded[:-1]) + " and " + ungraded[-1]
        ex.follow_up = ASK_GRADES.format(subjects=names,
                                         example=", ".join(f"{s} B" for s in ungraded))
    ex.to_confirm = _optional_missing(ex.o_level)
    return ex


def _optional_missing(o_level: Dict[str, Any]) -> List[str]:
    return [label for key, label in (("English", "O Level English grade"), ("Mathematics", "O Level Mathematics grade"),
                                     ("passes", "number of O Level passes")) if key not in o_level]


def extract_grades(conversation: List[Any], llm: Any, settings: GenerationSettings) -> Extraction:
    """Ask the model for JSON over the conversation (oldest first) and validate it. Raises LLMError.
    Items are the applicant's messages (str) or ("assistant", question) for what the assistant asked; only the
    applicant's own words count as evidence for a value."""
    text = "\n".join(m for m in conversation if isinstance(m, str) and m)
    lines = [f"Assistant asked: {m[1]}" if isinstance(m, tuple) else f"Applicant: {m}" for m in conversation if m]
    reply = ask_model(llm, settings, EXTRACT_PROMPT, "Conversation, oldest first:\n" + "\n".join(lines), max_tokens=1024)
    data = parse_json_object(reply)
    ex = validate(data, text)
    if data is None:
        ex.error = "the model did not return valid JSON"
    return ex


def from_form(a_level_rows: List[tuple], english: Optional[str] = None, mathematics: Optional[str] = None,
              passes: Optional[int] = None) -> Extraction:
    """Sidebar form values (already restricted to valid choices by the widgets)."""
    ex = Extraction(source="form", method="form")
    for subject, grade in a_level_rows:
        if subject and grade in A_GRADES:
            ex.a_level[subject] = grade
    if english in O_GRADES:
        ex.o_level["English"] = english
    if mathematics in O_GRADES:
        ex.o_level["Mathematics"] = mathematics
    if passes is not None:
        ex.o_level["passes"] = int(passes)
    if not ex.a_level:
        ex.missing.append("A Level subjects and grades")
        ex.follow_up = ASK_RESULTS
    ex.to_confirm = _optional_missing(ex.o_level)
    return ex


# ------------------------------------------------------------------ deterministic first, model only when needed
def combine(previous: Optional[Extraction], new: Extraction) -> Extraction:
    """Corrections and additions: newly given values win. A completely different set of two or more A Levels (no
    subject in common with the earlier ones) replaces the earlier A Levels instead of being added to them."""
    if previous is None:
        return new
    if new.a_level and len(new.a_level) >= 2 and not set(new.a_level) & set(previous.a_level):
        a_level = dict(new.a_level)
    else:
        a_level = {**previous.a_level, **new.a_level}
    return Extraction(a_level=a_level, o_level={**previous.o_level, **new.o_level}, source=previous.source,
                      method=new.method, dropped=new.dropped, error=new.error)


def finish(ex: Extraction, subjects_without_grade: List[str] = (), unattached_grades: bool = False) -> Extraction:
    """Work out what is still missing and the one short question to ask, if any."""
    ex.missing, ex.follow_up = [], None
    ungraded = [s for s in subjects_without_grade if s not in ex.a_level]
    if not ex.a_level:
        if ungraded:
            ex.missing.append("A Level grades for " + ", ".join(ungraded))
            names = ungraded[0] if len(ungraded) == 1 else ", ".join(ungraded[:-1]) + " and " + ungraded[-1]
            ex.follow_up = ASK_GRADES.format(subjects=names, example=", ".join(f"{s} B" for s in ungraded))
        else:
            ex.missing.append("A Level subjects and grades")
            ex.follow_up = ASK_SUBJECTS if unattached_grades else ASK_RESULTS
    ex.to_confirm = _optional_missing(ex.o_level)
    return ex


def read_results(message: str, previous: Optional[Extraction], conversation: List[Any], llm: Any = None,
                 settings: Optional[GenerationSettings] = None, o_level_context: bool = False) -> Extraction:
    """Results for the eligibility check after this message. The deterministic parser handles almost every message;
    the model (extract_grades) is asked only when grade letters cannot be attached to subjects although subjects are
    named. Raises LLMError only from that model call."""
    from src.results_parser import parse_results
    parsed = parse_results(message, o_level_context=o_level_context)
    if parsed.confident or not parsed.subjects_without_grade and not parsed.a_level:
        if parsed.found_anything:
            ex = combine(previous, Extraction(a_level=parsed.a_level, o_level=parsed.o_level, method="parsed"))
        elif previous is not None:
            ex = combine(previous, Extraction(method="earlier"))
        else:
            ex = Extraction(method="parsed")
        return finish(ex, parsed.subjects_without_grade, unattached_grades=not parsed.confident)
    if llm is None or settings is None:
        ex = combine(previous, Extraction(a_level=parsed.a_level, o_level=parsed.o_level, method="parsed"))
        return finish(ex, parsed.subjects_without_grade, unattached_grades=True)
    model = extract_grades(conversation, llm, settings)
    model.method = "model"
    return finish(combine(previous, model) if (model.a_level or model.o_level) else combine(previous, model),
                  [], unattached_grades=not model.a_level)
