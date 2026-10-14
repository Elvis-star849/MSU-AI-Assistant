"""Knowledge base (Stage 3.3b): registry-aware rollback, reinstatement control, emergency override and
reconciliation, consistency verification, crash recovery of these operations, metadata updates with revalidation,
and readable headings."""
import json
import tempfile
import unittest
from pathlib import Path

from src.kb import fsutil, states
from src.kb.adapters import JsonRecordsAdapter, heading_from
from src.kb.config import Actor
from src.kb.errors import (IntegrityError, InvalidTransition, OverrideActive, PermissionDenied, ReinstatementRequired,
                           ValidationFailed)
from src.kb.fsutil import sha256_file
from src.kb.versions import read_pointer
from tests.kb_helpers import ADMIN, APPROVER, UPLOADER, World, event_records, group_spec, open_store, write_dataset

APPROVER2 = Actor("second-approver", {"kb_approver"})


def read_units(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class SimulatedCrash(BaseException):
    pass


def crash_at(step):
    def hook(name):
        if name == step:
            raise SimulatedCrash(step)
    return hook


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = World(Path(self.tmp.name))
        self.kb = self.w.kb

    def tearDown(self):
        fsutil.crash_point = lambda step: None
        self.tmp.cleanup()

    def status(self, doc_id, version=1):
        return next(d["status"] for d in self.kb.registry.load()["documents"]
                    if d["doc_id"] == doc_id and d["doc_version"] == version)

    def entry(self, doc_id, version=1):
        return next(d for d in self.kb.registry.load()["documents"]
                    if d["doc_id"] == doc_id and d["doc_version"] == version)

    def public_docs(self):
        return [(d["doc_id"], d["doc_version"]) for d in open_store(self.kb, "public").kb["documents"] if not d["base"]]

    def current(self):
        return read_pointer(self.kb.cfg, "public")["version"]

    def assert_consistent(self):
        report = self.kb.verify()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["warnings"], [], report)
        self.assertEqual(self.kb.journal.open_operations(), [])

    def two_public_versions(self):
        """v_a: base + roadmap;  v_b: base + roadmap + intake."""
        self.w.stage_both()
        self.kb.approve("roadmap-test", 1, APPROVER, basis="ok")
        self.kb.publish(APPROVER)
        v_a = self.current()
        self.kb.approve("intake-test", 1, APPROVER, basis="ok")
        self.kb.publish(APPROVER)
        return v_a, self.current()


class TestStates(unittest.TestCase):
    def test_suspended_transitions(self):
        states.check_transition("published", "suspended")
        states.check_transition("suspended", "published")
        states.check_transition("suspended", "withdrawn")
        for bad in (("suspended", "approved"), ("staged", "suspended"), ("suspended", "superseded")):
            with self.assertRaises(InvalidTransition):
                states.check_transition(*bad)

    def test_reinstatement_only_with_the_explicit_flag(self):
        for retired in ("withdrawn", "superseded"):
            with self.assertRaises(InvalidTransition):
                states.check_transition(retired, "published")
            states.check_transition(retired, "published", reinstatement=True)
        with self.assertRaises(InvalidTransition):
            states.check_transition("rejected", "published", reinstatement=True)

    def test_suspended_is_never_visible(self):
        self.assertFalse(states.visible_in("public", "suspended"))
        self.assertFalse(states.visible_in("staging", "suspended"))


