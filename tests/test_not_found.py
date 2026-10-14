"""'Not found' responses show the main answer only: no Sources, no Technical details, no notes (offline, no Groq).

Run from the project root: python -m unittest tests.test_not_found -v
"""
import os
import unittest
from unittest.mock import patch

from src.assistant import NO_EVIDENCE_MESSAGE, Assistant
from src.llm.base import GenerationSettings, LLMError, LLMResponse
from src.safeguards import is_not_found

SETTINGS = GenerationSettings(model="openai/gpt-oss-20b", retry_backoff_s=0.0)
DECLINE = "The MSU documents I searched do not contain any information about the tuition fee for this programme."


def item(rank):
    return {"rank": rank, "chunk_id": rank, "source": "MSU Humanities Yearbook", "page": rank, "heading": "H",
            "text": f"[MSU Humanities Yearbook, p. {rank}]\nPassage {rank}."}


class Retriever:
    def retrieve(self, question):
        return [] if "WiFi" in question else [item(1), item(2), item(3)]


class LLM:
    def generate(self, messages, settings):
        q = messages[1].content
        if "busy" in q:
            raise LLMError("rate_limit", "fake")
        text = DECLINE if "fee" in q else "BM134 is worth 12 credits [Evidence 1]."
        return LLMResponse(text=text, provider="fake", requested_model=settings.model, returned_model=settings.model,
                           finish_reason="stop", usage={})


class DetectionTests(unittest.TestCase):
    def test_not_found_cases(self):
        self.assertTrue(is_not_found("no_evidence", NO_EVIDENCE_MESSAGE))
        self.assertTrue(is_not_found("answered", DECLINE))
        self.assertTrue(is_not_found("answered", "I’m sorry, but I can’t help with that."))
        self.assertTrue(is_not_found("answered", "I could not find this programme in the MSU documents."))

    def test_answers_with_evidence_are_not_not_found(self):
        self.assertFalse(is_not_found("answered", "BM134 is worth 12 credits [Evidence 1]."))
        self.assertFalse(is_not_found("answered", "The advert does not state a commencement date for this "
                                                  "programme【Evidence 1】."))         # a sourced answer
        self.assertFalse(is_not_found("answered", "The documents do not contain any information on fees; the "
                                                  "duration is 4 years [Evidence 2]."))
        self.assertFalse(is_not_found("generation_error", None))                     # errors keep their sources
        self.assertFalse(is_not_found("rejected", None))

    def test_assistant_sets_flag(self):
        a = Assistant(Retriever(), llm=LLM(), settings=SETTINGS, ambiguity_fn=lambda *a: [])
        self.assertTrue(a.ask("What is the WiFi password?").not_found)
        self.assertTrue(a.ask("What is the tuition fee?").not_found)
        self.assertFalse(a.ask("How many credits is BM134?").not_found)
        self.assertFalse(a.ask("busy question").not_found)


class NotFoundUITests(unittest.TestCase):
    """Runs the real app.py headless with a fake assistant."""

    def setUp(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_resource.clear()
        fake = Assistant(Retriever(), llm=LLM(), settings=SETTINGS, ambiguity_fn=lambda *a: [])
        create = patch.object(Assistant, "create", classmethod(lambda cls, offline=False: fake))
        create.start()
        self.addCleanup(create.stop)
        env = patch.dict(os.environ, {"MSU_ASSISTANT_OFFLINE": ""})
        env.start()
        self.addCleanup(env.stop)
        app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        self.at = AppTest.from_file(app, default_timeout=60)
        self.at.run()

    def ask(self, question):
        self.at.chat_input[0].set_value(question).run()
        self.assertFalse(self.at.exception)
        chat = self.at.session_state["chats"]
        return self.at.get_by_key(f"amsg-{chat.current_id}-{len(chat.current.turns) - 1}")

    def test_no_evidence_shows_answer_only(self):
        block = self.ask("What is the WiFi password?")
        self.assertEqual(len(block.expander), 0)                       # no Sources, no Technical details
        self.assertIn(NO_EVIDENCE_MESSAGE, " ".join(e.value for e in block.info))
        self.assertEqual((len(block.warning), len(block.caption)), (0, 0))

    def test_declined_answer_shows_answer_only(self):
        block = self.ask("What is the tuition fee?")
        self.assertEqual(len(block.expander), 0)
        self.assertIn(DECLINE, " ".join(e.value for e in block.markdown))
        self.assertEqual((len(block.info), len(block.warning), len(block.caption)), (0, 0, 0))

    def test_found_answer_and_errors_keep_sources(self):
        found = self.ask("How many credits is BM134?")
        self.assertEqual([e.label for e in found.expander], ["Sources (3)", "Technical details"])
        error = self.ask("busy question")
        self.assertEqual([e.label for e in error.expander], ["Sources (3)", "Technical details"])

    def test_mixed_conversation_keeps_each_turn_correct(self):
        self.ask("How many credits is BM134?")
        self.ask("What is the WiFi password?")
        chat = self.at.session_state["chats"]
        first = self.at.get_by_key(f"amsg-{chat.current_id}-0")
        second = self.at.get_by_key(f"amsg-{chat.current_id}-1")
        self.assertEqual(len(first.expander), 2)
        self.assertEqual(len(second.expander), 0)


if __name__ == "__main__":
    unittest.main()
