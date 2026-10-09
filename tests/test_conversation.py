"""Basic contextual follow-up support and in-memory chats (src/conversation.py). Pure logic; no Streamlit, no Groq.

Run from the project root: python -m unittest discover -s tests -t .
"""
import unittest
from types import SimpleNamespace

from src.conversation import ChatContext, ChatSession, ChatStore, context_after, is_followup, resolve


class RecordingAssistant:
    """Records the standalone questions it receives; its answers deliberately mention another course code."""
    def __init__(self):
        self.asked = []

    def ask(self, question):
        self.asked.append(question)
        return SimpleNamespace(question=question, answer="Answer that also mentions HAM105 and SEMA204.")


def chat_with(*questions):
    session, assistant = ChatSession(), RecordingAssistant()
    for q in questions:
        session.ask(assistant, q)
    return session, assistant


class ResolverTests(unittest.TestCase):
    def test_reference_forms_to_course_code(self):
        ctx = ChatContext(anchor="Describe BM134", code="bm134")
        cases = {
            "How many credits is it?": "How many credits is BM134?",
            "What are its prerequisites?": "What are BM134's prerequisites?",
            "Which semester is this module taught in?": "Which semester is BM134 taught in?",
            "What does the course cover?": "What does BM134 cover?",
            "Who teaches that module?": "Who teaches BM134?",
            "What about the credits?": "What about the credits for BM134?",
            "And the semester?": "And the semester for BM134?",
        }
        for question, expected in cases.items():
            r = resolve(question, ctx)
            self.assertEqual((r.standalone, r.is_followup, r.rule), (expected, True, "course_code_reference"),
                             question)

    def test_standalone_questions_unchanged(self):
        ctx = ChatContext(anchor="Describe BM134", code="bm134")
        for q in ("Describe SEMA204", "SEMA 204", "What is HAM105 about?",  # explicit course codes
                  "Who chairs Council meetings when the Chancellor is not there?",  # no referring word
                  "Which semester?",  # bare fragment: deliberately not resolved
                  "If it rains during an examination and I arrive late because the roads are flooded what happens"):
            r = resolve(q, ctx)
            self.assertEqual((r.standalone, r.is_followup, r.rule), (q, False, "standalone"), q)

    def test_no_history_means_standalone(self):
        r = resolve("How many credits is it?", ChatContext())
        self.assertFalse(r.is_followup)
        self.assertEqual(r.standalone, "How many credits is it?")

    def test_topic_follow_up_appends_last_standalone_question(self):
        ctx = ChatContext(anchor="Can I switch from an MPhil to a PhD, and when?", code=None)
        r = resolve("What do they need to submit?", ctx)
        self.assertEqual((r.rule, r.standalone), ("topic_reference",
                         "Can I switch from an MPhil to a PhD, and when? What do they need to submit?"))

    def test_multiple_codes_use_topic_rule(self):
        ctx = context_after(ChatContext(), resolve("Compare BM134 and BM135", ChatContext()))
        self.assertIsNone(ctx.code)
        self.assertEqual(resolve("Which is harder, it seems?", ctx).rule, "topic_reference")

    def test_is_followup(self):
        ctx = ChatContext(anchor="Describe BM134", code="bm134")
        self.assertTrue(is_followup("Is it compulsory?", ctx))
        self.assertFalse(is_followup("Is BM135 compulsory?", ctx))


class ChatSessionTests(unittest.TestCase):
    def test_bm134_chain_and_explicit_switch(self):
        session, assistant = chat_with("Describe BM134", "How many credits is it?", "Which semester is it taught in?",
                                       "Describe SEMA204", "How many credits is it?")
        self.assertEqual(assistant.asked, ["Describe BM134", "How many credits is BM134?",
                                           "Which semester is BM134 taught in?", "Describe SEMA204",
                                           "How many credits is SEMA204?"])
        self.assertEqual([t.question for t in session.turns][1], "How many credits is it?")  # original kept
        self.assertEqual([t.resolution.is_followup for t in session.turns], [False, True, True, False, True])

    def test_previous_assistant_answers_never_used(self):
        # every answer mentions HAM105 and SEMA204; resolution must still follow the user's BM134 question
        session, assistant = chat_with("Describe BM134", "How many credits is it?")
        self.assertEqual(assistant.asked[1], "How many credits is BM134?")
        self.assertEqual(session.context.code, "bm134")
        self.assertEqual(session.context.anchor, "Describe BM134")

    def test_title(self):
        session, _ = chat_with("What qualification do I need to apply for an MPhil at Midlands State University?")
        self.assertEqual(len(session.title), 40)
        self.assertTrue(session.title.endswith("…"))
        self.assertEqual(ChatSession().title, "New chat")


class ChatStoreTests(unittest.TestCase):
    def test_new_chat_keeps_previous_and_clears_context(self):
        store, assistant = ChatStore(), RecordingAssistant()
        first = store.current_id
        store.current.ask(assistant, "Describe BM134")
        second = store.new_chat()
        self.assertNotEqual(first, second)
        self.assertIn(first, store.sessions)
        store.current.ask(assistant, "How many credits is it?")  # fresh context: not rewritten
        self.assertEqual(assistant.asked[-1], "How many credits is it?")
        self.assertEqual(store.new_chat(), store.new_chat())  # an empty current chat is reused

    def test_switching_restores_conversation_and_isolated_context(self):
        store, assistant = ChatStore(), RecordingAssistant()
        a = store.current_id
        store.current.ask(assistant, "Describe BM134")
        b = store.new_chat()
        store.current.ask(assistant, "SEMA 204")
        store.switch(a)
        self.assertEqual(store.current.turns[0].question, "Describe BM134")
        store.current.ask(assistant, "How many credits is it?")
        self.assertEqual(assistant.asked[-1], "How many credits is BM134?")
        store.switch(b)
        store.current.ask(assistant, "How many credits is it?")
        self.assertEqual(assistant.asked[-1], "How many credits is SEMA204?")
        with self.assertRaises(KeyError):
            store.switch(999999)

    def test_history_newest_first_and_search_titles_only(self):
        store, assistant = ChatStore(), RecordingAssistant()
        for q in ("Describe BM134", "What do I have to sign when I register as a student?", "SEMA 204"):
            store.new_chat()
            store.current.ask(assistant, q)
        store.new_chat()  # empty chat is not listed
        titles = [s.title for s in store.history()]
        self.assertEqual(titles, ["SEMA 204", "What do I have to sign when I register…", "Describe BM134"])
        self.assertEqual([s.title for s in store.history("bm1")], ["Describe BM134"])
        self.assertEqual([s.title for s in store.history("REGISTER")], [titles[1]])
        self.assertEqual(store.history("Business Ethics"), [])  # answer text is not searched
        asked = len(assistant.asked)
        store.history("anything")
        self.assertEqual(len(assistant.asked), asked)  # search performs no retrieval


if __name__ == "__main__":
    unittest.main()
