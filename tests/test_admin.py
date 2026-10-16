"""Admin features on an ISOLATED knowledge base (temporary folders; the live knowledge base is never touched):
authentication and roles, document upload (TXT/DOCX/PDF) through validation and the KB service, staging, approval,
publication, permission checks, duplicates, analytics and rule review notes.

Run from the project root: python -m unittest tests.test_admin -v
"""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from src import admin_service as admin
from src.auth import AuthError, User, UserStore, require
from src.kb.errors import DuplicateDocument
from tests.kb_helpers import World

OWNER = User("owner", "admin")
UPLOADER = User("clerk", "uploader")
PUBLISHER = User("registrar", "publisher")
REVIEWER = User("reviewer", "reviewer")
VIEWER = User("viewer", "viewer")
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def docx_bytes(paragraphs, rows=()):
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    if rows:
        body += "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in r)
                                    + "</w:tr>" for r in rows) + "</w:tbl>"
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.store = UserStore(Path(tempfile.mkdtemp()) / "users.json")

    def test_first_account_must_be_admin_and_later_accounts_need_an_admin(self):
        with self.assertRaises(AuthError):
            self.store.create("clerk", "long enough pass", "uploader")
        owner = self.store.create("owner", "long enough pass", "admin")
        with self.assertRaises(AuthError):
            self.store.create("clerk", "long enough pass", "uploader")
        self.store.create("clerk", "long enough pass", "uploader", by=owner)
        with self.assertRaises(AuthError):
            self.store.create("other", "long enough pass", "viewer", by=User("clerk", "uploader"))

    def test_passwords_are_hashed_and_checked(self):
        self.store.create("owner", "long enough pass", "admin")
        self.assertNotIn("long enough pass", self.store.path.read_text())
        self.assertEqual(self.store.authenticate("owner", "long enough pass"), User("owner", "admin"))
        with self.assertRaises(AuthError):
            self.store.authenticate("owner", "wrong password!")
        with self.assertRaises(AuthError):
            self.store.authenticate("nobody", "long enough pass")

    def test_lockout_after_repeated_failures(self):
        self.store.create("owner", "long enough pass", "admin")
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.store.authenticate("owner", "bad")
        with self.assertRaises(AuthError) as ctx:
            self.store.authenticate("owner", "long enough pass")
        self.assertIn("too many", str(ctx.exception))

    def test_role_permissions(self):
        self.assertTrue(VIEWER.can("view") and not VIEWER.can("review"))
        self.assertTrue(REVIEWER.can("review") and not REVIEWER.can("upload"))
        self.assertTrue(UPLOADER.can("upload") and not UPLOADER.can("publish"))
        self.assertTrue(PUBLISHER.can("publish") and not PUBLISHER.can("manage_users"))
        self.assertTrue(OWNER.can("manage_users"))
        with self.assertRaises(AuthError):
            require(None, "view")
        with self.assertRaises(AuthError):
            require(VIEWER, "publish")


class DocumentLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.world = World(self.tmp)
        self.kb = self.world.kb

    def upload(self, user, name, data, **kw):
        return admin.upload_document(user, self.kb, name, data, kw.pop("title", "Test Admissions Notice"),
                                     kw.pop("source_label", "MSU Test Notice"), scan=False, **kw)

    def test_txt_upload_is_validated_and_staged(self):
        text = ("ADMISSIONS NOTICE\n\nApplicants for the Diploma in Zyxtesting need five O Level passes including "
                "English.\n\nThe programme runs for two years.").encode()
        report = self.upload(UPLOADER, "notice.txt", text, stage=True)
        self.assertEqual(report["status"], "staged", report)
        doc = next(d for d in self.kb.status()["documents"] if d["doc_id"] == report["registered"]["doc_id"])
        self.assertEqual(doc["status"], "staged")
        self.assertGreaterEqual(doc["passages"], 1)
        self.assertIsNone(self.kb.status()["pointers"]["public"] and None)       # nothing published by staging

    def test_docx_upload_reads_paragraphs_and_tables(self):
        data = docx_bytes(["Entry requirements for the Diploma in Zyxdocx."], [("Programme", "Duration"),
                                                                                ("Diploma in Zyxdocx", "2 years")])
        report = self.upload(UPLOADER, "notice.docx", data, title="Docx Notice", source_label="MSU Docx Notice")
        self.assertEqual(report["status"], "validated", report)

    def test_invalid_files_are_rejected_before_registration(self):
        for name, data in (("bad.pdf", b"not a pdf"), ("bad.docx", b"not a zip"), ("x.exe", b"MZ"), ("e.txt", b"")):
            report = self.upload(UPLOADER, name, data)
            self.assertEqual(report["status"], "rejected", name)
        self.assertEqual(len(self.kb.status()["documents"]), len(World(Path(tempfile.mkdtemp())).kb.status()["documents"]))

    def test_duplicate_upload_is_refused(self):
        data = b"Admissions notice for the zyxdup programme.\n\nSecond paragraph about the zyxdup programme."
        self.upload(UPLOADER, "a.txt", data, title="First Title")
        with self.assertRaises(DuplicateDocument):
            self.upload(UPLOADER, "b.txt", data, title="Another Title")
        again = self.upload(UPLOADER, "a.txt", data, title="First Title")
        self.assertEqual(again["status"], "already registered")

    def test_permissions_are_enforced_server_side(self):
        data = b"Admissions notice for the zyxperm programme.\n\nMore text about zyxperm."
        for user in (VIEWER, REVIEWER):
            with self.assertRaises(AuthError):
                self.upload(user, "p.txt", data)
        report = self.upload(UPLOADER, "p.txt", data, stage=True)
        doc_id, v = report["registered"]["doc_id"], report["registered"]["doc_version"]
        with self.assertRaises(AuthError):
            admin.approve_document(UPLOADER, self.kb, doc_id, v, "basis")
        with self.assertRaises(AuthError):
            admin.publish(UPLOADER, self.kb)
        with self.assertRaises(ValueError):
            admin.approve_document(PUBLISHER, self.kb, doc_id, v, "  ")

    def test_approve_publish_and_rollback(self):
        before = self.kb.status()["pointers"]["public"]["version"]
        data = b"Admissions notice for the zyxpub programme.\n\nMore text about zyxpub entry."
        report = self.upload(UPLOADER, "pub.txt", data, stage=True)
        doc_id, v = report["registered"]["doc_id"], report["registered"]["doc_version"]
        admin.approve_document(PUBLISHER, self.kb, doc_id, v, "Approved for the isolated test.")
        result = admin.publish(PUBLISHER, self.kb)
        after = self.kb.status()["pointers"]["public"]["version"]
        self.assertNotEqual(before, after)
        self.assertEqual(next(d for d in self.kb.status()["documents"] if d["doc_id"] == doc_id)["status"], "published")
        admin.rollback(PUBLISHER, self.kb, before, "isolated test rollback")
        self.assertEqual(self.kb.status()["pointers"]["public"]["version"], before)
        self.assertTrue(admin.verify(VIEWER, self.kb))
        self.assertTrue(admin.document_history(REVIEWER, self.kb, doc_id)["versions"])
        self.assertTrue(result)


class RulesAndAnalyticsTests(unittest.TestCase):
    def test_rules_overview_and_review_notes_never_change_rules(self):
        import hashlib
        rules = Path(__file__).resolve().parents[1] / "src/eligibility/MSU_Eligibility_Rules.json"
        before = hashlib.sha256(rules.read_bytes()).hexdigest()
        notes = Path(tempfile.mkdtemp()) / "notes.jsonl"
        with patch.object(admin, "REVIEW_NOTES", notes):
            ov = admin.rules_overview(REVIEWER)
            self.assertEqual(ov["programmes"], 141)
            self.assertTrue(any(q["id"] == "MSU-JF2027-126" for q in ov["open_questions"]))
            self.assertEqual([c["id"] for c in ov["corrections"]], ["C1", "C2", "C3", "C4", "C5"])
            admin.record_review_note(REVIEWER, "MSU-JF2027-126", "question_sent_to_admissions", "Asked by e-mail.")
            self.assertEqual(admin.review_notes(REVIEWER)[0]["by"], "reviewer")
            with self.assertRaises(ValueError):
                admin.record_review_note(REVIEWER, "MSU-JF2027-126", "delete_rule", "")
            with self.assertRaises(AuthError):
                admin.rules_overview(VIEWER)
        self.assertEqual(hashlib.sha256(rules.read_bytes()).hexdigest(), before)

    def test_analytics_from_the_metadata_log(self):
        log = Path(tempfile.mkdtemp()) / "q.jsonl"
        rows = [{"timestamp": "2026-10-16T09:00:00+00:00", "route": "INFO", "router_reason": "model", "status": "answered",
                 "not_found": False, "latency_ms": 900},
                {"timestamp": "2026-10-16T09:01:00+00:00", "route": "INFO", "router_reason": "model", "status": "answered",
                 "not_found": True, "latency_ms": 700},
                {"timestamp": "2026-10-16T09:02:00+00:00", "route": "ELIGIBILITY", "router_reason": "results_in_message",
                 "status": "answered", "results_method": "parsed", "latency_ms": 40}]
        log.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
        a = admin.analytics(VIEWER, log)
        self.assertEqual((a["questions"], a["documents_not_found"], a["documents_answered"]), (3, 1, 1))
        self.assertEqual(a["by_route"], {"INFO": 2, "ELIGIBILITY": 1})
        self.assertEqual(a["results_read_by"], {"parsed": 1})
        with self.assertRaises(AuthError):
            admin.analytics(None, log)


if __name__ == "__main__":
    unittest.main()
