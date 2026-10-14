"""
MSU knowledge base: incremental, versioned document ingestion on top of the accepted Stage 6 retrieval.

Independent of any user interface: the CLI (python -m src.kb), notebooks and a future Django admin call
src.kb.service.KnowledgeBase. See audit/stage3_architecture_proposal.md.
"""
from src.kb.config import Actor, KBConfig
from src.kb.errors import KBError
from src.kb.service import KnowledgeBase

__all__ = ["Actor", "KBConfig", "KBError", "KnowledgeBase"]
