"""
Stage 7 answer pipeline:
question -> frozen Stage 6 retrieval (top 5) -> context builder -> LLM interface -> final answer.

Depends only on the provider-independent LLM interface; the evidence (with its ranking information) is returned
alongside the answer for citation, logging and evaluation.
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from src.context import PROMPT_VERSION, build_messages, prompt_sha256
from src.llm.base import GenerationSettings, LLMClient, LLMResponse


@dataclass
class AnswerResult:
    question: str
    answer: str
    evidence: List[Dict[str, Any]]
    prompt_version: str
    prompt_sha256: str
    llm: LLMResponse


def answer_question(question: str, retriever: Any, llm: LLMClient, settings: GenerationSettings,
                    evidence: Optional[List[Dict[str, Any]]] = None,
                    message_builder: Optional[Callable] = None) -> AnswerResult:
    """evidence: pass already-retrieved evidence to reuse it (e.g. to send identical input to two models).
    message_builder: profile-specific prompt (src/profiles.build_c3_messages); default = the S7-0 baseline."""
    if evidence is None:
        evidence = retriever.retrieve(question)
    messages = (message_builder or build_messages)(question, evidence)
    response = llm.generate(messages, settings)
    version = PROMPT_VERSION if message_builder is None else getattr(message_builder, "prompt_version", "custom")
    return AnswerResult(question=question, answer=response.text, evidence=evidence, prompt_version=version,
                        prompt_sha256=prompt_sha256(messages), llm=response)
