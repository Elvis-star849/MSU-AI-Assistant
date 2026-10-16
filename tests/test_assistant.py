"""MSU AI Assistant prototype: service-layer tests and headless UI tests (Streamlit AppTest). No live Groq calls.

Run from the project root: python -m unittest discover -s tests -t .
"""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.assistant import (ACCEPTED_GENERATION, EXAMPLE_QUESTIONS, NO_EVIDENCE_MESSAGE, Assistant, AssistantResult,
                           escape_markdown, friendly_error, passage_body)
from src.context import SYSTEM_PROMPT
from src.llm import LLMConfig, LLMError
from src.llm.base import GenerationSettings, LLMClient, LLMResponse

SETTINGS = GenerationSettings(model="openai/gpt-oss-20b", retry_backoff_s=0.0)
AMBIGUITY = [{"code": "SEMA204", "titles": [
    {"title": "Real Analysis", "pages": ["MSU Humanities Yearbook p. 556"], "in_results": True},
    {"title": "Introduction to Numerical Methods", "pages": ["MSU Humanities Yearbook p. 571"], "in_results": False}]}]


def item(rank, text="Body text.", heading="Section: Council > Chair"):
    return {"rank": rank, "chunk_id": 100 + rank, "source": "MSU Humanities Yearbook", "page": 10 + rank,
            "heading": heading, "text": f"[MSU Humanities Yearbook, p. {10 + rank}]\n{text} {rank}",
            "retrieval_rank": rank + 1, "retrieval_score": 0.5, "rerank_score": 3.0 - rank, "route": "vector",
            "configuration": "main"}


class FakeRetriever:
    """Question-dependent fake: 'WiFi' -> no evidence; 'boom' -> retrieval failure; otherwise 3 passages."""
    def retrieve(self, question):
        if "boom" in question:
            raise RuntimeError("index unavailable")
        return [] if "WiFi" in question else [item(1), item(2, heading=""), item(3)]


def fake_ambiguity(question, evidence, ambiguous):
    return AMBIGUITY if "SEMA" in question else []


class FakeLLM(LLMClient):
    """Real LLMClient path (retries, latency); 'MECDP704' -> rate-limit failure."""
    provider = "fake"

    def __init__(self):
        super().__init__(sleep=lambda s: None)
        self.messages = []

    def _complete(self, messages, settings):
        self.messages.append(messages)
        if "MECDP704" in messages[1].content:
            raise LLMError("rate_limit", "Groq request failed: rate_limit (HTTP 429)", status_code=429)
        return LLMResponse(text="Grounded answer citing Evidence 1.", provider="fake", requested_model=settings.model,
                           returned_model=settings.model, finish_reason="stop", usage={"total_tokens": 42})


def fake_assistant(llm=None, **kw):
    return Assistant(FakeRetriever(), llm=llm, settings=SETTINGS, ambiguity_fn=fake_ambiguity, **kw)


