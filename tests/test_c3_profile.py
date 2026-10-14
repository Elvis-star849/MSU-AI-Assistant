"""C3 profile integration tests (offline: no Groq calls, network blocked during the parity test).

Run from the project root: python -m unittest tests.test_c3_profile -v

Parity: the app's c3_public_0005 path must reproduce, for the public held-out questions of the evaluation that passed
the release gates, the same retrieved top-5 passages and byte-identical messages (remediation/heldout/...).
"""
import hashlib
import json
import os
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELDOUT = ROOT / "remediation/heldout"


def canonical(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


def kb_tree_hash():
    h = hashlib.sha256()
    for p in sorted((ROOT / "knowledge_base/store").rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(ROOT)).encode())
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


class ProfileUnitTests(unittest.TestCase):
    def test_frozen_candidate_copy_is_byte_identical(self):
        from src.profiles import CANDIDATE_SHA256
        app_copy = hashlib.sha256((ROOT / "src/c3_candidate.py").read_bytes()).hexdigest()
        self.assertTrue(app_copy.startswith(CANDIDATE_SHA256))
        frozen = ROOT / "remediation/candidate.py"
        if frozen.exists():
            self.assertEqual(app_copy, hashlib.sha256(frozen.read_bytes()).hexdigest())

    def test_profile_selection(self):
        from src.profiles import BASELINE, C3, ProfileError, current_profile
        self.assertEqual(current_profile({}), C3)                          # default = evaluated configuration
        self.assertEqual(current_profile({"MSU_ASSISTANT_PROFILE": "Baseline"}), BASELINE)
        with self.assertRaises(ProfileError):
            current_profile({"MSU_ASSISTANT_PROFILE": "staging"})          # no setting can select staging

    def test_public_pointer_is_the_evaluated_version(self):
        from src.profiles import EXPECTED_PUBLIC, verify_public_pointer
        pointer = verify_public_pointer()
        self.assertEqual((pointer["version"], pointer["manifest_sha256"]),
                         (EXPECTED_PUBLIC["version"], EXPECTED_PUBLIC["manifest_sha256"]))

    def test_wrong_public_pointer_is_refused(self):
        from src import profiles
        with patch("src.kb.versions.read_pointer", lambda cfg, kind: {"kind": "public", "version": "0006",
                                                                         "manifest_sha256": "x"}):
            with self.assertRaises(profiles.ProfileError):
                profiles.verify_public_pointer()


@unittest.skipUnless((HELDOUT / "frozen/heldout_frozen_inputs.json").exists(), "evaluation artifacts not present")
class ParityTests(unittest.TestCase):
    """Loads the real indexes and models once (about a minute)."""

    @classmethod
    def setUpClass(cls):
        from src.evidence import Stage6Retriever
        from src.profiles import open_public_retriever
        cls.kb_before = kb_tree_hash()
        models = Stage6Retriever("main")
        models._load()
        cls.retriever = open_public_retriever(models)
        cls.questions = [q for q in json.loads((HELDOUT / "heldout_questions.json").read_text(encoding="utf-8"))["questions"]
                         if q["system"] == "public"]
        cls.report = {i["id"]: i for i in json.loads((HELDOUT / "frozen/heldout_retrieval_report.json").read_text(encoding="utf-8"))["items"]}
        s_inputs = ROOT / "remediation/experiments/heldout/HO_S_C3_inputs.json"
        cls.frozen_msgs = {i["id"]: i["messages_sha256"] for i in json.loads(s_inputs.read_text(encoding="utf-8"))["items"]}
        real_connect = socket.socket.connect

        def no_network(*a, **k):
            raise RuntimeError("network disabled during the parity test")
        socket.socket.connect = no_network
        try:
            cls.evidence = {q["id"]: cls.retriever.retrieve(q["question"]) for q in cls.questions}
        finally:
            socket.socket.connect = real_connect

    def test_18_public_questions(self):
        self.assertEqual(len(self.questions), 18)

    def test_retrieval_parity_with_the_evaluation(self):
        for q in self.questions:
            self.assertEqual([e["passage_uid"] for e in self.evidence[q["id"]]], self.report[q["id"]]["top5"], q["id"])

    def test_message_parity_with_the_evaluation(self):
        from src.profiles import build_c3_messages
        for q in self.questions:
            msgs = build_c3_messages(q["question"], self.evidence[q["id"]])
            plain = [{"role": m.role, "content": m.content} for m in msgs]
            self.assertEqual(hashlib.sha256(canonical(plain)).hexdigest(), self.frozen_msgs[q["id"]], q["id"])

    def test_safeguards_do_not_change_evaluated_evidence(self):
        from src.safeguards import screen_evidence
        for q in self.questions:
            kept, withheld = screen_evidence(self.evidence[q["id"]])
            self.assertEqual(withheld, [], q["id"])

    def test_road_map_is_answerable_and_advert_is_absent(self):
        sources = {e["source"] for ev in self.evidence.values() for e in ev}
        self.assertIn("MSU 2027 Road Map", sources)
        self.assertNotIn("MSU January/February 2027 Intake Advert", sources)
        docs = {d["source"] if "source" in d else d.get("title", "") for d in self.retriever.store.kb["documents"]}
        self.assertFalse(any("Intake Advert" in str(d) for d in docs))

    def test_knowledge_base_not_modified(self):
        self.assertEqual(kb_tree_hash(), self.kb_before)


if __name__ == "__main__":
    unittest.main()
