"""
KBStore: one knowledge-base store version (knowledge_base/store/versions/NNNN), opened with the accepted
HeadingAwareStore loader and then verified against the version's "kb" manifest block.

Files of a version:
  index.faiss             FAISS IndexFlatIP (row i = chunk_id i)
  chunks.jsonl            unchanged record schema: chunk_id, source, file_name, page, text, heading
                          (the first base.chunk_count lines are a byte-for-byte copy of faiss_store_v2/chunks.jsonl)
  passages.jsonl          external identifiers per row: chunk_id, passage_uid, record_key, doc_id, doc_version,
                          record_id, unit_type
  registry_snapshot.json  the registry entries this version contains
  manifest.json           existing manifest fields + "kb"

Search-time filter (safeguard; empty in correctly built versions): rows listed in kb.inactive_chunk_ids are excluded
from vector search (FAISS IDSelector, or over-fetch + filter), BM25 and the course-code map.
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import faiss
import numpy as np

from src.heading_store import HeadingAwareStore, heading_fingerprint
from src.kb.errors import IntegrityError
from src.kb.fsutil import read_json, sha256_bytes, sha256_file
from src.kb.states import visible_in
from src.vectorstore import (BM25_B, BM25_K1, CHUNKS_FILE, MANIFEST_FILE, _CITATION_HEADER, bm25_tokenize,
                             corpus_fingerprint, vectors_checksum)

PASSAGES_FILE = "passages.jsonl"
SNAPSHOT_FILE = "registry_snapshot.json"
KB_FORMAT_VERSION = 1


def content_fingerprint(records: List[Dict[str, Any]], passages: List[Dict[str, Any]]) -> str:
    """Position-independent fingerprint of one document's rows (record_id, source, file, page, heading, text)."""
    digest = hashlib.sha256()
    for r, p in zip(records, passages):
        row = [p["record_id"], r["source"], r.get("file_name"), r.get("page"), r.get("heading", ""), r["text"]]
        digest.update(json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n")
    return "sha256:" + digest.hexdigest()


def bm25_corpus_fingerprint(records: List[Dict[str, Any]]) -> str:
    """Fingerprint of exactly what HeadingAwareStore._build_bm25 indexes (heading line + body tokens) and its
    parameters, so a version's BM25 statistics are tied to its own records."""
    digest = hashlib.sha256(json.dumps({"variant": "BM25Okapi", "k1": BM25_K1, "b": BM25_B,
                                        "tokenizer": "v1"}).encode("utf-8"))
    for r in records:
        body = _CITATION_HEADER.sub("", r["text"], count=1)
        digest.update(json.dumps(bm25_tokenize(f"{r.get('heading', '')}\n{body}")).encode("utf-8") + b"\n")
    return "sha256:" + digest.hexdigest()


def raw_lines(path: Path, n: int) -> bytes:
    """The first n lines of a file as raw bytes (line endings included)."""
    out = bytearray()
    with open(path, "rb") as f:
        for _ in range(n):
            line = f.readline()
            if not line:
                raise IntegrityError(f"{path} has fewer than {n} lines")
            out += line
    return bytes(out)


class KBStore(HeadingAwareStore):
    def __init__(self, version_dir, filter_method: str = "selector", **kwargs):
        super().__init__(str(version_dir), **kwargs)
        self.version_dir = Path(version_dir)
        self.filter_method = filter_method
        self.passages: List[Dict[str, Any]] = []
        self.snapshot: Dict[str, Any] = {}
        self.inactive = np.zeros(0, dtype="int64")
        self._inactive_set = frozenset()
        self._uid_to_row: Dict[str, int] = {}

    @property
    def kb(self) -> Dict[str, Any]:
        return self.manifest["kb"]

    # ------------------------------------------------------------------ load + verify
    def load(self, expected_kind: Optional[str] = None, manifest_sha256: Optional[str] = None,
             verify_bm25: bool = True):
        manifest_path = self.version_dir / MANIFEST_FILE
        if manifest_sha256 is not None and sha256_file(manifest_path) != manifest_sha256:
            raise IntegrityError(f"{manifest_path} does not match the pointer's manifest_sha256")
        try:
            super().load()                     # existing checks: files, counts, model, fingerprints, vectors
        except ValueError as e:
            raise IntegrityError(str(e)) from e
        self._verify_kb(expected_kind, verify_bm25)
        inactive = sorted(set(self.kb.get("inactive_chunk_ids") or []))
        self.inactive = np.asarray(inactive, dtype="int64")
        self._inactive_set = frozenset(inactive)
        self._uid_to_row = {p["passage_uid"]: i for i, p in enumerate(self.passages)}
        return self

    def _verify_kb(self, expected_kind: Optional[str], verify_bm25: bool) -> None:
        problems = []
        kb = self.manifest.get("kb")
        if not kb or kb.get("format_version") != KB_FORMAT_VERSION:
            raise IntegrityError(f"{self.version_dir}: not a knowledge-base version (no kb block)")
        if expected_kind and kb.get("kind") != expected_kind:
            raise IntegrityError(f"{self.version_dir}: kind {kb.get('kind')!r}, expected {expected_kind!r}")
        n = len(self.records)

        passages_path = self.version_dir / PASSAGES_FILE
        if sha256_file(passages_path) != kb.get("passages_sha256"):
            problems.append("passages.jsonl does not match the manifest")
        with open(passages_path, encoding="utf-8") as f:
            self.passages = [json.loads(line) for line in f]
        if [p.get("chunk_id") for p in self.passages] != list(range(n)):
            problems.append("passages.jsonl rows do not match the chunk records")
        uids = [p.get("passage_uid") for p in self.passages]
        if len(set(uids)) != len(uids):
            problems.append("duplicate passage_uid")

        snapshot_path = self.version_dir / SNAPSHOT_FILE
        if sha256_file(snapshot_path) != kb.get("registry_snapshot_sha256"):
            problems.append("registry_snapshot.json does not match the manifest")
        self.snapshot = read_json(snapshot_path)
        if self.snapshot.get("kind") != kb.get("kind"):
            problems.append("registry snapshot kind differs from the manifest")
        snap_status = {(d["doc_id"], d["doc_version"]): d["status"] for d in self.snapshot.get("documents", [])}

        base = kb["base"]
        nb = base["chunk_count"]
        if nb > n:
            problems.append("base block larger than the store")
        else:
            if sha256_bytes(raw_lines(self.version_dir / CHUNKS_FILE, nb)) != base["chunks_sha256"]:
                problems.append("base chunk lines are not byte-identical to the frozen base")
            if corpus_fingerprint(self.records[:nb]) != base["corpus_fingerprint"]:
                problems.append("base corpus fingerprint differs")
            if heading_fingerprint(self.records[:nb]) != base["heading_fingerprint"]:
                problems.append("base heading fingerprint differs")
        vectors = self.index.reconstruct_n(0, self.index.ntotal)
        if nb <= n and vectors_checksum(vectors[:nb]) != base["vectors_checksum"]:
            problems.append("base vectors differ")

        expected_start = 0
        for d in kb["documents"]:
            a, b = d["chunk_range"]
            if a != expected_start or b < a - 1 or b - a + 1 != d["passages"]:
                problems.append(f"{d['doc_id']}: chunk_range {d['chunk_range']} is not contiguous")
                break
            expected_start = b + 1
            rows, maps = self.records[a:b + 1], self.passages[a:b + 1]
            if any((p["doc_id"], p["doc_version"]) != (d["doc_id"], d["doc_version"]) for p in maps):
                problems.append(f"{d['doc_id']}: passages.jsonl rows belong to another document")
            if content_fingerprint(rows, maps) != d["content_fingerprint"]:
                problems.append(f"{d['doc_id']}: content fingerprint differs")
            if vectors_checksum(vectors[a:b + 1]) != d["vectors_checksum"]:
                problems.append(f"{d['doc_id']}: vectors differ")
            if not visible_in(kb["kind"], d["status"]):
                problems.append(f"{d['doc_id']}: status {d['status']!r} is not allowed in a {kb['kind']} version")
            if snap_status.get((d["doc_id"], d["doc_version"])) != d["status"]:
                problems.append(f"{d['doc_id']}: status differs between manifest and registry snapshot")
        if expected_start != n:
            problems.append(f"documents cover {expected_start} rows, store has {n}")
        if len(snap_status) != len(kb["documents"]):
            problems.append("registry snapshot lists a different set of documents")
        if verify_bm25 and bm25_corpus_fingerprint(self.records) != kb.get("bm25_corpus_fingerprint"):
            problems.append("BM25 corpus fingerprint differs")
        if any(not (0 <= i < n) for i in kb.get("inactive_chunk_ids") or []):
            problems.append("inactive_chunk_ids out of range")
        if problems:
            raise IntegrityError(f"{self.version_dir} failed knowledge-base verification:\n  - " + "\n  - ".join(problems))

    # ------------------------------------------------------------------ identifiers
    def passage(self, chunk_id: int) -> Dict[str, Any]:
        return self.passages[chunk_id]

    def row_of(self, passage_uid: str) -> int:
        return self._uid_to_row[passage_uid]

    def _result(self, idx: int, rank: int, score: float, **extra) -> Dict[str, Any]:
        return super()._result(idx, rank, score, passage_uid=self.passages[idx]["passage_uid"], **extra)

    # ------------------------------------------------------------------ search with the inactive filter
    def vector_search(self, query: str, top_k: int = 5, chunk_ids: Optional[List[int]] = None):
        if not self._inactive_set:
            return super().vector_search(query, top_k, chunk_ids)
        allowed = None if chunk_ids is None else np.asarray(
            [i for i in chunk_ids if i not in self._inactive_set], dtype="int64")
        if allowed is not None and allowed.size == 0:
            return []
        q = self.embedder.embed_query(query)
        if self.filter_method == "selector":
            inner = faiss.IDSelectorBatch(allowed) if allowed is not None else faiss.IDSelectorBatch(self.inactive)
            sel = inner if allowed is not None else faiss.IDSelectorNot(inner)
            scores, ids = self.index.search(q, top_k, params=faiss.SearchParameters(sel=sel))
            hits = [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i >= 0]
        else:
            params = None
            if allowed is not None:
                sel = faiss.IDSelectorBatch(allowed)
                params = faiss.SearchParameters(sel=sel)
            k = top_k if allowed is not None else top_k + len(self.inactive)
            scores, ids = self.index.search(q, min(k, self.index.ntotal), params=params)
            hits = [(int(i), float(s)) for i, s in zip(ids[0], scores[0])
                    if i >= 0 and int(i) not in self._inactive_set][:top_k]
        return [self._result(i, rank, s) for rank, (i, s) in enumerate(hits, 1)]

    def bm25_search(self, query: str, top_k: int = 5, chunk_ids: Optional[List[int]] = None):
        if not self._inactive_set:
            return super().bm25_search(query, top_k, chunk_ids)
        scores = self.bm25.get_scores(bm25_tokenize(query)).astype(float)
        scores[self.inactive] = -np.inf
        ids = np.arange(len(scores)) if chunk_ids is None else np.asarray(chunk_ids)
        top = ids[np.argsort(-scores[ids], kind="stable")][:top_k]
        return [self._result(int(i), rank, float(scores[i])) for rank, i in enumerate(top, 1) if scores[i] > 0]

    def chunks_with_codes(self, query: str):
        ids = super().chunks_with_codes(query)
        if ids is None or not self._inactive_set:
            return ids
        ids = [i for i in ids if i not in self._inactive_set]
        return ids or None
