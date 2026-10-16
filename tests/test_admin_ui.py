"""The Programme explorer and Admin pages, headless (AppTest), on an isolated knowledge base and account file.

Run from the project root: python -m unittest tests.test_admin_ui -v
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.auth import UserStore
from tests.kb_helpers import World

ROOT = Path(__file__).resolve().parents[1]


class ExplorerPageTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.at = AppTest.from_file(str(ROOT / "ui/programme_explorer.py"), default_timeout=60)
        self.at.run()

    def test_search_and_filters(self):
        self.assertFalse(self.at.exception)
        self.assertIn("programme(s)", " ".join(m.value for m in self.at.markdown))
        self.at.text_input(key="px-text").set_value("Human Resource Management").run()
        labels = [e.label for e in self.at.expander]
        self.assertTrue(any("Human Resource Management" in l for l in labels))
        self.at.selectbox(key="px-level").set_value("Undergraduate").run()
        exp = next(e for e in self.at.expander if "Human Resource Management" in e.label)
        self.assertIn("Route 2", " ".join(m.value for m in exp.markdown))
        self.at.selectbox(key="px-campus").set_value("Zvishavane").run()
        self.assertFalse(self.at.exception)


class AdminPageTests(unittest.TestCase):
    def setUp(self):
        from streamlit.testing.v1 import AppTest
        self.tmp = Path(tempfile.mkdtemp())
        self.world = World(self.tmp)
        env = patch.dict(os.environ, {"MSU_ADMIN_USERS": str(self.tmp / "users.json"),
                                      "MSU_KB_ROOT": str(self.tmp / "kb"), "MSU_QUESTION_LOG": str(self.tmp / "q.jsonl")})
        env.start()
        self.addCleanup(env.stop)
        self.at = AppTest.from_file(str(ROOT / "ui/admin.py"), default_timeout=60)

    def test_first_run_setup_then_sign_out_and_sign_in(self):
        self.at.run()
        self.assertIn("First-run setup", [s.value for s in self.at.subheader])
        self.at.text_input[0].set_value("owner")
        self.at.text_input[1].set_value("correct horse battery")
        self.at.text_input[2].set_value("correct horse battery")
        self.at.button[0].click().run()
        self.assertFalse(self.at.exception)
        self.assertIn("Signed in as **owner** (admin)", " ".join(c.value for c in self.at.caption))
        self.assertEqual([t.label for t in self.at.tabs][:5], ["Overview", "Documents", "Rules review", "Analytics",
                                                               "Accounts"])
        next(b for b in self.at.button if b.label == "Sign out").click().run()
        self.assertEqual(self.at.text_input[0].label, "User name")

    def test_wrong_password_and_role_limited_tabs(self):
        store = UserStore(self.tmp / "users.json")
        owner = store.create("owner", "correct horse battery", "admin")
        store.create("viewer1", "another long pass", "viewer", by=owner)
        self.at.run()
        self.at.text_input[0].set_value("viewer1")
        self.at.text_input[1].set_value("wrong password")
        self.at.button[0].click().run()
        self.assertTrue(any("wrong password" in e.value for e in self.at.error))
        self.at.text_input[0].set_value("viewer1")
        self.at.text_input[1].set_value("another long pass")
        self.at.button[0].click().run()
        self.assertFalse(self.at.exception)
        labels = [t.label for t in self.at.tabs]
        self.assertIn("Overview", labels)
        self.assertNotIn("Rules review", labels)
        self.assertNotIn("Accounts", labels)
        self.assertFalse([b for b in self.at.button if b.label in ("Publish", "Approve", "Upload and validate")])


if __name__ == "__main__":
    unittest.main()