class TestRegistryAwareRollback(Case):
    def test_rollback_suspends_and_publish_does_not_resurrect(self):
        v_a, v_b = self.two_public_versions()
        result = self.kb.rollback(v_a, APPROVER, "intake error found")
        self.assertEqual(result["status_changes"], [["intake-test", 1, "published", "suspended"]])
        self.assertEqual(self.current(), v_a)
        self.assertEqual(self.status("intake-test"), "suspended")
        self.assert_consistent()
        staging = open_store(self.kb, "staging")                       # staging refreshed too
        self.assertFalse(any(p["doc_id"] == "intake-test" for p in staging.passages))
        self.kb.publish(APPROVER)                                       # nothing approved: must not bring it back
        self.assertEqual(self.public_docs(), [("roadmap-test", 1)])
        self.assert_consistent()

    def test_rolling_forward_restores_suspended_documents(self):
        v_a, v_b = self.two_public_versions()
        self.kb.rollback(v_a, APPROVER, "check")
        result = self.kb.rollback(v_b, APPROVER, "false alarm")
        self.assertEqual(result["status_changes"], [["intake-test", 1, "suspended", "published"]])
        self.assertEqual(self.status("intake-test"), "published")
        self.assert_consistent()

    def test_republish_a_suspended_document_with_a_recorded_decision(self):
        v_a, _ = self.two_public_versions()
        self.kb.rollback(v_a, APPROVER, "check")
        with self.assertRaises(ValidationFailed):
            self.kb.republish("intake-test", 1, APPROVER, basis=" ")
        self.kb.republish("intake-test", 1, APPROVER, basis="Corrected and re-checked", decision_date="2026-10-20")
        self.assertIn(("intake-test", 1), self.public_docs())
        self.assertEqual(self.entry("intake-test")["approvals"][-1]["decision"], "republished")
        self.assert_consistent()
        with self.assertRaises(InvalidTransition):
            self.kb.republish("intake-test", 1, APPROVER, basis="again")      # no longer suspended

    def test_suspended_document_can_be_withdrawn(self):
        v_a, _ = self.two_public_versions()
        self.kb.rollback(v_a, APPROVER, "check")
        self.kb.withdraw("intake-test", 1, APPROVER, "not coming back")
        self.assertEqual(self.status("intake-test"), "withdrawn")
        self.assert_consistent()


class TestReinstatementPrevention(Case):
    def withdrawn_setup(self):
        self.w.publish_roadmap_only()
        v_with = self.current()
        self.kb.withdraw("roadmap-test", 1, APPROVER, "wrong dates")
        return v_with

    def test_rollback_refuses_to_reinstate_without_approval_and_changes_nothing(self):
        v_with = self.withdrawn_setup()
        before_pointer, before_registry = self.current(), self.kb.registry.load()
        with self.assertRaises(ReinstatementRequired):
            self.kb.rollback(v_with, APPROVER2, "restore")
        with self.assertRaises(ReinstatementRequired):                  # a basis without listing the document
            self.kb.rollback(v_with, APPROVER2, "restore", reinstate={"basis": "ok", "documents": []})
        self.assertEqual(self.current(), before_pointer)
        self.assertEqual(self.kb.registry.load(), before_registry)
        self.assert_consistent()

    def test_explicit_reinstatement_is_recorded(self):
        v_with = self.withdrawn_setup()
        self.kb.rollback(v_with, APPROVER2, "restore", reinstate={
            "basis": "Withdrawal was a mistake", "documents": [["roadmap-test", 1]], "decision_date": "2026-10-21"})
        e = self.entry("roadmap-test")
        self.assertEqual(e["status"], "published")
        self.assertEqual((e["approvals"][-1]["decision"], e["approvals"][-1]["previous_status"],
                          e["approvals"][-1]["decision_date"]), ("reinstated", "withdrawn", "2026-10-21"))
        self.assertEqual(e["history"][-1]["from"], "withdrawn")
        self.assert_consistent()

    def test_two_person_rule_for_reinstatement(self):
        v_with = self.withdrawn_setup()
        self.kb.cfg.two_person_rule = True
        with self.assertRaises(PermissionDenied):                       # the approver who withdrew it
            self.kb.rollback(v_with, APPROVER, "restore",
                             reinstate={"basis": "mine", "documents": [["roadmap-test", 1]]})
        self.kb.rollback(v_with, APPROVER2, "restore",
                         reinstate={"basis": "independent", "documents": [["roadmap-test", 1]]})
        self.assertEqual(self.status("roadmap-test"), "published")

    def test_superseded_version_needs_reinstatement_and_successor_is_suspended(self):
        self.w.publish_roadmap_only()
        v1_public = self.current()
        changed = write_dataset(self.w.tmp / "road2.json", {"events": event_records(4, word="revised")},
                                sha256_file(self.w.road_pdf))
        self.kb.register_upload(changed, self.w.road_meta, UPLOADER, source_file=self.w.road_pdf)
        self.kb.validate("roadmap-test", 2, UPLOADER)
        self.kb.stage("roadmap-test", 2, UPLOADER)
        self.kb.approve("roadmap-test", 2, APPROVER, basis="revision")
        self.kb.supersede(("roadmap-test", 1), ("roadmap-test", 2), APPROVER, "revision")
        with self.assertRaises(ReinstatementRequired):
            self.kb.rollback(v1_public, APPROVER2, "revision was wrong")
        result = self.kb.rollback(v1_public, APPROVER2, "revision was wrong",
                                  reinstate={"basis": "go back to v1", "documents": [["roadmap-test", 1]]})
        self.assertIn(["roadmap-test", 2, "published", "suspended"], result["status_changes"])
        self.assertIn(["roadmap-test", 1, "superseded", "published"], result["status_changes"])
        self.assertEqual(self.public_docs(), [("roadmap-test", 1)])
        self.assert_consistent()


