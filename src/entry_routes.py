"""
Admission-route discovery for one applicant profile (deterministic; no AI decides anything).

    assess(profile) -> Assessment      (every programme x every advertised route that the profile makes relevant)

Routes and their sources:
- normal_a_level  A Level route, decided by the eligibility engine (src/eligibility_engine.py) exactly as before;
- normal_o_level  the advert's O Level-only programmes (engine, O Level part only);
- special         entry with a post-school qualification (certificate, diploma, HND, degree, professional
                  qualification): the qualification lines of each programme's advert entry, plus the general Special
                  Entry regulation for degree holders (Humanities Yearbook 3.2, p. 129);
- mature          the 18 programmes whose advert entry states mature entry, with the conditions encoded in
                  src/eligibility/entry_routes.json (built from the advert wording; see build_entry_routes.py).

Statuses: MEETS (only for grade-decided routes whose every advertised condition is met), POSSIBLE (every condition we
can check is met; the Admissions Office still assesses relevance, recognition, interviews or tests), NEEDS_INFO
(something is still unknown or unconfirmed), NOT_MET (a stated condition is known not to be met). Special and mature
routes are never MEETS: "relevant", "recognised" and "suitability" are decided by the Admissions Office.
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.applicant_profile import ApplicantProfile, describe, describe_qualification
from src.eligibility import eligibility_checker as ec
from src.eligibility_engine import (CONDITIONAL, MEETS as E_MEETS, NOT_MET as E_NOT_MET, PASS_ONLY, RULES, Evaluation,
                                    evaluate, o_check)

ROUTES_FILE = Path(ec.HERE) / "entry_routes.json"
ROUTE_DATA = json.loads(ROUTES_FILE.read_text(encoding="utf-8"))
MATURE_RULES = ROUTE_DATA["mature_entry"]
GENERAL = ROUTE_DATA["general_regulations"]
PROGRAMMES = {p["id"]: p for p in RULES["programmes"]}

MEETS, POSSIBLE, NEEDS_INFO, NOT_MET = "meets", "possible", "needs_info", "not_met"
NORMAL_A, NORMAL_O, SPECIAL, MATURE = "normal_a_level", "normal_o_level", "special", "mature"
ROUTE_NAMES = {NORMAL_A: "Normal entry (A Levels)", NORMAL_O: "Normal entry (O Levels)",
               SPECIAL: "Special entry (post-school qualification)", MATURE: "Mature entry"}
STATUS_NAMES = {MEETS: "Meets the advertised requirements", POSSIBLE: "Possible route — the Admissions Office assesses it",
                NEEDS_INFO: "Could be possible — details still needed", NOT_MET: "Not met"}
GENERAL_MATURE_CITE = "MSU Humanities Yearbook, General Academic Regulations 3.3, p. 129 (may be older than the 2027 advert)"
GENERAL_SPECIAL_CITE = "MSU Humanities Yearbook, General Academic Regulations 3.2, p. 129 (may be older than the 2027 advert)"
INTERVIEW = "the Admissions Office may require an interview or tests (general regulations)"


@dataclass
class RouteResult:
    id: str
    programme: str
    faculty: str
    modes: List[str]
    duration: str
    page: int
    route: str
    status: str
    met: List[str] = field(default_factory=list)            # conditions the applicant meets (applicant-facing)
    outstanding: List[str] = field(default_factory=list)    # still needed / to confirm
    unknown: int = 0                                        # how many outstanding items are unknown facts
    basis: str = ""                                         # where the route's conditions come from
    score: float = 0.0
    questions: List[str] = field(default_factory=list)      # open rule questions for MSU
    needs: List[str] = field(default_factory=list)          # profile facts that would settle the unknowns


@dataclass
class Assessment:
    results: List[RouteResult]
    evaluation: Optional[Evaluation] = None                 # the engine's full A Level evaluation, when A Levels known

    def by_route(self, route: str) -> List[RouteResult]:
        return [r for r in self.results if r.route == route]

    def candidates(self) -> List[RouteResult]:
        return [r for r in self.results if r.status != NOT_MET]


# ------------------------------------------------------------------ field relevance
_SYNONYMS = {
    "information technology": "computer computing software information cyber telecommunication systems technology",
    "computer": "computer computing software information cyber systems", "software": "software computer computing",
    "programmer": "computer software computing", "developer": "software computer computing",
    "accounting": "accounting accountancy accounts audit finance", "accountant": "accounting accountancy audit finance",
    "accounts": "accounting accountancy", "nursing": "nursing health nutrition", "nurse": "nursing health nutrition",
    "teaching": "education", "teacher": "education", "education": "education",
    "agriculture": "agriculture agricultural crop animal agronomy farm", "farmer": "agriculture agricultural crop animal",
    "journalism": "journalism media communication", "journalist": "journalism media communication",
    "media": "media film radio television journalism graphic", "photographer": "media graphic film",
    "business": "business commerce management marketing entrepreneurship", "banking": "banking finance",
    "banker": "banking finance", "marketing": "marketing", "engineering": "engineering", "engineer": "engineering",
    "electrician": "electrical electronic engineering", "technician": "technology engineering laboratory",
    "laboratory": "chemistry chemical laboratory", "lab": "chemistry chemical laboratory biology", "police": "security policing", "police officer": "security policing",
    "soldier": "security", "security": "security", "tourism": "tourism hospitality", "hospitality": "hospitality tourism",
    "chef": "hospitality cookery", "secretary": "secretarial business", "clerk": "business administration",
    "statistics": "statistics", "chemistry": "chemistry chemical", "biology": "biology biosciences biotechnology",
    "food": "food nutrition", "psychology": "psychology", "law": "law legal", "social work": "social work",
}
_STOP = {"and", "the", "of", "in", "for", "with", "studies", "study", "science", "sciences", "management", "degree",
         "honours", "bachelor", "diploma", "applied", "general", "field", "industry", "sector", "work", "related"}


def _stems(text: str) -> set:
    words = [w for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _STOP]
    return {w[:6] for w in words}


def relevance(field_text: Optional[str], target: str) -> int:
    """How many distinctive words of the applicant's field (with a small list of synonyms) appear in the target text
    (programme name and advert line)."""
    if not field_text:
        return 0
    expanded = field_text.lower()
    for key, extra in _SYNONYMS.items():
        if re.search(rf"\b{re.escape(key)}\b", expanded):
            expanded += " " + extra
    return len(_stems(expanded) & _stems(target))


# ------------------------------------------------------------------ helpers
def _base(p: Dict[str, Any], route: str, status: str) -> RouteResult:
    return RouteResult(p["id"], p["programme"], p["faculty"], p["modes"], p["duration"], p["source_page"], route, status)


def _o_level_state(profile: ApplicantProfile, subject: str) -> Optional[bool]:
    """True = passed (grade C or better or 'passed'), False = known not passed, None = unknown."""
    oo = {k: f.value for k, f in profile.o_level.items()}
    have = ec.find_o(oo, subject)
    if have is None:
        return None
    if have == PASS_ONLY:
        return True
    return ec.O_ORDER.get(str(have).upper(), 0) >= ec.O_ORDER["C"]


def _o_level_text(subject: str) -> str:
    return {"Science": "a Science subject", "English Language": "English Language"}.get(subject, subject)


# ------------------------------------------------------------------ normal entry (engine)
def _normal(profile: ApplicantProfile) -> (List[RouteResult], Optional[Evaluation]):
    a, o = profile.engine_inputs()
    ev = evaluate(a, o)
    out = []
    for r in ev.results:
        p = PROGRAMMES[r.id]
        if p["route"] == "other_qualification":
            continue
        route = NORMAL_O if p["route"] == "o_level_only" else NORMAL_A
        if route == NORMAL_A and not a:
            if profile.a_level_none():
                res = _base(p, route, NOT_MET)
                res.outstanding = ["needs A Level passes (" + "; ".join(p["requirements_as_advertised"][:1]) + ")"]
                out.append(res)
            continue                                          # A Levels not known yet: not evaluated
        to_confirm = [t for t in r.to_confirm if not (profile.one_sitting and profile.one_sitting.value and "one sitting" in t)]
        status = {E_MEETS: MEETS, CONDITIONAL: NEEDS_INFO, E_NOT_MET: NOT_MET}[r.outcome]
        if r.outcome == CONDITIONAL and not (to_confirm or r.reasons or r.questions):
            status = MEETS
        res = _base(p, route, status)
        res.basis = f"2027 intake advert, p. {p['source_page']}"
        if status == NOT_MET:
            res.outstanding = list(r.reasons)
        else:
            res.outstanding = to_confirm + list(r.reasons)
            res.questions = list(r.questions)
            res.unknown = len(to_confirm)
            res.needs = (["one_sitting"] if any("one sitting" in t for t in to_confirm) else []) + \
                        (["o_level"] if any(t.startswith("O Level") or "O Level passes" in t for t in to_confirm) else [])
            if route == NORMAL_A:
                res.met.append("your A Levels meet the subject requirement" if not r.reasons and not r.questions
                               else "your A Levels match one reading of the subject requirement")
            else:
                have = [f"{profile.o_passes.value} O Level passes"] if profile.o_passes else []
                needed = [_o_level_text(s) for s in p["o_level_rule"]["required_subjects"] if _o_level_state(profile, s)]
                if needed:
                    have.append("including " + (needed[0] if len(needed) == 1 else
                                                ", ".join(needed[:-1]) + " and " + needed[-1]))
                res.met.append("this programme asks for O Levels only" + (", and you have " + " ".join(have)
                                                                          if have else ""))
        res.score = (r.relevance / 10.0) if route == NORMAL_A else 0.0
        out.append(res)
    return out, (ev if a else None)


# ------------------------------------------------------------------ special entry (qualifications)
_QUAL_LINE = re.compile(r"diploma|\bhnd\b|\bnd\b|\bnc\b|certificate|degree|cima|acca|\bcis\b|\biac\b|ipmz|institute of"
                        r"|qualification|znqf", re.I)
_ANY_QUAL = re.compile(r"any (?:other )?(?:relevant |related |equivalent )*(?:tertiary )?qualification|equivalent tertiary"
                       r"|any related qualification|approved equivalent|or an equivalent", re.I)


def _line_kinds(line: str) -> set:
    low = line.lower()
    kinds = set()
    if re.search(r"diploma|\bnd\b|\bhnd\b", low):
        kinds.add("diploma")
    if re.search(r"\bhnd\b|higher national", low):
        kinds.add("hnd")
    if re.search(r"certificate|\bnc\b", low):
        kinds.add("certificate")
    if "degree" in low:
        kinds.add("degree")
    if re.search(r"cima|acca|\bcis\b|\biac\b|ipmz|institute of|professional qualification", low):
        kinds.add("professional")
    if re.search(r"(?:diploma|certificate)\s*(?:/\s*certificate)?\s+in education|teaching qualification", low):
        kinds.add("teaching")
    if _ANY_QUAL.search(line):
        kinds.add("any")
    return kinds


def _applicant_kinds(kind: Optional[str], field_text: Optional[str]) -> set:
    k = (kind or "").lower()
    if k in ("hnd",):
        out = {"hnd", "diploma"}
    elif "diploma" in k:
        out = {"diploma"}
    elif "certificate" in k:
        out = {"certificate"}
    elif k == "degree":
        out = {"degree"}
    elif k in ("cima", "acca", "cis", "iac", "ipmz", "professional qualification"):
        out = {"professional"}
    elif k == "teaching qualification":
        out = {"teaching", "diploma", "certificate"}
    else:
        out = {"diploma", "certificate"}                     # kind not given yet
    if field_text and "education" in field_text and out & {"diploma", "certificate"}:
        out.add("teaching")
    return out


def _special(profile: ApplicantProfile, normal_ok: set) -> List[RouteResult]:
    out = []
    quals = [f.value for f in profile.qualifications]
    for pid, p in PROGRAMMES.items():
        if p["route"] == "o_level_only":
            continue
        lines = p["requirements_as_advertised"] if p["route"] == "other_qualification" else \
            [l for l in p["requirements_as_advertised"] if _QUAL_LINE.search(l) and not re.match(r"\s*mature", l, re.I)]
        qual_lines = [l for l in lines if _QUAL_LINE.search(l)]
        employ_lines = sorted((l for l in p["requirements_as_advertised"] if re.search(r"employ", l, re.I)), key=len)
        employ_lines = [l if len(l) <= 140 else "proof of employment, as the advert asks" for l in employ_lines]
        if not qual_lines or pid in normal_ok:
            continue
        if not quals:
            if profile.tertiary_none() and p["route"] == "other_qualification":
                res = _base(p, SPECIAL, NOT_MET)
                res.outstanding = ["needs a post-school qualification: " + qual_lines[0]]
                out.append(res)
            continue
        best = None
        for q in quals:
            kinds = _applicant_kinds(q.get("kind"), q.get("field"))
            for line in qual_lines:
                lk = _line_kinds(line)
                if not (kinds & lk or "any" in lk):
                    continue
                rel = relevance(q.get("field"), line) + 2 * relevance(q.get("field"), p["programme"])
                score = rel * 20 + (5 if kinds & (lk - {"any"}) else 0)
                if best is None or score > best[0]:
                    best = (score, q, line, rel)
        degree = next((q for q in quals if (q.get("kind") or "") == "degree"), None)
        if best is None and degree is None:
            res = _base(p, SPECIAL, NOT_MET)
            res.outstanding = ["the advert asks for: " + qual_lines[0]]
            out.append(res)
            continue
        if best is None:                                     # degree holder: general Special Entry regulation only
            best = (1, degree, None, relevance(degree.get("field"), p["programme"]))
        score, q, line, rel = best
        res = _base(p, SPECIAL, POSSIBLE)
        res.basis = f"2027 intake advert, p. {p['source_page']}" + ("" if line else f"; {GENERAL_SPECIAL_CITE}")
        if line:
            res.met.append(f"you hold {describe_qualification(q)}; the advert accepts: “{line.strip()}”")
        else:
            res.met.append(f"you hold {describe_qualification(q)}; degree holders may apply for Special Entry under the "
                           "general regulations")
        if not q.get("field"):
            res.status = NEEDS_INFO
            res.unknown += 1
            res.outstanding.append("what your qualification is in (the advert asks for a relevant field)")
            res.needs.append("qual_field")
        elif rel == 0:
            res.status = NEEDS_INFO
            res.outstanding.append(f"whether the Admissions Office accepts {q['field']} as relevant to this programme")
        else:
            res.outstanding.append("the Admissions Office decides whether your qualification is relevant and recognised")
        for l in employ_lines[:1]:
            if profile.employed and profile.employed.value is False:
                res.status = NOT_MET
                res.outstanding.insert(0, "the advert asks for employment in a relevant field: " + l.strip())
            elif not (profile.employed and profile.employed.value):
                res.outstanding.append("employment in a relevant field (" + l.strip().rstrip(".") + ")")
                res.unknown += 1
                res.needs.append("employed")
        fails, confirm = o_check(p["o_level_rule"], profile.engine_inputs()[1])
        if fails:
            res.status = NOT_MET
            res.outstanding = fails + res.outstanding
        else:
            res.outstanding += [f"general advert requirement: {c}" for c in confirm]
            res.unknown += len(confirm)
            res.needs += ["o_level"] if confirm else []
        res.score = score
        out.append(res)
    return out


# ------------------------------------------------------------------ mature entry
def _mature(profile: ApplicantProfile, normal_ok: set) -> List[RouteResult]:
    out = []
    for pid, rule in MATURE_RULES.items():
        if pid in normal_ok:
            continue                                          # mature entry is for applicants not eligible otherwise
        p, c = PROGRAMMES[pid], rule["conditions"]
        res = _base(p, MATURE, POSSIBLE)
        general = set(c.get("from_general_regulation", []))
        res.basis = f"2027 intake advert, p. {rule['page']}" + (f"; {GENERAL_MATURE_CITE}" if general else "")
        fail, unknown = [], []
        # age
        age, sex = profile.age.value if profile.age else None, profile.sex.value if profile.sex else None
        lo, hi = c["age"]["female"], c["age"]["male"]
        age_text = f"at least {hi} (men) or {lo} (women) on the first day of the academic year"
        if age is None:
            unknown.append((f"your age: mature entry needs applicants aged {age_text}", "age"))
        elif age >= hi:
            res.met.append(f"you are {age} (the minimum is {hi} for men and {lo} for women)")
        elif age >= lo:
            if sex == "female":
                res.met.append(f"you are {age} (the minimum for women is {lo})")
            elif sex == "male":
                fail.append(f"the minimum mature-entry age for men is {hi} (you are {age})")
            else:
                unknown.append((f"the minimum age is {lo} for women and {hi} for men (you are {age})", "sex"))
        else:
            fail.append(f"mature entry needs applicants aged {age_text} (you are {age})")
        # O Levels
        need = c.get("o_level_passes")
        if need:
            have = profile.o_passes.value if profile.o_passes else None
            if have is None:
                unknown.append((f"at least {need} O Level passes", "o_passes"))
            elif have < need:
                fail.append(f"needs at least {need} O Level passes (you have {have})")
            else:
                res.met.append(f"you have {have} O Level passes")
        passed_subjects = []
        for subject in c.get("o_level_subjects", []):
            state = _o_level_state(profile, subject)
            if state is None:
                unknown.append((f"an O Level pass in {_o_level_text(subject)}", f"o:{subject}"))
            elif not state:
                fail.append(f"needs an O Level pass in {_o_level_text(subject)}")
            else:
                passed_subjects.append(_o_level_text(subject))
        if passed_subjects:
            i = next((k for k, m in enumerate(res.met) if m.endswith("O Level passes")), None)
            text = "including " + (passed_subjects[0] if len(passed_subjects) == 1 else
                                   ", ".join(passed_subjects[:-1]) + " and " + passed_subjects[-1])
            if i is None:
                res.met.append("O Level passes " + text)
            else:
                res.met[i] += ", " + text
        if c.get("o_level_any_of"):
            if any(_o_level_state(profile, s) for s in c["o_level_any_of"]):
                res.met.append("an O Level indigenous language passed")
            else:
                unknown.append(("an O Level pass in an indigenous language (" + ", ".join(c["o_level_any_of"]) + ")", "o:indigenous"))
        # work
        years = profile.work_years.value if profile.work_years else None
        wfield = profile.work_field.value if profile.work_field else None
        rel = relevance(wfield, p["programme"])
        if c.get("work_years"):
            if years is None:
                unknown.append((f"{c['work_years']} years of experience in a relevant field", "work_years"))
            elif years < c["work_years"]:
                fail.append(f"needs {c['work_years']} years of experience in a relevant field (you have {years})")
            else:
                res.met.append(f"{years} years of work experience (the advert asks for {c['work_years']})")
        if c.get("work_relevant") or c.get("employed_related"):
            if wfield is None:
                unknown.append(("what field you work in (it must be relevant to this programme)", "work_field"))
            elif rel == 0:
                res.outstanding.append(f"whether the Admissions Office accepts your experience ({describe('work_field', wfield)}) as relevant")
                res.status = NEEDS_INFO
            else:
                res.outstanding.append(f"the Admissions Office decides whether your experience ({describe('work_field', wfield)}) is relevant")
        if c.get("employed_related"):
            emp = profile.employed.value if profile.employed else None
            if emp is False:
                fail.append("the advert asks for current employment in a related profession")
            elif emp is None:
                unknown.append(("current employment in a related profession (with confirmation of employment)", "employed"))
            else:
                res.outstanding.append("confirmation of employment from your employer")
        if c.get("suitability"):
            res.outstanding.append("the Admissions Office assesses your suitability from your attainments and/or "
                                   "relevant work experience")
        if c.get("modes"):
            res.outstanding.append("mature entry is advertised for " + " and ".join(c["modes"]) + " only")
        res.outstanding.append(INTERVIEW)
        if fail:
            res.status, res.outstanding = NOT_MET, fail
        elif unknown:
            res.status = NEEDS_INFO
            res.outstanding = [t for t, _ in unknown] + res.outstanding
        res.unknown = len(unknown)
        res.needs = [k for _, k in unknown]
        res.score = 20 * rel + (5 if years else 0)
        out.append(res)
    return out


# ------------------------------------------------------------------ assessment
def assess(profile: ApplicantProfile) -> Assessment:
    normal, ev = _normal(profile)
    normal_ok = {r.id for r in normal if r.status == MEETS}
    results = normal + _special(profile, normal_ok) + _mature(profile, normal_ok)
    return Assessment(results, ev)


def interest_match(r: RouteResult, interests: List[str]) -> int:
    """2 = the programme's name contains the interest, 1 = a related word, 0 = none."""
    name = r.programme.lower()
    best = 0
    for x in interests:
        if re.search(rf"\b{re.escape(x.lower())}\b", name):
            return 2
        if relevance(x, r.programme) > 0:
            best = 1
    return best


STATUS_RANK = {MEETS: 300, POSSIBLE: 200, NEEDS_INFO: 100, NOT_MET: 0}


def rank(results: List[RouteResult], interests: List[str]) -> List[RouteResult]:
    """Best route per programme, most relevant first: interest, then status, then fewest unknowns, then fit."""
    best: Dict[str, RouteResult] = {}
    for r in results:
        if r.status == NOT_MET:
            continue
        key = (STATUS_RANK[r.status] - 15 * r.unknown + r.score)
        if r.id not in best or key > (STATUS_RANK[best[r.id].status] - 15 * best[r.id].unknown + best[r.id].score):
            best[r.id] = r
    # Normal-entry unknowns are mostly the same general O Level checks for every programme, so A Level fit (score)
    # orders them; for special and mature routes, fewer unknowns come first.
    return sorted(best.values(), key=lambda r: (-interest_match(r, interests), -STATUS_RANK[r.status],
                                                0 if r.route == NORMAL_A else r.unknown, -r.score, r.faculty,
                                                r.programme))