class ServiceTests(unittest.TestCase):
    def test_answered_with_numbered_sources(self):
        llm = FakeLLM()
        r = fake_assistant(llm).ask("  Who chairs Council?  ")
        self.assertEqual((r.status, r.answer, r.question), ("answered", "Grounded answer citing Evidence 1.",
                                                           "Who chairs Council?"))
        self.assertEqual([s["number"] for s in r.sources], [1, 2, 3])
        s1 = r.sources[0]
        self.assertEqual((s1["document"], s1["pdf_page"], s1["heading"], s1["passage"]),
                         ("MSU Humanities Yearbook", 11, "Council > Chair", "Body text. 1"))
        self.assertIsNone(r.sources[1]["heading"])
        self.assertEqual((r.usage, r.model, r.route), ({"total_tokens": 42}, "openai/gpt-oss-20b", "vector"))
        self.assertTrue({"retrieval", "generation", "total"} <= set(r.timings_ms))

    def test_accepted_prompt_used_and_ambiguity_not_injected(self):
        llm = FakeLLM()
        r = fake_assistant(llm).ask("SEMA 204")
        self.assertEqual(r.ambiguity, AMBIGUITY)  # returned for display
        system, user = llm.messages[0]
        self.assertEqual(system.content, SYSTEM_PROMPT)  # s7-0-baseline-v1 unchanged
        for text in ("Real Analysis", "Introduction to Numerical Methods", "SEMA204 is listed"):
            self.assertNotIn(text, user.content)
        self.assertIn("[Evidence 1]", user.content)

    def test_no_evidence_skips_llm(self):
        llm = FakeLLM()
        r = fake_assistant(llm).ask("What is the WiFi password?")
        self.assertEqual((r.status, r.answer, r.sources), ("no_evidence", NO_EVIDENCE_MESSAGE, []))
        self.assertEqual(llm.messages, [])

    def test_llm_failure_keeps_evidence(self):
        r = fake_assistant(FakeLLM()).ask("How many credits is MECDP704 worth?")
        self.assertEqual((r.status, r.error_kind, len(r.sources)), ("generation_error", "rate_limit", 3))
        self.assertIn("busy", r.error_message)
        self.assertIn("still shown below", r.error_message)
        self.assertIsNone(r.answer)

    def test_unexpected_llm_exception(self):
        def broken(*a, **k):
            raise RuntimeError("bug")
        r = Assistant(FakeRetriever(), llm=FakeLLM(), settings=SETTINGS, ambiguity_fn=fake_ambiguity,
                      answer_fn=broken).ask("Who chairs Council?")
        self.assertEqual((r.status, r.error_kind, len(r.sources)), ("generation_error", "unknown", 3))

    def test_retrieval_failure(self):
        r = fake_assistant(FakeLLM()).ask("boom")
        self.assertEqual((r.status, r.sources), ("retrieval_error", []))
        self.assertIn("Searching the yearbooks failed", r.error_message)

    def test_ambiguity_failure_does_not_block_answer(self):
        def broken(*a):
            raise RuntimeError("bad metadata")
        r = Assistant(FakeRetriever(), llm=FakeLLM(), settings=SETTINGS, ambiguity_fn=broken).ask("SEMA 204")
        self.assertEqual((r.status, r.ambiguity), ("answered", []))

    def test_offline_mode_shows_evidence_without_llm(self):
        r = fake_assistant(None, llm_unavailable_reason="Answer generation is switched off (retrieval-only mode).") \
            .ask("Who chairs Council?")
        self.assertEqual((r.status, r.error_kind, len(r.sources)), ("generation_error", "unavailable", 3))
        self.assertIn("retrieval-only", r.error_message)

    def test_empty_question_rejected(self):
        with self.assertRaises(ValueError):
            fake_assistant(FakeLLM()).ask("   ")

    def test_create_enforces_accepted_configuration(self):
        class StubRetriever:
            def __init__(self, configuration):
                self.configuration = configuration
                self._store = SimpleNamespace(records=[])

            def _load(self):
                self.loaded = True

            def retrieve(self, question):
                self.warmed_up = question
                return []

        cfg = GenerationSettings(model="openai/gpt-oss-120b", temperature=0.7, reasoning_effort="high",
                                 max_completion_tokens=100, timeout_s=30.0, max_retries=1)
        with patch("src.evidence.Stage6Retriever", StubRetriever), \
                patch("src.ambiguity.code_titles", lambda records: {}), \
                patch("src.ambiguity.ambiguous_codes", lambda titles: {"x": []}):
            # this test pins the baseline (rollback) wiring; the C3 profile is covered in tests/test_c3_profile.py
            a = Assistant.create(config_loader=lambda: LLMConfig("groq", cfg, api_key="fake-test-key-not-real"),
                                 profile="baseline")
            self.assertEqual(a.retriever.configuration, "main")
            self.assertTrue(a.retriever.loaded)
            self.assertTrue(a.retriever.warmed_up)
            self.assertEqual(a.ambiguous_codes, {"x": []})
            s = a.settings
            self.assertEqual({k: getattr(s, k) for k in ACCEPTED_GENERATION}, ACCEPTED_GENERATION)
            self.assertEqual((s.timeout_s, s.max_retries), (30.0, 1))  # infrastructure settings from config
            self.assertIsNotNone(a.llm)
            self.assertNotIn("fake-test-key-not-real", repr(vars(a)))
            missing = Assistant.create(config_loader=lambda: LLMConfig("groq", cfg, api_key=None), profile="baseline")
            self.assertIsNone(missing.llm)
            self.assertIn("not configured", missing.llm_unavailable_reason)
            offline = Assistant.create(offline=True, config_loader=lambda: self.fail("must not load config"),
                                       profile="baseline")
            self.assertIsNone(offline.llm)

    def test_helpers(self):
        self.assertEqual(passage_body("[MSU Sciences Yearbook Vol. 2, p. 3]\nText\nmore"), "Text\nmore")
        self.assertEqual(passage_body("No header"), "No header")
        self.assertEqual(escape_markdown("1. a *b*\n# c"), "1\\. a \\*b\\*  \n\\# c")
        self.assertIn("busy", friendly_error("rate_limit"))
        self.assertEqual(friendly_error("model_not_found"), friendly_error(None))

    def test_examples_are_stage5_development_questions(self):
        with open("eval/stage5_questions.json", encoding="utf-8") as f:
            dev = {q["question"] for q in json.load(f)["questions"]}
        self.assertTrue(set(EXAMPLE_QUESTIONS) <= dev)


