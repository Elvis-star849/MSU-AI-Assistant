"""Knowledge base: the service workflow, public/staging separation, permissions, idempotency, stable identifiers,
rollback, retention, determinism and retrieval (synthetic data, hash embedder, fake reranker)."""
import json
import tempfile
import unittest
from pathlib import Path

from src.kb.config import Actor
from src.kb.errors import DuplicateDocument, InvalidTransition, KBError, PermissionDenied, ValidationFailed
from src.kb.fsutil import sha256_file
from src.kb.retriever import PublicRetriever, StagingRetriever
from src.kb.versions import read_pointer
from tests.kb_helpers import (ADMIN, APPROVER, UPLOADER, VISITOR, FakeReranker, HashEmbedder, QueryEmbedder, World,
                              event_records, open_store, write_dataset)


class WorldCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = World(Path(self.tmp.name))
        self.kb = self.w.kb

    def tearDown(self):
        self.tmp.cleanup()

    def doc(self, doc_id, version=1):
        return next(d for d in self.kb.registry.load()["documents"]
                    if d["doc_id"] == doc_id and d["doc_version"] == version)


class TestWorkflow(WorldCase):
    def test_states_through_the_workflow(self):
        self.w.register_both()
        self.assertEqual(self.doc("roadmap-test")["status"], "uploaded")
        report = self.kb.validate("roadmap-test", 1, UPLOADER)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(self.doc("roadmap-test")["status"], "validated")
        self.assertEqual(self.doc("roadmap-test")["units"]["count"], 3)
        self.kb.stage("roadmap-test", 1, UPLOADER)
        self.assertEqual(self.doc("roadmap-test")["status"], "staged")
        with self.assertRaises(InvalidTransition):
            self.kb.approve("intake-test", 1, APPROVER, basis="x")        # intake is only uploaded
        self.kb.approve("roadmap-test", 1, APPROVER, basis="ok")
        self.kb.publish(APPROVER)
        self.assertEqual(self.doc("roadmap-test")["status"], "published")
        self.assertEqual(self.doc("roadmap-test")["publish_seq"], 1)

    def test_validation_errors_keep_the_document_uploaded(self):
        bad = write_dataset(self.w.tmp / "bad.json", {"events": event_records(2)}, source_sha="not-the-pdf")
        meta = {**self.w.road_meta, "doc_id": "bad-doc"}
        self.kb.register_upload(bad, meta, UPLOADER, source_file=self.w.road_pdf)
        report = self.kb.validate("bad-doc", 1, UPLOADER)
        self.assertFalse(report["ok"])
        self.assertEqual(self.doc("bad-doc")["status"], "uploaded")
        self.assertIsNone(self.doc("bad-doc")["units"])
        with self.assertRaises(InvalidTransition):
            self.kb.stage("bad-doc", 1, UPLOADER)

    def test_metadata_is_checked(self):
        with self.assertRaises(ValidationFailed):
            self.kb.register_upload(self.w.road_json, {"doc_id": "x-doc"}, UPLOADER)
        with self.assertRaises(ValidationFailed):
            self.kb.register_upload(self.w.road_json, {**self.w.road_meta, "colour": "red"}, UPLOADER)


