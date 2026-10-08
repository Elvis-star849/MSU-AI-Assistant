"""S7-1 non-live tests: manifest/order, guarded runner, blind packages, spot-check selection and results logic.

No call reaches Groq: the runner is exercised with a fake client. Run from the project root:
python -m unittest discover -s tests -t .
"""
import json
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, "eval/stage7")
from s7_1_core import (COMPARISONS, REPLICATE, build_absolute_package, build_pairwise_package, compute_results,  # noqa: E402
                       execute, frozen_settings, oos_outcome, plan_items, randomized_order, read_attempts,
                       replicate_adjacent, spot_check_selection, strip_markdown, validate_absolute, validate_pairwise,
                       build_request)
from src.context import SYSTEM_PROMPT, build_messages  # noqa: E402
from src.llm.base import GenerationSettings, LLMClient, LLMError, LLMResponse  # noqa: E402

DESIGN = json.load(open("eval/stage7/s7_1_design.json", encoding="utf-8"))
PROMPTS = json.load(open("eval/stage7/s7_1_prompts.json", encoding="utf-8"))


def toy_evidence():
    ev = lambda n: {"rank": n, "chunk_id": n, "source": "MSU Humanities Yearbook", "page": n, "heading": "Section: X",
                    "text": f"passage {n}", "retrieval_rank": n, "retrieval_score": 0.5, "rerank_score": 1.0,
                    "route": "vector", "configuration": "main"}
    main = {"question": "Q main?", "category": "natural_language", "set": "main",
            "answer_key": {"sufficient": "key", "pages": ["Hum 1"]}, "sufficient_evidence_numbers": [1],
            "evidence": [ev(1), ev(2)]}
    oos = {"question": "Q oos?", "category": "out_of_scope", "set": "oos", "answer_key": None,
           "sufficient_evidence_numbers": [], "evidence": [ev(3)]}
    return {"questions": {"N1": main, "O1": oos}}


def toy_manifest(evidence):
    order, _ = randomized_order(plan_items(["N1"], ["O1"]), 1)
    for position, item in enumerate(order, 1):
        item.update({"position": position, **{k: v for k, v in build_request(item, evidence, PROMPTS).items()
                                                if k != "messages"}})
    return {"order": order, "total_items": len(order)}


class FakeLLM(LLMClient):
    provider = "fake"

    def __init__(self, fail_on=None):
        super().__init__(sleep=lambda s: None)
        self.calls, self.fail_on = [], fail_on or set()

    def _complete(self, messages, settings):
        self.calls.append(messages)
        if len(self.calls) in self.fail_on:
            raise LLMError("rate_limit", "Groq request failed: rate_limit (HTTP 429)", status_code=429)
        return LLMResponse(text=f"**Answer** {len(self.calls)}", provider="fake", requested_model=settings.model,
                           returned_model=settings.model, finish_reason="stop", usage={"total_tokens": 10})


def settings(**kw):
    return frozen_settings(DESIGN).with_changes(**kw)


class FrozenInputsTests(unittest.TestCase):
    def test_default_system_prompt_is_s7_0_baseline(self):
        ev = toy_evidence()["questions"]["N1"]["evidence"]
        self.assertEqual(build_messages("q", ev), build_messages("q", ev, system_prompt=SYSTEM_PROMPT))
        self.assertEqual(PROMPTS["arms"]["arm0"]["text"], SYSTEM_PROMPT)

    def test_frozen_settings(self):
        s = frozen_settings(DESIGN)
        self.assertEqual((s.model, s.temperature, s.reasoning_effort, s.max_completion_tokens, s.max_retries),
                         ("openai/gpt-oss-20b", 0.0, "medium", 4096, 0))

    def test_real_manifest(self):
        m = json.load(open("eval/stage7/s7_1_manifest.json", encoding="utf-8"))
        self.assertEqual((m["total_items"], len(m["order"]), len({i["item_id"] for i in m["order"]})), (75, 75, 75))
        self.assertFalse(replicate_adjacent(m["order"]))
        self.assertEqual(m["seed"], DESIGN["ordering"]["seed"])
        for q in {i["question_id"] for i in m["order"]}:
            self.assertEqual(len({i["user_sha256"] for i in m["order"] if i["question_id"] == q}), 1)
        reordered, _ = randomized_order(plan_items(
            [q for c in ("natural_language", "exact_code", "code_in_context") for q in
             json.load(open("eval/stage7/s7_1_questions.json"))["main"][c]],
            json.load(open("eval/stage7/s7_1_questions.json"))["oos_diagnostic_S7_1B"]), m["seed"])
        self.assertEqual([i["item_id"] for i in reordered], [i["item_id"] for i in m["order"]])  # reproducible


