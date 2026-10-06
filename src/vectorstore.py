import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from src.embedding import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_MODEL,
    QUERY_PREFIXES,
    EmbeddingPipeline,
)

# Files written to the persist directory. Line i of CHUNKS_FILE belongs to vector i of INDEX_FILE.
INDEX_FILE = "index.faiss"
CHUNKS_FILE = "chunks.jsonl"
MANIFEST_FILE = "manifest.json"
MANIFEST_VERSION = 1
REQUIRED_RECORD_FIELDS = {"chunk_id", "source", "file_name", "page", "text"}

# BM25 keyword search settings (rank_bm25 defaults)
BM25_K1 = 1.5
BM25_B = 0.75
BM25_TOKENIZER_VERSION = "v1"  # bump if bm25_tokenize() changes

# Reciprocal Rank Fusion: score = sum over retrievers of 1 / (RRF_K + rank)
RRF_K = 60
# How many results each retriever contributes to the fusion
HYBRID_CANDIDATES = 50

# Words that carry no meaning for keyword search
STOPWORDS = frozenset("""
a about am an and any are as at be been being but by can could did do does doing for from had has have
how i if in into is it its me my of on or our should so than that the their them then there these they
this those to was we were what when where which while who whom why will with would you your tell describe
explain please
""".split())

_WORD = re.compile(r"[a-z]+|\d+")
# Course codes, written either "HAWS 433" or "HAWS433" in the yearbooks
_COURSE_CODE = re.compile(r"\b([A-Za-z]{2,6})\s?(\d{3})(?!\d)")
_CITATION_HEADER = re.compile(r"^\[[^\]\n]*\]\n")


def bm25_tokenize(text: str) -> List[str]:
    """
    Lower-case words and numbers (stopwords removed), plus one joined token per course code, so
    "HAWS 433", "HAWS433" and "haws 433" all produce the same rare token "haws433".
    """
    tokens = [t for t in _WORD.findall(text.lower()) if t not in STOPWORDS]
    return tokens + [(prefix + number).lower() for prefix, number in _COURSE_CODE.findall(text)]


def course_codes(text: str, uppercase_only: bool = False) -> List[str]:
    """
    Course codes in a text, normalised to the joined lower-case form ("HAWS 433" -> "haws433").
    uppercase_only (used on the yearbook text, where real codes are always capitals) skips phrases like
    "load 270" or "at least 360"; queries are matched in any case ("mpg 704").
    """
    return sorted({(prefix + number).lower() for prefix, number in _COURSE_CODE.findall(text)
                   if not uppercase_only or (prefix.isupper() and prefix.lower() not in STOPWORDS)})