class TestEmergencyOverrideAndReconciliation(Case):
    def setUp(self):
        super().setUp()
        self.v_a, self.v_b = self.two_public_versions()
        self.registry_before = self.kb.registry.load()
        self.kb.rollback(self.v_a, APPROVER, "site is serving a wrong answer", emergency=True)

    def test_emergency_rollback_moves_only_the_pointer_and_blocks_publishing(self):
        self.assertEqual(self.current(), self.v_a)
        state = self.kb.registry.load()
        self.assertEqual(state["active_override"]["version"], self.v_a)
        self.assertEqual([d["status"] for d in state["documents"]],
                         [d["status"] for d in self.registry_before["documents"]])   # statuses untouched
        for blocked in (lambda: self.kb.publish(APPROVER),
                        lambda: self.kb.withdraw("roadmap-test", 1, APPROVER, "x"),
                        lambda: self.kb.republish("intake-test", 1, APPROVER, basis="x"),
                        lambda: self.kb.rollback(self.v_b, APPROVER, "x"),
                        lambda: self.kb.rollback(self.v_b, APPROVER, "x", emergency=True)):
            with self.assertRaises(OverrideActive):
                blocked()

    def test_verify_reports_the_expected_divergence_as_warnings_only(self):
        report = self.kb.verify()
        self.assertTrue(report["ok"], report)
        self.assertTrue(any("emergency override active" in w for w in report["warnings"]))
        self.assertTrue(any("intake-test v1: registry published, index absent" in w for w in report["warnings"]))
        plan = self.kb.reconcile_plan()
        self.assertEqual(plan["published_but_not_in_current"], [["intake-test", 1]])
        self.assertEqual(plan["needs_reinstatement_approval"], [])

    def test_reconcile_accept_index(self):
        result = self.kb.reconcile(APPROVER, "accept_index", "keep the safe version")
        self.assertEqual(result["status_changes"], [["intake-test", 1, "published", "suspended"]])
        self.assertIsNone(self.kb.registry.load()["active_override"])
        self.assertEqual(self.current(), self.v_a)
        self.assert_consistent()
        self.kb.publish(APPROVER)                                       # unblocked, and intake stays out
        self.assertEqual(self.public_docs(), [("roadmap-test", 1)])

    def test_reconcile_restore_registry(self):
        result = self.kb.reconcile(APPROVER, "restore_registry", "false alarm")
        self.assertNotEqual(result["version"], self.v_a)
        self.assertEqual(self.public_docs(), [("roadmap-test", 1), ("intake-test", 1)])
        self.assertIsNone(self.kb.registry.load()["active_override"])
        self.assert_consistent()

    def test_reconcile_without_override_is_a_no_op(self):
        self.kb.reconcile(APPROVER, "accept_index", "first")
        self.assertTrue(self.kb.reconcile(APPROVER, "accept_index", "again")["no_op"])

    def test_events_are_recorded(self):
        self.kb.reconcile(APPROVER, "accept_index", "keep")
        events = [e["event"] for e in self.kb.registry.load()["pointer_events"]]
        self.assertEqual(events, ["emergency_rollback", "reconcile:accept_index"])


