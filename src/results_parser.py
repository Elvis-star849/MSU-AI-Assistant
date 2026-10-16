"""
Deterministic reading of exam results from a chat message (no model call).

    parse_results(text) -> Parsed

Understands "Mathematics A, Physics B", "maths=a", "A in Chemistry", "a B in Physics", "O level English B, Maths C,
6 passes", "five O level passes" and corrections such as "actually Physics is B". Subject names and aliases come from
the eligibility rules (taxonomy and aliases). Results are A Level unless an "O level" marker comes before them in the
same message (or the assistant asked for O Level results).

Parsed.confident is False when the message contains grade letters the parser could not attach to a subject; the
caller then asks the model (src/extract_grades.py), which is otherwise not needed.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.eligibility import RULES, norm

A_GRADES = set("ABCDEFO")
O_GRADES = set("ABCDEU")
O_SUBJECTS = {"english": "English", "english language": "English", "maths": "Mathematics", "math": "Mathematics",
              "mathematics": "Mathematics", "science": "Science", "combined science": "Combined Science",
              "integrated science": "Combined Science"}
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12}
_names = sorted(set(RULES["taxonomy"]) | set(RULES["aliases"]) | set(O_SUBJECTS), key=len, reverse=True)
_SUBJ = r"(?P<subj>%s)" % "|".join(re.escape(n) for n in _names)
# "Mathematics A", "maths = a", "Maths: B", "Physics - C", "Physics grade B"
_PAIR = re.compile(rf"(?<![A-Za-z]){_SUBJ}\s*(?:[=:\-]|\bgrade\b|\bis\b|\bwas\b|\bat\b)?\s*(?P<grade>[A-Fa-fOoUu])(?![A-Za-z'’])", re.I)
# "A in Chemistry", "a B in Physics", "an A for Maths"
_REVERSE = re.compile(rf"(?<![A-Za-z])(?:an?\s+)?(?P<grade>[A-F])\s+(?:in|for)\s+{_SUBJ}(?![A-Za-z])")
_O_MARK = re.compile(r"\b(?:o[\s'’-]*levels?|ordinary\s+levels?|zimsec\s+o)\b", re.I)
_A_MARK = re.compile(r"\b(?:a[\s'’-]*levels?|advanced\s+levels?)\b", re.I)
_PASSES = re.compile(r"\b(?P<n>\d{1,2}|%s)\s+(?:o[\s'’-]*level\s+)?(?:passes|subjects passed|o[\s'’-]*levels)\b"
                     % "|".join(NUMBER_WORDS), re.I)
_PASSES_AFTER = re.compile(r"\bpasses\s*[=:]\s*(?P<n>\d{1,2})\b", re.I)
_GRADE_TOKEN = re.compile(r"(?<![A-Za-z'’])[A-FOU](?![A-Za-z'’])")
_SUBJECT_ONLY = re.compile(rf"(?<![A-Za-z]){_SUBJ}(?![A-Za-z])", re.I)


@dataclass
class Parsed:
    a_level: Dict[str, str] = field(default_factory=dict)
    o_level: Dict[str, object] = field(default_factory=dict)
    subjects_without_grade: List[str] = field(default_factory=list)
    confident: bool = True
    found_anything: bool = False


def _o_ranges(text: str) -> List[tuple]:
    """Spans of the message that are about O Level results: from an O Level marker to the next A Level marker."""
    spans, marks = [], sorted([(m.start(), "O") for m in _O_MARK.finditer(text)] +
                              [(m.start(), "A") for m in _A_MARK.finditer(text)])
    for i, (pos, kind) in enumerate(marks):
        if kind == "O":
            end = next((p for p, k in marks[i + 1:] if k == "A"), len(text))
            spans.append((pos, end))
    return spans


def _looks_like_o_level(text: str) -> bool:
    """English with a grade, or a number of passes, and only O Level-type subjects: an O Level answer."""
    pairs = [m.group("subj").lower() for m in _PAIR.finditer(text)]
    english = any(p.startswith("english") for p in pairs)
    passes = bool(_PASSES.search(text) or _PASSES_AFTER.search(text))
    return (english or passes) and bool(pairs) and all(p in O_SUBJECTS for p in pairs) and not _A_MARK.search(text)


def parse_results(text: str, o_level_context: bool = False) -> Parsed:
    text = text or ""
    out = Parsed()
    implied = (o_level_context or _looks_like_o_level(text)) and not _A_MARK.search(text)
    explicit = _o_ranges(text)
    in_o = lambda pos: any(a <= pos < b for a, b in explicit)
    used = []
    for m in list(_PAIR.finditer(text)) + list(_REVERSE.finditer(text)):
        if any(a <= m.start() < b or a < m.end() <= b for a, b in used):
            continue
        raw, grade = m.group("subj").lower(), m.group("grade").upper()
        if raw in ("a",):                                        # never a subject
            continue
        # O Level when an explicit 'O level' marker covers it, or when O Level is only implied (the assistant asked for
        # O Level results) and the subject is an O Level-type subject; 'Economics A' then stays an A Level result.
        if in_o(m.start()) or (implied and raw in O_SUBJECTS):
            name = O_SUBJECTS.get(raw) or norm(raw)
            if grade in O_GRADES:
                out.o_level[name] = grade
                used.append((m.start(), m.end()))
        elif grade in A_GRADES:
            if raw in O_SUBJECTS and raw not in RULES["aliases"] and norm(raw) not in RULES["taxonomy"]:
                continue                                         # e.g. "English" alone is not an A Level subject
            out.a_level[norm(raw)] = grade
            used.append((m.start(), m.end()))
    for rx in (_PASSES, _PASSES_AFTER):
        m = rx.search(text)
        if m:
            n = m.group("n").lower()
            out.o_level["passes"] = int(NUMBER_WORDS.get(n, n))
            used.append((m.start(), m.end()))
    # grade letters left over that were not attached to a subject -> not confident
    leftovers = [m for m in _GRADE_TOKEN.finditer(text) if not any(a <= m.start() < b for a, b in used)]
    leftovers = [m for m in leftovers if not (m.group(0) == "A" and _A_MARK.match(text, m.start()))
                 and not (m.group(0) == "O" and _O_MARK.match(text, m.start()))
                 and not (m.group(0) in ("A", "I") and text[m.end():m.end() + 1] == " " and _starts_word(text, m.end()))]
    named = {norm(m.group("subj").lower()) for m in _SUBJECT_ONLY.finditer(text) if not in_o(m.start())}
    out.subjects_without_grade = sorted(s for s in named if s not in out.a_level and s in RULES["taxonomy"])
    out.confident = not leftovers
    out.found_anything = bool(out.a_level or out.o_level)
    return out


def _starts_word(text: str, pos: int) -> bool:
    """'A level', 'A Level', 'a good...' : the letter is an article or part of 'A level', not a grade."""
    nxt = text[pos + 1:pos + 8].lower()
    return bool(re.match(r"[a-z]{2,}", nxt)) and not re.match(r"(?:in|for)\b", nxt)
