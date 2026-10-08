"""S6-2: cross-encoder reranking of T1 routed candidates, two models x pool sizes N = 5, 10, 20, 30.

Development set only (Stage 5 questions); the frozen held-out set is not read.
Writes eval/stage6/s6_2_runs.json and the list of chunks still needing a blind grade (argv[1]). Run from the project root.
"""
import gc, hashlib, json, os, statistics, sys, time

import psutil

sys.path.insert(0, ".")
from src.rerank import RERANKERS, Reranker
from src.retrieval_v2 import routed_search
from src.vectorstore import FaissVectorStore

POOLS = [5, 10, 20, 30]
TOP = 10  # lists are scored to rank 10 (MRR@10); beyond the pool they keep T1 order

baseline = json.load(open("eval/stage6/baseline_hashes.json"))
for path, digest in baseline["sha256"].items():
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == digest, f"baseline file changed: {path}"
print("baseline hashes verified")

questions = json.load(open("eval/stage5_questions.json", encoding="utf-8"))["questions"]
grades = {(g["question_id"], g["chunk_id"]): g["grade"] for g in json.load(open("eval/stage5_grades.json"))["grades"]}
if os.path.exists("eval/stage6/grades.json"):
    grades.update({(g["question_id"], g["chunk_id"]): g["grade"]
                   for g in json.load(open("eval/stage6/grades.json"))["grades"]})

store = FaissVectorStore("faiss_store")
store.load(expected_fingerprint=baseline["corpus_fingerprint"])
process = psutil.Process()

# T1 candidates (retrieval only), timed; the same call is repeated inside each timed reranking run
routed_search(store, "warm up", 30, "vector")
t1, retrieval_ms = {}, []
for q in questions:
    start = time.perf_counter()
    t1[q["id"]] = routed_search(store, q["question"], 30, "vector")
    retrieval_ms.append((time.perf_counter() - start) * 1000)

out = {"pools": POOLS, "retrieval_only_ms": {"median": statistics.median(retrieval_ms),
                                             "p95": statistics.quantiles(retrieval_ms, n=20)[-1]},
       "models": {}}
for key, model_name in RERANKERS.items():
    gc.collect()
    rss_before = process.memory_info().rss
    start = time.perf_counter()
    reranker = Reranker(model_name)
    load_s = time.perf_counter() - start
    reranker.rerank("warm up", t1[questions[0]["id"]][:5])
    model = {"name": model_name, "load_s": round(load_s, 2),
             "memory_mb": round((process.memory_info().rss - rss_before) / 2**20), "pools": {}}
    for pool in POOLS:
        runs, added_ms, total_ms = {}, [], []
        for q in questions:
            start = time.perf_counter()
            candidates = routed_search(store, q["question"], max(pool, TOP), "vector")
            mid = time.perf_counter()
            reranked = reranker.rerank(q["question"], candidates[:pool])
            end = time.perf_counter()
            added_ms.append((end - mid) * 1000)
            total_ms.append((end - start) * 1000)
            assert [r["chunk_id"] for r in candidates] == [r["chunk_id"] for r in t1[q["id"]][:len(candidates)]]
            rest = [{**r, "retrieval_rank": r["rank"], "rerank_score": None} for r in candidates[pool:TOP]]
            final = (reranked + rest)[:TOP]
            runs[q["id"]] = [{"rank": n, "chunk_id": r["chunk_id"], "page": r["page"],
                              "retrieval_rank": r["retrieval_rank"], "rerank_score": r["rerank_score"],
                              "route": r["route"]} for n, r in enumerate(final, 1)]
        model["pools"][str(pool)] = {
            "added_ms": {"median": round(statistics.median(added_ms)), "p95": round(statistics.quantiles(added_ms, n=20)[-1])},
            "total_ms": {"median": round(statistics.median(total_ms)), "p95": round(statistics.quantiles(total_ms, n=20)[-1])},
            "runs": runs}
        print(key, pool, model["pools"][str(pool)]["added_ms"], model["pools"][str(pool)]["total_ms"])
    out["models"][key] = model
    del reranker
json.dump(out, open("eval/stage6/s6_2_runs.json", "w"), indent=1)

# chunks to grade: everything above the first sufficient chunk in each top 10, and the whole top 5
need = set()
for q in questions:
    if q["category"] == "out_of_scope":
        continue
    for model in out["models"].values():
        for pool in model["pools"].values():
            found_sufficient = False
            for r in pool["runs"][q["id"]]:
                if r["rank"] > 5 and found_sufficient:
                    break
                grade = grades.get((q["id"], r["chunk_id"]))
                if grade is None:
                    need.add((q["id"], r["chunk_id"]))
                found_sufficient = found_sufficient or grade == 2
json.dump(sorted(need), open(sys.argv[1], "w"))
print("chunks still needing a blind grade:", len(need))
