"""
Build the admissions evaluation sets from the approved structured records (deterministic; no model involved).

    python evaluation/admissions_eval/build_sets.py

dev_set.json      for development: run it, inspect failures, improve the system.
sealed/           SEALED set for the owner's independent final evaluation: built and hash-frozen here, NOT run during
                  development (run_eval.py refuses to run it without MSU_SEALED_EVAL_AUTHORISED=1).

Sources: the January/February 2027 intake advert records and the 2027 road map records registered in knowledge-base
version 0006 (SHA-256 checked by src/programme_lookup.py). Programmes and road-map events used by the earlier held-out
set (remediation/heldout) are excluded, and the dev and sealed sets share no programme or event.

Question types (keys are derived from the records, so each key is traceable to an advert/road-map page):
  duration      every advertised duration of every route
  modes         every campus and study mode of every route
  start         the stated commencement month(s), or 'not stated' (abstention) when the advert gives none
  requirements  up to three distinctive requirement terms (named subjects, degree classes, qualifications)
  calendar      start and end dates of a road-map activity
  decline       out-of-scope questions the documents cannot answer (abstention)
"""
import hashlib
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).parent
SEED = "msu-admissions-eval-v1"
NOT_STATED = r"not (?:stated|specified|given|provided|indicated|mentioned)|does not (?:state|specify|give|say|indicate)|no (?:commencement|start) date"
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
# most distinctive first; general terms (English from the general O Level rule, Diploma, Honours ...) last
SUBJECT_TERMS = ["2.1", "2.2", "Mathematics", "Physics", "Chemistry", "Biology", "Geography", "History", "Accounting",
                 "Economics", "Computer Science", "Statistics", "Agriculture", "Shona", "Ndebele", "Literature",
                 "Divinity", "Sociology", "Psychology", "Combined Science", "Commercial", "Arts", "Humanities",
                 "Certificate in Education", "HND", "employ", "Sciences", "Diploma", "Honours", "Bachelor", "English",
                 "Science"]
DECLINES_DEV = ["What is the student Wi-Fi password at the Gweru campus?", "Who won the MSU football league in 2026?",
                "What is the weather forecast for Zvishavane next week?", "Can you recommend a good restaurant in Harare?"]
DECLINES_SEALED = ["What is the email address of the Vice Chancellor's personal assistant?",
                   "How many students failed the 2025 examinations?", "Which hostel room is the quietest at MSU?",
                   "What will the exchange rate be in January 2027?", "Who is the best lecturer in the Faculty of Law?",
                   "Can you write my application essay for me?"]


def held_out_ids():
    keys = json.loads((ROOT / "remediation/heldout/heldout_keys.json").read_text(encoding="utf-8"))["keys"]
    return {s["record"] for k in keys.values() for s in k.get("sources", []) if "record" in s}


def roadmap_events():
    snap = json.loads((ROOT / "knowledge_base/store/versions/0006/registry_snapshot.json").read_text(encoding="utf-8"))
    d = next(x for x in snap["documents"] if x["doc_id"] == "roadmap-2027")
    return json.loads((ROOT / "knowledge_base" / d["dataset"]["path"]).read_text(encoding="utf-8"))["events"]


def duration_regex(v: float) -> str:
    if v == 1.5:
        return r"1\s*½|1\.5|one and a half|18\s*months|eighteen"
    if v < 1:
        return rf"\b{int(round(v * 12))}\s*months?"
    n = int(v)
    return rf"(?<![\d.]){n}\s*-?\s*(?:years?|yrs)|\b{WORDS.get(n, n)}\s*-?\s*years?"


def date_regex(iso: str) -> str:
    y, m, d = iso.split("-")
    month = MONTHS.split("|")[int(m) - 1]
    return rf"\b{int(d)}(?:st|nd|rd|th)?\s+{month}|{int(d)}/{int(m)}/{y}|0?{int(d)}/0?{int(m)}/{y}"


def name_variant(name: str, i: int) -> str:
    """Mostly the advert's full name; every third question a shorter form ('X degree') to test programme matching."""
    if i % 3 == 2 and " in " in name and name.startswith("Bachelor"):
        return name.rsplit(" in ", 1)[-1].rstrip(".").replace(" Degree", "") + " degree"
    return name.rstrip(".")