class TestPublicStagingSeparation(WorldCase):
    def setUp(self):
        super().setUp()
        self.w.publish_roadmap_only()
        self.public, self.staging = open_store(self.kb, "public"), open_store(self.kb, "staging")

    def test_versions_contain_the_right_documents(self):
        pub = [(d["doc_id"], d["status"]) for d in self.public.kb["documents"]]
        stg = [(d["doc_id"], d["status"]) for d in self.staging.kb["documents"]]
        self.assertEqual(pub, [("yearbook-humanities", "published"), ("yearbook-sciences-v2", "published"),
                               ("roadmap-test", "published")])
        self.assertEqual(stg, pub + [("intake-test", "staged")])
        self.assertEqual((len(self.public.records), len(self.staging.records)), (7 + 3, 7 + 3 + 5))

    def test_staged_text_is_absent_from_public_faiss_bm25_and_code_map(self):
        self.assertFalse(any(p["doc_id"] == "intake-test" for p in self.public.passages))
        self.assertFalse(any("zyxintake" in r["text"] for r in self.public.records))
        hits = self.public.vector_search("zyxintake programme ZQX 101", len(self.public.records))
        self.assertFalse(any(r["passage_uid"].startswith("intake-test/") for r in hits))
        self.assertEqual(self.public.bm25_search("zyxintake", 20), [])
        self.assertIsNone(self.public.chunks_with_codes("ZQX 101"))
        self.assertTrue(self.staging.bm25_search("zyxintake", 20))
        self.assertTrue(self.staging.chunks_with_codes("ZQX 101"))

    def test_bm25_statistics_are_separate(self):
        self.assertNotEqual(self.public.kb["bm25_corpus_fingerprint"], self.staging.kb["bm25_corpus_fingerprint"])
        self.assertNotEqual(self.public.bm25.corpus_size, self.staging.bm25.corpus_size)
        a = self.public.bm25_search("roadmap activity", 1)[0]["score"]
        b = self.staging.bm25_search("roadmap activity", 1)[0]["score"]
        self.assertNotAlmostEqual(a, b)                        # same passage, different corpus statistics

    def test_base_block_identical_in_both(self):
        frozen = (self.w.frozen / "chunks.jsonl").read_bytes()
        for kind in ("public", "staging"):
            v = self.kb.cfg.versions_dir / read_pointer(self.kb.cfg, kind)["version"]
            self.assertTrue((v / "chunks.jsonl").read_bytes().startswith(frozen))

    def test_retrievers(self):
        rr = FakeReranker()
        public = PublicRetriever.open(self.kb.cfg, reranker=rr)
        public.store._embedder = QueryEmbedder()
        evidence = public.retrieve("roadmap activity 2 week")
        self.assertEqual(len(evidence), 5)
        self.assertEqual(rr.calls[0][1:], (10, True))             # accepted pool 10, reranker sees the heading
        self.assertTrue(all("passage_uid" in e for e in evidence))
        self.assertEqual(evidence[0]["configuration"], "kb_public")
        self.assertFalse(any(e["passage_uid"].startswith("intake-test/") for e in public.retrieve("zyxintake fee")))
        code = public.retrieve("What is HAWS 433?")
        self.assertEqual(code[0]["route"], "code_hybrid")

        for who in (None, VISITOR, UPLOADER):
            with self.assertRaises(PermissionDenied):
                StagingRetriever.open(self.kb.cfg, who, reranker=rr)
        staging = StagingRetriever.open(self.kb.cfg, APPROVER, reranker=rr)
        staging.store._embedder = QueryEmbedder()
        self.assertTrue(any(e["passage_uid"].startswith("intake-test/") for e in staging.retrieve("zyxintake fee")))


