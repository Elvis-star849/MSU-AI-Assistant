"""
Application safeguards around the grounded answer. They never rewrite the model's answer (the evaluated behaviour is
kept); they check inputs and evidence, and attach visible notes for the reader.

- clean_question   bounded, control-character-free question text
- screen_evidence  drops a retrieved passage that contains instruction-like text aimed at the model (prompt
                   injection through documents). Verified to match no passage of public KB 0005, so the evaluated
                   messages are unchanged; it protects against future document uploads.
- review_answer    notes for: no evidence citation, citations to evidence numbers that do not exist, admissions
                   topics (verify with MSU Admissions), evidence mixing the 2027 intake advert with older yearbook
                   regulations (the advert applies to the 2027 intake), and, on the public profile only, any mention of
                   an intake advert (not among the public sources).
"""
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

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
NOTE_ADMISSIONS_INTAKE = ("For the January/February 2027 intake, the 2027 intake advert is the current source; yearbook "
                          "regulations may be older. Confirm entry requirements with MSU Admissions before applying.")
NOTE_MIXED_SOURCES = ("The passages used include the 2027 intake advert (current information for the January/February "
                      "2027 intake) and MSU yearbook regulations (older). Where they differ, the 2027 advert applies.")
ADVERT_SOURCE = "MSU January/February 2027 Intake Advert"
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


def review_answer(question: str, answer: str, n_evidence: int, public_profile: bool = True, intake: bool = False,
                  sources: Optional[List[str]] = None) -> List[Dict[str, str]]:
    """intake: the 2027 intake advert is among the knowledge sources (profile c3_intake_0006); sources: the source
    document of each evidence passage given to the model, in evidence-number order. The advert-vs-yearbook note is
    shown only when the answer cites at least one advert passage AND one yearbook passage."""
    notes: List[Dict[str, str]] = []
    text = answer or ""
    cited = cited_numbers(text)
    if not cited and not DECLINE.search(text):
        notes.append({"kind": "citation", "text": NOTE_NO_CITATION})
    bad = [n for n in cited if n < 1 or n > n_evidence]
    if bad:
        notes.append({"kind": "citation", "text": NOTE_BAD_CITATION.format(nums=", ".join(map(str, bad)))})
    cited_sources = [sources[n - 1] for n in cited if sources and 1 <= n <= len(sources)]
    if intake and ADVERT_SOURCE in cited_sources and any("Yearbook" in (s or "") for s in cited_sources):
        notes.append({"kind": "sources", "text": NOTE_MIXED_SOURCES})
    if ADMISSIONS.search(question or "") or ADMISSIONS.search(text):
        notes.append({"kind": "admissions", "text": NOTE_ADMISSIONS_INTAKE if intake else NOTE_ADMISSIONS})
    if public_profile and ADVERT.search(text):
        notes.append({"kind": "advert", "text": NOTE_ADVERT})
    return notes
