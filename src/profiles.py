"""
Assistant configuration profiles (selected by MSU_ASSISTANT_PROFILE).

c3_intake_0006 (default)  Owner-approved local demonstration with the 2027 intake advert: KB StagingRetriever on the
                          staging pointer, verified to be version 0006 = everything in public 0005 (yearbooks + 2027
                          road map, identical records) + the MSU January/February 2027 Intake Advert (226 records).
                          G2 grounding prompt + F2 evidence formatting, gpt-oss-20b. Same wiring as the held-out
                          evaluation of the 22 intake questions (C3 there: 0 critical claims; reliable-sufficient 0.545).
c3_public_0005            The configuration that passed the pre-registered public release gates: KB PublicRetriever
                          on the active public pointer (verified version 0005: yearbooks + 2027 road map; no advert).
baseline                  The previous app: Stage 6 retriever over faiss_store_v2 (yearbooks only), S7-0 prompt.

Profiles only read knowledge-base versions; none writes or switches a pointer. The intake profile reads the staging
version as the local-demonstration actor "msu-assistant-local-demo" (kb_approver role), on the owner's approval of
2026-10-14 to include the 2027 intake advert in the local demonstration (not for public internet hosting).
src/c3_candidate.py is a byte-for-byte copy of the frozen remediation/candidate.py (checked by tests).
"""
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from src import c3_candidate
from src.context import build_messages
from src.llm.base import Message

ROOT = Path(__file__).resolve().parents[1]
PROFILE_ENV = "MSU_ASSISTANT_PROFILE"
INTAKE = "c3_intake_0006"
C3 = "c3_public_0005"
BASELINE = "baseline"
PROFILES = (INTAKE, C3, BASELINE)
DEFAULT_PROFILE = INTAKE
KB_PROFILES = (INTAKE, C3)
C3_PROMPT_VERSION = f"{c3_candidate.G2_PROMPT_VERSION}+F2"
CANDIDATE_SHA256 = "3abeaa7801567faf"   # first 16 hex of the frozen remediation/candidate.py (CANDIDATE_FREEZE.json)
EXPECTED_PUBLIC = {"version": "0005",
                   "manifest_sha256": "25956ff5099f876a23b1f5d7c1d5daefc977ee3625a0345502698b2f71a1c82c"}
EXPECTED_STAGING = {"version": "0006",
                    "manifest_sha256": "04169e83fa22291406ae3371d6225348f66519b0e90eb7517c463593d1c9aca6"}
DEMO_ACTOR = "msu-assistant-local-demo"
ADVERT_SOURCE = "MSU January/February 2027 Intake Advert"
ROADMAP_SOURCE = "MSU 2027 Road Map"
LABELS = {INTAKE: "C3 - knowledge base 0006 (yearbooks + 2027 road map + 2027 intake advert)",
          C3: "C3 - public knowledge base 0005 (yearbooks + 2027 road map)",
          BASELINE: "Baseline - yearbook index (rollback configuration)"}


class ProfileError(RuntimeError):
    """The requested profile is unknown or its knowledge base does not match the evaluated version."""


def current_profile(env: Optional[Mapping[str, str]] = None) -> str:
    value = ((os.environ if env is None else env).get(PROFILE_ENV) or "").strip().lower() or DEFAULT_PROFILE
    if value not in PROFILES:
        raise ProfileError(f"unknown {PROFILE_ENV} {value!r}; use one of {', '.join(PROFILES)}")
    return value


def _verify_pointer(kind: str, expected: Dict[str, str], kb_root: Path) -> Dict[str, Any]:
    from src.kb.config import KBConfig
    from src.kb.versions import read_pointer
    pointer = read_pointer(KBConfig(root=kb_root), kind)
    if not pointer or pointer.get("kind") != kind:
        raise ProfileError(f"no {kind} knowledge-base version is active")
    found = {k: pointer.get(k) for k in expected}
    if found != expected:
        raise ProfileError(f"{kind} knowledge base {found} is not the evaluated version {expected}")
    return pointer


def verify_public_pointer(kb_root: Path = ROOT / "knowledge_base") -> Dict[str, Any]:
    """Read-only check that the active public pointer is the evaluated version 0005 with its recorded manifest."""
    return _verify_pointer("public", EXPECTED_PUBLIC, kb_root)


def verify_staging_pointer(kb_root: Path = ROOT / "knowledge_base") -> Dict[str, Any]:
    """Read-only check that the staging pointer is version 0006 (with the 2027 intake advert) and its manifest."""
    return _verify_pointer("staging", EXPECTED_STAGING, kb_root)


def _share_models(retriever: Any, models: Any, expected: Dict[str, str]) -> Any:
    retriever.store._embedder = models._store.embedder
    if retriever.version != expected["version"]:
        raise ProfileError(f"opened version {retriever.version}, expected {expected['version']}")
    return retriever


