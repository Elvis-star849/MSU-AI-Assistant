"""Hardening of the admissions features (offline; model calls scripted where any are made).

- results parser: phrasings, O Level context, corrections, unattached grades;
- deterministic answers: no model takes part, so no model output can change a category, a count or a programme;
- answer rendering: ordering, exact programme first, O Level request, disclaimer, show all;
- router regressions: tuition vs fees, deadlines, follow-ups, programme names, unrelated questions;
- failures: every Groq error kind on the router and on the extraction fallback;
- structured programme lookup and the programme-lookup retriever.

Run from the project root: python -m unittest tests.test_eligibility_hardening -v
"""
import json
import unittest
from unittest.mock import patch

from src.admissions_flow import EXTRACTION_BUSY, handle_message
from src.conversation import ChatSession
from src.eligibility_answer import ASK_O_LEVEL, DISCLAIMER, answer_eligibility, mentioned
from src.eligibility_engine import CONDITIONAL, MEETS, NOT_MET, OTHER_ROUTE, evaluate
from src.extract_grades import ASK_GRADES, ASK_RESULTS, ASK_SUBJECTS, Extraction, from_form, read_results
from src.llm.base import LLMClient, LLMError, LLMResponse
from src.programme_lookup import card_markdown, facets, find_programmes, programme_groups, records, search
from src.results_parser import parse_results
from src.router import ELIGIBILITY, INFO, OUT_OF_SCOPE, route, route_with_reason
from tests.test_router_and_flow import Q_ELIG, SETTINGS, ScriptedLLM, fake_assistant

CS = [("Mathematics", "A"), ("Computer Science", "A"), ("Economics", "B")]
O_FULL = {"English": "B", "Mathematics": "C", "passes": 6}


class ParserTests(unittest.TestCase):
    def check(self, text, a=None, o=None, confident=True, context=False):
        r = parse_results(text, o_level_context=context)
        self.assertEqual((r.a_level, r.o_level, r.confident), (a or {}, o or {}, confident), text)

    def test_common_phrasings(self):
        self.check("I have Mathematics A, Computer Science A and Economics B",
                   {"Mathematics": "A", "Computer Science": "A", "Economics": "B"})
        self.check("maths=F, physics=A, chem=O", {"Mathematics": "F", "Physics": "A", "Chemistry": "O"})
        self.check("I got an A in Chemistry and a B in Physics", {"Chemistry": "A", "Physics": "B"})
        self.check("Physics grade B and Maths: A", {"Physics": "B", "Mathematics": "A"})
        self.check("With Physics A, Chemistry B and Biology B can I do medicine?",
                   {"Physics": "A", "Chemistry": "B", "Biology": "B"})

    def test_o_level(self):
        self.check("O level English B, Maths C, 6 passes", o={"English": "B", "Mathematics": "C", "passes": 6})
        self.check("English B, Maths C, 6 passes", o={"English": "B", "Mathematics": "C", "passes": 6})
        self.check("I have five O level passes and A level History A, Shona B", {"History": "A", "Shona": "B"}, {"passes": 5})
        self.check("My A Levels: Mathematics F, Physics A. O levels: English C, Mathematics B, 7 passes",
                   {"Mathematics": "F", "Physics": "A"}, {"English": "C", "Mathematics": "B", "passes": 7})
        self.check("Maths C and Science B", o={"Mathematics": "C", "Science": "B"}, context=True)
        self.check("Sorry, actually Economics is A", {"Economics": "A"}, context=True)   # A Level-only subject

    def test_unattached_grades_and_subjects_without_grades(self):
        self.check("I got A, B and C at A Level", confident=False)
        r = parse_results("I did Biology and Chemistry")
        self.assertEqual(r.subjects_without_grade, ["Biology", "Chemistry"])
        self.check("Why can't I do Biotechnology?")
        self.check("Can I study at a campus in Gweru?")

    def test_read_results_follow_ups_without_a_model(self):
        self.assertEqual(read_results("I got A, B and C at A Level", None, []).follow_up, ASK_SUBJECTS)
        self.assertEqual(read_results("What can I study?", None, []).follow_up, ASK_RESULTS)
        self.assertEqual(read_results("I did Biology", None, []).follow_up,
                         ASK_GRADES.format(subjects="Biology", example="Biology B"))

    def test_corrections_and_replacement(self):
        first = read_results("Mathematics A, Physics B, Chemistry C", None, [])
        fixed = read_results("actually Physics is A", first, [])
        self.assertEqual(fixed.a_level, {"Mathematics": "A", "Physics": "A", "Chemistry": "C"})
        other = read_results("History A, Shona B, Sociology C", fixed, [])
        self.assertEqual(other.a_level, {"History": "A", "Shona": "B", "Sociology": "C"})   # a new set replaces


