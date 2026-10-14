"""
Knowledge-base configuration, profiles and actors.

Profiles (D2): "development" (two-person rule off) and "production" (two-person rule on). The profile comes from,
in order: the KBConfig argument, the KB_PROFILE environment variable, knowledge_base/kb_config.json, "development".
An explicit "two_person_rule" (argument, KB_TWO_PERSON_RULE=1/0, or kb_config.json) overrides the profile default.
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, FrozenSet, Optional

from src.embedding import EMBEDDING_MODEL

PROFILES = {"development": {"two_person_rule": False}, "production": {"two_person_rule": True}}

# Revision of BAAI/bge-small-en-v1.5 that produced the frozen vectors (eval/stage6/s6_6_freeze.json)
EMBEDDING_REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
EMBEDDING_RECIPE = "heading_store.index_text"   # citation header + heading line + body

ROLE_UPLOADER, ROLE_APPROVER, ROLE_ADMIN = "kb_uploader", "kb_approver", "kb_admin"
ROLES = frozenset({ROLE_UPLOADER, ROLE_APPROVER, ROLE_ADMIN})


@dataclass(frozen=True)
class Actor:
    """Who performs an operation. A Django integration maps users and groups to these roles."""
    name: str
    roles: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self):
        if not self.name or not isinstance(self.name, str):
            raise ValueError("actor name is required")
        object.__setattr__(self, "roles", frozenset(self.roles))
        unknown = self.roles - ROLES
        if unknown:
            raise ValueError(f"unknown roles: {sorted(unknown)}")

    def has_any(self, *roles: str) -> bool:
        return ROLE_ADMIN in self.roles or bool(self.roles & set(roles))


def _flag(value: Optional[str]) -> Optional[bool]:
    if value is None or value == "":
        return None
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class KBConfig:
    root: Path
    profile: Optional[str] = None
    two_person_rule: Optional[bool] = None
    retention_public: int = 10                 # D4: frozen base + the 10 most recent public versions
    near_duplicate_threshold: float = 0.97
    max_tokens: int = 512
    embedding_model: str = EMBEDDING_MODEL
    embedding_revision: str = EMBEDDING_REVISION
    embedding_recipe: str = EMBEDDING_RECIPE
    filter_method: str = "selector"            # "selector" (FAISS IDSelector) or "overfetch" (tested fallback)
    io_retries: int = 8                         # Windows/OneDrive: retries when a file is briefly held
    io_retry_delay_s: float = 0.25
    clock: Callable[[], str] = None             # returns an ISO-8601 UTC timestamp; injectable for tests

    def __post_init__(self):
        self.root = Path(self.root)
        file_cfg = {}
        cfg_path = self.root / "kb_config.json"
        if cfg_path.is_file():
            file_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.profile = self.profile or os.environ.get("KB_PROFILE") or file_cfg.get("profile") or "development"
        if self.profile not in PROFILES:
            raise ValueError(f"profile must be one of {sorted(PROFILES)}")
        if self.two_person_rule is None:
            explicit = _flag(os.environ.get("KB_TWO_PERSON_RULE"))
            if explicit is None and "two_person_rule" in file_cfg:
                explicit = bool(file_cfg["two_person_rule"])
            self.two_person_rule = PROFILES[self.profile]["two_person_rule"] if explicit is None else explicit
        if self.filter_method not in ("selector", "overfetch"):
            raise ValueError("filter_method must be 'selector' or 'overfetch'")
        if self.clock is None:
            from datetime import datetime, timezone
            self.clock = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Layout
    @property
    def registry_path(self) -> Path: return self.root / "registry.json"
    @property
    def uploads_dir(self) -> Path: return self.root / "uploads"
    @property
    def units_dir(self) -> Path: return self.root / "units"
    @property
    def validation_dir(self) -> Path: return self.root / "validation"
    @property
    def embeddings_dir(self) -> Path: return self.root / "embeddings"
    @property
    def store_dir(self) -> Path: return self.root / "store"
    @property
    def versions_dir(self) -> Path: return self.store_dir / "versions"
    @property
    def journal_path(self) -> Path: return self.root / "ingest_log.jsonl"
    @property
    def quarantine_dir(self) -> Path: return self.root / "quarantine"
    @property
    def archive_dir(self) -> Path: return self.root / "archive"
    @property
    def lock_path(self) -> Path: return self.root / ".lock"
