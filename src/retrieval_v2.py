"""
Stage 6 retrieval experiments, layered on the frozen Stage 4 store.

src/vectorstore.py stays byte-identical (the Stage 4/5 baseline); everything here uses only its public
vector_search / bm25_search / chunks_with_codes methods, so the baseline can always be reproduced.
"""
from typing import Any, Dict, List

from src.vectorstore import HYBRID_CANDIDATES, RRF_K, FaissVectorStore

# How code-aware hybrid search orders chunks with equal RRF scores
#   "bm25"    - Stage 4 baseline: the better BM25 rank wins
#   "vector"  - S6-1 T1: the better vector rank wins
#   "neutral" - S6-1 T2: the better of the two ranks wins, favouring neither retriever
TIE_BREAKS = ("bm25", "vector", "neutral")


def hybrid_search(store: FaissVectorStore, query: str, top_k: int = 5, tie_break: str = "bm25",
                  candidates: int = HYBRID_CANDIDATES, rrf_k: int = RRF_K) -> List[Dict[str, Any]]:
    """Code-aware RRF exactly as FaissVectorStore.hybrid_search, except for how ties are ordered."""
    if tie_break not in TIE_BREAKS:
        raise ValueError(f"tie_break must be one of {TIE_BREAKS}")
    chunk_ids = store.chunks_with_codes(query)
    vector_ranks = {r["chunk_id"]: r["rank"] for r in store.vector_search(query, candidates, chunk_ids)}
    bm25_ranks = {r["chunk_id"]: r["rank"] for r in store.bm25_search(query, candidates, chunk_ids)}
    fused = {}
    for ranks in (vector_ranks, bm25_ranks):
        for chunk_id, rank in ranks.items():
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
    missing = candidates + 1

    def tie_rank(chunk_id: int) -> int:
        if chunk_ids is None or tie_break == "vector":  # without a code filter the baseline already uses vector
            return vector_ranks.get(chunk_id, missing)
        if tie_break == "bm25":
            return bm25_ranks.get(chunk_id, missing)
        return min(vector_ranks.get(chunk_id, missing), bm25_ranks.get(chunk_id, missing))

    best = sorted(fused.items(), key=lambda item: (-item[1], tie_rank(item[0]), item[0]))[:top_k]
    return [store._result(chunk_id, rank, score, vector_rank=vector_ranks.get(chunk_id),
                          bm25_rank=bm25_ranks.get(chunk_id), code_filtered=chunk_ids is not None)
            for rank, (chunk_id, score) in enumerate(best, 1)]


def routed_search(store: FaissVectorStore, query: str, top_k: int = 5,
                  tie_break: str = "bm25") -> List[Dict[str, Any]]:
    """Stage 4 routing (code-aware hybrid for known course codes, vector-only otherwise) with a chosen tie-break."""
    if store.chunks_with_codes(query):
        return [{**r, "route": "code_hybrid"} for r in hybrid_search(store, query, top_k, tie_break)]
    return [{**r, "route": "vector"} for r in store.vector_search(query, top_k)]
