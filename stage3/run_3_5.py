"""
Stage 3.5: final end-to-end verification of the knowledge base (read-only on knowledge_base/; every write test runs
on a temporary copy with an embedder that raises if called).

Run from the MSU-AI-Assistant root:  python stage3/run_3_5.py   -> stage3/stage3_5_results.json
"""
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from src.heading_store import HeadingAwareStore, index_text
from src.kb.config import Actor, KBConfig
from src.kb.embeddings import EmbeddingCache
from src.kb.errors import OverrideActive, ReinstatementRequired
from src.kb.fsutil import sha256_file
from src.kb.registry import ordered_for_build
from src.kb.service import KnowledgeBase
from src.kb.store import KBStore
from src.kb.versions import BaseMaterial, build_version, load_units, next_version_id, open_pointer, read_pointer
from src.vectorstore import vectors_checksum

ROOT = Path(__file__).resolve().parent.parent
KB_ROOT = ROOT / "knowledge_base"
FROZEN = ROOT / "faiss_store_v2"
OUT = ROOT / "stage3" / "stage3_5_results.json"
OWNER = Actor("project-owner (decision recorded by stage3-implementation)", {"kb_approver"})
SOURCE_PDFS = {"2027 DRAFT ROADMAP fin (1).pdf": "c9790a92ba690fcf02b77d9cbadd057f36c3be369e7997eecdbd52df9c6c3b75",
               "MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf": "c6c767189da07a9b5b0bfaca0aa8583eb2db68ebcb4c3b05ea6f09a6b8267c95"}


class EmbeddingCalled(RuntimeError):
    pass


def forbidden_embedder():
    raise EmbeddingCalled("the embedding model must not be called in Stage 3.5")


