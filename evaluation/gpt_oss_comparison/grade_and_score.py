"""
Blind grading and scoring of the GPT-OSS-20B vs GPT-OSS-120B comparison (frozen Stage 4 §5 rubric, unchanged).

    python evaluation/gpt_oss_comparison/grade_and_score.py prepare      # blind views + sealed label mapping
    python evaluation/gpt_oss_comparison/grade_and_score.py grade < grades.jsonl
    python evaluation/gpt_oss_comparison/grade_and_score.py commit       # hash-commit the grades
    python evaluation/gpt_oss_comparison/grade_and_score.py report       # unseal, score, write comparison files

Blinding: every answer gets a random label; the two answers to a question are shown in random order, with the
question, the frozen held-out key, the evidence the model was given and automatic citation hints (never grades). The
label -> model mapping is written to SEALED_mapping.json, whose SHA-256 is committed first; `report` refuses to run
until the grades are committed, and verifies both hashes.

Grade lines (one JSON object per answer): {"label", "c", "comp", "attr", "claims": [{"claim", "severity"}],
"refusal": appropriate|inappropriate|failed|n.a., "conflict": handled|partly|mishandled|n.a., "notes"}.
The overall label is derived by the frozen rule (remediation/grading/grade.py::overall).
"""
import argparse
import csv
import hashlib
import json
import random
import secrets
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RESULTS = ROOT / "evaluation/results/gpt_oss_comparison"
KEYS = ROOT / "remediation/heldout/heldout_keys.json"
RETRIEVAL = ROOT / "remediation/heldout/frozen/heldout_retrieval_report.json"
INPUTS = ROOT / "remediation/experiments/heldout/HO_S_C3_inputs.json"
MODELS = {"GROQ_MODEL": "GPT-OSS-20B", "GROQ_MODEL_2": "GPT-OSS-120B"}
REF = {"appropriate", "inappropriate", "failed", "n.a."}
CON = {"handled", "partly", "mishandled", "n.a."}
# held-out strata -> the evaluation areas asked for in the comparison
AREAS = {"S1_prerequisite_table": "table reading (prerequisites)", "S2_multiple_routes": "admission requirements",
         "S3_ambiguous_duration": "programme durations", "S4_start_date": "commencement dates",
         "S5_yearbook_vs_advert": "multi-document reasoning (advert vs yearbook)",
         "S6_roadmap_calendar": "academic calendar", "S7_ordinary_control": "ordinary questions",
         "S8_decline": "abstention (out of scope)"}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def overall(c, comp, attr, claims, ref, conf):          # frozen §5 rule, identical to remediation/grading/grade.py
    if c == 0 or any(u["severity"] == "critical" for u in claims) or ref == "failed" or conf == "mishandled":
        return "insufficient"
    if c == 2 and comp >= 1 and attr >= 1 and not claims and ref in ("appropriate", "n.a.") and conf in ("handled", "n.a."):
        return "sufficient"
    return "partially_sufficient"


def load_results(base):
    out = {}
    for env in MODELS:
        p = base / env / "results.jsonl"
        out[env] = {json.loads(l)["id"]: json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()} \
            if p.exists() else {}
    return out


def citation_hints(answer, n_evidence=5):
    from src.safeguards import cited_numbers
    cited = cited_numbers(answer or "")
    return {"cited": cited, "out_of_range": [n for n in cited if n < 1 or n > n_evidence], "cites_any": bool(cited)}


