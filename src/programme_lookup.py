"""
Structured programme lookup over the approved January/February 2027 intake advert records.

    find_programmes(question) -> [record, ...]          all routes of the programme(s) the question names
    programme_groups(question) -> [ProgrammeGroup, ...]  the same, grouped by programme (one group, several routes)
    search(text="", faculty=None, level=None, campus=None, mode=None) -> [ProgrammeGroup, ...]   (programme explorer)

The records are read from the dataset registered for intake-2027-jan-feb in the verified knowledge-base version
(registry snapshot of version 0006; the file's SHA-256 is checked against the registry). Nothing here writes to the
knowledge base. Each record keeps its passage_uid, so the retriever can add the exact advert passages of every route
to the evidence (see profiles.ProgrammeLookupRetriever), and every fact shown carries its advert page.
"""
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.kb.fsutil import sha256_file

ROOT = Path(__file__).resolve().parents[1]
KB_ROOT = ROOT / "knowledge_base"
STAGING_VERSION = "0006"
DOC_ID = "intake-2027-jan-feb"
GENERIC = {"bachelor", "honours", "degree", "science", "sciences", "master", "masters", "diploma", "postgraduate",
           "studies", "management", "technology", "technologies", "engineering", "education", "applied", "and", "the",
           "with", "for", "programme", "course", "what", "are", "entry", "requirements", "how", "long", "does", "take",
           "when", "start", "offered", "campus", "msu", "special", "dual", "arts", "commerce", "development"}
LEVEL_HINTS = {"postgraduate": re.compile(r"\b(?:masters?|msc|mba|mcom|med|ma|postgraduate|pgd)\b", re.I),
               "undergraduate": re.compile(r"\b(?:bachelor|bsc|bcom|bed|ba|undergraduate|degree|honours)\b", re.I)}


@dataclass
class ProgrammeGroup:
    programme: str
    level: str
    faculty: str
    routes: List[Dict[str, Any]] = field(default_factory=list)
    match: str = ""                                    # exact | words (find_programmes)


def _clean(text: str) -> str:
    return (text or "").replace("�", "'").replace("’", "'").replace("‘", "'").replace("–", "-")


@lru_cache(maxsize=1)
def records() -> List[Dict[str, Any]]:
    snap = json.loads((KB_ROOT / "store/versions" / STAGING_VERSION / "registry_snapshot.json").read_text(encoding="utf-8"))
    doc = next(d for d in snap["documents"] if d["doc_id"] == DOC_ID)
    path = KB_ROOT / doc["dataset"]["path"]
    if sha256_file(path) != doc["dataset"]["sha256"]:
        raise RuntimeError("intake advert dataset does not match the registered SHA-256")
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for r in data["programmes"]:
        out.append({"id": r["id"], "programme": _clean(r["programme"]), "level": _clean(r["level"]),
                    "faculty": _clean(r["faculty"]), "duration": _clean(r["duration_as_advertised"]),
                    "modes": [m["as_written"] for m in r["modes_of_entry"]],
                    "campuses": sorted({m.get("campus") for m in r["modes_of_entry"] if m.get("campus")}),
                    "study_modes": sorted({m.get("study_mode") for m in r["modes_of_entry"] if m.get("study_mode")}),
                    "entry_requirements": [_clean(x) for x in r["entry_requirements"]],
                    "commencement": _clean(r.get("commencement") or ""), "programme_note": _clean(r.get("programme_note") or ""),
                    "faculty_note": _clean(r.get("faculty_note") or ""), "source_page": r["source_page"],
                    "passage_uid": f"{DOC_ID}/v{doc['doc_version']}/{r['id']}"})
    return out


def _short(name: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*", " ", name.rsplit(" in ", 1)[-1]).strip().rstrip(".").lower()


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in GENERIC}


def _group(recs: List[Dict[str, Any]], match: str = "") -> List[ProgrammeGroup]:
    groups: Dict[tuple, ProgrammeGroup] = {}
    for r in recs:
        key = (r["programme"].lower().rstrip("."), r["level"])
        groups.setdefault(key, ProgrammeGroup(r["programme"], r["level"], r["faculty"], match=match)).routes.append(r)
    return list(groups.values())