class TestPermissionsAndTwoPersonRule(WorldCase):
    def test_roles(self):
        with self.assertRaises(PermissionDenied):
            self.kb.register_upload(self.w.road_json, self.w.road_meta, VISITOR)
        self.w.stage_both()
        for call in (lambda: self.kb.approve("roadmap-test", 1, UPLOADER, basis="b"),
                     lambda: self.kb.publish(UPLOADER),
                     lambda: self.kb.reject("intake-test", 1, UPLOADER, "r"),
                     lambda: self.kb.rollback("0001", UPLOADER, "r"),
                     lambda: self.kb.unlock(APPROVER),
                     lambda: self.kb.seed_base(self.w.frozen, [], APPROVER)):
            with self.assertRaises(PermissionDenied):
                call()

    def test_two_person_rule_when_enabled(self):
        self.w.stage_both()
        self.kb.cfg.two_person_rule = True
        both = Actor("uploader", {"kb_uploader", "kb_approver"})       # same person as the uploader
        with self.assertRaises(PermissionDenied):
            self.kb.approve("roadmap-test", 1, both, basis="self approval")
        self.kb.approve("roadmap-test", 1, APPROVER, basis="independent approval")
        self.assertTrue(self.doc("roadmap-test")["approvals"][0]["two_person_rule"])

    def test_two_person_rule_off_in_development(self):
        self.w.stage_both()
        self.assertFalse(self.kb.cfg.two_person_rule)
        self.kb.approve("roadmap-test", 1, Actor("uploader", {"kb_approver"}), basis="prototype")

    def test_approval_needs_a_basis(self):
        self.w.stage_both()
        with self.assertRaises(ValidationFailed):
            self.kb.approve("roadmap-test", 1, APPROVER, basis="  ")


class TestApprovalHistory(WorldCase):
    def test_roadmap_style_approval_is_recorded_exactly(self):
        self.w.publish_roadmap_only()
        entry = self.doc("roadmap-test")
        approval = entry["approvals"][0]
        self.assertEqual(approval["decision_date"], "2026-10-13")
        self.assertEqual(approval["basis"], "Owner confirmed the corrected road map.")
        self.assertEqual(approval["registry_verification"], "not performed")
        self.assertNotEqual(approval["recorded_at"], approval["decision_date"])
        self.assertEqual(entry["source_file"]["name"], "ROADMAP DRAFT.pdf")             # original filename kept
        self.assertEqual(entry["source_file"]["sha256"], sha256_file(self.w.road_pdf))
        self.assertEqual(entry["correction_history"][0]["dates_in_source"], "13/09/2026")
        self.assertEqual(entry["excluded_units"]["semester_summaries"]["count"], 4)
        self.assertEqual([h["to"] for h in entry["history"]],
                         ["uploaded", "validated", "staged", "approved", "published"])
        snapshot = open_store(self.kb, "public").snapshot
        self.assertEqual(next(d for d in snapshot["documents"] if d["doc_id"] == "roadmap-test")["approvals"],
                         entry["approvals"])                                          # published with the version
        history = self.kb.history("roadmap-test")
        self.assertEqual(history["versions"][0]["approvals"][0]["decision_date"], "2026-10-13")
        self.assertTrue(any(e.get("name") == "approve" for e in history["journal"]))


class TestPriorApproval(WorldCase):
    def test_prior_approval_is_recorded_as_evidence_not_as_a_status(self):
        prior = {"actor": "project-owner", "decision": "approved", "decision_date": "2026-10-13",
                 "basis": "Owner confirmed the corrected road map.", "registry_verification": "not performed"}
        self.kb.register_upload(self.w.road_json, {**self.w.road_meta, "prior_approval": prior}, UPLOADER,
                                source_file=self.w.road_pdf)
        entry = self.doc("roadmap-test")
        self.assertEqual(entry["prior_approval"], prior)
        self.assertEqual(entry["status"], "uploaded")                 # the state machine is not bypassed
        self.assertEqual(entry["approvals"], [])

    def test_incomplete_prior_approval_is_rejected(self):
        with self.assertRaises(ValidationFailed):
            self.kb.register_upload(self.w.road_json, {**self.w.road_meta, "prior_approval": {"actor": "x"}},
                                    UPLOADER)


