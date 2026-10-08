"""S6-6: the held-out evaluation. One run of all four arms on the frozen held-out set.

Refuses to run unless every hash in eval/stage6/s6_6_freeze.json matches. The held-out questions are read only
after that check; this script is the moment the held-out set is opened.
Writes eval/stage6/s6_6_runs.json. Grading and metrics are separate steps. Run from the project root.
"""
import hashlib, json, os, statistics, sys, time

sys.path.insert(0, ".")
FREEZE = "eval/stage6/s6_6_freeze.json"
HOLDOUT = "eval/stage6/holdout_questions.json"
OUT = "eval/stage6/s6_6_runs.json"
TOP = 10


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


freeze = json.load(open(FREEZE))
bad = [path for path, digest in freeze["sha256"].items() if sha256(os.path.expanduser(path)) != digest]
assert not bad, f"frozen files changed: {bad}"
assert not os.path.exists(OUT), "S6-6 has already been run; a re-run must be disclosed and approved"
print(f"freeze verified: {len(freeze['sha256'])} files, commit {freeze['git_commit']}")

os.environ["HF_HUB_OFFLINE"] = "1"
from src.heading_store import HeadingAwareStore
from src.rerank import RERANKERS, Reranker
from src.retrieval_v2 import routed_search
from src.vectorstore import FaissVectorStore

v1 = FaissVectorStore("faiss_store")
v1.load(expected_fingerprint=freeze["corpus_fingerprint"])
v2 = HeadingAwareStore("faiss_store_v2")
v2.load(expected_fingerprint=freeze["corpus_fingerprint"])
reranker = Reranker(RERANKERS["minilm"])
for warm in ("warm up", "HAWS 433"):  # load models and caches before timing
    v1.query(warm, TOP)
    v2.query(warm, TOP)
    reranker.rerank(warm, routed_search(v2, warm, TOP, "vector"), with_heading=True)


def arm3(query):
    candidates = routed_search(v2, query, TOP, "vector")
    start = time.perf_counter()
    ranked = reranker.rerank(query, candidates, with_heading=True)
    return ranked, (time.perf_counter() - start) * 1000


ARMS = {
    "arm0": lambda q: (v1.query(q, TOP, "routed"), None),
    "arm1": lambda q: (routed_search(v1, q, TOP, "vector"), None),
    "arm2": lambda q: (routed_search(v2, q, TOP, "vector"), None),
    "arm3": arm3,
}

# ---- the held-out set is opened here ----
holdout = json.load(open(HOLDOUT, encoding="utf-8"))
opened_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
runs = {arm: {} for arm in ARMS}
total_ms = {arm: [] for arm in ARMS}
rerank_ms = []
for q in holdout["questions"]:
    for arm, search in ARMS.items():
        start = time.perf_counter()
        results, added = search(q["question"])
        total_ms[arm].append((time.perf_counter() - start) * 1000)
        if added is not None:
            rerank_ms.append(added)
        runs[arm][q["id"]] = [{"rank": n, "chunk_id": r["chunk_id"], "source": r["source"], "page": r["page"],
                               "score": r["score"], "rerank_score": r.get("rerank_score"),
                               "route": r.get("route")} for n, r in enumerate(results, 1)]

p95 = lambda xs: statistics.quantiles(xs, n=20)[-1]
latency = {arm: {"total_median_ms": round(statistics.median(v)), "total_p95_ms": round(p95(v))}
           for arm, v in total_ms.items()}
latency["arm3"].update({"rerank_added_median_ms": round(statistics.median(rerank_ms)),
                        "rerank_added_p95_ms": round(p95(rerank_ms))})
json.dump({"opened_at": opened_at, "git_commit": freeze["git_commit"], "holdout_sha256": sha256(HOLDOUT),
           "top": TOP, "arms": {"arm0": "Stage 4 routed, faiss_store/", "arm1": "T1, faiss_store/",
                                "arm2": "T1, faiss_store_v2/", "arm3": "T1, faiss_store_v2/ -> MiniLM (heading + text)"},
           "latency": latency, "runs": runs}, open(OUT, "w"), indent=1)
print("held-out opened at", opened_at, "| runs saved | latency:", json.dumps(latency))
