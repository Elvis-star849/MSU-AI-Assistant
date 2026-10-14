"""
Building, publishing and retaining store versions.

A version is built in store/versions/.tmp-<op>/, flushed to disk, verified by opening it with KBStore, and only then
renamed to store/versions/NNNN. Pointers (CURRENT = public, STAGING = staging) are small JSON files replaced
atomically; each names a version and the SHA-256 of its manifest. Builds contain no timestamps, so the same inputs
give the same files.
"""
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np

from src.heading_store import HeadingAwareStore, heading_fingerprint, index_text
from src.kb import fsutil
from src.kb.config import KBConfig
from src.kb.errors import IntegrityError
from src.kb.fsutil import canonical_json, read_json, sha256_bytes, sha256_file
from src.kb.ids import base_record_id, passage_uid, record_key
from src.kb.store import (KB_FORMAT_VERSION, PASSAGES_FILE, SNAPSHOT_FILE, KBStore, bm25_corpus_fingerprint,
                          content_fingerprint, raw_lines)
from src.vectorstore import CHUNKS_FILE, INDEX_FILE, MANIFEST_FILE, corpus_fingerprint, vectors_checksum

POINTERS = {"public": "CURRENT", "staging": "STAGING"}
# Existing manifest fields carried over from the frozen base unchanged (they describe the embedding/BM25 setup)
CARRIED_FIELDS = ("embedding_model", "embedding_dim", "normalized_embeddings", "query_prefix", "chunk_size",
                  "chunk_overlap", "bm25", "structure_version", "index_text")
RECORD_KEYS = ("chunk_id", "source", "file_name", "page", "text", "heading")   # key order of faiss_store_v2 lines


# ------------------------------------------------------------------ base material

class BaseMaterial:
    """The frozen yearbook block: raw chunk lines, parsed records, vectors, identifier rows, manifest fields."""

    def __init__(self, raw: bytes, records, vectors, passages, fields, line_ending: bytes, source: str):
        self.raw, self.records, self.vectors, self.passages = raw, records, vectors, passages
        self.fields, self.line_ending, self.source = fields, line_ending, source

    @property
    def count(self) -> int:
        return len(self.records)

    @classmethod
    def from_frozen(cls, store_dir: Path, base_entries: List[Dict[str, Any]],
                    expected_fingerprint: Optional[str] = None) -> "BaseMaterial":
        """Read a frozen heading-aware store (faiss_store_v2) through its own verified loader."""
        store = HeadingAwareStore(str(store_dir))
        try:
            store.load(expected_fingerprint=expected_fingerprint)
        except ValueError as e:
            raise IntegrityError(f"frozen base {store_dir} failed verification: {e}") from e
        raw = Path(store_dir, CHUNKS_FILE).read_bytes()
        if raw.count(b"\n") != len(store.records):
            raise IntegrityError("frozen chunks.jsonl line count differs from its records")
        passages = []
        for e in base_entries:
            a, b = e["base_range"]
            for i in range(a, b + 1):
                rid = base_record_id(i)
                passages.append({"chunk_id": i, "passage_uid": passage_uid(e["doc_id"], e["doc_version"], rid),
                                 "record_key": record_key(e["doc_id"], rid), "doc_id": e["doc_id"],
                                 "doc_version": e["doc_version"], "record_id": rid, "unit_type": "yearbook"})
        if [p["chunk_id"] for p in passages] != list(range(len(store.records))):
            raise IntegrityError("base document ranges do not cover the frozen store exactly once, in order")
        fields = {k: store.manifest[k] for k in CARRIED_FIELDS if k in store.manifest}
        ending = b"\r\n" if raw.endswith(b"\r\n") else b"\n"
        return cls(raw, store.records, store.index.reconstruct_n(0, store.index.ntotal), passages, fields, ending,
                   str(store_dir))

    @classmethod
    def from_version(cls, version_dir: Path) -> "BaseMaterial":
        store = KBStore(version_dir).load(verify_bm25=False)
        n = store.kb["base"]["chunk_count"]
        raw = raw_lines(version_dir / CHUNKS_FILE, n)
        fields = {k: store.manifest[k] for k in CARRIED_FIELDS if k in store.manifest}
        ending = b"\r\n" if raw.endswith(b"\r\n") else b"\n"
        return cls(raw, store.records[:n], store.index.reconstruct_n(0, n), store.passages[:n], fields, ending,
                   str(version_dir))


# ------------------------------------------------------------------ version ids and pointers

def _version_numbers(cfg: KBConfig) -> List[int]:
    nums = []
    for d in (cfg.versions_dir, cfg.archive_dir, cfg.quarantine_dir):
        if d.is_dir():
            for p in d.iterdir():
                head = p.name.split(".")[0]
                if head.isdigit():
                    nums.append(int(head))
    return nums


def next_version_id(cfg: KBConfig) -> str:
    return f"{max(_version_numbers(cfg), default=0) + 1:04d}"