class DeterministicAnswerTests(unittest.TestCase):
    def test_no_model_is_used_even_when_one_is_available(self):
        llm = ScriptedLLM()
        chat = ChatSession()
        for q in (Q_ELIG, "English B, Maths C, 6 passes", "Why can't I do Biotechnology?", "show all"):
            handle_message(chat, fake_assistant(llm), q, log_path=None)
        self.assertEqual(llm.calls, [])

    def test_answer_matches_the_engine_exactly(self):
        ex = from_form(CS, "B", "C", 6)
        ans = answer_eligibility(ex, "what can I study?", show_all=True)
        ev = evaluate(ex.a_level, ex.checker_o_level())
        for outcome in (MEETS, CONDITIONAL, NOT_MET, OTHER_ROUTE):
            self.assertEqual({r.id for r in ans.sections[outcome]}, {r.id for r in ev.by_outcome(outcome)})
            self.assertEqual(ans.counts[outcome], len(ev.by_outcome(outcome)))
        for r in ans.sections[MEETS] + ans.sections[CONDITIONAL]:
            self.assertIn(r.programme, ans.text)

    def test_order_is_deterministic_and_relevant(self):
        ex = from_form(CS, "B", "C", 6)
        a, b = answer_eligibility(ex, "x"), answer_eligibility(ex, "x")
        for o in a.sections:
            self.assertEqual([r.id for r in a.sections[o]], [r.id for r in b.sections[o]])
        top = [r.programme for r in a.sections[MEETS][:4]]
        for name in ("Degree in Computer Science", "Software Engineering", "Cybersecurity"):
            self.assertTrue(any(name in p for p in top), (name, top))

    def test_exact_programme_first_and_own_results_are_not_names(self):
        ev = evaluate(dict(CS), O_FULL)
        asked = mentioned(ev.results, "Can I do Computer Science?")
        self.assertEqual(asked[0]["result"].programme, "Bachelor of Science Honours Degree in Computer Science")
        self.assertEqual(asked[0]["match"], "exact")
        for q in ("English B, Maths C, 6 passes", "I have Mathematics A, Computer Science A and Economics B"):
            self.assertEqual(mentioned(ev.results, q), [], q)

    def test_conditional_language_o_level_request_and_disclaimer(self):
        ans = answer_eligibility(from_form(CS), "what can I study?")
        self.assertEqual(ans.counts[MEETS], 0)
        self.assertTrue(ans.asked_for_o_level)
        self.assertIn(ASK_O_LEVEL, ans.text)
        self.assertIn("conditional matches", ans.text)
        self.assertTrue(ans.text.rstrip().endswith(DISCLAIMER))
        self.assertIn("does not guarantee a place", DISCLAIMER)
        full = answer_eligibility(from_form(CS, "B", "B", 7), "what can I study?")
        self.assertFalse(full.asked_for_o_level)


