"""S6-3 report: A and B (heading-aware index) against the accepted MiniLM@10 configuration, with both criteria."""
import json

questions = json.load(open("eval/stage5_questions.json", encoding="utf-8"))["questions"]
scored = [q for q in questions if q["category"] != "out_of_scope"]
data = json.load(open("eval/stage6/s6_3_runs.json"))
runs = data["runs"]
grades = {(g["question_id"], g["chunk_id"]): g["grade"] for g in json.load(open("eval/stage5_grades.json"))["grades"]}
grades.update({(g["question_id"], g["chunk_id"]): g["grade"] for g in json.load(open("eval/stage6/grades.json"))["grades"]})
CATEGORIES = ["natural_language", "exact_code", "code_in_context"]


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


ranks = {name: {q["id"]: first_sufficient(q["id"], runs[name][q["id"]]) for q in scored} for name in runs}
summary = {name: metrics(r) for name, r in ranks.items()}
base = ranks["accepted"]
report = {"summary": summary, "ranks": ranks, "added_ms": data["added_ms"], "n4_diagnosis": data["n4_diagnosis"],
          "variants": {}}
for name in ("A", "B"):
    new = ranks[name]
    changes = {"improved": [], "worse": [], "unchanged": []}
    for q in scored:
        o, n = base[q["id"]], new[q["id"]]
        key = "unchanged" if o == n else "improved" if o is None or (n is not None and n < o) else "worse"
        changes[key].append(q["id"] if key == "unchanged" else f"{q['id']} {o or '-'}->{n or '-'}")
    s, b = summary[name], summary["accepted"]
    no_category_top5_drop = all(s[c]["top5"] >= b[c]["top5"] for c in CATEGORIES)
    criterion_a = no_category_top5_drop and (s["overall"]["top1"] - b["overall"]["top1"] >= 2 or
                                             s["overall"]["top3"] - b["overall"]["top3"] >= 2)
    # "no meaningful regressions", as stated before the run: no question leaves the top 5, no category loses more
    # than 1 at Top-3, overall Top-1 does not fall by 2 or more
    lost_top5 = [q["id"] for q in scored if base[q["id"]] and base[q["id"]] <= 5 and not (new[q["id"]] and new[q["id"]] <= 5)]
    meaningful_regression = bool(lost_top5) or any(b[c]["top3"] - s[c]["top3"] > 1 for c in CATEGORIES) or \
        b["overall"]["top1"] - s["overall"]["top1"] >= 2
    criterion_b = bool(new["N4"] and new["N4"] <= 5) and s["overall"]["top5"] > b["overall"]["top5"] and \
        not meaningful_regression
    report["variants"][name] = {"changes": changes, "N4_rank": new["N4"], "lost_top5": lost_top5,
                                "meaningful_regression": meaningful_regression,
                                "criterion_A": criterion_a, "criterion_B": criterion_b}
json.dump(report, open("eval/stage6/s6_3_results.json", "w"), indent=1)

line = lambda s: "  ".join(f"{c[:5]} {s[c]['top1']}/{s[c]['top3']}/{s[c]['top5']}" for c in CATEGORIES) + \
    f"  ALL {s['overall']['top1']}/{s['overall']['top3']}/{s['overall']['top5']} MRR {s['overall']['mrr10']}"
for name in ("accepted", "A", "B", "T1_v1", "T1_v2"):
    print(f"{name:9}", line(summary[name]), "| N4:", ranks[name]["N4"] or "-")
for name in ("A", "B"):
    v = report["variants"][name]
    print(name, "improved:", ", ".join(v["changes"]["improved"]) or "-", "| worse:", ", ".join(v["changes"]["worse"]) or "-",
          "| lost top5:", v["lost_top5"] or "-", "| criterion A:", v["criterion_A"], "| criterion B:", v["criterion_B"])
print("latency:", data["added_ms"], "| N4 diagnosis:", data["n4_diagnosis"])
