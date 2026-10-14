"""Knowledge base: adapters, validation and the embedding cache (synthetic data, hash embedder)."""
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.heading_store import index_text
from src.kb import fsutil
from src.kb.adapters import JsonRecordsAdapter, PdfProseAdapter, body_of, get_adapter
from src.kb.embeddings import EmbeddingCache
from src.kb.errors import IntegrityError, ValidationFailed
from src.kb.validate import validate_units
from tests.kb_helpers import (MODEL, HashEmbedder, event_records, group_spec, make_pdf, programme_records,
                              write_dataset)
from src.kb.config import EMBEDDING_REVISION

WORDS = lambda t: len(t.split())


def entry(groups, label="MSU Test", source_sha=None, name="source.pdf", **extra):
    return {"doc_id": "doc-test", "doc_version": 1, "source_label": label,
            "adapter_options": {"groups": groups, **({"source_sha256_field": "source_sha256"} if source_sha else {})},
            "dataset": {"name": "data.json"}, "source_file": {"name": name, "sha256": source_sha}, **extra}


class SimulatedCrash(BaseException):
    pass


class TestJsonRecordsAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_units_follow_group_order_with_header_and_heading(self):
        path = write_dataset(self.dir / "d.json", {"programmes": programme_records(2), "events": event_records(2)})
        e = entry([group_spec("events", ["calendar_group", "semester", "activity"], "roadmap_event"),
                   group_spec("programmes", ["faculty", "programme"], "programme")])
        units, problems = JsonRecordsAdapter().extract(e, path)
        self.assertEqual(problems, [])
        self.assertEqual([u["record_id"] for u in units], ["RM-01", "RM-02", "PR-001", "PR-002"])
        u = units[0]
        self.assertEqual(u["text"], "[MSU Test, p. 1]\nACTIVITY: roadmap activity 1 runs in week 1.")
        self.assertEqual(u["heading"], "Section: Main > First Semester > Activity 1")
        self.assertEqual((u["file_name"], u["source"], u["unit_type"]), ("source.pdf", "MSU Test", "roadmap_event"))
        self.assertEqual(body_of(u["text"]), "ACTIVITY: roadmap activity 1 runs in week 1.")

    def test_only_selected_groups_are_indexed(self):
        path = write_dataset(self.dir / "d.json", {"events": event_records(3), "semester_summaries": event_records(2)})
        units, _ = JsonRecordsAdapter().extract(entry([group_spec("events", [], "roadmap_event")]), path)
        self.assertEqual(len(units), 3)

    def test_provenance_and_field_problems(self):
        recs = event_records(3)
        recs[1]["source_page"] = 0
        recs[2]["rag_text"] = "  "
        path = write_dataset(self.dir / "d.json", {"events": recs}, source_sha="aaa")
        units, problems = JsonRecordsAdapter().extract(entry([group_spec("events", [], "e")], source_sha="bbb"), path)
        self.assertEqual(len(units), 1)          # extracted, but its provenance error blocks validation
        self.assertTrue(any("does not match the registered source file" in p for p in problems))
        self.assertTrue(any("positive integer" in p for p in problems))
        self.assertTrue(any("empty text" in p for p in problems))

    def test_bad_options(self):
        path = write_dataset(self.dir / "d.json", {"events": event_records(1)})
        with self.assertRaises(ValidationFailed):
            JsonRecordsAdapter().extract(entry({}), path)
        with self.assertRaises(ValidationFailed):
            JsonRecordsAdapter().extract(entry([{"name": "events"}]), path)
        with self.assertRaises(ValidationFailed):
            get_adapter("docx_magic")


class TestPdfProseAdapter(unittest.TestCase):
    def test_pages_become_cited_chunks_and_duplicates_are_skipped(self):
        with tempfile.TemporaryDirectory() as t:
            import pymupdf
            pdf = Path(t) / "prose.pdf"
            doc = pymupdf.open()
            for text in ("Regulation one applies to all students in the faculty.",
                         "Regulation one applies to all students in the faculty.",   # duplicate page
                         "Short"):                                                   # below min_page_chars
                doc.new_page().insert_text((72, 72), text)
            doc.save(str(pdf))
            doc.close()
            units, problems = PdfProseAdapter().extract({"source_label": "MSU Rules", "dataset": {"name": "prose.pdf"}},
                                                        pdf)
            self.assertEqual(problems, [])
            self.assertEqual([u["record_id"] for u in units], ["p0001-c00"])
            self.assertTrue(units[0]["text"].startswith("[MSU Rules, p. 1]\nRegulation one"))


