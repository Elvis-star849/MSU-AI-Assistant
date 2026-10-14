"""
Stage 3.2: build knowledge-base base version 0001 from the frozen faiss_store_v2 (no re-chunking, no passage
embedding), verify it against the frozen originals, compare retrieval with the accepted v2 pipeline, and measure
timings and memory.

Run from the MSU-AI-Assistant root:  python stage3/run_3_2.py
Writes knowledge_base/ (the v3 store, approved location D3) and stage3/stage3_2_results.json.
Reads (never writes) faiss_store_v2/, eval/stage5_questions.json, eval/stage6/s6_5_ambiguous_codes.json and
eval/stage6/s6_6_freeze.json.
"""
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psutil

from src.kb.config import Actor, KBConfig
from src.kb.fsutil import sha256_bytes, sha256_file
from src.kb.service import KnowledgeBase

ROOT = Path(__file__).resolve().parent.parent
FROZEN = ROOT / "faiss_store_v2"
KB_ROOT = ROOT / "knowledge_base"
OUT = ROOT / "stage3" / "stage3_2_results.json"
BASE_DOCS = [
    {"doc_id": "yearbook-humanities", "title": "MSU Humanities Yearbook (General Information and Regulations)",
     "source_label": "MSU Humanities Yearbook"},
    {"doc_id": "yearbook-sciences-v2", "title": "MSU Sciences Yearbook Vol. 2 (General Information and Regulations)",
     "source_label": "MSU Sciences Yearbook Vol. 2"},
]
AMBIGUOUS_QUERIES = ["What is ACC 135?", "Tell me about ACC 136.", "What is AECS 131 about?",
                     "What is covered in HAWS 443?", "What does HAWS 444 cover?"]
ACTOR = Actor("stage3-implementation (approved by project owner 2026-10-13)", {"kb_admin"})
proc = psutil.Process()


def mem():
    info = proc.memory_info()
    return {"rss_mb": round(info.rss / 2**20, 1), "peak_mb": round(getattr(info, "peak_wset", info.rss) / 2**20, 1)}


def timed(fn):
    t = time.perf_counter()
    value = fn()
    return value, round(time.perf_counter() - t, 3)


def no_embedding():
    raise RuntimeError("Stage 3.2 must not embed passages")