class TestConsistencyErrors(Case):
    def setUp(self):
        super().setUp()
        self.w.publish_roadmap_only()

    def tamper_registry(self, change):
        state = self.kb.registry.load()
        change(state)
        self.kb.registry.save(state)

    def test_unexpected_registry_index_difference_is_an_error(self):
        self.tamper_registry(lambda s: next(d for d in s["documents"] if d["doc_id"] == "roadmap-test")
                             .__setitem__("status", "withdrawn"))
        report = self.kb.verify()
        self.assertFalse(report["ok"])
        self.assertTrue(any("roadmap-test v1: registry not visible, index published" in p for p in report["problems"]))
        with self.assertRaises(IntegrityError):
            self.kb.refresh_staging(APPROVER)                           # post-operation check catches it

    def test_frozen_base_mismatch_is_an_error(self):
        self.tamper_registry(lambda s: s["documents"][0].__setitem__("base_range", [0, 2]))
        self.assertTrue(any("frozen base document yearbook-humanities" in p for p in self.kb.verify()["problems"]))

    def test_staged_documents_without_a_staging_version_is_an_error(self):
        (self.kb.cfg.store_dir / "STAGING").unlink()
        self.assertTrue(any("no staging version exists" in p for p in self.kb.verify()["problems"]))


class TestRecoveryOfNewOperations(Case):
    def test_crash_during_normal_rollback(self):
        v_a, v_b = self.two_public_versions()
        for step, expect_current, expect_status in (("begun", v_b, "published"),
                                                    ("pointer_switched", v_a, "suspended"),
                                                    ("registry_saved", v_a, "suspended")):
            with self.subTest(step=step):
                fsutil.crash_point = crash_at(step)
                with self.assertRaises(SimulatedCrash):
                    self.kb.rollback(v_a, APPROVER, "test")
                fsutil.crash_point = lambda s: None
                self.kb.recover(ADMIN)
                self.assertTrue((self.kb.cfg.versions_dir / v_a).is_dir())    # an existing rollback target is
                self.assertTrue((self.kb.cfg.versions_dir / v_b).is_dir())    # never quarantined (bug found in 3.3b)
                self.assertEqual(self.current(), expect_current)
                self.assertEqual(self.status("intake-test"), expect_status)
                if expect_status == "suspended":
                    self.kb.refresh_staging(APPROVER)                   # the step rollback runs next
                    self.kb.rollback(v_b, APPROVER, "reset")            # back to the start for the next case
                self.assert_consistent()

    def test_crash_after_emergency_pointer_switch_records_the_override(self):
        v_a, v_b = self.two_public_versions()
        fsutil.crash_point = crash_at("pointer_switched")
        with self.assertRaises(SimulatedCrash):
            self.kb.rollback(v_a, APPROVER, "outage", emergency=True)
        fsutil.crash_point = lambda s: None
        self.kb.recover(ADMIN)
        self.assertEqual(self.kb.registry.load()["active_override"]["version"], v_a)
        with self.assertRaises(OverrideActive):
            self.kb.publish(APPROVER)

    def test_crash_during_reconcile_accept_index_completes(self):
        v_a, _ = self.two_public_versions()
        self.kb.rollback(v_a, APPROVER, "outage", emergency=True)
        fsutil.crash_point = crash_at("begun")
        with self.assertRaises(SimulatedCrash):
            self.kb.reconcile(APPROVER, "accept_index", "keep")
        fsutil.crash_point = lambda s: None
        self.kb.recover(ADMIN)
        self.assertIsNone(self.kb.registry.load()["active_override"])
        self.assertEqual(self.status("intake-test"), "suspended")
        self.kb.refresh_staging(APPROVER)
        self.assert_consistent()


