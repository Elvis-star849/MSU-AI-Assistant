"""Admissions adviser: conversation flow, applicant profile, entry routes. No live model calls.

Covers incomplete profiles, mature entry, diploma (special entry) pathways, stale applicant data, corrections,
"those were my brother's results", new assessments with confirmation, progressive recommendations, and the safety
invariants (conditional never shown as confirmed, no invented details, no technical counts in the conversation).
"""
import random
import re
import subprocess
import sys
import unittest
from pathlib import Path

from src.admissions_adviser import DISCLAIMER, advise
from src.applicant_profile import CONFIRMED, INFERRED, STATED, ApplicantProfile, read_message
from src.conversation import ChatSession
from src.eligibility_engine import PASS_ONLY, o_check
from src import entry_routes as er

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = "I have 5 O-Level passes including Maths and English, and I'm 30 years old. What programme can I do?"
TECHNICAL = re.compile(r"\b\d+\s+(?:conditional matches|meet the advertised requirements|do not meet|other entry routes)\b"
                       r"|\bELIGIBILITY\b|\bRouter\b|\bOTHER_ROUTE\b|\bneeds_info\b|\bnot_met\b", re.I)


def talk(messages, profile=None):
    profile = profile or ApplicantProfile()
    replies = [advise(profile, m, i) for i, m in enumerate(messages)]
    return profile, replies


class ReportedExampleTests(unittest.TestCase):
    def test_o_levels_and_age_get_a_follow_up_not_a_database_report(self):
        profile, (r,) = talk([EXAMPLE])
        self.assertEqual(r.status, "follow_up")
        self.assertEqual(r.asked, "a_level_or_tertiary")
        self.assertFalse(r.shortlist)
        self.assertNotRegex(r.text, TECHNICAL)
        self.assertIn("5 O Level passes, including Mathematics and English Language", r.text)
        self.assertIn("age 30", r.text)
        self.assertIn("mature entry", r.text)
        self.assertEqual(r.text.count("?**"), 1)                     # exactly one question
        self.assertEqual(profile.o_level["Mathematics"].value, PASS_ONLY)
        self.assertEqual(profile.o_level["Mathematics"].status, INFERRED)
        self.assertEqual((profile.o_passes.value, profile.age.value), (5, 30))
        self.assertEqual(profile.age.status, STATED)
        self.assertFalse(profile.a_level)                            # nothing invented

    def test_complete_conversation_progressively_recommends(self):
        profile, replies = talk([EXAMPLE, "I only have O-Levels.", "I have worked for 8 years.", "In IT", "yes"])
        asked = [r.asked for r in replies]
        self.assertEqual(asked[:3], ["a_level_or_tertiary", "work", "work_field"])
        self.assertEqual(asked[3], "science")                        # the unknown that settles most IT routes
        self.assertFalse(replies[1].shortlist)                      # asks before recommending
        self.assertTrue(replies[2].shortlist)
        final = replies[4]
        self.assertLessEqual(len(final.shortlist), 5)
        names = [r.programme for r in final.shortlist]
        self.assertTrue(any("Computer" in n for n in names), names)
        for r in final.shortlist:
            self.assertIn(r.status, (er.MEETS, er.POSSIBLE, er.NEEDS_INFO))
            if r.route in (er.MATURE, er.SPECIAL):
                self.assertNotEqual(r.status, er.MEETS)
        self.assertIn(DISCLAIMER, final.text)
        self.assertNotRegex(final.text, TECHNICAL)
        self.assertIn("Detailed assessment", final.text)
        self.assertIsNotNone(final.assessment)                      # the full results stay available

    def test_programme_question_after_the_profile(self):
        profile, replies = talk([EXAMPLE, "No, only O Levels", "8 years in IT", "yes", "Can I study Computer Science?"])
        r = replies[-1]
        self.assertEqual(r.focus, "programme")
        self.assertIn("Bachelor of Science Honours Degree in Computer Science", r.text)
        self.assertLess(r.text.index("Honours Degree in Computer Science"),
                        r.text.index("Computer Science and Emerging Technologies"))      # the exact name first
        self.assertIn("you told me you don't have A Levels", r.text)
        self.assertIn("Mature entry", r.text)
        self.assertIn("5 years of experience in the relevant field", r.text)              # quoted from the advert


