"""Synthetic fixtures for the knowledge-base tests: no model downloads, no real indexes, temporary folders only."""
import hashlib
import itertools
import json
import re
from pathlib import Path

import faiss
import numpy as np

from src.heading_store import heading_fingerprint, index_text
from src.kb.config import EMBEDDING_REVISION, Actor, KBConfig
from src.kb.service import KnowledgeBase
from src.vectorstore import BM25_B, BM25_K1, corpus_fingerprint, vectors_checksum

MODEL = "BAAI/bge-small-en-v1.5"
DIM = 64
ADMIN = Actor("admin", {"kb_admin"})
UPLOADER = Actor("uploader", {"kb_uploader"})
APPROVER = Actor("approver", {"kb_approver"})
VISITOR = Actor("visitor", set())


def hash_vector(text: str, dim: int = DIM) -> np.ndarray:
    """Bag of hashed words (so texts sharing words are close) plus a tiny text-specific component."""
    v = np.zeros(dim, dtype="float64")
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % dim] += 1.0
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
    v += np.random.default_rng(seed).normal(0, 0.01, dim)
    return (v / np.linalg.norm(v)).astype("float32")


class HashEmbedder:
    model_name, revision, dim = MODEL, EMBEDDING_REVISION, DIM
    calls = 0

    def encode(self, texts):
        HashEmbedder.calls += len(texts)
        return np.stack([hash_vector(t) for t in texts])


class QueryEmbedder:
    """Stands in for EmbeddingPipeline.embed_query (the store's query side)."""
    def embed_query(self, query):
        return hash_vector(query)[None, :]


class FakeReranker:
    """Keeps retrieval order; same output fields as src.rerank.Reranker.rerank."""
    def __init__(self):
        self.calls = []

    def rerank(self, query, results, with_heading=False):
        self.calls.append((query, len(results), with_heading))
        return [{**r, "retrieval_rank": r["rank"], "rank": i, "rerank_score": float(len(results) - i)}
                for i, r in enumerate(results, 1)]


BASE_ROWS = [
    ("MSU Humanities Yearbook", "HUMANITIES test.pdf", 2, "Section: Council", "The Council shall be chaired by the chairman."),
    ("MSU Humanities Yearbook", "HUMANITIES test.pdf", 3, "Section: Council > Meetings", "At meetings the vice-chairman presides in the chairman's absence."),
    ("MSU Humanities Yearbook", "HUMANITIES test.pdf", 4, "", "HAWS 433 Water Resources Engineering module description."),
    ("MSU Humanities Yearbook", "HUMANITIES test.pdf", 5, "Section: Fees", "Tuition fees are payable before registration."),
    ("MSU Sciences Yearbook Vol. 2", "SCIENCES test.pdf", 7, "Section: Examinations", "Examinations are written at the end of each semester."),
    ("MSU Sciences Yearbook Vol. 2", "SCIENCES test.pdf", 8, "", "Students must attend at least eighty percent of lectures."),
    ("MSU Sciences Yearbook Vol. 2", "SCIENCES test.pdf", 9, "Section: Library", "The library opens at eight in the morning."),
]
BASE_DOCS = [{"doc_id": "yearbook-humanities", "title": "Humanities Yearbook", "source_label": "MSU Humanities Yearbook"},
             {"doc_id": "yearbook-sciences-v2", "title": "Sciences Yearbook Vol. 2",
              "source_label": "MSU Sciences Yearbook Vol. 2"}]


def make_frozen_store(path: Path) -> Path:
    """A miniature faiss_store_v2: same files, record schema, key order, CRLF line endings and manifest fields."""
    path.mkdir(parents=True)
    records = [{"chunk_id": i, "source": s, "file_name": f, "page": p, "text": f"[{s}, p. {p}]\n{body}", "heading": h}
               for i, (s, f, p, h, body) in enumerate(BASE_ROWS)]
    vectors = np.stack([hash_vector(index_text(r)) for r in records])
    with open(path / "chunks.jsonl", "wb") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False).encode("utf-8") + b"\r\n")
    index = faiss.IndexFlatIP(DIM)
    index.add(vectors)
    faiss.write_index(index, str(path / "index.faiss"))
    fp = corpus_fingerprint(records)
    config = {"embedding_model": MODEL, "embedding_dim": DIM, "normalized_embeddings": True,
              "query_prefix": "Represent this sentence for searching relevant passages: ", "chunk_size": 800,
              "chunk_overlap": 150}
    manifest = {"manifest_version": 1, "created_at": "2026-10-07T23:41:09+00:00", **config,
                "chunk_count": len(records), "chunks_per_source": {"MSU Humanities Yearbook": 4,
                                                                   "MSU Sciences Yearbook Vol. 2": 3},
                "corpus_fingerprint": fp, "build_fingerprint": "sha256:test", "vectors_checksum": vectors_checksum(vectors),
                "index_type": "IndexFlatIP", "faiss_version": faiss.__version__,
                "bm25": {"variant": "BM25Okapi", "k1": BM25_K1, "b": BM25_B, "tokenizer": "v1"},
                "structure_version": "v2", "heading_fingerprint": heading_fingerprint(records),
                "index_text": "citation header + heading line + chunk body; BM25: heading line + body; code filter: body only"}
    (path / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def make_pdf(path: Path, pages: int = 3, text: str = "Page") -> Path:
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 72), f"{text} {i + 1}")
    doc.save(str(path))
    doc.close()
    return path


