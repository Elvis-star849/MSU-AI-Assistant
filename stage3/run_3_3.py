"""
Stage 3.3: register and validate the corrected 2027 road map and the January/February 2027 intake advert, and
produce the dry-run report. No embeddings, no staging/public build, CURRENT unchanged.

Run from the MSU-AI-Assistant root:  python stage3/run_3_3.py
Writes knowledge_base/ (registry, uploads, units, validation reports, journal) and stage3/stage3_3_dry_run.json.
"""
import itertools
import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.heading_store import index_text
from src.kb.adapters import body_of
from src.kb.config import Actor, KBConfig
from src.kb.fsutil import sha256_file
from src.kb.ids import passage_uid
from src.kb.service import KnowledgeBase
from src.kb.validate import text_key
from src.kb.versions import load_units, read_pointer

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT.parent / "msu docs" / "2027"
PDFS = ROOT / "data" / "source_pdfs"
KB_ROOT = ROOT / "knowledge_base"
OUT = ROOT / "stage3" / "stage3_3_dry_run.json"
ROAD_JSON, INTAKE_JSON = DOCS / "2027_ROADMAP_RAG_Ready_v2.json", DOCS / "MSU_2027_Intake_Corrected_v2.json"
ROAD_PDF, INTAKE_PDF = PDFS / "2027 DRAFT ROADMAP fin (1).pdf", PDFS / "MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf"
EXPECTED = {  # Step 1 source hashes; Stage 2 validation_report.json dataset hashes
    "roadmap_pdf": "c9790a92ba690fcf02b77d9cbadd057f36c3be369e7997eecdbd52df9c6c3b75",
    "intake_pdf": "c6c767189da07a9b5b0bfaca0aa8583eb2db68ebcb4c3b05ea6f09a6b8267c95",
    "roadmap_json": json.loads((ROOT / "stage2/validation_report.json").read_text())["files"]["2027_ROADMAP_RAG_Ready_v2.json"],
    "intake_json": json.loads((ROOT / "stage2/validation_report.json").read_text())["files"]["MSU_2027_Intake_Corrected_v2.json"],
}
ACTOR = Actor("stage3-implementation (approved by project owner 2026-10-13)", {"kb_uploader"})
FEB = {"MSU-JF2027-099", "MSU-JF2027-100", "MSU-JF2027-107", "MSU-JF2027-108"}
KNOWN_EMPTY_MODES = {"MSU-JF2027-146"}       # Biomedical Sciences: the advert states no mode of entry (Stage 2)


def no_embedding():
    raise RuntimeError("Stage 3.3 must not embed passages")


def words(text):
    return set(re.findall(r"[a-z0-9]+", body_of(text).lower()))


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else 0.0


