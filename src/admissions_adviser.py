"""
Conversational admissions guidance: the layer between the chat and the deterministic engines.

    advise(profile, message, turn, conversation=(), llm=None, settings=None, form=None, confirmed_reset=False)
        -> AdviserReply

One message at a time it (1) reads the message into the structured applicant profile (src/applicant_profile.py),
(2) handles confirmations, corrections, "those were my brother's results" and new assessments, never silently mixing
a new applicant's details with earlier ones, (3) decides whether enough is known to recommend anything, and (4) either
asks ONE high-value question or gives a short, ranked shortlist with the reason, the entry route and what is still
outstanding. Every recommendation comes from src/entry_routes.py and src/eligibility_engine.py (no model decides
anything, and the model never writes these answers). The full assessment (all programmes, all routes) is returned in
AdviserReply.assessment / .detail for an optional "Detailed assessment" view; counts and internal labels are not put in
the conversation.

The model is used only where the old flow used it: to attach A Level grade letters to subjects when the deterministic
parser cannot (src/extract_grades.py, validated against the applicant's own words).
"""
import copy
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.applicant_profile import (CONFIRMED, INFERRED, ApplicantProfile, Update, describe_qualification,
                                   read_message)
from src.eligibility_answer import EligibilityAnswer, answer_eligibility
from src.entry_routes import (GENERAL, GENERAL_MATURE_CITE, MATURE, MATURE_RULES, MEETS, NEEDS_INFO, NORMAL_A, NORMAL_O,
                              NOT_MET, POSSIBLE, PROGRAMMES, ROUTE_NAMES, SPECIAL, Assessment, RouteResult, assess,
                              interest_match, rank, relevance)
from src.extract_grades import Extraction, _optional_missing

SHORTLIST = 5
MAX_GATING = 3                     # questions in a row before recommending anything with what is known
DISCLAIMER = ("This is guidance based on the January/February 2027 intake advert. Meeting the advertised "
              "requirements does not guarantee a place: the Admissions Office makes the final decision.")
ICON = {MEETS: "✅", POSSIBLE: "🟡", NEEDS_INFO: "🔎", NOT_MET: "❌"}
STATUS_SHORT = {MEETS: "Meets the advertised requirements", POSSIBLE: "Possible: the Admissions Office assesses this route",
                NEEDS_INFO: "Could be possible: some details still needed", NOT_MET: "Not met"}

QUESTIONS = {
    "opener": ("I can help you find MSU programmes that match your qualifications. **What qualifications do you have?** "
               "For example your A Level subjects and grades, your O Level results, or a certificate or diploma.",
               ["I have A Levels", "I only have O Levels", "I have a diploma or certificate"]),
    "a_level_or_tertiary": ("**Do you also have any A Level passes, or a post-school qualification such as a "
                            "certificate, diploma or professional qualification?**",
                            ["No, only O Levels", "Yes, A Levels", "Yes, a diploma or certificate"]),
    "which_qualification": ("Great. **Is that A Levels, or a certificate, diploma or other post-school qualification?**",
                            ["A Levels", "A diploma", "A certificate"]),
    "a_level_subjects": ("**Which A Level subjects did you pass, and with what grades?** For example: Mathematics A, "
                         "Physics B, Chemistry C.", []),
    "a_level_grades": ("**What grade did you get in {subjects} at A Level?**", []),
    "tertiary": ("**Do you have any post-school qualification, such as a certificate, diploma or professional "
                 "qualification?**", ["No", "Yes, a diploma", "Yes, a certificate"]),
    "qual_field": ("**What is your {kind} in?** For example Accounting, Information Technology or Agriculture.", []),
    "o_level_details": ("**How many O Level subjects did you pass at grade C or better, and did they include English "
                        "Language and Mathematics?**", []),
    "o_level_grades": ("To complete the check, **what were your O Level English Language and Mathematics grades, and how "
                       "many O Level subjects did you pass at grade C or better?**", []),
    "age": ("Mature entry is open to applicants who are at least 25 (men) or 23 (women) on the first day of the "
            "academic year. **How old will you be in January 2027?**", []),
    "sex": ("The mature-entry age in the advert is 23 for women and 25 for men. **Which applies to you?** (You can skip "
            "this question.)", ["Female", "Male", "Skip"]),
    "work": ("Many mature-entry routes ask for relevant work experience. **Have you been working since you left "
             "school? If so, for how many years, and in what field?**", ["No work experience"]),
    "work_field": ("**What field or job have you worked in?** The advert asks for experience in a field relevant to "
                   "the programme.", []),
    "employed": ("**Are you currently employed? If so, in what field?** Some routes ask for current employment and a "
                 "confirmation letter from your employer.", ["Yes", "No"]),
    "science": ("**Did you pass a Science subject at O Level**, for example Combined Science, Biology, Chemistry or "
                "Physics? Several programmes ask for one.", ["Yes", "No"]),
    "one_sitting": ("**Did you get your O Level passes in one sitting?** One programme asks for that.", ["Yes", "No"]),
    "interest": ("**Is there a subject area you would like to study**, for example business, education, computing or "
                 "media? I can focus the list.", []),
}
YES_NO_QUESTIONS = {"a_level_or_tertiary", "tertiary", "science", "employed", "one_sitting", "work", "sex"}
NEED_TO_QUESTION = {"age": "age", "sex": "sex", "o_passes": "o_level_details", "o:English Language": "o_level_details",
                    "o:Mathematics": "o_level_details", "o:Science": "science", "work_years": "work",
                    "work_field": "work_field", "employed": "employed", "qual_field": "qual_field",
                    "o_level": "o_level_grades", "one_sitting": "one_sitting"}
