"""
Run an admissions evaluation set through the real application flow (router, retrieval, model, safeguards) and grade
the answers automatically against the record-derived keys.

    python evaluation/admissions_eval/run_eval.py --set dev [--runs 2] [--limit N]
    MSU_SEALED_EVAL_AUTHORISED=1 python evaluation/admissions_eval/run_eval.py --set sealed --runs 2   (owner only)

Each question gets a fresh chat (no carry-over). Grading per answer:
- sufficient    every required key fact present, no forbidden statement, and (for answers from documents) at least one
                evidence citation; abstention items: the answer says the information is not stated / not available
- partial       at least half of the required facts, nothing forbidden
- insufficient  otherwise
- critical      a forbidden statement (e.g. a start month the advert does not state)
Tracked separately: unverified-fact notes (facts the safeguards could not find in the evidence), correct abstentions,
citations, latency, and run-to-run consistency (same label and same facts across runs).

Live Groq calls: about one or two per question per run (router when not decided deterministically, answer).
Results: evaluation/results/admissions_eval/<set>_<timestamp>/results.jsonl and summary.json.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SETS = {"dev": Path(__file__).with_name("dev_set.json"), "sealed": Path(__file__).parent / "sealed" / "sealed_set.json"}
GRADER_VERSION = "v4"   # v2: name+page citations count, Unicode hyphens/spaces normalised, standard abstention phrasing
                        # v3: strict - an unverified-fact note (a fact or descriptor not found in the evidence) is a
                        #     minor unsupported claim, so the answer cannot be 'sufficient' (frozen rubric rule)
                        # v4: a campus/mode combination the advert does not show is CRITICAL (wrong campus or mode)
CITE = re.compile(r"Evidence\s*\d|【\s*(?:Evidence\s*)?\d"
                  r"|(?:Advert|Yearbook|Road Map)[^\n|]{0,40}?(?:p\.|page)\s*\d", re.I)
ABSTAIN = re.compile(r"do(?:es)? not (?:state|specify|give|say|indicate|contain|include|provide|mention)|"
                     r"not (?:stated|specified|given|provided|indicated|mentioned|available)|could not find|"
                     r"no (?:commencement|start) date|no information|don't have verified information", re.I)


def normalise(text: str) -> str:
    return (text or "").translate({0x2011: "-", 0x2010: "-", 0x2012: "-", 0x2013: "-", 0x2014: "-", 0x00A0: " ",
                                   0x202F: " ", 0x2009: " "})


def answer_of(turn):
    if turn.path == "INFO":
        r = turn.result
        return (r.answer or r.error_message or ""), [n["kind"] for n in r.safety_notes], r.status, bool(r.not_found)
    return turn.flow.answer or "", [], turn.flow.status, False


def grade(item, answer, path, notes):
    answer = normalise(answer)
    found = [bool(re.search(rx, answer, re.I)) for rx in item["required"]]
    if item["abstain"] and not all(found) and ABSTAIN.search(answer):
        found = [True] * len(found)                  # an explicit abstention in other words
    forbidden = [rx for rx in item["forbidden"] if re.search(rx, answer, re.I)]
    cites = path != "INFO" or bool(CITE.search(answer))
    unverified = "verification" in notes
    wrong_route = "mode_combination" in notes
    if forbidden or wrong_route:
        label = "insufficient"
    elif all(found) and (item["abstain"] or cites) and not unverified:
        label = "sufficient"
    elif found and sum(found) >= len(found) / 2:
        label = "partial"
    else:
        label = "insufficient"
    return {"label": label, "found": found, "forbidden_hit": forbidden, "critical": bool(forbidden or wrong_route),
            "cites": cites, "unverified_note": unverified, "wrong_route": wrong_route}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=sorted(SETS), default="dev")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--regrade", default=None, help="re-grade a saved run folder with the current grader (no API calls)")
    a = ap.parse_args()
    if a.regrade:
        return regrade(Path(a.regrade), a)
    if a.set == "sealed" and os.environ.get("MSU_SEALED_EVAL_AUTHORISED") != "1":
        sys.exit("STOPPED: the sealed set is reserved for the owner's independent evaluation "
                 "(set MSU_SEALED_EVAL_AUTHORISED=1 only when authorised).")
    data = json.loads(SETS[a.set].read_text(encoding="utf-8"))
    items = data["items"][:a.limit]
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from src.admissions_flow import handle_message
    from src.assistant import Assistant
    from src.conversation import ChatSession
    assistant = Assistant.create(profile="c3_intake_0006")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "evaluation/results/admissions_eval" / f"{a.set}_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with open(out / "results.jsonl", "w", encoding="utf-8") as f:
        for run in range(1, a.runs + 1):
            for item in items:
                t = time.perf_counter()
                turn = handle_message(ChatSession(), assistant, item["question"], log_path=None)
                ms = round((time.perf_counter() - t) * 1000)
                answer, notes, status, not_found = answer_of(turn)
                g = grade(item, answer, turn.path, notes)
                row = {"run": run, "id": item["id"], "type": item["type"], "question": item["question"],
                       "path": turn.path, "status": status, "not_found": not_found, "latency_ms": ms, **g,
                       "notes": notes, "answer": answer, "key": item["key"], "source_pages": item["source_pages"]}
                rows.append(row)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print(run, item["id"], g["label"], "CRITICAL" if g["critical"] else "", item["type"], ms, "ms", flush=True)
    summary = summarise(rows, items, a)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


def regrade(folder: Path, a) -> int:
    rows = [json.loads(l) for l in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    set_name = rows[0]["id"][0] == "S" and "sealed" or "dev"
    items = {i["id"]: i for i in json.loads(SETS[set_name].read_text(encoding="utf-8"))["items"]}
    for r in rows:
        r.update(grade(items[r["id"]], r["answer"], r["path"], r["notes"]))
    (folder / f"results_regraded_{GRADER_VERSION}.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    a.set = set_name
    summary = {**summarise(rows, list(items.values()), a), "grader": GRADER_VERSION, "regraded_from": folder.name}
    (folder / f"summary_regraded_{GRADER_VERSION}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


def summarise(rows, items, a):
    per_run = defaultdict(list)
    for r in rows:
        per_run[r["run"]].append(r)
    runs = {}
    for run, rs in per_run.items():
        labels = Counter(r["label"] for r in rs)
        abst = [r for r in rs if next(i for i in items if i["id"] == r["id"])["abstain"]]
        runs[run] = {"questions": len(rs), "sufficient": labels["sufficient"], "partial": labels["partial"],
                     "insufficient": labels["insufficient"],
                     "sufficient_pct": round(100 * labels["sufficient"] / len(rs), 1),
                     "critical": sum(r["critical"] for r in rs),
                     "unverified_fact_notes": sum(r["unverified_note"] for r in rs),
                     "abstention_items": len(abst), "correct_abstentions": sum(r["label"] == "sufficient" for r in abst),
                     "answers_citing_evidence": sum(r["cites"] for r in rs if r["path"] == "INFO"),
                     "by_type": {t: f"{sum(r['label'] == 'sufficient' for r in rs if r['type'] == t)}/"
                                    f"{sum(r['type'] == t for r in rs)}" for t in sorted({r['type'] for r in rs})},
                     "median_latency_ms": sorted(r["latency_ms"] for r in rs)[len(rs) // 2]}
    consistency = None
    if len(per_run) > 1:
        by_id = defaultdict(list)
        for r in rows:
            by_id[r["id"]].append((r["label"], tuple(r["found"])))
        consistency = {"same_label_pct": round(100 * sum(len({x[0] for x in v}) == 1 for v in by_id.values()) / len(by_id), 1),
                       "same_facts_pct": round(100 * sum(len({x[1] for x in v}) == 1 for v in by_id.values()) / len(by_id), 1)}
    return {"set": a.set, "runs": runs, "consistency": consistency}


if __name__ == "__main__":
    sys.exit(main())
