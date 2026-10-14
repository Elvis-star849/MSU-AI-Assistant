"""
Assistant configuration profiles (selected by MSU_ASSISTANT_PROFILE).

c3_public_0005 (default)  The configuration that passed the pre-registered held-out release gates
                          (remediation/REMEDIATION_FINAL_REPORT.md): KB PublicRetriever on the active public pointer
                          (verified to be version 0005: yearbooks + 2027 road map), G2 grounding prompt, F2 evidence
                          formatting, gpt-oss-20b. Built exactly as in the evaluation, so the app sends the same messages.
baseline                  The previous app: Stage 6 retriever over faiss_store_v2 (yearbooks only), S7-0 prompt.
                          Rollback: set MSU_ASSISTANT_PROFILE=baseline and restart.

The public profile never opens the staging pointer (KB 0006, unpublished 2027 intake advert) and never writes or
switches a pointer. src/c3_candidate.py is a byte-for-byte copy of the frozen remediation/candidate.py (checked by tests).
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from src import c3_candidate
from src.context import build_messages
from src.llm.base import Message

ROOT = Path(__file__).resolve().parents[1]
PROFILE_ENV = "MSU_ASSISTANT_PROFILE"
C3 = "c3_public_0005"
BASELINE = "baseline"
PROFILES = (C3, BASELINE)
DEFAULT_PROFILE = C3
C3_PROMPT_VERSION = f"{c3_candidate.G2_PROMPT_VERSION}+F2"
CANDIDATE_SHA256 = "3abeaa7801567faf"   # first 16 hex of the frozen remediation/candidate.py (CANDIDATE_FREEZE.json)
EXPECTED_PUBLIC = {"version": "0005",
                   "manifest_sha256": "25956ff5099f876a23b1f5d7c1d5daefc977ee3625a0345502698b2f71a1c82c"}
LABELS = {C3: "C3 - public knowledge base 0005 (yearbooks + 2027 road map)",
          BASELINE: "Baseline - yearbook index (rollback configuration)"}


class ProfileError(RuntimeError):
    """The requested profile is unknown or its knowledge base does not match the evaluated version."""


def current_profile(env: Optional[Mapping[str, str]] = None) -> str:
    value = ((os.environ if env is None else env).get(PROFILE_ENV) or "").strip().lower() or DEFAULT_PROFILE
    if value not in PROFILES:
        raise ProfileError(f"unknown {PROFILE_ENV} {value!r}; use one of {', '.join(PROFILES)}")
    return value


def verify_public_pointer(kb_root: Path = ROOT / "knowledge_base") -> Dict[str, Any]:
    """Read-only check that the active public pointer is the evaluated version 0005 with its recorded manifest."""
    from src.kb.config import KBConfig
    from src.kb.versions import read_pointer
    pointer = read_pointer(KBConfig(root=kb_root), "public")
    if not pointer or pointer.get("kind") != "public":
        raise ProfileError("no public knowledge-base version is active")
    found = {k: pointer.get(k) for k in EXPECTED_PUBLIC}
    if found != EXPECTED_PUBLIC:
        raise ProfileError(f"active public knowledge base {found} is not the evaluated version {EXPECTED_PUBLIC}")
    return pointer


def open_public_retriever(models: Any, kb_root: Path = ROOT / "knowledge_base") -> Any:
    """PublicRetriever on the verified public pointer, sharing the loaded embedding model and MiniLM reranker of the
    Stage 6 retriever `models` (same wiring as the held-out freeze, remediation/heldout/freeze_heldout.py)."""
    from src.kb.config import KBConfig
    from src.kb.retriever import PublicRetriever
    verify_public_pointer(kb_root)
    retriever = PublicRetriever.open(KBConfig(root=kb_root), reranker=models._reranker)
    retriever.store._embedder = models._store.embedder
    if retriever.version != EXPECTED_PUBLIC["version"]:
        raise ProfileError(f"opened public version {retriever.version}, expected {EXPECTED_PUBLIC['version']}")
    return retriever


def build_c3_messages(question: str, evidence: List[Dict[str, Any]]) -> List[Message]:
    """G2 system prompt + F2-formatted user message (same passages, nothing removed), as evaluated."""
    messages = build_messages(question, evidence, system_prompt=c3_candidate.G2_SYSTEM_PROMPT)
    user = c3_candidate.format_user_message(question, "public", evidence, messages[1].content)
    return [messages[0], Message("user", user)]


build_c3_messages.prompt_version = C3_PROMPT_VERSION
