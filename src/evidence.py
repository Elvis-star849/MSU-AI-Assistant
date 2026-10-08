"""
Stage 7 access to the accepted Stage 6 retrieval (read-only wrapper; Stage 6 modules are imported, never changed).

  main     - T1 tie-break -> faiss_store_v2 (heading-aware) -> top 10 -> MiniLM (heading + chunk text) -> best 5
             (S6-6 Arm 3; S6-3 configuration "B")
  fallback - T1 tie-break -> faiss_store -> top 10 -> first 5, no reranker (S6-6 Arm 1)

Each evidence item keeps the original chunk text, source, page, heading and the ranking information. The ranking
fields are for logging and evaluation only; the context builder does not show them to the LLM.
"""
from typing import Any, Dict, List, Optional

CORPUS_FINGERPRINT = "sha256:545d0dabe1fbe022baf9dd5dfaadaaee6637490e9a2f5fef9e04cf1d455e41f5"
CONFIGURATIONS = {
    "main": {"index": "faiss_store_v2", "tie_break": "vector", "pool": 10, "reranker": "minilm",
             "with_heading": True, "top_k": 5},
    "fallback": {"index": "faiss_store", "tie_break": "vector", "pool": 10, "reranker": None,
                 "with_heading": False, "top_k": 5},
}


class Stage6Retriever:
    def __init__(self, configuration: str = "main", expected_fingerprint: str = CORPUS_FINGERPRINT,
                 store: Any = None, reranker: Any = None):
        if configuration not in CONFIGURATIONS:
            raise ValueError(f"configuration must be one of {tuple(CONFIGURATIONS)}")
        self.configuration = configuration
        self.config = CONFIGURATIONS[configuration]
        self._expected_fingerprint = expected_fingerprint
        self._store = store
        self._reranker = reranker

    def _load(self):
        from src.heading_store import HeadingAwareStore
        from src.rerank import RERANKERS, Reranker
        from src.vectorstore import FaissVectorStore

        if self._store is None:
            cls = HeadingAwareStore if self.config["index"] == "faiss_store_v2" else FaissVectorStore
            store = cls(self.config["index"])
            store.load(expected_fingerprint=self._expected_fingerprint)
            self._store = store
        if self.config["reranker"] and self._reranker is None:
            self._reranker = Reranker(RERANKERS[self.config["reranker"]])

    def retrieve(self, question: str) -> List[Dict[str, Any]]:
        from src.retrieval_v2 import routed_search

        self._load()
        c = self.config
        candidates = routed_search(self._store, question, c["pool"], c["tie_break"])
        if c["reranker"]:
            ranked = self._reranker.rerank(question, candidates, with_heading=c["with_heading"])
        else:
            ranked = [{**r, "retrieval_rank": r["rank"], "rerank_score": None} for r in candidates]
        return [to_evidence(r, self.configuration) for r in ranked[:c["top_k"]]]


def to_evidence(result: Dict[str, Any], configuration: str) -> Dict[str, Any]:
    metadata = result.get("metadata") or {}
    heading: Optional[str] = metadata.get("heading")
    return {"rank": result["rank"], "chunk_id": result["chunk_id"], "source": result["source"],
            "page": result["page"], "heading": heading, "text": result["text"],
            "retrieval_rank": result.get("retrieval_rank", result["rank"]), "retrieval_score": result.get("score"),
            "rerank_score": result.get("rerank_score"), "route": result.get("route"), "configuration": configuration}
