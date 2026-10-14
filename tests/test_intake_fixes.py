"""Tests for the three intake fixes (offline, no Groq): query clean-up, advert supplement trigger, miss wording.

Run from the project root: python -m unittest tests.test_intake_fixes -v
"""
import json
import unittest
from pathlib import Path

from src.assistant import Assistant
from src.llm.base import GenerationSettings, LLMResponse
from src.profiles import INTAKE, is_intake_question
from src.query_normalise import normalise_query
from src.safeguards import NOTE_MISS_TIP, miss_tip, present_answer

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = GenerationSettings(model="openai/gpt-oss-20b", retry_backoff_s=0.0)
USER_EXAMPLE = ("The documents you provided do not contain any information about intake‑specific requirements for a "
                "Computer Science programme. They only list learning outcomes and course modules for existing "
                "programmes. If you can provide the specific intake (e.g., “2027 Spring Intake”) or the relevant "
                "intake‑advert, I can locate the requirements for that intake.")


class NormaliseTests(unittest.TestCase):
    def test_user_question_is_cleaned(self):
        q, changes = normalise_query("what are the requrements for computer science for the following intake")
        self.assertEqual(q, "what are the requirements for computer science for the 2027 intake")
        self.assertEqual(len(changes), 2)

    def test_variants(self):
        self.assertEqual(normalise_query("Entery requirments for the next intake?")[0],
                         "entry requirements for the 2027 intake?")
        self.assertEqual(normalise_query("Requirements for the 2027 intake, this intake")[0],
                         "Requirements for the 2027 intake, this intake")      # an explicit year is never rewritten
        self.assertEqual(normalise_query("Describe HSWE223 and BM134")[0], "Describe HSWE223 and BM134")

    def test_evaluated_questions_are_unchanged(self):
        files = [ROOT / "remediation/heldout/heldout_questions.json",
                 ROOT / "remediation/R1_generation_consistency/dev_questions.json"]
        files = [f for f in files if f.exists()]
        if not files:
            self.skipTest("evaluation artifacts not present")
        for f in files:
            for q in json.loads(f.read_text(encoding="utf-8"))["questions"]:
                self.assertEqual(normalise_query(q["question"])[0], q["question"], q["id"])


class TriggerTests(unittest.TestCase):
    def test_intake_questions(self):
        for q in ("what are the requirements for computer science for the 2027 intake",
                  "How long is the BSc Honours in Agronomy?", "When does the Bachelor of Commerce degree start?",
                  "Do I need A level Maths?"):
            self.assertTrue(is_intake_question(q), q)

    def test_non_intake_questions(self):
        for q in ("When does second-quarter face-to-face tuition run in 2027?", "Describe BM134",
                  "If I repeat a module, which marks will count?", "When does the semester start?"):
            self.assertFalse(is_intake_question(q), q)


class WordingTests(unittest.TestCase):
    def test_user_example(self):
        text = present_answer(USER_EXAMPLE)
        self.assertTrue(text.startswith("The MSU documents I searched do not contain"))
        self.assertNotIn("provide", text)
        self.assertNotIn("you provided", text)
        self.assertTrue(text.endswith("for existing programmes."))
        self.assertEqual(miss_tip(text, "intake")[0]["kind"], "tip")

    def test_documents_provided_without_you(self):
        self.assertEqual(present_answer("The documents provided do not contain any information about X."),
                         "The MSU documents I searched do not contain any information about X.")
        kept = "The duration provided in Evidence 1 is 4 years. The evidence provided by the advert is current."
        self.assertEqual(present_answer(kept), kept)

    def test_agreement_and_tables_untouched(self):
        self.assertEqual(present_answer("The supplied evidence lists 4 years [Evidence 1]."),
                         "The MSU evidence I searched lists 4 years [Evidence 1].")
        table = "| Route | Years |\n|---|---|\n| Gweru Conventional | 4 (p. 28) |\n\nSee Evidence 1 (Vol. 2, p. 897)."
        self.assertEqual(present_answer(table), table)
        self.assertEqual(miss_tip("It lasts 4 years [Evidence 1].", "intake"), [])

    def test_assistant_applies_fixes_on_c3_profiles_only(self):
        class LLM:
            def generate(self, messages, settings):
                self.question = messages[1].content
                return LLMResponse(text=USER_EXAMPLE, provider="fake", requested_model=settings.model,
                                   returned_model=settings.model, finish_reason="stop", usage={})

        class Retriever:
            def retrieve(self, question):
                self.query = question
                return [{"rank": 1, "chunk_id": 1, "source": "MSU Sciences Yearbook Vol. 2", "page": 897,
                         "heading": "H", "text": "[MSU Sciences Yearbook Vol. 2, p. 897]\nLearning outcomes."}]
        from src.profiles import build_c3_messages
        retriever, llm = Retriever(), LLM()
        r = Assistant(retriever, llm=llm, settings=SETTINGS, ambiguity_fn=lambda *a: [], profile=INTAKE,
                      message_builder=build_c3_messages).ask("requrements for computer science for the next intake")
        self.assertEqual(retriever.query, "requirements for computer science for the 2027 intake")
        self.assertEqual(r.normalised_question, "requirements for computer science for the 2027 intake")
        self.assertTrue(r.answer.startswith("The MSU documents I searched"))
        self.assertEqual(r.raw_answer, USER_EXAMPLE)
        self.assertIn("tip", [n["kind"] for n in r.safety_notes])
        baseline = Assistant(Retriever(), llm=LLM(), settings=SETTINGS, ambiguity_fn=lambda *a: []).ask(
            "requrements for computer science for the next intake")
        self.assertEqual(baseline.answer, USER_EXAMPLE)           # rollback profile: previous behaviour
        self.assertIsNone(baseline.normalised_question)


if __name__ == "__main__":
    unittest.main()
