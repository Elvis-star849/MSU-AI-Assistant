"""
Eligibility answers, rendered deterministically from the eligibility engine (src/eligibility_engine.py). No language
model writes any part of an eligibility answer, so a model cannot add or drop programmes, move a programme between
categories, change a count or add a requirement.

    answer_eligibility(extraction, question, show_all=False) -> EligibilityAnswer

The answer has a short summary (text) and full per-outcome sections (sections) that the app shows as tabs:
- ordering is deterministic: programmes whose rule names the applicant's own subjects first, then faculty, then name;
- a programme the applicant names ("Can I do Computer Science?") is answered first (exact name match before related);
- conditional matches always say what is unconfirmed (O Level results, an open rule question, an assumed subject
  category, employment, ...); missing O Level results are asked for;
- every answer ends with the disclaimer that the Admissions Office decides.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.eligibility import RULES
from src.eligibility_engine import (CONDITIONAL, MEETS, NOT_MET, OTHER_ROUTE, Evaluation, ProgrammeResult, evaluate)
from src.extract_grades import Extraction

DISCLAIMER = ("This is based on the advertised requirements for the January/February 2027 intake. Meeting the "
              "advertised requirements does not guarantee a place: the Admissions Office makes the final decision.")
ASK_O_LEVEL = ("To turn the conditional matches into a full check, please tell me your O Level results: your English "
               "Language grade, your Mathematics grade and how many O Level subjects you passed at grade C or better "
               "(or enter them in the form in the sidebar).")
TITLES = {MEETS: "Meets the advertised requirements", CONDITIONAL: "Conditional matches (not yet a full eligibility result)",
          NOT_MET: "Does not meet the advertised requirements",
          OTHER_ROUTE: "Other entry routes (diploma, qualification or employment; not decided by grades)"}
SHORT = {MEETS: "meet the advertised requirements", CONDITIONAL: "conditional matches",
         NOT_MET: "do not meet the requirements", OTHER_ROUTE: "other entry routes"}
ICON = {MEETS: "✅", CONDITIONAL: "🟡", NOT_MET: "❌", OTHER_ROUTE: "➡️"}
HIGHLIGHTS = 5
MAX_ASKED = 5
ASKS_WHY = re.compile(r"\b(?:why|reason|not eligible|cannot|can't|can not|don't qualify|do not qualify|not qualify)\b", re.I)


@dataclass
class EligibilityAnswer:
    text: str                                         # summary (or full listing for "show all") as Markdown
    evaluation: Evaluation
    sections: Dict[str, List[ProgrammeResult]]        # every programme, per outcome, in display order
    counts: Dict[str, int]
    asked: List[Dict[str, Any]] = field(default_factory=list)
    asked_for_o_level: bool = False


# ------------------------------------------------------------------ ordering and programme matching
def order(results: List[ProgrammeResult]) -> List[ProgrammeResult]:
    return sorted(results, key=lambda r: (-r.relevance, r.faculty, r.programme))


GENERIC_WORDS = {"science", "sciences", "studies", "management", "technology", "technologies", "engineering", "education",
                 "honours", "degree", "applied", "bachelor", "development", "systems", "and", "with", "diploma",
                 "the", "can", "for", "you", "did", "get", "got", "how", "why", "not", "any", "all", "what", "study",
                 "level", "levels", "grade", "grades", "have", "qualify", "programme", "programmes", "course", "courses",
                 "show", "about", "into", "apply", "doing"}
O_LEVEL_NAMES = {"english", "english language", "maths", "math", "mathematics", "science", "combined science",
                 "integrated science"}
_SUBJECT_NAMES = sorted(set(RULES["taxonomy"]) | set(RULES["aliases"]) | O_LEVEL_NAMES, key=len, reverse=True)
_SUBJECT_WITH_GRADE = re.compile(r"\b(?:%s)\s*[=:]?\s*[A-FOU]\b" % "|".join(map(re.escape, _SUBJECT_NAMES)), re.I)


def _short_name(programme: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*", " ", programme.rsplit(" in ", 1)[-1]).strip().lower()


def _words(text: str) -> set:
    words = {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in re.findall(r"[a-z]{3,}", (text or "").lower())}
    return words - GENERIC_WORDS


def mentioned(results: List[ProgrammeResult], question: str) -> List[Dict[str, Any]]:
    """Programmes the question names: exact matches (the whole name, or the whole part after 'in') first, then
    related ones (a distinctive word). The applicant's own results ('Mathematics A') never count as names."""
    q = _SUBJECT_WITH_GRADE.sub(" ", question or "").lower()
    words = _words(q)
    exact, related = [], []
    for r in order(results):
        name = _short_name(r.programme)
        if r.programme.lower() in q or (len(name) >= 4 and re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", q)):
            exact.append({"match": "exact", "result": r})
        elif words & _words(name):
            related.append({"match": "related", "result": r})
    return (exact + related)[:MAX_ASKED]


# ------------------------------------------------------------------ rendering
GENERIC_O_LEVEL = re.compile(r"^O Level(?:: at least \d+ passes at grade [A-E] or better| English Language| Mathematics)$")


def _confirm_items(r: ProgrammeResult, o_level_given: bool) -> List[str]:
    """What to confirm for this programme; without any O Level results the general O Level items are said once for
    all programmes (ASK_O_LEVEL) instead of under every programme."""
    return [t for t in r.to_confirm if o_level_given or not GENERIC_O_LEVEL.match(t)]


INTERPRETATION = re.compile(r"\b(?:interpreted as|modelled as|treated as)\b", re.I)


PREFERRED = re.compile(r"^Preferred \(not required\):\s*", re.I)
PREFERRED_TEXT = "The advert says “preferably”: "
PREFERRED_TAIL = " Whether these are required is not confirmed; check with the Admissions Office."


def _neutral(note: str) -> str:
    """The rules file's 'Preferred (not required)' is an interpretation of the advert's 'preferably' (an open question
    for MSU, see HUMAN_REVIEW.md B4/B5): quote the advert's word instead of deciding it."""
    if not PREFERRED.match(note):
        return note
    return PREFERRED_TEXT + PREFERRED.sub("", note).rstrip() + PREFERRED_TAIL


def _notes(r: ProgrammeResult) -> List[str]:
    """Interpretation notes matter only when the match depends on that interpretation (an open question)."""
    return [_neutral(n) for n in r.notes if r.questions or not INTERPRETATION.search(n)]


def programme_line(r: ProgrammeResult, detail: bool = True, o_level_given: bool = True) -> str:
    modes = ", ".join(r.modes) if r.modes else "modes not stated"
    line = f"- **{r.programme}** — {modes}; {r.duration} (advert p. {r.source_page})"
    if not detail:
        return line
    sub = []
    if r.outcome == CONDITIONAL:
        sub += [f"to confirm: {t}" for t in _confirm_items(r, o_level_given)] + [f"assumption: {x}" for x in r.reasons]
        sub += [f"open question for MSU: {q}" for q in r.questions]
    elif r.outcome == NOT_MET:
        sub += [f"reason: {x}" for x in r.reasons]
        if r.alternative_routes:
            sub.append("other ways in (as advertised): " + " | ".join(r.alternative_routes))
    elif r.outcome == OTHER_ROUTE:
        sub.append("requirements as advertised: " + " | ".join(r.requirements))
    sub += [f"note: {n}" for n in _notes(r)] if r.outcome in (MEETS, CONDITIONAL) else []
    return line + "".join(f"\n    - {s}" for s in sub)


def by_faculty(results: List[ProgrammeResult], detail: bool = True, o_level_given: bool = True) -> str:
    groups: Dict[str, List[ProgrammeResult]] = {}
    for r in results:
        groups.setdefault(r.faculty, []).append(r)
    return "\n".join(f"\n*{fac}*\n" + "\n".join(programme_line(r, detail) for r in items) for fac, items in groups.items())


def summary_line(evaluation: Evaluation, counts: Dict[str, int]) -> str:
    parts = " · ".join(f"{ICON[o]} **{counts[o]}** {SHORT[o]}" for o in (MEETS, CONDITIONAL, NOT_MET, OTHER_ROUTE))
    return f"**A Level points (best three passes): {evaluation.points_best_three}**  \n{parts}"


def _asked_block(asked: List[Dict[str, Any]], o_level_given: bool) -> str:
    lines = ["**The programme(s) you asked about**"]
    for a in asked:
        r = a["result"]
        lines.append(programme_line(r, True, o_level_given).replace("- **", f"- {ICON[r.outcome]} {TITLES[r.outcome]}: **", 1))
    return "\n".join(lines)


def render(evaluation: Evaluation, sections: Dict[str, List[ProgrammeResult]], asked: List[Dict[str, Any]],
           question: str, ask_o_level: bool, show_all: bool) -> str:
    counts = {o: len(v) for o, v in sections.items()}
    out = [summary_line(evaluation, counts)]
    if evaluation.failed_grades:
        out.append("Not passes, not counted: " + ", ".join(evaluation.failed_grades) + ".")
    if asked:
        out.append(_asked_block(asked, evaluation.o_level_given))
    if show_all:
        for o in (MEETS, CONDITIONAL, NOT_MET, OTHER_ROUTE):
            if sections[o]:
                out.append(f"### {ICON[o]} {TITLES[o]} ({counts[o]})" + by_faculty(sections[o], o != OTHER_ROUTE,
                                                                                    evaluation.o_level_given))
    else:
        top = sections[MEETS][:HIGHLIGHTS] or sections[CONDITIONAL][:HIGHLIGHTS]
        if top:
            label = "Best matches for your subjects" if sections[MEETS] else "Closest conditional matches"
            out.append(f"**{label}**\n" + "\n".join(programme_line(r, r.outcome == CONDITIONAL, evaluation.o_level_given)
                                                    for r in top))
        if ASKS_WHY.search(question or "") and not asked and sections[NOT_MET]:
            out.append("**Some programmes you do not meet the requirements for**\n"
                       + "\n".join(programme_line(r, True, evaluation.o_level_given) for r in sections[NOT_MET][:HIGHLIGHTS]))
        out.append("The complete lists are in the tabs below (or type **show all**).")
    if ask_o_level:
        out.append(ASK_O_LEVEL)
    out.append(DISCLAIMER)
    return "\n\n".join(out)


def answer_eligibility(extraction: Extraction, question: str, show_all: bool = False, **_ignored) -> EligibilityAnswer:
    evaluation = evaluate(extraction.a_level, extraction.checker_o_level())
    sections = {o: order(evaluation.by_outcome(o)) for o in (MEETS, CONDITIONAL, NOT_MET, OTHER_ROUTE)}
    asked = mentioned(evaluation.results, question)
    ask_o = bool(extraction.to_confirm) and bool(sections[CONDITIONAL])
    text = render(evaluation, sections, asked, question, ask_o, show_all)
    return EligibilityAnswer(text, evaluation, sections, {o: len(v) for o, v in sections.items()}, asked, ask_o)