FRESH_INTRO = re.compile(r"^\s*(?:(?:hi|hello|hey|good (?:morning|afternoon|evening))[\s,!.]*)?"
                         r"(?:i have|i've got|i got|i hold|i am|i'm|my (?:results|a[\s-]?levels|o[\s-]?levels|qualifications)"
                         r"|i passed|i wrote|i did)\b", re.I)
STUDY_QUESTION = re.compile(r"\b(?:what|which)\s+(?:programmes?|courses?|degrees?)?\s*(?:can|could|should)\s+i\b"
                            r"|\bwhat can i (?:study|do|apply)|\bdo i qualify|\bam i eligible|\bwhat (?:are )?my options", re.I)
CONTINUING = re.compile(r"\b(?:also|too|as well|additionally|another|plus|actually|sorry|correction|i meant|mistake"
                        r"|instead|update|forgot|wrong|not\s+\w+\s+but)\b", re.I)


@dataclass
class AdviserReply:
    text: str
    status: str = "answered"                   # answered | follow_up | confirm | error
    asked: Optional[str] = None                # question key, if the reply asks one
    quick_replies: List[str] = field(default_factory=list)
    shortlist: List[RouteResult] = field(default_factory=list)
    assessment: Optional[Assessment] = None
    detail: Optional[EligibilityAnswer] = None # the engine's A Level result tabs (detailed view)
    expand_detail: bool = False
    focus: str = "general"
    debug: Dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ small helpers
def _join(items: List[str]) -> str:
    items = [i for i in items if i]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def _question(key: str, profile: ApplicantProfile) -> (str, List[str]):
    text, replies = QUESTIONS[key]
    if key == "a_level_grades":
        text = text.format(subjects=_join(list(profile.a_level_ungraded)))
    if key == "a_level_subjects" and profile.loose_grades:
        text = (f"**Which A Level subjects did you get those grades ({_join(profile.loose_grades.value)}) in?** "
                "Please list them in the same order, for example: Mathematics, Physics and Chemistry.")
    if key == "qual_field":
        q = next((f.value for f in profile.qualifications if not f.value.get("field")), {})
        text = text.format(kind=(q.get("kind") or "qualification"))
    return text, list(replies)


def _recap(changed: List[str], profile: ApplicantProfile) -> str:
    """'Thanks. I've noted: 5 O Level passes, including Mathematics and English Language; age 30.'"""
    if not changed:
        return ""
    passed = [c[len("O Level "):-len(" passed")] for c in changed if c.startswith("O Level ") and c.endswith(" passed")]
    count = next((c for c in changed if re.fullmatch(r"\d+ O Level passes", c)), None)
    a_items = [c[len("A Level "):] for c in changed if c.startswith("A Level ")]
    rest = [c for c in changed if c != count and not (c.startswith("O Level ") and c.endswith(" passed"))
            and not c.startswith("A Level ") and not (a_items and c == "you have A Levels")]
    items = ["A Levels: " + ", ".join(a_items)] if a_items else []
    if count and passed:
        items.append(f"{count}, including {_join(passed)}")
    elif count:
        items.append(count)
    elif passed:
        items.append(("an O Level pass in " if len(passed) == 1 else "O Level passes in ") + _join(passed))
    items += rest
    inferred = any(f.status == INFERRED for f in profile.o_level.values())
    note = (" (I've taken “passed” to mean grade C or better, which is how the advert counts O Level passes.)"
            if inferred and passed else "")
    return "Thanks. I've noted: " + "; ".join(items) + "." + note