class RouterRegressionTests(unittest.TestCase):
    def test_tuition_versus_fees(self):
        llm = ScriptedLLM(labels={"tuition": "OUT_OF_SCOPE"})
        self.assertEqual(route("What are the tuition fees for nursing?", [], llm, SETTINGS), OUT_OF_SCOPE)
        self.assertEqual(route_with_reason("How much is tuition at MSU?")[1], "keyword")
        for q in ("When does second-quarter face-to-face tuition run in 2027?",
                  "When is face to face tuition for block release students?"):
            self.assertEqual(route(q, [], llm, SETTINGS), INFO, q)

    def test_deadlines_without_the_word_deadline(self):
        llm = ScriptedLLM()
        for q in ("When is the last day to apply?", "Until when can I submit my application?",
                  "When do applications close?", "By when should I apply for the January intake?"):
            self.assertEqual(route_with_reason(q, [], llm, SETTINGS), (OUT_OF_SCOPE, "keyword"), q)
        paraphrase = ScriptedLLM(labels={"too late": "OUT_OF_SCOPE", "How long do I have": "OUT_OF_SCOPE"})
        for q in ("Is it too late to apply for 2027?", "How long do I have to get my application in?"):
            self.assertEqual(route(q, [], paraphrase, SETTINGS), OUT_OF_SCOPE, q)
        self.assertEqual(llm.calls, [])

    def test_programme_names_are_not_out_of_scope(self):
        llm = ScriptedLLM(labels={"Banking": "OUT_OF_SCOPE", "Accounting": "OUT_OF_SCOPE"})
        for q in ("What are the entry requirements for the BCom in Banking and Finance?",
                  "How long is the Bachelor of Commerce in Applied Accounting?"):
            self.assertEqual(route(q, [], llm, SETTINGS), INFO, q)

    def test_unrelated_questions_go_to_the_documents_path(self):
        llm = ScriptedLLM(labels={"WiFi": "OUT_OF_SCOPE", "weather": "OUT_OF_SCOPE"})
        for q in ("What is the WiFi password for the MSU library?", "What is the weather in Gweru today?"):
            self.assertEqual(route_with_reason(q, [], llm, SETTINGS), (INFO, "model_out_of_scope_not_confirmed"), q)


class FailureTests(unittest.TestCase):
    KINDS = ("rate_limit", "timeout", "connection", "server", "authentication", "permission", "empty_response",
             "bad_request", "unknown")
    TRICKY = "Maths and Physics were both A, and I got a C"

    def test_router_failures_never_choose_eligibility(self):
        for kind in self.KINDS:
            self.assertEqual(route_with_reason("Is a pass enough for law?", [], ScriptedLLM(fail={"router": kind}),
                                               SETTINGS), (INFO, "model_error"), kind)

    def test_extraction_failures_make_no_decision(self):
        for kind in self.KINDS:
            llm = ScriptedLLM(labels={self.TRICKY: "ELIGIBILITY"}, fail={"extract": kind})
            with patch("src.eligibility_answer.evaluate", side_effect=AssertionError("no decision on failure")):
                turn = handle_message(ChatSession(), fake_assistant(llm), self.TRICKY, log_path=None)
            self.assertEqual((turn.flow.status, turn.flow.answer), ("error", EXTRACTION_BUSY), kind)

    def test_malformed_extraction_output_makes_no_decision(self):
        for bad in ("not json", "[1, 2]", '{"a_level": "Maths A"}', '{"a_level": [{"grade": "A"}]}',
                    '{"a_level": [{"subject": "Underwater Basketweaving", "grade": "A"}]}'):
            llm = ScriptedLLM(labels={self.TRICKY: "ELIGIBILITY"}, extractions={self.TRICKY: bad})
            with patch("src.eligibility_answer.evaluate", side_effect=AssertionError("no decision")):
                turn = handle_message(ChatSession(), fake_assistant(llm), self.TRICKY, log_path=None)
            self.assertEqual(turn.flow.status, "follow_up", bad)

    def test_no_model_configured(self):
        a = fake_assistant(None)
        turn = handle_message(ChatSession(), a, Q_ELIG, log_path=None)
        self.assertEqual(turn.flow.status, "answered")                # the deterministic path needs no model
        tricky = handle_message(ChatSession(), a, self.TRICKY, log_path=None)
        self.assertEqual(tricky.path, INFO)                           # unclear and no model: never a guessed decision
        form = handle_message(ChatSession(), a, "what can I study?", form=from_form(CS, "B", "B", 7), log_path=None)
        self.assertEqual(form.flow.status, "answered")                # the sidebar form works without a model

    def test_rate_limit_is_retried_once(self):
        class Flaky(LLMClient):
            def __init__(self):
                super().__init__(sleep=lambda s: self.sleeps.append(s))
                self.sleeps, self.attempts = [], 0

            def _complete(self, messages, settings):
                self.attempts += 1
                if self.attempts == 1:
                    raise LLMError("rate_limit", "HTTP 429", status_code=429)
                return LLMResponse(text="INFO", provider="fake", requested_model=settings.model,
                                   returned_model=settings.model, finish_reason="stop", usage={})
        llm = Flaky()
        self.assertEqual(route("Describe BM134", [], llm, SETTINGS), INFO)
        self.assertEqual((llm.attempts, llm.sleeps), (2, [2.0]))


