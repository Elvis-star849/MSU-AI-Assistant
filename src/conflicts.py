"""
Deterministic detection of contradictions between the 2027 intake advert and the yearbook regulations.

    evidence_conflicts(evidence) -> [note]     for one answer: advert and yearbook passages in the evidence that state
                                               different durations for the same programme
    duration_conflicts() -> [conflict]          whole knowledge base (staging version): every advert programme whose
                                               yearbook regulation states a different duration (admin report)

Durations are read from the regulation text itself ("REGULATIONS FOR ... DEGREE IN X ... Duration: 4 years"), not
from chunk headings, which are known to attach the next programme's opening text to the previous section. A conflict
is disclosed, never resolved here: the advert is the current source for the 2027 intake only where MSU's precedence
rules say so, and the applicant is asked to confirm with MSU.
"""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

ADVERT = "MSU January/February 2027 Intake Advert"
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "eighteen": 18, "twelve": 12}
_REG = re.compile(r"REGULATIONS FOR (?:THE )?(?P<title>[A-Z][A-Z ,&'’\-]+?)\s*(?:\([A-Za-z0-9 /]+\))?\s*\n+\s*"
                  r"Duration(?: of Degree)?\s*:?\s*\n*\s*(?P<dur>[^\n]*(?:\n+\s*[^\n]*(?:years?|months?)[^\n]*)?)", re.I)
_DUR = re.compile(r"(?P<n>\d+(?:[.,]\d+)?(?:\s*½)?|½|one|two|three|four|five|six|eighteen|twelve)\s*(?:\(\d+\)\s*)?-?\s*"
                  r"(?P<unit>years?|months?)", re.I)


def durations(text: str) -> Set[float]:
    """Durations in years: '4 years 3 years Visiting' -> {4, 3}; '1 ½ years' / '18 months' -> {1.5}."""
    out = set()
    text = re.sub(r"(\d+)\s*1\s*/\s*2\s*", r"\1.5 ", (text or "").replace("1½", "1 ½"))   # '1 1/2years' -> 1.5
    text = re.sub(r"(\d+)\s+1/2", r"\1.5", text)
    for m in _DUR.finditer(text):
        raw = m.group("n").lower().replace(",", ".").replace(" ", "")
        if raw in WORDS:
            n = float(WORDS[raw])
        elif "½" in raw:
            n = float(raw.replace("½", "") or 0) + 0.5
        else:
            n = float(raw)
        out.add(round(n / 12, 2) if m.group("unit").lower().startswith("month") else n)
    return out


def _short(name: str) -> str:
    name = re.sub(r"\s*\(.*?\)\s*", " ", name or "")
    name = re.split(r"\bDEGREE IN\b|\bHONOURS IN\b|\bDIPLOMA IN\b|\bDEGREE\b(?=\s+IN\b)|\bin\b", name, flags=re.I)[-1]
    return re.sub(r"[^a-z ]", " ", name.lower()).split("degree")[0].strip().replace("  ", " ")


def _level(name: str) -> str:
    """bachelor | master | pg_diploma | diploma | doctorate: a Postgraduate Diploma or a Certificate is never matched
    to a Master's or a Bachelor's of the same name."""
    n = re.sub(r"[^a-z ]", " ", (name or "").lower())
    if re.search(r"\bphd\b|\bmphil\b|\bdoctor", n):
        return "doctorate"
    if re.search(r"\bmaster", n):
        return "master"
    if re.search(r"\bpost\s*graduate diploma\b|\bpostgraduate diploma\b", n) or re.search(r"\bduate diploma\b", n):
        return "pg_diploma"
    if re.search(r"\bcertificate\b", n):
        return "certificate"
    if re.search(r"\bdiploma\b", n):
        return "diploma"
    return "bachelor"


def _fmt(years: Set[float]) -> str:
    return ", ".join(f"{y:g} years" for y in sorted(years))


# ------------------------------------------------------------------ one answer's evidence
def evidence_conflicts(evidence: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    adverts, yearbooks = [], []
    for e in evidence:
        text = e.get("text") or ""
        if e.get("source") == ADVERT:
            prog = re.search(r"PROGRAMME:\s*(.+)", text)
            dur = re.search(r"DURATION AS ADVERTISED:\s*(.+)", text)
            if prog and dur and durations(dur.group(1)):
                adverts.append((prog.group(1).strip(), durations(dur.group(1)), e.get("page")))
        elif "Yearbook" in (e.get("source") or ""):
            for m in _REG.finditer(text):
                if durations(m.group("dur")):
                    yearbooks.append((m.group("title").strip(), durations(m.group("dur")), e.get("page"), e.get("source")))
    notes, seen = [], set()
    for a_name, a_dur, a_page in adverts:
        for y_name, y_dur, y_page, y_src in yearbooks:
            if _short(a_name) != _short(y_name) or _level(a_name) != _level(y_name) or not a_dur.isdisjoint(y_dur):
                continue
            key = (_short(a_name), tuple(sorted(a_dur)), tuple(sorted(y_dur)))
            if key in seen:
                continue
            seen.add(key)
            notes.append({"kind": "conflict", "text": (
                f"The sources differ on the duration of {a_name}: the 2027 intake advert gives {_fmt(a_dur)} "
                f"(p. {a_page}); the {y_src} gives {_fmt(y_dur)} (p. {y_page}). The yearbook may be older than the "
                f"advert; confirm the duration with MSU Admissions.")})
    return notes


# ------------------------------------------------------------------ the whole knowledge base (admin report)
@lru_cache(maxsize=1)
def yearbook_durations(version: str = "0006") -> List[Dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "knowledge_base/store/versions" / version / "chunks.jsonl"
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if "Yearbook" not in r.get("source", "") or "REGULATIONS FOR" not in r.get("text", "").upper():
                continue
            for m in _REG.finditer(r["text"]):
                d = durations(m.group("dur"))
                if d:
                    out.append({"title": m.group("title").strip(), "short": _short(m.group("title")),
                                "level": _level(m.group("title")), "durations": d, "page": r.get("page"),
                                "source": r["source"], "text": m.group("dur").strip()[:80]})
    return out


def duration_conflicts(version: str = "0006") -> List[Dict[str, Any]]:
    from src.programme_lookup import programme_groups, records
    by_short: Dict[tuple, List[Dict[str, Any]]] = {}
    for y in yearbook_durations(version):
        by_short.setdefault((y["short"], y["level"]), []).append(y)
    out, done = [], set()
    for r in records():
        key = (_short(r["programme"]), _level(r["programme"]))
        if key in done or key not in by_short:
            continue
        done.add(key)
        routes = [x for x in records() if (_short(x["programme"]), _level(x["programme"])) == key]
        advert = set().union(*(durations(x["duration"]) for x in routes))
        if not advert:
            continue
        for y in by_short[key]:
            if advert.isdisjoint(y["durations"]) or not y["durations"] <= advert:
                out.append({"programme": r["programme"], "advert_durations": sorted(advert),
                            "advert_pages": sorted({x["source_page"] for x in routes}),
                            "yearbook": y["source"], "yearbook_page": y["page"], "yearbook_durations": sorted(y["durations"]),
                            "yearbook_text": y["text"],
                            "kind": "different" if advert.isdisjoint(y["durations"]) else "yearbook lists other durations"})
    return out