def open_public_retriever(models: Any, kb_root: Path = ROOT / "knowledge_base") -> Any:
    """PublicRetriever on the verified public pointer, sharing the loaded embedding model and MiniLM reranker of the
    Stage 6 retriever `models` (same wiring as the held-out freeze, remediation/heldout/freeze_heldout.py)."""
    from src.kb.config import KBConfig
    from src.kb.retriever import PublicRetriever
    verify_public_pointer(kb_root)
    return _share_models(PublicRetriever.open(KBConfig(root=kb_root), reranker=models._reranker), models, EXPECTED_PUBLIC)


def open_intake_retriever(models: Any, kb_root: Path = ROOT / "knowledge_base") -> Any:
    """StagingRetriever on the verified staging pointer (0006 = 0005 + 2027 intake advert), read-only, same wiring as
    the held-out freeze of the intake questions."""
    from src.kb.config import Actor, KBConfig
    from src.kb.retriever import StagingRetriever
    verify_staging_pointer(kb_root)
    retriever = StagingRetriever.open(KBConfig(root=kb_root), Actor(DEMO_ACTOR, {"kb_approver"}),
                                      reranker=models._reranker)
    return _share_models(retriever, models, EXPECTED_STAGING)


ADMISSION_WORDS = re.compile(r"\b(?:entry|requirements?|admissions?|admit|apply|applying|applications?|eligib\w*|"
                             r"qualif\w*|intake|[oa][\s'’-]?levels?)\b", re.I)
PROGRAMME_FACT_WORDS = re.compile(r"\b(?:duration|how long|modes?|offered|study options?|visiting|weekend|"
                                  r"block release|conventional|start|starts|begin|begins|commenc\w*)\b", re.I)
PROGRAMME_WORDS = re.compile(r"\b(?:degree|bachelor\w*|master\w*|diploma|certificate|programmes?|course|honours|"
                             r"bsc|ba|bcom|bed|beng|msc|ma|mba|med|mcom|phd)\b", re.I)


def is_intake_question(question: str) -> bool:
    """Admissions vocabulary, or a programme fact (duration, mode, start) asked about a named programme."""
    return bool(ADMISSION_WORDS.search(question) or
                (PROGRAMME_FACT_WORDS.search(question) and PROGRAMME_WORDS.search(question)))
SUPPLEMENT_MAX = 2            # advert records added when none was retrieved
SUPPLEMENT_MIN_SCORE = 1.0    # MiniLM rerank score a supplemented advert record must reach (relevance floor)


class IntakeAwareRetriever:
    """Wraps the 0006 StagingRetriever. For an admissions/intake question whose top 5 contains NO advert passage, it
    searches the advert records only (vector + BM25, then the same MiniLM reranker) and replaces the lowest-ranked
    passages with up to SUPPLEMENT_MAX relevant advert records, so the current 2027 requirements reach the model.
    Questions whose top 5 already contains an advert passage are unchanged (evaluated behaviour)."""

    def __init__(self, base: Any):
        self.base = base
        self._advert_ids = [r["chunk_id"] for r in base.store.records if r["source"] == ADVERT_SOURCE]

    def __getattr__(self, name):          # store, version, _rerank, ... come from the wrapped retriever
        return getattr(self.base, name)

    def retrieve(self, question: str) -> List[Dict[str, Any]]:
        evidence = self.base.retrieve(question)
        if not self._advert_ids or not is_intake_question(question) or \
                any(e["source"] in (ADVERT_SOURCE, ROADMAP_SOURCE) for e in evidence):
            return evidence                # advert already present, or a calendar question: unchanged
        try:
            pool = {}
            for r in self.base.store.vector_search(question, 10, chunk_ids=self._advert_ids) + \
                    self.base.store.bm25_search(question, 10, chunk_ids=self._advert_ids):
                pool.setdefault(r["chunk_id"], r)
            ranked = [r for r in self.base._rerank(question, list(pool.values()))
                      if (r.get("rerank_score") or 0) >= SUPPLEMENT_MIN_SCORE][:SUPPLEMENT_MAX]
        except Exception:
            return evidence                # the supplement is best-effort; never break retrieval
        if not ranked:
            return evidence
        from src.evidence import to_evidence
        extra = [{**to_evidence({**r, "route": "advert_supplement"}, self.base.configuration),
                  "passage_uid": r["passage_uid"]} for r in ranked]
        merged = evidence[:max(0, len(evidence) - len(extra))] + extra
        return [{**e, "rank": i} for i, e in enumerate(merged, 1)]


def open_profile_retriever(profile: str, models: Any) -> Any:
    if profile == INTAKE:
        return IntakeAwareRetriever(open_intake_retriever(models))
    return open_public_retriever(models)


def build_c3_messages(question: str, evidence: List[Dict[str, Any]]) -> List[Message]:
    """G2 system prompt + F2-formatted user message (same passages, nothing removed), as evaluated. G2 already tells
    the model to present the 2027 advert as the current requirement and to attribute yearbook differences; F2 labels
    every passage's source type and marks missing commencement dates as 'not stated'."""
    messages = build_messages(question, evidence, system_prompt=c3_candidate.G2_SYSTEM_PROMPT)
    user = c3_candidate.format_user_message(question, "kb", evidence, messages[1].content)
    return [messages[0], Message("user", user)]


build_c3_messages.prompt_version = C3_PROMPT_VERSION
