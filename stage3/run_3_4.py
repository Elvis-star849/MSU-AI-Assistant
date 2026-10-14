"""
Stage 3.4: correct the approval metadata (owner clarification), embed the 247 new passages, build the staging
version (base + road map + intake) and the first public version after the base (base + road map), and verify
isolation, integrity, retrieval and rollback.

Run from the MSU-AI-Assistant root:  python stage3/run_3_4.py   -> stage3/stage3_4_results.json
Reads faiss_store_v2 (comparison only, never written). The Streamlit app is not touched (it still uses
faiss_store_v2). The rollback test runs on a temporary copy of knowledge_base/.
"""
import copy
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import psutil

from src.kb.config import Actor, KBConfig
from src.kb.fsutil import sha256_file
from src.kb.service import KnowledgeBase
from src.kb.versions import open_pointer, read_pointer

ROOT = Path(__file__).resolve().parent.parent
KB_ROOT = ROOT / "knowledge_base"
FROZEN = ROOT / "faiss_store_v2"
OUT = ROOT / "stage3" / "stage3_4_results.json"
IMPL = Actor("stage3-implementation (approved by project owner 2026-10-13)", {"kb_uploader"})
OWNER = Actor("project-owner (decision recorded by stage3-implementation)", {"kb_approver"})
CONFIRMED = "2026-10-13"
NO_REFERENCE = "None recorded: no Registry signatory or approval reference number was provided."
SAMPLES = [  # (id, question, expected passage_uid(s), visible in public?)
    ("S1", "What is the application fee for the January/February 2027 intake?",
     ["intake-2027-jan-feb/v1/MSU-JF2027-INFO-02"], False),
    ("S2", "When does the Bachelor of Education Honours Degree in Science and Applied Technologies start?",
     ["intake-2027-jan-feb/v1/MSU-JF2027-107"], False),
    ("S3", "What are the entry requirements for Mining Engineering?",
     ["intake-2027-jan-feb/v1/MSU-JF2027-132", "intake-2027-jan-feb/v1/MSU-JF2027-133"], False),
    ("S4", "Which bank accounts can I use to pay the MSU application fee?",
     ["intake-2027-jan-feb/v1/MSU-JF2027-INFO-03"], False),
    ("S5", "How can I contact MSU admissions?", ["intake-2027-jan-feb/v1/MSU-JF2027-INFO-04"], False),
    ("S6", "When are the second semester examinations in 2027?", ["roadmap-2027/v1/RM2027-13"], True),
    ("S7", "When is the second semester break in 2027?", ["roadmap-2027/v1/RM2027-11"], True),
    ("S8", "When does registration start for the first semester of 2027?", ["roadmap-2027/v1/RM2027-01"], True),
    ("S9", "When do Faculty of Education block release students write first semester examinations?",
     ["roadmap-2027/v1/RM2027-17"], True),
]
proc = psutil.Process()


def mem():
    i = proc.memory_info()
    return {"rss_mb": round(i.rss / 2**20), "peak_mb": round(getattr(i, "peak_wset", i.rss) / 2**20)}


def timed(fn):
    t = time.perf_counter()
    v = fn()
    return v, round(time.perf_counter() - t, 2)


