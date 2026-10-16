"""
Structured applicant profile for the admissions adviser, and the deterministic reading of one chat message into
profile updates and conversational intents (no model call).

    read_message(text, asked=None) -> Update
    ApplicantProfile.apply(update, turn) / remove_turn(turn) / summary() / engine_inputs()

Every fact records where it came from (Fact.status):
- stated     the applicant said it (in this chat, for this assessment);
- confirmed  the applicant explicitly confirmed it (e.g. kept earlier details for the same person);
- inferred   derived from what they said, and shown as an assumption, e.g. "5 O Level passes including Maths" ->
             Mathematics passed at grade C or better (the advert counts passes at grade C or better).
Anything else is unknown. Nothing is guessed: a value is recorded only when its words are in the message.
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.eligibility import RULES, norm
from src.eligibility import eligibility_checker as ec
from src.eligibility_engine import PASS_ONLY
from src.results_parser import NUMBER_WORDS, parse_results

STATED, CONFIRMED, INFERRED = "stated", "confirmed", "inferred"
_NUM = r"(?:\d{1,2}|%s)" % "|".join(NUMBER_WORDS)
_LEVEL_A = r"a[\s'’-]*levels?"
_LEVEL_O = r"o[\s'’-]*levels?"


def _int(word: str) -> int:
    word = word.lower()
    return int(NUMBER_WORDS.get(word, word))


@dataclass
class Fact:
    value: Any
    status: str = STATED
    turn: int = 0
    note: str = ""


@dataclass
class Update:
    """What one message says. Only keys that the message actually supports are set."""
    a_level: Dict[str, str] = field(default_factory=dict)            # subject -> grade
    a_level_ungraded: List[str] = field(default_factory=list)
    a_level_status: Optional[str] = None                             # has | none
    o_level: Dict[str, str] = field(default_factory=dict)            # checker subject name -> grade or PASS_ONLY
    o_inferred: List[str] = field(default_factory=list)              # subjects recorded as PASS_ONLY
    o_passes: Optional[int] = None
    one_sitting: Optional[bool] = None
    tertiary_status: Optional[str] = None                            # has | none
    qualifications: List[Dict[str, Optional[str]]] = field(default_factory=list)   # {kind, field}
    age: Optional[int] = None
    sex: Optional[str] = None                                        # only recorded when the applicant says it
    work_years: Optional[int] = None
    work_field: Optional[str] = None
    employed: Optional[bool] = None
    interests: List[str] = field(default_factory=list)               # words naming what they want to study
    intents: List[str] = field(default_factory=list)
    hypothetical: bool = False                                       # "what if I don't have A Levels?"
    unattached_grades: bool = False                                  # grade letters not attached to a subject
    loose_grades: List[str] = field(default_factory=list)            # "I got A, B and C at A Level" (in order)
    named_subjects: List[str] = field(default_factory=list)          # A Level subjects named without a grade

    @property
    def has_facts(self) -> bool:
        return bool(self.a_level or self.a_level_ungraded or self.a_level_status or self.o_level or
                    self.o_passes is not None or self.one_sitting is not None or self.tertiary_status or
                    self.qualifications or self.age is not None or self.sex or self.work_years is not None or
                    self.work_field or self.employed is not None)


# ------------------------------------------------------------------ intents
RESET = re.compile(r"\b(?:start (?:a |the )?(?:new|fresh|another|over)(?: (?:assessment|check|application))?|new assessment"
                   r"|start (?:all )?over|start again|reset(?: (?:my|the) (?:details|assessment))?"
                   r"|clear (?:my|the|all) (?:details|results|information|assessment)|forget (?:everything|my details))\b", re.I)
NOT_MINE = re.compile(r"\b(?:those|these|that|they|it) (?:were|are|was|is) (?:actually )?(?:not mine|not my|my (?:brother|sister|friend|cousin|son|daughter|child|wife|husband|partner|sibling)'?s?|someone else'?s|for my)"
                      r"|\bnot (?:my|mine)\b[^.?!]{0,20}\b(?:results|grades|marks)"
                      r"|\b(?:were|are) (?:my )?(?:brother|sister|friend|cousin|son|daughter|child|wife|husband|partner)'?s (?:results|grades|marks)", re.I)
YES = re.compile(r"^\s*(?:yes|yeah|yep|yup|correct|right|sure|ok(?:ay)?|please do|go ahead|do it)\b"
                 r"|^\s*i (?:do|have|did)\s*[.!]?\s*$", re.I)
NO = re.compile(r"^\s*(?:no|nope|nah|not really|none|never)\b"
                r"|^\s*i (?:don'?t|do not|haven'?t|have not|didn'?t|did not)\s*[.!]?\s*$", re.I)
KEEP = re.compile(r"\b(?:keep|same person|combine|it'?s me|they'?re mine|that was me|both mine)\b", re.I)
NEW = re.compile(r"\b(?:new assessment|different person|someone else|start (?:a )?new|start fresh|start over|clear)\b", re.I)
SKIP = re.compile(r"^\s*(?:skip|pass|prefer not(?: to say)?|i'?d rather not(?: say)?|not sure|i don'?t know|don'?t know)\b", re.I)
MATURE = re.compile(r"\bmature(?:[- ]age)?(?:\s+(?:entry|student|applicant|route)s?)?\b", re.I)
WITHOUT_A_LEVEL = re.compile(rf"\bwhat if i (?:don'?t|do not) have (?:any )?{_LEVEL_A}|\bwithout (?:any )?{_LEVEL_A}", re.I)
SHOW_ALL = re.compile(r"\b(?:show (?:me )?(?:all|everything|the full list)|full list|list all|view all|all (?:the )?results|detailed assessment)\b", re.I)
WHY_NOT = re.compile(r"\bwhy\s+(?:can'?t|cannot|can\s+not|don'?t)\s+i\b|\bwhy\s+not\b", re.I)

# ------------------------------------------------------------------ facts
_AGE = [re.compile(r"\b(?:i'?m|i am|aged?|age(?:\s+is)?|i'?ll be|i will be|turning|turn)\s*:?\s*(?P<n>\d{2})(?!\s*(?:%|passes|subjects|o\b|a\b|[- ]?levels?))(?:\s*(?:years?|yrs?)(?:\s+old)?)?\b", re.I),
        re.compile(r"\b(?P<n>\d{2})\s*(?:years?|yrs?)[\s-]*old\b", re.I),
        re.compile(r"\b(?:age|aged)\s*[:=]\s*(?P<n>\d{2})\b", re.I)]
_SEX = re.compile(r"\b(?:i'?m|i am)\s+(?:a\s+)?(?P<s>female|woman|lady|girl|male|man|guy|boy)\b"
                  r"|^\s*(?:i'?m\s+)?(?:a\s+)?(?P<a>female|woman|male|man)\s*[.!]?\s*$", re.I)
_FEMALE = {"female", "woman", "lady", "girl"}
_NO_A = re.compile(rf"\b(?:only|just)\s+(?:have\s+|did\s+|got\s+)?(?:my\s+)?{_LEVEL_O}\b"
                   rf"|\b(?:no|don'?t have(?: any)?|do not have(?: any)?|didn'?t (?:do|write|sit|take|pass)|did not (?:do|write|sit|take|pass)|never (?:did|wrote|sat|took))\s+(?:any\s+|my\s+)?{_LEVEL_A}"
                   rf"|\bwithout\s+(?:any\s+)?{_LEVEL_A}|\bnot\s+(?:done|written)\s+{_LEVEL_A}", re.I)
_HAS_A = re.compile(rf"\b(?:i\s+(?:have|did|wrote|sat|passed|completed|finished)|i've got|i got|yes,?\s*(?:i have\s+)?)\s+(?:my\s+|some\s+|two\s+|three\s+|2\s+|3\s+)?{_LEVEL_A}\b", re.I)
_KIND = (r"(?P<kind>higher\s+national\s+diploma|national\s+diploma|national\s+certificate|national\s+foundation\s+certificate"
         r"|advanced\s+diploma|hnd|nd|nc|diploma|certificate|(?:honours\s+|bachelor'?s?\s+|first\s+)?degree|bachelor'?s|masters?"
         r"|cima|acca|cis|iac|ipmz|teaching\s+(?:diploma|qualification|certificate)|professional\s+qualification)")
_QUAL = re.compile(rf"\b(?:i\s+(?:also\s+)?(?:have|hold|got|did|completed|finished|obtained|earned|am doing|am studying)|i've\s+(?:also\s+)?got|also\s+have|plus|and|with|yes,?)\s+(?:a|an|my|the)?\s*{_KIND}\b"
                   r"(?:\s+(?:in|of|on)\s+(?P<field>[a-z][a-z &/,'’-]{1,60}?))?"
                   r"(?=\s+(?:and\s+(?:i|my|also|have|worked|work|years?|\d+|%s)|or|from|but|which|that|so|because|since|with"
                   r"|plus|for\s+\d)\b|[.,;!?)]|$)" % "|".join(NUMBER_WORDS), re.I)
_QUAL_BARE = re.compile(rf"^\s*(?:a|an|my)?\s*{_KIND}(?:\s+(?:in|of)\s+(?P<field>[a-z][a-z &/'’-]{{1,60}}?))?\s*[.!]?\s*$", re.I)
_NO_QUAL = re.compile(r"\b(?:no|don'?t have (?:a|any)|do not have (?:a|any)|without (?:a|any))\s+(?:other\s+)?(?:diploma|certificate|degree|post[- ]school|tertiary|college|professional)\b"
                      r"|\bno other qualifications?\b|\bnothing else\b", re.I)
_WORK = [re.compile(rf"\b(?:worked|been working|working|work(?:ed)? experience|employed|in the job)\b[^.?!]{{0,40}}?\bfor\s+(?:about\s+|over\s+|almost\s+|nearly\s+)?(?P<n>{_NUM})\s*\+?\s*(?:years?|yrs?)\b", re.I),
         re.compile(rf"\b(?P<n>{_NUM})\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:(?:relevant|work|working|professional|job|teaching|nursing)\s+)*(?:experience|work)\b", re.I),
         re.compile(rf"\b(?P<n>{_NUM})\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:working|work)\s+(?:as|in)\b", re.I),
         re.compile(rf"\b(?:worked|been working|working)\s+(?:as\s+[a-z ]{{2,30}}?\s+)?(?:for\s+)?(?P<n>{_NUM})\s*(?:years?|yrs?)\b", re.I)]
_FIELD = [re.compile(r"\b(?:work|working|worked|employed|job|experience)\b[^.?!]{0,30}?\bas\s+(?:an?\s+)?(?P<f>[a-z][a-z /&-]{2,40}?)(?=\s+(?:for|since|in|at|with)\b|[.,;!?]|$)", re.I),
          re.compile(r"\b(?:work|working|worked|employed|experience)\s+in\s+(?:the\s+|a\s+|an\s+)?(?P<f>[a-z][a-z /&-]{1,40}?)(?:\s+(?:field|industry|sector|department))?(?=\s+(?:for|since|as|at)\b|[.,;!?]|$)", re.I),
          re.compile(r"\bin\s+the\s+(?P<f>[a-z][a-z /&-]{1,40}?)\s+(?:field|industry|sector)\b", re.I),
          re.compile(r"\b(?:years?|yrs?)(?:\s+of(?:\s+(?:work|working|relevant))?\s+experience)?\s+(?:in|as an?|as)\s+(?:the\s+)?"
                     r"(?P<f>[a-z][a-z /&-]{1,40}?)(?:\s+(?:field|industry|sector))?(?=\s+(?:for|since|at)\b|[.,;!?]|$)", re.I),
          re.compile(r"\bi(?:'m| am)\s+(?:an?\s+)(?P<f>nurse|teacher|accountant|journalist|engineer|technician|programmer|developer|farmer|police officer|soldier|banker|lab technician|laboratory technician|electrician|chef|secretary|clerk|photographer)\b", re.I)]
_EMPLOYED = re.compile(r"\bi(?:'m| am)\s+(?:currently\s+)?(?:employed|working)\b|\bi\s+(?:currently\s+)?work\s+(?:as|in|for|at)\b|\bcurrently\s+(?:employed|working)\b|\bemployed\s+as\b", re.I)
_NOT_EMPLOYED = re.compile(r"\b(?:unemployed|not working|never worked|no work experience|not employed|don'?t work|do not work|haven'?t worked|have not worked)\b", re.I)
_ONE_SITTING = re.compile(r"\b(?:in\s+)?(?:one|1|a single|the same)\s+sitting\b", re.I)
_O_INCLUDING = re.compile(rf"(?:{_LEVEL_O}|passes|subjects)[^.?!]{{0,40}}?\binclud\w*\s+(?P<subs>[a-z ,&]+?)(?=[.?!;]|\s+(?:and\s+(?:i|my|i'm)|but|so|what|which|can|i\b)|$)", re.I)
_O_PASSED_IN = re.compile(rf"\bpassed\s+(?P<subs>[a-z ,&]+?)\s+at\s+{_LEVEL_O}\b", re.I)
_INTEREST = re.compile(r"\b(?:study|studying|do|doing|take|apply for|get into|enrol (?:in|for)|interested in|want to (?:study|do|become)|"
                       r"like to (?:study|do)|about|for)\s+(?:a\s+|an\s+|the\s+)?(?P<x>[a-z][a-z &,/'’-]{2,70}?)(?=[.?!;]|\s+(?:at msu|at the university|with my|if|and i|instead)\b|$)", re.I)
_GENERIC_INTEREST = re.compile(r"^(?:it|this|that|so|something|anything|what|which|programmes?|courses?|degrees?|a degree|university|msu"
                               r"|there|here|me|my (?:results|grades)|mature entry|mature|now|next|then|them|the programmes?)$", re.I)
_O_NAMES = {"english": "English Language", "english language": "English Language", "maths": "Mathematics",
            "math": "Mathematics", "mathematics": "Mathematics", "science": "Science", "combined science": "Combined Science",
            "integrated science": "Combined Science", "biology": "Biology", "chemistry": "Chemistry", "physics": "Physics",
            "geography": "Geography", "history": "History", "shona": "Shona", "ndebele": "Ndebele",
            "accounts": "Accounts", "commerce": "Commerce", "agriculture": "Agriculture"}
for _lang in ("barwe", "khoisan", "ndau", "chewa", "shangani", "tswana", "xhosa", "venda", "sotho", "kalanga", "nambya",
              "tonga"):
    _O_NAMES[_lang] = _lang.title()


def _clean_field(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip(" ,.-'’").lower()
    text = re.sub(r"^(?:the|a|an)\s+", "", text)
    return text if len(text) >= 2 and not _GENERIC_INTEREST.match(text) else None


def _kind(raw: str) -> str:
    k = re.sub(r"\s+", " ", raw.lower())
    if k in ("hnd", "higher national diploma"):
        return "HND"
    if k in ("nd", "national diploma"):
        return "National Diploma"
    if k in ("nc", "national certificate"):
        return "National Certificate"
    if "foundation" in k:
        return "National Foundation Certificate"
    if k in ("cima", "acca", "cis", "iac", "ipmz"):
        return k.upper()
    if k.startswith("teaching"):
        return "teaching qualification"
    if "degree" in k or k.startswith("bachelor") or k.startswith("master"):
        return "degree"
    return k.replace("advanced diploma", "Advanced Diploma")


def _o_subjects(text: str) -> List[str]:
    out = []
    for part in re.split(r",|\band\b|&", text.lower()):
        name = part.strip()
        if name in _O_NAMES:
            out.append(_O_NAMES[name])
    return out


def _position(subject: str, low: str) -> int:
    names = [subject.lower()] + [a for a, s in RULES["aliases"].items() if s == subject]
    found = [m.start() for n in names for m in [re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", low)] if m]
    return min(found) if found else len(low)


def read_message(text: str, asked: Optional[str] = None) -> Update:
    """Facts and intents in one message. 'asked' is the question the adviser asked last (its key), which gives short
    answers ('no', '8', 'female', 'a diploma in IT') their meaning."""
    text = (text or "").strip()
    text = re.sub(r"\bI\.?T\b|\bICT\b", "information technology", text)       # the acronym, not the pronoun "it"
    low = text.lower()
    u = Update()
    # intents
    for name, rx in (("reset", RESET), ("not_mine", NOT_MINE), ("mature", MATURE), ("show_all", SHOW_ALL),
                     ("why_not", WHY_NOT), ("without_a_level", WITHOUT_A_LEVEL)):
        if rx.search(text):
            u.intents.append(name)
    if YES.search(text):
        u.intents.append("yes")
    if NO.search(text):
        u.intents.append("no")
    if SKIP.search(text):
        u.intents.append("skip")
    if KEEP.search(text):
        u.intents.append("keep")
    if NEW.search(text) and "reset" not in u.intents:
        u.intents.append("new")
    u.hypothetical = "without_a_level" in u.intents and bool(re.search(r"\bwhat if\b", low))

    # exam results (the existing deterministic parser)
    parsed = parse_results(text, o_level_context=asked in ("o_level_details", "o_level_grades"))
    u.a_level = dict(parsed.a_level)
    u.unattached_grades = not parsed.confident
    u.named_subjects = list(parsed.subjects_without_grade)
    if asked in ("a_level_subjects", "a_level_grades") or parsed.a_level:
        u.a_level_ungraded = sorted((s for s in parsed.subjects_without_grade if s not in u.a_level),
                                    key=lambda s: _position(s, low))      # in the order the applicant wrote them
    for k, v in parsed.o_level.items():
        if k == "passes":
            u.o_passes = int(v)
        else:
            u.o_level[ec.norm_o(k)] = v
    for rx in (_O_INCLUDING, _O_PASSED_IN):
        for m in rx.finditer(text):
            for s in _o_subjects(m.group("subs")):
                if s not in u.o_level:
                    u.o_level[s] = PASS_ONLY
                    u.o_inferred.append(s)
    if u.o_passes is None:
        m = re.search(rf"\b(?P<n>{_NUM})\s+(?:{_LEVEL_O}|ordinary levels?)\b(?!\s+(?:subjects?\s+)?(?:at|grade))", text, re.I)
        if m and not re.search(rf"{_LEVEL_O}\s+(?:english|maths?|mathematics)", text[m.end():m.end() + 30], re.I):
            u.o_passes = _int(m.group("n"))
    if _ONE_SITTING.search(text):
        u.one_sitting = True

    # a question ("Can I study ...?") is never read as a short answer such as a field of work
    question_like = "?" in text or bool(re.match(r"\s*(?:can|could|what|which|how|is|are|do|does|why|will|may)\b", low))

    # grade letters without subjects, said about A Levels: kept in order so the next answer can name the subjects
    if u.unattached_grades and not u.a_level and re.search(_LEVEL_A, text, re.I):
        body = re.sub(rf"\b{_LEVEL_A}\b", " ", text, flags=re.I)
        u.loose_grades = re.findall(r"(?<![A-Za-z'’])([A-E])(?![A-Za-z'’])", re.sub(r"^\s*I\b|\bI\b(?=\s+[a-z])", " ", body))
        if u.loose_grades:
            u.a_level_status = "has"

    # A Level status ("I only have O Levels" also means no post-school qualification)
    if _NO_A.search(text) and not u.a_level:
        u.a_level_status = "none"
        if re.search(rf"\b(?:only|just)\s+(?:have\s+|did\s+|got\s+)?(?:my\s+)?{_LEVEL_O}\b", text, re.I) \
                and not u.qualifications:
            u.tertiary_status = "none"
    elif u.a_level or u.a_level_ungraded or u.loose_grades or _HAS_A.search(text):
        u.a_level_status = "has"

    # post-school qualifications
    bare_ok = asked in ("a_level_or_tertiary", "qual_field", "opener", "tertiary", "which_qualification")
    for rx in (_QUAL,) + ((_QUAL_BARE,) if bare_ok else ()):
        for m in rx.finditer(text):
            kind = _kind(m.group("kind"))
            if kind in ("degree",) and re.search(r"\bwhat\b.{0,20}\bdegree\b|\bwhich\b.{0,20}\bdegree\b", low):
                continue
            u.qualifications.append({"kind": kind, "field": _clean_field(m.group("field"))})
    if asked == "qual_field" and not u.qualifications and not u.intents and not question_like:
        f = _clean_field(re.sub(r"^(?:it'?s|it is|in|my diploma is in|a diploma in)\s+", "", low))
        if f and len(f.split()) <= 6:
            u.qualifications.append({"kind": None, "field": f})
    if u.qualifications:
        u.tertiary_status = "has"
    elif _NO_QUAL.search(text):
        u.tertiary_status = "none"

    # age (never from "5 passes", "30 years of experience")
    for rx in _AGE:
        m = rx.search(text)
        if m and not re.match(r"\s*(?:years?|yrs?)\s+(?:of\s+)?(?:work|working|experience|teaching)", text[m.end("n"):], re.I):
            n = int(m.group("n"))
            if 14 <= n <= 90:
                u.age = n
                break
    if u.age is None and asked == "age":
        m = re.fullmatch(r"\s*(?:i'?ll be |i will be |i'?m |i am )?(\d{2})\s*(?:years?(?: old)?)?\s*[.!]?\s*", low)
        if m and 14 <= int(m.group(1)) <= 90:
            u.age = int(m.group(1))
    m = _SEX.search(text)
    if m:
        word = (m.group("s") or m.group("a")).lower()
        u.sex = "female" if word in _FEMALE else "male"

    # work
    for rx in _WORK:
        m = rx.search(text)
        if m:
            u.work_years = _int(m.group("n"))
            break
    if u.work_years is None and asked in ("work", "work_field"):
        m = re.match(rf"\s*(?:about |around |over |for )?(?P<n>{_NUM})\s*(?:years?|yrs?)?"
                     r"(?:\s+(?:in|as an?|as)\s+(?P<f>[a-z][a-z /&-]{1,40}))?\s*[.!]?\s*$", low)
        if m:
            u.work_years = _int(m.group("n"))
            u.work_field = _clean_field(m.group("f"))
    for rx in _FIELD:
        m = rx.search(text)
        if m:
            u.work_field = _clean_field(m.group("f"))
            if u.work_field:
                break
    if u.work_field is None and asked in ("work_field", "employed") and not u.intents and not question_like:
        f = _clean_field(re.sub(r"^(?:in|as an?|i worked (?:in|as an?)|i work (?:in|as an?))\s+", "", low))
        if f and len(f.split()) <= 6:
            u.work_field = f
    if _NOT_EMPLOYED.search(text):
        u.employed = False
        if re.search(r"never worked|no work experience|haven'?t worked|have not worked", low):
            u.work_years = 0
    elif _EMPLOYED.search(text) or u.work_field and re.search(r"\b(?:i work|i'?m working|currently)\b", low):
        u.employed = True
    if asked == "work" and "no" in u.intents and u.work_years is None:
        u.work_years = 0
    if asked == "a_level_or_tertiary" and "no" in u.intents and not u.a_level and not u.qualifications:
        u.a_level_status = u.a_level_status or "none"
        u.tertiary_status = u.tertiary_status or "none"
    if asked == "tertiary" and "no" in u.intents and not u.qualifications:
        u.tertiary_status = "none"
    if asked == "employed" and u.employed is None and not question_like:
        if "yes" in u.intents or u.work_field:
            u.employed = True
        elif "no" in u.intents:
            u.employed = False
    if asked == "which_qualification" and re.search(rf"^\s*{_LEVEL_A}\b", text, re.I):
        u.a_level_status = "has"
    if asked == "one_sitting" and u.one_sitting is None:
        if "yes" in u.intents:
            u.one_sitting = True
        elif "no" in u.intents:
            u.one_sitting = False
    if asked == "science" and not u.o_level:
        if "yes" in u.intents:
            u.o_level["Science"] = PASS_ONLY
            u.o_inferred.append("Science")
        elif "no" in u.intents:
            u.o_level["Science"] = "U"
    if asked == "sex_for_age" and u.sex is None:
        if re.search(r"\b(?:female|woman|women|lady|23)\b", low):
            u.sex = "female"
        elif re.search(r"\b(?:male|man|men|25)\b", low):
            u.sex = "male"

    # what they want to study
    for m in _INTEREST.finditer(text):
        x = _clean_field(re.sub(r"\b(?:at msu|please|instead|then|now)\b", "", m.group("x")))
        if x and not re.search(rf"{_LEVEL_A}|{_LEVEL_O}|\bpasses?\b|\bresults?\b|\bgrades?\b|\bmature\b|\bentry\b", x):
            u.interests.append(x)
    return u


# ------------------------------------------------------------------ the profile
LABELS = {"a_level_status": "A Levels", "o_passes": "O Level passes", "one_sitting": "O Levels in one sitting",
          "tertiary_status": "Post-school qualification", "age": "Age", "sex": "Mature-entry age group",
          "work_years": "Work experience", "work_field": "Field of work", "employed": "Currently employed"}


@dataclass
class ApplicantProfile:
    a_level: Dict[str, Fact] = field(default_factory=dict)
    a_level_ungraded: Dict[str, Fact] = field(default_factory=dict)
    a_level_status: Optional[Fact] = None
    o_level: Dict[str, Fact] = field(default_factory=dict)
    o_passes: Optional[Fact] = None
    one_sitting: Optional[Fact] = None
    tertiary_status: Optional[Fact] = None
    qualifications: List[Fact] = field(default_factory=list)
    age: Optional[Fact] = None
    sex: Optional[Fact] = None
    work_years: Optional[Fact] = None
    work_field: Optional[Fact] = None
    employed: Optional[Fact] = None
    interests: List[Fact] = field(default_factory=list)
    asked: List[str] = field(default_factory=list)        # question keys asked in this assessment, in order
    declined: List[str] = field(default_factory=list)     # question keys the applicant chose not to answer
    pending: Optional[Dict[str, Any]] = None              # a confirmation the adviser is waiting for
    form_applied: bool = False
    last_asked: Optional[str] = None                      # the question key the adviser's last reply asked
    recommended: bool = False                             # a shortlist has been shown in this assessment
    last_shortlist: List[Tuple[str, str, str]] = field(default_factory=list)   # (id, route, status) last shown
    loose_grades: Optional[Fact] = None                   # A Level grade letters given without subjects

    # -------------------------------------------------- state
    def is_empty(self) -> bool:
        return not (self.a_level or self.a_level_ungraded or self.a_level_status or self.o_level or self.o_passes
                    or self.one_sitting or self.tertiary_status or self.qualifications or self.age or self.sex
                    or self.work_years or self.work_field or self.employed is not None or self.interests)

    def has_results(self) -> bool:
        return bool(self.a_level or self.o_level or self.o_passes)

    def facts(self) -> List[Tuple[str, Fact]]:
        out: List[Tuple[str, Fact]] = [(f"a_level:{s}", f) for s, f in self.a_level.items()]
        out += [(f"a_level_ungraded:{s}", f) for s, f in self.a_level_ungraded.items()]
        out += [(f"o_level:{s}", f) for s, f in self.o_level.items()]
        out += [(f"qualification:{i}", f) for i, f in enumerate(self.qualifications)]
        out += [(f"interest:{i}", f) for i, f in enumerate(self.interests)]
        out += [(k, getattr(self, k)) for k in LABELS if getattr(self, k) is not None]
        return out

    def a_level_none(self) -> bool:
        return bool(self.a_level_status and self.a_level_status.value == "none" and not self.a_level)

    def tertiary_none(self) -> bool:
        return bool(self.tertiary_status and self.tertiary_status.value == "none")

    # -------------------------------------------------- updates
    def apply(self, u: Update, turn: int, status: str = STATED) -> List[str]:
        """Record what the update says; returns short descriptions of what changed (for the reply's recap)."""
        changed: List[str] = []
        if u.a_level:
            for s, g in u.a_level.items():
                old = self.a_level.get(s)
                if old is None or old.value != g:
                    changed.append(f"A Level {s} {g}" + (f" (was {old.value})" if old else ""))
                self.a_level[s] = Fact(g, status, turn)
                self.a_level_ungraded.pop(s, None)
        if u.loose_grades:
            self.loose_grades = Fact(list(u.loose_grades), status, turn)
        ungraded = [s for s in u.a_level_ungraded if s not in self.a_level]
        if self.loose_grades and ungraded and len(ungraded) == len(self.loose_grades.value) and not u.a_level:
            # "A, B and C" then "Mathematics, Physics and Chemistry": matched in the order given, shown as an assumption
            pairs = list(zip(ungraded, self.loose_grades.value))
            for s, g in pairs:
                self.a_level[s] = Fact(g, INFERRED, turn, "grades matched to subjects in the order you gave them")
            changed.append("A Levels (matched in the order you gave them): " + ", ".join(f"{s} {g}" for s, g in pairs))
            self.loose_grades, ungraded = None, []
        for s in ungraded:
            self.a_level_ungraded[s] = Fact(None, status, turn)
        if u.a_level_status and not (u.a_level_status == "none" and self.a_level):
            if not self.a_level_status or self.a_level_status.value != u.a_level_status:
                changed.append("no A Levels" if u.a_level_status == "none" else "you have A Levels")
            self.a_level_status = Fact(u.a_level_status, status, turn)
        for s, g in u.o_level.items():
            inferred = s in u.o_inferred
            old = self.o_level.get(s)
            if inferred and old is not None and old.value != PASS_ONLY:
                continue                                 # a stated grade beats "passed"
            note = "you said you passed it; the advert counts passes at grade C or better" if inferred else ""
            if old is None or old.value != g:
                changed.append(f"O Level {s} " + ("passed" if g == PASS_ONLY else "not passed" if g == "U" else g))
            self.o_level[s] = Fact(g, INFERRED if inferred else status, turn, note)
        if u.o_passes is not None:
            if not self.o_passes or self.o_passes.value != u.o_passes:
                changed.append(f"{u.o_passes} O Level passes")
            self.o_passes = Fact(u.o_passes, status, turn)
        if u.one_sitting is not None:
            self.one_sitting = Fact(u.one_sitting, status, turn)
            changed.append("O Levels in one sitting")
        for q in u.qualifications:
            target = next((f for f in self.qualifications if f.value.get("field") is None and q.get("field")), None)
            if q.get("kind") is None and target is None:
                target = next((f for f in self.qualifications if f.value.get("field") is None), None)
            if target is not None and (q.get("kind") is None or target.value.get("kind") in (None, q.get("kind"), "diploma", "certificate")):
                target.value = {"kind": q.get("kind") or target.value.get("kind"), "field": q.get("field")}
                target.turn = turn
                changed.append(describe_qualification(target.value))
            elif not any(f.value == q for f in self.qualifications):
                self.qualifications.append(Fact(dict(q), status, turn))
                changed.append(describe_qualification(q))
        if u.tertiary_status:
            if u.tertiary_status == "has" or not self.qualifications:
                self.tertiary_status = Fact(u.tertiary_status, status, turn)
                if u.tertiary_status == "none":
                    changed.append("no post-school qualification")
        for key in ("age", "sex", "work_years", "work_field", "employed"):
            value = getattr(u, key)
            if value is not None:
                old = getattr(self, key)
                if old is None or old.value != value:
                    changed.append(describe(key, value) + (f" (was {describe(key, old.value)})" if old else ""))
                setattr(self, key, Fact(value, status, turn))
        for x in u.interests:
            if not any(f.value == x for f in self.interests):
                self.interests.append(Fact(x, status, turn))
        return changed

    def remove_turn(self, turn: int) -> List[str]:
        """Forget every fact recorded from one message (e.g. "those were my brother's results")."""
        removed = []
        for name in ("a_level", "a_level_ungraded", "o_level"):
            d = getattr(self, name)
            for s in [s for s, f in d.items() if f.turn == turn]:
                removed.append(f"{'A' if name.startswith('a_') else 'O'} Level {s}" +
                               (f" {d[s].value}" if d[s].value not in (None, PASS_ONLY) else ""))
                del d[s]
        for name in ("qualifications", "interests"):
            keep = [f for f in getattr(self, name) if f.turn != turn]
            removed += [describe_qualification(f.value) if name == "qualifications" else f"interest in {f.value}"
                        for f in getattr(self, name) if f.turn == turn]
            setattr(self, name, keep)
        for key in LABELS:
            f = getattr(self, key)
            if f is not None and f.turn == turn:
                if key not in ("a_level_status", "tertiary_status"):
                    removed.append(describe(key, f.value))
                setattr(self, key, None)
        if not self.a_level and not self.a_level_ungraded and self.a_level_status and self.a_level_status.value == "has" \
                and self.a_level_status.turn == turn:
            self.a_level_status = None
        return removed

    def remove_results_set(self) -> List[str]:
        """"Those were my brother's results": forget the most recent set of exam results. Every result of the same
        level(s) goes (the original set and any later corrections to it), with everything else from that message."""
        t = self.latest_results_turn()
        if t is None:
            return []
        levels = {"a" for f in list(self.a_level.values()) + list(self.a_level_ungraded.values()) if f.turn == t} | \
                 {"o" for f in self.o_level.values() if f.turn == t} | ({"o"} if self.o_passes and self.o_passes.turn == t else set())
        turns = {t}
        if "a" in levels:
            turns |= {f.turn for f in list(self.a_level.values()) + list(self.a_level_ungraded.values())}
        if "o" in levels:
            turns |= {f.turn for f in self.o_level.values()} | ({self.o_passes.turn} if self.o_passes else set())
        removed: List[str] = []
        for turn in sorted(turns):
            removed += self.remove_turn(turn)
        return removed

    def confirm_all(self) -> None:
        for _, f in self.facts():
            if f.status == STATED:
                f.status = CONFIRMED

    def latest_results_turn(self) -> Optional[int]:
        turns = [f.turn for f in list(self.a_level.values()) + list(self.a_level_ungraded.values()) +
                 list(self.o_level.values())] + ([self.o_passes.turn] if self.o_passes else [])
        return max(turns) if turns else None

    # -------------------------------------------------- views
    def engine_inputs(self) -> Tuple[Dict[str, str], Optional[Dict[str, Any]]]:
        a = {s: f.value for s, f in self.a_level.items()}
        o: Dict[str, Any] = {s: f.value for s, f in self.o_level.items()}
        if self.o_passes is not None:
            o["passes"] = self.o_passes.value
        return a, (o or None)

    def summary(self) -> List[Dict[str, str]]:
        """What the adviser knows, for the profile panel and confirmations: label, value, status."""
        rows = []
        if self.a_level:
            rows.append({"label": "A Levels", "value": ", ".join(f"{s} {f.value}" for s, f in self.a_level.items()),
                         "status": _worst(self.a_level.values())})
        if self.a_level_ungraded:
            rows.append({"label": "A Levels (grade not given)", "value": ", ".join(self.a_level_ungraded),
                         "status": _worst(self.a_level_ungraded.values())})
        if not self.a_level and self.a_level_status:
            rows.append({"label": "A Levels", "value": "none" if self.a_level_status.value == "none" else
                         "yes (subjects not given yet)", "status": self.a_level_status.status})
        if self.o_level or self.o_passes:
            parts = ([f"{self.o_passes.value} passes"] if self.o_passes else []) + \
                    [f"{s} " + ("passed" if f.value == PASS_ONLY else f.value) for s, f in self.o_level.items()]
            facts = list(self.o_level.values()) + ([self.o_passes] if self.o_passes else [])
            rows.append({"label": "O Levels", "value": ", ".join(parts), "status": _worst(facts)})
        if self.one_sitting:
            rows.append({"label": "O Levels in one sitting", "value": "yes", "status": self.one_sitting.status})
        if self.qualifications:
            rows.append({"label": "Post-school qualification",
                         "value": "; ".join(describe_qualification(f.value) for f in self.qualifications),
                         "status": _worst(self.qualifications)})
        elif self.tertiary_status:
            rows.append({"label": "Post-school qualification", "value": "none", "status": self.tertiary_status.status})
        for key in ("age", "sex", "work_years", "work_field", "employed"):
            f = getattr(self, key)
            if f is not None:
                rows.append({"label": LABELS[key], "value": describe(key, f.value, short=True), "status": f.status})
        if self.interests:
            rows.append({"label": "Interested in", "value": ", ".join(f.value for f in self.interests),
                         "status": _worst(self.interests)})
        return rows

    def summary_text(self) -> str:
        return "; ".join(f"{r['label']}: {r['value']}" for r in self.summary())


def _worst(facts) -> str:
    statuses = {f.status for f in facts}
    return INFERRED if INFERRED in statuses else STATED if STATED in statuses else CONFIRMED


def describe_qualification(q: Dict[str, Optional[str]]) -> str:
    kind = q.get("kind") or "qualification"
    article = "an" if kind[:1].lower() in "aeiouh" and kind not in ("HND",) else "a"
    if kind in ("HND", "CIMA", "ACCA", "CIS", "IAC", "IPMZ"):
        article = "an" if kind[0] in "AEIOUH" else "a"
    return f"{article} {kind}" + (f" in {q['field']}" if q.get("field") else " (field not given yet)")


def describe(key: str, value: Any, short: bool = False) -> str:
    if key == "age":
        return f"{value}" if short else f"age {value}"
    if key == "sex":
        return ("female (mature-entry age 23)" if value == "female" else "male (mature-entry age 25)")
    if key == "work_years":
        if value == 0:
            return "no work experience"
        return f"{value} year{'s' if value != 1 else ''}" + ("" if short else " of work experience")
    if key == "work_field":
        if short:
            return value
        if re.search(r"(?:er|or|ist|ian|ant|nurse|officer|clerk|chef|soldier|secretary|farmer|teacher|developer)$", value):
            return f"work as {'an' if value[:1] in 'aeiou' else 'a'} {value}"
        return f"work in {value}"
    if key == "employed":
        return ("yes" if value else "no") if short else ("currently employed" if value else "not currently employed")
    return str(value)
