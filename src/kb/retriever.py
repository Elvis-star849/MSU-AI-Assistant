"""
Retrieval over knowledge-base versions with the accepted Stage 6 configuration ("main"):
routed_search (T1 vector tie-break) -> top 10 -> MiniLM reranker with heading -> best 5.

PublicRetriever  opens only CURRENT; refuses any version containing a document that is not published.
StagingRetriever opens only STAGING and requires an authorised administrator (kb_approver or kb_admin). It is a
                 separate class on purpose: the public app has no setting that can select it.
Results are the Stage 7 evidence items plus "passage_uid" (the stable external identifier).
"""
from typing import Any, Dict, List, Optional

from src.evidence import CONFIGURATIONS, to_evidence
from src.kb.config import ROLE_APPROVER, Actor, KBConfig
from src.kb.errors import IntegrityError, PermissionDenied
from src.kb.states import PUBLISHED
from src.kb.store import KBStore
from src.kb.versions import open_pointer

ACCEPTED = CONFIGURATIONS["main"]          # tie_break vector, pool 10, MiniLM, with_heading, top_k 5


class _KBRetriever:
    kind: str = ""
    configuration: str = ""

    def __init__(self, store: KBStore, reranker: Any = None):
        self._store = store
        self._reranker = reranker

    @property
    def store(self) -> KBStore:
        return self._store

    @property
    def version(self) -> str:
        return self._store.kb["version"]

    def _rerank(self, question, candidates):
        if self._reranker is None:
            from src.rerank import RERANKERS, Reranker
            self._reranker = Reranker(RERANKERS[ACCEPTED["reranker"]])
        return self._reranker.rerank(question, candidates, with_heading=ACCEPTED["with_heading"])

    def retrieve(self, question: str) -> List[Dict[str, Any]]:
        from src.retrieval_v2 import routed_search
        candidates = routed_search(self._store, question, ACCEPTED["pool"], ACCEPTED["tie_break"])
        ranked = self._rerank(question, candidates)
        return [{**to_evidence(r, self.configuration), "passage_uid": r["passage_uid"]}
                for r in ranked[:ACCEPTED["top_k"]]]


class PublicRetriever(_KBRetriever):
    kind, configuration = "public", "kb_public"

    @classmethod
    def open(cls, config: KBConfig, reranker: Any = None) -> "PublicRetriever":
        store = open_pointer(config, "public")
        not_published = [(d["doc_id"], d["status"]) for d in store.kb["documents"] if d["status"] != PUBLISHED]
        if not_published:
            raise IntegrityError(f"public version contains unpublished documents: {not_published}")
        return cls(store, reranker)


class StagingRetriever(_KBRetriever):
    kind, configuration = "staging", "kb_staging"

    @classmethod
    def open(cls, config: KBConfig, actor: Optional[Actor], reranker: Any = None) -> "StagingRetriever":
        if not isinstance(actor, Actor) or not actor.has_any(ROLE_APPROVER):
            raise PermissionDenied("staging search is restricted to authorised administrators "
                                   "(kb_approver or kb_admin)")
        return cls(open_pointer(config, "staging"), reranker)
