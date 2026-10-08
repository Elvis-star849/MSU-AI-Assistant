"""
Stage 7 context builder and the S7-0 baseline grounded prompt.

The LLM sees, for each evidence item in rank order: its number, source, page, heading (when the index has one) and
the original chunk text. Retrieval and reranker scores are deliberately left out.
S7-0 prompt: minimal baseline, not optimised. Prompt experiments belong to S7-1.
"""
import hashlib
import json
from typing import Any, Dict, List

from src.llm.base import Message

PROMPT_VERSION = "s7-0-baseline-v1"

SYSTEM_PROMPT = """You answer questions about Midlands State University (MSU) using only the numbered evidence \
passages from the MSU yearbooks supplied in the user's message.

Rules:
- Answer only from the supplied MSU evidence.
- Do not invent MSU information that is not in the evidence.
- If the evidence is insufficient to answer, say so clearly.
- If evidence passages conflict, point out the conflict instead of silently choosing one.
- Do not use general or pretrained knowledge as authoritative MSU information.
- When you use a passage, cite it by its number, source and page."""


def build_context(evidence: List[Dict[str, Any]]) -> str:
    if not evidence:
        return "No evidence passages were retrieved."
    blocks = []
    for n, item in enumerate(evidence, 1):
        lines = [f"[Evidence {n}]", f"Source: {item['source']}", f"Page: {item['page']}"]
        if item.get("heading"):
            lines.append(f"Heading: {item['heading']}")
        lines.append(f"Text:\n{item['text']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_messages(question: str, evidence: List[Dict[str, Any]]) -> List[Message]:
    user = f"Evidence:\n\n{build_context(evidence)}\n\nQuestion: {question}"
    return [Message("system", SYSTEM_PROMPT), Message("user", user)]


def prompt_sha256(messages: List[Message]) -> str:
    canonical = json.dumps([{"role": m.role, "content": m.content} for m in messages], ensure_ascii=False,
                           separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
