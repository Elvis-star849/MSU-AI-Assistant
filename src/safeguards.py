"""
Application safeguards around the grounded answer. They never rewrite the model's answer (the evaluated behaviour is
kept); they check inputs and evidence, and attach visible notes for the reader.

- clean_question   bounded, control-character-free question text
- screen_evidence  drops a retrieved passage that contains instruction-like text aimed at the model (prompt
                   injection through documents). Verified to match no passage of public KB 0005, so the evaluated
                   messages are unchanged; it protects against future document uploads.
- review_answer    notes for: no evidence citation, citations to evidence numbers that do not exist, admissions
                   topics (verify with MSU Admissions; the 2027 intake advert is not published here), and any mention
                   of an intake advert (not among the public sources).
"""
import re
import unicodedata
from typing import Any, Dict, List, Tuple

MAX_QUESTION_CHARS = 1000

INJECTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)"
    r"|disregard (all |the )?(previous|prior|above) "
    r"|system prompt|you are now |new instructions?:"
    r"|<\|im_start\|>|<\|system\|>|\[INST\]|###\s*(instruction|system)|do anything now|jailbreak", re.I)

CITATION = re.compile(r"Evidence\s*(\d+)|【\s*(?:Evidence\s*)?(\d+)")   # bare (5) / [5] are not citations ("five (5) O levels")
DECLINE = re.compile(r"do(?:es)? not contain|not (?:stated|provided|specified|mentioned|listed)|cannot (?:answer|provide|determine)"
                     r"|can[’']?t (?:help|answer|provide)|no information|not (?:in|among) the (?:supplied|provided)", re.I)
ADMISSIONS = re.compile(r"\bentry requirements?\b|\badmissions?\b|\bapply(?:ing)?\b|\bapplications?\b|\beligib"
                        r"|\bintake\b|\bqualifications?\b|\b[OA][\s'’-]?levels?\b|\btuition fees?\b|\bfees?\b",
                        re.I)   # word-bounded: 'face to face tuition' or 'feedback' must not trigger the admissions note
ADVERT = re.compile(r"\badvert", re.I)

NOTE_NO_CITATION = ("This answer does not cite an evidence passage. Check it against the sources below before "
                    "relying on it.")
NOTE_BAD_CITATION = "This answer cites evidence number(s) {nums} that were not retrieved. Rely only on the listed sources."
NOTE_ADMISSIONS = ("Admissions information here comes from the published yearbook regulations, which may be older than "
                   "current requirements. The 2027 intake advert is not yet published in this assistant. Confirm "
                   "entry requirements with MSU Admissions before applying.")
NOTE_ADVERT = ("The public sources of this assistant do not include the 2027 intake advert; treat any reference to an "
               "advert in this answer as unverified.")
NOTE_INJECTION = ("{n} retrieved passage(s) were withheld from the model because they contained instruction-like text.")


def clean_question(question: str) -> str:
    text = "".join(ch if ch in "\n\t" or unicodedata.category(ch)[0] != "C" else " " for ch in (question or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_QUESTION_CHARS:
        raise ValueError(f"Please shorten your question to at most {MAX_QUESTION_CHARS} characters.")
    return text


def screen_evidence(evidence: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    kept, withheld = [], []
    for item in evidence:
        (withheld if INJECTION.search(item.get("text") or "") else kept).append(item)
    return kept, withheld


def cited_numbers(answer: str) -> List[int]:
    return sorted({int(next(g for g in m.groups() if g)) for m in CITATION.finditer(answer or "")})


def review_answer(question: str, answer: str, n_evidence: int, public_profile: bool = True) -> List[Dict[str, str]]:
    notes: List[Dict[str, str]] = []
    text = answer or ""
    cited = cited_numbers(text)
    if not cited and not DECLINE.search(text):
        notes.append({"kind": "citation", "text": NOTE_NO_CITATION})
    bad = [n for n in cited if n < 1 or n > n_evidence]
    if bad:
        notes.append({"kind": "citation", "text": NOTE_BAD_CITATION.format(nums=", ".join(map(str, bad)))})
    if ADMISSIONS.search(question or "") or ADMISSIONS.search(text):
        notes.append({"kind": "admissions", "text": NOTE_ADMISSIONS})
    if public_profile and ADVERT.search(text):
        notes.append({"kind": "advert", "text": NOTE_ADVERT})
    return notes
