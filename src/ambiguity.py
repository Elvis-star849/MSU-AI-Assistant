"""
S6-5: course codes that name different modules in different programmes (e.g. SEMA204 is "Real Analysis" in one
programme table and "Introduction to Numerical Methods" elsewhere).

Metadata only: retrieval and ranking are unchanged. Stage 7 uses the flag to name every meaning (or ask which
programme the student means) instead of answering as if the code had one meaning.
"""
import difflib
import re
from typing import Any, Dict, List

from src.vectorstore import course_codes

_CITATION_HEADER = re.compile(r"^\[[^\]\n]*\]\n")
# "SEMA204: Real Analysis", "MIM 732 Advanced Databases", "MADP 825 - Development Practice Project"
_CODE_TITLE = re.compile(r"^\*?([A-Z]{2,6}) ?(\d{3})\*?\s*[:\-–]?\s*([A-Z][^\n]{2,90})$")
_CODE_ONLY = re.compile(r"^\*?([A-Z]{2,6}) ?(\d{3})\*?$")
_OTHER_CODE = re.compile(r"\b[a-z]{2,6} ?\d{3}\b")
# two titles are the same module if one starts the other, the spelling is this similar, or this share of the
# shorter title's words appears in the other (any order): "Grassland Science" = "Grassland and Pasture Science"
SAME_TITLE_RATIO = 0.8
SAME_WORDS_SHARE = 0.75
_STOP = {"and", "of", "the", "in", "to", "for", "a", "an", "on", "with", "i", "ii", "1", "2"}


def _clean(title: str) -> str:
    """Drop trailing credits ("Real Analysis 12"), bracketed notes and "- Refer to ..." remarks."""
    title = re.sub(r"\s+\d{1,3}$", "", title.strip())
    title = re.sub(r"\s*[(\[][^)\]]*[)\]]", "", title)
    return re.split(r"\s+[-–]\s+", title)[0].strip(" *")


def _normalise(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", _clean(title).lower())).strip()


def _words(norm: str) -> set:
    return {w for w in norm.split() if w not in _STOP}


def _title_like(line: str) -> bool:
    words = re.findall(r"[A-Za-z]{2,}", line)
    return bool(line) and line[0].isupper() and 1 <= len(words) <= 14 and not _CODE_ONLY.match(line) \
        and not _CODE_TITLE.match(line)


def _same(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    shared = len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0.0
    return a.startswith(b) or b.startswith(a) or shared >= SAME_WORDS_SHARE or \
        difflib.SequenceMatcher(None, a, b).ratio() >= SAME_TITLE_RATIO


def code_titles(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """code ("sema204") -> distinct titles, each with the chunks and pages that give it."""
    found: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        lines = [l.strip() for l in _CITATION_HEADER.sub("", r["text"], count=1).split("\n")]
        for i, line in enumerate(lines):
            m = _CODE_TITLE.match(line)
            if m:
                code, title = (m.group(1) + m.group(2)).lower(), m.group(3)
            else:
                m = _CODE_ONLY.match(line)
                following = next((l for l in lines[i + 1:] if l), "")
                if not (m and _title_like(following)):
                    continue
                code, title = (m.group(1) + m.group(2)).lower(), following
            norm = _normalise(title)
            if len(norm) < 4 or _OTHER_CODE.search(norm):  # too short, or a list of other codes, not a title
                continue
            groups = found.setdefault(code, [])
            group = next((g for g in groups if _same(g["normalised"], norm)), None)
            if group is None:
                groups.append({"title": _clean(title), "normalised": norm,
                               "chunk_ids": [r["chunk_id"]], "pages": [f"{r['source']} p. {r['page']}"]})
            elif r["chunk_id"] not in group["chunk_ids"]:
                group["chunk_ids"].append(r["chunk_id"])
                group["pages"].append(f"{r['source']} p. {r['page']}")
    return found


def ambiguous_codes(titles: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    return {code: groups for code, groups in titles.items() if len(groups) > 1}


def ambiguity_note(query: str, results: List[Dict[str, Any]],
                   ambiguous: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    For each code in the query that has several meanings: all its titles, and which of them the retrieved chunks
    support. Stage 7 must mention every meaning (or ask for the programme) when this list is not empty.
    """
    retrieved = {r["chunk_id"] for r in results}
    notes = []
    for code in course_codes(query):
        if code in ambiguous:
            notes.append({"code": code.upper(), "titles": [
                {"title": g["title"], "pages": g["pages"], "in_results": bool(retrieved & set(g["chunk_ids"]))}
                for g in ambiguous[code]]})
    return notes