class TestIdempotencyAndDuplicates(WorldCase):
    def test_reupload_validate_publish_are_no_ops(self):
        self.w.register_both()
        again = self.kb.register_upload(self.w.road_json, self.w.road_meta, UPLOADER, source_file=self.w.road_pdf)
        self.assertTrue(again["no_op"])
        self.kb.validate("roadmap-test", 1, UPLOADER)
        self.assertTrue(self.kb.validate("roadmap-test", 1, UPLOADER)["no_op"])
        self.kb.stage("roadmap-test", 1, UPLOADER)
        self.kb.approve("roadmap-test", 1, APPROVER, basis="ok")
        first = self.kb.publish(APPROVER)
        second = self.kb.publish(APPROVER)
        self.assertTrue(second["no_op"])
        self.assertEqual(second["version"], first["version"])
        self.assertTrue(self.kb.refresh_staging(APPROVER)["no_op"])

    def test_same_file_under_another_id_is_rejected(self):
        self.kb.register_upload(self.w.road_json, self.w.road_meta, UPLOADER)
        with self.assertRaises(DuplicateDocument):
            self.kb.register_upload(self.w.road_json, {**self.w.road_meta, "doc_id": "roadmap-copy"}, UPLOADER)

    def test_changed_content_becomes_a_new_document_version(self):
        self.kb.register_upload(self.w.road_json, self.w.road_meta, UPLOADER)
        changed = write_dataset(self.w.tmp / "roadmap2.json", {"events": event_records(4)},
                                sha256_file(self.w.road_pdf))
        result = self.kb.register_upload(changed, self.w.road_meta, UPLOADER)
        self.assertEqual(result["doc_version"], 2)

    def test_base_documents_cannot_be_replaced(self):
        with self.assertRaises(DuplicateDocument):
            self.kb.register_upload(self.w.road_json, {**self.w.road_meta, "doc_id": "yearbook-humanities"}, UPLOADER)
        with self.assertRaises(InvalidTransition):
            self.kb.withdraw("yearbook-humanities", 1, APPROVER, "no")

    def test_staging_reports_near_duplicates(self):
        self.w.stage_both()
        report = json.loads((self.kb.cfg.root / self.doc("intake-test")["staging_report"]).read_text())
        self.assertIn("near_duplicates", report)


class TestStableIdentifiersAndLifecycle(WorldCase):
    def test_uids_survive_position_changes(self):
        self.w.stage_both()
        self.kb.approve("roadmap-test", 1, APPROVER, basis="ok")
        self.kb.approve("intake-test", 1, APPROVER, basis="ok")
        self.kb.publish(APPROVER)
        before = open_store(self.kb, "public")
        uid = "intake-test/v1/PR-002"
        row_before = before.row_of(uid)
        text = before.records[row_before]["text"]
        self.kb.withdraw("roadmap-test", 1, APPROVER, "superseded by a later road map")
        after = open_store(self.kb, "public")
        self.assertFalse(any(p["doc_id"] == "roadmap-test" for p in after.passages))
        row_after = after.row_of(uid)
        self.assertEqual(row_after, row_before - 3)                     # internal position moved
        self.assertEqual(after.records[row_after]["text"], text)        # same passage, same external id
        doc = next(d for d in after.kb["documents"] if d["doc_id"] == "intake-test")
        old = next(d for d in before.kb["documents"] if d["doc_id"] == "intake-test")
        self.assertEqual(doc["content_fingerprint"], old["content_fingerprint"])
        self.assertEqual(doc["vectors_checksum"], old["vectors_checksum"])

    def test_supersede_publishes_new_and_retires_old(self):
        self.w.publish_roadmap_only()
        changed = write_dataset(self.w.tmp / "roadmap2.json", {"events": event_records(4, word="revised")},
                                sha256_file(self.w.road_pdf))
        self.kb.register_upload(changed, self.w.road_meta, UPLOADER, source_file=self.w.road_pdf)
        self.kb.validate("roadmap-test", 2, UPLOADER)
        self.kb.stage("roadmap-test", 2, UPLOADER)
        self.kb.approve("roadmap-test", 2, APPROVER, basis="revised road map")
        self.kb.supersede(("roadmap-test", 1), ("roadmap-test", 2), APPROVER, "revision")
        public = open_store(self.kb, "public")
        docs = [(d["doc_id"], d["doc_version"]) for d in public.kb["documents"] if not d["base"]]
        self.assertEqual(docs, [("roadmap-test", 2)])
        self.assertEqual(self.doc("roadmap-test", 1)["status"], "superseded")
        self.assertEqual(self.doc("roadmap-test", 2)["supersedes"], {"doc_id": "roadmap-test", "doc_version": 1})

    def test_rejecting_a_staged_document_removes_it_from_staging(self):
        self.w.stage_both()
        self.kb.reject("intake-test", 1, APPROVER, "not approved")
        staging = open_store(self.kb, "staging")
        self.assertFalse(any(p["doc_id"] == "intake-test" for p in staging.passages))


