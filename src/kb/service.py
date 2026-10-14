"""
KnowledgeBase: the user-interface-independent service API. The CLI, the v3 notebook and a future Django admin call
only these methods; none of them touches files directly.

Every write operation:
  1. takes the single-writer lock and recovers from any interrupted earlier operation;
  2. writes a journal "begin" entry (with the intended registry state and pointer change, if any);
  3. builds and verifies a new version (if the operation changes what an index contains);
  4. switches at most one pointer atomically, then saves the registry atomically;
  5. writes a journal "commit" entry.
If the process dies between 2 and 5, recovery completes the operation when its pointer was already switched (the
version is complete and verified) and aborts it otherwise, moving unreferenced files to quarantine/.
"""
import copy
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from src.heading_store import index_text
from src.kb import fsutil, states
from src.kb.adapters import get_adapter
from src.kb.config import ROLE_ADMIN, ROLE_APPROVER, ROLE_UPLOADER, Actor, KBConfig
from src.kb.embeddings import EmbeddingCache, SentenceTransformerEmbedder
from src.kb.errors import (DuplicateDocument, IntegrityError, InvalidTransition, KBError, OverrideActive,
                           PermissionDenied, ReinstatementRequired, UnknownDocument, ValidationFailed)
from src.kb.fsutil import canonical_json, read_json, sha256_file
from src.kb.ids import check_doc_id, doc_key
from src.kb.journal import Journal
from src.kb.lock import WriterLock, force_unlock
from src.kb.registry import (JsonRegistry, RegistryBackend, clone, find, find_by_sha, ordered_for_build,
                             state_sha256)
from src.kb.validate import text_key, validate_units
from src.kb.versions import (POINTERS, BaseMaterial, apply_retention, build_version, next_version_id,
                             open_pointer, read_pointer, version_manifest, write_pointer)
from src.vectorstore import CHUNKS_FILE, INDEX_FILE

META_REQUIRED = ("doc_id", "title", "source_label", "adapter")
META_OPTIONAL = ("adapter_options", "valid_for", "correction_history", "excluded_units", "notes", "prior_approval")
# A decision taken before the document entered the knowledge base (e.g. the owner's confirmation of the 2027 road
# map). It is evidence only: the formal approval still happens after staging, through approve().
PRIOR_APPROVAL_REQUIRED = ("actor", "decision", "decision_date", "basis")
# Fields update_metadata() may change (only while a document version is uploaded or validated)
META_UPDATABLE = ("title", "source_label", "adapter", "adapter_options", "valid_for", "correction_history",
                  "excluded_units", "notes", "prior_approval")


