"""Deterministic eligibility engine: consistency with the supplied checker, the recorded rule corrections, and the
confirmation layer (strict / lenient readings). Offline; no model.

Run from the project root: python -m unittest tests.test_eligibility_engine -v
"""
import json
import random
import unittest
from pathlib import Path

from src.eligibility import check
from src.eligibility_engine import (CONDITIONAL, MEETS, NOT_MET, OTHER_ROUTE, RULES, TAX, evaluate, open_questions)

ROOT = Path(__file__).resolve().parents[1]
O_FULL = {"English": "B", "Mathematics": "C", "passes": 6}
GRADES = ["A", "B", "C", "D", "E", "F", "O"]
O_GRADES = ["A", "B", "C", "D", "E", "U"]


def outcome(a, o, pid):
    return evaluate(a, o).get(pid).outcome


def random_applicant(rng):
    subjects = rng.sample(sorted(TAX), rng.choice([1, 2, 3, 3, 3, 4]))
    a = {s: rng.choice(GRADES) for s in subjects}
    o = None if rng.random() < 0.3 else {k: v for k, v in (("English", rng.choice(O_GRADES)),
                                                             ("Mathematics", rng.choice(O_GRADES)),
                                                             ("passes", rng.randint(3, 9))) if rng.random() < 0.9}
    return a, (o or None)


class ConsistencyWithChecker(unittest.TestCase):
    def test_engine_never_contradicts_the_checker(self):
        rng = random.Random(20261016)
        for _ in range(2500):
            a, o = random_applicant(rng)
            c = check(a, o)
            e = evaluate(a, o)
            eligible = {x["id"] for x in c["eligible"]}
            maybe = eligible | {x["id"] for x in c["eligible_confirm"]}
            not_eligible = {x["id"] for x in c["not_eligible"]}
            meets = {r.id for r in e.by_outcome(MEETS)}
            positive = meets | {r.id for r in e.by_outcome(CONDITIONAL)}
            self.assertTrue(meets <= eligible, (a, o, sorted(meets - eligible)))          # MEETS only if checker eligible
            self.assertTrue(maybe <= positive, (a, o, sorted(maybe - positive)))          # checker positives never dropped
            self.assertTrue({r.id for r in e.by_outcome(NOT_MET)} <= not_eligible, (a, o))
            self.assertEqual({r.id for r in e.by_outcome(OTHER_ROUTE)}, {x["id"] for x in c["other_route"]})
            self.assertEqual(len(e.results), len(RULES["programmes"]))

    def test_evaluation_is_deterministic(self):
        a = {"Mathematics": "A", "Physics": "B", "Chemistry": "C"}
        self.assertEqual([(r.id, r.outcome, r.reasons, r.questions) for r in evaluate(a, O_FULL).results],
                         [(r.id, r.outcome, r.reasons, r.questions) for r in evaluate(dict(reversed(a.items())), O_FULL).results])