def programme_items(group, kinds, i):
    from src.conflicts import durations
    name, routes = group.programme, group.routes
    pages = sorted({r["source_page"] for r in routes})
    base = {"programme": name, "level": group.level, "records": [r["id"] for r in routes], "source_pages": pages}
    items = []
    nm = name_variant(name, i)
    for kind in kinds:
        if kind == "duration":
            ds = sorted(set().union(*(durations(r["duration"]) for r in routes)))
            if not ds:
                items.append({**base, "type": "duration_not_stated", "question": f"How long is the {nm}?",
                              "required": [NOT_STATED], "forbidden": [], "abstain": True,
                              "key": "duration not stated in the advert"})
                continue
            items.append({**base, "type": "duration", "question": f"How long is the {nm}?",
                          "required": [duration_regex(v) for v in ds], "forbidden": [], "abstain": False,
                          "key": "; ".join(f"{r['duration']} ({', '.join(r['modes'])})" for r in routes)})
        elif kind == "modes":
            campuses = sorted({c for r in routes for c in r["campuses"]})
            modes = sorted({m for r in routes for m in r["study_modes"]})
            if not campuses:
                continue
            items.append({**base, "type": "modes", "question": f"Where and how is the {nm} offered?",
                          "required": [re.escape(c) for c in campuses] +
                                      [re.escape(m.split()[0]) for m in modes],
                          "forbidden": [], "abstain": False, "key": "; ".join(", ".join(r["modes"]) for r in routes)})
        elif kind == "start":
            starts = sorted({r["commencement"] for r in routes if r["commencement"]})
            if starts and all(r["commencement"] for r in routes):
                months = sorted({re.search(MONTHS, s).group(0) for s in starts if re.search(MONTHS, s)})
                items.append({**base, "type": "start", "question": f"When does the {nm} start?",
                              "required": [rf"{m}\s+2027" for m in months], "forbidden": [], "abstain": False,
                              "key": "; ".join(starts)})
            elif not starts:
                items.append({**base, "type": "start_not_stated", "question": f"When does the {nm} start?",
                              "required": [NOT_STATED],
                              "forbidden": [rf"(?:commences?|starts?|begins?)\s+(?:in|on)?\s*(?:{MONTHS})\s+2027"],
                              "abstain": True, "key": "commencement not stated in the advert"})
        elif kind == "requirements":
            text = " ".join(x for r in routes for x in r["entry_requirements"])
            terms = [t for t in SUBJECT_TERMS if re.search(rf"(?<![A-Za-z]){re.escape(t)}", text, re.I)][:3]
            if not terms:
                terms = ["two"] if re.search(r"\btwo\b|\b2\b", text, re.I) else []
            if not terms:
                continue
            items.append({**base, "type": "requirements", "question": f"What are the entry requirements for the {nm}?",
                          "required": [re.escape(t) for t in terms], "forbidden": [], "abstain": False,
                          "key": " || ".join(text.split("  "))[:600]})
    return items


def calendar_item(e):
    q = f"When is {e['activity'].replace('–', '-')} in the {e['semester']} of the {e['calendar_group']} in 2027?"
    req = [date_regex(e["start_date"])] + ([date_regex(e["end_date"])] if e["end_date"] != e["start_date"] else [])
    return {"type": "calendar", "question": q, "required": req, "forbidden": [], "abstain": False,
            "records": [e["id"]], "source_pages": [1], "key": e["summary"]}


def build():
    from src.programme_lookup import _group, records
    excluded = held_out_ids()
    groups = [g for g in _group(records()) if not any(r["id"] in excluded for r in g.routes)]
    groups.sort(key=lambda g: (g.programme, g.level))
    random.Random(SEED).shuffle(groups)
    multi = [g for g in groups if len(g.routes) > 1]
    single = [g for g in groups if len(g.routes) == 1]
    dev_groups = multi[:8] + single[:10]
    sealed_groups = multi[8:20] + single[10:28]
    kinds = ["duration", "modes", "start", "requirements"]
    events = [e for e in roadmap_events() if e["id"] not in excluded]
    random.Random(SEED + "-calendar").shuffle(events)

    def make(groups_, events_, declines, prefix):
        items = []
        for i, g in enumerate(groups_):
            items += programme_items(g, [kinds[i % 4], kinds[(i + 1) % 4]], i)
        items += [calendar_item(e) for e in events_]
        items += [{"type": "decline", "question": q, "required": [r"not (?:contain|include|have|provide)|could not find|"
                                                                     r"no information|cannot (?:help|answer)|don't have|"
                                                                     r"do not have|not (?:in|among|covered)|outside"],
                   "forbidden": [], "abstain": True, "records": [], "source_pages": [], "key": "decline"}
                  for q in declines]
        return [{"id": f"{prefix}{n:03d}", **it} for n, it in enumerate(items, 1)]

    dev = make(dev_groups, events[:6], DECLINES_DEV, "D")
    sealed = make(sealed_groups, events[6:14], DECLINES_SEALED, "S")
    assert not {p for x in dev for p in x.get("records", [])} & {p for x in sealed for p in x.get("records", [])}
    return dev, sealed


def main():
    dev, sealed = build()
    meta = {"version": "admissions-eval-v1", "built_from": "knowledge base 0006 advert + road map records",
            "excludes": "records used by remediation/heldout", "seed": SEED}
    (OUT / "dev_set.json").write_text(json.dumps({**meta, "set": "dev", "items": dev}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    sealed_dir = OUT / "sealed"
    sealed_dir.mkdir(exist_ok=True)
    payload = json.dumps({**meta, "set": "sealed", "items": sealed}, ensure_ascii=False, indent=1)
    path = sealed_dir / "sealed_set.json"
    if path.exists() and path.read_text(encoding="utf-8") != payload:
        sys.exit("STOPPED: the sealed set already exists and would change; it is frozen")
    path.write_text(payload, encoding="utf-8")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    (sealed_dir / "SEALED.json").write_text(json.dumps({
        "sealed_set_sha256": sha, "items": len(sealed), "frozen_on": "2026-10-16",
        "status": "SEALED - not run during development. For the owner's independent final evaluation.",
        "run": "MSU_SEALED_EVAL_AUTHORISED=1 python evaluation/admissions_eval/run_eval.py --set sealed --runs 2"},
        indent=1), encoding="utf-8")
    from collections import Counter
    print("dev:", len(dev), dict(Counter(x["type"] for x in dev)))
    print("sealed:", len(sealed), dict(Counter(x["type"] for x in sealed)), "sha256", sha[:16])


if __name__ == "__main__":
    main()
