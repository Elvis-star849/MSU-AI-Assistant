"""S6-3: heading-aware index (faiss_store_v2) vs the accepted configuration, on the Stage 5 development set only.

Configurations (all: T1 routed candidates -> top 10 -> MiniLM rerank -> ranked list of 10):
  accepted - frozen faiss_store/ (must reproduce S6-2 MiniLM@10 exactly)
  A        - faiss_store_v2/, MiniLM sees the original chunk text
  B        - faiss_store_v2/, MiniLM sees heading line + chunk text
Also records, for diagnosis, T1 without reranking on each index and the N4 answer chunk's full vector/BM25 ranks.
argv[1]: file listing chunks that still need a blind grade. Run from the project root.
"""
import hashlib, json, os, statistics, sys, time

sys.path.insert(0, ".")
from src.heading_store import HeadingAwareStore
from src.rerank import RERANKERS, Reranker
from src.retrieval_v2 import routed_search
from src.vectorstore import FaissVectorStore

POOL = 10
N4_ANSWER_CHUNK = 38  # the N4 answer-key chunk (membership list (a)-(f), Hum p. 14), found by text search

baseline = json.load(open("eval/stage6/baseline_hashes.json"))
for path, digest in baseline["sha256"].items():
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == digest, f"baseline file changed: {path}"
print("baseline hashes verified")

questions = json.load(open("eval/stage5_questions.json", encoding="utf-8"))["questions"]
s62 = json.load(open("eval/stage6/s6_2_runs.json"))["models"]["minilm"]["pools"][str(POOL)]["runs"]
grades = {(g["question_id"], g["chunk_id"]): g["grade"] for g in json.load(open("eval/stage5_grades.json"))["grades"]}
grades.update({(g["question_id"], g["chunk_id"]): g["grade"] for g in json.load(open("eval/stage6/grades.json"))["grades"]})

v1 = FaissVectorStore("faiss_store")
v1.load(expected_fingerprint=baseline["corpus_fingerprint"])
v2 = HeadingAwareStore("faiss_store_v2")
v2.load(expected_fingerprint=baseline["corpus_fingerprint"])
v2._embedder = v1._embedder  # same embedding model; load it once
reranker = Reranker(RERANKERS["minilm"])
reranker.rerank("warm up", routed_search(v1, "warm up", POOL, "vector"))

CONFIGS = {"accepted": (v1, False), "A": (v2, False), "B": (v2, True)}
runs = {name: {} for name in CONFIGS}
runs.update({"T1_v1": {}, "T1_v2": {}})
added_ms = {name: [] for name in CONFIGS}
for q in questions:
    for name, (store, with_heading) in CONFIGS.items():
        candidates = routed_search(store, q["question"], POOL, "vector")
        start = time.perf_counter()
        ranked = reranker.rerank(q["question"], candidates, with_heading)
        added_ms[name].append((time.perf_counter() - start) * 1000)
        runs[name][q["id"]] = [{"rank": r["rank"], "chunk_id": r["chunk_id"], "page": r["page"],
                                "retrieval_rank": r["retrieval_rank"], "rerank_score": r["rerank_score"],
                                "route": r["route"]} for r in ranked]
    for name, store in (("T1_v1", v1), ("T1_v2", v2)):
        runs[name][q["id"]] = [{"rank": r["rank"], "chunk_id": r["chunk_id"], "page": r["page"], "route": r["route"]}
                               for r in routed_search(store, q["question"], POOL, "vector")]
    assert [r["chunk_id"] for r in runs["accepted"][q["id"]]] == [r["chunk_id"] for r in s62[q["id"]]], \
        f"accepted configuration does not reproduce S6-2 MiniLM@10 for {q['id']}"
print("accepted configuration reproduces S6-2 MiniLM@10: yes")

# N4 diagnosis: where the answer chunk sits in each index's full vector and BM25 rankings
n4 = next(q for q in questions if q["id"] == "N4")["question"]
diag = {}
for name, store in (("v1", v1), ("v2", v2)):
    vec = [r["chunk_id"] for r in store.vector_search(n4, len(store.records))]
    bm = [r["chunk_id"] for r in store.bm25_search(n4, len(store.records))]
    diag[name] = {"vector_rank": vec.index(N4_ANSWER_CHUNK) + 1,
                  "bm25_rank": bm.index(N4_ANSWER_CHUNK) + 1 if N4_ANSWER_CHUNK in bm else None}
diag["v2_heading"] = v2.records[N4_ANSWER_CHUNK]["heading"]
print("N4 answer chunk ranks:", diag)

latency = {name: {"median": round(statistics.median(v)), "p95": round(statistics.quantiles(v, n=20)[-1])}
           for name, v in added_ms.items()}
json.dump({"pool": POOL, "runs": runs, "added_ms": latency, "n4_diagnosis": diag},
          open("eval/stage6/s6_3_runs.json", "w"), indent=1)
print("added rerank ms:", latency)

need = set()
for q in questions:
    if q["category"] == "out_of_scope":
        continue
    for name in runs:
        found_sufficient = False
        for r in runs[name][q["id"]]:
            if r["rank"] > 5 and found_sufficient:
                break
            grade = grades.get((q["id"], r["chunk_id"]))
            if grade is None:
                need.add((q["id"], r["chunk_id"]))
            found_sufficient = found_sufficient or grade == 2
json.dump(sorted(need), open(sys.argv[1], "w"))
print("chunks still needing a blind grade:", len(need))