def main():
    out = {"stage": "3.4", "checks": {}, "failures": [], "timings_s": {}, "memory": {"start": mem()}}

    def check(name, ok, detail=None):
        out["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            out["failures"].append(name)

    kb = KnowledgeBase(KBConfig(root=KB_ROOT))
    v2_hashes = {p.name: sha256_file(p) for p in sorted(FROZEN.iterdir())}
    state = kb.registry.load()
    docs = {d["doc_id"]: d for d in state["documents"] if not d.get("base")}
    check("pre-state: both validated, CURRENT 0001, no STAGING, no embeddings",
          all(d["status"] == "validated" for d in docs.values()) and read_pointer(kb.cfg, "public")["version"] == "0001"
          and not (KB_ROOT / "store/STAGING").exists() and not (KB_ROOT / "embeddings").exists())

    # 0. Approval metadata per the owner's clarification -------------------------------------------------
    road, intake = docs["roadmap-2027"], docs["intake-2027-jan-feb"]
    road_units_sha, intake_units_sha = road["units"]["sha256"], intake["units"]["sha256"]
    corrections = [{**{k: c[k] for k in ("event_id", "item", "dates_in_source", "approved_dates")},
                    "basis": "Approved date: the project owner confirmed on 2026-10-13 that the 2027 road map, "
                             "including this corrected date, is officially approved by the university. The text "
                             "printed in the original PDF is kept in dates_in_source for traceability."}
                   for c in road["correction_history"]]
    road_prior = {
        "actor": "project-owner", "decision": "officially approved university document", "decision_date": CONFIRMED,
        "scope": "The MSU 2027 Road Map is an officially approved university document. The two corrected dates "
                 "(RM2027-11 Semester Break 13/09/2027 - 17/09/2027; RM2027-13 Examinations 01/11/2027 - "
                 "12/11/2027) are the approved dates.",
        "basis": "The project owner confirmed on 2026-10-13 that the 2027 road map, including its two corrected "
                 "dates, is officially approved by the university.",
        "approval_reference": NO_REFERENCE,
        "source_file_note": "The original source file name '2027 DRAFT ROADMAP fin (1).pdf' contains 'DRAFT'. It is "
                            "kept unchanged for provenance and does not change the approved status.",
        "evidence": "Project owner's clarification of 2026-10-13 (before Stage 3.4)."}
    road_notes = ("Officially approved university document (project owner confirmation 2026-10-13); the two corrected "
                  "dates are the approved dates. The original source file name contains 'DRAFT' and is kept for "
                  "provenance only. The knowledge-base publication approval is recorded in Stage 3.4.")
    intake_prior = {
        "actor": "project-owner", "decision": "officially approved university source document",
        "decision_date": CONFIRMED,
        "scope": "The January/February 2027 Intake Advert is an officially approved university document. This does "
                 "not approve publishing its passages in the assistant: that technical approval is separate and "
                 "pending (decision D1).",
        "basis": "The project owner confirmed on 2026-10-13 that the January/February 2027 intake advert is an "
                 "officially approved university document.",
        "approval_reference": NO_REFERENCE,
        "evidence": "Project owner's clarification of 2026-10-13 (before Stage 3.4)."}
    intake_notes = ("Officially approved university source document (project owner confirmation 2026-10-13). "
                    "Publishing its passages in the assistant is a separate technical approval that is pending "
                    "(decision D1): the document stays staged and out of the public index.")
    reason = "Project owner clarification 2026-10-13: officially approved university document(s); corrected dates approved."
    out["metadata"] = {
        "roadmap": kb.update_metadata("roadmap-2027", 1, {"prior_approval": road_prior, "notes": road_notes,
                                                          "correction_history": corrections}, IMPL, reason),
        "intake": kb.update_metadata("intake-2027-jan-feb", 1, {"prior_approval": intake_prior, "notes": intake_notes},
                                     IMPL, reason)}
    for d in ("roadmap-2027", "intake-2027-jan-feb"):
        rep = kb.validate(d, 1, IMPL)
        check(f"{d}: revalidated with 0 errors, 0 warnings", rep["ok"] and not rep["warnings"], rep["errors"])
    docs = {d["doc_id"]: d for d in kb.registry.load()["documents"] if not d.get("base")}
    road, intake = docs["roadmap-2027"], docs["intake-2027-jan-feb"]
    check("passages unchanged by the metadata correction (same units SHA-256)",
          road["units"]["sha256"] == road_units_sha and intake["units"]["sha256"] == intake_units_sha)
    current_meta = json.dumps({k: road[k] for k in ("prior_approval", "notes", "correction_history")} |
                              {"i": {k: intake[k] for k in ("prior_approval", "notes")}}).lower()
    check("current metadata no longer says 'not verified', 'not obtained' or 'not a formal approval'",
          not any(s in current_meta for s in ("not independently verified", "not obtained", "not a formal approval",
                                              "not performed", "not claimed")))
    check("road map: DRAFT filename, 2 corrections with original-source text, 21 events",
          road["source_file"]["name"] == "2027 DRAFT ROADMAP fin (1).pdf"
          and [(c["event_id"], c["dates_in_source"], c["approved_dates"]) for c in road["correction_history"]] ==
          [("RM2027-11", "13/09/2026 - 17/09/2027", "13/09/2027 - 17/09/2027"),
           ("RM2027-13", "01/11/2027 - 12/11/202", "01/11/2027 - 12/11/2027")] and road["units"]["count"] == 21)

    # 1-2. Stage both (real embedding, pinned model revision) -------------------------------------------
    out["memory"]["before_embedding"] = mem()
    r1, out["timings_s"]["stage_roadmap_embed21_build"] = timed(lambda: kb.stage("roadmap-2027", 1, IMPL))
    r2, out["timings_s"]["stage_intake_embed226_build"] = timed(lambda: kb.stage("intake-2027-jan-feb", 1, IMPL))
    out["memory"]["after_staging"] = mem()
    out["staging_results"] = {"roadmap": r1, "intake": r2}
    check("247 passages embedded (21 + 226), nothing re-embedded", r1["embedded_now"] == 21 and r2["embedded_now"] == 226)
    near = {d: json.loads((KB_ROOT / docs_[d]["staging_report"]).read_text(encoding="utf-8"))["near_duplicates"]
            for docs_ in [{x["doc_id"]: x for x in kb.registry.load()["documents"]}] for d in ("roadmap-2027",
                                                                                              "intake-2027-jan-feb")}
    out["near_duplicates_semantic"] = {d: {"count": len(v), "within_document": sum(x["where"] == "within document" for x in v),
                                           "vs_public_store": sum(x["where"] == "public store" for x in v),
                                           "top": sorted(v, key=lambda x: -x["cosine"])[:15]} for d, v in near.items()}

    # 3-4. Formal publication approval of the road map, then publish ------------------------------------
    _, out["timings_s"]["approve_roadmap_rebuild_staging"] = timed(lambda: kb.approve(
        "roadmap-2027", 1, OWNER, basis="Officially approved university document, including its two approved "
        "corrected dates (project owner confirmation 2026-10-13). Approved for publication in the MSU AI Assistant.",
        decision_date=CONFIRMED, evidence="Project owner's clarification of 2026-10-13; approval_reference: " + NO_REFERENCE))
    pub, out["timings_s"]["publish_public_and_refresh_staging"] = timed(lambda: kb.publish(OWNER))
    out["publish"] = pub
    out["memory"]["after_publish"] = mem()
    state = kb.registry.load()
    st = {d["doc_id"]: d["status"] for d in state["documents"]}
    check("statuses: road map published, intake staged (not approved), base published",
          st == {"yearbook-humanities": "published", "yearbook-sciences-v2": "published",
                 "roadmap-2027": "published", "intake-2027-jan-feb": "staged"}, st)
    check("intake has no knowledge-base approval",
          not next(d for d in state["documents"] if d["doc_id"] == "intake-2027-jan-feb")["approvals"])

    # 5. Versions and integrity --------------------------------------------------------------------------
    (public, t_pub_load), (staging, t_stg_load) = timed(lambda: open_pointer(kb.cfg, "public")), \
        timed(lambda: open_pointer(kb.cfg, "staging"))
    out["timings_s"]["load_verify_public"], out["timings_s"]["load_verify_staging"] = t_pub_load, t_stg_load
    out["versions"] = {k: {"version": s.kb["version"], "passages": len(s.records),
                           "documents": [(d["doc_id"], d["chunk_range"], d["status"]) for d in s.kb["documents"]],
                           "files_sha256": {p.name: sha256_file(p) for p in sorted(s.version_dir.iterdir())},
                           "bm25_corpus_fingerprint": s.kb["bm25_corpus_fingerprint"]}
                       for k, s in (("public", public), ("staging", staging))}
    out["versions"]["all"] = sorted(p.name for p in (KB_ROOT / "store/versions").iterdir())
    check("public version: 10,753 passages (base + 21 road map events)", len(public.records) == 10753 and
          [d["doc_id"] for d in public.kb["documents"]] == ["yearbook-humanities", "yearbook-sciences-v2", "roadmap-2027"])
    check("staging version: 10,979 passages (base + road map + intake)", len(staging.records) == 10979 and
          [d["doc_id"] for d in staging.kb["documents"]] ==
          ["yearbook-humanities", "yearbook-sciences-v2", "roadmap-2027", "intake-2027-jan-feb"])
    frozen_raw = (FROZEN / "chunks.jsonl").read_bytes()
    v2_vectors_cs = json.loads((FROZEN / "manifest.json").read_text())["vectors_checksum"]
    from src.vectorstore import vectors_checksum
    for k, s in (("public", public), ("staging", staging)):
        raw = (s.version_dir / "chunks.jsonl").read_bytes()
        b = s.kb["base"]
        check(f"{k}: base lines byte-identical to faiss_store_v2 (CRLF) and base fingerprints 545d/7ce5/4a4a",
              raw.startswith(frozen_raw) and b["corpus_fingerprint"].startswith("sha256:545d0dab")
              and b["heading_fingerprint"].startswith("sha256:7ce5f4d9") and b["vectors_checksum"] == v2_vectors_cs
              and vectors_checksum(s.index.reconstruct_n(0, 10732)) == v2_vectors_cs)
    check("faiss_store_v2 unchanged", {p.name: sha256_file(p) for p in sorted(FROZEN.iterdir())} == v2_hashes)
    check("CURRENT points to the new public version", read_pointer(kb.cfg, "public")["version"] == public.kb["version"])

    # 6. Isolation: the staged intake is absent from every public structure -------------------------------
    from src.evidence import Stage6Retriever
    from src.kb.retriever import PublicRetriever, StagingRetriever
    from src.retrieval_v2 import routed_search
    v2 = Stage6Retriever("main")
    v2._load()
    v2.retrieve("warm-up")
    pr = PublicRetriever.open(kb.cfg, reranker=v2._reranker)
    sr = StagingRetriever.open(kb.cfg, OWNER, reranker=v2._reranker)
    for r in (pr, sr):
        r.store._embedder = v2._store.embedder
    public, staging = pr.store, sr.store
    out["memory"]["after_retrievers"] = mem()
    intake_rows_public = [p for p in public.passages if p["doc_id"] == "intake-2027-jan-feb"]
    all_public = public.vector_search("application fee intake programme entry requirements", len(public.records))
    bm25_intake_words = ["COBZZWHA", "4575486039200", "0716626820"]       # occur only in the intake advert
    check("public: no intake rows, no intake passage in a full-corpus vector search",
          not intake_rows_public and not any(r["passage_uid"].startswith("intake-") for r in all_public))
    check("public BM25: intake-only terms score nothing; staging finds them",
          all(not public.bm25_search(w, 5) for w in bm25_intake_words)
          and all(staging.bm25_search(w, 5) for w in bm25_intake_words))
    check("public and staging BM25 statistics differ (separate corpora)",
          public.kb["bm25_corpus_fingerprint"] != staging.kb["bm25_corpus_fingerprint"]
          and public.bm25.corpus_size == 10753 and staging.bm25.corpus_size == 10979)
    check("course-code maps: identical to v2 in both (no new codes)",
          public.code_to_chunks == v2._store.code_to_chunks == staging.code_to_chunks)
    try:
        StagingRetriever.open(kb.cfg, Actor("visitor", set()))
        check("staging retriever refuses a non-administrator", False)
    except Exception as e:
        check("staging retriever refuses a non-administrator", type(e).__name__ == "PermissionDenied")

    # 7. Retrieval: frozen regression set (v2 vs public vs staging) and new-document samples -------------
    questions = json.loads((ROOT / "eval/stage5_questions.json").read_text(encoding="utf-8"))["questions"]
    ambiguous = ["What is ACC 135?", "Tell me about ACC 136.", "What is AECS 131 about?",
                 "What is covered in HAWS 443?", "What does HAWS 444 cover?"]
    queries = [(q["id"], q["category"], q["question"]) for q in questions] + \
              [(f"A{i}", "ambiguous_code", q) for i, q in enumerate(ambiguous, 1)]
    rows, t_v2, t_pub, t_stg = [], [], [], []
    for qid, cat, q in queries:
        e2, a = timed(lambda: v2.retrieve(q))
        ep, b = timed(lambda: pr.retrieve(q))
        es, c = timed(lambda: sr.retrieve(q))
        t_v2.append(a); t_pub.append(b); t_stg.append(c)
        k2 = [(e["chunk_id"], round(e["rerank_score"], 6)) for e in e2]
        rows.append({"id": qid, "category": cat, "route": e2[0]["route"] if e2 else None,
                     "public_identical_to_v2": k2 == [(e["chunk_id"], round(e["rerank_score"], 6)) for e in ep],
                     "staging_identical_to_v2": k2 == [(e["chunk_id"], round(e["rerank_score"], 6)) for e in es],
                     "public_new_doc_hits": [e["passage_uid"] for e in ep if not e["passage_uid"].startswith("yearbook")],
                     "staging_new_doc_hits": [e["passage_uid"] for e in es if not e["passage_uid"].startswith("yearbook")]})
    out["regression"] = rows
    out["regression_summary"] = {
        "queries": len(rows), "public_identical_to_v2": sum(r["public_identical_to_v2"] for r in rows),
        "staging_identical_to_v2": sum(r["staging_identical_to_v2"] for r in rows),
        "public_queries_with_road_map_hits": [r["id"] for r in rows if r["public_new_doc_hits"]],
        "staging_queries_with_new_doc_hits": [r["id"] for r in rows if r["staging_new_doc_hits"]]}
    out["timings_s"]["retrieval_ms"] = {n: {"median": round(statistics.median(t) * 1000), "max": round(max(t) * 1000)}
                                        for n, t in (("v2", t_v2), ("public", t_pub), ("staging", t_stg))}
    samples = []
    for sid, q, expected, in_public in SAMPLES:
        es, ep = sr.retrieve(q), pr.retrieve(q)
        su, pu = [e["passage_uid"] for e in es], [e["passage_uid"] for e in ep]
        samples.append({"id": sid, "question": q, "expected": expected, "staging_top5": su, "public_top5": pu,
                        "staging_found": any(x in su for x in expected),
                        "staging_rank": next((su.index(x) + 1 for x in expected if x in su), None),
                        "public_found": any(x in pu for x in expected),
                        "public_has_intake": any(x.startswith("intake-") for x in pu)})
    out["samples"] = samples
    check("no public result for any query contains an intake passage",
          not any(s["public_has_intake"] for s in samples) and
          not any(h.startswith("intake-") for r in rows for h in r["public_new_doc_hits"]))
    check("road map samples found in public and staging top 5",
          all(s["public_found"] and s["staging_found"] for s in samples if s["id"] in ("S6", "S7", "S8", "S9")),
          [(s["id"], s["public_rank"] if "public_rank" in s else None) for s in samples])
    out["sample_summary"] = {"staging_found": sum(s["staging_found"] for s in samples), "of": len(samples)}

    # 8. Service-level checks and idempotency ------------------------------------------------------------
    rep, out["timings_s"]["kb_verify"] = timed(kb.verify)
    check("kb.verify(): ok, no warnings, no override", rep["ok"] and not rep["warnings"] and not rep["active_override"], rep)
    n_versions = len(list((KB_ROOT / "store/versions").iterdir()))
    again = kb.publish(OWNER)
    check("publishing again is a no-op (no new version)", again["no_op"] and again["staging"]["no_op"]
          and len(list((KB_ROOT / "store/versions").iterdir())) == n_versions)
    check("journal: no open operations", kb.journal.open_operations() == [])
    from src.kb.embeddings import EmbeddingCache
    cache = EmbeddingCache(KB_ROOT / "embeddings", kb.cfg.embedding_model, kb.cfg.embedding_revision, kb.cfg.embedding_recipe)
    check("embedding cache: 247 vectors for the pinned model revision", len(cache._load_index()) == 247,
          {"dir": str(cache.dir.relative_to(ROOT)), "meta": cache.meta})

    # 9. Rollback test on a temporary copy -----------------------------------------------------------------
    with tempfile.TemporaryDirectory() as t:
        copy_root = Path(t) / "knowledge_base"
        shutil.copytree(KB_ROOT, copy_root)
        ck = KnowledgeBase(KBConfig(root=copy_root))
        target = read_pointer(ck.cfg, "public")["version"]
        rb, out["timings_s"]["rollback_to_0001"] = timed(lambda: ck.rollback("0001", OWNER, "Stage 3.4 rollback test"))
        status_after_rb = {d["doc_id"]: d["status"] for d in ck.registry.load()["documents"]}
        ok_rb = rb["status_changes"] == [["roadmap-2027", 1, "published", "suspended"]] and \
            read_pointer(ck.cfg, "public")["version"] == "0001" and ck.verify()["ok"] and not ck.verify()["warnings"]
        noop = ck.publish(OWNER)
        still_out = not any(p["doc_id"] == "roadmap-2027" for p in open_pointer(ck.cfg, "public", verify_bm25=False).passages)
        fw, out["timings_s"]["rollback_forward"] = timed(lambda: ck.rollback(target, OWNER, "restore after test"))
        ok_fw = fw["status_changes"] == [["roadmap-2027", 1, "suspended", "published"]] and ck.verify()["ok"] \
            and not ck.verify()["warnings"]
        out["rollback_test"] = {"on": "temporary copy of knowledge_base/", "rollback": rb, "statuses_after": status_after_rb,
                                "publish_after_rollback_kept_roadmap_out": still_out, "forward": fw}
        check("rollback test (copy): 0001 suspends the road map, publish does not resurrect it, forward restores it",
              ok_rb and still_out and ok_fw)
    check("real knowledge base untouched by the rollback test",
          read_pointer(kb.cfg, "public")["version"] == public.kb["version"] and kb.verify()["ok"])

    out["memory"]["end"] = mem()
    out["knowledge_base_size_mb"] = round(sum(p.stat().st_size for p in KB_ROOT.rglob("*") if p.is_file()) / 2**20, 1)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    for name, c in out["checks"].items():
        print("PASS" if c["ok"] else "FAIL", name, "" if c["ok"] else str(c["detail"])[:300])
    print(json.dumps({"timings_s": out["timings_s"], "memory": out["memory"], "regression": out["regression_summary"],
                      "samples": out["sample_summary"]}, indent=1))
    print(f"{sum(c['ok'] for c in out['checks'].values())}/{len(out['checks'])} checks passed")
    return 1 if out["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
