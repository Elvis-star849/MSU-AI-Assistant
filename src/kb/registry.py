"""
Document registry.

The service works on a registry *state*: {"schema_version": 1, "documents": [entry, ...], "pointer_events": [...]}.
A backend only loads and saves that state atomically, so the engine does not depend on how it is stored:
JsonRegistry (knowledge_base/registry.json) now; a Django-model backend can implement the same two methods later.
"""
import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from src.kb.errors import UnknownDocument
from src.kb.fsutil import atomic_write_json, canonical_json, read_json, sha256_bytes

SCHEMA_VERSION = 1


def empty_state() -> Dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "documents": [], "pointer_events": []}


class RegistryBackend(Protocol):
    def load(self) -> Dict[str, Any]: ...
    def save(self, state: Dict[str, Any]) -> None: ...


class JsonRegistry:
    def __init__(self, path: Path, retries: int = 8, delay_s: float = 0.25):
        self.path = Path(path)
        self._io = {"retries": retries, "delay_s": delay_s}

    def load(self) -> Dict[str, Any]:
        if not self.path.is_file():
            return empty_state()
        state = read_json(self.path)
        if state.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"registry schema_version {state.get('schema_version')!r} is not supported")
        return state

    def save(self, state: Dict[str, Any]) -> None:
        atomic_write_json(self.path, state, **self._io)


def state_sha256(state: Dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(state))


# Helpers on a state (backend independent) --------------------------------------------------------

def find(state: Dict[str, Any], doc_id: str, doc_version: Optional[int] = None) -> Dict[str, Any]:
    """The entry for doc_id at doc_version (default: its latest version)."""
    entries = [d for d in state["documents"] if d["doc_id"] == doc_id]
    if doc_version is not None:
        entries = [d for d in entries if d["doc_version"] == doc_version]
    if not entries:
        raise UnknownDocument(f"{doc_id} v{doc_version}" if doc_version else doc_id)
    return max(entries, key=lambda d: d["doc_version"])


def find_by_sha(state: Dict[str, Any], sha256: str) -> List[Dict[str, Any]]:
    return [d for d in state["documents"] if d.get("dataset", {}).get("sha256") == sha256]


def documents_with(state: Dict[str, Any], statuses) -> List[Dict[str, Any]]:
    return [d for d in state["documents"] if d["status"] in statuses]


def ordered_for_build(state: Dict[str, Any], statuses) -> List[Dict[str, Any]]:
    """Documents in index order: base first (registry order), then published by publish_seq, then the rest by
    stage_seq. The order is deterministic, so identical registry states build identical versions."""
    docs = documents_with(state, statuses)
    base = [d for d in docs if d.get("base")]
    published = sorted((d for d in docs if not d.get("base") and d.get("publish_seq") is not None),
                       key=lambda d: d["publish_seq"])
    others = sorted((d for d in docs if not d.get("base") and d.get("publish_seq") is None),
                    key=lambda d: (d.get("stage_seq") or 0, d["doc_id"], d["doc_version"]))
    return base + published + others


def clone(state: Dict[str, Any]) -> Dict[str, Any]:
    return copy.deepcopy(state)