class IncompleteProfileTests(unittest.TestCase):
    def test_empty_question_gets_the_opener(self):
        _, (r,) = talk(["What can I study?"])
        self.assertEqual(r.asked, "opener")
        self.assertEqual(r.quick_replies, ["I have A Levels", "I only have O Levels", "I have a diploma or certificate"])

    def test_grades_without_subjects_are_kept_and_matched_in_order(self):
        profile, replies = talk(["I got A, B and C at A Level. What can I study?", "Mathematics, Physics and Chemistry"])
        self.assertEqual(replies[0].asked, "a_level_subjects")
        self.assertIn("(A, B and C)", replies[0].text)
        self.assertEqual({s: f.value for s, f in profile.a_level.items()},
                         {"Mathematics": "A", "Physics": "B", "Chemistry": "C"})
        self.assertTrue(all(f.status == INFERRED for f in profile.a_level.values()))
        self.assertIn("matched in the order you gave them", replies[1].text)

    def test_a_levels_without_o_levels_ask_for_o_levels_with_a_preliminary_shortlist(self):
        _, (r,) = talk(["I have Mathematics A, Computer Science A and Economics B, what can I study?"])
        self.assertEqual(r.asked, "o_level_grades")
        self.assertEqual(r.shortlist[0].programme, "Bachelor of Science Honours Degree in Computer Science")
        self.assertTrue(all(x.status == er.NEEDS_INFO for x in r.shortlist))
        self.assertNotIn("✅", r.text)
        self.assertIn("I need your O Level results to confirm them", r.text)

    def test_unreadable_answer_is_rephrased_once_then_skipped(self):
        profile, replies = talk(["I am 30", "hmm", "hmm"])
        self.assertIn("didn't quite catch", replies[1].text)
        self.assertEqual(replies[1].asked, replies[0].asked)
        self.assertNotEqual(replies[2].asked, replies[0].asked)
        self.assertIn(replies[0].asked, profile.declined)


class MatureEntryTests(unittest.TestCase):
    def test_cold_question_explains_the_documented_rule_and_asks_age(self):
        _, (r,) = talk(["What about mature entry?"])
        self.assertIn("General Academic Regulations", r.text)
        self.assertIn("p. 129", r.text)
        self.assertIn("Age alone is not enough", r.text)
        self.assertIn("18 programmes", r.text)
        self.assertEqual(r.asked, "age")

    def test_age_alone_never_makes_a_mature_route_possible(self):
        profile, _ = talk(["I am 30 and I don't have A levels"])
        for r in er.assess(profile).by_route(er.MATURE):
            self.assertEqual(r.status, er.NEEDS_INFO, r.programme)
            self.assertTrue(r.needs)

    def test_age_thresholds(self):
        def mature(age, sex=None):
            p = ApplicantProfile()
            p.apply(read_message(f"I'm {age}. I have 5 O levels including English, Maths and Science"), 1)
            if sex:
                p.apply(read_message(sex, "sex"), 2)
            return {r.status for r in er.assess(p).by_route(er.MATURE)}
        self.assertEqual(mature(22), {er.NOT_MET})
        self.assertNotIn(er.NOT_MET, mature(24, "Female"))
        self.assertEqual(mature(24, "Male"), {er.NOT_MET})
        self.assertNotIn(er.NOT_MET, mature(25))

    def test_programme_specific_conditions_are_applied(self):
        p = ApplicantProfile()
        p.apply(read_message("I'm 30, 5 O levels including English, Maths and Science, 3 years experience as a "
                             "programmer"), 1)
        cs = next(r for r in er.assess(p).by_route(er.MATURE) if r.id == "MSU-JF2027-156")
        self.assertEqual(cs.status, er.NOT_MET)
        self.assertIn("needs 5 years of experience", cs.outstanding[0])

    def test_23_or_24_asks_which_age_applies_before_work(self):
        _, replies = talk(["I only have O levels: 6 passes including English and Maths", "I'm 24"])
        self.assertEqual(replies[1].asked, "sex")
        self.assertIn("Skip", replies[1].quick_replies)