def read_pointer(cfg: KBConfig, kind: str) -> Optional[Dict[str, Any]]:
    path = cfg.store_dir / POINTERS[kind]
    return read_json(path) if path.is_file() else None


def write_pointer(cfg: KBConfig, kind: str, version_id: str) -> Dict[str, Any]:
    vdir = cfg.versions_dir / version_id
    manifest = read_json(vdir / MANIFEST_FILE)
    if manifest["kb"]["kind"] != kind:
        raise IntegrityError(f"version {version_id} is {manifest['kb']['kind']}, cannot be the {kind} pointer")
    pointer = {"version": version_id, "kind": kind, "manifest_sha256": sha256_file(vdir / MANIFEST_FILE)}
    fsutil.atomic_write_json(cfg.store_dir / POINTERS[kind], pointer, retries=cfg.io_retries,
                             delay_s=cfg.io_retry_delay_s)
    return pointer


def open_pointer(cfg: KBConfig, kind: str, verify_bm25: bool = True) -> KBStore:
    pointer = read_pointer(cfg, kind)
    if pointer is None:
        raise IntegrityError(f"no {POINTERS[kind]} version has been published")
    if pointer.get("kind") != kind:
        raise IntegrityError(f"{POINTERS[kind]} pointer names a {pointer.get('kind')} version")
    store = KBStore(cfg.versions_dir / pointer["version"], filter_method=cfg.filter_method)
    return store.load(expected_kind=kind, manifest_sha256=pointer["manifest_sha256"], verify_bm25=verify_bm25)


def version_manifest(cfg: KBConfig, version_id: str) -> Dict[str, Any]:
    return read_json(cfg.versions_dir / version_id / MANIFEST_FILE)


# ------------------------------------------------------------------ building

