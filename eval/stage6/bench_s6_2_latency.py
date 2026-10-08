"""S6-2 latency re-measurement: reranking time only, 3 repetitions per question, configurations interleaved.

The first S6-2 run timed each configuration once, in sequence, and its medians did not rise with pool size, so
background load on the machine could not be separated from model cost. Here every (model, pool) is timed on the
same pre-retrieved T1 candidates, round-robin, and each question's time is the median of 3 repetitions.
"""
import json, statistics, sys, time

import psutil

sys.path.insert(0, ".")
from src.rerank import RERANKERS, Reranker
from src.retrieval_v2 import routed_search
from src.vectorstore import FaissVectorStore

POOLS, REPS = [5, 10, 20, 30], 3
questions = json.load(open("eval/stage5_questions.json", encoding="utf-8"))["questions"]
store = FaissVectorStore("faiss_store")
store.load(expected_fingerprint=json.load(open("eval/stage6/baseline_hashes.json"))["corpus_fingerprint"])
candidates = {q["id"]: routed_search(store, q["question"], 30, "vector") for q in questions}
models = {key: Reranker(name) for key, name in RERANKERS.items()}
for m in models.values():
    m.rerank("warm up", candidates[questions[0]["id"]][:30])

print("cpu load before (%):", psutil.cpu_percent(interval=2), "| cores:", psutil.cpu_count(),
      "| free RAM (GB):", round(psutil.virtual_memory().available / 2**30, 1))
times = {(k, p, q["id"]): [] for k in models for p in POOLS for q in questions}
for rep in range(REPS):
    for q in questions:
        for key, model in models.items():
            for pool in POOLS:
                start = time.perf_counter()
                model.rerank(q["question"], candidates[q["id"]][:pool])
                times[(key, pool, q["id"])].append((time.perf_counter() - start) * 1000)
out = {}
for key in models:
    for pool in POOLS:
        per_q = [statistics.median(times[(key, pool, q["id"])]) for q in questions]
        out[f"{key}@{pool}"] = {"median": round(statistics.median(per_q)), "p95": round(statistics.quantiles(per_q, n=20)[-1]),
                                "max": round(max(per_q))}
        print(f"{key}@{pool}", out[f"{key}@{pool}"])
print("cpu load after (%):", psutil.cpu_percent(interval=2))
json.dump({"reps": REPS, "added_ms": out}, open("eval/stage6/s6_2_latency.json", "w"), indent=1)