def prepare(base):
    blind = base / "blind"
    if (blind / "mapping_commitment.json").exists():
        sys.exit("STOPPED: blind views already prepared (delete nothing; grade them)")
    results = load_results(base)
    items = {i["id"]: i for i in json.loads(INPUTS.read_text(encoding="utf-8"))["items"]}
    missing = {env: sorted(set(items) - set(r)) for env, r in results.items() if set(items) - set(r)}
    if missing:
        sys.exit(f"STOPPED: both passes must be complete before blind grading; missing {missing}")
    keys = json.loads(KEYS.read_text(encoding="utf-8"))["keys"]
    blind.mkdir(parents=True, exist_ok=True)
    rng, mapping = random.Random(secrets.randbits(64)), {}
    for qid in sorted(items):
        answers = []
        for env in MODELS:
            label = f"{qid}-{secrets.token_hex(3)}"
            mapping[label] = env
            r = results[env][qid]
            text = r.get("answer") if r["status"] == "answered" else f"[NO ANSWER: API error {r['attempts'][-1]['error']['kind']}]"
            answers.append((label, text))
        rng.shuffle(answers)
        parts = [f"# {qid}  ({items[qid]['system']})\n", f"**Question:** {items[qid]['question']}\n",
                 "**Key:**\n```json\n" + json.dumps(keys[qid], ensure_ascii=False, indent=1) + "\n```\n",
                 "**Evidence given to both models (identical):**\n\n" + items[qid]["messages"][1]["content"] + "\n"]
        for label, text in answers:
            parts.append(f"---\n## Answer {label}\n\n*Automatic hints (not grades):* "
                         f"{json.dumps(citation_hints(text))}\n\n{text}\n")
        (blind / f"view_{qid}.md").write_text("\n".join(parts), encoding="utf-8")
    sealed = blind / "SEALED_mapping.json"
    sealed.write_text(json.dumps(mapping, indent=1, sort_keys=True), encoding="utf-8")
    (blind / "mapping_commitment.json").write_text(json.dumps({"SEALED_mapping.json": sha(sealed)}, indent=1),
                                                   encoding="utf-8")
    print(f"prepared {len(items)} views, {len(mapping)} blind labels; mapping sealed and committed")


def grade(base):
    blind = base / "blind"
    if (blind / "grades_commitment.json").exists():
        sys.exit("STOPPED: grades already committed")
    labels = set(json.loads((blind / "SEALED_mapping.json").read_text(encoding="utf-8")))   # label names only
    p = blind / "grades_work.json"
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    for line in sys.stdin.read().strip().splitlines():
        g = json.loads(line)
        lab = g["label"]
        assert lab in labels, lab
        assert g["refusal"] in REF and g["conflict"] in CON, lab
        for u in g["claims"]:
            assert u["severity"] in ("minor", "critical") and u["claim"].strip(), lab
        c, comp, attr = int(g["c"]), int(g["comp"]), int(g["attr"])
        assert all(v in (0, 1, 2) for v in (c, comp, attr)), lab
        d[lab] = {"correctness": c, "completeness": comp, "attribution": attr, "unsupported_claims": g["claims"],
                  "refusal": g["refusal"], "conflict": g["conflict"],
                  "overall": overall(c, comp, attr, g["claims"], g["refusal"], g["conflict"]), "notes": g.get("notes", "")}
        print(lab, d[lab]["overall"])
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print("graded", len(d), "of", len(labels))


def commit(base):
    blind = base / "blind"
    labels = set(json.loads((blind / "SEALED_mapping.json").read_text(encoding="utf-8")))
    grades = json.loads((blind / "grades_work.json").read_text(encoding="utf-8"))
    if set(grades) != labels:
        sys.exit(f"STOPPED: {len(labels - set(grades))} answers not graded")
    (blind / "grades_commitment.json").write_text(json.dumps({"grades_work.json": sha(blind / "grades_work.json")},
                                                             indent=1), encoding="utf-8")
    print("grades committed")


def pct(n, d):
    return round(100 * n / d, 1) if d else None


def p95(values):
    v = sorted(values)
    return v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))] if v else None


