"""Knowledge base: interrupted writes. A simulated crash (BaseException, like a killed process: no abort entry is
written) is injected at every crash-relevant step; the next operation must recover to a consistent state."""
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.kb import fsutil
from src.kb.errors import LockedError
from src.kb.versions import open_pointer, read_pointer
from tests.kb_helpers import ADMIN, APPROVER, UPLOADER, World


class SimulatedCrash(BaseException):
    pass


def crash_at(step, occurrence=1):
    seen = []

    def hook(name):
        if name == step:
            seen.append(name)
            if len(seen) == occurrence:
                raise SimulatedCrash(step)
    return hook


class RecoveryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = World(Path(self.tmp.name))
        self.kb = self.w.kb
        self.w.stage_both()
        self.kb.approve("roadmap-test", 1, APPROVER, basis="ok")
        self.before_public = read_pointer(self.kb.cfg, "public")["version"]

    def tearDown(self):
        fsutil.crash_point = lambda step: None
        self.tmp.cleanup()

    def status(self, doc_id):
        return next(d["status"] for d in self.kb.registry.load()["documents"] if d["doc_id"] == doc_id)

    def crash_publish(self, step):
        fsutil.crash_point = crash_at(step)
        with self.assertRaises(SimulatedCrash):
            self.kb.publish(APPROVER)
        fsutil.crash_point = lambda step: None
        self.assertEqual(len(self.kb.journal.open_operations()), 1)        # left open, as after a real crash

    def assert_consistent(self):
        self.assertEqual(self.kb.journal.open_operations(), [])
        report = self.kb.verify()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["warnings"], [], report)                 # registry agrees with both pointers
        self.assertFalse(any(p.name.startswith(".tmp-") for p in self.kb.cfg.versions_dir.iterdir()))


class TestPublishInterrupted(RecoveryCase):
    def test_crash_before_the_pointer_switch_rolls_back(self):
        for step in ("begun", "version_files_written", "version_verified"):
            with self.subTest(step=step):
                self.crash_publish(step)
                report = self.kb.recover(ADMIN)
                self.assertEqual(len(report["aborted"]), 1)
                self.assertEqual(read_pointer(self.kb.cfg, "public")["version"], self.before_public)
                self.assertEqual(self.status("roadmap-test"), "approved")
                self.assert_consistent()
        quarantined = list(self.kb.cfg.quarantine_dir.iterdir())
        self.assertEqual(len(quarantined), 2)                            # the two half-built versions, kept
        self.kb.publish(APPROVER)                                        # and publishing still works afterwards
        self.assertEqual(self.status("roadmap-test"), "published")
        self.assert_consistent()

    def test_crash_after_the_pointer_switch_completes(self):
        for step in ("pointer_switched", "registry_saved"):
            with self.subTest(step=step):
                self.crash_publish(step)
                new_public = read_pointer(self.kb.cfg, "public")["version"]
                self.assertNotEqual(new_public, self.before_public)
                report = self.kb.recover(ADMIN)
                self.assertEqual(len(report["completed"]), 1)
                self.assertEqual(self.status("roadmap-test"), "published")
                self.assertEqual(read_pointer(self.kb.cfg, "public")["version"], new_public)
                self.kb.refresh_staging(APPROVER)                        # the step publish() runs next
                self.assert_consistent()
                self.tearDown()
                self.setUp()

    def test_recovery_runs_automatically_on_the_next_write(self):
        self.crash_publish("pointer_switched")
        self.kb.refresh_staging(APPROVER)
        self.assertEqual(len(self.kb.last_recovery["completed"]), 1)
        self.assert_consistent()

    def test_ordinary_error_after_begin_is_aborted_and_cleaned_up(self):
        def fail(step):
            if step == "version_files_written":
                raise RuntimeError("disk full")
        fsutil.crash_point = fail
        with self.assertRaises(RuntimeError):
            self.kb.publish(APPROVER)
        fsutil.crash_point = lambda step: None
        self.assertEqual(self.kb.journal.open_operations(), [])          # abort recorded immediately
        self.assertEqual(self.status("roadmap-test"), "approved")
        self.kb.recover(ADMIN)                                           # moves the leftover temp folder away
        self.assert_consistent()


class TestOtherOperationsInterrupted(RecoveryCase):
    def test_stage_crash_after_staging_pointer_switch(self):
        self.kb.reject("intake-test", 1, APPROVER, "redo")
        new = self.w.tmp / "intake2.json"
        data = json.loads(self.w.intake_json.read_text(encoding="utf-8"))
        data["programmes"][0]["rag_text"] += " Revised."
        new.write_text(json.dumps(data), encoding="utf-8")
        self.kb.register_upload(new, self.w.intake_meta, UPLOADER, source_file=self.w.intake_pdf)
        self.kb.validate("intake-test", 2, UPLOADER)
        fsutil.crash_point = crash_at("pointer_switched")
        with self.assertRaises(SimulatedCrash):
            self.kb.stage("intake-test", 2, UPLOADER)
        fsutil.crash_point = lambda step: None
        self.kb.recover(ADMIN)
        entry = next(d for d in self.kb.registry.load()["documents"]
                     if d["doc_id"] == "intake-test" and d["doc_version"] == 2)
        self.assertEqual(entry["status"], "staged")
        self.assert_consistent()

    def test_registry_only_operation_crash_completes(self):
        new = self.w.tmp / "road_b.json"
        new.write_text(self.w.road_json.read_text(encoding="utf-8").replace("week", "month"), encoding="utf-8")
        self.kb.register_upload(new, {**self.w.road_meta, "doc_id": "roadmap-b"}, UPLOADER,
                                source_file=self.w.road_pdf)
        fsutil.crash_point = crash_at("begun")
        with self.assertRaises(SimulatedCrash):
            self.kb.validate("roadmap-b", 1, UPLOADER)                   # units + report already written
        fsutil.crash_point = lambda step: None
        self.kb.recover(ADMIN)
        self.assertEqual(self.status("roadmap-b"), "validated")
        self.kb.stage("roadmap-b", 1, UPLOADER)                          # the frozen units are usable
        self.assert_consistent()

    def test_stale_lock_from_a_killed_process(self):
        self.crash_publish("pointer_switched")
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self.kb.cfg.lock_path.write_text(json.dumps({"pid": dead.pid, "host": socket.gethostname(),
                                                     "operation": "publish", "actor": "approver"}))
        report = self.kb.recover(ADMIN)
        self.assertEqual(report["stale_lock_released"]["operation"], "publish")
        self.assertEqual(len(report["completed"]), 1)
        self.assertFalse(self.kb.cfg.lock_path.exists())

    def test_live_lock_blocks_writers_but_not_readers(self):
        self.kb.cfg.lock_path.write_text(json.dumps({"pid": 1, "host": "other-host"}))
        with self.assertRaises(LockedError):
            self.kb.publish(APPROVER)
        open_pointer(self.kb.cfg, "public")                              # readers never need the lock
        self.kb.unlock(ADMIN)
        self.kb.publish(APPROVER)

    def test_corrupt_pointer_target_is_detected_not_served(self):
        public = read_pointer(self.kb.cfg, "public")["version"]
        index = self.kb.cfg.versions_dir / public / "index.faiss"
        data = bytearray(index.read_bytes())
        data[-8:] = b"\x00" * 8                                          # flip the last vector bytes
        index.write_bytes(bytes(data))
        self.assertFalse(self.kb.verify()["ok"])


if __name__ == "__main__":
    unittest.main()
