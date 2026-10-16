"""
Application safeguards around the grounded answer. They check inputs and evidence and attach visible notes for the
reader. The model's answer is changed in one narrow way only (present_answer): references to documents the user
"provided", and requests that the user supply documents, are corrected, because the assistant searches its own MSU
documents; the original text is kept in AssistantResult.raw_answer.

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
    sources = sources or []
    cited_sources = [sources[n - 1] for n in cited if 1 <= n <= len(sources)]
    if not cited:   # attributed by document name instead of evidence number: use the names it mentions
        cited_sources = [s for s in sources if (s == ADVERT_SOURCE and ADVERT.search(text)) or
                         ("Yearbook" in (s or "") and re.search(r"\byearbook", text, re.I))]
    if intake and ADVERT_SOURCE in cited_sources and any("Yearbook" in (s or "") for s in cited_sources):
        notes.append({"kind": "sources", "text": NOTE_MIXED_SOURCES})
    if ADMISSIONS.search(question or "") or ADMISSIONS.search(text):
        notes.append({"kind": "admissions", "text": NOTE_ADMISSIONS_INTAKE if intake else NOTE_ADMISSIONS})
    if public_profile and ADVERT.search(text):
        notes.append({"kind": "advert", "text": NOTE_ADVERT})
    return notes


# ------------------------------------------------------------------ wording on misses
_USER_PROVIDED = re.compile(
    r"\b(?:the|these|those)\s+(?:MSU\s+)?(?:documents?|evidence|passages?|excerpts?|sources?|information|materials?|"
    r"yearbook(?:\s+(?:excerpts?|passages?))?)\s+(?:that\s+)?you(?:\s+have|'ve|’ve)?\s+(?:provided|supplied|gave|given|"
    r"shared|sent|uploaded)\b"
    r"|\b(?:the\s+)?(?:supplied|provided)\s+(?:MSU\s+)?(?:documents?|evidence(?:\s+passages?)?|passages?|excerpts?|"
    r"yearbook\s+(?:excerpts?|passages?)|sources?)\b"
    # "the documents provided do not ..." (but not "the information provided in Evidence 1")
    r"|\bthe\s+(?:MSU\s+)?(?:documents?|evidence|passages?|excerpts?|sources?|materials?)\s+(?:provided|supplied)\b"
    r"(?!\s+(?:in|by|for|on|under|with|at|from)\b)", re.I)
_ASK_TO_PROVIDE = re.compile(
    r"\b(?:if\s+you\s+(?:can\s+|could\s+)?(?:provide|supply|share|upload|send)|"
    r"(?:please|kindly)\s+(?:provide|supply|share|upload|send)|you\s+(?:may|might|could)\s+(?:provide|supply|share|upload))"
    r"\b", re.I)
_ABBREVIATIONS = re.compile(r"\b(?:e\.g|i\.e|etc|cf|vs|No|p|pp|Vol)\.", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+(?=[A-Z“\"(])")
SEARCHED = "the MSU documents I searched"
TIP_SOURCES = {"intake": "the MSU yearbooks, the 2027 academic road map and the January/February 2027 intake advert",
               "public": "the MSU yearbooks and the 2027 academic road map",
               "baseline": "the MSU yearbooks"}
NOTE_MISS_TIP = ("I searched {sources}. If you expected an answer, try naming the programme and what you need, for "
                 "example: “BSc Honours in Computer Science 2027 entry requirements”.")


def present_answer(answer: str) -> str:
    """Correct 'documents you provided' wording and drop sentences asking the user to supply documents."""
    original = answer or ""

    def searched(m: "re.Match") -> str:
        plural = re.search(r"(?:documents|passages|excerpts|sources|materials)\b", m.group(0), re.I)
        phrase = SEARCHED if plural else "the MSU evidence I searched"
        sentence_start = not original[:m.start()].strip() or re.search(r"(?:[.?!]|\n)\s*$", original[:m.start()])
        return phrase[0].upper() + phrase[1:] if sentence_start else phrase
    text = _USER_PROVIDED.sub(searched, original)

    lines = []
    for line in text.split("\n"):
        protected = _ABBREVIATIONS.sub(lambda m: m.group(0).replace(".", "․"), line)   # one-dot leader
        kept = [s for s in _SENTENCE_SPLIT.split(protected) if not _ASK_TO_PROVIDE.search(s)]
        if kept or not line.strip():
            lines.append(" ".join(kept).replace("․", "."))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text or original


def miss_tip(answer: str, kind: str) -> List[Dict[str, str]]:
    """A rephrasing tip when the answer says the information was not found."""
    if DECLINE.search(answer or "") and not cited_numbers(answer):
        return [{"kind": "tip", "text": NOTE_MISS_TIP.format(sources=TIP_SOURCES.get(kind, TIP_SOURCES["public"]))}]
    return []


# ------------------------------------------------------------------ "not found" responses
NOT_FOUND = re.compile(
    r"do(?:es)? not (?:contain|include|mention|provide|have) (?:any |the )?(?:information|details?|data|mention)"
    r"|(?:could|can)\s?not find|could not locate|no (?:relevant )?information (?:is |was )?(?:available|found|provided)?"
    r"|no information about|contain no information|cannot (?:answer|provide|help)|can[’']?t (?:help|answer|provide)"
    r"|not (?:covered|included) in the (?:MSU )?(?:documents|evidence|sources)"
    r"|documents (?:searched )?do not (?:contain|include|mention|provide)", re.I)


def is_not_found(status: str, answer: str) -> bool:
    """True when the assistant could not find an answer: no evidence was retrieved, or the generated answer says
    the documents contain no such information and cites no evidence passage."""
    if status == "no_evidence":
        return True
    return status == "answered" and bool(NOT_FOUND.search(answer or "")) and not cited_numbers(answer)


# ------------------------------------------------------------------ fact verification against the evidence
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_FACT_DATE = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTHS})\s+(\d{{4}})\b", re.I)
_FACT_DURATION = re.compile(r"\b(\d+(?:\.\d+)?|\d*\s*½)\s*-?\s*(years?|months?)\b", re.I)
_FACT_CLASS = re.compile(r"(?<![\d.])2\.[12](?![\d])")
_FACT_CODE = re.compile(r"\b([A-Z]{2,6})\s?(\d{3}[A-Z]?)\b")
_NUM_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_MONTH_NAMES = MONTHS.split("|")
_WORD_NUMBERS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "twelve": "12",
                 "eighteen": "18"}


def _norm_facts_text(text: str) -> str:
    t = (text or "").lower().replace(" ", " ").replace(" ", " ").replace("‑", "-")
    t = _NUM_DATE.sub(lambda m: f"{int(m.group(1))} {_MONTH_NAMES[int(m.group(2)) - 1]} {m.group(3)}"
                      if 1 <= int(m.group(2)) <= 12 else m.group(0), t)
    t = re.sub(r"(\d)\s*1\s*/\s*2", r"\1.5", t.replace("1½", "1 ½"))
    t = re.sub(r"(\d+)\s*½", lambda m: f"{m.group(1)}.5", t)
    for w, n in _WORD_NUMBERS.items():
        t = re.sub(rf"\b{w}\b", n, t)
    t = re.sub(r"\b(\d+)\s*\((\d+)\)", lambda m: m.group(2) if m.group(1) == m.group(2) else m.group(0), t)  # 18 (18)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*-?\s*(year|month)", r"\1 \2", t)
    return re.sub(r"\s+", " ", t)


def unverified_facts(answer: str, evidence_texts: List[str], question: str = "") -> List[str]:
    """Dates, durations, degree classes (2.1/2.2) and module codes in the answer that appear in none of the evidence
    passages (nor in the question). Deterministic; used only to show a caution note, never to change the answer."""
    source = _norm_facts_text(" ".join(evidence_texts) + " " + (question or ""))
    found = []
    text = answer or ""
    for m in _FACT_DATE.finditer(text):
        key = f"{int(m.group(1))} {m.group(2).lower()} {m.group(3)}"
        if key not in source:
            found.append(m.group(0))
    for m in _FACT_DURATION.finditer(_norm_facts_text(text)):
        num = m.group(1).replace(" ", "")
        num = "0.5" if num == "½" else num
        unit = "year" if m.group(2).startswith("year") else "month"
        if not re.search(rf"(?<![\d.]){re.escape(num)} {unit}", source):
            found.append(f"{m.group(1).strip()} {m.group(2)}")
    for m in _FACT_CLASS.finditer(text):
        if m.group(0) not in source:
            found.append(m.group(0))
    for m in _FACT_CODE.finditer(text):
        code = (m.group(1) + m.group(2)).lower()
        if m.group(1) in ("MSU", "ZNQF", "HND", "ND", "UZ") or code in source.replace(" ", ""):
            continue
        found.append(m.group(1) + m.group(2))
    for m in _FACT_DESCRIPTOR.finditer(_norm_facts_text(text)):     # 'full-time' / 'part-time' study descriptors
        if not re.search(rf"\b{m.group(1)}[- ]?time\b", source):
            found.append(f"{m.group(1)}-time")
    return list(dict.fromkeys(found))


_FACT_DESCRIPTOR = re.compile(r"\b(full|part)[- ]?time\b", re.I)
_DESCRIPTOR_PAREN = re.compile(r"\s*\((?:full|part)[\s\-‐‑]?time[^)]*\)", re.I)
_DESCRIPTOR_WORD = re.compile(r"\b(?:full|part)[\s\-‐‑]?time\b[\s,]*", re.I)


def remove_unsupported_descriptors(answer: str, evidence_texts: List[str]) -> str:
    """Remove 'full-time' / 'part-time' qualifiers that no evidence passage contains (the advert never classifies its
    study modes that way; the model sometimes adds it). Only that qualifier is removed; the rest of the answer is
    unchanged, and the original text is kept in AssistantResult.raw_answer."""
    source = " ".join(evidence_texts).lower()
    text = answer or ""
    for kind in ("full", "part"):
        if re.search(rf"\b{kind}[\s\-‐‑]?time\b", source):
            continue
        text = re.sub(rf"\s*\({kind}[\s\-‐‑]?time[^)]*\)", "", text, flags=re.I)
        text = re.sub(rf"\b{kind}[\s\-‐‑]?time\b[ ,]*", "", text, flags=re.I)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\b(a|an)\s+(?=[,.;:)])", "", text)
    return re.sub(r" +([,.;:)])", r"\1", text)


NOTE_UNVERIFIED = ("Check these details against the sources below; they were not found in the retrieved passages: "
                   "{facts}.")


def fact_notes(answer: str, evidence: List[Dict[str, Any]], question: str = "") -> List[Dict[str, str]]:
    facts = unverified_facts(answer, [e.get("text") or "" for e in evidence], question)
    notes = [{"kind": "verification", "text": NOTE_UNVERIFIED.format(facts=", ".join(facts[:6]))}] if facts else []
    return notes + mode_combination_notes(answer, evidence)


# ------------------------------------------------------------------ campus / study-mode combinations
CAMPUSES = ("Gweru", "Harare", "Bulawayo", "Zvishavane", "Kwekwe")
STUDY_MODES = ("Block Release", "Weekend School", "Weekend Class", "Conventional", "Visiting")
_MODES_LINE = re.compile(r"MODES OF ENTRY:\s*([^\n]+)", re.I)
NOTE_MODE_COMBINATION = ("This answer lists a campus and study mode combination that the advert does not show: "
                         "{pairs}. Use only the routes listed in the sources below.")


def _mode_of(text: str) -> Optional[str]:
    t = text.lower()
    return next((m for m in STUDY_MODES if m.lower() in t), None)


def advertised_pairs(evidence: List[Dict[str, Any]]) -> set:
    pairs = set()
    for e in evidence:
        for line in _MODES_LINE.findall(e.get("text") or ""):
            for part in line.split(";"):
                campus = next((c for c in CAMPUSES if c.lower() in part.lower()), None)
                mode = _mode_of(part)
                if campus and mode:
                    pairs.add((campus, "Weekend School" if mode == "Weekend Class" else mode))
    return pairs


_MODE_ALT = "|".join(re.escape(m) for m in STUDY_MODES)
_CAMPUS_ALT = "|".join(CAMPUSES)
# an explicit campus + mode phrase: "Bulawayo Visiting", "Gweru – Visiting", "Harare (Weekend School)", "Gweru: Conventional"
_PAIR_PHRASE = re.compile(rf"\b({_CAMPUS_ALT})(?:\s+campus)?\s*(?:[\-–—:(]\s*)?({_MODE_ALT})\b", re.I)


def _canon_mode(m: str) -> str:
    m = next(s for s in STUDY_MODES if s.lower() == m.lower())
    return "Weekend School" if m == "Weekend Class" else m


def unadvertised_pairs(answer: str, evidence: List[Dict[str, Any]]) -> List[str]:
    """Campus + mode pairs the answer states explicitly that are not among the advert's MODES OF ENTRY in the
    evidence. Only high-precision forms are checked: an explicit phrase ('Bulawayo Visiting', 'Gweru – Visiting') and a
    table row whose cell is a campus followed by a cell that starts with a mode ('| Bulawayo | Visiting | 3 years |').
    Loose sentences ('a conventional route at Gweru and a weekend-school route at Bulawayo') are not interpreted."""
    allowed = advertised_pairs(evidence)
    if not allowed:
        return []
    found = []
    text = re.sub(r"(?<=[A-Za-z])[\-‐‑‒](?=[A-Za-z])", " ", answer or "")   # weekend-school
    for m in _PAIR_PHRASE.finditer(text):
        found.append((m.group(1).title(), _canon_mode(m.group(2))))
    for line in text.splitlines():
        if line.count("|") < 2:
            continue
        cells = [c.strip(" *") for c in line.strip().strip("|").split("|")]
        for i, cell in enumerate(cells[:-1]):
            campus = next((c for c in CAMPUSES if re.fullmatch(rf"{c}(?:\s+campus)?", cell, re.I)), None)
            mode = re.match(rf"({_MODE_ALT})\b", cells[i + 1], re.I) if campus else None
            if campus and mode:
                found.append((campus, _canon_mode(mode.group(1))))
    bad = []
    for c, m in found:
        if (c, m) not in allowed and f"{c} {m}" not in bad:
            bad.append(f"{c} {m}")
    return bad


def mode_combination_notes(answer: str, evidence: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    bad = unadvertised_pairs(answer, evidence)
    return [{"kind": "mode_combination", "text": NOTE_MODE_COMBINATION.format(pairs=", ".join(bad[:4]))}] if bad else []