class RecordingRetriever(FakeRetriever):
    """Records every retrieval query, so tests can see the standalone question the RAG pipeline received."""
    def __init__(self, log):
        self.log = log

    def retrieve(self, question):
        self.log.append(question)
        return super().retrieve(question)


class AppUITests(unittest.TestCase):
    """Runs the real chat app.py headless with a fake assistant (no index load, no Groq)."""
    offline = False

    def setUp(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_resource.clear()
        self.queries = []
        llm = None if self.offline else FakeLLM()
        reason = "Answer generation is switched off (retrieval-only mode)." if self.offline else None
        fake = Assistant(RecordingRetriever(self.queries), llm=llm, settings=SETTINGS, ambiguity_fn=fake_ambiguity,
                         llm_unavailable_reason=reason)
        create = patch.object(Assistant, "create", classmethod(lambda cls, offline=False: fake))
        create.start()
        self.addCleanup(create.stop)
        env = patch.dict(os.environ, {"MSU_ASSISTANT_OFFLINE": "1" if self.offline else "",
                                      "MSU_ASSISTANT_DEV_MODE": "1"})  # Technical details are developer-mode only
        env.start()
        self.addCleanup(env.stop)
        app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        self.at = AppTest.from_file(app, default_timeout=60)
        self.at.run()

    def ask(self, question):
        self.at.chat_input[0].set_value(question).run()
        self.assertFalse(self.at.exception)

    def chat_id(self):
        return self.at.session_state["chats"].current_id

    def message(self, role, index):
        return self.at.get_by_key(f"{'u' if role == 'user' else 'a'}msg-{self.chat_id()}-{index}")

    def text(self, block, kind="markdown"):
        return " ".join(e.value for e in getattr(block, kind))


class ChatLayoutTests(AppUITests):
    def test_empty_chat_screen_and_sidebar(self):
        self.assertFalse(self.at.exception)
        self.assertEqual(self.at.title[0].value, "MSU AI Assistant")
        self.assertIn("How can I help you with MSU today?", self.text(self.at))
        self.assertEqual(sorted(b.label for b in self.at.button if b.key and b.key.startswith("example-")),
                         sorted(EXAMPLE_QUESTIONS))
        self.assertEqual(len(self.at.chat_input), 1)
        side = self.at.sidebar
        self.assertEqual(side.button[0].label, "New chat")  # New chat first
        self.assertEqual(side.text_input[0].placeholder, "Search chats...")
        self.assertIn("Basic contextual follow-up support", self.text(side))
        self.assertIn("complete standalone question", self.text(side))

    def test_chronological_left_right_messages_and_examples_hidden(self):
        self.ask("Describe BM134")
        self.ask("How many credits is it?")
        self.assertEqual([m.name for m in self.at.chat_message], ["user", "assistant", "user", "assistant"])
        for i in (0, 1):
            self.assertEqual(self.message("user", i).chat_message[0].name, "user")
            self.assertEqual(self.message("assistant", i).chat_message[0].name, "assistant")
        self.assertEqual(self.text(self.message("user", 1)), "How many credits is it?")  # original wording shown
        self.assertFalse([b for b in self.at.button if b.key and b.key.startswith("example-")])
        with open("app.py", encoding="utf-8") as f:
            css = f.read()
        self.assertRegex(css, r'\[class\*="st-key-umsg-"\] \{[^}]*margin-right: auto')  # user bubbles: left
        self.assertRegex(css, r'\[class\*="st-key-amsg-"\] \{[^}]*margin-left: auto')  # assistant bubbles: right

    def test_follow_up_resolution_and_interpreted_note(self):
        for q in ("Describe BM134", "How many credits is it?", "Which semester is it taught in?", "Describe SEMA204"):
            self.ask(q)
        self.assertEqual(self.queries, ["Describe BM134", "How many credits is BM134?",
                                        "Which semester is BM134 taught in?", "Describe SEMA204"])
        notes = [self.text(self.message("assistant", i), "caption") for i in range(4)]
        self.assertNotIn("Interpreted as", notes[0])
        self.assertIn("Interpreted as: How many credits is BM134?", notes[1])
        self.assertIn("Interpreted as: Which semester is BM134 taught in?", notes[2])
        self.assertNotIn("Interpreted as", notes[3])

    def test_sources_technical_and_ambiguity_under_correct_response(self):
        self.ask("Describe BM134")
        self.ask("SEMA 204")
        first, second = self.message("assistant", 0), self.message("assistant", 1)
        for block in (first, second):
            self.assertEqual([e.label for e in block.expander], ["Sources (3)", "Technical details"])
        self.assertIn("Grounded answer citing Evidence 1.", self.text(first))
        sources = self.text(first.expander[0])
        self.assertIn("**[1] MSU Humanities Yearbook** — PDF page 11", sources)
        self.assertIn("**Section at start of passage:** Council \\> Chair", sources)
        self.assertIn("**[2] MSU Humanities Yearbook** — PDF page 12", sources)
        self.assertIn("Body text\\. 1", sources)
        self.assertIn("Retrieval query:", self.text(first.expander[1]))
        self.assertEqual(len(first.warning), 0)
        self.assertIn("SEMA204 is listed with more than one title", self.text(second, "warning"))

    def test_new_chat_search_and_switching(self):
        self.ask("Describe BM134")
        first = self.chat_id()
        self.at.button(key="new-chat").click().run()
        self.assertNotEqual(self.chat_id(), first)
        self.assertEqual(len(self.at.chat_message), 0)  # fresh conversation
        self.ask("How many credits is it?")  # no context in the new chat: not rewritten
        self.assertEqual(self.queries[-1], "How many credits is it?")
        second = self.chat_id()
        self.at.button(key="new-chat").click().run()
        self.ask("SEMA 204")
        self.assertEqual([b.label for b in self.at.sidebar.button if b.key.startswith("chat-")],
                         ["SEMA 204", "How many credits is it?", "Describe BM134"])  # newest first
        self.at.text_input(key="search-chats").input("bm1").run()
        self.assertEqual([b.label for b in self.at.sidebar.button if b.key.startswith("chat-")], ["Describe BM134"])
        self.at.button(key=f"chat-{first}").click().run()
        self.assertEqual(self.chat_id(), first)
        self.assertEqual(self.text(self.message("user", 0)), "Describe BM134")  # conversation restored
        self.ask("Which semester is it taught in?")  # context restored with the chat
        self.assertEqual(self.queries[-1], "Which semester is BM134 taught in?")
        self.assertIn(second, self.at.session_state["chats"].sessions)

    def test_no_evidence_and_error_state_keeps_evidence(self):
        self.ask("What is the WiFi password?")
        self.assertIn(NO_EVIDENCE_MESSAGE, self.text(self.message("assistant", 0), "info"))
        self.ask("How many credits is MECDP704 worth?")
        block = self.message("assistant", 1)
        self.assertIn("busy", self.text(block, "error"))
        self.assertEqual(block.expander[0].label, "Sources (3)")  # evidence still shown


class OfflineModeTests(AppUITests):
    offline = True

    def test_retrieval_only_mode(self):
        self.assertIn("retrieval-only mode", self.text(self.at, "warning"))
        self.assertIn("Retrieval-only mode", self.text(self.at.sidebar, "info"))
        self.ask("Describe BM134")
        block = self.message("assistant", 0)
        self.assertIn("retrieval-only mode", self.text(block, "error"))
        self.assertEqual(block.expander[0].label, "Sources (3)")


if __name__ == "__main__":
    unittest.main()
