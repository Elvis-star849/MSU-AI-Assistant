"""
Basic contextual follow-up support and in-memory chat sessions for the MSU AI Assistant (no UI code, no LLM call).

original question -> rule-based follow-up resolver -> standalone question -> Assistant.ask() (unchanged RAG pipeline)

The resolver uses only previous *user* questions (their standalone form), never assistant answers, so earlier
answers cannot become evidence: every answer is grounded in passages retrieved anew for the standalone question.

Rules (deliberately conservative):
- A question is standalone if it names a course code, if there is no earlier question in the chat, or if it has no
  referring word/opening ("it", "its", "this module", "they", ..., "what about ...", "and ...") or is long.
- A follow-up to a question about exactly one course code has the reference replaced by the code
  ("How many credits is it?" after "Describe BM134" -> "How many credits is BM134?").
- Any other follow-up is appended to the last standalone (non-follow-up) question of the chat.
Complex references or topic changes may need a complete standalone question.
"""
import itertools
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.vectorstore import course_codes  # the same course-code rule retrieval uses

MAX_FOLLOWUP_WORDS = 12
TITLE_CHARS = 40
_OPENERS = re.compile(r"^\s*(what about|how about|and)\b", re.IGNORECASE)
_UNIT = r"(?:module|course|subject|unit)"
# (pattern, replacement template); {code} is the course code. Checked in order; the first that matches is applied.
_CODE_REFERENCES = [
    (re.compile(rf"\b(?:this|that|the same|the) {_UNIT}'s\b", re.IGNORECASE), "{code}'s"),
    (re.compile(rf"\b(?:this|that|the same|the) {_UNIT}\b", re.IGNORECASE), "{code}"),
    (re.compile(r"\b(?:its|their)\b", re.IGNORECASE), "{code}'s"),
    (re.compile(r"\b(?:it|they|them)\b", re.IGNORECASE), "{code}"),
]
_REFERRING = re.compile(rf"\b(?:it|its|they|them|their|(?:this|that|the same|the) {_UNIT})\b", re.IGNORECASE)


def display_code(code: str) -> str:
    """'bm134' -> 'BM134'."""
    return code.upper()


@dataclass
class Resolution:
    original: str
    standalone: str
    is_followup: bool
    rule: str  # "standalone" | "course_code_reference" | "topic_reference"
    context_code: Optional[str] = None


@dataclass
class ChatContext:
    """Built only from user questions: the last standalone question and its single course code, if any."""
    anchor: Optional[str] = None
    code: Optional[str] = None


def is_followup(question: str, context: ChatContext) -> bool:
    if context.anchor is None or course_codes(question):
        return False
    if len(question.split()) > MAX_FOLLOWUP_WORDS:
        return False
    return bool(_REFERRING.search(question) or _OPENERS.match(question))


def resolve(question: str, context: ChatContext) -> Resolution:
    question = question.strip()
    if not is_followup(question, context):
        return Resolution(question, question, False, "standalone")
    if context.code:
        code = display_code(context.code)
        for pattern, template in _CODE_REFERENCES:
            if pattern.search(question):
                standalone = pattern.sub(template.format(code=code), question)
                break
        else:  # "What about the credits?" / "And the semester?"
            standalone = f"{question.rstrip(' ?')} for {code}?"
        return Resolution(question, standalone, True, "course_code_reference", context.code)
    return Resolution(question, f"{context.anchor} {question}", True, "topic_reference")


def context_after(context: ChatContext, resolution: Resolution) -> ChatContext:
    """A standalone question starts a new context; a follow-up keeps the current one."""
    if resolution.is_followup:
        return context
    codes = course_codes(resolution.standalone)
    return ChatContext(anchor=resolution.standalone, code=codes[0] if len(codes) == 1 else None)


@dataclass
class Turn:
    question: str  # what the user typed (shown in the chat)
    resolution: Resolution
    result: Any  # AssistantResult for resolution.standalone


_ids = itertools.count(1)


@dataclass
class ChatSession:
    id: int = field(default_factory=lambda: next(_ids))
    turns: List[Turn] = field(default_factory=list)
    context: ChatContext = field(default_factory=ChatContext)

    @property
    def title(self) -> str:
        if not self.turns:
            return "New chat"
        q = " ".join(self.turns[0].question.split())
        return q if len(q) <= TITLE_CHARS else q[:TITLE_CHARS - 1].rstrip() + "…"

    def ask(self, assistant: Any, question: str) -> Turn:
        """Resolve against this chat's context, answer the standalone question, record the turn."""
        resolution = resolve(question, self.context)
        result = assistant.ask(resolution.standalone)
        turn = Turn(question.strip(), resolution, result)
        self.turns.append(turn)
        self.context = context_after(self.context, resolution)
        return turn


class ChatStore:
    """All chats of one browser session (kept in Streamlit session state only; nothing is persisted)."""

    def __init__(self):
        self.sessions: Dict[int, ChatSession] = {}
        self.current_id = self.new_chat()

    @property
    def current(self) -> ChatSession:
        return self.sessions[self.current_id]

    def new_chat(self) -> int:
        """Start a fresh chat (fresh follow-up context). Previous chats are kept; an empty current chat is reused."""
        if getattr(self, "current_id", None) is not None and not self.current.turns:
            return self.current_id
        session = ChatSession()
        self.sessions[session.id] = session
        self.current_id = session.id
        return session.id

    def switch(self, session_id: int):
        if session_id not in self.sessions:
            raise KeyError(session_id)
        self.current_id = session_id

    def history(self, search: str = "") -> List[ChatSession]:
        """Chats with at least one question, newest first, filtered by title only (no retrieval)."""
        needle = search.strip().lower()
        chats = [s for s in self.sessions.values() if s.turns and needle in s.title.lower()]
        return sorted(chats, key=lambda s: s.id, reverse=True)