def _study_programmes(interests: List[str]) -> List[Dict[str, Any]]:
    """Advert programmes (undergraduate and diploma) named by what the applicant wants to study: exact names first."""
    equal, exact, related = [], [], []
    for x in interests:
        xl = x.lower()
        for p in PROGRAMMES.values():
            short = re.sub(r"\s*\(.*?\)\s*", " ", p["programme"].rsplit(" in ", 1)[-1]).strip().lower().rstrip(".")
            if short == xl:
                equal.append(p)
            elif re.search(rf"\b{re.escape(xl)}\b", p["programme"].lower()):
                exact.append(p)
            elif relevance(x, p["programme"]) > 0:
                related.append(p)
    seen, out = set(), []
    for p in (equal + exact) or related:
        if p["id"] not in seen:
            seen.add(p["id"])
            out.append(p)
    return out[:3]


def _extraction(profile: ApplicantProfile) -> Extraction:
    a, o = profile.engine_inputs()
    ex = Extraction(a_level=a, o_level={k: v for k, v in (o or {}).items()}, method="profile")
    ex.to_confirm = _optional_missing({("English" if k == "English Language" else k): v for k, v in (o or {}).items()})
    return ex


# ------------------------------------------------------------------ what to ask next
def _gating_question(profile: ApplicantProfile) -> Optional[str]:
    """Questions that come before any recommendation (answers change the whole picture)."""
    declined = set(profile.declined)
    if profile.is_empty():
        return "opener"
    if profile.a_level_ungraded and not profile.a_level:
        return "a_level_grades"
    if profile.a_level_status and profile.a_level_status.value == "has" and not profile.a_level \
            and not profile.a_level_ungraded:
        return "a_level_subjects"
    if not profile.a_level and not profile.a_level_status and not profile.qualifications \
            and "a_level_or_tertiary" not in declined:
        return "a_level_or_tertiary"
    if any(not f.value.get("field") for f in profile.qualifications) and "qual_field" not in declined:
        return "qual_field"
    no_routes = profile.a_level_none() and not profile.qualifications
    if no_routes and not profile.tertiary_status and "tertiary" not in declined:
        return "tertiary"
    if no_routes and profile.age is None and "age" not in declined:
        return "age"
    if no_routes and profile.age and 23 <= profile.age.value < 25 and profile.sex is None and "sex" not in declined:
        return "sex"
    if no_routes and profile.age and profile.age.value >= 23 and profile.work_years is None and "work" not in declined:
        return "work"
    return None


def _next_question(profile: ApplicantProfile, shortlist: List[RouteResult], assessment: Assessment) -> Optional[str]:
    """After recommendations: the unknown that would settle the most of the top candidates."""
    declined, asked = set(profile.declined), profile.asked
    votes: Dict[str, float] = {}
    pool = shortlist + [r for r in rank(assessment.results, [f.value for f in profile.interests]) if r not in shortlist][:10]
    for i, r in enumerate(pool):
        for need in r.needs:
            key = NEED_TO_QUESTION.get(need)
            if key and key not in declined and asked.count(key) < 2:
                votes[key] = votes.get(key, 0) + (3 if r in shortlist else 1)
    if votes:
        return max(votes, key=lambda k: (votes[k], -list(QUESTIONS).index(k)))
    if profile.a_level and not profile.o_level and not profile.o_passes and "o_level_grades" not in declined:
        return "o_level_grades"
    if not profile.interests and "interest" not in declined and "interest" not in asked and len(shortlist) >= SHORTLIST:
        return "interest"
    return None


# ------------------------------------------------------------------ rendering
def _mature_quote(pid: str) -> str:
    """The mature-entry part of the advert wording (some entries put it after the A Level requirement)."""
    text = re.sub(r"\s+", " ", MATURE_RULES[pid]["quote"])
    m = re.search(r"mature entry", text, re.I)
    return text[m.start():] if m else text


def _quote(r: RouteResult) -> str:
    p = PROGRAMMES[r.id]
    if r.route == MATURE:
        text = _mature_quote(r.id)
    elif r.route == SPECIAL:
        text = next((m.split("the advert accepts: ", 1)[1].strip("“”") for m in r.met if "the advert accepts" in m), "")
    else:
        text = (p["requirements_as_advertised"] or [""])[0]
    text = re.sub(r"\s+", " ", text).strip()
    return (text[:220].rsplit(" ", 1)[0] + "…") if len(text) > 220 else text