class ProgrammeLookupTests(unittest.TestCase):
    def test_all_routes_of_a_named_programme(self):
        groups = programme_groups("How long is the BSc Honours in Human Resource Management and how is it offered?")
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(r["id"] for r in groups[0].routes), ["MSU-JF2027-206", "MSU-JF2027-207"])
        self.assertIn("Route 2", card_markdown(groups[0]))

    def test_precision(self):
        self.assertEqual(programme_groups("Masters in Computer Science requirements"), [])     # no such programme
        g = programme_groups("Requirements for the Master of Science Degree in Community Psychology?")
        self.assertEqual([x.programme for x in g], ["Master of Science Degree in Community Psychology"])
        self.assertEqual(find_programmes("Describe BM134"), [])
        self.assertEqual(find_programmes("When does the second semester start?"), [])

    def test_explorer_search_and_facets(self):
        self.assertEqual(len(records()), 222)
        f = facets()
        self.assertIn("Zvishavane", f["campus"])
        eng = search(faculty="Faculty of Engineering and Geosciences", campus="Zvishavane")
        self.assertTrue(eng and all(g.faculty == "Faculty of Engineering and Geosciences" for g in eng))
        weekend = search(text="Psychology", mode="Weekend School")
        self.assertTrue(all("psychology" in g.programme.lower() for g in weekend))

    def test_programme_lookup_retriever_adds_missing_routes(self):
        from src.profiles import ProgrammeLookupRetriever

        class Store:
            def row_of(self, uid):
                return uid

            def _result(self, idx, rank, score, **extra):
                return {"rank": rank, "chunk_id": 9000, "source": "MSU January/February 2027 Intake Advert", "page": 35,
                        "text": f"[advert] {idx}", "metadata": {"heading": "H"}, **extra}

        class Base:
            store, configuration = Store(), "main"

            def retrieve(self, q):
                return [{"rank": i, "passage_uid": f"yb/{i}", "source": "MSU Humanities Yearbook", "page": i,
                         "chunk_id": i, "text": "t"} for i in range(1, 6)]
        ev = ProgrammeLookupRetriever(Base()).retrieve("How long is the BSc Honours in Human Resource Management?")
        self.assertEqual([e["passage_uid"] for e in ev[:2]],
                         ["intake-2027-jan-feb/v1/MSU-JF2027-206", "intake-2027-jan-feb/v1/MSU-JF2027-207"])
        self.assertEqual(len(ev), 5)
        self.assertEqual([e["rank"] for e in ev], [1, 2, 3, 4, 5])
        plain = ProgrammeLookupRetriever(Base()).retrieve("Describe BM134")
        self.assertEqual([e["passage_uid"] for e in plain], [f"yb/{i}" for i in range(1, 6)])


if __name__ == "__main__":
    unittest.main()