class DiplomaPathwayTests(unittest.TestCase):
    def test_diploma_then_field_then_special_entry_shortlist(self):
        profile, replies = talk(["I also have a diploma.", "Accounting", "I have 5 O levels including English and Maths"])
        self.assertEqual(replies[0].asked, "qual_field")
        self.assertIn("What is your diploma in?", replies[0].text)
        self.assertEqual(profile.qualifications[0].value, {"kind": "diploma", "field": "accounting"})
        special = [r for r in replies[2].shortlist if r.route == er.SPECIAL]
        self.assertTrue(special)
        self.assertTrue(all(r.status != er.MEETS for r in special))
        self.assertTrue(any("Accounting" in r.programme for r in special))
        self.assertIn("decides whether your qualification is relevant", replies[2].text)

    def test_employment_condition_is_settled_by_the_answer(self):
        profile, replies = talk(["I have an HND in Accounting", "5 O levels including English and Maths",
                                 "I am employed as an accountant"])
        acc = next(r for r in er.assess(profile).by_route(er.SPECIAL) if r.id == "MSU-JF2027-054")
        self.assertEqual(acc.status, er.POSSIBLE)
        self.assertFalse(any("employment" in o for o in acc.outstanding))


class StaleDataAndCorrectionTests(unittest.TestCase):
    A_LEVELS = "I have Mathematics A, Computer Science A and Economics B, what can I study?"

    def test_new_applicant_details_are_never_merged_silently(self):
        profile, replies = talk([self.A_LEVELS, EXAMPLE])
        r = replies[1]
        self.assertEqual(r.status, "confirm")
        self.assertIn("Are these details for the same person?", r.text)
        self.assertEqual({s: f.value for s, f in profile.a_level.items()},
                         {"Mathematics": "A", "Computer Science": "A", "Economics": "B"})
        self.assertIsNone(profile.age)                                # nothing applied before the answer

    def test_new_assessment_uses_only_the_latest_details(self):
        profile, replies = talk([self.A_LEVELS, EXAMPLE, "New assessment"])
        self.assertFalse(profile.a_level)
        self.assertEqual((profile.age.value, profile.o_passes.value), (30, 5))
        self.assertIn("nothing from earlier is used", replies[2].text)
        self.assertEqual(replies[2].asked, "a_level_or_tertiary")

    def test_same_person_combines_and_marks_earlier_details_confirmed(self):
        profile, replies = talk([self.A_LEVELS, EXAMPLE, "Same person, keep everything"])
        self.assertEqual(profile.age.value, 30)
        self.assertTrue(profile.a_level)
        self.assertTrue(all(f.status == CONFIRMED for f in profile.a_level.values()))

    def test_unclear_answer_to_the_confirmation_decides_nothing(self):
        profile, replies = talk([self.A_LEVELS, EXAMPLE, "hmm"])
        self.assertEqual(replies[2].status, "confirm")
        self.assertIsNotNone(profile.pending)

    def test_a_different_full_set_of_a_levels_asks_before_replacing(self):
        profile, replies = talk([self.A_LEVELS, "History A, Shona B and Sociology C", "Replace earlier A Levels"])
        self.assertEqual(replies[1].status, "confirm")
        self.assertEqual(set(profile.a_level), {"History", "Shona", "Sociology"})

    def test_correction_updates_the_value(self):
        profile, replies = talk(["I have Mathematics A, Physics B and Chemistry C", "Sorry, actually Chemistry is A"])
        self.assertEqual(profile.a_level["Chemistry"].value, "A")
        self.assertIn("Chemistry A (was C)", replies[1].text)
        self.assertNotEqual(replies[1].status, "confirm")

    def test_brothers_results_are_removed(self):
        profile, replies = talk(["I have Mathematics A, Physics B and Chemistry C",
                                 "Actually, those were my brother's results."])
        self.assertFalse(profile.a_level)
        self.assertIn("removed A Level Mathematics A, A Level Physics B and A Level Chemistry C", replies[1].text)
        self.assertEqual(replies[1].asked, "opener")


    def test_brothers_results_after_a_correction_remove_the_whole_set(self):
        profile, replies = talk(["I'm 19. I have Mathematics A, Physics B and Chemistry C", "Sorry, actually Chemistry is A",
                                 "Actually, those were my brother's results."])
        self.assertFalse(profile.a_level)
        self.assertIn("A Level Mathematics A", replies[2].text)
        self.assertIn("A Level Physics B", replies[2].text)
        self.assertIsNone(profile.age)                    # the same message described the brother

    def test_brothers_a_levels_do_not_remove_the_applicants_own_o_levels(self):
        profile, _ = talk(["English B, Maths C, 6 passes", "I have Mathematics A, Physics B and Chemistry C",
                           "Actually, those were my brother's results."])
        self.assertFalse(profile.a_level)
        self.assertEqual(profile.o_passes.value, 6)