class OrderTests(unittest.TestCase):
    def test_plan_counts(self):
        items = plan_items(["N1", "E1"], ["O1"])
        self.assertEqual(len(items), 11)
        self.assertEqual(sum(i["arm"] == REPLICATE for i in items), 2)
        self.assertTrue(all(i["prompt"] == "arm0" for i in items if i["arm"] == REPLICATE))

    def test_adjacency_rule(self):
        a, r = {"question_id": "N1", "arm": "arm0"}, {"question_id": "N1", "arm": REPLICATE}
        o = {"question_id": "N2", "arm": "arm0"}
        self.assertTrue(replicate_adjacent([o, r, a]))
        self.assertFalse(replicate_adjacent([a, o, r]))
        for seed in range(30):
            order, _ = randomized_order(plan_items(["N1"], []), seed)  # 4 items: adjacency is common
            self.assertFalse(replicate_adjacent(order))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.runs = os.path.join(self.dir, "runs.jsonl")
        self.evidence = toy_evidence()
        self.manifest = toy_manifest(self.evidence)
        self.waits = []

    def run_once(self, client, **kw):
        return execute(self.manifest, self.evidence, PROMPTS, client, settings(), self.runs,
                       sleep=self.waits.append, log=lambda s: None, **kw)

    def test_each_item_exactly_once_in_frozen_order_with_pacing(self):
        client = FakeLLM()
        result = self.run_once(client)
        attempts = read_attempts(self.runs)
        self.assertEqual(len(client.calls), 7)
        self.assertEqual([a["item_id"] for a in attempts], [i["item_id"] for i in self.manifest["order"]])
        self.assertEqual(self.waits, [3.0] * 6)
        self.assertEqual(result, {"sent": 7, "stopped_on_failure": None})
        self.assertTrue(all(a["attempts"] == 1 and a["attempt_type"] == "planned" for a in attempts))
        self.assertEqual(self.run_once(client), {"sent": 0, "stopped_on_failure": None})  # nothing beyond manifest
        self.assertEqual(len(client.calls), 7)

    def test_stops_on_first_failure_and_never_resends_automatically(self):
        client = FakeLLM(fail_on={3})
        result = self.run_once(client)
        self.assertEqual((result["sent"], len(client.calls)), (3, 3))
        failed = self.manifest["order"][2]["item_id"]
        self.assertEqual(result["stopped_on_failure"], failed)
        resume = FakeLLM()
        self.run_once(resume)  # resume sends only never-attempted items
        self.assertEqual(len(resume.calls), 4)
        attempts = read_attempts(self.runs)
        self.assertEqual(sum(a["item_id"] == failed for a in attempts), 1)

    def test_resend_requires_failed_item_and_owner_approval(self):
        self.run_once(FakeLLM(fail_on={1}))
        failed = self.manifest["order"][0]["item_id"]
        with self.assertRaises(ValueError):
            self.run_once(FakeLLM(), resend_item=failed)
        with self.assertRaises(ValueError):
            self.run_once(FakeLLM(), resend_item=self.manifest["order"][1]["item_id"], resend_approval="ok")
        client = FakeLLM()
        self.run_once(client, resend_item=failed, resend_approval="owner approved on 2026-10-09")
        attempts = [a for a in read_attempts(self.runs) if a["item_id"] == failed]
        self.assertEqual([a["attempt_type"] for a in attempts], ["planned", "approved_resend_extra_attempt"])
        self.assertEqual(len(client.calls), 1)

    def test_guards(self):
        with self.assertRaises(ValueError):
            self.run_once(FakeLLM(), pace_s=1.0)
        with self.assertRaises(ValueError):
            execute(self.manifest, self.evidence, PROMPTS, FakeLLM(), settings(max_retries=1), self.runs,
                    sleep=lambda s: None, log=lambda s: None)
        tampered = json.loads(json.dumps(self.manifest))
        tampered["order"][0]["prompt_sha256"] = "sha256:0"
        with self.assertRaises(RuntimeError):
            execute(tampered, self.evidence, PROMPTS, FakeLLM(), settings(), self.runs, sleep=lambda s: None,
                    log=lambda s: None)
        tampered["total_items"] = 8
        with self.assertRaises(ValueError):
            execute(tampered, self.evidence, PROMPTS, FakeLLM(), settings(), self.runs, sleep=lambda s: None,
                    log=lambda s: None)

    def test_replicate_sends_identical_request_to_arm0(self):
        client = FakeLLM()
        self.run_once(client)
        sent = {a["item_id"]: a["prompt_sha256"] for a in read_attempts(self.runs)}
        self.assertEqual(sent["N1/arm0"], sent[f"N1/{REPLICATE}"])
        self.assertNotEqual(sent["N1/arm0"], sent["N1/arm1"])


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.evidence = toy_evidence()
        self.answers = {i["item_id"]: f"## Heading\n- **point** for {i['item_id']}"
                        for i in plan_items(["N1"], ["O1"])}

    def test_strip_markdown(self):
        text = "# Title\n**Bold** and *it*\n- item\n1. step\n| a | b |\n|---|---|\n| c | d |\n---\n`code`"
        self.assertEqual(strip_markdown(text), "Title\nBold and it\nitem\nstep\na; b\nc; d\ncode")

    def test_absolute_package_is_blind_and_complete(self):
        answers = {i: "## Heading\n- **point**" for i in self.answers}  # answers carry no item IDs
        text, mapping = build_absolute_package(DESIGN, self.evidence, answers, random.Random(5))
        self.assertEqual(len(mapping), 7)
        self.assertEqual(set(mapping.values()), set(self.answers))
        for word in ("arm0", "arm1", "arm2", "replicate", "Arm 0", "prompt", "**", "## Heading", "\n- **"):
            self.assertNotIn(word, text)
        self.assertIn("Heading\npoint", text)
        self.assertIn("Do not inspect any files and do not use any tools.", text)
        self.assertIn("Answer key: key", text)

    def test_pairwise_package(self):
        text, mapping = build_pairwise_package(DESIGN, self.evidence, self.answers, random.Random(5))
        self.assertEqual(len(mapping), 3)  # one main question x three comparisons
        self.assertEqual(sorted(p["comparison"] for p in mapping.values()), sorted(COMPARISONS))
        self.assertNotIn("replicate", text.split("######## COMPARISON")[0].lower())

    def test_validation(self):
        _, a_map = build_absolute_package(DESIGN, self.evidence, self.answers, random.Random(1))
        main = [{"label": l, "correctness": 2, "groundedness": 2, "completeness": 2, "directness": 1,
                 "hallucination": False} for l, i in a_map.items() if i.startswith("N1")]
        oos = [{"label": l, "appropriate_abstention": True, "unsupported_general_knowledge_answer": False,
                "invented_msu_specific_information": False, "evidence_supports_answer": False}
               for l, i in a_map.items() if i.startswith("O1")]
        self.assertEqual(validate_absolute({"main": main, "oos": oos}, a_map), [])
        self.assertTrue(validate_absolute({"main": main[:-1], "oos": oos}, a_map))
        main[0]["correctness"] = 3
        self.assertTrue(validate_absolute({"main": main, "oos": oos}, a_map))
        _, p_map = build_pairwise_package(DESIGN, self.evidence, self.answers, random.Random(1))
        good = {"pairwise": [{"label": l, "preferred": "tie"} for l in p_map]}
        self.assertEqual(validate_pairwise(good, p_map), [])
        good["pairwise"][0]["preferred"] = "C"
        self.assertTrue(validate_pairwise(good, p_map))


