"""S6-1 tie-break investigation: run baseline (bm25), T1 (vector) and T2 (neutral) on the Stage 5 development set.

Writes eval/stage6/s6_1_runs.json and lists chunks that still need a blind grade (scratch file given as argv[1]).
Run from the project root.
"""
import hashlib, json, sys

sys.path.insert(0, ".")
from src.vectorstore import FaissVectorStore
from src.retrieval_v2 import routed_search

baseline = json.load(open("eval/stage6/baseline_hashes.json"))
for path, digest in baseline["sha256"].items():
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == digest, f"baseline file changed: {path}"
print("baseline hashes verified:", len(baseline["sha256"]), "files")

questions = json.load(open("eval/stage5_questions.json", encoding="utf-8"))["questions"]
stage5_runs = json.load(open("eval/stage5_runs.json"))["runs"]
grades = {(g["question_id"], g["chunk_id"]): g["grade"] for g in json.load(open("eval/stage5_grades.json"))["grades"]}

store = FaissVectorStore("faiss_store")
store.load(expected_fingerprint=baseline["corpus_fingerprint"])

VARIANTS = {"baseline": "bm25", "T1": "vector", "T2": "neutral"}
runs, mismatches = {}, []
for q in questions:
    runs[q["id"]] = {}
    for name, tie_break in VARIANTS.items():
        top10 = routed_search(store, q["question"], 10, tie_break)
        runs[q["id"]][name] = [{k: r.get(k) for k in ["rank", "chunk_id", "page", "score", "vector_rank",
                                                      "bm25_rank", "route"]} for r in top10]
    # the baseline variant must reproduce Stage 5 and the frozen store exactly
    ids = [r["chunk_id"] for r in runs[q["id"]]["baseline"]]
    if ids != [r["chunk_id"] for r in stage5_runs[q["id"]]["routed"]] or \
            ids != [r["chunk_id"] for r in store.query(q["question"], 10, "routed")]:
        mismatches.append(q["id"])
print("baseline reproduces Stage 5 routed top-10:", "yes" if not mismatches else f"NO {mismatches}")
assert not mismatches

json.dump({"variants": VARIANTS, "runs": runs}, open("eval/stage6/s6_1_runs.json", "w"), indent=1)

# MRR@10 needs a grade for every chunk ranked above the first sufficient one; Top-k needs the whole top 5
need = set()
for q in questions:
    if q["category"] == "out_of_scope":
        continue
    for name in VARIANTS:
        found_sufficient = False
        for r in runs[q["id"]][name]:
            if r["rank"] > 5 and found_sufficient:
                break
            grade = grades.get((q["id"], r["chunk_id"]))
            if grade is None:
                need.add((q["id"], r["chunk_id"]))
            found_sufficient = found_sufficient or grade == 2
json.dump(sorted(need), open(sys.argv[1], "w"))
print("chunks still needing a blind grade:", len(need))