def _item(n: int, r: RouteResult) -> str:
    modes = ", ".join(r.modes) if r.modes else "modes not stated"
    lines = [f"**{n}. {r.programme}**",
             f"{ICON[r.status]} {STATUS_SHORT[r.status]} · *{ROUTE_NAMES[r.route]}*"]
    why = [m.split("; the advert accepts", 1)[0] for m in r.met]
    quote = _quote(r)
    if quote:
        lines.append(f"Advert: “{quote}”")
    if why:
        lines.append("Why it fits: " + "; ".join(why[:4]) + ".")
    still = r.outstanding[:3]
    if r.questions:
        still = still + [f"MSU still has to confirm how the requirement is read ({r.questions[0]})"]
    lines.append(("Still needed: " + "; ".join(still) + ".") if still else "Still needed: nothing else is listed in the advert.")
    lines.append(f"*{modes} · {r.duration} · {r.basis or 'advert p. %d' % r.page}*")
    return "  \n".join(lines)


def _shortlist_block(shortlist: List[RouteResult], intro: str) -> str:
    return intro + "\n\n" + "\n\n".join(_item(i + 1, r) for i, r in enumerate(shortlist))


def _no_match_text(profile: ApplicantProfile, assessment: Assessment) -> str:
    known = []
    if profile.a_level:
        known.append("your A Levels")
    if profile.o_passes or profile.o_level:
        known.append("your O Levels")
    if profile.qualifications:
        known.append("your qualification")
    basis = _join(known) or "what you've told me so far"
    return (f"Based on {basis}, I can't yet see a programme where you meet the advertised requirements. That doesn't "
            "mean there is no way in: MSU also admits students through other routes, and a few more details will "
            "show which of them could work for you.")


def _closing_options(profile: ApplicantProfile) -> str:
    return ("I've looked at every route the 2027 advert describes for what you've told me. The usual ways to open more "
            "options are: two A Level passes in the subjects a programme asks for; a relevant certificate or diploma "
            "(special entry); or mature entry, which needs you to be at least 25 (men) or 23 (women), five O Level "
            "passes including English Language (and Mathematics or a Science where required) and, for many "
            "programmes, relevant work experience. The Admissions Office (admissions@admin.msu.ac.zw) can advise on "
            "your situation.")


def _mature_overview(profile: ApplicantProfile, assessment: Assessment) -> str:
    g = GENERAL["mature"]
    listed = len(MATURE_RULES)
    text = ("**Mature entry at MSU.** The university's general regulations say that applicants who are at least 25 "
            "(men) or 23 (women) on the first day of the academic year, and who do not qualify through normal or "
            "special entry, may apply if they have at least five O Level passes including English Language (and "
            "Mathematics where required) and can show they are suited to university study through their attainments "
            "and/or relevant work experience. Interviews or tests may be required. "
            f"*({g['source']}, {g['section']}, p. {g['page']}; the yearbook regulations may be older than the 2027 "
            "advert.)*\n\n"
            f"The 2027 intake advert lists mature entry for **{listed} programmes**, some with extra conditions (for "
            "example five years of relevant experience, an O Level Science pass, or current employment). Age alone "
            "is not enough. For programmes where the advert does not mention mature entry, please ask the Admissions "
            "Office whether it is possible.")
    return text


def _for_you(r: Optional[RouteResult], unknown_text: str) -> str:
    """One route's status for this applicant, in plain words."""
    if r is None:
        return unknown_text
    if r.status == NOT_MET:
        return f"{ICON[NOT_MET]} not open to you: " + "; ".join(r.outstanding[:2])
    if r.status == MEETS:
        return f"{ICON[MEETS]} you meet the advertised requirements" + (
            " (still to confirm: " + "; ".join(r.outstanding[:2]) + ")" if r.outstanding else "")
    if r.status == POSSIBLE:
        return f"{ICON[POSSIBLE]} possible; " + "; ".join(r.outstanding[:3])
    return f"{ICON[NEEDS_INFO]} could be possible; still needed: " + "; ".join(r.outstanding[:3])