class VerificationAndConflictTests(unittest.TestCase):
    EV = ["[MSU 2027 Road Map, p. 1] DATES: 12/04/2027 - 21/05/2027 START DATE: 12 April 2027",
          "Duration: 1 ½ years. Minimum of an upper second class (2.1) HCSCI237", "eighteen (18) months",
          "DURATION AS ADVERTISED: 4 years 3 Years for Block Release"]

    def test_supported_facts_pass(self):
        from src.safeguards import unverified_facts
        self.assertEqual(unverified_facts("Tuition runs from 12 April 2027 to 21 May 2027 [Evidence 1].", self.EV), [])
        self.assertEqual(unverified_facts("It takes 1.5 years or 18 months; 4 years conventional, 3 years block "
                                          "release; needs a 2.1; prerequisite HCSCI237.", self.EV), [])

    def test_unsupported_facts_are_flagged(self):
        from src.safeguards import fact_notes, unverified_facts
        self.assertEqual(unverified_facts("It takes 5 years, starts 3 March 2027, needs a 2.2 and HCSCI999.", self.EV),
                         ["3 March 2027", "5 years", "2.2", "HCSCI999"])
        notes = fact_notes("It takes 5 years.", [{"text": t} for t in self.EV])
        self.assertEqual(notes[0]["kind"], "verification")
        self.assertIn("5 years", notes[0]["text"])

    def test_evidence_conflict_note(self):
        from src.conflicts import evidence_conflicts
        ev = [{"source": "MSU January/February 2027 Intake Advert", "page": 7,
               "text": "PROGRAMME: Master of Arts Degree in Archaeology\nDURATION AS ADVERTISED: 1 ½ years"},
              {"source": "MSU Humanities Yearbook", "page": 169,
               "text": "REGULATIONS FOR THE MASTER OF ARTS DEGREE IN ARCHAEOLOGY (MARC)\n\nDuration:\n\n2 years\n"}]
        notes = evidence_conflicts(ev)
        self.assertEqual(len(notes), 1)
        self.assertIn("1.5 years (p. 7)", notes[0]["text"])
        self.assertIn("2 years (p. 169)", notes[0]["text"])
        same = [ev[0], {**ev[1], "text": ev[1]["text"].replace("2 years", "1 ½ years")}]
        self.assertEqual(evidence_conflicts(same), [])

    def test_knowledge_base_conflict_scan(self):
        from src.conflicts import duration_conflicts, durations
        self.assertEqual(durations("1 1/2years"), {1.5})
        self.assertEqual(durations("4 years -3 Years for Block Release"), {3.0, 4.0})
        found = {c["programme"] for c in duration_conflicts()}
        self.assertIn("Master of Arts Degree in Archaeology", found)
        self.assertNotIn("Undergraduate Diploma in Social Work", found)     # a Certificate is a different programme


