"""S6-2 report: each reranker x pool size against the provisional T1 configuration, plus the pre-agreed pool rule."""
import json, statistics

questions = json.load(open("eval/stage5_questions.json", encoding="utf-8"))["questions"]
scored = [q for q in questions if q["category"] != "out_of_scope"]
s61 = json.load(open("eval/stage6/s6_1_runs.json"))["runs"]
s62 = json.load(open("eval/stage6/s6_2_runs.json"))
grades = {(g["question_id"], g["chunk_id"]): g["grade"] for g in json.load(open("eval/stage5_grades.json"))["grades"]}
grades.update({(g["question_id"], g["chunk_id"]): g["grade"] for g in json.load(open("eval/stage6/grades.json"))["grades"]})
CATEGORIES = ["natural_language", "exact_code", "code_in_context"]
BUDGET_MEDIAN_MS, BUDGET_P95_MS = 1500, 3000


def first_sufficient(qid, ranked):
    for r in ranked:
        if grades[(qid, r["chunk_id"])] == 2:  # KeyError = an ungraded chunk above the first sufficient one
            return r["rank"]
    return None


def metrics(ranks):
    s = {}
    for cat in CATEGORIES + ["overall"]:
        qs = [q["id"] for q in scored if cat in ("overall", q["category"])]
        s[cat] = {f"top{k}": sum(1 for q in qs if ranks[q] and ranks[q] <= k) for k in (1, 3, 5)}
        s[cat]["mrr10"] = round(sum(1 / ranks[q] for q in qs if ranks[q]) / len(qs), 3)
    return s


t1_ranks = {q["id"]: first_sufficient(q["id"], s61[q["id"]]["T1"]) for q in scored}
report = {"T1": {"summary": metrics(t1_ranks), "ranks": t1_ranks}, "retrieval_only_ms": s62["retrieval_only_ms"],
          "configs": {}, "pool_choice": {}}
for key, model in s62["models"].items():
    for pool, data in model["pools"].items():
        ranks = {q["id"]: first_sufficient(q["id"], data["runs"][q["id"]]) for q in scored}
        changes = {c: [] for c in ("improved", "worse")}
        for q in scored:
            old, new = t1_ranks[q["id"]], ranks[q["id"]]
            if new != old:
                better = old is None or (new is not None and new < old)
                changes["improved" if better else "worse"].append(f"{q['id']} {old or '-'}->{new or '-'}")
        report["configs"][f"{key}@{pool}"] = {
            "model": model["name"], "pool": int(pool), "summary": metrics(ranks), "ranks": ranks, "changes": changes,
            "added_ms": data["added_ms"], "total_ms": data["total_ms"], "load_s": model["load_s"],
            "memory_mb": model["memory_mb"]}

    # pre-agreed rule: smallest N within one question of the model's best Top-1 and best Top-5, within the budget
    configs = [report["configs"][f"{key}@{p}"] for p in model["pools"]]
    best1 = max(c["summary"]["overall"]["top1"] for c in configs)
    best5 = max(c["summary"]["overall"]["top5"] for c in configs)
    eligible = [c for c in configs if c["summary"]["overall"]["top1"] >= best1 - 1 and
                c["summary"]["overall"]["top5"] >= best5 - 1 and
                c["added_ms"]["median"] <= BUDGET_MEDIAN_MS and c["added_ms"]["p95"] <= BUDGET_P95_MS]
    report["pool_choice"][key] = {"best_top1": best1, "best_top5": best5,
                                  "chosen_pool": min(c["pool"] for c in eligible) if eligible else None}

# side measurement for Stage 7: top reranker score, out-of-scope vs in-scope (pool 30)
side = {}
for key, model in s62["models"].items():
    runs = model["pools"]["30"]["runs"]
    top = {q["id"]: max(r["rerank_score"] for r in runs[q["id"]] if r["rerank_score"] is not None) for q in questions}
    oos = [top[q["id"]] for q in questions if q["category"] == "out_of_scope"]
    ins = [top[q["id"]] for q in scored]
    side[key] = {"out_of_scope": [round(x, 2) for x in sorted(oos)],
                 "in_scope_min": round(min(ins), 2), "in_scope_median": round(statistics.median(ins), 2),
                 "in_scope_below_max_out_of_scope": sum(1 for x in ins if x <= max(oos))}
report["out_of_scope_scores"] = side
json.dump(report, open("eval/stage6/s6_2_results.json", "w"), indent=1)

line = lambda s: "  ".join(f"{c[:5]} {s[c]['top1']}/{s[c]['top3']}/{s[c]['top5']}" for c in CATEGORIES) + \
    f"  ALL {s['overall']['top1']}/{s['overall']['top3']}/{s['overall']['top5']} MRR {s['overall']['mrr10']}"
print("T1        ", line(report["T1"]["summary"]))
for name, c in report["configs"].items():
    print(f"{name:10}", line(c["summary"]), f"| added {c['added_ms']['median']}/{c['added_ms']['p95']} ms",
          f"| load {c['load_s']} s, {c['memory_mb']} MB")
    print("            improved:", ", ".join(c["changes"]["improved"]) or "-", "| worse:", ", ".join(c["changes"]["worse"]) or "-")
print("pool choice:", report["pool_choice"])
print("out-of-scope:", json.dumps(side))
