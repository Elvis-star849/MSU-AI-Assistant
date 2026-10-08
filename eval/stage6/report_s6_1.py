"""S6-1 report: Top-1/3/5 by category, MRR@10 and per-question changes, from s6_1_runs.json and the blind grades."""
import json

questions = [q for q in json.load(open("eval/stage5_questions.json", encoding="utf-8"))["questions"]
             if q["category"] != "out_of_scope"]
runs = json.load(open("eval/stage6/s6_1_runs.json"))["runs"]
grades = {(g["question_id"], g["chunk_id"]): g["grade"] for g in json.load(open("eval/stage5_grades.json"))["grades"]}
CATEGORIES = ["natural_language", "exact_code", "code_in_context"]
VARIANTS = ["baseline", "T1", "T2"]


def first_sufficient(qid, variant):
    """Rank of the first chunk graded 2 in the top 10, or None."""
    for r in runs[qid][variant]:
        if grades[(qid, r["chunk_id"])] == 2:
            return r["rank"]
        # every chunk above the first sufficient one is graded (checked by run_s6_1.py), so a KeyError is a bug


rank = {(q["id"], v): first_sufficient(q["id"], v) for q in questions for v in VARIANTS}
summary = {}
for v in VARIANTS:
    s = {}
    for cat in CATEGORIES + ["overall"]:
        qs = [q for q in questions if cat in ("overall", q["category"])]
        s[cat] = {f"top{k}": sum(1 for q in qs if rank[(q["id"], v)] and rank[(q["id"], v)] <= k) for k in (1, 3, 5)}
        s[cat]["mrr10"] = round(sum(1 / rank[(q["id"], v)] for q in qs if rank[(q["id"], v)]) / len(qs), 3)
    summary[v] = s

per_question = []
for q in questions:
    base = rank[(q["id"], "baseline")]
    row = {"id": q["id"], "category": q["category"], "table_answer": q.get("answer_type") == "table",
           "route": runs[q["id"]]["baseline"][0]["route"], "baseline": base}
    for v in ("T1", "T2"):
        new = rank[(q["id"], v)]
        row[v] = new
        row[v + "_change"] = ("unchanged" if new == base else
                              "improved" if base is None or (new is not None and new < base) else "worse")
    per_question.append(row)

out = {"summary": summary, "per_question": per_question}
json.dump(out, open("eval/stage6/s6_1_results.json", "w"), indent=1)

for v in VARIANTS:
    print(v.ljust(9), "  ".join(f"{c[:8]:>8} T1/3/5 {summary[v][c]['top1']}/{summary[v][c]['top3']}/{summary[v][c]['top5']}"
                                f" MRR {summary[v][c]['mrr10']}" for c in CATEGORIES + ["overall"]))
print()
for row in per_question:
    if row["T1_change"] != "unchanged" or row["T2_change"] != "unchanged" or row["table_answer"]:
        print(row)