class ResultTests(unittest.TestCase):
    def test_oos_precedence(self):
        base = {"appropriate_abstention": True, "unsupported_general_knowledge_answer": False,
                "invented_msu_specific_information": False, "evidence_supports_answer": False}
        self.assertEqual(oos_outcome(base), "pass")
        self.assertEqual(oos_outcome({**base, "unsupported_general_knowledge_answer": True}), "abstention_failure")
        self.assertEqual(oos_outcome({**base, "unsupported_general_knowledge_answer": True,
                                      "invented_msu_specific_information": True}), "serious_failure")
        self.assertEqual(oos_outcome({**base, "appropriate_abstention": False, "evidence_supports_answer": True}),
                         "pass")
        self.assertEqual(oos_outcome({**base, "appropriate_abstention": False}), "unclassified_owner_review")

    def scenario(self, arm1_correct, arm2_correct, rep_diff, pair, oos_invented=False):
        """15 main questions (5 per category) + 1 OOS; grades set per arm; pair: comparison -> list of 'x'/'y'/'tie'."""
        main_q = [f"{c}{n}" for c in "NEC" for n in range(1, 6)]
        cats = {"N": "natural_language", "E": "exact_code", "C": "code_in_context"}
        evidence = {"questions": {q: {"category": cats[q[0]], "set": "main"} for q in main_q}}
        evidence["questions"]["O1"] = {"category": "out_of_scope", "set": "oos"}
        correct = {"arm0": [2] * 15, "arm1": arm1_correct, "arm2": arm2_correct,
                   REPLICATE: [0 if i < rep_diff else 2 for i in range(15)]}
        abs_main, abs_map, n = [], {}, 0
        for arm, values in correct.items():
            for q, c in zip(main_q, values):
                n += 1
                abs_map[f"L{n}"] = f"{q}/{arm}"
                abs_main.append({"label": f"L{n}", "correctness": c, "groundedness": 2, "completeness": 2,
                                 "directness": 2, "hallucination": False})
        abs_oos = []
        for arm in ("arm0", "arm1", "arm2"):
            n += 1
            abs_map[f"L{n}"] = f"O1/{arm}"
            abs_oos.append({"label": f"L{n}", "appropriate_abstention": True,
                            "unsupported_general_knowledge_answer": False,
                            "invented_msu_specific_information": oos_invented and arm == "arm2",
                            "evidence_supports_answer": False})
        pair_map, pair_rows = {}, []
        for comparison, (x, y) in COMPARISONS.items():
            for q, outcome in zip(main_q, pair[comparison]):
                label = f"P{len(pair_map) + 1}"
                pair_map[label] = {"question_id": q, "comparison": comparison, "A": f"{q}/{y}", "B": f"{q}/{x}"}
                pair_rows.append({"label": label, "preferred": {"x": "B", "y": "A", "tie": "tie"}[outcome]})
        order = [{"item_id": i} for i in abs_map.values()]
        attempts = [{"item_id": i, "succeeded": True, "finish_reason": "stop", "attempt_type": "planned",
                     "reasoning_check": {"answer_reasoning_markers_found": [], "provider_returned_reasoning_field": False}}
                    for i in abs_map.values()]
        return compute_results(evidence, {"main": abs_main, "oos": abs_oos}, abs_map, {"pairwise": pair_rows},
                               pair_map, attempts, {"order": order})

    def test_selection_and_flags(self):
        ties = ["tie"] * 15
        r = self.scenario([2] * 15, [2] * 15, 0, {"arm1_vs_arm0": ["x"] * 3 + ["tie"] * 12,
                                                    "arm2_vs_arm0": ["x"] * 4 + ["tie"] * 11,
                                                    "replicate_vs_arm0": ties})
        self.assertTrue(r["eligibility"]["arm1"]["eligible"] and r["eligibility"]["arm2"]["eligible"])
        self.assertEqual(r["selected_prompt"], "arm2")  # greater wins-minus-losses
        self.assertTrue(r["conclusiveness"]["treat_as_conclusive"])
        r = self.scenario([2] * 15, [2] * 14 + [0], 0, {"arm1_vs_arm0": ["x"] * 3 + ties[3:],
                                                        "arm2_vs_arm0": ["x"] * 9 + ties[9:],
                                                        "replicate_vs_arm0": ties})
        self.assertFalse(r["eligibility"]["arm2"]["conditions"]["no_correctness_2_to_0"])
        self.assertEqual(r["selected_prompt"], "arm1")
        r = self.scenario([2] * 15, [2] * 15, 0, {"arm1_vs_arm0": ["x"] * 2 + ties[2:],
                                                    "arm2_vs_arm0": ["x"] * 4 + ["y"] * 2 + ties[6:],
                                                    "replicate_vs_arm0": ties})
        self.assertEqual(r["selected_prompt"], "arm0")  # neither reaches +3
        r = self.scenario([2] * 15, [2] * 15, 3, {"arm1_vs_arm0": ties, "arm2_vs_arm0": ties,
                                                    "replicate_vs_arm0": ties}, oos_invented=True)
        self.assertTrue(r["instability"]["flag_less_reliable"])
        self.assertEqual(r["oos_S7_1B"]["serious_failures"]["arm2"], ["O1"])
        self.assertFalse(r["conclusiveness"]["treat_as_conclusive"])
        r = self.scenario([2] * 15, [2] * 15, 0, {"arm1_vs_arm0": ties, "arm2_vs_arm0": ties,
                                                    "replicate_vs_arm0": ["x"] * 3 + ties[3:]})
        self.assertTrue(r["instability"]["flag_less_reliable"])

    def test_spot_check_selection(self):
        a_map = {f"L{i}": (f"N1/arm{i % 3}" if i < 12 else f"O1/arm{i % 3}") for i in range(15)}
        absolute = {"main": [{"label": f"L{i}", "hallucination": i == 2} for i in range(12)],
                    "oos": [{"label": f"L{i}", "invented_msu_specific_information": i == 13} for i in range(12, 15)]}
        p_map = {"P1": {"comparison": "arm1_vs_arm0"}, "P2": {"comparison": "replicate_vs_arm0"},
                 "P3": {"comparison": "arm2_vs_arm0"}}
        sel = spot_check_selection(absolute, a_map, p_map, 71002)
        self.assertEqual(sel["hallucination_flags"], ["L13", "L2"])
        self.assertEqual(sel["main_pairwise"], ["P1", "P3"])
        self.assertEqual(len(sel["absolute_sample"]), 5)
        self.assertEqual(sel, spot_check_selection(absolute, a_map, p_map, 71002))  # seeded


if __name__ == "__main__":
    unittest.main()