def _programme_block(p: Dict[str, Any], assessment: Assessment, profile: ApplicantProfile) -> str:
    """Every advertised route into one programme, with what it means for this applicant."""
    by_route = {r.route: r for r in assessment.results if r.id == p["id"]}
    reqs = p["requirements_as_advertised"] or [""]
    lines = [f"**{p['programme']}** *(2027 intake advert, p. {p['source_page']})*"]
    if p["route"] == "a_level":
        r = by_route.get(NORMAL_A)
        if r is not None and r.status == NOT_MET and profile.a_level_none():
            status = f"{ICON[NOT_MET]} you told me you don't have A Levels"
        else:
            status = _for_you(r, "tell me your A Level subjects and grades and I'll check this route")
        lines.append(f"- *Normal entry (A Levels)*: the advert asks for “{reqs[0].strip()}” For you: {status}.")
    elif p["route"] == "o_level_only":
        lines.append(f"- *Normal entry (O Levels)*: the advert asks for “{reqs[0].strip()}” For you: "
                     f"{_for_you(by_route.get(NORMAL_O), 'tell me your O Level results')}.")
    qual_lines = reqs[:3] if p["route"] == "other_qualification" else \
        [l for l in reqs[1:] if re.search(r"diploma|certificate|\bhnd\b|\bnd\b|degree|qualification", l, re.I)
         and not re.match(r"\s*mature", l, re.I)]
    if qual_lines:
        unknown = ("you told me you have no post-school qualification" if profile.tertiary_none()
                   else "tell me about any certificate or diploma you hold and I'll check this route")
        quote = re.sub(r"\s+", " ", " ".join(qual_lines[:2])).strip()
        lines.append(f"- *Special entry (qualification)*: the advert accepts “{quote[:240]}” For you: "
                     f"{_for_you(by_route.get(SPECIAL), unknown)}.")
    if p["id"] in MATURE_RULES:
        r = by_route.get(MATURE)
        status = "you already meet normal entry for this programme" if r is None else _for_you(r, "")
        lines.append(f"- *Mature entry*: the advert says “{_mature_quote(p['id'])[:260]}” For you: {status}.")
    else:
        lines.append("- *Mature entry*: the 2027 advert does not mention mature entry for this programme; ask the "
                     "Admissions Office whether it is possible.")
    return "\n".join(lines)


# ------------------------------------------------------------------ the policy
def _reset(profile: ApplicantProfile) -> None:
    fresh = ApplicantProfile()
    profile.__dict__.update(fresh.__dict__)


def _detail(profile: ApplicantProfile) -> Optional[EligibilityAnswer]:
    if not profile.a_level:
        return None
    return answer_eligibility(_extraction(profile), "")


def _reply_with_question(text_parts: List[str], key: Optional[str], profile: ApplicantProfile, status: str = "follow_up",
                         **kw) -> AdviserReply:
    replies: List[str] = []
    if key:
        q, replies = _question(key, profile)
        text_parts.append(q)
        profile.asked.append(key)
        profile.last_asked = key
    else:
        profile.last_asked = None
    return AdviserReply("\n\n".join(t for t in text_parts if t), status=status if key else kw.pop("final_status", "answered"),
                        asked=key, quick_replies=replies, **kw)


def _stale_conflict(profile: ApplicantProfile, u: Update, message: str) -> Optional[str]:
    """Does this message look like a new person's details that would otherwise be merged with earlier ones?"""
    if profile.is_empty() or not u.has_facts or CONTINUING.search(message):
        return None
    if u.a_level and profile.a_level and len(u.a_level) >= 2 and not set(u.a_level) & set(profile.a_level):
        return "a_level"
    if not (FRESH_INTRO.search(message) and STUDY_QUESTION.search(message)):
        return None
    earlier = []
    if profile.a_level and not u.a_level:
        earlier.append("a_level")
    if profile.qualifications and not u.qualifications:
        earlier.append("qualification")
    if profile.age and u.age is not None and u.age != profile.age.value:
        earlier.append("age")
    if profile.o_passes and u.o_passes is not None and u.o_passes != profile.o_passes.value:
        earlier.append("o_level")
    return "profile" if earlier else None