def report(base):
    blind = base / "blind"
    if not (blind / "grades_commitment.json").exists():
        sys.exit("STOPPED: commit the grades before unsealing the label mapping")
    commitment = json.loads((blind / "grades_commitment.json").read_text(encoding="utf-8"))
    if sha(blind / "grades_work.json") != commitment["grades_work.json"]:
        sys.exit("STOPPED: grades changed after commitment")
    if sha(blind / "SEALED_mapping.json") != json.loads((blind / "mapping_commitment.json").read_text())["SEALED_mapping.json"]:
        sys.exit("STOPPED: label mapping changed after commitment")
    mapping = json.loads((blind / "SEALED_mapping.json").read_text(encoding="utf-8"))
    grades = json.loads((blind / "grades_work.json").read_text(encoding="utf-8"))
    results, keys = load_results(base), json.loads(KEYS.read_text(encoding="utf-8"))["keys"]
    retrieval = {i["id"]: i for i in json.loads(RETRIEVAL.read_text(encoding="utf-8"))["items"]}
    by = {(env, lab.rsplit("-", 1)[0]): grades[lab] for lab, env in mapping.items()}
    rows, summary = [], {}
    for env, name in MODELS.items():
        rs = results[env]
        errors = []
        ep = base / env / "api_errors.jsonl"
        if ep.exists():
            errors = [json.loads(l) for l in ep.read_text(encoding="utf-8").splitlines() if l.strip()]
        answered = [r for r in rs.values() if r["status"] == "answered"]
        g = {qid: by[(env, qid)] for qid in rs}
        labels = [x["overall"] for x in g.values()]
        abst = [q for q in rs if keys[q]["behaviour"] in ("decline", "not_available")]
        answer_items = [q for q in rs if keys[q]["behaviour"] == "answer"]
        hints = {q: citation_hints(rs[q].get("answer")) for q in rs}
        lat = [r["generation_latency_ms"] for r in answered if r.get("generation_latency_ms") is not None]
        use = [r.get("usage", {}) for r in answered]
        reasoning = [r.get("reasoning_tokens") for r in answered if r.get("reasoning_tokens") is not None]
        by_stratum = {}
        for q, x in g.items():
            s = by_stratum.setdefault(rs[q]["stratum"], {"n": 0, "sufficient": 0, "partially_sufficient": 0,
                                                         "insufficient": 0})
            s["n"] += 1
            s[x["overall"]] += 1
        failures = {q: ("retrieval (target passage not in top 5)" if not retrieval[q]["target_in_top5"]
                        else "generation") for q, x in g.items() if x["overall"] != "sufficient"}
        summary[name] = {
            "model_env": env, "model": (answered[0]["returned_model"] if answered else None),
            "attempted": len(rs), "completed": len(answered),
            "correct_sufficient": labels.count("sufficient"), "partially_correct": labels.count("partially_sufficient"),
            "incorrect_insufficient": labels.count("insufficient"),
            "accuracy_pct": pct(labels.count("sufficient"), len(rs)),
            "answers_with_unsupported_claims": sum(1 for x in g.values() if x["unsupported_claims"]),
            "unsupported_claims_total": sum(len(x["unsupported_claims"]) for x in g.values()),
            "critical_unsupported_claims": sum(1 for x in g.values() for u in x["unsupported_claims"]
                                               if u["severity"] == "critical"),
            "citation_attribution_correct_pct": pct(sum(1 for q in answer_items if g[q]["attribution"] == 2), len(answer_items)),
            "citation_attribution_at_least_partly_pct": pct(sum(1 for q in answer_items if g[q]["attribution"] >= 1),
                                                            len(answer_items)),
            "citations_in_range_pct": pct(sum(1 for q in rs if not hints[q]["out_of_range"]), len(rs)),
            "answer_items_citing_evidence_pct": pct(sum(1 for q in answer_items if hints[q]["cites_any"]), len(answer_items)),
            "correct_abstentions": sum(1 for q in abst if g[q]["refusal"] == "appropriate" and g[q]["correctness"] == 2),
            "abstention_items": len(abst),
            "failed_refusals": sum(1 for x in g.values() if x["refusal"] == "failed"),
            "inappropriate_refusals": sum(1 for x in g.values() if x["refusal"] == "inappropriate"),
            "conflicts_mishandled": sum(1 for x in g.values() if x["conflict"] == "mishandled"),
            "generation_latency_ms": {"mean": round(statistics.mean(lat), 1) if lat else None,
                                      "median": round(statistics.median(lat), 1) if lat else None, "p95": p95(lat)},
            "groq_reported_total_time_s_mean": round(statistics.mean([u["total_time"] for u in use if "total_time" in u]), 3)
            if any("total_time" in u for u in use) else None,
            "prompt_tokens_mean": round(statistics.mean([u.get("prompt_tokens", 0) for u in use]), 1) if use else None,
            "completion_tokens_mean": round(statistics.mean([u.get("completion_tokens", 0) for u in use]), 1) if use else None,
            "reasoning_tokens_mean": round(statistics.mean(reasoning), 1) if reasoning else None,
            "total_tokens": sum(u.get("total_tokens", 0) for u in use),
            "usd": round(sum(r.get("usd", 0) for r in answered), 4),
            "api_errors": {k: sum(1 for e in errors if e["error"]["kind"] == k)
                           for k in sorted({e["error"]["kind"] for e in errors})},
            "by_stratum": by_stratum, "non_sufficient_failure_source": failures,
        }
        for q in sorted(rs):
            r, x = rs[q], g[q]
            rows.append({"model": name, "id": q, "stratum": r["stratum"], "area": AREAS[r["stratum"]],
                         "system": r["system"], "key_behaviour": keys[q]["behaviour"], "status": r["status"],
                         "overall": x["overall"], "correctness": x["correctness"], "completeness": x["completeness"],
                         "attribution": x["attribution"], "unsupported_claims": len(x["unsupported_claims"]),
                         "critical_claims": sum(u["severity"] == "critical" for u in x["unsupported_claims"]),
                         "refusal": x["refusal"], "conflict": x["conflict"],
                         "target_in_top5": retrieval[q]["target_in_top5"],
                         "generation_latency_ms": r.get("generation_latency_ms"),
                         "prompt_tokens": r.get("usage", {}).get("prompt_tokens"),
                         "completion_tokens": r.get("usage", {}).get("completion_tokens"),
                         "reasoning_tokens": r.get("reasoning_tokens"), "notes": x["notes"]})
    order = {"sufficient": 2, "partially_sufficient": 1, "insufficient": 0}
    diffs = []
    for q in sorted(keys):
        a, b = by[("GROQ_MODEL", q)], by[("GROQ_MODEL_2", q)]
        gap = abs(order[a["overall"]] - order[b["overall"]]) * 10 + abs(a["correctness"] - b["correctness"]) * 3 + \
            abs(len(a["unsupported_claims"]) - len(b["unsupported_claims"])) + abs(a["completeness"] - b["completeness"])
        diffs.append({"id": q, "difference_score": gap, "GPT-OSS-20B": a, "GPT-OSS-120B": b})
    diffs.sort(key=lambda d: -d["difference_score"])
    retrieval_mrr = statistics.mean(
        next((1 / (i + 1) for i, c in enumerate(retrieval[q]["top5"]) if c in retrieval[q]["targets"]), 0)
        for q in keys if retrieval[q]["targets"])
    out = {"summary": summary, "retrieval_metric_identical_for_both_models": {
        "MRR@5_on_frozen_evidence": round(retrieval_mrr, 3),
        "note": "retrieval metric, not an LLM-quality metric: both models received byte-identical evidence"},
        "largest_differences": diffs[:10]}
    (base / "comparison_summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(base / "per_question_grades.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(json.dumps({k: {m: v for m, v in s.items() if m not in ("by_stratum", "non_sufficient_failure_source")}
                      for k, s in summary.items()}, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("prepare", "grade", "commit", "report"))
    ap.add_argument("--base", default=str(RESULTS), help="results folder (tests use a scratch folder)")
    a = ap.parse_args()
    {"prepare": prepare, "grade": grade, "commit": commit, "report": report}[a.step](Path(a.base))


if __name__ == "__main__":
    main()