class TestMetadataUpdate(Case):
    def setUp(self):
        super().setUp()
        self.w.register_both()
        self.kb.validate("intake-test", 1, UPLOADER)

    def labels_change(self, labels):
        options = json.loads(json.dumps(self.entry("intake-test")["adapter_options"]))
        options["groups"][1]["heading_labels"] = labels
        return {"adapter_options": options}

    def test_validated_document_returns_to_uploaded_and_must_be_revalidated(self):
        old = self.entry("intake-test")
        result = self.kb.update_metadata("intake-test", 1, self.labels_change({"fee": "Application fee"}),
                                         UPLOADER, "readable headings")
        self.assertEqual(result["changed"], ["adapter_options"])
        e = self.entry("intake-test")
        self.assertEqual((e["status"], e["units"], e["validation"]), ("uploaded", None, None))
        self.assertEqual(e["metadata_history"][0]["detached_units"], old["units"])
        self.assertTrue((self.kb.cfg.root / old["units"]["path"]).is_file())      # detached, not deleted
        self.assertEqual(e["history"][-1]["to"], "uploaded")
        with self.assertRaises(InvalidTransition):
            self.kb.stage("intake-test", 1, UPLOADER)                  # revalidation required first
        self.assertTrue(self.kb.validate("intake-test", 1, UPLOADER)["ok"])
        e = self.entry("intake-test")
        self.assertNotEqual(e["units"]["path"], old["units"]["path"])  # content-addressed: nothing overwritten
        units = read_units(self.kb.cfg.root / e["units"]["path"])
        info = next(u for u in units if u["record_id"] == "INFO-01")
        self.assertEqual(info["heading"], "Section: Application fee")
        old_units = read_units(self.kb.cfg.root / old["units"]["path"])
        for a, b in zip(old_units, units):                              # only headings changed
            self.assertEqual({k: v for k, v in a.items() if k != "heading"}, {k: v for k, v in b.items() if k != "heading"})
        self.assertEqual(e["dataset"], old["dataset"])                  # same file, hash and provenance
        self.assert_consistent()

    def test_no_change_is_a_no_op(self):
        self.assertTrue(self.kb.update_metadata("intake-test", 1, {"title": "Test Intake"}, UPLOADER, "same")["no_op"])
        self.assertEqual(self.status("intake-test"), "validated")

    def test_forbidden_fields_and_states(self):
        for bad in ({"doc_id": "x"}, {"status": "published"}, {"dataset": {}}, {"approvals": []}):
            with self.assertRaises(ValidationFailed):
                self.kb.update_metadata("intake-test", 1, bad, UPLOADER, "x")
        with self.assertRaises(ValidationFailed):
            self.kb.update_metadata("intake-test", 1, {"prior_approval": {"actor": "x"}}, UPLOADER, "x")
        with self.assertRaises(ValidationFailed):
            self.kb.update_metadata("intake-test", 1, {"title": "y"}, UPLOADER, " ")
        self.kb.stage("intake-test", 1, UPLOADER)
        for status_step in ("staged", "approved", "published"):
            with self.subTest(status=status_step):
                if status_step == "approved":
                    self.kb.approve("intake-test", 1, APPROVER, basis="ok")
                if status_step == "published":
                    self.kb.publish(APPROVER)
                with self.assertRaises(InvalidTransition):
                    self.kb.update_metadata("intake-test", 1, {"title": "late change"}, UPLOADER, "too late")
        with self.assertRaises(InvalidTransition):
            self.kb.update_metadata("yearbook-humanities", 1, {"title": "x"}, UPLOADER, "base")

    def test_uploaded_document_can_be_updated_and_is_journaled(self):
        self.kb.update_metadata("roadmap-test", 1, {"notes": "corrected wording"}, UPLOADER, "wording")
        self.assertEqual(self.entry("roadmap-test")["status"], "uploaded")
        self.assertTrue(any(e.get("name") == "update_metadata" and e.get("changed_fields") == ["notes"]
                            for e in self.kb.journal.entries()))

    def test_crash_after_begin_completes_the_update(self):
        fsutil.crash_point = crash_at("begun")
        with self.assertRaises(SimulatedCrash):
            self.kb.update_metadata("intake-test", 1, {"notes": "x"}, UPLOADER, "test")
        fsutil.crash_point = lambda s: None
        self.kb.recover(ADMIN)
        self.assertEqual((self.entry("intake-test")["notes"], self.status("intake-test")), ("x", "uploaded"))


class TestHeadingLabels(unittest.TestCase):
    def test_labels_map_values_and_fall_back_to_the_raw_value(self):
        rec = {"topic": "application_fee", "faculty": "Faculty of Law"}
        self.assertEqual(heading_from(rec, ["topic"], {"application_fee": "Application fee"}),
                         "Section: Application fee")
        self.assertEqual(heading_from(rec, ["faculty", "topic"], {}), "Section: Faculty of Law > application_fee")

    def test_invalid_labels_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            path = write_dataset(Path(t) / "d.json", {"events": event_records(1)})
            spec = group_spec("events", ["activity"], "e")
            for bad in ({"x": ""}, {"x": 3}, ["x"]):
                entry = {"source_label": "L", "dataset": {"name": "d.json"},
                         "adapter_options": {"groups": [{**spec, "heading_labels": bad}]}}
                with self.assertRaises(ValidationFailed):
                    JsonRecordsAdapter().extract(entry, path)


if __name__ == "__main__":
    unittest.main()
