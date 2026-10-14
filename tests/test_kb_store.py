"""Knowledge base: frozen-base preservation, version verification and tamper detection, inactive-row filtering."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from src.heading_store import HeadingAwareStore
from src.kb.errors import IntegrityError
from src.kb.fsutil import sha256_file
from src.kb.store import KBStore
from src.kb.versions import open_pointer, read_pointer
from tests.kb_helpers import ADMIN, BASE_DOCS, QueryEmbedder, World, make_frozen_store, make_kb, open_store


class TestFrozenBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.frozen = make_frozen_store(self.root / "frozen_v2")
        self.frozen_hashes = {p.name: sha256_file(p) for p in self.frozen.iterdir()}
        self.kb = make_kb(self.root / "kb")
        self.result = self.kb.seed_base(self.frozen, BASE_DOCS, ADMIN)

    def tearDown(self):
        self.tmp.cleanup()

    def test_seed_copies_records_and_index_byte_for_byte(self):
        v = self.kb.cfg.versions_dir / self.result["version"]
        self.assertEqual(self.result["version"], "0001")
        self.assertEqual((v / "chunks.jsonl").read_bytes(), (self.frozen / "chunks.jsonl").read_bytes())
        self.assertEqual((v / "index.faiss").read_bytes(), (self.frozen / "index.faiss").read_bytes())
        self.assertIn(b"\r\n", (v / "chunks.jsonl").read_bytes())           # CRLF endings preserved

    def test_seed_reproduces_frozen_fingerprints_and_does_not_touch_the_frozen_store(self):
        frozen_manifest = json.loads((self.frozen / "manifest.json").read_text())
        store = open_pointer(self.kb.cfg, "public")
        base = store.kb["base"]
        self.assertEqual(base["corpus_fingerprint"], frozen_manifest["corpus_fingerprint"])
        self.assertEqual(base["heading_fingerprint"], frozen_manifest["heading_fingerprint"])
        self.assertEqual(base["vectors_checksum"], frozen_manifest["vectors_checksum"])
        self.assertEqual(base["chunks_sha256"], sha256_file(self.frozen / "chunks.jsonl"))
        self.assertEqual({p.name: sha256_file(p) for p in self.frozen.iterdir()}, self.frozen_hashes)

    def test_identifiers_live_in_a_separate_mapping(self):
        store = open_pointer(self.kb.cfg, "public")
        self.assertEqual(set(store.records[0]), {"chunk_id", "source", "file_name", "page", "text", "heading"})
        self.assertEqual(store.passages[0]["passage_uid"], "yearbook-humanities/v1/c00000")
        self.assertEqual(store.passages[4]["passage_uid"], "yearbook-sciences-v2/v1/c00004")
        ranges = [(d["doc_id"], d["chunk_range"]) for d in store.kb["documents"]]
        self.assertEqual(ranges, [("yearbook-humanities", [0, 3]), ("yearbook-sciences-v2", [4, 6])])

    def test_seed_is_idempotent_and_checks_expected_fingerprint(self):
        self.assertTrue(self.kb.seed_base(self.frozen, BASE_DOCS, ADMIN)["no_op"])
        other = make_kb(self.root / "kb2")
        with self.assertRaises(IntegrityError):
            other.seed_base(self.frozen, BASE_DOCS, ADMIN, expected_fingerprint="sha256:not-the-frozen-one")

    def test_base_ranges_must_cover_every_frozen_row(self):
        other = make_kb(self.root / "kb3")
        with self.assertRaises(IntegrityError):
            other.seed_base(self.frozen, BASE_DOCS[:1], ADMIN)


class TestTamperDetection(unittest.TestCase):
    """Every file of a version is bound to the manifest, and the manifest to the pointer."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.world = World(Path(self.tmp.name))
        self.world.publish_roadmap_only()
        self.vdir = self.world.kb.cfg.versions_dir / read_pointer(self.world.kb.cfg, "public")["version"]

    def tearDown(self):
        self.tmp.cleanup()

    def tamper(self, name, old, new):
        path = self.vdir / name
        data = path.read_bytes()
        self.assertIn(old, data)
        path.write_bytes(data.replace(old, new, 1))

    def assert_rejected(self):
        with self.assertRaises(IntegrityError):
            open_pointer(self.world.kb.cfg, "public")

    def test_base_record_change(self):
        self.tamper("chunks.jsonl", b"chaired by the chairman", b"chaired by the Chancellor")
        self.assert_rejected()

    def test_new_record_change(self):
        self.tamper("chunks.jsonl", b"roadmap activity 2", b"roadmap activity 9")
        self.assert_rejected()

    def test_identifier_mapping_change(self):
        self.tamper("passages.jsonl", b"roadmap-test/v1/RM-01", b"roadmap-test/v1/RM-77")
        self.assert_rejected()

    def test_registry_snapshot_change(self):
        self.tamper("registry_snapshot.json", b"Owner confirmed", b"Someone claimed")
        self.assert_rejected()

    def test_manifest_change_breaks_the_pointer(self):
        manifest = json.loads((self.vdir / "manifest.json").read_text(encoding="utf-8"))
        manifest["kb"]["inactive_chunk_ids"] = [0]
        (self.vdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assert_rejected()

    def test_status_not_allowed_for_kind(self):
        manifest_path = self.vdir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["kb"]["documents"][-1]["status"] = "staged"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaises(IntegrityError):
            KBStore(self.vdir).load(expected_kind="public")            # even without the pointer check

    def test_wrong_kind(self):
        staging = self.world.kb.cfg.versions_dir / read_pointer(self.world.kb.cfg, "staging")["version"]
        with self.assertRaises(IntegrityError):
            KBStore(staging).load(expected_kind="public")


class TestInactiveFilter(unittest.TestCase):
    """The safeguard filter: inactive rows never appear in vector, BM25 or code-filtered results."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        world = World(Path(cls.tmp.name))
        world.stage_both()
        cls.vdir = world.kb.cfg.versions_dir / read_pointer(world.kb.cfg, "staging")["version"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def store(self, method, inactive=()):
        s = KBStore(self.vdir, filter_method=method).load(expected_kind="staging")
        s._embedder = QueryEmbedder()
        s.inactive = np.asarray(sorted(inactive), dtype="int64")
        s._inactive_set = frozenset(inactive)
        return s

    def brute_force(self, s, query, k, inactive):
        q = QueryEmbedder().embed_query(query)[0]
        vectors = s.index.reconstruct_n(0, s.index.ntotal)
        scores = vectors @ q
        scores[list(inactive)] = -np.inf
        return [int(i) for i in np.argsort(-scores, kind="stable")[:k] if np.isfinite(scores[i])]

    def test_vector_search_matches_brute_force_for_both_methods(self):
        n = len(self.store("selector").records)
        inactive = {8, 10, 11, 13}
        for method in ("selector", "overfetch"):
            s = self.store(method, inactive)
            for query in ("zyxintake programme requirements", "roadmap activity week", "council chairman",
                          "library opening"):
                got = [r["chunk_id"] for r in s.vector_search(query, 5)]
                self.assertEqual(got, self.brute_force(s, query, 5, inactive), (method, query))
                self.assertFalse(inactive & set(got))
            everything = [r["chunk_id"] for r in s.vector_search("anything", n)]
            self.assertEqual(len(everything), n - len(inactive))       # FAISS -1 padding dropped

    def test_no_inactive_rows_means_identical_results_to_the_accepted_store(self):
        kb_store = self.store("selector")
        accepted = HeadingAwareStore(str(self.vdir))
        accepted.load()
        accepted._embedder = QueryEmbedder()
        for query in ("zyxintake ZQX 101", "HAWS 433", "examinations semester"):
            for name in ("vector_search", "bm25_search"):
                a = [(r["chunk_id"], round(r["score"], 6)) for r in getattr(kb_store, name)(query, 5)]
                b = [(r["chunk_id"], round(r["score"], 6)) for r in getattr(accepted, name)(query, 5)]
                self.assertEqual(a, b, (name, query))
            self.assertEqual(kb_store.chunks_with_codes(query), accepted.chunks_with_codes(query))

    def test_bm25_and_code_map_exclude_inactive_rows(self):
        s = self.store("selector")
        intake_rows = [i for i, p in enumerate(s.passages) if p["doc_id"] == "intake-test"]
        self.assertTrue(s.chunks_with_codes("ZQX 101"))
        f = self.store("selector", intake_rows)
        self.assertEqual(f.bm25_search("zyxintake", 10), [])
        self.assertIsNone(f.chunks_with_codes("ZQX 101"))
        self.assertEqual(f.vector_search("ZQX 101", 5, chunk_ids=intake_rows), [])
        o = self.store("overfetch", intake_rows)
        self.assertEqual(o.vector_search("ZQX 101", 5, chunk_ids=intake_rows), [])

    def test_results_carry_the_stable_identifier(self):
        s = self.store("selector")
        r = s.vector_search("zyxintake programme 2", 1)[0]
        self.assertEqual(r["passage_uid"], s.passages[r["chunk_id"]]["passage_uid"])
        self.assertEqual(s.row_of(r["passage_uid"]), r["chunk_id"])


if __name__ == "__main__":
    unittest.main()
