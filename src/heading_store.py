"""
S6-3 heading-aware index (faiss_store_v2/).

Same chunks, chunk_ids and chunk text as the frozen faiss_store/ (so its corpus fingerprint is identical); each record
also carries a "heading" line from src/structure.py. Only what retrieval indexes changes:
  embedding text = citation header + heading line + chunk body
  BM25 tokens    = heading line + chunk body
The code filter (which chunks mention a course code) still reads the chunk body only, so routing is unchanged.
"""
import hashlib
import json
import time
from typing import Any, Dict, List, Optional

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from src.structure import STRUCTURE_VERSION, assign_headings, heading_line
from src.vectorstore import (BM25_B, BM25_K1, _CITATION_HEADER, FaissVectorStore, bm25_tokenize,
                             course_codes)


def heading_fingerprint(records: List[Dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for r in records:
        digest.update(json.dumps([r["chunk_id"], r["heading"]], ensure_ascii=False).encode("utf-8") + b"\n")
    return "sha256:" + digest.hexdigest()


def index_text(record: Dict[str, Any]) -> str:
    """What gets embedded: the chunk with its heading line inserted after the citation header."""
    header = _CITATION_HEADER.match(record["text"])
    body = record["text"][header.end():] if header else record["text"]
    head = header.group(0) if header else ""
    return f"{head}{record['heading']}\n{body}" if record["heading"] else record["text"]


class HeadingAwareStore(FaissVectorStore):
    def build_from_records(self, records: List[Dict[str, Any]], batch_size: int = 32):
        """Add headings to existing chunk records, embed heading + text, and build the FAISS and BM25 indexes."""
        start = time.perf_counter()
        headings = assign_headings(records)
        self.records = [{**r, "heading": heading_line(h)} for r, h in zip(records, headings)]
        self.timings["headings_s"] = time.perf_counter() - start

        start = time.perf_counter()
        embeddings = self.embedder.model.encode([index_text(r) for r in self.records], batch_size=batch_size,
                                                show_progress_bar=False, normalize_embeddings=True).astype("float32")
        self.timings["embed_s"] = time.perf_counter() - start

        self.index = faiss.IndexFlatIP(embeddings.shape[1])
        self.index.add(embeddings)
        self.manifest = self._make_manifest(embeddings)
        self.manifest.update({"structure_version": STRUCTURE_VERSION,
                              "heading_fingerprint": heading_fingerprint(self.records),
                              "index_text": "citation header + heading line + chunk body; BM25: heading line + body; "
                                            "code filter: body only"})
        self._build_bm25()

    def _build_bm25(self):
        start = time.perf_counter()
        bodies = [_CITATION_HEADER.sub("", r["text"], count=1) for r in self.records]
        self.bm25 = BM25Okapi([bm25_tokenize(f"{r.get('heading', '')}\n{body}")
                               for r, body in zip(self.records, bodies)], k1=BM25_K1, b=BM25_B)
        self.code_to_chunks = {}
        for chunk_id, body in enumerate(bodies):
            for code in course_codes(body, uppercase_only=True):
                self.code_to_chunks.setdefault(code, []).append(chunk_id)
        self.timings["bm25_build_s"] = time.perf_counter() - start

    def load(self, expected_fingerprint: Optional[str] = None):
        """Base checks (files, counts, corpus fingerprint, vectors) plus the headings' fingerprint and version."""
        super().load(expected_fingerprint)
        problems = []
        if any("heading" not in r for r in self.records):
            problems.append("chunk records lack the heading field")
        elif heading_fingerprint(self.records) != self.manifest.get("heading_fingerprint"):
            problems.append("headings do not match the manifest's heading fingerprint")
        if self.manifest.get("structure_version") != STRUCTURE_VERSION:
            problems.append(f"structure_version: index has {self.manifest.get('structure_version')!r}, "
                            f"code is {STRUCTURE_VERSION!r}")
        if problems:
            raise ValueError("Heading-aware index failed verification:\n  - " + "\n  - ".join(problems))
