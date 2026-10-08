"""
Stage 6 (S6-3): document-structure headings for heading-aware retrieval.

Each chunk inherits the headings that govern it, found by reading the chunks of each yearbook in order:
  part     - a document part or programme title, e.g. "MIDLANDS STATE UNIVERSITY ACT",
             "REGULATIONS FOR THE MASTER OF SCIENCE DEGREE IN HORTICULTURE", "FACULTY OF ..."
  section  - the latest numbered heading, e.g. "5 Membership of the University", "13. ELIGIBILITY FOR EXAMINATIONS",
             or a module title line followed by its description, e.g. "MIM 732 Advanced Databases"
  sub      - the latest programme-table row group inside a section, e.g. "Level 1 Semester 2"
A chunk's heading is the state in force where it starts, plus any headings opened inside it.
The chunk text itself is never changed; the heading is only added to what retrieval indexes.
"""
import re
from typing import Dict, List, Optional

STRUCTURE_VERSION = "v2"  # bump if the detection rules change
# v2 (after the S6-3 accuracy sample, before any index build): join wrapped titles whose second line holds a code
# such as "(BS09)"; accept "CODE - Title" module lines; look into the next chunk when a module title ends a chunk

_CITATION_HEADER = re.compile(r"^\[[^\]\n]*\]\n")

# Document parts / programme titles: an all-capitals line starting with one of these words
_PART_START = re.compile(r"^(REGULATIONS FOR|GENERAL ACADEMIC REGULATIONS|FACULTY OF|SCHOOL OF|GRADUATE SCHOOL|"
                         r"INSTITUTE OF|CENTRE FOR|DEPARTMENT OF|MIDLANDS STATE UNIVERSITY ACT|STATUTES OF)\b")
# Numbered section headings: "5 Membership of the University", "6.2 Full Registration", "13. ELIGIBILITY ..."
_NUMBERED = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+([A-Z][A-Za-z0-9 ,'&/()\-]{2,80})$")
# Words that make a numbered line a sentence (a regulation clause), not a heading
_SENTENCE_WORDS = re.compile(r"\b(shall|must|may|will|is|are|was|were|should|can|has|have)\b")
# Module title line: "MIM 732 Advanced Databases", "SEBI 203: Plant Morphology ...", "HMECH113* Engineering Physics",
# "MADP 825 - Development Practice Project"
_MODULE = re.compile(r"^([A-Z]{2,6}) ?(\d{3})\*?\s*[:\-–]?\s*([A-Z][^\n]{3,90})$")
# Programme-table row groups: "Level 1 Semester 2", "LEVEL 3 SEMESTER 1 WORK-RELATED LEARNING", "Level II"
_LEVEL = re.compile(r"^(?:Level|LEVEL)\s*:?\s*(\d|I{1,3}|IV)\b(?:\s*(?:Semester|SEMESTER)\s*(\d))?[^\n]{0,60}$")
# A chunk with at least this many section headings, making up most of its lines, is a contents page or list,
# so it does not change the state
_CONTENTS_THRESHOLD = 5
_CONTENTS_SHARE = 0.6


def _body(text: str) -> str:
    return _CITATION_HEADER.sub("", text, count=1)


def _is_caps(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 8 and all(c.isupper() for c in letters)


def _numbered(line: str) -> Optional[str]:
    m = _NUMBERED.match(line)
    if not m:
        return None
    title = m.group(2).strip()
    words = re.findall(r"[A-Za-z]{2,}", title)
    if not 1 <= len(words) <= 12 or title.endswith((",", ";", ":", ".")) or _SENTENCE_WORDS.search(title.lower()):
        return None
    # long sentence-case lines are list items (e.g. learning outcomes), not headings
    title_case = sum(1 for w in words if len(w) > 3 and w[0].isupper()) >= 0.6 * sum(1 for w in words if len(w) > 3)
    if len(words) > 8 and not (_is_caps(title) or title_case):
        return None
    if len(words) == 1 and not _is_caps(title) and len(title) < 6:
        return None
    return f"{m.group(1)} {title}"


def detect(lines: List[str], lookahead: List[str] = ()) -> List[tuple]:
    """
    (position, level, heading) for every heading line in a chunk body. level: part / section / sub.
    lookahead: the next chunk's lines, used when a heading is the chunk's last line of text.
    """
    found, i = [], 0
    while i < len(lines):
        line = lines[i].strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        # first line of text after this one, in this chunk or (if none) at the start of the next chunk
        following = next((l.strip() for l in list(lines[i + 1:]) + list(lookahead)
                          if l.strip() and l.strip() != line), "")
        # a title ending in dot leaders or a page number is a contents-page entry, not the part itself
        if _is_caps(line) and _PART_START.match(line) and not re.search(r"(\.{3,}|…)|\s\d{1,4}$", line):
            title = line
            # titles wrap: join one following all-capitals line (it may hold a code such as "(BS09)")
            if nxt and _is_caps(nxt) and not re.match(r"\d", nxt) and len(nxt.split()) <= 8:
                title, i = f"{title} {nxt}", i + 1
            found.append((i, "part", re.sub(r"\s+", " ", title)[:150]))
        elif _MODULE.match(line) and len(re.findall(r"[A-Za-z]+", following)) >= 8:
            m = _MODULE.match(line)
            found.append((i, "section", f"{m.group(1)} {m.group(2)} {m.group(3).strip()}"))
        elif _numbered(line):
            found.append((i, "section", _numbered(line)))
        elif _LEVEL.match(line):
            found.append((i, "sub", re.sub(r"\s+", " ", line)))
        i += 1
    return found


def assign_headings(records: List[Dict]) -> List[Dict[str, Optional[str]]]:
    """For each chunk (in chunk_id order), the part / section / sub headings that govern it."""
    out, state, current_file = [], {}, None
    for n, r in enumerate(records):
        if r.get("file_name") != current_file:  # each yearbook file starts with no headings
            state, current_file = {"part": None, "section": None, "sub": None}, r.get("file_name")
        lines = _body(r["text"]).split("\n")
        after = records[n + 1] if n + 1 < len(records) else None
        lookahead = _body(after["text"]).split("\n") if after and after.get("file_name") == current_file else []
        found = detect(lines, lookahead)
        sections = sum(1 for _, level, _ in found if level == "section")
        is_contents = sections >= _CONTENTS_THRESHOLD and \
            len(found) >= _CONTENTS_SHARE * sum(1 for line in lines if line.strip())
        heading_rows = {pos for pos, _, _ in found}
        first_text = next((i for i, line in enumerate(lines) if line.strip() and i not in heading_rows), len(lines))
        start = None
        if not is_contents:
            for pos, level, heading in found:
                if pos > first_text and start is None:
                    start = dict(state)  # headings above the chunk's first line of text govern the whole chunk
                if level == "part":
                    state = {"part": heading, "section": None, "sub": None}
                elif level == "section":
                    state["section"], state["sub"] = heading, None
                else:
                    state["sub"] = heading
        start = start or dict(state)
        # headings in force at the start of the chunk, completed by the first ones opened inside it
        heading = {k: start[k] or state[k] for k in ("part", "section", "sub")}
        heading["contents_page"] = is_contents
        out.append(heading)
    return out


def heading_line(heading: Dict[str, Optional[str]]) -> str:
    """One line added in front of the chunk for retrieval, e.g. "Section: PART > 5 Membership ..."."""
    parts = [heading[k] for k in ("part", "section", "sub") if heading.get(k)]
    return "Section: " + " > ".join(parts) if parts else ""