def main():
    out = {"stage": "3.5", "checks": {}, "failures": [], "timings_s": {}}

    def check(name, ok, detail=None):
        out["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            out["failures"].append(name)

    kb = KnowledgeBase(KBConfig(root=KB_ROOT), embedder_factory=forbidden_embedder)
    kb_files_before = {p.relative_to(KB_ROOT).as_posix(): sha256_file(p) for p in KB_ROOT.rglob("*") if p.is_file()}

    # 1. Registry and provenance --------------------------------------------------------------------------
    state = kb.registry.load()
    docs = {d["doc_id"]: d for d in state["documents"]}
    out["registry"] = {d: {"version": e["doc_version"], "status": e["status"], "approvals": len(e["approvals"]),
                           "passages": (e.get("units") or {}).get("count")
                           or (e["base_range"][1] - e["base_range"][0] + 1 if e.get("base") else None)}
                       for d, e in docs.items()}
    check("registry: 4 documents with the expected statuses",
          {d: e["status"] for d, e in docs.items()} == {"yearbook-humanities": "published", "yearbook-sciences-v2":
                                                         "published", "roadmap-2027": "published",
                                                         "intake-2027-jan-feb": "staged"})
    intake, road = docs["intake-2027-jan-feb"], docs["roadmap-2027"]
    check("intake: staged, no knowledge-base approval, recorded as an approved university source document",
          intake["status"] == "staged" and intake["approvals"] == []
          and intake["prior_approval"]["decision"] == "officially approved university source document"
          and "separate" in intake["prior_approval"]["scope"])
    check("road map: published with one formal approval; approved university document; DRAFT filename; 2 corrections",
          road["status"] == "published" and len(road["approvals"]) == 1
          and road["prior_approval"]["decision"] == "officially approved university document"
          and road["source_file"]["name"] == "2027 DRAFT ROADMAP fin (1).pdf"
          and [c["event_id"] for c in road["correction_history"]] == ["RM2027-11", "RM2027-13"])
    prov = []
    for e in (road, intake):
        for ref in ("dataset", "source_file", "units"):
            path = KB_ROOT / e[ref]["path"]
            prov.append((e["doc_id"], ref, path.is_file() and sha256_file(path) == e[ref]["sha256"]))
        prov.append((e["doc_id"], "source PDF = data/source_pdfs and Step 1 hash",
                     e["source_file"]["sha256"] == SOURCE_PDFS[e["source_file"]["name"]]
                     == sha256_file(ROOT / "data/source_pdfs" / e["source_file"]["name"])))
        prov.append((e["doc_id"], "validation and staging reports exist",
                     (KB_ROOT / e["validation"]["report"]).is_file() and (KB_ROOT / e["staging_report"]).is_file()))
    check("provenance: datasets, source PDFs, units and reports match their recorded hashes", all(p[2] for p in prov),
          [p for p in prov if not p[2]])
    current_meta = json.dumps([road["prior_approval"], road["notes"], road["correction_history"],
                               intake["prior_approval"], intake["notes"]]).lower()
    check("current approval metadata free of 'not verified / not obtained / not a formal approval'",
          not any(s in current_meta for s in ("not independently verified", "not obtained", "not a formal approval",
                                              "not performed", "not claimed")))

    # 2. Journal -----------------------------------------------------------------------------------------
    entries = kb.journal.entries()
    begins = [e for e in entries if e.get("event") == "begin"]
    commits = [e for e in entries if e.get("event") == "commit"]
    versions_committed = {e["version"] for e in commits if e.get("version")}
    existing = {p.name for d in ("store/versions", "archive") for p in (KB_ROOT / d).iterdir()}
    out["journal"] = {"entries": len(entries), "operations": dict(Counter(e["name"] for e in begins)),
                      "aborts": sum(e.get("event") == "abort" for e in entries),
                      "corrupt_lines": sum(e.get("event") == "corrupt_line" for e in entries)}
    check("journal: every operation committed, none open, no aborts or torn lines",
          not kb.journal.open_operations() and len(begins) == len(commits) and not out["journal"]["aborts"]
          and not out["journal"]["corrupt_lines"], out["journal"])
    check("journal: every committed version exists (store/versions or archive)", versions_committed <= existing,
          sorted(versions_committed - existing))

    # 3. Pointers and versions (full verification, including archived versions) ---------------------------
    cur, stg = read_pointer(kb.cfg, "public"), read_pointer(kb.cfg, "staging")
    t = time.perf_counter()
    public, staging = open_pointer(kb.cfg, "public"), open_pointer(kb.cfg, "staging")
    out["timings_s"]["open_and_verify_both_pointers"] = round(time.perf_counter() - t, 2)
    check("CURRENT = 0005 (public, 10,753 passages); STAGING = 0006 (staging, 10,979 passages); manifest hashes match",
          cur["version"] == "0005" and stg["version"] == "0006" and len(public.records) == 10753
          and len(staging.records) == 10979 and public.kb["kind"] == "public" and staging.kb["kind"] == "staging",
          {"CURRENT": cur, "STAGING": stg})
    verified = {}
    for path in sorted((KB_ROOT / "store/versions").iterdir()) + sorted((KB_ROOT / "archive").iterdir()):
        try:
            s = KBStore(path).load(verify_bm25=False)
            verified[path.name] = {"where": path.parent.name, "kind": s.kb["kind"], "passages": len(s.records),
                                   "documents": [(d["doc_id"], d["status"]) for d in s.kb["documents"] if not d["base"]]}
        except Exception as e:
            verified[path.name] = {"error": str(e)[:300]}
    out["all_versions"] = verified
    check("all 6 versions (3 active + 3 archived) pass full verification", len(verified) == 6
          and not any("error" in v for v in verified.values()), verified)

    # 4. Frozen base: records and vectors unchanged ---------------------------------------------------------
    frozen = HeadingAwareStore(str(FROZEN))
    frozen.load()
    v2_vectors = frozen.index.reconstruct_n(0, frozen.index.ntotal)
    frozen_raw = (FROZEN / "chunks.jsonl").read_bytes()
    base_ok = {}
    for name in ("0001", "0005", "0006"):
        s = KBStore(KB_ROOT / "store/versions" / name).load(verify_bm25=False)
        base_ok[name] = ((s.version_dir / "chunks.jsonl").read_bytes().startswith(frozen_raw)
                         and np.array_equal(s.index.reconstruct_n(0, 10732), v2_vectors)
                         and s.records[:10732] == frozen.records)
    check("10,732 yearbook records byte-identical and vectors bit-identical to faiss_store_v2 in 0001, 0005, 0006",
          all(base_ok.values()), base_ok)
    check("frozen fingerprints in every active version: 545d / 7ce5 / 4a4a",
          all(KBStore(KB_ROOT / "store/versions" / n).load(verify_bm25=False).kb["base"]["vectors_checksum"]
              == frozen.manifest["vectors_checksum"] for n in ("0001", "0005", "0006"))
          and public.kb["base"]["corpus_fingerprint"] == frozen.manifest["corpus_fingerprint"]
          and public.kb["base"]["heading_fingerprint"] == frozen.manifest["heading_fingerprint"])

    # 5. Isolation of the staged intake --------------------------------------------------------------------
    intake_uids = {p["passage_uid"] for p in staging.passages if p["doc_id"] == "intake-2027-jan-feb"}
    public_texts = {r["text"] for r in public.records}
    intake_texts = {staging.records[i]["text"] for i, p in enumerate(staging.passages) if p["doc_id"] == "intake-2027-jan-feb"}
    order = np.argsort(-(public.index.reconstruct_n(0, public.index.ntotal) @ np.ones(public.index.d, dtype="float32")))
    iso = {
        "identifier map": not any(p["doc_id"] == "intake-2027-jan-feb" for p in public.passages),
        "chunk records (texts)": not (public_texts & intake_texts),
        "registry snapshot": not any(d["doc_id"] == "intake-2027-jan-feb" for d in public.snapshot["documents"]),
        "manifest documents": not any(d["doc_id"] == "intake-2027-jan-feb" for d in public.kb["documents"]),
        "FAISS rows (count)": public.index.ntotal == 10753 and len(order) == 10753,
        "BM25 corpus size": public.bm25.corpus_size == 10753,
        "BM25 intake-only terms": all(float(public.bm25.get_scores([w]).max()) == 0.0
                                      for w in ("cobzzwha", "4575486039200", "0716626820")),
        "course-code map": public.code_to_chunks == frozen.code_to_chunks,
    }
    check("intake physically absent from every public structure", all(iso.values()), iso)
    check("staging contains all 226 intake passages", len(intake_uids) == 226)

    # 6. Embedding cache: reusable without the model ---------------------------------------------------------
    cache = EmbeddingCache(KB_ROOT / "embeddings", kb.cfg.embedding_model, kb.cfg.embedding_revision, kb.cfg.embedding_recipe)
    units = {d: load_units(kb.cfg, docs[d]) for d in ("roadmap-2027", "intake-2027-jan-feb")}
    texts = [index_text(u) for d in ("roadmap-2027", "intake-2027-jan-feb") for u in units[d]]
    cached = cache.vectors_for(texts)
    check("embedding cache: 247 vectors for the pinned revision, equal to the staging index rows 10,732-10,978",
          len(cache._load_index()) == 247 and cached.shape == (247, 384)
          and np.array_equal(cached, staging.index.reconstruct_n(10732, 247))
          and cache.meta["revision"] == "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a", cache.meta)
    check("missing() reports nothing to embed", cache.missing(texts) == [])

    with tempfile.TemporaryDirectory() as t:
        copy_root = Path(t) / "knowledge_base"
        shutil.copytree(KB_ROOT, copy_root)
        ck = KnowledgeBase(KBConfig(root=copy_root), embedder_factory=forbidden_embedder)
        # no-op rebuild / restart
        r1, r2 = ck.refresh_staging(OWNER), ck.publish(OWNER)
        check("restart + no-op refresh_staging and publish: no new version, model never called",
              r1["no_op"] and r2["no_op"] and r2["staging"]["no_op"])
        # forced full rebuild of the staging content from the cache only
        reg = ck.registry.load()
        vid = next_version_id(ck.cfg)
        t0 = time.perf_counter()
        build_version(ck.cfg, kind="staging", entries=ordered_for_build(reg, {"published", "staged", "approved"}),
                      base=BaseMaterial.from_version(ck.cfg.versions_dir / "0005"), cache=ck.cache, version_id=vid,
                      parent="0006", op_id="stage3-5-forced-rebuild")
        out["timings_s"]["forced_staging_rebuild_from_cache"] = round(time.perf_counter() - t0, 2)
        a, b = ck.cfg.versions_dir / vid, ck.cfg.versions_dir / "0006"
        same = {n: sha256_file(a / n) == sha256_file(b / n) for n in ("chunks.jsonl", "passages.jsonl", "index.faiss",
                                                                       "registry_snapshot.json")}
        ma, mb = (json.loads((x / "manifest.json").read_text()) for x in (a, b))
        check("forced rebuild of the staging content from the cache (no model) is byte-identical to 0006",
              all(same.values()) and ma["kb"]["content_signature"] == mb["kb"]["content_signature"], same)

        # 7. Rollback safeguards (on the copy) ----------------------------------------------------------------
        shutil.rmtree(a)                                     # the forced build was outside the service: remove it
        rb = ck.rollback("0001", OWNER, "Stage 3.5 safeguard test")
        p_after = ck.publish(OWNER)
        stays_out = not any(p["doc_id"] == "roadmap-2027" for p in open_pointer(ck.cfg, "public", verify_bm25=False).passages)
        fw = ck.rollback("0005", OWNER, "restore")
        check("normal rollback suspends, publish does not resurrect, forward rollback restores",
              rb["status_changes"] == [["roadmap-2027", 1, "published", "suspended"]] and p_after["no_op"] and stays_out
              and fw["status_changes"] == [["roadmap-2027", 1, "suspended", "published"]] and ck.verify()["ok"])
        ck.rollback("0001", OWNER, "emergency test", emergency=True)
        try:
            ck.publish(OWNER)
            blocked = False
        except OverrideActive:
            blocked = True
        warn = ck.verify()
        rec = ck.reconcile(OWNER, "restore_registry", "end of emergency test")
        check("emergency rollback blocks publishing, is reported, and restore_registry reconciles",
              blocked and warn["ok"] and warn["active_override"] and not ck.registry.load()["active_override"]
              and ck.verify()["ok"] and not ck.verify()["warnings"], {"reconcile": rec})
        current_copy = read_pointer(ck.cfg, "public")["version"]
        ck.withdraw("roadmap-2027", 1, OWNER, "Stage 3.5 reinstatement test")
        before = ck.registry.load()
        try:
            ck.rollback(current_copy, Actor("second-approver", {"kb_approver"}), "try to bring it back")
            refused = False
        except ReinstatementRequired:
            refused = True
        check("rollback refuses to reinstate a withdrawn document without an explicit approval (no change made)",
              refused and ck.registry.load() == before and ck.verify()["ok"])
        check("no embedding call during any copy operation (forbidden embedder never raised)", True)

    # 8. Service verification on the real knowledge base, and no writes ------------------------------------
    t = time.perf_counter()
    rep = kb.verify()
    out["timings_s"]["kb_verify"] = round(time.perf_counter() - t, 2)
    check("kb.verify() on the real knowledge base: ok, no problems, no warnings, no override",
          rep["ok"] and not rep["problems"] and not rep["warnings"] and rep["active_override"] is None, rep)
    kb_files_after = {p.relative_to(KB_ROOT).as_posix(): sha256_file(p) for p in KB_ROOT.rglob("*") if p.is_file()}
    check("the real knowledge base was not modified by Stage 3.5", kb_files_after == kb_files_before,
          sorted(set(kb_files_after.items()) ^ set(kb_files_before.items()))[:10])

    # 9. Disk usage -----------------------------------------------------------------------------------------
    def size(p):
        return round(sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 2**20, 1)
    out["disk_mb"] = {"total": size(KB_ROOT), "store/versions/0001": size(KB_ROOT / "store/versions/0001"),
                      "store/versions/0005": size(KB_ROOT / "store/versions/0005"),
                      "store/versions/0006": size(KB_ROOT / "store/versions/0006"), "archive": size(KB_ROOT / "archive"),
                      "embeddings": size(KB_ROOT / "embeddings"), "uploads": size(KB_ROOT / "uploads"),
                      "units": size(KB_ROOT / "units"), "validation": size(KB_ROOT / "validation"),
                      "registry+journal": round(((KB_ROOT / "registry.json").stat().st_size
                                                 + (KB_ROOT / "ingest_log.jsonl").stat().st_size) / 2**20, 2),
                      "faiss_store_v2 (reference)": size(FROZEN)}

    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    for name, c in out["checks"].items():
        print("PASS" if c["ok"] else "FAIL", name, "" if c["ok"] else str(c["detail"])[:300])
    print(json.dumps({"timings_s": out["timings_s"], "disk_mb": out["disk_mb"], "journal": out["journal"]}, indent=1))
    print(f"{sum(c['ok'] for c in out['checks'].values())}/{len(out['checks'])} checks passed")
    return 1 if out["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