class C4AndAnswerCorrectionTests(unittest.TestCase):
    def test_c4_not_found_wording_is_detected(self):
        from src.safeguards import is_not_found
        self.assertTrue(is_not_found("answered", "The MSU documents searched do not contain the WiFi password."))
        self.assertFalse(is_not_found("answered", "The documents searched do not contain a start date; it is "
                                                  "4 years【Evidence 1】."))

    def test_empty_response_is_retried_once_with_light_reasoning(self):
        from tests.test_assistant import FakeLLM, fake_assistant
        from src.llm import LLMError
        from src.llm.base import LLMResponse

        class EmptyOnce(FakeLLM):
            def _complete(self, messages, settings):
                self.messages.append((messages, settings.reasoning_effort))
                if len(self.messages) == 1 or "always empty" in messages[1].content:
                    raise LLMError("empty_response", "Groq returned no final answer")
                return LLMResponse(text="Answer citing Evidence 1.", provider="fake", requested_model=settings.model,
                                   returned_model=settings.model, finish_reason="stop", usage={})
        llm = EmptyOnce()
        r = fake_assistant(llm).ask("Who chairs Council?")
        self.assertEqual((r.status, r.retried_empty), ("answered", True))
        self.assertEqual([e for _, e in llm.messages], ["medium", "low"])
        llm = EmptyOnce()
        r = fake_assistant(llm).ask("always empty")
        self.assertEqual((r.status, r.error_kind, len(llm.messages)), ("generation_error", "empty_response", 2))

    def test_preferably_notes_are_quoted_not_decided(self):
        from src.eligibility_answer import programme_line
        from src.eligibility_engine import evaluate
        ev = evaluate({"Economics": "A", "Mathematics": "B"},
                      {"English Language": "B", "Mathematics": "C", "Biology": "C", "History": "C", "Geography": "C"})
        r = next(x for x in ev.results if x.id == "MSU-JF2027-001")
        line = programme_line(r)
        self.assertNotIn("not required", line)
        self.assertIn("The advert says “preferably”: Agriculture, Mathematics", line)
        self.assertIn("not confirmed", line)

    def test_degenerate_answer_is_retried_and_never_shown(self):
        from tests.test_assistant import FakeLLM, fake_assistant
        from src.assistant import degenerate
        from src.llm.base import LLMResponse
        self.assertTrue(degenerate("| Route |" + "-" * 400))
        self.assertFalse(degenerate("| Route | Requirements |\n|-------|-----------------------------|"))

        class Dashes(FakeLLM):
            def __init__(self, good_on_retry):
                super().__init__()
                self.good = good_on_retry

            def _complete(self, messages, settings):
                self.messages.append(settings.reasoning_effort)
                text = "Answer citing Evidence 1." if self.good and len(self.messages) > 1 else "|" + "-" * 3000
                return LLMResponse(text=text, provider="fake", requested_model=settings.model,
                                   returned_model=settings.model, finish_reason="length", usage={})
        llm = Dashes(True)
        r = fake_assistant(llm).ask("Who chairs Council?")
        self.assertEqual((r.status, r.answer, llm.messages), ("answered", "Answer citing Evidence 1.", ["medium", "low"]))
        r = fake_assistant(Dashes(False)).ask("Who chairs Council?")
        self.assertEqual((r.status, r.error_kind, r.answer), ("generation_error", "empty_response", None))

    def test_c4_prompt_is_g2_plus_documented_edits_and_c3_is_unchanged(self):
        from src import c3_candidate
        from src.profiles import C4_SYSTEM_PROMPT, build_c3_messages, build_c4_messages
        self.assertTrue(C4_SYSTEM_PROMPT.startswith(c3_candidate.G2_SYSTEM_PROMPT.split("3. Answer")[0]))
        self.assertNotIn("documents provided", C4_SYSTEM_PROMPT)
        self.assertIn("Never call a mode full-time or part-time", C4_SYSTEM_PROMPT)
        self.assertIn("never create a campus and mode combination", C4_SYSTEM_PROMPT)
        ev = [{"rank": 1, "chunk_id": 1, "source": "MSU Humanities Yearbook", "page": 1, "heading": "H", "text": "t"}]
        c3, c4 = build_c3_messages("q", ev), build_c4_messages("q", ev)
        self.assertEqual(c3[0].content, c3_candidate.G2_SYSTEM_PROMPT)        # the evaluated C3 stays byte-identical
        self.assertEqual(c3[1].content, c4[1].content)                        # only the system prompt differs

    def test_app_uses_c4_on_kb_profiles(self):
        import inspect
        from src import assistant
        self.assertIn("build_c4_messages", inspect.getsource(assistant.Assistant.create))

    def test_unsupported_descriptors_are_removed_supported_kept(self):
        from src.safeguards import remove_unsupported_descriptors as r
        ev = ["MODES OF ENTRY: Gweru Conventional; Harare Weekend School"]
        self.assertEqual(r("The programme is offered as a conventional (full‑time) route at Gweru.", ev),
                         "The programme is offered as a conventional route at Gweru.")
        self.assertEqual(r("- **Conventional** – full‑time study at the Gweru campus.", ev),
                         "- **Conventional** – study at the Gweru campus.")
        self.assertEqual(r("Must be employed as a full-time teacher.", ["employed as a full-time teacher"]),
                         "Must be employed as a full-time teacher.")

    def test_campus_mode_combinations(self):
        from src.safeguards import mode_combination_notes, unadvertised_pairs
        ev = [{"text": "MODES OF ENTRY: Zvishavane Conventional; Zvishavane Visiting; Bulawayo Weekend School; "
                       "Bulawayo Conventional"}]
        self.assertEqual(unadvertised_pairs("| Bulawayo | Visiting | 3 years |", ev), ["Bulawayo Visiting"])
        self.assertEqual(unadvertised_pairs("Zvishavane Conventional and Bulawayo Visiting", ev), ["Bulawayo Visiting"])
        for ok in ("| Zvishavane | Visiting | 3 years (Visiting/Weekend School) |",
                   "Offered at Zvishavane (Conventional, Visiting) and Bulawayo (Weekend School).",
                   "a conventional route at Zvishavane and a weekend‑school route at Bulawayo"):
            self.assertEqual(unadvertised_pairs(ok, ev), [], ok)
        self.assertEqual(mode_combination_notes("| Bulawayo | Visiting |", ev)[0]["kind"], "mode_combination")
        self.assertEqual(unadvertised_pairs("| Bulawayo | Visiting |", [{"text": "no modes line"}]), [])
