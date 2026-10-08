"""S6-6 blind grading sheets: per held-out question, the unique chunks pooled from all four arms, shuffled,
labelled anonymously, with no arm or rank shown.

phase "top5":   every chunk in any arm's top 5 (all Top-k metrics)
phase "rank6_10": chunks at ranks 6-10 that sit above an arm's first sufficient chunk (MRR@10 only);
                  needs the phase-1 grades in eval/stage6/s6_6_grades.json
Usage: python eval/stage6/make_s6_6_sheet.py top5|rank6_10 <sheet.txt> <labels.json>
"""
import json, os, random, sys

phase, sheet_path, labels_path = sys.argv[1:4]
holdout = json.load(open("eval/stage6/holdout_questions.json", encoding="utf-8"))
runs = json.load(open("eval/stage6/s6_6_runs.json"))["runs"]
records = {}
for line in open("faiss_store/chunks.jsonl", encoding="utf-8"):
    r = json.loads(line)
    records[r["chunk_id"]] = r
graded = {}
if os.path.exists("eval/stage6/s6_6_grades.json"):
    graded = {(g["question_id"], g["chunk_id"]): g["grade"] for g in json.load(open("eval/stage6/s6_6_grades.json"))["grades"]}

rng = random.Random(606 if phase == "top5" else 610)
lines, labels = [], {}
for q in holdout["questions"]:
    if q["category"] == "out_of_scope":
        continue
    if phase == "top5":
        pool = {r["chunk_id"] for arm in runs.values() for r in arm[q["id"]][:5]}
    else:
        pool = set()
        for arm in runs.values():
            ranked = arm[q["id"]]
            if any(graded.get((q["id"], r["chunk_id"])) == 2 for r in ranked[:5]):
                continue
            for r in ranked[5:]:
                if (q["id"], r["chunk_id"]) not in graded:
                    pool.add(r["chunk_id"])
                elif graded[(q["id"], r["chunk_id"])] == 2:
                    break
    if not pool:
        continue
    pool = sorted(pool)
    rng.shuffle(pool)
    tag = "t" if phase == "top5" else "r"
    lines.append(f"\n######## {q['id']}: {q['question']}\nSUFFICIENT: {q['sufficient']}\nPAGES: {', '.join(q['pages'])}"
                 + (f"\nNOTE: {q['note']}" if q.get("note") else ""))
    for n, chunk_id in enumerate(pool, 1):
        label = f"{q['id']}-{tag}{n:02d}"
        labels[label] = chunk_id
        lines.append(f"[{label}] {' '.join(records[chunk_id]['text'].split())}")
open(sheet_path, "w", encoding="utf-8").write("\n".join(lines))
json.dump(labels, open(labels_path, "w"))
print(f"{phase}: {len(labels)} chunks to grade")
