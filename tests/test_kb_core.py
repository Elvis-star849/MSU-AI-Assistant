"""Knowledge base: identifiers, states, configuration/roles, atomic files, lock, journal, registry helpers."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.kb import ids, states
from src.kb.config import Actor, KBConfig
from src.kb.errors import InvalidIdentifier, InvalidTransition, LockedError
from src.kb.fsutil import atomic_write_json, canonical_json, read_json
from src.kb.journal import Journal
from src.kb.lock import WriterLock, force_unlock, pid_alive
from src.kb.registry import JsonRegistry, empty_state, find, ordered_for_build


class TestIdentifiers(unittest.TestCase):
    def test_uid_and_keys(self):
        self.assertEqual(ids.passage_uid("intake-2027-jan-feb", 1, "MSU-JF2027-107"),
                         "intake-2027-jan-feb/v1/MSU-JF2027-107")
        self.assertEqual(ids.record_key("roadmap-2027", "RM2027-11"), "roadmap-2027/RM2027-11")
        self.assertEqual(ids.doc_key("roadmap-2027", 2), "roadmap-2027@v2")
        self.assertEqual(ids.base_record_id(123), "c00123")
        self.assertEqual(ids.prose_record_id(18, 3), "p0018-c03")

    def test_invalid_identifiers(self):
        for bad in ("Intake", "a", "-x-", "a--b", "has space", "x/y", ""):
            with self.assertRaises(InvalidIdentifier):
                ids.check_doc_id(bad)
        for bad in ("", "a/b", "../x", "x" * 200):
            with self.assertRaises(InvalidIdentifier):
                ids.check_record_id(bad)
        for bad in (0, -1, True, "1"):
            with self.assertRaises(InvalidIdentifier):
                ids.check_version(bad)


class TestStates(unittest.TestCase):
    def test_happy_path_and_terminal_states(self):
        path = [None, "uploaded", "validated", "staged", "approved", "published", "superseded"]
        for a, b in zip(path, path[1:]):
            states.check_transition(a, b)
        for terminal in ("rejected", "withdrawn", "superseded"):
            with self.assertRaises(InvalidTransition):
                states.check_transition(terminal, "published")

    def test_no_shortcuts(self):
        for a, b in [("uploaded", "published"), ("validated", "approved"), ("staged", "published"),
                     ("published", "approved"), (None, "published")]:
            with self.assertRaises(InvalidTransition):
                states.check_transition(a, b)

    def test_visibility(self):
        self.assertEqual(states.VISIBLE["public"], {"published"})
        self.assertEqual(states.VISIBLE["staging"], {"published", "staged", "approved"})
        self.assertFalse(states.visible_in("public", "staged"))
        self.assertFalse(states.visible_in("public", "approved"))


class TestConfigAndRoles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("KB_PROFILE", None)
        os.environ.pop("KB_TWO_PERSON_RULE", None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_two_person_rule_follows_profile(self):
        self.assertFalse(KBConfig(root=self.root).two_person_rule)                    # development default
        self.assertTrue(KBConfig(root=self.root, profile="production").two_person_rule)
        os.environ["KB_PROFILE"] = "production"
        self.assertTrue(KBConfig(root=self.root).two_person_rule)

    def test_explicit_override_and_config_file(self):
        self.assertTrue(KBConfig(root=self.root, two_person_rule=True).two_person_rule)
        (self.root / "kb_config.json").write_text(json.dumps({"profile": "production", "two_person_rule": False}))
        cfg = KBConfig(root=self.root)
        self.assertEqual(cfg.profile, "production")
        self.assertFalse(cfg.two_person_rule)
        os.environ["KB_TWO_PERSON_RULE"] = "1"
        self.assertTrue(KBConfig(root=self.root).two_person_rule)

    def test_bad_profile_and_actor(self):
        with self.assertRaises(ValueError):
            KBConfig(root=self.root, profile="staging")
        with self.assertRaises(ValueError):
            Actor("x", {"superuser"})
        self.assertTrue(Actor("a", {"kb_admin"}).has_any("kb_approver"))
        self.assertFalse(Actor("u", {"kb_uploader"}).has_any("kb_approver"))


class TestFilesLockJournal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_atomic_json_is_canonical_and_leaves_no_temp(self):
        atomic_write_json(self.root / "a.json", {"b": 1, "a": [1, 2]})
        self.assertEqual(read_json(self.root / "a.json"), {"a": [1, 2], "b": 1})
        self.assertEqual((self.root / "a.json").read_bytes(), canonical_json({"a": [1, 2], "b": 1}))
        self.assertEqual([p.name for p in self.root.iterdir()], ["a.json"])

    def test_lock_excludes_second_writer_and_releases(self):
        path = self.root / ".lock"
        with WriterLock(path, "op", "a", "t"):
            with self.assertRaises(LockedError):
                WriterLock(path, "op2", "b", "t").acquire()
        self.assertFalse(path.exists())

    def test_stale_lock_from_dead_process_is_released(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self.assertFalse(pid_alive(dead.pid))
        path = self.root / ".lock"
        path.write_text(json.dumps({"pid": dead.pid, "host": socket.gethostname(), "operation": "publish"}))
        lock = WriterLock(path, "op", "a", "t").acquire()
        self.assertEqual(lock.released_stale["operation"], "publish")
        lock.release()

    def test_lock_from_other_host_needs_force_unlock(self):
        path = self.root / ".lock"
        path.write_text(json.dumps({"pid": 1, "host": "another-host"}))
        with self.assertRaises(LockedError):
            WriterLock(path, "op", "a", "t").acquire()
        self.assertEqual(force_unlock(path)["host"], "another-host")
        self.assertFalse(path.exists())

    def test_journal_open_operations_and_torn_line(self):
        j = Journal(self.root / "log.jsonl")
        j.append({"event": "begin", "op_id": "1", "doc_ids": ["d"]})
        j.append({"event": "commit", "op_id": "1", "doc_ids": ["d"]})
        j.append({"event": "begin", "op_id": "2", "doc_ids": ["d"]})
        with open(j.path, "a", encoding="utf-8") as f:
            f.write('{"event": "comm')                      # torn final line (crash mid-write)
        self.assertEqual([e["op_id"] for e in j.open_operations()], ["2"])
        self.assertEqual(len(j.history("d")), 3)


class TestRegistryHelpers(unittest.TestCase):
    def test_find_and_build_order(self):
        state = empty_state()
        state["documents"] = [
            {"doc_id": "base-b", "doc_version": 1, "status": "published", "base": True},
            {"doc_id": "z-doc", "doc_version": 1, "status": "staged", "stage_seq": 2},
            {"doc_id": "a-doc", "doc_version": 1, "status": "published", "publish_seq": 2},
            {"doc_id": "m-doc", "doc_version": 1, "status": "published", "publish_seq": 1},
            {"doc_id": "m-doc", "doc_version": 2, "status": "approved", "stage_seq": 1},
            {"doc_id": "r-doc", "doc_version": 1, "status": "rejected"}]
        self.assertEqual(find(state, "m-doc")["doc_version"], 2)
        order = [(d["doc_id"], d["doc_version"]) for d in ordered_for_build(state, states.VISIBLE["staging"])]
        self.assertEqual(order, [("base-b", 1), ("m-doc", 1), ("a-doc", 1), ("m-doc", 2), ("z-doc", 1)])
        public = [d["doc_id"] for d in ordered_for_build(state, states.VISIBLE["public"])]
        self.assertEqual(public, ["base-b", "m-doc", "a-doc"])

    def test_json_registry_round_trip(self):
        with tempfile.TemporaryDirectory() as t:
            reg = JsonRegistry(Path(t) / "registry.json")
            self.assertEqual(reg.load(), empty_state())
            s = empty_state()
            s["documents"].append({"doc_id": "x", "doc_version": 1})
            reg.save(s)
            self.assertEqual(reg.load(), s)


if __name__ == "__main__":
    unittest.main()