class TestRollbackRetentionDeterminism(WorldCase):
    def test_rollback_to_the_base_suspends_published_documents(self):
        """(Detailed rollback, reinstatement and reconciliation tests are in test_kb_rollback.py.)"""
        self.w.publish_roadmap_only()
        published = read_pointer(self.kb.cfg, "public")["version"]
        result = self.kb.rollback("0001", APPROVER, "emergency")
        self.assertEqual((result["version"], result["previous"]), ("0001", published))
        self.assertEqual(result["status_changes"], [["roadmap-test", 1, "published", "suspended"]])
        self.assertEqual(len(open_store(self.kb, "public").records), 7)
        report = self.kb.verify()
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["warnings"], [])
        with self.assertRaises(KBError):
            self.kb.rollback(read_pointer(self.kb.cfg, "staging")["version"], APPROVER, "staging is not public")

    def test_retention_keeps_base_and_newest_public_versions(self):
        self.kb.cfg.retention_public = 2
        self.w.stage_both()
        self.kb.approve("roadmap-test", 1, APPROVER, basis="ok")
        self.kb.publish(APPROVER)
        self.kb.approve("intake-test", 1, APPROVER, basis="ok")
        self.kb.publish(APPROVER)
        self.kb.withdraw("intake-test", 1, APPROVER, "test")
        self.kb.withdraw("roadmap-test", 1, APPROVER, "test")
        kept = sorted(p.name for p in self.kb.cfg.versions_dir.iterdir() if p.name.isdigit())
        archived = sorted(p.name for p in self.kb.cfg.archive_dir.iterdir())
        publics = [v for v in kept if json.loads((self.kb.cfg.versions_dir / v / "manifest.json").read_text())
                   ["kb"]["kind"] == "public"]
        self.assertIn("0001", kept)                                     # frozen base never archived
        self.assertLessEqual(len([v for v in publics if v != "0001"]), 2)
        self.assertIn(read_pointer(self.kb.cfg, "public")["version"], kept)
        self.assertIn(read_pointer(self.kb.cfg, "staging")["version"], kept)
        self.assertTrue(archived)                                       # moved, not deleted
        self.assertTrue(self.kb.verify()["ok"])

    def test_identical_inputs_build_identical_versions(self):
        self.w.publish_roadmap_only()
        other = World(Path(self.tmp.name) / "second")
        other.publish_roadmap_only()
        for kind in ("public", "staging"):
            a = self.kb.cfg.versions_dir / read_pointer(self.kb.cfg, kind)["version"]
            b = other.kb.cfg.versions_dir / read_pointer(other.kb.cfg, kind)["version"]
            for name in ("chunks.jsonl", "passages.jsonl", "index.faiss"):
                self.assertEqual(sha256_file(a / name), sha256_file(b / name), (kind, name))
            ma, mb = (json.loads((x / "manifest.json").read_text()) for x in (a, b))
            for key in ("corpus_fingerprint", "vectors_checksum", "heading_fingerprint"):
                self.assertEqual(ma[key], mb[key])
            for key in ("documents", "base", "bm25_corpus_fingerprint", "passages_sha256"):
                self.assertEqual(ma["kb"][key], mb["kb"][key])


if __name__ == "__main__":
    unittest.main()