def advise(profile: ApplicantProfile, message: str, turn: int, conversation: List[Any] = (), llm: Any = None,
           settings: Any = None, form: Optional[Extraction] = None, confirmed_reset: bool = False) -> AdviserReply:
    asked = getattr(profile, "last_asked", None)
    parts: List[str] = []
    debug: Dict[str, Any] = {"asked_before": asked}

    if confirmed_reset:                               # the "Start new assessment" button (confirmed in the UI)
        _reset(profile)
        return _reply_with_question(["New assessment started. I've cleared the earlier details."], "opener", profile,
                                    focus="reset")

    u = read_message(message, asked)
    if form is not None and form.a_level and not profile.form_applied:
        u.a_level.update(form.a_level)
        u.a_level_status = "has"
        for k, v in form.o_level.items():
            if k == "passes":
                u.o_passes = v
            else:
                u.o_level["English Language" if k == "English" else k] = v
        profile.form_applied = True
        debug["form"] = True
    # A Level grade letters the parser could not attach: the model reads them (validated), as before
    if u.unattached_grades and not u.a_level and llm is not None and settings is not None and \
            (u.named_subjects or asked in ("a_level_subjects", "a_level_grades") or re.search(r"a[\s-]?level", message, re.I)):
        from src.extract_grades import read_results
        ex = read_results(message, None, list(conversation) + [message], llm, settings)
        if ex.a_level:
            u.a_level, u.a_level_status = dict(ex.a_level), "has"
            debug["results_method"] = ex.method
    debug["read"] = {"intents": u.intents, "facts": u.has_facts}

    # ---------------------------------------------------------- confirmations the adviser is waiting for
    pending = profile.pending
    if pending:
        kind = pending["kind"]
        yes = bool({"yes", "keep"} & set(u.intents)) or bool(re.search(r"\b(?:replace|same person)\b", message, re.I))
        new = bool({"new", "reset"} & set(u.intents)) or ("no" in u.intents and kind == "same_person")
        add = bool(re.search(r"\badd\b", message, re.I))
        if kind == "reset":
            declines = bool({"no", "keep"} & set(u.intents))
            confirms = bool({"yes", "reset", "new"} & set(u.intents)) and not declines
            if confirms:
                _reset(profile)
                return _reply_with_question(["Done. I've cleared the earlier details, so we can start a new "
                                             "assessment."], "opener", profile, focus="reset")
            if not declines and not u.has_facts:          # unclear: ask again rather than guess
                return AdviserReply("Sorry, I need a clear answer before I clear anything. " + pending["question"],
                                    status="confirm", quick_replies=list(pending["replies"]), focus="confirm")
            profile.pending = None
            parts.append("No problem, I've kept your details.")
            if not u.has_facts:
                return _continue(profile, parts, u, message, debug)
        elif kind in ("same_person", "replace_a_level"):
            stored = pending["update"]
            if new:
                _reset(profile)
                profile.apply(stored, turn)
                parts.append("Understood. I've started a new assessment using only your latest details, so nothing "
                             "from earlier is used.")
                return _continue(profile, parts, stored, pending["message"], debug, recap=False)
            if yes or add:
                profile.pending = None
                if kind == "replace_a_level" and not add:
                    profile.a_level.clear()
                    parts.append("I've replaced your earlier A Level results with the new ones.")
                else:
                    profile.confirm_all()
                    parts.append("Thanks for confirming. I've kept your earlier details and added the new ones.")
                changed = profile.apply(stored, turn)
                return _continue(profile, parts, stored, pending["message"], debug, changed=changed)
            # unclear answer: ask again (never decide for the applicant)
            return AdviserReply("Sorry, I need a clear answer before I continue. " + pending["question"],
                                status="confirm", quick_replies=list(pending["replies"]), focus="confirm")

    # ---------------------------------------------------------- explicit intents
    if "reset" in u.intents and not u.has_facts:
        if profile.is_empty():
            return _reply_with_question(["Of course, let's start a new assessment."], "opener", profile, focus="reset")
        q = ("Before I clear anything: **start a new assessment?** This removes what you've told me so far ("
             + profile.summary_text() + ").")
        replies = ["Yes, start a new assessment", "No, keep my details"]
        profile.pending = {"kind": "reset", "question": q, "replies": replies}
        profile.last_asked = None
        return AdviserReply(q, status="confirm", quick_replies=replies, focus="confirm")
    if "not_mine" in u.intents:
        removed = profile.remove_results_set()
        if removed:
            parts.append("Thanks for telling me. I've removed " + _join(removed) + ", and I won't use them in your "
                         "assessment.")
            if profile.is_empty():
                return _reply_with_question(parts + ["Let's look at your own qualifications instead."], "opener", profile,
                                            focus="not_mine")
        else:
            parts.append("I don't have any results recorded for this assessment, so there is nothing to remove.")
        return _continue(profile, parts, Update(), message, debug, recap=False)

    # ---------------------------------------------------------- stale data: never merge silently
    conflict = _stale_conflict(profile, u, message)
    if conflict:
        if conflict == "a_level":
            earlier = ", ".join(f"{s} {f.value}" for s, f in profile.a_level.items())
            q = (f"These A Level results are different from the ones you gave earlier ({earlier}). **Should I replace "
                 "the earlier results, or start a new assessment for someone else?**")
            replies = ["Replace earlier A Levels", "Add them to my earlier results", "Start a new assessment"]
            kind = "replace_a_level"
        else:
            q = ("Before I go on: earlier in this chat you told me " + profile.summary_text() + ". **Are these "
                 "details for the same person?** If so I'll combine them with what you just said; otherwise I'll start a "
                 "new assessment with only your latest details.")
            replies = ["Same person, keep everything", "New assessment"]
            kind = "same_person"
        profile.pending = {"kind": kind, "update": u, "message": message, "question": q, "replies": replies}
        profile.last_asked = None
        return AdviserReply(q, status="confirm", quick_replies=replies, focus="confirm", debug={**debug, "stale": conflict})

    # ---------------------------------------------------------- record what the message says
    if "skip" in u.intents and asked:
        profile.declined.append(asked)
    hypothetical = u.hypothetical
    if hypothetical:
        u.a_level_status = None                      # "what if I don't have A Levels?" is a question, not a fact
    changed = profile.apply(u, turn)
    meaningful = set(u.intents) - ({"yes", "no"} if asked not in YES_NO_QUESTIONS else set())
    if asked and not u.has_facts and not meaningful and not u.interests and asked not in ("interest",):
        # the answer could not be read: rephrase once, then move on
        if profile.asked.count(asked) >= 2:
            profile.declined.append(asked)
        else:
            q, replies = _question(asked, profile)
            profile.asked.append(asked)
            return AdviserReply("Sorry, I didn't quite catch that. " + q, status="follow_up", asked=asked,
                                quick_replies=replies, focus="clarify")
    if asked == "a_level_or_tertiary" and "yes" in u.intents and not u.has_facts:
        return _reply_with_question([], "which_qualification", profile)
    return _continue(profile, parts, u, message, debug, changed=changed, hypothetical=hypothetical)


