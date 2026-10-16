"""Router + eligibility flow with every model call mocked (offline, no Groq), including the Streamlit UI.

Run from the project root: python -m unittest tests.test_router_and_flow -v
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.admissions_flow import EXTRACTION_BUSY, handle_message
from src.assistant import Assistant, AssistantResult
from src.conversation import ChatSession
from src.admissions_adviser import DISCLAIMER
from src import entry_routes as er
from src.eligibility_engine import CONDITIONAL, MEETS, NOT_MET
from src.extract_grades import EXTRACT_PROMPT, from_form
from src.llm.base import GenerationSettings, LLMError, LLMResponse
from src.router import (ELIGIBILITY, INFO, OUT_OF_SCOPE, OUT_OF_SCOPE_REPLY, ROUTER_PROMPT, parse_label, route,
                        route_with_reason)

SETTINGS = GenerationSettings(model="openai/gpt-oss-20b", retry_backoff_s=0.0)
Q_ELIG = "I have Mathematics A, Computer Science A and Economics B, what can I study?"
Q_INFO = "What are the entry requirements for Software Engineering?"
Q_FEES = "How much are the fees?"
Q_NO_SUBJECTS = "I got A, B and C at A Level. What can I study?"
Q_FAILS = "My A Levels: Mathematics F, Physics A, Chemistry O. What can I do?"


class ScriptedLLM:
    """Answers by system prompt (router label, extraction JSON, RAG answer); records every call."""

    def __init__(self, labels=None, extractions=None, fail=None):
        self.labels, self.extractions, self.fail = labels or {}, extractions or {}, fail or {}
        self.calls = []

    def generate(self, messages, settings):
        system, user = messages[0].content, messages[1].content
        kind = {ROUTER_PROMPT: "router", EXTRACT_PROMPT: "extract"}.get(system, "rag")
        self.calls.append((kind, user, settings))
        if kind in self.fail:
            raise LLMError(self.fail[kind], "fake")
        if kind == "router":
            text = next((v for k, v in self.labels.items() if k in user.split("Message to classify:")[-1]), "INFO")
        elif kind == "extract":
            text = next((v for k, v in self.extractions.items() if k in user), '{"a_level": []}')
        else:
            text = "Grounded answer [Evidence 1]."
        return LLMResponse(text=text, provider="fake", requested_model=settings.model, returned_model=settings.model,
                           finish_reason="stop", usage={})

    def kinds(self):
        return [c[0] for c in self.calls]


def fake_assistant(llm):
    asked = []

    def ask(q):
        asked.append(q)
        return AssistantResult(question=q, status="answered", answer="Software Engineering needs ... [Evidence 1].",
                               sources=[{"number": 1, "document": "MSU January/February 2027 Intake Advert", "pdf_page": 30}])
    return SimpleNamespace(llm=llm, settings=SETTINGS, ask=ask, asked=asked)


def names(answer, outcome):
    return [r.programme for r in answer.sections[outcome]]


class RequiredCases(unittest.TestCase):
    """The five cases of the original specification."""

    def setUp(self):
        self.llm = ScriptedLLM(labels={Q_INFO: "INFO"})
        self.assistant = fake_assistant(self.llm)

    def test_a_eligibility_question(self):
        self.assertEqual(route(Q_ELIG, [], self.llm, SETTINGS), ELIGIBILITY)
        chat = ChatSession()
        turn = handle_message(chat, self.assistant, Q_ELIG, log_path=None)
        self.assertEqual(turn.path, ELIGIBILITY)
        reply = turn.flow.data
        ans = reply.detail                                    # the engine's full result (Detailed assessment)
        positive = names(ans, MEETS) + names(ans, CONDITIONAL)
        for programme in ("Degree in Computer Science", "Software Engineering", "Cybersecurity", "Actuarial Science"):
            self.assertTrue(any(programme in p for p in positive), programme)
        self.assertTrue(any("Biotechnology" in p for p in names(ans, NOT_MET)))
        self.assertEqual(reply.shortlist[0].programme, "Bachelor of Science Honours Degree in Computer Science")
        self.assertIn(DISCLAIMER, turn.flow.answer)
        self.assertNotIn("conditional matches", turn.flow.answer)       # no counts in the conversation
        self.assertEqual(self.llm.calls, [])                 # routed, read and answered without any model call
        self.assertEqual(self.assistant.asked, [])
    def test_b_info_question(self):
        self.assertEqual(route(Q_INFO, [], self.llm, SETTINGS), INFO)
        chat = ChatSession()
        turn = handle_message(chat, self.assistant, Q_INFO, log_path=None)
        self.assertEqual(turn.path, INFO)
        self.assertEqual(self.assistant.asked, [Q_INFO])

    def test_c_fees_question_gets_the_fixed_reply_without_any_model_call(self):
        turn = handle_message(ChatSession(), self.assistant, Q_FEES, log_path=None)
        self.assertEqual((turn.path, turn.flow.answer), (OUT_OF_SCOPE, OUT_OF_SCOPE_REPLY))
        self.assertEqual(self.llm.calls, [])

    def test_d_grades_without_subjects_ask_a_follow_up(self):
        chat = ChatSession()
        with patch("src.eligibility_engine.evaluate", side_effect=AssertionError("no decision without subjects")):
            turn = handle_message(chat, self.assistant, Q_NO_SUBJECTS, log_path=None)
        self.assertEqual((turn.path, turn.flow.status, turn.flow.asked), (ELIGIBILITY, "follow_up", "a_level_subjects"))
        self.assertIn("Which A Level subjects did you get those grades (A, B and C) in?", turn.flow.answer)
        self.assertFalse(chat.applicant.a_level)
        self.assertEqual(self.llm.calls, [])
    def test_e_f_and_o_grades_are_not_passes(self):
        turn = handle_message(ChatSession(), self.assistant, Q_FAILS, log_path=None)
        self.assertEqual(turn.flow.debug["failed_a_level_grades"], ["Mathematics (F)", "Chemistry (O)"])
        self.assertEqual(turn.flow.debug["points"], 5)                  # only Physics A counts
        self.assertIn("Mathematics F and Chemistry O are not A Level passes", turn.flow.answer)


class RoutingTests(unittest.TestCase):
    def test_deterministic_routes_need_no_model(self):
        llm = ScriptedLLM()
        cases = [(Q_ELIG, [], False, ELIGIBILITY, "applicant_profile"),
                 ("What can I study?", [], False, ELIGIBILITY, "eligibility_phrase"),
                 ("English B, Maths C, 6 passes", [{"path": ELIGIBILITY, "asked": "o_level_grades",
                                                    "asked_for_o_level": True}], True, ELIGIBILITY, "adviser_reply"),
                 ("Why can't I do Biotechnology?", [{"path": ELIGIBILITY}], True, ELIGIBILITY, "adviser_reply"),
                 ("show all", [{"path": ELIGIBILITY}], True, ELIGIBILITY, "show_all"),
                 ("Mathematics, Physics and Chemistry", [{"path": ELIGIBILITY, "asked": "a_level_subjects",
                                                          "asked_for_grades": True}], False, ELIGIBILITY, "adviser_reply"),
                 ("Mathematics, Physics and Chemistry", [{"path": ELIGIBILITY, "asked_for_grades": True}], False,
                  ELIGIBILITY, "results_in_message"),
                 ("When is the last day to apply?", [], False, OUT_OF_SCOPE, "keyword")]
        for q, hist, has, label, reason in cases:
            self.assertEqual(route_with_reason(q, hist, llm, SETTINGS, has), (label, reason), q)
        self.assertEqual(llm.calls, [])
    def test_other_questions_use_the_model_and_default_to_info(self):
        self.assertEqual(route_with_reason("Describe BM134", [], ScriptedLLM(labels={"BM134": "INFO"}), SETTINGS),
                         (INFO, "model"))
        self.assertEqual(route_with_reason("Describe BM134", [], ScriptedLLM(labels={"BM134": "maybe"}), SETTINGS),
                         (INFO, "model_invalid_output"))
        self.assertEqual(route_with_reason("Describe BM134", [], ScriptedLLM(fail={"router": "timeout"}), SETTINGS),
                         (INFO, "model_error"))
        for text in ("INFO or ELIGIBILITY", "", "banana"):
            self.assertEqual(parse_label(text), INFO)

    def test_model_out_of_scope_needs_a_money_or_deadline_word(self):
        llm = ScriptedLLM(labels={"tuition": "OUT_OF_SCOPE", "Council": "OUT_OF_SCOPE", "expensive": "OUT_OF_SCOPE"})
        self.assertEqual(route("When does second-quarter face-to-face tuition run in 2027?", [], llm, SETTINGS), INFO)
        self.assertEqual(route("Who chairs Council meetings when the Chancellor is not there?", [], llm, SETTINGS), INFO)
        self.assertEqual(route("Is studying at MSU expensive?", [], llm, SETTINGS), OUT_OF_SCOPE)

    def test_router_uses_the_configured_model_at_temperature_zero(self):
        llm = ScriptedLLM(labels={"x": "INFO"})
        route("x", [], llm, SETTINGS.with_changes(model="model-from-GROQ_MODEL"))
        self.assertEqual((llm.calls[0][2].model, llm.calls[0][2].temperature), ("model-from-GROQ_MODEL", 0.0))


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.llm = ScriptedLLM(labels={"Describe BM134": "INFO", "credits": "INFO"})
        self.a = fake_assistant(self.llm)

    def test_o_level_request_and_reply_complete_the_check(self):
        chat = ChatSession()
        first = handle_message(chat, self.a, Q_ELIG, log_path=None)
        self.assertEqual(first.flow.asked, "o_level_grades")
        self.assertIn("O Level English Language and Mathematics grades", first.flow.answer)
        self.assertEqual(first.flow.data.detail.counts[MEETS], 0)
        self.assertNotIn("✅", first.flow.answer)
        second = handle_message(chat, self.a, "English B, Maths C, 6 passes", log_path=None)
        self.assertEqual(second.flow.debug["o_level"], {"English Language": "B", "Mathematics": "C", "passes": 6})
        self.assertGreater(second.flow.data.detail.counts[MEETS], 0)
        self.assertIn("✅ Meets the advertised requirements", second.flow.answer)
        self.assertNotEqual(second.flow.asked, "o_level_grades")
        self.assertEqual(self.llm.calls, [])
    def test_corrections_update_the_results(self):
        chat = ChatSession()
        handle_message(chat, self.a, Q_ELIG, log_path=None)
        turn = handle_message(chat, self.a, "Sorry, actually Economics is A", log_path=None)
        self.assertEqual(turn.flow.debug["a_level"], {"Mathematics": "A", "Computer Science": "A", "Economics": "A"})
        self.assertEqual(turn.flow.debug["points"], 15)
        self.assertIn("Economics A (was B)", turn.flow.answer)
    def test_why_not_reuses_results_and_answers_the_named_programme_first(self):
        chat = ChatSession()
        handle_message(chat, self.a, Q_ELIG, log_path=None)
        turn = handle_message(chat, self.a, "Why can't I do Biotechnology?", log_path=None)
        self.assertEqual(turn.flow.data.focus, "programme")
        self.assertTrue(turn.flow.answer.startswith("Here is how you could get into"))
        self.assertIn("Biotechnology", turn.flow.answer.split("\n\n")[1])
        self.assertIn("❌ not open to you: A Level requirement not met", turn.flow.answer)
    def test_show_all_lists_everything(self):
        chat = ChatSession()
        handle_message(chat, self.a, Q_ELIG, log_path=None)
        turn = handle_message(chat, self.a, "show all", log_path=None)
        reply = turn.flow.data
        self.assertTrue(reply.expand_detail)                         # the full lists open in Detailed assessment
        self.assertEqual(sum(reply.detail.counts.values()), 141)     # every programme, nothing dropped
        self.assertIn("Detailed assessment", turn.flow.answer)
    def test_form_is_used_instead_of_the_message(self):
        form = from_form([("Mathematics", "A"), ("Physics", "B"), ("Chemistry", "B")], "B", "B", 7)
        chat = ChatSession()
        turn = handle_message(chat, self.a, "what can I study", form=form, log_path=None)
        self.assertTrue(turn.flow.debug.get("form"))
        self.assertEqual(turn.flow.debug["a_level"], {"Mathematics": "A", "Physics": "B", "Chemistry": "B"})
        again = handle_message(chat, self.a, "show all", form=form, log_path=None)
        self.assertFalse(again.flow.debug.get("form"))                # a saved form is applied once
    def test_info_turns_keep_the_follow_up_context(self):
        chat = ChatSession()
        handle_message(chat, self.a, "Describe BM134", log_path=None)
        handle_message(chat, self.a, Q_ELIG, log_path=None)
        handle_message(chat, self.a, "How many credits is it?", log_path=None)
        self.assertEqual(self.a.asked[-1], "How many credits is BM134?")

    def test_model_reads_results_only_when_the_parser_cannot(self):
        tricky = "Maths and Physics were both A, and I got a C"
        llm = ScriptedLLM(labels={tricky: "ELIGIBILITY"}, extractions={tricky: json.dumps(
            {"a_level": [{"subject": "Mathematics", "grade": "A"}, {"subject": "Physics", "grade": "A"}]})})
        turn = handle_message(ChatSession(), fake_assistant(llm), tricky, log_path=None)
        self.assertIn("extract", llm.kinds())
        self.assertEqual(turn.flow.debug["results_method"], "model")
        self.assertEqual(turn.flow.debug["a_level"], {"Mathematics": "A", "Physics": "A"})
    def test_extraction_failure_makes_no_decision(self):
        tricky = "Maths and Physics were both A, and I got a C"
        llm = ScriptedLLM(labels={tricky: "ELIGIBILITY"}, fail={"extract": "rate_limit"})
        turn = handle_message(ChatSession(), fake_assistant(llm), tricky, log_path=None)
        self.assertEqual((turn.flow.status, turn.flow.answer), ("error", EXTRACTION_BUSY))
        self.assertIsNone(turn.flow.data)


class OutOfScopeAndLogging(unittest.TestCase):
    def test_deadline_stated_in_the_advert_is_quoted_with_its_page(self):
        turn = handle_message(ChatSession(), fake_assistant(ScriptedLLM()),
                              "What is the application deadline for Mining Engineering?", log_path=None)
        self.assertEqual(turn.path, OUT_OF_SCOPE)
        self.assertIn("Deadline for submission of applications is 31 March 2027", turn.flow.answer)
        self.assertIn("p. 23", turn.flow.answer)
        generic = handle_message(ChatSession(), fake_assistant(ScriptedLLM()), "When is the last day to apply?",
                                 log_path=None)
        self.assertEqual(generic.flow.answer, OUT_OF_SCOPE_REPLY)

    def test_question_log_is_metadata_only_by_default(self):
        contact = "My email is jane.doe@gmail.com and phone +263 77 123 4567, how much are fees?"
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "q.jsonl"
            chat, a = ChatSession(), fake_assistant(ScriptedLLM())
            handle_message(chat, a, Q_ELIG, log_path=log)
            handle_message(chat, a, contact, log_path=log)
            raw = log.read_text(encoding="utf-8")
            lines = [json.loads(l) for l in raw.splitlines()]
        self.assertEqual([l["route"] for l in lines], [ELIGIBILITY, OUT_OF_SCOPE])
        self.assertEqual(set(lines[0]), {"timestamp", "route", "router_reason", "question_chars", "latency_ms", "status",
                                         "asked", "focus", "shortlist", "results_method"})
        for secret in ("Mathematics", "Computer Science", "jane.doe", "123 4567", "what can I study"):
            self.assertNotIn(secret, raw)

    def test_question_text_only_when_enabled_and_redacted(self):
        contact = "My email is jane.doe@gmail.com and phone +263 77 123 4567, how much are fees?"
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "q.jsonl"
            handle_message(ChatSession(), fake_assistant(ScriptedLLM()), contact, log_path=log, log_text=True)
            line = json.loads(log.read_text(encoding="utf-8"))
        self.assertIn("how much are fees", line["question"])
        self.assertNotIn("jane.doe", line["question"])


class CheckerScriptTest(unittest.TestCase):
    def test_the_checkers_own_25_tests_pass(self):
        import subprocess
        import sys
        folder = Path(__file__).resolve().parents[1] / "src" / "eligibility"
        out = subprocess.run([sys.executable, "test_checker.py"], cwd=folder, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "25 / 25")


def item(rank):
    return {"rank": rank, "chunk_id": rank, "source": "MSU January/February 2027 Intake Advert", "page": 28,
            "heading": "H", "text": f"[MSU January/February 2027 Intake Advert, p. 28]\nPassage {rank}."}


class Retriever:
    def retrieve(self, question):
        return [] if "WiFi" in question else [item(1), item(2)]


class AppFlowUITests(unittest.TestCase):
    """The real app.py, headless, with a fake assistant whose model calls are scripted."""
    dev_mode = "1"

    def setUp(self):
        import streamlit as st
        from streamlit.testing.v1 import AppTest
        st.cache_resource.clear()
        llm = ScriptedLLM(labels={"Describe": "INFO", "Computer Science": "INFO"})
        fake = Assistant(Retriever(), llm=llm, settings=SETTINGS, ambiguity_fn=lambda *a: [])
        create = patch.object(Assistant, "create", classmethod(lambda cls, offline=False: fake))
        create.start()
        self.addCleanup(create.stop)
        env = patch.dict(os.environ, {"MSU_ASSISTANT_OFFLINE": "", "MSU_ASSISTANT_DEV_MODE": self.dev_mode})
        env.start()
        self.addCleanup(env.stop)
        app = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
        self.at = AppTest.from_file(app, default_timeout=60)
        self.at.run()

    def ask(self, question):
        self.at.chat_input[0].set_value(question).run()
        self.assertFalse(self.at.exception)
        return self.last()

    def last(self):
        chat = self.at.session_state["chats"]
        return self.at.get_by_key(f"amsg-{chat.current_id}-{len(chat.current.turns) - 1}")

    def test_eligibility_answer_with_tabs_and_follow_ups(self):
        elig = self.ask(Q_ELIG)
        self.assertIn("Admissions adviser", " ".join(c.value for c in elig.caption))     # developer mode only
        labels = [e.label for e in elig.expander]
        self.assertEqual(labels, ["Detailed assessment (all programmes and entry routes)", "Technical details"])
        detail = elig.expander[0]
        routes = ["Normal entry (A Levels)", "Normal entry (O Levels)", "Special entry (post-school qualification)",
                  "Mature entry"]
        self.assertEqual([t.label for t in detail.tabs if t.label in routes], routes)
        self.assertTrue(any(t.label.startswith("🟡 Conditional (") for t in detail.tabs))
        self.assertIn(DISCLAIMER, " ".join(m.value for m in elig.markdown))
        self.assertIn("Software Engineering", " ".join(m.value for m in detail.markdown))
    def test_paths_are_shown_under_each_answer(self):
        fees = self.ask(Q_FEES)
        self.assertIn(OUT_OF_SCOPE_REPLY, " ".join(m.value for m in fees.markdown))
        info = self.ask("Describe BM134")
        self.assertIn("Documents: MSU January/February 2027 Intake Advert p. 28", " ".join(c.value for c in info.caption))
        self.assertEqual([e.label for e in info.expander], ["Sources (2)", "Technical details"])

    def test_programme_details_panel_for_a_named_programme(self):
        info = self.ask("What are the entry requirements for Computer Science?")
        labels = [e.label for e in info.expander]
        self.assertIn("Programme details (2027 intake advert)", labels)
        panel = info.expander[labels.index("Programme details (2027 intake advert)")]
        self.assertIn("advert p. 28", " ".join(m.value for m in panel.markdown))

    def test_not_found_info_answers_still_show_the_answer_only(self):
        block = self.ask("What is the WiFi password?")
        self.assertEqual((len(block.expander), len(block.caption)), (0, 0))

    def test_sidebar_form_saves_results(self):
        side = self.at.sidebar
        side.selectbox(key="elig-subject-0").set_value("Mathematics")
        side.selectbox(key="elig-grade-0").set_value("A")
        side.selectbox(key="elig-subject-1").set_value("Physics")
        side.selectbox(key="elig-grade-1").set_value("B")
        next(b for b in self.at.button if b.label == "Save my results").click().run()
        self.assertFalse(self.at.exception)
        self.assertEqual(self.at.session_state["elig_form"].a_level, {"Mathematics": "A", "Physics": "B"})


class DefaultModeUITests(AppFlowUITests):
    """Developer mode off (the default): no technical details, no extracted results."""
    dev_mode = ""

    def test_eligibility_answer_with_tabs_and_follow_ups(self):
        elig = self.ask(Q_ELIG)
        self.assertEqual([e.label for e in elig.expander], ["Detailed assessment (all programmes and entry routes)"])
        self.assertEqual(len(elig.json), 0)
        self.assertEqual([c.value for c in elig.caption if "adviser" in c.value.lower()], [])   # no routing label
        text = " ".join(m.value for m in elig.markdown)
        self.assertNotIn("conditional matches", text)

    def test_quick_replies_and_new_assessment(self):
        first = self.ask("I have 5 O-Level passes including Maths and English, and I'm 30 years old. What programme can I do?")
        self.assertEqual([b.label for b in first.button],
                         ["No, only O Levels", "Yes, A Levels", "Yes, a diploma or certificate"])
        next(b for b in first.button if b.label == "No, only O Levels").click().run()
        self.assertFalse(self.at.exception)
        chat = self.at.session_state["chats"].current
        self.assertEqual(chat.turns[-1].question, "No, only O Levels")
        self.assertTrue(chat.applicant.a_level_none())
        panel = " ".join(m.value for m in self.at.sidebar.markdown)
        self.assertIn("**Age:** 30", panel)
        self.assertIn("my assumption: please check", panel)                 # inferred "passed = grade C or better"
        next(b for b in self.at.button if b.label == "Yes, start a new assessment").click().run()
        self.assertFalse(self.at.exception)
        chat = self.at.session_state["chats"].current
        self.assertTrue(chat.applicant.is_empty())
        self.assertIn("New assessment started", chat.turns[-1].flow.answer)

    def test_paths_are_shown_under_each_answer(self):
        info = self.ask("Describe BM134")
        self.assertEqual([e.label for e in info.expander], ["Sources (2)"])
        self.assertNotIn("Router:", " ".join(m.value for m in info.markdown))


if __name__ == "__main__":
    unittest.main()