def write_dataset(path: Path, groups: dict, source_sha: str = None) -> Path:
    data = {}
    for name, records in groups.items():
        data[name] = [{**r, **({"source_sha256": source_sha} if source_sha else {})} for r in records]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def event_records(n=3, word="roadmap"):
    return [{"id": f"RM-{i:02d}", "calendar_group": "Main", "semester": "First Semester", "activity": f"Activity {i}",
             "source_page": 1, "rag_text": f"ACTIVITY: {word} activity {i} runs in week {i}."} for i in range(1, n + 1)]


def programme_records(n=4, word="zyxintake"):
    return [{"id": f"PR-{i:03d}", "faculty": "Faculty of Testing", "programme": f"Programme {i}", "source_page": 2,
             "rag_text": f"PROGRAMME: {word} programme {i} requires ZQX 101 and two A level passes."}
            for i in range(1, n + 1)]


def group_spec(name, heading, unit_type, page="source_page"):
    return {"name": name, "path": name, "id": "id", "text": "rag_text", "page": page, "heading": heading,
            "unit_type": unit_type}


def make_kb(root: Path, **cfg) -> KnowledgeBase:
    counter = itertools.count(1)

    def clock():
        n = next(counter)
        return f"2026-10-13T{10 + n // 3600:02d}:{n // 60 % 60:02d}:{n % 60:02d}+00:00"
    config = KBConfig(root=root, clock=clock, io_retry_delay_s=0.01, **{"profile": "development", **cfg})
    return KnowledgeBase(config, embedder_factory=HashEmbedder, token_counter=lambda t: len(t.split()))


class World:
    """A seeded knowledge base with a frozen base, a roadmap-like and an intake-like document registered."""

    def __init__(self, tmp: Path, **cfg):
        self.tmp = tmp
        self.frozen = make_frozen_store(tmp / "frozen_v2")
        self.kb = make_kb(tmp / "kb", **cfg)
        self.kb.seed_base(self.frozen, BASE_DOCS, ADMIN)
        self.road_pdf = make_pdf(tmp / "ROADMAP DRAFT.pdf", 1)
        self.intake_pdf = make_pdf(tmp / "INTAKE.pdf", 3)
        from src.kb.fsutil import sha256_file
        self.road_json = write_dataset(tmp / "roadmap.json", {"events": event_records()}, sha256_file(self.road_pdf))
        self.intake_json = write_dataset(tmp / "intake.json", {"programmes": programme_records(),
                                                               "information_records": [
            {"id": "INFO-01", "topic": "fee", "source_page": 3,
             "rag_text": "TOPIC: Application fee is US$10 for local zyxintake applicants."}]},
            sha256_file(self.intake_pdf))
        self.road_meta = {"doc_id": "roadmap-test", "title": "Test Road Map", "source_label": "MSU Test Road Map",
                          "adapter": "json_records",
                          "adapter_options": {"groups": [group_spec("events", ["calendar_group", "semester", "activity"],
                                                                    "roadmap_event")],
                                              "source_sha256_field": "source_sha256"},
                          "correction_history": [{"event_id": "RM-02", "dates_in_source": "13/09/2026",
                                                  "approved_dates": "13/09/2027"}],
                          "excluded_units": {"semester_summaries": {"count": 4, "reason": "kept for evaluation"}}}
        self.intake_meta = {"doc_id": "intake-test", "title": "Test Intake", "source_label": "MSU Test Intake Advert",
                            "adapter": "json_records",
                            "adapter_options": {"groups": [group_spec("programmes", ["faculty", "programme"], "programme"),
                                                           group_spec("information_records", ["topic"], "information")],
                                                "source_sha256_field": "source_sha256"}}

    def register_both(self):
        self.kb.register_upload(self.road_json, self.road_meta, UPLOADER, source_file=self.road_pdf)
        self.kb.register_upload(self.intake_json, self.intake_meta, UPLOADER, source_file=self.intake_pdf)

    def stage_both(self):
        self.register_both()
        for doc in ("roadmap-test", "intake-test"):
            assert self.kb.validate(doc, 1, UPLOADER)["ok"]
            self.kb.stage(doc, 1, UPLOADER)

    def publish_roadmap_only(self):
        self.stage_both()
        self.kb.approve("roadmap-test", 1, APPROVER, basis="Owner confirmed the corrected road map.",
                        decision_date="2026-10-13", registry_verification="not performed")
        return self.kb.publish(APPROVER)


def open_store(kb, kind):
    from src.kb.versions import open_pointer
    store = open_pointer(kb.cfg, kind)
    store._embedder = QueryEmbedder()
    return store