class NewAssessmentTests(unittest.TestCase):
    def test_reset_needs_explicit_confirmation(self):
        profile, replies = talk(["I have History A, Shona B and Literature in English B", "Start a new assessment.",
                                 "No, keep my details"])
        self.assertEqual(replies[1].status, "confirm")
        self.assertIn("History A", replies[1].text)
        self.assertTrue(profile.a_level)                              # "No, keep" keeps everything
        self.assertIn("kept your details", replies[2].text)

    def test_confirmed_reset_clears_everything(self):
        profile, replies = talk(["I have History A, Shona B and Literature in English B", "Start a new assessment.",
                                 "Yes, start a new assessment"])
        self.assertTrue(profile.is_empty())
        self.assertEqual(replies[2].asked, "opener")

    def test_interface_button_reset(self):
        profile, _ = talk(["I am 30, 5 O levels including English"])
        r = advise(profile, "Start a new assessment", 5, confirmed_reset=True)
        self.assertTrue(profile.is_empty())
        self.assertIn("New assessment started", r.text)


class SafetyInvariantTests(unittest.TestCase):
    def test_five_o_levels_never_qualify_for_a_level_programmes(self):
        profile, _ = talk(["I only have O levels: 5 passes including English and Maths"])
        a = er.assess(profile)
        self.assertTrue(all(r.status == er.NOT_MET for r in a.by_route(er.NORMAL_A)))
        meets = {r.id for r in a.results if r.status == er.MEETS}
        self.assertTrue(meets <= {"MSU-JF2027-092", "MSU-JF2027-107", "MSU-JF2027-108", "MSU-JF2027-220"}, meets)

    def test_random_profiles_never_show_special_or_mature_as_confirmed(self):
        rnd = random.Random(7)
        subjects = ["Mathematics", "Physics", "Chemistry", "Biology", "Economics", "Accounting", "History", "Shona"]
        for _ in range(150):
            p = ApplicantProfile()
            parts = []
            if rnd.random() < 0.5:
                parts.append(", ".join(f"{s} {rnd.choice('ABCDE')}" for s in rnd.sample(subjects, 3)))
            parts.append(f"{rnd.randint(3, 9)} O levels including English and Maths")
            if rnd.random() < 0.6:
                parts.append(f"I'm {rnd.randint(17, 45)}")
            if rnd.random() < 0.4:
                parts.append(f"I have a diploma in {rnd.choice(['accounting', 'agriculture', 'information technology'])}")
            if rnd.random() < 0.5:
                parts.append(f"I have worked as a {rnd.choice(['nurse', 'programmer', 'teacher'])} for {rnd.randint(0, 12)} years")
            p.apply(read_message(". ".join(parts)), 1)
            for r in er.assess(p).results:
                if r.route in (er.SPECIAL, er.MATURE):
                    self.assertNotEqual(r.status, er.MEETS)
                if r.status == er.MEETS:
                    self.assertFalse(r.questions)

    def test_no_invented_values(self):
        u = read_message("I have 5 O level passes and 8 years of experience")
        self.assertIsNone(u.age)                                   # neither 5 nor 8 is an age
        self.assertEqual((u.o_passes, u.work_years), (5, 8))
        u = read_message("I'm 30 years old")
        self.assertIsNone(u.work_years)
        self.assertFalse(u.o_level)

    def test_conversation_text_never_contains_internal_labels(self):
        for msgs in (["What can I study?", "I only have O Levels", "6", "I'm 40", "no work experience"],
                     ["I have Mathematics A, Physics B and Chemistry B", "English B, Maths C, 6 passes", "show all"]):
            for r in talk(msgs)[1]:
                self.assertNotRegex(r.text, TECHNICAL)