def programme_groups(question: str, max_groups: int = 4) -> List[ProgrammeGroup]:
    """Programmes named in the question. Exact matches (the full name, or the whole name after 'in', as a phrase)
    win; otherwise every distinctive word of a programme name must appear in the question. A level hint
    ('Masters', 'BSc') puts that level first."""
    q = _clean(question).lower()
    qwords = _words(q)
    exact, worded = [], []
    for r in records():
        full, short = r["programme"].lower().rstrip("."), _short(r["programme"])
        if full in q or (len(short) >= 5 and re.search(rf"(?<![a-z]){re.escape(short)}(?![a-z])", q)):
            exact.append(r)
        else:
            w = _words(short)
            if w and w <= qwords:
                worded.append(r)
    groups = _group(exact, "exact") or _group(worded, "words")
    # a name contained in a longer matched name is not a separate match ("Psychology" in "Community Psychology")
    shorts = {_short(g.programme) for g in groups}
    groups = [g for g in groups if not any(_short(g.programme) != s and _short(g.programme) in s for s in shorts)]
    hint = next((lvl for lvl, rx in LEVEL_HINTS.items() if rx.search(q)), None)
    if hint == "postgraduate" or (hint and any(hint in g.level.lower() for g in groups)):
        groups = [g for g in groups if hint in g.level.lower()]     # 'Masters in X' never returns the Bachelor's
    groups.sort(key=lambda g: (-len(_short(g.programme)), g.level, g.programme))
    return groups[:max_groups]


def find_programmes(question: str, max_groups: int = 4) -> List[Dict[str, Any]]:
    return [r for g in programme_groups(question, max_groups) for r in g.routes]


def search(text: str = "", faculty: Optional[str] = None, level: Optional[str] = None, campus: Optional[str] = None,
           mode: Optional[str] = None) -> List[ProgrammeGroup]:
    """Programme explorer: case-insensitive filters; every route is kept."""
    t = (text or "").strip().lower()
    out = []
    for r in records():
        if t and t not in r["programme"].lower() and t not in r["faculty"].lower():
            continue
        if faculty and r["faculty"] != faculty:
            continue
        if level and level.lower() not in r["level"].lower():
            continue
        if campus and campus not in r["campuses"]:
            continue
        if mode and mode not in r["study_modes"]:
            continue
        out.append(r)
    return sorted(_group(out), key=lambda g: (g.faculty, g.programme, g.level))


def facets() -> Dict[str, List[str]]:
    recs = records()
    levels = sorted({("Postgraduate" if "Postgraduate" in r["level"] else "Undergraduate" if "Bachelor" in r["level"]
                      else "Diploma") for r in recs})
    return {"faculty": sorted({r["faculty"] for r in recs}), "level": levels,
            "campus": sorted({c for r in recs for c in r["campuses"]}),
            "mode": sorted({m for r in recs for m in r["study_modes"]})}


def card_markdown(group: ProgrammeGroup) -> str:
    """Deterministic programme details from the advert (all routes), with page references."""
    lines = [f"**{group.programme}** — {group.level}; {group.faculty}"]
    for i, r in enumerate(group.routes, 1):
        head = f"Route {i}" if len(group.routes) > 1 else "Details"
        lines.append(f"- *{head}* (advert p. {r['source_page']}): duration **{r['duration']}**; "
                     f"modes: {', '.join(r['modes']) or 'not stated'}"
                     + (f"; commencement: {r['commencement']}" if r["commencement"] else "; commencement: not stated"))
        lines += [f"    - {x}" for x in r["entry_requirements"]]
        if r["programme_note"]:
            lines.append(f"    - note: {r['programme_note']}")
    if group.routes and group.routes[0]["faculty_note"]:
        lines.append(f"- faculty note: {group.routes[0]['faculty_note']}")
    return "\n".join(lines)