def _continue(profile: ApplicantProfile, parts: List[str], u: Update, message: str, debug: Dict[str, Any],
              changed: Optional[List[str]] = None, recap: bool = True, hypothetical: bool = False) -> AdviserReply:
    """Decide what to say next for the current profile."""
    if recap and changed:
        parts.append(_recap(changed, profile))
        not_passes = [f"{s} {f.value}" for s, f in profile.a_level.items() if f.value in ("F", "O")
                      and any(c.startswith(f"A Level {s} ") or f"{s} {f.value}" in c for c in changed)]
        if not_passes:
            parts.append(f"{_join(not_passes)} {'is not an A Level pass' if len(not_passes) == 1 else 'are not A Level passes'}"
                         ", so " + ("it doesn't" if len(not_passes) == 1 else "they don't") + " count towards the "
                         "requirements (only grades A to E are passes).")
    interests = [f.value for f in profile.interests]
    focus_programmes = _study_programmes(u.interests) if u.interests else []
    focus = ("programme" if focus_programmes else "mature" if "mature" in u.intents else
             "without_a_level" if "without_a_level" in u.intents else "all" if "show_all" in u.intents else "general")
    view = profile
    if hypothetical and profile.a_level:
        view = copy.deepcopy(profile)
        view.a_level.clear()
        view.a_level_status = None
    assessment = assess(view)
    detail = _detail(profile)
    debug.update({"focus": focus, "profile": [r["label"] for r in profile.summary()],
                  "a_level": {s: f.value for s, f in profile.a_level.items()},
                  "o_level": profile.engine_inputs()[1],
                  "points": detail.evaluation.points_best_three if detail else None,
                  "failed_a_level_grades": detail.evaluation.failed_grades if detail else []})
    common = dict(assessment=assessment, detail=detail, focus=focus, debug=debug)

    # a named programme: answer it directly, route by route
    if focus == "programme":
        blocks = [_programme_block(p, assessment, profile) for p in focus_programmes[:2]]
        intro = "Here is how you could get into " + ("this programme" if len(blocks) == 1 else "these programmes") + \
                (", based on what you've told me so far:" if not profile.is_empty() else
                 ". Tell me your qualifications and I'll check each route for you:")
        parts += [intro] + blocks
        key = _gating_question(profile)
        if key is None:
            rows = [r for r in assessment.results if r.id in {p["id"] for p in focus_programmes} and r.status != NOT_MET]
            key = _next_question(profile, rows, assessment) if rows else None
        parts.append(DISCLAIMER)
        return _reply_with_question(parts, key, profile, status="answered", **common)

    if focus == "mature":
        parts.append(_mature_overview(profile, assessment))
        rows = rank([r for r in assessment.results if r.route == MATURE], interests)
        if not profile.is_empty():
            if rows:
                parts.append(_shortlist_block(rows[:SHORTLIST], "**For you, the advertised mature-entry routes look like "
                                                                  "this:**"))
            else:
                not_met = [r for r in assessment.results if r.route == MATURE and r.status == NOT_MET]
                if not_met:
                    parts.append("From what you've told me, the advertised mature-entry routes are not open to you "
                                 "yet: " + not_met[0].outstanding[0] + ".")
        key = None
        for k in ("age", "o_level_details", "work", "work_field", "science", "sex", "employed"):
            need = {"age": profile.age is None, "o_level_details": not profile.o_passes,
                    "work": profile.work_years is None, "work_field": bool(profile.work_years and profile.work_years.value)
                    and profile.work_field is None, "science": "Science" not in profile.o_level and not any(
                        s in profile.o_level for s in ("Combined Science", "Biology", "Chemistry", "Physics")),
                    "sex": bool(profile.age and 23 <= profile.age.value < 25 and profile.sex is None),
                    "employed": profile.employed is None and bool(profile.work_field)}[k]
            if need and k not in profile.declined and profile.asked.count(k) < 2:
                key = k
                break
        parts.append(DISCLAIMER)
        return _reply_with_question(parts, key, profile, status="answered", shortlist=rows[:SHORTLIST], **common)

    if focus == "without_a_level":
        parts.append("**Without A Levels**, the 2027 advert describes three ways in: a few programmes that ask for O "
                     "Levels only; **special entry** with a relevant certificate, diploma or other post-school "
                     "qualification; and **mature entry** for applicants aged at least 25 (men) or 23 (women) who meet "
                     "the extra conditions, such as five O Level passes and, for many programmes, relevant work "
                     "experience.")

    # what to ask before recommending anything
    key = _gating_question(profile)
    gating_run = 0
    for k in reversed(profile.asked):
        if k in ("opener", "a_level_or_tertiary", "which_qualification", "a_level_subjects", "a_level_grades", "tertiary",
                 "qual_field", "age", "work"):
            gating_run += 1
        else:
            break
    if key and (gating_run < MAX_GATING or key in ("opener", "a_level_subjects", "a_level_grades")):
        if key == "a_level_or_tertiary" and profile.age and profile.age.value >= 23 and not profile.a_level \
                and "a_level_or_tertiary" not in profile.asked:
            parts.append(f"At {profile.age.value} you may also be able to apply through mature entry. I'll check that "
                         "once I know a little more.")
        return _reply_with_question(parts, key, profile, **common)

    shortlist = rank(assessment.results, interests)
    shortlist = [r for r in shortlist if r.status in (MEETS, POSSIBLE) or r.route == NORMAL_A or r.unknown <= 2][:SHORTLIST]
    if focus == "all":
        parts.append("Here is the full assessment: every programme and route is listed in **Detailed assessment** "
                     "below.")
    if shortlist:
        signature = [(r.id, r.route, r.status) for r in shortlist]
        if signature == profile.last_shortlist and focus != "all":
            parts.append("That doesn't change your shortlist. The programmes I suggested above still fit best, and "
                         "every programme and route is in **Detailed assessment** below.")
        else:
            meets = any(r.status == MEETS for r in shortlist)
            intro = ("**These programmes fit you best so far:**" if meets or any(r.status == POSSIBLE for r in shortlist)
                     else "**I can't confirm a match yet, but these programmes could be possible once a few details "
                          "are settled:**")
            if all(r.route == NORMAL_A and r.status == NEEDS_INFO and set(r.needs) <= {"o_level"} and not r.questions
                   for r in shortlist):
                intro = ("**Your A Levels fit these programmes.** I need your O Level results to confirm them:")
            if profile.recommended:
                intro = intro.replace("so far:", "now:")
            parts.append(_shortlist_block(shortlist, intro))
            parts.append("You can see every programme and entry route in **Detailed assessment** below.")
        profile.recommended = True
        profile.last_shortlist = signature
        key = _next_question(profile, shortlist, assessment)
        parts.append(DISCLAIMER)
        return _reply_with_question(parts, key, profile, status="answered", shortlist=shortlist, expand_detail=focus == "all", **common)

    # nothing open yet: say so kindly and explore other routes
    parts.append(_no_match_text(profile, assessment))
    key = None
    if not profile.a_level and not profile.a_level_status and "a_level_or_tertiary" not in profile.declined:
        key = "a_level_or_tertiary"
    elif not profile.qualifications and not profile.tertiary_status and "tertiary" not in profile.declined:
        key = "tertiary"
    elif profile.age is None and "age" not in profile.declined:
        key = "age"
    elif profile.work_years is None and (profile.age and profile.age.value >= 23) and "work" not in profile.declined:
        key = "work"
    elif not profile.o_passes and "o_level_details" not in profile.declined:
        key = "o_level_details"
    if key is None:
        parts.append(_closing_options(profile))
    parts.append(DISCLAIMER)
    return _reply_with_question(parts, key, profile, status="answered", expand_detail=focus == "all", **common)