def corpus_fingerprint(records: List[Dict[str, Any]]) -> str:
    """SHA-256 of the ordered chunk records (id, source, file, page, text). Any change in order or content changes it."""
    digest = hashlib.sha256()
    for r in records:
        row = [r["chunk_id"], r["source"], r.get("file_name"), r.get("page"), r["text"]]
        digest.update(json.dumps(row, ensure_ascii=False).encode("utf-8"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def vectors_checksum(vectors: np.ndarray) -> str:
    return "sha256:" + hashlib.sha256(np.ascontiguousarray(vectors, dtype="float32").tobytes()).hexdigest()


def chunk_to_record(chunk: Any) -> Dict[str, Any]:
    """The data stored next to each vector: everything needed to show and cite the chunk."""
    return {
        "chunk_id": chunk.metadata["chunk_id"],
        "source": chunk.metadata.get("source", "Unknown"),
        "file_name": chunk.metadata.get("file_name"),
        "page": chunk.metadata.get("page"),
        "text": chunk.page_content,
    }


class FaissVectorStore:
    """
    FAISS vector index (cosine similarity on normalised embeddings) + BM25 keyword index over the same chunks,
    combined with Reciprocal Rank Fusion for hybrid search.
    """

    def __init__(self, persist_dir: str = "faiss_store", embedding_model: str = EMBEDDING_MODEL,
                 chunk_size: int = CHUNK_SIZE, chunk_overlap: int = CHUNK_OVERLAP):
        self.persist_dir = persist_dir
        self.embedding_model = embedding_model
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.index = None
        self.records: List[Dict[str, Any]] = []
        self.manifest: Dict[str, Any] = {}
        self.bm25 = None
        self.code_to_chunks: Dict[str, List[int]] = {}  # "haws433" -> chunk_ids that mention HAWS 433
        self._embedder = None
        self.timings: Dict[str, float] = {}

    @property
    def embedder(self) -> EmbeddingPipeline:
        """The embedding model is loaded on first use (only needed to embed queries or build the index)."""
        if self._embedder is None:
            self._embedder = EmbeddingPipeline(self.embedding_model, self.chunk_size, self.chunk_overlap)
        return self._embedder

    # ------------------------------------------------------------------ build
    def build_from_documents(self, documents: List[Any]):
        """Chunk, embed and index page Documents, then save to persist_dir."""
        chunks = self.embedder.chunk_documents(documents)
        embeddings = self.embedder.embed_chunks(chunks)
        self.build(chunks, embeddings)
        self.save()

    def build(self, chunks: List[Any], embeddings: np.ndarray):
        """Build the FAISS and BM25 indexes from chunks and their embeddings (row i = chunks[i])."""
        embeddings = np.ascontiguousarray(embeddings, dtype="float32")
        if embeddings.ndim != 2 or embeddings.shape[0] != len(chunks):
            raise ValueError(f"{len(chunks)} chunks but embeddings have shape {embeddings.shape}")
        norms = np.linalg.norm(embeddings, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-3):
            raise ValueError("Embeddings must be normalised (cosine similarity via inner product)")

        records = [chunk_to_record(c) for c in chunks]
        if [r["chunk_id"] for r in records] != list(range(len(records))):
            raise ValueError("chunk_id must equal the chunk's position (0..n-1) so row i maps to chunk i")

        start = time.perf_counter()
        index = faiss.IndexFlatIP(embeddings.shape[1])
        index.add(embeddings)
        self.timings["faiss_build_s"] = time.perf_counter() - start

        self.index, self.records = index, records
        self.manifest = self._make_manifest(embeddings)
        self._build_bm25()
        print(f"[INFO] Built index: {index.ntotal} vectors, dim={index.d}")

    def _make_manifest(self, embeddings: np.ndarray) -> Dict[str, Any]:
        config = {
            "embedding_model": self.embedding_model,
            "embedding_dim": int(embeddings.shape[1]),
            "normalized_embeddings": True,
            "query_prefix": QUERY_PREFIXES.get(self.embedding_model, ""),
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
        }
        fingerprint = corpus_fingerprint(self.records)
        # Fingerprint of the corpus + embedding configuration together
        build_fingerprint = "sha256:" + hashlib.sha256(
            json.dumps({"corpus": fingerprint, **config}, sort_keys=True).encode("utf-8")).hexdigest()
        sources: Dict[str, int] = {}
        for r in self.records:
            sources[r["source"]] = sources.get(r["source"], 0) + 1
        return {
            "manifest_version": MANIFEST_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **config,
            "chunk_count": len(self.records),
            "chunks_per_source": sources,
            "corpus_fingerprint": fingerprint,
            "build_fingerprint": build_fingerprint,
            "vectors_checksum": vectors_checksum(embeddings),
            "index_type": "IndexFlatIP",
            "faiss_version": faiss.__version__,
            "bm25": {"variant": "BM25Okapi", "k1": BM25_K1, "b": BM25_B, "tokenizer": BM25_TOKENIZER_VERSION},
        }

    def _build_bm25(self):
        start = time.perf_counter()
        # The citation header ("[MSU Humanities Yearbook, p. 404]") is left out so page numbers don't match course numbers
        bodies = [_CITATION_HEADER.sub("", r["text"], count=1) for r in self.records]
        self.bm25 = BM25Okapi([bm25_tokenize(body) for body in bodies], k1=BM25_K1, b=BM25_B)
        self.code_to_chunks = {}
        for chunk_id, body in enumerate(bodies):
            for code in course_codes(body, uppercase_only=True):
                self.code_to_chunks.setdefault(code, []).append(chunk_id)
        self.timings["bm25_build_s"] = time.perf_counter() - start

    # ------------------------------------------------------------------ save / load
    def _path(self, name: str) -> str:
        return os.path.join(self.persist_dir, name)

    def save(self):
        os.makedirs(self.persist_dir, exist_ok=True)
        start = time.perf_counter()
        faiss.write_index(self.index, self._path(INDEX_FILE))
        with open(self._path(CHUNKS_FILE), "w", encoding="utf-8") as f:
            for r in self.records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(self._path(MANIFEST_FILE), "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2, ensure_ascii=False)
        self.timings["save_s"] = time.perf_counter() - start
        print(f"[INFO] Saved index, {len(self.records)} chunk records and manifest to {self.persist_dir}")

    def load(self, expected_fingerprint: Optional[str] = None):
        """
        Load and verify the saved index. Raises ValueError if the files don't match each other, the configured
        embedding model / chunking, or (when given) the fingerprint of the current chunk corpus.
        """
        start = time.perf_counter()
        with open(self._path(MANIFEST_FILE), encoding="utf-8") as f:
            manifest = json.load(f)
        index = faiss.read_index(self._path(INDEX_FILE))
        with open(self._path(CHUNKS_FILE), encoding="utf-8") as f:
            records = [json.loads(line) for line in f]
        self.timings["read_s"] = time.perf_counter() - start

        start = time.perf_counter()
        problems = []
        expected_config = {"embedding_model": self.embedding_model, "chunk_size": self.chunk_size,
                           "chunk_overlap": self.chunk_overlap}
        for key, value in expected_config.items():
            if manifest.get(key) != value:
                problems.append(f"{key}: index has {manifest.get(key)!r}, expected {value!r}")
        if not (index.ntotal == len(records) == manifest["chunk_count"]):
            problems.append(f"counts differ: {index.ntotal} vectors, {len(records)} records, "
                            f"manifest {manifest['chunk_count']}")
        if index.d != manifest["embedding_dim"]:
            problems.append(f"dim: index {index.d}, manifest {manifest['embedding_dim']}")
        incomplete = [i for i, r in enumerate(records) if not REQUIRED_RECORD_FIELDS <= r.keys()]
        if incomplete:
            problems.append(f"{len(incomplete)} chunk records lack {sorted(REQUIRED_RECORD_FIELDS)} "
                            f"(first: line {incomplete[0] + 1})")
        else:
            if [r["chunk_id"] for r in records] != list(range(len(records))):
                problems.append("chunk records are not in chunk_id order")
            if corpus_fingerprint(records) != manifest["corpus_fingerprint"]:
                problems.append("chunk records do not match the manifest's corpus fingerprint")
        if vectors_checksum(index.reconstruct_n(0, index.ntotal)) != manifest["vectors_checksum"]:
            problems.append("FAISS vectors do not match the manifest's checksum")
        if expected_fingerprint and expected_fingerprint != manifest["corpus_fingerprint"]:
            problems.append("index was built from a different chunk corpus than the current one (rebuild it)")
        if problems:
            raise ValueError("Saved index failed verification:\n  - " + "\n  - ".join(problems))
        self.timings["verify_s"] = time.perf_counter() - start

        self.index, self.records, self.manifest = index, records, manifest
        self._build_bm25()
        print(f"[INFO] Loaded and verified {index.ntotal} vectors + chunk records from {self.persist_dir}")

    # ------------------------------------------------------------------ search
    def _result(self, idx: int, rank: int, score: float, **extra) -> Dict[str, Any]:
        r = self.records[idx]
        return {"rank": rank, "chunk_id": r["chunk_id"], "source": r["source"], "page": r["page"],
                "text": r["text"], "score": score, "metadata": r, **extra}

    def vector_search(self, query: str, top_k: int = 5,
                      chunk_ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        """Semantic search: cosine similarity between the query embedding and every chunk (or only chunk_ids)."""
        params = None
        if chunk_ids is not None:
            params = faiss.SearchParameters(sel=faiss.IDSelectorBatch(np.asarray(chunk_ids, dtype="int64")))
        scores, ids = self.index.search(self.embedder.embed_query(query), top_k, params=params)
        return [self._result(int(i), rank, float(s))
                for rank, (i, s) in enumerate(zip(ids[0], scores[0]), 1) if i >= 0]

    def bm25_search(self, query: str, top_k: int = 5,
                    chunk_ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        """Keyword search: BM25 over words and course codes. Chunks sharing no keyword are not returned."""
        scores = self.bm25.get_scores(bm25_tokenize(query))
        ids = np.arange(len(scores)) if chunk_ids is None else np.asarray(chunk_ids)
        top = ids[np.argsort(-scores[ids], kind="stable")][:top_k]
        return [self._result(int(i), rank, float(scores[i]))
                for rank, i in enumerate(top, 1) if scores[i] > 0]

    def chunks_with_codes(self, query: str) -> Optional[List[int]]:
        """Chunks mentioning any course code in the query, or None if the query has no code known to the index."""
        ids = sorted({i for code in course_codes(query) for i in self.code_to_chunks.get(code, [])})
        return ids or None

    def hybrid_search(self, query: str, top_k: int = 5, candidates: int = HYBRID_CANDIDATES,
                      rrf_k: int = RRF_K, code_filter: bool = True) -> List[Dict[str, Any]]:
        """
        Vector + BM25 results combined with Reciprocal Rank Fusion.
        With code_filter, a query naming a course code (e.g. "HAWS 433") is answered only from chunks containing
        that code; both retrievers then rank within those chunks (e.g. the description above programme tables).
        """
        chunk_ids = self.chunks_with_codes(query) if code_filter else None
        vector_ranks = {r["chunk_id"]: r["rank"] for r in self.vector_search(query, candidates, chunk_ids)}
        bm25_ranks = {r["chunk_id"]: r["rank"] for r in self.bm25_search(query, candidates, chunk_ids)}
        fused = {}
        for ranks in (vector_ranks, bm25_ranks):
            for chunk_id, rank in ranks.items():
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
        # Ties (e.g. vector #1 + BM25 #2 vs vector #2 + BM25 #1) go to the more trusted retriever: BM25 when the
        # query names a course code (exact match), vector otherwise; then chunk_id so results are deterministic
        primary = bm25_ranks if chunk_ids is not None else vector_ranks
        best = sorted(fused.items(), key=lambda item: (-item[1], primary.get(item[0], candidates + 1), item[0]))[:top_k]
        return [self._result(chunk_id, rank, score, vector_rank=vector_ranks.get(chunk_id),
                             bm25_rank=bm25_ranks.get(chunk_id), code_filtered=chunk_ids is not None)
                for rank, (chunk_id, score) in enumerate(best, 1)]

    def routed_search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Default retrieval. Queries naming a course code known to the index use code-aware hybrid search
        (vector embeddings carry little meaning for "MPG 704"); all other questions use vector search only,
        because BM25 fusion lowered the correct answer for some natural-language questions (see notebook Stage 4).
        """
        if self.chunks_with_codes(query):
            return [{**r, "route": "code_hybrid"} for r in self.hybrid_search(query, top_k)]
        return [{**r, "route": "vector"} for r in self.vector_search(query, top_k)]

    def query(self, query_text: str, top_k: int = 5, mode: str = "routed") -> List[Dict[str, Any]]:
        """mode: "routed" (default), "hybrid" (code-aware RRF for every query), "rrf" (plain RRF), "vector", "bm25"."""
        if mode == "rrf":
            return self.hybrid_search(query_text, top_k, code_filter=False)
        searches = {"routed": self.routed_search, "hybrid": self.hybrid_search,
                    "vector": self.vector_search, "bm25": self.bm25_search}
        return searches[mode](query_text, top_k)


# Example usage
if __name__ == "__main__":
    from src.data_loader import load_all_documents
    store = FaissVectorStore("faiss_store")
    if not os.path.exists(os.path.join("faiss_store", MANIFEST_FILE)):
        store.build_from_documents(load_all_documents())
    store.load()
    for question in ["What is HAWS 433 about?", "How do I defer my studies?"]:
        for result in store.query(question, top_k=3):
            print(result["route"], result["rank"], result["source"], "p.", result["page"], "|",
                  result["text"][:100].replace("\n", " "))