def main():
    results = {"stage": "3.2", "memory": {"start": mem()}, "timings_s": {}, "checks": {}, "failures": []}
    check = lambda name, ok, detail=None: (results["checks"].__setitem__(name, {"ok": bool(ok), "detail": detail}),
                                           None if ok else results["failures"].append(name))
    freeze = json.loads((ROOT / "eval/stage6/s6_6_freeze.json").read_text(encoding="utf-8"))
    v2_manifest = json.loads((FROZEN / "manifest.json").read_text(encoding="utf-8"))
    frozen_hashes = {p.name: sha256_file(p) for p in sorted(FROZEN.iterdir())}
    results["frozen_v2"] = {"files_sha256": frozen_hashes, "chunk_count": v2_manifest["chunk_count"],
                            "corpus_fingerprint": v2_manifest["corpus_fingerprint"],
                            "heading_fingerprint": v2_manifest["heading_fingerprint"],
                            "vectors_checksum": v2_manifest["vectors_checksum"]}

    # 1. Build version 0001 ------------------------------------------------------------------------
    if KB_ROOT.exists() and any(KB_ROOT.iterdir()):
        raise SystemExit(f"{KB_ROOT} already exists; Stage 3.2 builds it once from scratch")
    kb = KnowledgeBase(KBConfig(root=KB_ROOT), embedder_factory=no_embedding)
    seed, results["timings_s"]["build_version_0001"] = timed(
        lambda: kb.seed_base(FROZEN, BASE_DOCS, ACTOR, expected_fingerprint=freeze["corpus_fingerprint"]))
    results["memory"]["after_build"] = mem()
    results["seed"] = seed
    vdir = KB_ROOT / "store" / "versions" / seed["version"]
    check("version is 0001 and CURRENT points to it", seed["version"] == "0001" and
          json.loads((KB_ROOT / "store/CURRENT").read_text())["version"] == "0001")
    check("no passage embedding performed", not (KB_ROOT / "embeddings").exists())

    # 2. Byte-level and fingerprint checks against the frozen originals ----------------------------
    v3_hashes = {p.name: sha256_file(p) for p in sorted(vdir.iterdir())}
    results["version_0001"] = {"files_sha256": v3_hashes}
    check("chunks.jsonl byte-identical to faiss_store_v2 (incl. CRLF)",
          v3_hashes["chunks.jsonl"] == frozen_hashes["chunks.jsonl"],
          {"v2": frozen_hashes["chunks.jsonl"], "v3": v3_hashes["chunks.jsonl"]})
    raw = (vdir / "chunks.jsonl").read_bytes()
    check("every base line ends with CRLF", raw.count(b"\r\n") == raw.count(b"\n") == 10732,
          {"crlf": raw.count(b"\r\n"), "lf": raw.count(b"\n")})
    check("index.faiss byte-identical to faiss_store_v2", v3_hashes["index.faiss"] == frozen_hashes["index.faiss"],
          {"v2": frozen_hashes["index.faiss"], "v3": v3_hashes["index.faiss"]})
    check("faiss_store_v2 unchanged by the build",
          {p.name: sha256_file(p) for p in sorted(FROZEN.iterdir())} == frozen_hashes)

    from src.kb.store import KBStore
    from src.heading_store import HeadingAwareStore, heading_fingerprint
    from src.vectorstore import corpus_fingerprint, vectors_checksum
    store, t_load_full = timed(lambda: KBStore(vdir).load(expected_kind="public"))
    results["timings_s"]["load_verify_v0001_full"] = t_load_full
    results["timings_s"]["load_v0001_breakdown"] = {k: round(v, 3) for k, v in store.timings.items()}
    _, results["timings_s"]["load_verify_v0001_without_bm25_check"] = timed(
        lambda: KBStore(vdir).load(expected_kind="public", verify_bm25=False))
    v2_store, results["timings_s"]["load_verify_frozen_v2_reference"] = timed(
        lambda: HeadingAwareStore(str(FROZEN)).load(expected_fingerprint=freeze["corpus_fingerprint"]) or None)
    results["memory"]["after_loads"] = mem()
    kbm, base = store.manifest, store.manifest["kb"]["base"]
    vectors = store.index.reconstruct_n(0, store.index.ntotal)
    computed = {"chunk_count": len(store.records), "corpus_fingerprint": corpus_fingerprint(store.records),
                "heading_fingerprint": heading_fingerprint(store.records), "vectors_checksum": vectors_checksum(vectors)}
    results["version_0001"].update(computed)
    results["version_0001"]["kb_base"] = base
    for key in ("chunk_count", "corpus_fingerprint", "heading_fingerprint", "vectors_checksum"):
        check(f"{key}: recomputed v0001 == frozen v2 manifest", computed[key] == v2_manifest[key],
              {"v2": v2_manifest[key], "v0001": computed[key]})
    check("corpus fingerprint == s6_6_freeze.json", computed["corpus_fingerprint"] == freeze["corpus_fingerprint"])
    check("kb.base block records the frozen values",
          base["chunk_count"] == 10732 and base["chunks_sha256"] == frozen_hashes["chunks.jsonl"]
          and base["corpus_fingerprint"] == v2_manifest["corpus_fingerprint"]
          and base["heading_fingerprint"] == v2_manifest["heading_fingerprint"]
          and base["vectors_checksum"] == v2_manifest["vectors_checksum"])
    carried = {k: (kbm[k], v2_manifest[k]) for k in ("embedding_model", "embedding_dim", "normalized_embeddings",
                                                       "query_prefix", "chunk_size", "chunk_overlap", "bm25",
                                                       "structure_version", "index_text")}
    check("embedding/BM25/structure settings carried over unchanged", all(a == b for a, b in carried.values()))
    check("records keep exactly the original schema",
          all(set(r) == {"chunk_id", "source", "file_name", "page", "text", "heading"} for r in store.records))
    docs = [(d["doc_id"], d["chunk_range"], d["passages"]) for d in kbm["kb"]["documents"]]
    check("base document ranges", docs == [("yearbook-humanities", [0, 5613], 5614),
                                           ("yearbook-sciences-v2", [5614, 10731], 5118)], docs)
    uids = [p["passage_uid"] for p in store.passages]
    check("passages.jsonl: one unique uid per row, matching chunk_id",
          len(set(uids)) == 10732 and uids[0] == "yearbook-humanities/v1/c00000"
          and uids[-1] == "yearbook-sciences-v2/v1/c10731"
          and all(p["chunk_id"] == i for i, p in enumerate(store.passages)), {"first": uids[0], "last": uids[-1]})

    # 3. Retrieval comparison with the accepted v2 pipeline -----------------------------------------
    from src.ambiguity import ambiguity_note, ambiguous_codes, code_titles
    from src.evidence import Stage6Retriever
    from src.kb.retriever import PublicRetriever
    from src.retrieval_v2 import routed_search
    v2, results["timings_s"]["load_v2_retriever_with_models"] = timed(lambda: Stage6Retriever("main"))
    v2._load()
    v2.retrieve("MSU yearbook warm-up")
    v3 = PublicRetriever.open(kb.cfg, reranker=v2._reranker)          # same MiniLM instance, same query model
    v3.store._embedder = v2._store.embedder
    results["memory"]["after_retrievers"] = mem()
    check("course-code map identical", v3.store.code_to_chunks == v2._store.code_to_chunks,
          {"codes": len(v2._store.code_to_chunks)})
    amb2, amb3 = ambiguous_codes(code_titles(v2._store.records)), ambiguous_codes(code_titles(v3.store.records))
    check("ambiguous-code metadata identical", amb2 == amb3, {"ambiguous_codes": len(amb2)})

    questions = json.loads((ROOT / "eval/stage5_questions.json").read_text(encoding="utf-8"))["questions"]
    queries = [(q["id"], q["category"], q["question"]) for q in questions]
    queries += [(f"A{i}", "ambiguous_code", q) for i, q in enumerate(AMBIGUOUS_QUERIES, 1)]
    rows, t2, t3, mismatches = [], [], [], []
    for qid, category, q in queries:
        c2 = [(r["chunk_id"], r["score"], r["route"]) for r in routed_search(v2._store, q, 10, "vector")]
        c3 = [(r["chunk_id"], r["score"], r["route"]) for r in routed_search(v3.store, q, 10, "vector")]
        e2, s2 = timed(lambda: v2.retrieve(q))
        e3, s3 = timed(lambda: v3.retrieve(q))
        t2.append(s2)
        t3.append(s3)
        f2 = [(e["chunk_id"], e["rerank_score"], e["page"], e["source"], e["text"]) for e in e2]
        f3 = [(e["chunk_id"], e["rerank_score"], e["page"], e["source"], e["text"]) for e in e3]
        n2, n3 = ambiguity_note(q, e2, amb2), ambiguity_note(q, e3, amb3)
        same = c2 == c3 and f2 == f3 and n2 == n3
        if not same:
            mismatches.append(qid)
        rows.append({"id": qid, "category": category, "question": q, "route": c2[0][2] if c2 else None,
                     "top5_chunk_ids": [x[0] for x in f2], "top5_pages": [f"{x[3]} p. {x[2]}" for x in f2],
                     "candidates_identical": c2 == c3, "top5_identical": f2 == f3,
                     "ambiguity_notes": [n["code"] for n in n2], "ambiguity_identical": n2 == n3,
                     "passage_uids_v0001": [e["passage_uid"] for e in e3], "ms_v2": round(s2 * 1000, 1),
                     "ms_v0001": round(s3 * 1000, 1)})
    results["retrieval_comparison"] = rows
    check(f"retrieval identical on all {len(queries)} queries (top-10 candidates with scores, reranked top 5 "
          "with scores and text, ambiguity notes)", not mismatches, mismatches)
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["route"])
    results["query_mix"] = {c: {"n": len(v), "routes": {x: v.count(x) for x in set(v)}} for c, v in by_cat.items()}
    results["timings_s"]["retrieval_per_query_ms"] = {
        "v2": {"median": round(statistics.median(t2) * 1000, 1), "max": round(max(t2) * 1000, 1)},
        "v0001": {"median": round(statistics.median(t3) * 1000, 1), "max": round(max(t3) * 1000, 1)}}

    # 4. Service-level operations on the real store ---------------------------------------------------
    report, results["timings_s"]["kb_verify"] = timed(kb.verify)
    check("kb.verify() ok with no warnings", report["ok"] and not report["warnings"], report)
    again, results["timings_s"]["seed_again_no_op"] = timed(
        lambda: kb.seed_base(FROZEN, BASE_DOCS, ACTOR, expected_fingerprint=freeze["corpus_fingerprint"]))
    check("re-running the seed is a no-op", again["no_op"] and again["version"] == "0001")
    from src.kb.versions import BaseMaterial
    _, results["timings_s"]["base_material_load_per_future_operation"] = timed(
        lambda: BaseMaterial.from_version(vdir))
    check("journal: every operation committed", kb.journal.open_operations() == [])
    results["memory"]["end"] = mem()
    results["knowledge_base_files"] = sorted(p.relative_to(ROOT).as_posix() for p in KB_ROOT.rglob("*") if p.is_file())
    results["knowledge_base_size_mb"] = round(sum(p.stat().st_size for p in KB_ROOT.rglob("*") if p.is_file()) / 2**20, 1)
    OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: results[k] for k in ("timings_s", "memory", "failures")}, indent=1))
    print(f"checks: {sum(c['ok'] for c in results['checks'].values())}/{len(results['checks'])} passed")
    return 1 if results["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
