"""
Deterministic eligibility engine: classifies every programme for one applicant. No AI is involved.

    evaluate(a_level, o_level=None) -> Evaluation

Inputs: the corrected rules (src/eligibility/MSU_Eligibility_Rules.json, the checker's own data) and the confirmation
layer (src/eligibility/rule_overrides.json). Four outcomes, each with reasons and the advert page:

- MEETS        the applicant meets the advertised requirements on a reading that does not depend on any open
               question: the strict reading of an ambiguous rule, subjects whose category the advert evidences,
               complete O Level results, no extra condition.
- CONDITIONAL  meets the requirements only on the lenient reading, or O Level results / another condition (employment,
               one sitting, an African language at O Level, ...) still need to be confirmed. Never presented as
               eligibility.
- NOT_MET      does not meet even the lenient reading, or an O Level requirement fails; alternative routes from the
               advert (diploma, employment, mature entry) are attached.
- OTHER_ROUTE  programmes not decided by grades (diploma / qualification / employment routes); advertised text only.

Relationship to the checker (src/eligibility/eligibility_checker.check, kept unchanged): the lenient reading is a
superset of the coded rule and the strict reading a subset, so the checker's 'eligible' programmes are always MEETS or
CONDITIONAL, and MEETS is always among the checker's 'eligible'. tests/test_eligibility_engine.py verifies this on
thousands of random applicants. O Level checks reuse the checker's own o_check().
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.eligibility import eligibility_checker as ec

MEETS, CONDITIONAL, NOT_MET, OTHER_ROUTE = "meets", "conditional", "not_met", "other_route"
OUTCOMES = (MEETS, CONDITIONAL, NOT_MET, OTHER_ROUTE)
RULES = ec.D
OVERRIDES = json.loads((Path(ec.HERE) / "rule_overrides.json").read_text(encoding="utf-8"))
PTS, PASS, TAX = ec.PTS, ec.PASS, ec.TAX
CATEGORIES = ("SCI", "COM", "ARTS", "LANG")
CATEGORY_NAMES = {"SCI": "science", "COM": "commercial", "ARTS": "arts/humanities", "LANG": "language"}


def _verified_members(cat: str) -> set:
    spec = OVERRIDES["subject_evidence"][cat]["verified"]
    return {s for s, cats in TAX.items() if cat in cats} if isinstance(spec, str) else set(spec)


VERIFIED = {c: _verified_members(c) for c in CATEGORIES}
CONDITIONAL_MEMBERS = {c: OVERRIDES["subject_evidence"][c].get("conditional", {}) for c in CATEGORIES}
SOCIAL = OVERRIDES["social_science_extension"]


@dataclass
class ProgrammeResult:
    id: str
    programme: str
    faculty: str
    modes: List[str]
    duration: str
    source_page: int
    outcome: str
    reasons: List[str] = field(default_factory=list)          # why not MEETS (conditional) or why NOT_MET
    to_confirm: List[str] = field(default_factory=list)       # O Level / other details still to confirm
    questions: List[str] = field(default_factory=list)        # open rule questions for MSU Admissions
    notes: List[str] = field(default_factory=list)            # modeller's notes from the rules file
    requirements: List[str] = field(default_factory=list)     # as advertised
    alternative_routes: List[str] = field(default_factory=list)
    relevance: float = 0.0                                    # how strongly the rule names the applicant's subjects


@dataclass
class Evaluation:
    results: List[ProgrammeResult]
    passed: Dict[str, str]
    failed_grades: List[str]
    points_best_three: int
    o_level_given: bool

    def by_outcome(self, outcome: str) -> List[ProgrammeResult]:
        return [r for r in self.results if r.outcome == outcome]

    def counts(self) -> Dict[str, int]:
        return {o: len(self.by_outcome(o)) for o in OUTCOMES}

    def get(self, programme_id: str) -> Optional[ProgrammeResult]:
        return next((r for r in self.results if r.id == programme_id), None)


# ------------------------------------------------------------------ A Level matching
def _cats(subject: str, mode: str, extra: Dict[str, List[str]]) -> set:
    """Categories of a subject. mode 'verified': only advert-evidenced membership; 'coded': the rules taxonomy;
    'lenient': coded plus programme-specific extensions (extra)."""
    if mode == "verified":
        cats = {c for c in CATEGORIES if subject in VERIFIED[c]}
    else:
        cats = set(TAX.get(subject, []))
    if mode == "lenient":
        cats |= {c for c, subs in extra.items() if subject in subs}
    return cats


def _slot_ok(slot: Dict[str, Any], subject: str, grade: str, mode: str, extra: Dict[str, List[str]]) -> bool:
    ok = any(t == "ANY" or t == subject or (t in CATEGORIES and t in _cats(subject, mode, extra))
             for t in slot["any_of"])
    g = slot.get("min_grade")
    return ok and (g is None or PTS[grade] >= PTS[g])


def _assign(slots: List[Dict[str, Any]], passed: Dict[str, str], mode: str,
            extra: Dict[str, List[str]]) -> Optional[List[str]]:
    subjects = sorted(passed)                               # deterministic search order

    def go(i, used):
        if i == len(slots):
            return []
        for s in subjects:
            if s not in used and _slot_ok(slots[i], s, passed[s], mode, extra):
                rest = go(i + 1, used | {s})
                if rest is not None:
                    return [s] + rest
        return None
    return go(0, frozenset())


def _points_ok(rule: Dict[str, Any], passed: Dict[str, str], assignment: List[str], points_subjects: Optional[int]) -> bool:
    need = rule.get("min_points")
    if not need:
        return True
    if points_subjects:                                     # strict: points over the named subject(s) plus best others
        first = [PTS[passed[s]] for s in assignment[:1]]
        others = sorted((PTS[g] for s, g in passed.items() if s not in assignment[:1]), reverse=True)
        return sum(first + others[:points_subjects - len(first)]) >= need
    return sum(sorted((PTS[g] for g in passed.values()), reverse=True)[:3]) >= need


def _slot_text(slots: List[Dict[str, Any]]) -> str:
    def one(s):
        opts = [f"any {CATEGORY_NAMES[t]} subject" if t in CATEGORIES else "any subject" if t == "ANY" else t
                for t in s["any_of"]]
        return " or ".join(opts) + (f" (grade {s['min_grade']} or better)" if s.get("min_grade") else "")
    return "; ".join(one(s) for s in slots)


def _category_caveats(slots, assignment, passed) -> List[str]:
    """Reasons a match depends on an unconfirmed subject category."""
    out = []
    for slot, subj in zip(slots, assignment):
        if subj in slot["any_of"] or "ANY" in slot["any_of"]:
            continue
        for t in slot["any_of"]:
            if t in CATEGORIES and t in TAX.get(subj, []) and subj not in VERIFIED[t]:
                out.append(CONDITIONAL_MEMBERS[t].get(subj, f"{subj} is counted as a {CATEGORY_NAMES[t]} subject; "
                                                             "the advert does not say so."))
    return out


def _alternatives(p: Dict[str, Any]) -> List[str]:
    lines = [l for l in p["requirements_as_advertised"]
             if any(w in l.lower() for w in ("diploma", "hnd", "national certificate", "employ", "znqf", "certificate",
                                             "professional qualification", "cima", "acca"))]
    if p.get("has_mature_entry"):
        lines += [t if t.lower().startswith("mature") else f"Mature entry: {t}" for t in p.get("mature_entry_text") or []]
    return lines[:4]


# ------------------------------------------------------------------ O Level check
PASS_ONLY = "PASS"          # an O Level subject the applicant passed without giving the grade ("passes including Maths")


def o_check(rule: Dict[str, Any], o_level: Optional[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    """The checker's o_check, extended for PASS_ONLY values. An O Level 'pass' in the advert's sense is grade C or
    better, so PASS_ONLY satisfies a C requirement; a higher requirement (e.g. Mathematics B) becomes 'to confirm',
    never a fail. Without PASS_ONLY values this is exactly ec.o_check."""
    if not o_level or not any(str(v).upper() == PASS_ONLY for k, v in o_level.items() if k.lower() != "passes"):
        return ec.o_check(rule, o_level)
    pass_only = {ec.norm_o(k) for k, v in o_level.items() if k.lower() != "passes" and str(v).upper() == PASS_ONLY}
    graded = {k: ("C" if str(v).upper() == PASS_ONLY else v) for k, v in o_level.items()}
    fails, confirm = ec.o_check(rule, graded)
    oo = {ec.norm_o(k): str(v).upper() for k, v in graded.items() if k.lower() != "passes"}
    for subject, grade in rule["required_subjects"].items():
        need = grade or rule["min_pass_grade"]
        have_key = next((k for k in oo if k in pass_only and ec.find_o({k: "C"}, subject) is not None), None)
        if have_key is None or ec.O_ORDER[need] <= ec.O_ORDER["C"]:
            continue
        fails = [f for f in fails if not f.startswith(f"O Level {subject} needs grade")]
        confirm.append(f"O Level {subject} at grade {need} or better (you said you passed it; the grade was not given)")
    return fails, confirm


# ------------------------------------------------------------------ evaluation
def _relevance(slots, passed) -> float:
    """How strongly the rule is built around the applicant's own subjects, in three tiers (score = 100*tier1 +
    10*tier2 + tier3):
    1. how many different applicant subjects the rule names (not just categorises), one per slot;
    2. slots the applicant fills through a specific category ('any commercial subject' beats 'any subject'), each
       counting 0.5 / (number of categories the slot allows);
    3. specificity of the named matches: 1 / (number of subjects the slot names), so 'Mathematics' alone beats
       'one of seven sciences'."""
    count, by_category, specificity, used = 0, 0.0, 0.0, set()
    for slot in sorted(slots, key=lambda s: len(s["any_of"])):
        named = [t for t in slot["any_of"] if t not in CATEGORIES and t != "ANY"]
        hit = next((t for t in named if t in passed and t not in used), None)
        if hit:
            used.add(hit)
            count += 1
            specificity += 1.0 / len(named)
            continue
        cats = [t for t in slot["any_of"] if t in CATEGORIES]
        sub = next((s for s in sorted(passed) if s not in used and set(TAX.get(s, [])) & set(cats)), None)
        if sub:
            used.add(sub)
            by_category += 0.5 / len(cats)
    return round(100 * count + 10 * by_category + specificity, 4)


def evaluate_programme(p: Dict[str, Any], passed: Dict[str, str], o_level: Optional[Dict[str, Any]]) -> ProgrammeResult:
    ov = OVERRIDES["programmes"].get(p["id"], {})
    res = ProgrammeResult(p["id"], p["programme"], p["faculty"], p["modes"], p["duration"], p["source_page"], NOT_MET,
                          notes=list(p.get("modelling_notes") or []), requirements=list(p["requirements_as_advertised"]))
    if p["route"] == "other_qualification":
        res.outcome = OTHER_ROUTE
        return res
    o_fails, o_confirm = o_check(p["o_level_rule"], o_level)
    extra_conditions = list(ov.get("extra_conditions", []))
    reasons, questions = [], []
    if p["route"] == "a_level":
        rule = p["a_level_rule"]
        coded = rule["slots"]
        strict = (ov.get("strict") or {}).get("slots", coded)
        lenient = (ov.get("lenient") or {}).get("slots", coded)
        extra = {c: list(v) for c, v in (ov.get("lenient_extra") or {}).items()}
        if ov.get("social_sciences"):
            extra.setdefault("ARTS", []).extend(SOCIAL["subjects"])
        res.relevance = _relevance(coded, passed)
        strict_v = _assign(strict, passed, "verified", {})
        strict_ok = strict_v is not None and _points_ok(rule, passed, strict_v, (ov.get("strict") or {}).get("points_subjects"))
        if not strict_ok:
            lenient_a = _assign(lenient, passed, "lenient", extra)
            if lenient_a is None or not _points_ok(rule, passed, lenient_a, None):
                res.reasons = [f"A Level requirement not met: {_slot_text(coded)}"
                               + (f"; at least {rule['min_points']} points" if rule.get("min_points") else "")] + o_fails
                res.alternative_routes = _alternatives(p)
                return res
            # met only on a reading that depends on an open question: say which
            strict_coded = _assign(strict, passed, "coded", {})
            if strict_coded is not None and _points_ok(rule, passed, strict_coded, (ov.get("strict") or {}).get("points_subjects")):
                reasons += _category_caveats(strict, strict_coded, passed)
            else:
                if ov.get("question"):
                    questions.append(ov["question"])
                coded_a = _assign(coded, passed, "coded", {})
                if coded_a is None:                          # only the programme-specific extension makes it match
                    used = [s for s in lenient_a if any(s in subs for subs in extra.values())]
                    if any(s in SOCIAL["subjects"] for s in used) and ov.get("social_sciences"):
                        questions.append(SOCIAL["question"])
                    if ov.get("question_extra"):
                        questions.append(ov["question_extra"])
                else:
                    reasons += _category_caveats(coded, coded_a, passed)
            if not reasons and not questions:
                reasons.append("the match depends on how the advert wording is read")
        if rule.get("requires_employment"):
            extra_conditions.append("proof of employment in a relevant field (required by the advert)")
    if o_fails:
        res.reasons = o_fails
        res.alternative_routes = _alternatives(p)
        return res
    res.reasons, res.questions, res.to_confirm = reasons, questions, o_confirm + extra_conditions
    res.outcome = MEETS if not (reasons or questions or res.to_confirm) else CONDITIONAL
    return res


def normalise_a_level(a_level: Dict[str, str]) -> Tuple[Dict[str, str], List[str]]:
    passed, failed = {}, []
    for k, v in (a_level or {}).items():
        s, g = ec.norm(k), (v or "").strip().upper()
        if g in PASS:
            passed[s] = g
        else:
            failed.append(f"{s} ({g})")
    return passed, failed


def evaluate(a_level: Dict[str, str], o_level: Optional[Dict[str, Any]] = None) -> Evaluation:
    passed, failed = normalise_a_level(a_level)
    results = [evaluate_programme(p, passed, o_level) for p in RULES["programmes"]]
    return Evaluation(results, passed, failed, sum(sorted((PTS[g] for g in passed.values()), reverse=True)[:3]),
                      bool(o_level))


def open_questions() -> List[Dict[str, str]]:
    """Every rule question recorded in the confirmation layer (for the human-review report and admin page)."""
    names = {p["id"]: p["programme"] for p in RULES["programmes"]}
    out = []
    for pid, ov in OVERRIDES["programmes"].items():
        for key in ("question", "question_extra"):
            if ov.get(key):
                out.append({"id": pid, "programme": names.get(pid, pid), "question": ov[key]})
        if ov.get("social_sciences"):
            out.append({"id": pid, "programme": names.get(pid, pid), "question": SOCIAL["question"]})
    return out