class TestValidation(unittest.TestCase):
    def units(self, n=3):
        return [{"record_id": f"R{i}", "unit_type": "t", "source": "MSU Test", "file_name": "f.pdf", "page": 1,
                 "heading": "Section: X", "text": f"[MSU Test, p. 1]\nUnique passage number {i}."} for i in range(n)]

    def test_clean_document_passes(self):
        report = validate_units(self.units(), entry={"source_label": "MSU Test"}, token_counter=WORDS, page_count=1)
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["stats"]["passages"], 3)

    def test_errors(self):
        u = self.units(4)
        u[1]["record_id"] = "R0"                                 # duplicate id
        u[2]["page"] = 9                                         # out of range
        u[3]["text"] = "[MSU Test, p. 1]\n" + "word " * 600      # too long
        report = validate_units(u, entry={"source_label": "MSU Test",
                                          "correction_history": [{"event_id": "R99"}]},
                                token_counter=WORDS, page_count=2, adapter_problems=["adapter said no"])
        self.assertFalse(report["ok"])
        joined = " | ".join(report["errors"])
        for needle in ("duplicate record_id R0", "outside 1..2", "tokens > 512", "R99", "adapter said no"):
            self.assertIn(needle, joined)

    def test_warnings_for_codes_and_duplicates(self):
        u = self.units(3)
        u[1]["text"] = "[MSU Test, p. 1]\nRequires ZQX 101."
        u[2]["text"] = u[0]["text"].replace("p. 1", "p. 2")      # same body, different header
        from src.kb.validate import text_key
        report = validate_units(u, entry={"source_label": "MSU Test"}, token_counter=WORDS,
                                existing_text_keys={text_key(u[1]["text"])})
        self.assertTrue(report["ok"])
        joined = " | ".join(report["warnings"])
        self.assertIn("zqx101", joined)
        self.assertIn("same text as R0", joined)
        self.assertIn("already in the store", joined)

    def test_empty_document(self):
        self.assertFalse(validate_units([], entry={"source_label": "x"}, token_counter=WORDS)["ok"])


class TestEmbeddingCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = EmbeddingCache(Path(self.tmp.name), MODEL, EMBEDDING_REVISION, "recipe")
        self.texts = [f"passage {i} about topic {i % 3}" for i in range(10)]

    def tearDown(self):
        fsutil.crash_point = lambda step: None
        self.tmp.cleanup()

    def test_embeds_once_and_returns_cached_vectors(self):
        HashEmbedder.calls = 0
        self.assertEqual(self.cache.ensure(self.texts, HashEmbedder, batch_size=4), 10)
        self.assertEqual(self.cache.ensure(self.texts, HashEmbedder, batch_size=4), 0)
        self.assertEqual(HashEmbedder.calls, 10)
        fresh = EmbeddingCache(Path(self.tmp.name), MODEL, EMBEDDING_REVISION, "recipe")   # reload from disk
        np.testing.assert_array_equal(fresh.vectors_for(self.texts), HashEmbedder().encode(self.texts))

    def test_interrupted_embedding_resumes(self):
        HashEmbedder.calls = 0
        batches = []

        def crash(step):
            if step == "embedding_batch_written":
                batches.append(step)
                if len(batches) == 2:
                    raise SimulatedCrash()
        fsutil.crash_point = crash
        with self.assertRaises(SimulatedCrash):
            self.cache.ensure(self.texts, HashEmbedder, batch_size=4)
        fsutil.crash_point = lambda step: None
        resumed = EmbeddingCache(Path(self.tmp.name), MODEL, EMBEDDING_REVISION, "recipe")
        self.assertEqual(resumed.ensure(self.texts, HashEmbedder, batch_size=4), 2)    # only the unfinished rest
        self.assertEqual(HashEmbedder.calls, 10)                                   # 8 before the crash + 2
        self.assertEqual(resumed.vectors_for(self.texts).shape, (10, 64))

    def test_wrong_model_and_missing_vectors(self):
        class OtherModel(HashEmbedder):
            revision = "something-else"
        with self.assertRaises(IntegrityError):
            self.cache.ensure(self.texts, OtherModel)
        with self.assertRaises(IntegrityError):
            self.cache.vectors_for(["never embedded"])

    def test_cache_dirs_are_separated_by_model_and_recipe(self):
        other = EmbeddingCache(Path(self.tmp.name), MODEL, EMBEDDING_REVISION, "another recipe")
        self.assertNotEqual(self.cache.dir, other.dir)


if __name__ == "__main__":
    unittest.main()
