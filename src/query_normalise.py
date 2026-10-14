"""
Query clean-up before retrieval and generation (fix for misspelled or vague admissions questions).

- Corrects common misspellings of admissions vocabulary ("requrements" -> "requirements").
- Resolves relative intake phrases to the only advertised intake: "the following/next/this/upcoming/coming/current
  intake" -> "the 2027 intake".
Whole-word, case-insensitive replacements only; course codes, programme names and numbers are never touched. The
original question is still what the user sees in the chat.
"""
import re
from typing import Dict, List, Tuple

MISSPELLINGS: Dict[str, str] = {
    "requrements": "requirements", "requrement": "requirement", "requirments": "requirements",
    "requirment": "requirement", "requiremnts": "requirements", "requirememts": "requirements",
    "reqirements": "requirements", "reqirement": "requirement", "requiements": "requirements",
    "requierments": "requirements", "requiremets": "requirements", "requirents": "requirements",
    "entery": "entry", "enrty": "entry", "admision": "admission", "admisions": "admissions", "addmission": "admission",
    "admissoin": "admission", "programe": "programme", "programes": "programmes", "programm": "programme",
    "progamme": "programme", "progarmme": "programme", "dureation": "duration", "durration": "duration",
    "duraton": "duration", "eligibilty": "eligibility", "eligiblity": "eligibility", "qualifcation": "qualification",
    "qualifcations": "qualifications", "qualificatons": "qualifications", "intak": "intake", "inatke": "intake",
    "comencement": "commencement", "commencment": "commencement", "comence": "commence", "comences": "commences",
    "begining": "beginning", "computor": "computer", "sceince": "science", "scince": "science",
    "cirtificate": "certificate", "diplomma": "diploma",
}
_WORDS = re.compile(r"\b(" + "|".join(map(re.escape, sorted(MISSPELLINGS, key=len, reverse=True))) + r")\b", re.I)
_RELATIVE_INTAKE = re.compile(r"\b(?:the\s+)?(?:following|next|this|upcoming|coming|current|forthcoming|new)\s+intake\b",
                              re.I)


def normalise_query(question: str) -> Tuple[str, List[str]]:
    """Returns (normalised question, list of human-readable changes)."""
    changes: List[str] = []

    def fix(m: "re.Match") -> str:
        right = MISSPELLINGS[m.group(0).lower()]
        changes.append(f"{m.group(0)} → {right}")
        return right
    text = _WORDS.sub(fix, question)

    def intake(m: "re.Match") -> str:
        changes.append(f"{m.group(0)} → the 2027 intake")
        return "the 2027 intake"
    if not re.search(r"\b2027\b", text):
        text = _RELATIVE_INTAKE.sub(intake, text)
    return text, changes