def load_units(cfg: KBConfig, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    path = cfg.root / entry["units"]["path"]
    if sha256_file(path) != entry["units"]["sha256"]:
        raise IntegrityError(f"{path} does not match the registry's units_sha256")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def content_signature(kind: str, base: BaseMaterial, documents: List[Dict[str, Any]], snapshot_sha: str) -> str:
    """Identifies what a version contains (not its number or parent): used to make rebuilds no-ops."""
    return "sha256:" + sha256_bytes(canonical_json({"kind": kind, "base": sha256_bytes(base.raw),
                                                    "documents": documents, "snapshot": snapshot_sha}))


def plan_version(cfg: KBConfig, kind: str, entries: List[Dict[str, Any]], base: BaseMaterial, cache):
    """Assemble rows, identifiers, vectors and per-document metadata (in memory; nothing is written)."""
    records, passages = list(base.records), list(base.passages)
    vectors = [base.vectors]
    docs = []
    base_entries = [e for e in entries if e.get("base")]
    for e in base_entries:
        a, b = e["base_range"]
        docs.append({"doc_id": e["doc_id"], "doc_version": e["doc_version"], "status": e["status"], "base": True,
                     "chunk_range": [a, b], "passages": b - a + 1,
                     "content_fingerprint": content_fingerprint(records[a:b + 1], passages[a:b + 1]),
                     "vectors_checksum": vectors_checksum(base.vectors[a:b + 1])})
    if sum(d["passages"] for d in docs) != base.count:
        raise IntegrityError("base documents in the registry do not cover the base block")
    for e in entries:
        if e.get("base"):
            continue
        units = load_units(cfg, e)
        start = len(records)
        doc_vectors = cache.vectors_for([index_text(u) for u in units])
        new_records, new_passages = [], []
        for offset, u in enumerate(units):
            new_records.append({"chunk_id": start + offset, "source": u["source"], "file_name": u["file_name"],
                                "page": u["page"], "text": u["text"], "heading": u["heading"]})
            new_passages.append({"chunk_id": start + offset,
                                 "passage_uid": passage_uid(e["doc_id"], e["doc_version"], u["record_id"]),
                                 "record_key": record_key(e["doc_id"], u["record_id"]), "doc_id": e["doc_id"],
                                 "doc_version": e["doc_version"], "record_id": u["record_id"],
                                 "unit_type": u["unit_type"]})
        records += new_records
        passages += new_passages
        vectors.append(doc_vectors)
        docs.append({"doc_id": e["doc_id"], "doc_version": e["doc_version"], "status": e["status"], "base": False,
                     "chunk_range": [start, start + len(units) - 1], "passages": len(units),
                     "units_sha256": e["units"]["sha256"],
                     "content_fingerprint": content_fingerprint(new_records, new_passages),
                     "vectors_checksum": vectors_checksum(doc_vectors)})
    return records, passages, np.concatenate(vectors).astype("float32"), docs


def build_version(cfg: KBConfig, *, kind: str, entries: List[Dict[str, Any]], base: BaseMaterial, cache,
                  version_id: str, parent: Optional[str], op_id: str, seed: bool = False,
                  copy_index_from: Optional[Path] = None) -> Tuple[str, str]:
    """Write, verify and number a version. Returns (version_id, manifest_sha256)."""
    records, passages, vectors, docs = plan_version(cfg, kind, entries, base, cache)
    snapshot = {"kind": kind, "documents": entries}
    snapshot_bytes = canonical_json(snapshot)
    passages_bytes = b"".join((json.dumps(p, ensure_ascii=False) + "\n").encode("utf-8") for p in passages)
    new_lines = b"".join(json.dumps({k: r[k] for k in RECORD_KEYS}, ensure_ascii=False).encode("utf-8")
                         + base.line_ending for r in records[base.count:])
    fields = base.fields
    corpus_fp = corpus_fingerprint(records)
    config = {k: fields[k] for k in ("embedding_model", "embedding_dim", "normalized_embeddings", "query_prefix",
                                     "chunk_size", "chunk_overlap")}
    sources: Dict[str, int] = {}
    for r in records:
        sources[r["source"]] = sources.get(r["source"], 0) + 1
    manifest = {
        "manifest_version": 1, **config, "chunk_count": len(records), "chunks_per_source": sources,
        "corpus_fingerprint": corpus_fp,
        "build_fingerprint": "sha256:" + sha256_bytes(json.dumps({"corpus": corpus_fp, **config},
                                                                sort_keys=True).encode("utf-8")),
        "vectors_checksum": vectors_checksum(vectors), "index_type": "IndexFlatIP",
        "faiss_version": faiss.__version__, "bm25": fields.get("bm25"),
        "structure_version": fields.get("structure_version"), "heading_fingerprint": heading_fingerprint(records),
        "index_text": fields.get("index_text"),
        "kb": {
            "format_version": KB_FORMAT_VERSION, "kind": kind, "version": version_id, "parent": parent,
            "seed": seed,
            "base": {"chunk_count": base.count, "chunks_sha256": sha256_bytes(base.raw),
                     "corpus_fingerprint": corpus_fingerprint(base.records),
                     "heading_fingerprint": heading_fingerprint(base.records),
                     "vectors_checksum": vectors_checksum(base.vectors)},
            "documents": docs,
            "passages_sha256": sha256_bytes(passages_bytes),
            "registry_snapshot_sha256": sha256_bytes(snapshot_bytes),
            "bm25_corpus_fingerprint": bm25_corpus_fingerprint(records),
            "inactive_chunk_ids": [],
            "embedding": {"model": cfg.embedding_model, "revision": cfg.embedding_revision,
                          "recipe": cfg.embedding_recipe},
        },
    }
    manifest["kb"]["content_signature"] = content_signature(kind, base, docs, manifest["kb"]["registry_snapshot_sha256"])

    tmp = cfg.versions_dir / f".tmp-{op_id}"
    tmp.mkdir(parents=True, exist_ok=False)
    with open(tmp / CHUNKS_FILE, "wb") as f:
        f.write(base.raw)
        f.write(new_lines)
    (tmp / PASSAGES_FILE).write_bytes(passages_bytes)
    (tmp / SNAPSHOT_FILE).write_bytes(snapshot_bytes)
    if copy_index_from is not None and len(records) == base.count:
        shutil.copyfile(copy_index_from, tmp / INDEX_FILE)
    else:
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(np.ascontiguousarray(vectors))
        faiss.write_index(index, str(tmp / INDEX_FILE))
    (tmp / MANIFEST_FILE).write_bytes(canonical_json(manifest))
    for name in (CHUNKS_FILE, PASSAGES_FILE, SNAPSHOT_FILE, INDEX_FILE, MANIFEST_FILE):
        fsutil.fsync_file(tmp / name)
    fsutil.crash_point("version_files_written")
    KBStore(tmp).load(expected_kind=kind)                 # full verification before the version gets a number
    fsutil.crash_point("version_verified")
    final = cfg.versions_dir / version_id
    fsutil.rename_dir(tmp, final, cfg.io_retries, cfg.io_retry_delay_s)
    return version_id, sha256_file(final / MANIFEST_FILE)


# ------------------------------------------------------------------ retention

def apply_retention(cfg: KBConfig) -> List[str]:
    """Keep the seed (base) version, the newest `retention_public` public versions and every pointer target;
    move other versions to archive/ (never deleted)."""
    if not cfg.versions_dir.is_dir():
        return []
    pinned = {p["version"] for p in (read_pointer(cfg, "public"), read_pointer(cfg, "staging")) if p}
    public, staging = [], []
    for d in sorted(cfg.versions_dir.iterdir()):
        if not d.is_dir() or not d.name.isdigit():
            continue
        kb = read_json(d / MANIFEST_FILE)["kb"]
        if kb.get("seed"):
            pinned.add(d.name)
        (public if kb["kind"] == "public" else staging).append(d.name)
    keep = pinned | set(sorted(public)[-cfg.retention_public:])
    moved = []
    for name in public + staging:
        if name not in keep:
            fsutil.rename_dir(cfg.versions_dir / name, cfg.archive_dir / name, cfg.io_retries, cfg.io_retry_delay_s)
            moved.append(name)
    return moved