def main():
    road = json.loads(ROAD_JSON.read_text(encoding="utf-8"))
    intake = json.loads(INTAKE_JSON.read_text(encoding="utf-8"))
    out = {"stage": "3.3", "checks": {}, "failures": [], "timings_s": {}}

    def check(name, ok, detail=None):
        out["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            out["failures"].append(name)

    # Pre-state
    current_before = sha256_file(KB_ROOT / "store/CURRENT")
    versions_before = sorted(p.name for p in (KB_ROOT / "store/versions").iterdir())
    check("pre-state: only version 0001, no STAGING, no embeddings",
          versions_before == ["0001"] and not (KB_ROOT / "store/STAGING").exists()
          and not (KB_ROOT / "embeddings").exists(), versions_before)

    road_meta = {
        "doc_id": "roadmap-2027", "title": "MSU 2027 Road Map", "source_label": "MSU 2027 Road Map",
        "adapter": "json_records", "valid_for": "2027 academic year",
        "adapter_options": {"groups": [{"name": "events", "path": "events", "id": "id", "text": "rag_text",
                                        "page": "source_page", "heading": ["calendar_group", "semester", "activity"],
                                        "unit_type": "roadmap_event"}],
                            "source_sha256_field": "source_sha256"},
        "correction_history": [{"event_id": c["event_id"], "item": c["item"], "dates_in_source": c["dates_in_source"],
                                "approved_dates": c["corrected_to"], "basis": c["basis"]}
                               for c in road["corrections_applied"]],
        "excluded_units": {"semester_summaries": {"count": len(road["semester_summaries"]),
                                                  "ids": [s["id"] for s in road["semester_summaries"]],
                                                  "reason": "Kept in the dataset for evaluation and possible later "
                                                            "inclusion; not indexed (owner decision R2)."}},
        "prior_approval": {"actor": "project-owner", "decision": "approved", "decision_date": "2026-10-13",
                           "basis": "The project owner confirmed that the corrected 2027 road map is the approved "
                                    "version for this project.",
                           "registry_verification": "not performed",
                           "evidence": "Project owner's instruction of 2026-10-13 (Stage 2 corrections); dataset "
                                       "status_basis: " + road["status_basis"]},
        "notes": "The source filename contains 'DRAFT'; the content is approved on the project owner's confirmation. "
                 "Formal approval is recorded after staging (Stage 3.4)."}
    intake_meta = {
        "doc_id": "intake-2027-jan-feb", "title": "MSU January/February 2027 Intake Advert",
        "source_label": "MSU January/February 2027 Intake Advert", "adapter": "json_records",
        "valid_for": "January/February 2027 intake",
        "adapter_options": {"groups": [
            {"name": "programmes", "path": "programmes", "id": "id", "text": "rag_text", "page": "source_page",
             "heading": ["faculty", "programme"], "unit_type": "programme"},
            {"name": "information_records", "path": "information_records", "id": "id", "text": "rag_text",
             "page": "source_page", "heading": ["topic"], "unit_type": "information"}],
            "source_sha256_field": "source_sha256"},
        "notes": "Not approved for publication. Record-level human approval is pending (Stage 2); stays out of the "
                 "public index until the project owner explicitly approves publication (decision D1)."}

    kb = KnowledgeBase(KBConfig(root=KB_ROOT), embedder_factory=no_embedding)
    t = time.perf_counter()
    reg_road = kb.register_upload(ROAD_JSON, road_meta, ACTOR, source_file=ROAD_PDF)
    reg_intake = kb.register_upload(INTAKE_JSON, intake_meta, ACTOR, source_file=INTAKE_PDF)
    out["timings_s"]["register_both"] = round(time.perf_counter() - t, 2)
    t = time.perf_counter()
    val_road = kb.validate("roadmap-2027", 1, ACTOR)
    val_intake = kb.validate("intake-2027-jan-feb", 1, ACTOR)
    out["timings_s"]["validate_both_incl_tokenizer"] = round(time.perf_counter() - t, 2)
    out["registration"] = {"roadmap": reg_road, "intake": reg_intake}
    out["validation"] = {name: {k: v[k] for k in ("ok", "errors", "warnings", "stats", "page_count")}
                         for name, v in (("roadmap-2027", val_road), ("intake-2027-jan-feb", val_intake))}
    check("engine validation: roadmap passed with 0 errors", val_road["ok"] and not val_road["errors"], val_road["errors"])
    check("engine validation: intake passed with 0 errors", val_intake["ok"] and not val_intake["errors"],
          val_intake["errors"])

    state = kb.registry.load()
    entries = {d["doc_id"]: d for d in state["documents"] if not d.get("base")}
    er, ei = entries["roadmap-2027"], entries["intake-2027-jan-feb"]
    units = {"roadmap-2027": load_units(kb.cfg, er), "intake-2027-jan-feb": load_units(kb.cfg, ei)}
    ur, ui = units["roadmap-2027"], units["intake-2027-jan-feb"]

    # Hashes and traceability
    check("source PDF hashes match the Step 1 record",
          er["source_file"]["sha256"] == EXPECTED["roadmap_pdf"] and ei["source_file"]["sha256"] == EXPECTED["intake_pdf"])
    check("dataset hashes match the Stage 2 validation report",
          er["dataset"]["sha256"] == EXPECTED["roadmap_json"] and ei["dataset"]["sha256"] == EXPECTED["intake_json"])
    check("stored upload copies match their hashes",
          all(sha256_file(KB_ROOT / e[k]["path"]) == e[k]["sha256"] for e in (er, ei) for k in ("dataset", "source_file")))
    check("datasets declare the same source file and hash",
          road["source"]["sha256"] == er["source_file"]["sha256"] and intake["source"]["sha256"] == ei["source_file"]["sha256"]
          and road["source"]["filename"] == er["source_file"]["name"] and intake["source"]["filename"] == ei["source_file"]["name"])
    check("roadmap keeps its original DRAFT source filename", er["source_file"]["name"] == "2027 DRAFT ROADMAP fin (1).pdf")
    check("every record carries the registered source SHA-256 (provenance check, no adapter problems)",
          not val_road["errors"] and not val_intake["errors"])
    check("units files match the registry hashes", all(
        sha256_file(KB_ROOT / e["units"]["path"]) == e["units"]["sha256"] for e in (er, ei)))

    # Counts and identifiers
    types_i = Counter(u["unit_type"] for u in ui)
    check("roadmap: 21 event passages (RM2027-01..21)",
          [u["record_id"] for u in ur] == [f"RM2027-{i:02d}" for i in range(1, 22)], len(ur))
    check("intake: 226 passages = 222 programmes + 4 information records",
          len(ui) == 226 and types_i == {"programme": 222, "information": 4}, dict(types_i))
    check("intake record ids in dataset order", [u["record_id"] for u in ui] ==
          [p["id"] for p in intake["programmes"]] + [r["id"] for r in intake["information_records"]])
    all_uids = [passage_uid(d, 1, u["record_id"]) for d, us in units.items() for u in us]
    check("247 new passages, all record ids and future passage_uids unique",
          len(all_uids) == 247 and len(set(all_uids)) == 247)
    summary_ids = {s["id"] for s in road["semester_summaries"]}
    check("semester summaries excluded (RM2027-S1..S4 not in units; recorded in excluded_units)",
          not summary_ids & {u["record_id"] for u in ur} and all(u["unit_type"] == "roadmap_event" for u in ur)
          and er["excluded_units"]["semester_summaries"]["count"] == 4, sorted(summary_ids))

    # Page references
    road_pages = Counter(u["page"] for u in ur)
    intake_pages = [u["page"] for u in ui]
    check("roadmap pages: all 1 of 1", road_pages == {1: 21} and val_road["page_count"] == 1)
    check("intake pages within 1..37 and equal to the dataset's source_page",
          val_intake["page_count"] == 37 and all(1 <= p <= 37 for p in intake_pages)
          and intake_pages == [p["source_page"] for p in intake["programmes"]] +
          [r["source_page"] for r in intake["information_records"]])
    check("information records on pages 1, 36, 36, 37",
          [u["page"] for u in ui if u["unit_type"] == "information"] == [1, 36, 36, 37])

    # Commencement dates
    by_id = {p["id"]: p for p in intake["programmes"]}
    comm_problems = []
    for u in ui:
        if u["unit_type"] != "programme":
            continue
        p = by_id[u["record_id"]]
        m = re.search(r"^COMMENCEMENT: (.+)$", u["text"], re.M)
        line = m.group(1) if m else None
        expected = ("February 2027" if p["id"] in FEB else "January 2027" if p["faculty"] == "Faculty of Education"
                    else "August 2027" if p["faculty"] in ("Faculty of Engineering and Geosciences",
                                                           "Faculty of Medicine and Health Sciences") else None)
        if line != p["commencement"] or p["commencement"] != expected:
            comm_problems.append((p["id"], line, p["commencement"], expected))
    comm = Counter(by_id[u["record_id"]]["commencement"] for u in ui if u["unit_type"] == "programme")
    check("commencement: passage text == dataset field == advert rule for all 222 programmes", not comm_problems,
          {"distribution": {str(k): v for k, v in comm.items()}, "problems": comm_problems})

    # Field completeness
    incomplete = []
    for p in intake["programmes"]:
        for f in ("id", "faculty", "programme", "duration_as_advertised", "entry_requirements", "source_page", "rag_text"):
            if not p.get(f):
                incomplete.append((p["id"], f))
        if not p.get("modes_of_entry") and p["id"] not in KNOWN_EMPTY_MODES:
            incomplete.append((p["id"], "modes_of_entry"))
    for r in intake["information_records"]:
        for f in ("id", "topic", "source_page", "source_text", "rag_text"):
            if not r.get(f):
                incomplete.append((r["id"], f))
    for e in road["events"]:
        for f in ("id", "calendar_group", "semester", "activity", "dates", "dates_in_source", "start_date",
                  "end_date", "source_page", "rag_text"):
            if not e.get(f):
                incomplete.append((e["id"], f))
    check("field completeness (only the documented Biomedical Sciences gap allowed)", not incomplete, incomplete)
    biomed = by_id["MSU-JF2027-146"]
    out["known_gaps"] = [{"record": "MSU-JF2027-146", "programme": biomed["programme"],
                          "duration_as_advertised": biomed["duration_as_advertised"],
                          "modes_of_entry": biomed["modes_of_entry"],
                          "note": "The advert states neither duration nor mode of entry (Stage 2 finding); the passage "
                                  "says so instead of guessing."}]

    # Roadmap corrections
    corr = {u["record_id"]: u["text"] for u in ur if u["record_id"] in ("RM2027-11", "RM2027-13")}
    check("corrected dates in passages, with DATE CORRECTION lines",
          "DATES: 13/09/2027 - 17/09/2027" in corr["RM2027-11"] and "prints 13/09/2026 - 17/09/2027" in corr["RM2027-11"]
          and "DATES: 01/11/2027 - 12/11/2027" in corr["RM2027-13"] and "prints 01/11/2027 - 12/11/202;" in corr["RM2027-13"])
    check("registry correction history == dataset corrections_applied",
          [(c["event_id"], c["dates_in_source"], c["approved_dates"]) for c in er["correction_history"]] ==
          [(c["event_id"], c["dates_in_source"], c["corrected_to"]) for c in road["corrections_applied"]])
    check("prior approval recorded (owner, 2026-10-13, not verified with the Registry)",
          er["prior_approval"]["decision_date"] == "2026-10-13" and er["prior_approval"]["actor"] == "project-owner"
          and er["prior_approval"]["registry_verification"] == "not performed")

    # Token limits (real bge-small tokenizer; no embedding)
    tc = kb.token_counter()
    toks = {d: [tc(index_text(u)) for u in us] for d, us in units.items()}
    out["tokens"] = {d: {"max": max(v), "median": statistics.median(v), "min": min(v), "over_512": sum(x > 512 for x in v),
                         "longest": us[v.index(max(v))]["record_id"]} for (d, v), us in zip(toks.items(), units.values())}
    check("every passage <= 512 tokens (indexed text: header + heading + body)",
          all(x <= 512 for v in toks.values() for x in v), out["tokens"])

    # Duplicates and lexical near-duplicates
    new = [(d, u) for d, us in units.items() for u in us]
    keys = Counter(text_key(u["text"]) for _, u in new)
    with open(KB_ROOT / "store/versions/0001/chunks.jsonl", encoding="utf-8") as f:
        base_records = [json.loads(line) for line in f]
    base_keys = {text_key(r["text"]) for r in base_records}
    out["duplicates"] = {"exact_within_new": [u["record_id"] for _, u in new if keys[text_key(u["text"])] > 1],
                         "exact_vs_base": [u["record_id"] for _, u in new if text_key(u["text"]) in base_keys]}
    check("no exact duplicate passages (within new documents or against the base)",
          not out["duplicates"]["exact_within_new"] and not out["duplicates"]["exact_vs_base"], out["duplicates"])
    ws = [(d, u["record_id"], words(u["text"])) for d, u in new]
    pairs = sorted(((round(jaccard(a[2], b[2]), 3), a[1], b[1]) for a, b in itertools.combinations(ws, 2)
                    if jaccard(a[2], b[2]) >= 0.85), reverse=True)
    from src.kb.store import KBStore
    from src.vectorstore import bm25_tokenize
    base_store = KBStore(KB_ROOT / "store/versions/0001").load(expected_kind="public", verify_bm25=False)
    vs_base = []
    for d, rid, w in ws:
        u = next(x for x in units[d] if x["record_id"] == rid)
        scores = base_store.bm25.get_scores(bm25_tokenize(f"{u['heading']}\n{body_of(u['text'])}"))
        j = int(scores.argmax())
        sim = jaccard(w, words(base_records[j]["text"]))
        vs_base.append((round(sim, 3), rid, j, base_records[j]["source"], base_records[j]["page"]))
    vs_base.sort(reverse=True)
    out["near_duplicates_lexical"] = {
        "method": "word-set Jaccard on passage bodies; vs base = Jaccard with the top BM25 match in version 0001. "
                  "Semantic (cosine >= 0.97) near-duplicates are computed at staging (Stage 3.4).",
        "within_new_threshold": 0.85, "within_new_pairs": len(pairs),
        "within_new_by_document": dict(Counter(p[1].split("-")[0] for p in pairs)),
        "within_new_top": pairs[:25],
        "vs_base_max": vs_base[0][0], "vs_base_over_0_5": [x for x in vs_base if x[0] >= 0.5],
        "vs_base_top5": vs_base[:5]}

    # Samples and traceability
    pick = ["RM2027-01", "RM2027-11", "RM2027-13", "RM2027-21", "MSU-JF2027-001", "MSU-JF2027-107",
            "MSU-JF2027-133", "MSU-JF2027-146", "MSU-JF2027-INFO-02", "MSU-JF2027-INFO-03"]
    allu = {u["record_id"]: (d, u) for d, u in new}
    out["samples"] = [{"doc_id": allu[r][0], "passage_uid": passage_uid(allu[r][0], 1, r), **allu[r][1],
                       "tokens": tc(index_text(allu[r][1]))} for r in pick]
    out["traceability"] = {d: {"title": e["title"], "source_label": e["source_label"], "status": e["status"],
                               "source_file": e["source_file"], "dataset": e["dataset"], "units": e["units"],
                               "validation_report": e["validation"]["report"],
                               "passages": [{"record_id": u["record_id"], "unit_type": u["unit_type"], "page": u["page"],
                                             "file_name": u["file_name"], "passage_uid": passage_uid(d, 1, u["record_id"])}
                                            for u in units[d]]}
                           for d, e in (("roadmap-2027", er), ("intake-2027-jan-feb", ei))}

    # Post-state
    check("registry: both documents 'validated'; intake has no approvals; nothing staged/approved/published",
          er["status"] == "validated" and ei["status"] == "validated" and not er["approvals"] and not ei["approvals"])
    check("CURRENT unchanged, still version 0001", sha256_file(KB_ROOT / "store/CURRENT") == current_before
          and read_pointer(kb.cfg, "public")["version"] == "0001")
    check("no new store version, no STAGING pointer, no embeddings",
          sorted(p.name for p in (KB_ROOT / "store/versions").iterdir()) == ["0001"]
          and not (KB_ROOT / "store/STAGING").exists() and not (KB_ROOT / "embeddings").exists())
    rep = kb.verify()
    check("kb.verify() ok, no warnings", rep["ok"] and not rep["warnings"], rep)
    check("journal: no open operations", kb.journal.open_operations() == [])
    out["registry_entries"] = {d: {k: v for k, v in e.items() if k != "history"} | {"history": e["history"]}
                               for d, e in (("roadmap-2027", er), ("intake-2027-jan-feb", ei))}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, c in out["checks"].items():
        print("PASS" if c["ok"] else "FAIL", name)
    print(f"{sum(c['ok'] for c in out['checks'].values())}/{len(out['checks'])} checks passed; timings {out['timings_s']}")
    return 1 if out["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
