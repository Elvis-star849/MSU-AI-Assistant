"""S6-6 metrics and the pre-agreed decision rules (written and frozen before the held-out set was opened).

Run only after blind grading and the owner's spot-check approval. Writes eval/stage6/s6_6_results.json.
"""
import json

holdout = json.load(open("eval/stage6/holdout_questions.json", encoding="utf-8"))
scored = [q for q in holdout["questions"] if q["category"] != "out_of_scope"]
data = json.load(open("eval/stage6/s6_6_runs.json"))
runs, latency = data["runs"], data["latency"]
grades = {(g["question_id"], g["chunk_id"]): g["grade"] for g in json.load(open("eval/stage6/s6_6_grades.json"))["grades"]}
CATEGORIES = ["natural_language", "exact_code", "code_in_context"]
ARMS = ["arm0", "arm1", "arm2", "arm3"]
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


def compare(old, new):
    out = {"improved": [], "worse": [], "unchanged": []}
    for q in scored:
        o, n = old[q["id"]], new[q["id"]]
        key = "unchanged" if o == n else "improved" if o is None or (n is not None and n < o) else "worse"
        out[key].append(q["id"] if key == "unchanged" else f"{q['id']} {o or '-'}->{n or '-'}")
    return out


ranks = {arm: {q["id"]: first_sufficient(q["id"], runs[arm][q["id"]]) for q in scored} for arm in ARMS}
summary = {arm: metrics(ranks[arm]) for arm in ARMS}
overall = {arm: summary[arm]["overall"] for arm in ARMS}
pairs = {"arm0_vs_arm1": compare(ranks["arm0"], ranks["arm1"]), "arm1_vs_arm2": compare(ranks["arm1"], ranks["arm2"]),
         "arm2_vs_arm3": compare(ranks["arm2"], ranks["arm3"]), "arm0_vs_arm3": compare(ranks["arm0"], ranks["arm3"])}

# Primary claim (Arm 3 vs Arm 0): all four conditions
p = pairs["arm0_vs_arm3"]
conditions = {
    "top5_not_lower": overall["arm3"]["top5"] >= overall["arm0"]["top5"],
    "top1_plus_3": overall["arm3"]["top1"] - overall["arm0"]["top1"] >= 3,
    "more_improved_than_worse": len(p["improved"]) > len(p["worse"]),
    "latency_within_budget": latency["arm3"]["rerank_added_median_ms"] <= BUDGET_MEDIAN_MS and
                             latency["arm3"]["rerank_added_p95_ms"] <= BUDGET_P95_MS,
}
primary = {"conditions": conditions, "passed": all(conditions.values()),
           "wording": "Passing means the system passed the predefined Stage 6 engineering/generalisation criteria; "
                      "it is not statistical proof of generalisation (30 in-scope questions)."}
# Reranker value (Arm 2 vs Arm 3): recommendation only
within_one = abs(overall["arm3"]["top1"] - overall["arm2"]["top1"]) <= 1 and \
    abs(overall["arm3"]["top5"] - overall["arm2"]["top5"]) <= 1
reranker = {"arm2_within_one_of_arm3_at_top1_and_top5": within_one,
            "rule": "if within one at both, discuss explicitly whether MiniLM justifies its complexity and latency "
                    "(recommend dropping it as simpler and cheaper); otherwise recommend keeping it"}
# Tie-break (Arm 1 vs Arm 0)
tie_break = {"confirmed": overall["arm1"]["top1"] >= overall["arm0"]["top1"] and
             overall["arm1"]["top5"] >= overall["arm0"]["top5"]}
# Fallback, if the reranker is kept
fallback = "arm2" if (overall["arm2"]["top1"] >= overall["arm1"]["top1"] and
                      overall["arm2"]["top5"] >= overall["arm1"]["top5"]) else "arm1"

report = {"summary": summary, "ranks": ranks, "pairs": pairs, "latency": latency, "primary_claim": primary,
          "reranker_value": reranker, "tie_break": tie_break, "fallback_if_reranker_kept": fallback}
json.dump(report, open("eval/stage6/s6_6_results.json", "w"), indent=1)

line = lambda s: "  ".join(f"{c[:5]} {s[c]['top1']}/{s[c]['top3']}/{s[c]['top5']}" for c in CATEGORIES) + \
    f"  ALL {s['overall']['top1']}/{s['overall']['top3']}/{s['overall']['top5']} MRR {s['overall']['mrr10']}"
for arm in ARMS:
    print(arm, line(summary[arm]))
for name, c in pairs.items():
    print(name, "improved:", ", ".join(c["improved"]) or "-", "| worse:", ", ".join(c["worse"]) or "-")
print("primary:", json.dumps(primary["conditions"]), "passed:", primary["passed"])
print("reranker within one:", within_one, "| tie-break confirmed:", tie_break["confirmed"], "| fallback:", fallback)
print("latency:", json.dumps(latency))
