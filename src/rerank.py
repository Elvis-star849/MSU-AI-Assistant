"""
Stage 6 cross-encoder reranking (S6-2).

A cross-encoder reads the question and one chunk together and scores how well the chunk answers it.
Candidates come from routed search with the provisionally accepted T1 tie-break; the frozen store is not changed.
"""
from typing import Any, Dict, List

from sentence_transformers import CrossEncoder

from src.retrieval_v2 import routed_search
from src.vectorstore import FaissVectorStore

RERANKERS = {"bge": "BAAI/bge-reranker-base", "minilm": "cross-encoder/ms-marco-MiniLM-L-6-v2"}


def passage_text(text: str) -> str:
    """Chunk text without its citation header ("[MSU Humanities Yearbook, p. 404]"), as BM25 sees it."""
    return text.split("\n", 1)[1] if text.startswith("[") and "\n" in text else text


class Reranker:
    def __init__(self, model_name: str = RERANKERS["bge"]):
        self.model_name = model_name
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, results: List[Dict[str, Any]], with_heading: bool = False) -> List[Dict[str, Any]]:
        """
        Reorder results by cross-encoder score (ties keep their retrieval order).
        with_heading (S6-3 variant B): the model also sees the chunk's heading line, when the index has one.
        """
        if not results:
            return []

        def text(r):
            heading = r.get("metadata", {}).get("heading") if with_heading else None
            return f"{heading}\n{passage_text(r['text'])}" if heading else passage_text(r["text"])

        scores = self.model.predict([(query, text(r)) for r in results])
        order = sorted(range(len(results)), key=lambda i: (-float(scores[i]), i))
        return [{**results[i], "retrieval_rank": results[i]["rank"], "rank": new_rank,
                 "rerank_score": float(scores[i])} for new_rank, i in enumerate(order, 1)]


def reranked_search(store: FaissVectorStore, reranker: Reranker, query: str, top_k: int = 5,
                    pool: int = 20, tie_break: str = "vector") -> List[Dict[str, Any]]:
    """Rerank the routed top-`pool` candidates; results beyond the pool keep their retrieval order."""
    candidates = routed_search(store, query, max(pool, top_k), tie_break)
    reranked = reranker.rerank(query, candidates[:pool])
    rest = [{**r, "retrieval_rank": r["rank"], "rank": rank, "rerank_score": None}
            for rank, r in enumerate(candidates[pool:], len(reranked) + 1)]
    return (reranked + rest)[:top_k]