class KnowledgeBase:
    def __init__(self, config: KBConfig, registry: Optional[RegistryBackend] = None,
                 embedder_factory: Optional[Callable] = None, token_counter: Optional[Callable[[str], int]] = None):
        self.cfg = config
        self.registry = registry or JsonRegistry(config.registry_path, config.io_retries, config.io_retry_delay_s)
        self.journal = Journal(config.journal_path)
        self._embedder_factory = embedder_factory or (
            lambda: SentenceTransformerEmbedder(config.embedding_model, config.embedding_revision))
        self._token_counter = token_counter
        self.cache = EmbeddingCache(config.embeddings_dir, config.embedding_model, config.embedding_revision,
                                    config.embedding_recipe)
        self.last_recovery: Dict[str, Any] = {}

    # ================================================================== helpers
    def token_counter(self) -> Callable[[str], int]:
        if self._token_counter is None:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            from transformers import AutoTokenizer
            tok = AutoTokenizer.from_pretrained(self.cfg.embedding_model, revision=self.cfg.embedding_revision)
            self._token_counter = lambda text: len(tok(text)["input_ids"])
        return self._token_counter

    @staticmethod
    def _require(actor: Actor, *roles: str) -> None:
        if not isinstance(actor, Actor) or not actor.has_any(*roles):
            raise PermissionDenied(f"{getattr(actor, 'name', actor)!r} needs one of {sorted(roles)} (or {ROLE_ADMIN})")

    def _now(self) -> str:
        return self.cfg.clock()

    def _set_status(self, entry: Dict[str, Any], new: str, actor: Actor, reason: str,
                    reinstatement: bool = False) -> None:
        states.check_transition(entry["status"], new, reinstatement=reinstatement)
        entry["history"].append({"from": entry["status"], "to": new, "actor": actor.name, "at": self._now(),
                                 "reason": reason})
        entry["status"] = new

    def _new_op_id(self) -> str:
        return f"op-{uuid.uuid4().hex[:12]}"

    @contextmanager
    def _operation(self, name: str, actor: Actor, doc_ids: Iterable[str] = ()):
        lock = WriterLock(self.cfg.lock_path, name, actor.name, self._now())
        lock.acquire()
        try:
            self.last_recovery = self._recover(lock.released_stale)
            op = {"op_id": self._new_op_id(), "name": name, "actor": actor.name, "doc_ids": list(doc_ids)}
            try:
                yield op
            except Exception as e:
                if op.get("begun") and not self._pointer_switched(op):
                    self.journal.append({"event": "abort", "op_id": op["op_id"], "at": self._now(),
                                         "reason": f"{type(e).__name__}: {e}"[:500]})
                    if op.get("new_version"):            # only a version this operation created; a rollback
                        self._quarantine_versions(op.get("target_version"))   # target existed before it
                # if the pointer was already switched the operation stays open; recovery completes it
                raise
        finally:
            lock.release()

    def _begin(self, op: Dict[str, Any], registry_after: Optional[Dict[str, Any]] = None,
               pointer: Optional[str] = None, target_version: Optional[str] = None, new_version: bool = False,
               **details) -> None:
        entry = {"event": "begin", "op_id": op["op_id"], "name": op["name"], "actor": op["actor"],
                 "doc_ids": op["doc_ids"], "at": self._now(), "pointer": pointer, "target_version": target_version,
                 "new_version": new_version, **details}
        if registry_after is not None:
            entry["registry_after"] = registry_after
            entry["registry_after_sha256"] = state_sha256(registry_after)
        self.journal.append(entry)
        op.update(begun=True, target_version=target_version, pointer=pointer, new_version=new_version)
        fsutil.crash_point("begun")

    def _pointer_switched(self, op: Dict[str, Any]) -> bool:
        kind = {"CURRENT": "public", "STAGING": "staging"}.get(op.get("pointer"))
        current = read_pointer(self.cfg, kind) if kind else None
        return bool(current and op.get("target_version") and current["version"] == op["target_version"])

    def _commit(self, op: Dict[str, Any], **details) -> None:
        self.journal.append({"event": "commit", "op_id": op["op_id"], "name": op["name"], "actor": op["actor"],
                             "doc_ids": op["doc_ids"], "at": self._now(), "version": op.get("target_version"),
                             **details})

    def _quarantine_versions(self, *version_ids) -> List[str]:
        moved = []
        for vid in version_ids:
            if not vid:
                continue
            src = self.cfg.versions_dir / vid
            pointed = {p["version"] for p in (read_pointer(self.cfg, "public"), read_pointer(self.cfg, "staging")) if p}
            if src.is_dir() and vid not in pointed:
                fsutil.rename_dir(src, self.cfg.quarantine_dir / f"{vid}.{uuid.uuid4().hex[:6]}",
                                  self.cfg.io_retries, self.cfg.io_retry_delay_s)
                moved.append(vid)
        return moved

    # ================================================================== recovery
    def _recover(self, stale_lock: Optional[dict] = None) -> Dict[str, Any]:
        """Complete or abort interrupted operations and quarantine half-written versions (called under the lock)."""
        report = {"stale_lock_released": stale_lock, "completed": [], "aborted": [], "quarantined": []}
        for op in self.journal.open_operations():
            pointer_kind = {"CURRENT": "public", "STAGING": "staging"}.get(op.get("pointer"))
            current = read_pointer(self.cfg, pointer_kind) if pointer_kind else None
            switched = bool(current and op.get("target_version") and current["version"] == op["target_version"])
            no_pointer_change = pointer_kind is None and "registry_after" in op
            if switched or no_pointer_change:
                if "registry_after" in op and state_sha256(self.registry.load()) != op["registry_after_sha256"]:
                    self.registry.save(op["registry_after"])
                self.journal.append({"event": "commit", "op_id": op["op_id"], "name": op.get("name"),
                                     "actor": op.get("actor"), "doc_ids": op.get("doc_ids", []), "at": self._now(),
                                     "version": op.get("target_version"), "recovered": True})
                report["completed"].append(op["op_id"])
            else:
                self.journal.append({"event": "abort", "op_id": op["op_id"], "at": self._now(), "recovered": True,
                                     "reason": "interrupted before its pointer was switched"})
                if op.get("new_version"):
                    report["quarantined"] += self._quarantine_versions(op.get("target_version"))
                report["aborted"].append(op["op_id"])
        if self.cfg.versions_dir.is_dir():
            for d in self.cfg.versions_dir.iterdir():
                if d.name.startswith(".tmp-"):
                    fsutil.rename_dir(d, self.cfg.quarantine_dir / d.name.lstrip("."), self.cfg.io_retries,
                                      self.cfg.io_retry_delay_s)
                    report["quarantined"].append(d.name)
            committed = {e.get("version") for e in self.journal.entries() if e.get("event") == "commit"}
            for d in self.cfg.versions_dir.iterdir():
                if d.is_dir() and d.name.isdigit() and d.name not in committed:
                    report["quarantined"] += self._quarantine_versions(d.name)
        return report

    # ================================================================== base seed (Stage 3.2)
    def seed_base(self, frozen_dir: Path, base_docs: List[Dict[str, Any]], actor: Actor,
                  expected_fingerprint: Optional[str] = None) -> Dict[str, Any]:
        """Create version 0001 (public) from the frozen heading-aware store, copying its chunk lines and index
        byte for byte. base_docs: [{"doc_id", "title", "source_label"}] in store order; each document's range is
        the contiguous block of rows with that source label."""
        self._require(actor, ROLE_ADMIN)
        with self._operation("seed_base", actor, [d["doc_id"] for d in base_docs]) as op:
            state = self.registry.load()
            if any(d.get("base") for d in state["documents"]):
                current = read_pointer(self.cfg, "public")
                return {"no_op": True, "version": current and current["version"]}
            with open(Path(frozen_dir) / CHUNKS_FILE, encoding="utf-8") as f:
                records = [json.loads(line) for line in f]
            after = clone(state)
            pos = 0
            for spec in base_docs:
                check_doc_id(spec["doc_id"])
                start = pos
                while pos < len(records) and records[pos]["source"] == spec["source_label"]:
                    pos += 1
                if pos == start:
                    raise IntegrityError(f"no rows labelled {spec['source_label']!r} at position {start}")
                after["documents"].append({
                    "doc_id": spec["doc_id"], "doc_version": 1, "title": spec["title"],
                    "source_label": spec["source_label"], "adapter": "frozen_base", "adapter_options": {},
                    "valid_for": spec.get("valid_for"), "base": True, "base_range": [start, pos - 1],
                    "status": states.PUBLISHED, "dataset": {"name": records[start]["file_name"], "sha256": None,
                                                            "path": None},
                    "source_file": None, "uploaded_by": actor.name, "uploaded_at": self._now(), "units": None,
                    "validation": None, "approvals": [], "correction_history": [], "excluded_units": {},
                    "publish_seq": None, "stage_seq": None, "supersedes": None,
                    "history": [{"from": None, "to": states.PUBLISHED, "actor": actor.name, "at": self._now(),
                                 "reason": f"frozen base from {Path(frozen_dir).name} (rows {start}-{pos - 1})"}]})
            if pos != len(records):
                raise IntegrityError(f"base documents cover {pos} of {len(records)} frozen rows")
            entries = ordered_for_build(after, states.VISIBLE["public"])
            base = BaseMaterial.from_frozen(Path(frozen_dir), entries, expected_fingerprint)
            vid = next_version_id(self.cfg)
            self._begin(op, after, pointer="CURRENT", target_version=vid, new_version=True,
                        frozen_dir=str(frozen_dir))
            build_version(self.cfg, kind="public", entries=entries, base=base, cache=self.cache, version_id=vid,
                          parent=None, op_id=op["op_id"], seed=True,
                          copy_index_from=Path(frozen_dir) / INDEX_FILE)
            write_pointer(self.cfg, "public", vid)
            fsutil.crash_point("pointer_switched")
            self.registry.save(after)
            self._commit(op)
            return {"no_op": False, "version": vid}

    # ================================================================== document operations
    def register_upload(self, dataset_path: Path, meta: Dict[str, Any], actor: Actor,
                        source_file: Optional[Path] = None) -> Dict[str, Any]:
        """Register a document version (status 'uploaded'). Same file + same doc_id again is a no-op."""
        self._require(actor, ROLE_UPLOADER, ROLE_APPROVER)
        missing = [k for k in META_REQUIRED if not meta.get(k)]
        if missing:
            raise ValidationFailed(f"metadata lacks {missing}")
        unknown = set(meta) - set(META_REQUIRED) - set(META_OPTIONAL)
        if unknown:
            raise ValidationFailed(f"unknown metadata fields {sorted(unknown)}")
        doc_id = check_doc_id(meta["doc_id"])
        get_adapter(meta["adapter"])
        self._check_prior_approval(meta.get("prior_approval"))
        dataset_sha = sha256_file(dataset_path)
        with self._operation("register_upload", actor, [doc_id]) as op:
            state = self.registry.load()
            same = find_by_sha(state, dataset_sha)
            if same:
                if same[0]["doc_id"] == doc_id:
                    return {"no_op": True, "doc_id": doc_id, "doc_version": same[0]["doc_version"]}
                raise DuplicateDocument(f"this file is already registered as {same[0]['doc_id']} "
                                        f"v{same[0]['doc_version']}")
            existing = [d for d in state["documents"] if d["doc_id"] == doc_id]
            if any(d.get("base") for d in existing):
                raise DuplicateDocument(f"{doc_id} is a frozen base document")
            version = max((d["doc_version"] for d in existing), default=0) + 1
            entry = {"doc_id": doc_id, "doc_version": version, "title": meta["title"],
                     "source_label": meta["source_label"], "adapter": meta["adapter"],
                     "adapter_options": meta.get("adapter_options") or {}, "valid_for": meta.get("valid_for"),
                     "base": False, "status": None,
                     "dataset": self._store_upload(dataset_path, dataset_sha),
                     "source_file": self._store_upload(source_file, sha256_file(source_file)) if source_file else None,
                     "uploaded_by": actor.name, "uploaded_at": self._now(), "units": None, "validation": None,
                     "approvals": [], "correction_history": meta.get("correction_history") or [],
                     "excluded_units": meta.get("excluded_units") or {}, "notes": meta.get("notes"),
                     "prior_approval": meta.get("prior_approval"),
                     "publish_seq": None, "stage_seq": None, "supersedes": None, "history": []}
            self._set_status(entry, states.UPLOADED, actor, "registered")
            after = clone(state)
            after["documents"].append(entry)
            self._begin(op, after, dataset_sha256=dataset_sha)
            self.registry.save(after)
            self._commit(op)
            return {"no_op": False, "doc_id": doc_id, "doc_version": version}

    @staticmethod
    def _check_prior_approval(prior) -> None:
        if prior is not None:
            gaps = [k for k in PRIOR_APPROVAL_REQUIRED if not (isinstance(prior, dict) and prior.get(k))]
            if gaps:
                raise ValidationFailed(f"prior_approval lacks {gaps}")

    def _store_upload(self, path: Path, sha: str) -> Dict[str, Any]:
        path = Path(path)
        dest = self.cfg.uploads_dir / sha / path.name
        if not dest.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f".{dest.name}.tmp")
            shutil.copyfile(path, tmp)
            fsutil.fsync_file(tmp)
            fsutil.retry(lambda: os.replace(tmp, dest), self.cfg.io_retries, self.cfg.io_retry_delay_s)
        if sha256_file(dest) != sha:
            raise IntegrityError(f"stored upload {dest} does not match {sha}")
        return {"name": path.name, "sha256": sha, "path": dest.relative_to(self.cfg.root).as_posix()}

    def _upload_path(self, ref: Dict[str, Any]) -> Path:
        path = self.cfg.root / ref["path"]
        if sha256_file(path) != ref["sha256"]:
            raise IntegrityError(f"{path} no longer matches its registered SHA-256")
        return path

    def validate(self, doc_id: str, doc_version: int, actor: Actor) -> Dict[str, Any]:
        """Run the adapter and validators. On success the passage units are frozen to units/<doc>@v<n>.jsonl."""
        self._require(actor, ROLE_UPLOADER, ROLE_APPROVER)
        with self._operation("validate", actor, [doc_id]) as op:
            state = self.registry.load()
            entry = find(state, doc_id, doc_version)
            if entry["status"] != states.UPLOADED:
                if entry["status"] == states.VALIDATED:
                    return {"no_op": True, **read_json(self.cfg.root / entry["validation"]["report"])}
                raise InvalidTransition(f"{doc_id} v{doc_version} is {entry['status']}, not uploaded")
            dataset = self._upload_path(entry["dataset"])
            units, problems = get_adapter(entry["adapter"]).extract(entry, dataset)
            page_count = self._page_count(entry)
            report = validate_units(units, entry=entry, token_counter=self.token_counter(),
                                    max_tokens=self.cfg.max_tokens, page_count=page_count, adapter_problems=problems,
                                    existing_text_keys=self._existing_text_keys())
            report.update({"doc_id": doc_id, "doc_version": doc_version, "validated_by": actor.name,
                           "validated_at": self._now(), "page_count": page_count})
            key = doc_key(doc_id, doc_version)
            report_bytes = canonical_json(report)
            # content-addressed names: a revalidation after a metadata change never overwrites earlier files
            report_path = self.cfg.validation_dir / f"{key}.{fsutil.sha256_bytes(report_bytes)[:12]}.json"
            after = clone(state)
            new = find(after, doc_id, doc_version)
            new["validation"] = {"report": report_path.relative_to(self.cfg.root).as_posix(),
                                 "errors": len(report["errors"]), "warnings": len(report["warnings"])}
            if report["ok"]:
                units_bytes = b"".join((json.dumps(u, ensure_ascii=False) + "\n").encode("utf-8") for u in units)
                units_path = self.cfg.units_dir / f"{key}.{fsutil.sha256_bytes(units_bytes)[:12]}.jsonl"
                new["units"] = {"path": units_path.relative_to(self.cfg.root).as_posix(),
                                "sha256": fsutil.sha256_bytes(units_bytes), "count": len(units)}
                self._set_status(new, states.VALIDATED, actor, "validation passed")
            fsutil.atomic_write_bytes(report_path, report_bytes)   # files first: the registry may only
            if report["ok"]:                                        # reference files that already exist
                fsutil.atomic_write_bytes(units_path, units_bytes)
            self._begin(op, after)
            self.registry.save(after)
            self._commit(op, ok=report["ok"])
        self._assert_consistent()
        return {"no_op": False, **report}

    def update_metadata(self, doc_id: str, doc_version: int, changes: Dict[str, Any], actor: Actor,
                        reason: str) -> Dict[str, Any]:
        """Correct registry metadata of a document version that is still 'uploaded' or 'validated'. A validated
        version returns to 'uploaded' (its frozen passages and report are detached, not deleted), so it must be
        validated again before it can be staged. Staged, approved and published versions cannot be changed."""
        self._require(actor, ROLE_UPLOADER, ROLE_APPROVER)
        if not changes or not isinstance(changes, dict):
            raise ValidationFailed("no metadata changes given")
        unknown = set(changes) - set(META_UPDATABLE)
        if unknown:
            raise ValidationFailed(f"these fields cannot be updated: {sorted(unknown)}")
        if "adapter" in changes:
            get_adapter(changes["adapter"])
        self._check_prior_approval(changes.get("prior_approval"))
        if not reason or not reason.strip():
            raise ValidationFailed("a metadata update needs a reason")
        with self._operation("update_metadata", actor, [doc_id]) as op:
            state = self.registry.load()
            entry = find(state, doc_id, doc_version)
            if entry.get("base") or entry["status"] not in (states.UPLOADED, states.VALIDATED):
                raise InvalidTransition(f"{doc_id} v{doc_version} is {entry['status']}: metadata can only be changed "
                                        "while a version is uploaded or validated (register a new version instead)")
            diff = {k: {"from": entry.get(k), "to": v} for k, v in changes.items() if entry.get(k) != v}
            if not diff:
                return {"no_op": True, "doc_id": doc_id, "doc_version": doc_version, "status": entry["status"]}
            after = clone(state)
            new = find(after, doc_id, doc_version)
            new.setdefault("metadata_history", []).append({
                "at": self._now(), "actor": actor.name, "reason": reason.strip(), "changes": diff,
                "detached_units": new.get("units"), "detached_validation": new.get("validation")})
            for k, v in changes.items():
                new[k] = v
            new["units"], new["validation"] = None, None
            if new["status"] == states.VALIDATED:
                self._set_status(new, states.UPLOADED, actor, f"metadata updated ({', '.join(diff)}): "
                                                              "revalidation required")
            self._begin(op, after, changed_fields=sorted(diff))
            self.registry.save(after)
            self._commit(op)
        self._assert_consistent()
        return {"no_op": False, "doc_id": doc_id, "doc_version": doc_version, "status": states.UPLOADED,
                "changed": sorted(diff)}

    def _page_count(self, entry: Dict[str, Any]) -> Optional[int]:
        ref = entry.get("source_file") or entry["dataset"]
        if not ref["name"].lower().endswith(".pdf"):
            return None
        import pymupdf
        with pymupdf.open(self._upload_path(ref)) as pdf:
            return pdf.page_count

    def _existing_text_keys(self) -> set:
        keys = set()
        for kind in ("public", "staging"):
            p = read_pointer(self.cfg, kind)
            if p:
                with open(self.cfg.versions_dir / p["version"] / CHUNKS_FILE, encoding="utf-8") as f:
                    keys |= {text_key(json.loads(line)["text"]) for line in f}
        return keys

    def stage(self, doc_id: str, doc_version: int, actor: Actor,
              progress: Optional[Callable[[int, int], None]] = None) -> Dict[str, Any]:
        """Embed the document's passages (cached; resumable) and rebuild the staging version to include it."""
        self._require(actor, ROLE_UPLOADER, ROLE_APPROVER)
        with self._operation("stage", actor, [doc_id]) as op:
            state = self.registry.load()
            entry = find(state, doc_id, doc_version)
            if entry["status"] != states.VALIDATED:
                raise InvalidTransition(f"{doc_id} v{doc_version} is {entry['status']}, not validated")
            from src.kb.versions import load_units
            units = load_units(self.cfg, entry)
            texts = [index_text(u) for u in units]
            embedded = self.cache.ensure(texts, self._embedder_factory, progress=progress)
            near = self._near_duplicates(texts, units)
            after = clone(state)
            new = find(after, doc_id, doc_version)
            new["stage_seq"] = max((d.get("stage_seq") or 0) for d in after["documents"]) + 1
            self._set_status(new, states.STAGED, actor, "staged for testing")
            report_path = self.cfg.validation_dir / f"{doc_key(doc_id, doc_version)}.staging.json"
            fsutil.atomic_write_json(report_path, {"doc_id": doc_id, "doc_version": doc_version,
                                                   "embedded_now": embedded, "near_duplicates": near})
            new["staging_report"] = report_path.relative_to(self.cfg.root).as_posix()
            result = self._rebuild(op, "staging", after)
            return {**result, "embedded_now": embedded, "near_duplicates": len(near)}

    def _near_duplicates(self, texts: List[str], units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Pairs with cosine >= threshold between the new passages and the current public store (or each other)."""
        import faiss
        import numpy as np
        vecs = self.cache.vectors_for(texts)
        out = []
        sim = np.triu(vecs @ vecs.T, k=1)
        for i, j in np.argwhere(sim >= self.cfg.near_duplicate_threshold):
            out.append({"a": units[i]["record_id"], "b": units[j]["record_id"], "cosine": round(float(sim[i, j]), 4),
                        "where": "within document"})
        pointer = read_pointer(self.cfg, "public")
        if pointer:
            index = faiss.read_index(str(self.cfg.versions_dir / pointer["version"] / INDEX_FILE))
            scores, ids = index.search(vecs, 1)
            for i, (s, j) in enumerate(zip(scores[:, 0], ids[:, 0])):
                if j >= 0 and s >= self.cfg.near_duplicate_threshold:
                    out.append({"a": units[i]["record_id"], "b": f"public row {int(j)}", "cosine": round(float(s), 4),
                                "where": "public store"})
        return out

    def approve(self, doc_id: str, doc_version: int, actor: Actor, *, basis: str,
                decision_date: Optional[str] = None, evidence: Optional[str] = None,
                registry_verification: Optional[str] = None) -> Dict[str, Any]:
        """Record an approval (staged -> approved). With the two-person rule, the approver cannot be the uploader."""
        self._require(actor, ROLE_APPROVER)
        if not basis or not basis.strip():
            raise ValidationFailed("an approval needs a basis")
        with self._operation("approve", actor, [doc_id]) as op:
            state = self.registry.load()
            entry = find(state, doc_id, doc_version)
            if entry["status"] != states.STAGED:
                raise InvalidTransition(f"{doc_id} v{doc_version} is {entry['status']}, not staged")
            if self.cfg.two_person_rule and actor.name == entry["uploaded_by"]:
                raise PermissionDenied("two-person rule: the approver must not be the uploader")
            after = clone(state)
            new = find(after, doc_id, doc_version)
            new["approvals"].append(self._approval_record(actor, "approved", basis, decision_date, evidence=evidence,
                                                          registry_verification=registry_verification))
            self._set_status(new, states.APPROVED, actor, basis.strip())
            return self._rebuild(op, "staging", after)

    def reject(self, doc_id: str, doc_version: int, actor: Actor, reason: str) -> Dict[str, Any]:
        self._require(actor, ROLE_APPROVER)
        with self._operation("reject", actor, [doc_id]) as op:
            state = self.registry.load()
            entry = find(state, doc_id, doc_version)
            was_visible = states.visible_in("staging", entry["status"])
            after = clone(state)
            self._set_status(find(after, doc_id, doc_version), states.REJECTED, actor, reason)
            if was_visible:
                return self._rebuild(op, "staging", after)
            self._begin(op, after)
            self.registry.save(after)
            self._commit(op)
            return {"no_op": False, "version": None}

    @staticmethod
    def _no_override(state: Dict[str, Any], operation: str) -> None:
        override = state.get("active_override")
        if override:
            raise OverrideActive(f"{operation} is blocked: an emergency rollback to version {override['version']} is "
                                 f"in force since {override['at']} ({override['reason']}). Run reconcile first.")

    def publish(self, actor: Actor) -> Dict[str, Any]:
        """Publish every approved document: build a public version (base + published), switch CURRENT, then
        refresh the staging version and apply retention."""
        self._require(actor, ROLE_APPROVER)
        with self._operation("publish", actor) as op:
            state = self.registry.load()
            self._no_override(state, "publish")
            after = clone(state)
            seq = max((d.get("publish_seq") or 0) for d in after["documents"])
            approved = sorted((d for d in after["documents"] if d["status"] == states.APPROVED),
                              key=lambda d: (d.get("stage_seq") or 0, d["doc_id"]))
            for d in approved:
                seq += 1
                d["publish_seq"] = seq
                self._set_status(d, states.PUBLISHED, actor, "published")
            op["doc_ids"] = [d["doc_id"] for d in approved]
            result = self._rebuild(op, "public", after)
        return self._after_public_change(actor, result)

    def _after_public_change(self, actor: Actor, result: Dict[str, Any]) -> Dict[str, Any]:
        result["staging"] = self.refresh_staging(actor, check=False)
        result["archived"] = apply_retention(self.cfg)
        self._assert_consistent()
        return result

    def withdraw(self, doc_id: str, doc_version: int, actor: Actor, reason: str) -> Dict[str, Any]:
        self._require(actor, ROLE_APPROVER)
        with self._operation("withdraw", actor, [doc_id]) as op:
            after = clone(self.registry.load())
            self._no_override(after, "withdraw")
            if find(after, doc_id, doc_version).get("base"):
                raise InvalidTransition("frozen base documents cannot be withdrawn")
            self._set_status(find(after, doc_id, doc_version), states.WITHDRAWN, actor, reason)
            result = self._rebuild(op, "public", after)
        return self._after_public_change(actor, result)

    def supersede(self, old: tuple, new: tuple, actor: Actor, reason: str) -> Dict[str, Any]:
        """Publish `new` (must be approved) and mark `old` (published) superseded in one public version."""
        self._require(actor, ROLE_APPROVER)
        with self._operation("supersede", actor, [old[0], new[0]]) as op:
            after = clone(self.registry.load())
            self._no_override(after, "supersede")
            o, n = find(after, *old), find(after, *new)
            if o.get("base"):
                raise InvalidTransition("frozen base documents cannot be superseded")
            if n["status"] != states.APPROVED:
                raise InvalidTransition(f"{new[0]} v{new[1]} must be approved first")
            self._set_status(o, states.SUPERSEDED, actor, f"superseded by {new[0]} v{new[1]}: {reason}")
            n["publish_seq"] = max((d.get("publish_seq") or 0) for d in after["documents"]) + 1
            n["supersedes"] = {"doc_id": old[0], "doc_version": old[1]}
            self._set_status(n, states.PUBLISHED, actor, f"published, superseding {old[0]} v{old[1]}")
            result = self._rebuild(op, "public", after)
        return self._after_public_change(actor, result)

    def republish(self, doc_id: str, doc_version: int, actor: Actor, *, basis: str,
                  decision_date: Optional[str] = None) -> Dict[str, Any]:
        """Return a suspended document to the public index, with a recorded decision."""
        self._require(actor, ROLE_APPROVER)
        if not basis or not basis.strip():
            raise ValidationFailed("re-publishing needs a basis")
        with self._operation("republish", actor, [doc_id]) as op:
            after = clone(self.registry.load())
            self._no_override(after, "republish")
            e = find(after, doc_id, doc_version)
            if e["status"] != states.SUSPENDED:
                raise InvalidTransition(f"{doc_id} v{doc_version} is {e['status']}, not suspended")
            if self.cfg.two_person_rule and actor.name == e["uploaded_by"]:
                raise PermissionDenied("two-person rule: the approver must not be the uploader")
            e["approvals"].append(self._approval_record(actor, "republished", basis, decision_date))
            self._set_status(e, states.PUBLISHED, actor, f"re-published: {basis.strip()}")
            result = self._rebuild(op, "public", after)
        return self._after_public_change(actor, result)

    def _approval_record(self, actor: Actor, decision: str, basis: str, decision_date: Optional[str] = None,
                         **extra) -> Dict[str, Any]:
        return {"actor": actor.name, "decision": decision, "decision_date": decision_date or self._now()[:10],
                "basis": basis.strip(), "recorded_at": self._now(), "two_person_rule": self.cfg.two_person_rule,
                **extra}

    def refresh_staging(self, actor: Actor, check: bool = True) -> Dict[str, Any]:
        """Rebuild the staging version from the registry (no-op when its content is already current)."""
        self._require(actor, ROLE_UPLOADER, ROLE_APPROVER)
        with self._operation("refresh_staging", actor) as op:
            result = self._rebuild(op, "staging", self.registry.load(), registry_changed=False)
        if check:
            self._assert_consistent()
        return result

    def rollback(self, version_id: str, actor: Actor, reason: str, *, emergency: bool = False,
                 reinstate: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Point CURRENT at an earlier verified public version.

        Normal (registry-aware): in the same journaled operation, published documents that the target version does
        not contain become 'suspended'; suspended documents that it contains become 'published' again; withdrawn or
        superseded documents that it contains become public again only if `reinstate`
        ({"basis": ..., "documents": [[doc_id, version], ...], "decision_date": optional}) covers each of them;
        otherwise ReinstatementRequired is raised and nothing changes.
        Emergency (emergency=True): only the pointer moves; an active_override is recorded, and publish, withdraw,
        supersede, republish and further rollbacks are blocked until reconcile() resolves the difference."""
        self._require(actor, ROLE_APPROVER)
        if not reason or not reason.strip():
            raise ValidationFailed("a rollback needs a reason")
        with self._operation("emergency_rollback" if emergency else "rollback", actor) as op:
            target = self._verified_public_version(version_id)
            previous = read_pointer(self.cfg, "public")
            after = clone(self.registry.load())
            self._no_override(after, "rollback")
            event = {"event": "emergency_rollback" if emergency else "rollback", "pointer": "CURRENT",
                     "from": previous and previous["version"], "to": version_id, "actor": actor.name,
                     "at": self._now(), "reason": reason.strip()}
            if emergency:
                after["active_override"] = {"version": version_id, "from": event["from"], "actor": actor.name,
                                            "at": event["at"], "reason": reason.strip()}
            else:
                event["status_changes"] = self._align_registry(after, target, actor,
                                                               f"rollback to version {version_id}", reinstate)
            after["pointer_events"].append(event)
            op["doc_ids"] = sorted({c[0] for c in event.get("status_changes", [])})
            self._begin(op, after, pointer="CURRENT", target_version=version_id, rollback=event["event"])
            write_pointer(self.cfg, "public", version_id)
            fsutil.crash_point("pointer_switched")
            self.registry.save(after)
            fsutil.crash_point("registry_saved")
            self._commit(op)
        result = {"no_op": False, "version": version_id, "previous": event["from"], "emergency": emergency,
                  "status_changes": event.get("status_changes", [])}
        if not emergency:
            result["staging"] = self.refresh_staging(actor, check=False)
            self._assert_consistent()
        return result

    def _verified_public_version(self, version_id: str) -> Dict[str, Any]:
        target = self.cfg.versions_dir / version_id
        if not target.is_dir():
            raise UnknownDocument(f"version {version_id} is not in store/versions (archived versions must be "
                                  "restored first)")
        from src.kb.store import KBStore
        return KBStore(target).load(expected_kind="public", verify_bm25=False).kb

    def _align_registry(self, after: Dict[str, Any], target_kb: Dict[str, Any], actor: Actor, context: str,
                        reinstate: Optional[Dict[str, Any]]) -> List[list]:
        """Change statuses in `after` so that its published set equals the documents of a public version.
        Returns [doc_id, version, old status, new status] for every change."""
        in_target = {(d["doc_id"], d["doc_version"]) for d in target_kb["documents"] if not d["base"]}
        base_target = {(d["doc_id"], d["doc_version"]) for d in target_kb["documents"] if d["base"]}
        base_registry = {(d["doc_id"], d["doc_version"]) for d in after["documents"] if d.get("base")}
        if base_target != base_registry:
            raise IntegrityError(f"version base documents {sorted(base_target)} differ from the registry's "
                                 f"{sorted(base_registry)}")
        published = {(d["doc_id"], d["doc_version"]) for d in after["documents"]
                     if not d.get("base") and d["status"] == states.PUBLISHED}
        covered = {tuple(x) for x in (reinstate or {}).get("documents", [])}
        basis = ((reinstate or {}).get("basis") or "").strip()
        changes, missing_approval = [], []
        for doc_id, version in sorted(published - in_target):
            self._set_status(find(after, doc_id, version), states.SUSPENDED, actor, f"suspended: {context}")
            changes.append([doc_id, version, states.PUBLISHED, states.SUSPENDED])
        for doc_id, version in sorted(in_target - published):
            e = find(after, doc_id, version)
            if e["status"] == states.SUSPENDED:
                self._set_status(e, states.PUBLISHED, actor, f"restored: {context}")
                changes.append([doc_id, version, states.SUSPENDED, states.PUBLISHED])
            elif e["status"] in (states.WITHDRAWN, states.SUPERSEDED):
                if (doc_id, version) not in covered or not basis:
                    missing_approval.append([doc_id, version, e["status"]])
                    continue
                retired_by = e["history"][-1]["actor"]
                if self.cfg.two_person_rule and actor.name == retired_by:
                    raise PermissionDenied(f"two-person rule: {doc_id} v{version} was {e['status']} by {retired_by}; "
                                           "another approver must reinstate it")
                previous = e["status"]
                e["approvals"].append(self._approval_record(actor, "reinstated", basis, reinstate.get("decision_date"),
                                                            context=context, previous_status=previous))
                self._set_status(e, states.PUBLISHED, actor, f"reinstated: {context}: {basis}", reinstatement=True)
                changes.append([doc_id, version, previous, states.PUBLISHED])
            else:
                raise IntegrityError(f"{doc_id} v{version} is in the public version but its status is {e['status']}")
        if missing_approval:
            raise ReinstatementRequired(f"{context} would make withdrawn or superseded documents public again: "
                                        f"{missing_approval}. Pass reinstate={{'basis': ..., 'documents': [...]}} "
                                        "with an explicit decision, or choose another version.")
        return changes

    def reconcile_plan(self) -> Dict[str, Any]:
        """Read-only: the difference between CURRENT and the registry (used while an emergency override is active)."""
        state = self.registry.load()
        pointer = read_pointer(self.cfg, "public")
        current = version_manifest(self.cfg, pointer["version"])["kb"] if pointer else {"documents": []}
        in_current = {(d["doc_id"], d["doc_version"]) for d in current["documents"] if not d["base"]}
        published = {(d["doc_id"], d["doc_version"]) for d in state["documents"]
                     if not d.get("base") and d["status"] == states.PUBLISHED}
        status = {(d["doc_id"], d["doc_version"]): d["status"] for d in state["documents"]}
        extra = sorted(in_current - published)
        return {"active_override": state.get("active_override"), "current_version": pointer and pointer["version"],
                "published_but_not_in_current": [list(k) for k in sorted(published - in_current)],
                "in_current_but_not_published": [[*k, status.get(k)] for k in extra],
                "needs_reinstatement_approval": [[*k, status.get(k)] for k in extra
                                                 if status.get(k) in (states.WITHDRAWN, states.SUPERSEDED)],
                "modes": {"accept_index": "keep CURRENT; align the registry to it (suspend / restore / reinstate)",
                          "restore_registry": "build a new public version from the registry and switch CURRENT"}}

    def reconcile(self, actor: Actor, mode: str, reason: str,
                  reinstate: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Resolve an emergency override.
        accept_index:     keep CURRENT and align the registry to it (registry-only, journaled).
        restore_registry: rebuild the public version from the registry and switch CURRENT."""
        self._require(actor, ROLE_APPROVER)
        if mode not in ("accept_index", "restore_registry"):
            raise ValidationFailed("mode must be 'accept_index' or 'restore_registry'")
        if not reason or not reason.strip():
            raise ValidationFailed("reconciliation needs a reason")
        with self._operation("reconcile", actor) as op:
            after = clone(self.registry.load())
            override = after.get("active_override")
            if not override:
                return {"no_op": True, "reason": "no emergency override is active"}
            event = {"event": f"reconcile:{mode}", "override": override, "actor": actor.name, "at": self._now(),
                     "reason": reason.strip()}
            after["active_override"] = None
            if mode == "accept_index":
                current = self._verified_public_version(read_pointer(self.cfg, "public")["version"])
                event["status_changes"] = self._align_registry(after, current, actor,
                                                               f"reconciliation with version {current['version']}",
                                                               reinstate)
                after["pointer_events"].append(event)
                op["doc_ids"] = sorted({c[0] for c in event["status_changes"]})
                self._begin(op, after, reconcile=mode)
                self.registry.save(after)
                self._commit(op)
                result = {"no_op": False, "mode": mode, "version": current["version"],
                          "status_changes": event["status_changes"]}
            else:
                after["pointer_events"].append(event)
                result = {**self._rebuild(op, "public", after), "mode": mode}
        if mode == "restore_registry":
            return self._after_public_change(actor, result)
        result["staging"] = self.refresh_staging(actor, check=False)
        self._assert_consistent()
        return result

    def _rebuild(self, op: Dict[str, Any], kind: str, after: Dict[str, Any],
                 registry_changed: bool = True) -> Dict[str, Any]:
        """Build a `kind` version from registry state `after`, switch its pointer, save the registry, commit.
        If the resulting content equals the current pointer target, only the registry is saved (no new version)."""
        entries = copy.deepcopy(ordered_for_build(after, states.VISIBLE[kind]))
        current = read_pointer(self.cfg, kind)
        public = read_pointer(self.cfg, "public")
        if public is None:
            raise KBError("the frozen base has not been seeded (run seed_base first)")
        base = BaseMaterial.from_version(self.cfg.versions_dir / public["version"])
        signature = self._signature(kind, entries, base)
        if current and version_manifest(self.cfg, current["version"])["kb"]["content_signature"] == signature:
            if registry_changed:
                self._begin(op, after)
                self.registry.save(after)
                self._commit(op, no_new_version=True)
            return {"no_op": True, "version": current["version"]}
        vid = next_version_id(self.cfg)
        self._begin(op, after if registry_changed else None, pointer=POINTERS[kind], target_version=vid,
                    new_version=True)
        build_version(self.cfg, kind=kind, entries=entries, base=base, cache=self.cache, version_id=vid,
                      parent=current and current["version"], op_id=op["op_id"])
        write_pointer(self.cfg, kind, vid)
        fsutil.crash_point("pointer_switched")
        if registry_changed:
            self.registry.save(after)
        fsutil.crash_point("registry_saved")
        self._commit(op)
        return {"no_op": False, "version": vid}

    def _signature(self, kind: str, entries: List[Dict[str, Any]], base: BaseMaterial) -> str:
        from src.kb.versions import content_signature, plan_version
        _, _, _, docs = plan_version(self.cfg, kind, entries, base, self.cache)
        return content_signature(kind, base, docs, fsutil.sha256_bytes(canonical_json({"kind": kind,
                                                                                     "documents": entries})))

    # ================================================================== read-only
    def status(self) -> Dict[str, Any]:
        state = self.registry.load()
        return {"profile": self.cfg.profile, "two_person_rule": self.cfg.two_person_rule,
                "pointers": {k: read_pointer(self.cfg, k) for k in POINTERS},
                "documents": [{"doc_id": d["doc_id"], "doc_version": d["doc_version"], "status": d["status"],
                               "base": d.get("base", False), "passages": (d.get("units") or {}).get("count")
                               or (d["base_range"][1] - d["base_range"][0] + 1 if d.get("base") else None)}
                              for d in state["documents"]]}

    def history(self, doc_id: str) -> Dict[str, Any]:
        state = self.registry.load()
        entries = [d for d in state["documents"] if d["doc_id"] == doc_id]
        if not entries:
            raise UnknownDocument(doc_id)
        return {"versions": [{"doc_version": d["doc_version"], "status": d["status"], "history": d["history"],
                              "approvals": d["approvals"], "correction_history": d["correction_history"]}
                             for d in entries],
                "journal": self.journal.history(doc_id)}

    def consistency(self, state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Compare the registry with the CURRENT and STAGING versions (manifests only, fast).

        After every completed normal operation the documents (and statuses) visible in each version equal the
        registry's visible set for that kind, and every frozen base document is present, published and unchanged.
        A difference is a problem, except the expected public difference while an emergency override is active."""
        state = state or self.registry.load()
        problems, warnings = [], []
        override = state.get("active_override")
        base_registry = {(d["doc_id"], d["doc_version"]): d for d in state["documents"] if d.get("base")}
        for kind in POINTERS:
            pointer = read_pointer(self.cfg, kind)
            expected = {(d["doc_id"], d["doc_version"]): d["status"] for d in state["documents"]
                        if states.visible_in(kind, d["status"])}
            if pointer is None:
                non_base = sorted(k for k in expected if k not in base_registry)
                if kind == "public" and state["documents"]:
                    problems.append("the registry has documents but no public version exists")
                elif kind == "staging" and non_base:
                    problems.append(f"no staging version exists, but the registry has staging documents {non_base}")
                continue
            kb = version_manifest(self.cfg, pointer["version"])["kb"]
            docs = {(d["doc_id"], d["doc_version"]): d for d in kb["documents"]}
            for key, entry in base_registry.items():
                doc = docs.get(key)
                if (doc is None or not doc["base"] or doc["chunk_range"] != entry["base_range"]
                        or entry["status"] != states.PUBLISHED or doc["status"] != states.PUBLISHED):
                    problems.append(f"{kind} version {pointer['version']}: frozen base document {key[0]} is missing, "
                                    "not published or not the frozen rows")
            if any(d["base"] and key not in base_registry for key, d in docs.items()):
                problems.append(f"{kind} version {pointer['version']} has base documents the registry does not know")
            have = {k: d["status"] for k, d in docs.items()}
            diff = [f"{k[0]} v{k[1]}: registry {expected.get(k) or 'not visible'}, index {have.get(k) or 'absent'}"
                    for k in sorted(set(expected) | set(have)) if expected.get(k) != have.get(k)]
            if diff:
                message = f"{kind} version {pointer['version']} differs from the registry: " + "; ".join(diff)
                if kind == "public" and override and override["version"] == pointer["version"]:
                    warnings.append("expected while the emergency override is active: " + message)
                else:
                    problems.append(message)
        if override:
            pointer = read_pointer(self.cfg, "public")
            if not pointer or pointer["version"] != override["version"]:
                problems.append(f"emergency override names version {override['version']} but CURRENT is "
                                f"{pointer and pointer['version']}")
            warnings.append(f"emergency override active since {override['at']} ({override['reason']}): publish, "
                            "withdraw, supersede, republish and rollback are blocked until reconcile()")
        return {"problems": problems, "warnings": warnings}

    def _assert_consistent(self) -> None:
        problems = self.consistency()["problems"]
        if problems:
            raise IntegrityError("registry and index versions disagree after the operation:\n  - "
                                 + "\n  - ".join(problems))

    def verify(self) -> Dict[str, Any]:
        """Fully verify both pointers' versions, uploads and units, and the registry/index consistency."""
        state = self.registry.load()
        report = {"ok": True, "problems": [], "warnings": [], "versions": {}}
        for kind in POINTERS:
            if read_pointer(self.cfg, kind) is None:
                continue
            try:
                store = open_pointer(self.cfg, kind)
                report["versions"][kind] = {"version": store.kb["version"], "passages": len(store.records),
                                            "documents": [(d["doc_id"], d["doc_version"], d["status"])
                                                          for d in store.kb["documents"]]}
            except KBError as e:
                report["problems"].append(f"{kind}: {e}")
        consistency = self.consistency(state)
        report["problems"] += consistency["problems"]
        report["warnings"] += consistency["warnings"]
        for d in state["documents"]:
            for ref in (d.get("dataset"), d.get("source_file"), d.get("units")):
                if ref and ref.get("path") and sha256_file(self.cfg.root / ref["path"]) != ref["sha256"]:
                    report["problems"].append(f"{d['doc_id']} v{d['doc_version']}: {ref['path']} hash mismatch")
        report["active_override"] = state.get("active_override")
        report["ok"] = not report["problems"]
        return report

    def recover(self, actor: Actor) -> Dict[str, Any]:
        """Run recovery explicitly (it also runs automatically at the start of every write operation)."""
        self._require(actor, ROLE_ADMIN)
        with self._operation("recover", actor):
            return self.last_recovery

    def unlock(self, actor: Actor) -> Optional[dict]:
        self._require(actor, ROLE_ADMIN)
        holder = force_unlock(self.cfg.lock_path)
        self.journal.append({"event": "unlock", "actor": actor.name, "at": self._now(), "holder": holder})
        return holder