class EngineAndDataTests(unittest.TestCase):
    def test_o_level_pass_without_grade(self):
        rule = {"min_passes": 5, "min_pass_grade": "C", "required_subjects": {"English Language": None, "Mathematics": "B"}}
        fails, confirm = o_check(rule, {"English Language": PASS_ONLY, "Mathematics": PASS_ONLY, "passes": 5})
        self.assertEqual(fails, [])
        self.assertTrue(any("Mathematics at grade B" in c for c in confirm))
        self.assertEqual(o_check(rule, {"English Language": "B", "Mathematics": "C", "passes": 5})[0],
                         ["O Level Mathematics needs grade B or better (you gave C)"])

    def test_entry_routes_file_is_built_from_the_advert_wording(self):
        r = subprocess.run([sys.executable, str(ROOT / "evaluation/eligibility_audit/build_entry_routes.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(er.MATURE_RULES), 18)


class RoutingTests(unittest.TestCase):
    def test_natural_follow_ups_reach_the_adviser(self):
        from src.router import ELIGIBILITY, INFO, route_with_reason
        cases = {"I only have O-Levels.": None, "I also have a diploma.": None, "I have worked for 8 years.": None,
                 "What about mature entry?": None, "Can I study Computer Science?": None,
                 "What if I don't have A-Levels?": None,
                 "Actually, those were my brother's results.": [{"path": "ELIGIBILITY", "asked": "o_level_grades"}],
                 "Start a new assessment.": [{"path": "ELIGIBILITY", "asked": None}], EXAMPLE: None,
                 "In IT": [{"path": "ELIGIBILITY", "asked": "work_field"}]}
        for q, history in cases.items():
            self.assertEqual(route_with_reason(q, history, None, None, has_results=bool(history))[0], ELIGIBILITY, q)
        for q in ("Can I do a module twice?", "Who chairs Council?", "How long is the BSc Computer Science?"):
            self.assertEqual(route_with_reason(q, [{"path": "ELIGIBILITY", "asked": "age"}], None, None)[0], INFO, q)

    def test_flow_keeps_one_profile_per_chat(self):
        from src.admissions_flow import handle_message

        class A:
            llm = settings = None
        chat = ChatSession()
        handle_message(chat, A(), EXAMPLE, log_path=None)
        other = ChatSession()
        handle_message(other, A(), "What can I study?", log_path=None)
        self.assertEqual(chat.applicant.age.value, 30)
        self.assertTrue(other.applicant.is_empty())               # a new chat never sees earlier details


if __name__ == "__main__":
    unittest.main()