class Corrections(unittest.TestCase):
    def test_corrected_file_matches_the_recorded_corrections(self):
        import subprocess
        import sys
        r = subprocess.run([sys.executable, "evaluation/eligibility_audit/apply_corrections.py", "--check"], cwd=ROOT,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_supplied_rules_file_is_kept_unchanged(self):
        import hashlib
        supplied = ROOT / "src/eligibility/MSU_Eligibility_Rules.supplied.json"
        self.assertEqual(hashlib.sha256(supplied.read_bytes()).hexdigest()[:16], "3ffb21c60db1dce1")

    def test_c1_agriculture_requires_o_level_mathematics(self):
        a = {"Biology": "A", "Agriculture": "A", "Chemistry": "B"}
        for pid in ("MSU-JF2027-001", "MSU-JF2027-006", "MSU-JF2027-013", "MSU-JF2027-017"):
            self.assertEqual(outcome(a, {"English": "B", "Mathematics": "U", "passes": 6}, pid), NOT_MET, pid)
            self.assertIn(outcome(a, O_FULL, pid), (MEETS, CONDITIONAL), pid)

    def test_c3_c4_added_o_level_subjects(self):
        rules = {p["id"]: p for p in RULES["programmes"]}
        self.assertIn("Combined Science", rules["MSU-JF2027-133"]["o_level_rule"]["required_subjects"])
        self.assertEqual(len(rules["MSU-JF2027-133"]["requirements_as_advertised"]), 3)
        self.assertIn("African language", rules["MSU-JF2027-025"]["o_level_rule"]["required_subjects"])
        r = evaluate({"Shona": "A", "History": "B"}, {"English": "B", "Mathematics": "C", "passes": 6}).get("MSU-JF2027-025")
        self.assertEqual(r.outcome, CONDITIONAL)                    # the African language is always 'to confirm'
        self.assertTrue(any("African language" in t for t in r.to_confirm))

    def test_c5_geography_counts_as_science_but_only_conditionally_for_generic_slots(self):
        a = {"Chemistry": "A", "Geography": "B"}
        self.assertTrue(any(x["id"] == "MSU-JF2027-159" for x in check(a, O_FULL)["eligible"]))
        r = evaluate(a, O_FULL).get("MSU-JF2027-159")                 # Industrial Chemistry: Chemistry + any science
        self.assertEqual(r.outcome, CONDITIONAL)
        self.assertIn("Geography", r.reasons[0])
        geo = evaluate({"Mathematics": "A", "Geography": "B"}, {"English": "B", "Mathematics": "C", "Physics": "C",
                                                                "passes": 6}).get("MSU-JF2027-136")
        self.assertEqual(geo.outcome, MEETS)                         # Exploration Geophysics names Geography itself


class ConfirmationLayer(unittest.TestCase):
    def test_strict_reading_met_gives_a_verified_match(self):
        self.assertEqual(outcome({"Mathematics": "A", "Physics": "B", "Chemistry": "B"},
                                 {"English": "B", "Mathematics": "C", "Combined Science": "C", "passes": 6},
                                 "MSU-JF2027-126"), MEETS)                       # third science present
        self.assertEqual(outcome({"Biology": "A", "Chemistry": "B"}, O_FULL, "MSU-JF2027-006"), MEETS)
        self.assertEqual(outcome({"Mathematics": "A", "Computer Science": "B"}, O_FULL, "MSU-JF2027-156"), MEETS)

    def test_only_lenient_reading_met_is_conditional_with_the_question(self):
        r = evaluate({"Mathematics": "A", "Physics": "B"},
                     {"English": "B", "Mathematics": "C", "Combined Science": "C", "passes": 6}).get("MSU-JF2027-126")
        self.assertEqual(r.outcome, CONDITIONAL)
        self.assertIn("third science", r.questions[0])
        r = evaluate({"History": "A", "Shona": "B"}, O_FULL).get("MSU-JF2027-006")      # 'preferably Biology/Agriculture'
        self.assertEqual(r.outcome, CONDITIONAL)
        self.assertIn("preferably", r.questions[0])
        r = evaluate({"Mathematics": "A", "Biology": "B"}, O_FULL).get("MSU-JF2027-156")  # 'relevant' science
        self.assertEqual(r.outcome, CONDITIONAL)

    def test_llb_b_grade_scope(self):
        o = {"English": "B", "Mathematics": "B", "passes": 6}
        self.assertEqual(outcome({"History": "B", "Shona": "B", "Sociology": "B"}, o, "MSU-JF2027-147"), MEETS)
        r = evaluate({"History": "C", "Shona": "C", "Sociology": "B"}, o).get("MSU-JF2027-147")
        self.assertEqual(r.outcome, CONDITIONAL)
        self.assertIn("B or better", r.questions[0])

    def test_actuarial_points_reading(self):
        self.assertEqual(outcome({"Mathematics": "A", "Physics": "A", "Chemistry": "C"}, O_FULL, "MSU-JF2027-169"), MEETS)
        self.assertEqual(outcome({"Mathematics": "B", "Physics": "B", "Chemistry": "C"}, O_FULL, "MSU-JF2027-169"),
                         CONDITIONAL)                                 # 11 points over three subjects only
        self.assertEqual(outcome({"Mathematics": "C", "Physics": "A", "Chemistry": "A"}, O_FULL, "MSU-JF2027-169"), NOT_MET)

    def test_social_sciences_extension(self):
        r = evaluate({"History": "A", "Economics": "B"}, O_FULL).get("MSU-JF2027-181")
        self.assertFalse(any(x["id"] == "MSU-JF2027-181" for x in check({"History": "A", "Economics": "B"}, O_FULL)["eligible"]))
        self.assertEqual(r.outcome, CONDITIONAL)                      # the checker says not eligible; flagged instead
        self.assertIn("Economics", r.questions[0])
        self.assertEqual(outcome({"History": "A", "Sociology": "B"}, O_FULL, "MSU-JF2027-181"), MEETS)
        self.assertEqual(outcome({"History": "A", "Economics": "B"}, O_FULL, "MSU-JF2027-206"), NOT_MET)  # Arts/Humanities only

    def test_extra_conditions_and_employment_keep_matches_conditional(self):
        r = evaluate({"Mathematics": "A"}, {"English": "B", "Mathematics": "B", "passes": 6}).get("MSU-JF2027-220")
        self.assertEqual(r.outcome, CONDITIONAL)
        self.assertTrue(any("one sitting" in t for t in r.to_confirm))
        r = evaluate({"Chemistry": "A", "Biology": "B"}, O_FULL).get("MSU-JF2027-161")
        self.assertEqual(r.outcome, CONDITIONAL)
        self.assertTrue(any("employment" in t for t in r.to_confirm))

    def test_missing_o_level_is_never_meets(self):
        e = evaluate({"Mathematics": "A", "Physics": "A", "Chemistry": "A"}, None)
        self.assertEqual(e.counts()[MEETS], 0)
        self.assertGreater(e.counts()[CONDITIONAL], 0)

    def test_not_met_lists_alternative_routes(self):
        r = evaluate({"History": "A", "Shona": "B"}, O_FULL).get("MSU-JF2027-054")        # Applied Accounting
        self.assertEqual(r.outcome, NOT_MET)
        self.assertTrue(any("employment" in l.lower() or "diploma" in l.lower() for l in r.alternative_routes))

    def test_open_questions_are_listed_for_review(self):
        qs = open_questions()
        ids = {q["id"] for q in qs}
        for pid in ("MSU-JF2027-126", "MSU-JF2027-147", "MSU-JF2027-169", "MSU-JF2027-006", "MSU-JF2027-181"):
            self.assertIn(pid, ids)
        overrides = json.loads((ROOT / "src/eligibility/rule_overrides.json").read_text(encoding="utf-8"))
        known = {p["id"] for p in RULES["programmes"]}
        self.assertTrue(set(overrides["programmes"]) <= known)


if __name__ == "__main__":
    unittest.main()
