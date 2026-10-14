"""
Stage 3.3b (real knowledge base): readable information-record headings for the intake and explicit approval wording
for the road map, both through the journaled update_metadata operation followed by revalidation.
No embeddings, no staging/public build, CURRENT unchanged.

Run from the MSU-AI-Assistant root:  python stage3/run_3_3b.py   -> stage3/stage3_3b_results.json
"""
import copy
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.kb.config import Actor, KBConfig
from src.kb.fsutil import sha256_file
from src.kb.service import KnowledgeBase
from src.kb.versions import read_pointer

ROOT = Path(__file__).resolve().parent.parent
KB_ROOT = ROOT / "knowledge_base"
OUT = ROOT / "stage3" / "stage3_3b_results.json"
ACTOR = Actor("stage3-implementation (approved by project owner 2026-10-13)", {"kb_uploader"})
HEADING_LABELS = {
    "application_procedure": "How to apply for the January/February 2027 intake",
    "application_fee": "Application fee for the January/February 2027 intake",
    "fee_payment_banking_details": "Paying the application fee: bank accounts and deposit slip",
    "enquiries_contacts": "Admissions enquiries: phone, WhatsApp and email",
}


def no_embedding():
    raise RuntimeError("Stage 3.3b must not embed passages")


def read_units(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def main():
    out = {"stage": "3.3b", "checks": {}, "failures": []}

    def check(name, ok, detail=None):
        out["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            out["failures"].append(name)

    kb = KnowledgeBase(KBConfig(root=KB_ROOT), embedder_factory=no_embedding)
    current_before = sha256_file(KB_ROOT / "store/CURRENT")
    state = kb.registry.load()
    before = {d["doc_id"]: copy.deepcopy(d) for d in state["documents"] if not d.get("base")}
    check("pre-state: both documents validated, CURRENT 0001, no STAGING, no embeddings",
          all(d["status"] == "validated" for d in before.values()) and read_pointer(kb.cfg, "public")["version"] == "0001"
          and not (KB_ROOT / "store/STAGING").exists() and not (KB_ROOT / "embeddings").exists())

    # 1. Intake: readable information-record headings ------------------------------------------------
    intake = before["intake-2027-jan-feb"]
    options = copy.deepcopy(intake["adapter_options"])
    info_group = next(g for g in options["groups"] if g["name"] == "information_records")
    info_group["heading_labels"] = HEADING_LABELS
    out["intake_update"] = kb.update_metadata(
        "intake-2027-jan-feb", 1, {"adapter_options": options}, ACTOR,
        "Readable headings for the four information records (project owner request, Stage 3.3b). "
        "Source text, record IDs, dataset and provenance unchanged.")
    out["intake_revalidation"] = {k: v for k, v in kb.validate("intake-2027-jan-feb", 1, ACTOR).items()
                                  if k in ("ok", "errors", "warnings", "stats", "no_op")}

    # 2. Road map: explicit approval wording ----------------------------------------------------------
    road = before["roadmap-2027"]
    dataset = json.loads((KB_ROOT / road["dataset"]["path"]).read_text(encoding="utf-8"))
    prior = {
        "actor": "project-owner",
        "decision": "approved for use in the MSU AI Assistant",
        "decision_date": "2026-10-13",
        "scope": "Use of the corrected 2027 road map as a source document for this assistant only.",
        "basis": "The project owner approved the corrected 2027 road map for use in the MSU AI Assistant on 2026-10-13.",
        "not_claimed": "This is not an independent verification of the dates and not a formal approval of the road "
                       "map by the Midlands State University Registry or any other university body.",
        "registry_verification": "not performed",
        "university_registry_approval": "not obtained and not claimed",
        "evidence": "Project owner's instructions of 2026-10-13 (Stage 2 corrections; Stage 3.3b wording). Original "
                    f"source file: '{road['source_file']['name']}'. Dataset status_basis: {dataset['status_basis']}",
    }
    notes = ("Approved by the project owner for use in this assistant only; not independently verified and not "
             "formally approved by the university Registry. The source filename contains 'DRAFT'. The two date "
             "corrections are recorded in correction_history. The formal knowledge-base approval is recorded after "
             "staging (Stage 3.4).")
    out["roadmap_update"] = kb.update_metadata(
        "roadmap-2027", 1, {"prior_approval": prior, "notes": notes}, ACTOR,
        "Explicit approval wording: owner approval for use in this assistant, not Registry verification or approval "
        "(project owner request, Stage 3.3b).")
    out["roadmap_revalidation"] = {k: v for k, v in kb.validate("roadmap-2027", 1, ACTOR).items()
                                   if k in ("ok", "errors", "warnings", "stats", "no_op")}

    # 3. Checks -----------------------------------------------------------------------------------------
    after = {d["doc_id"]: d for d in kb.registry.load()["documents"] if not d.get("base")}
    ai, ar = after["intake-2027-jan-feb"], after["roadmap-2027"]
    check("both revalidated: status validated, 0 errors, 0 warnings",
          ai["status"] == ar["status"] == "validated" and out["intake_revalidation"]["ok"]
          and out["roadmap_revalidation"]["ok"] and not out["intake_revalidation"]["warnings"]
          and not out["roadmap_revalidation"]["warnings"])
    for name, b, a in (("intake", intake, ai), ("roadmap", road, ar)):
        check(f"{name}: dataset and source file (name, SHA-256, stored copy) unchanged",
              a["dataset"] == b["dataset"] and a["source_file"] == b["source_file"]
              and sha256_file(KB_ROOT / a["dataset"]["path"]) == a["dataset"]["sha256"]
              and sha256_file(KB_ROOT / a["source_file"]["path"]) == a["source_file"]["sha256"])
        check(f"{name}: metadata change recorded with the detached earlier units and report",
              a["metadata_history"][-1]["detached_units"] == b["units"]
              and (KB_ROOT / b["units"]["path"]).is_file()
              and [h["to"] for h in a["history"][-2:]] == ["uploaded", "validated"])
    old_i, new_i = read_units(KB_ROOT / intake["units"]["path"]), read_units(KB_ROOT / ai["units"]["path"])
    changed = [(o["record_id"], o["heading"], n["heading"]) for o, n in zip(old_i, new_i) if o != n]
    check("intake: 226 passages, same record IDs, pages and text; only the 4 information headings changed",
          len(new_i) == 226 and [u["record_id"] for u in old_i] == [u["record_id"] for u in new_i]
          and all({k: v for k, v in o.items() if k != "heading"} == {k: v for k, v in n.items() if k != "heading"}
                  for o, n in zip(old_i, new_i))
          and [c[0] for c in changed] == ["MSU-JF2027-INFO-01", "MSU-JF2027-INFO-02", "MSU-JF2027-INFO-03",
                                         "MSU-JF2027-INFO-04"], changed)
    out["information_headings"] = [{"record_id": r, "before": o, "after": n} for r, o, n in changed]
    old_r, new_r = read_units(KB_ROOT / road["units"]["path"]), read_units(KB_ROOT / ar["units"]["path"])
    check("roadmap: 21 passages byte-identical in content (same units SHA-256)",
          old_r == new_r and ar["units"]["sha256"] == road["units"]["sha256"] and len(new_r) == 21)
    check("roadmap: DRAFT filename and correction history unchanged",
          ar["source_file"]["name"] == "2027 DRAFT ROADMAP fin (1).pdf"
          and ar["correction_history"] == road["correction_history"] and len(ar["correction_history"]) == 2)
    check("roadmap: prior approval states owner approval for this assistant, not Registry approval",
          ar["prior_approval"]["decision"] == "approved for use in the MSU AI Assistant"
          and ar["prior_approval"]["registry_verification"] == "not performed"
          and "not a formal approval" in ar["prior_approval"]["not_claimed"]
          and ar["prior_approval"]["decision_date"] == "2026-10-13")
    check("intake still unapproved (no approvals, no prior approval)", not ai["approvals"] and not ai.get("prior_approval"))
    check("CURRENT unchanged (same file hash, version 0001)",
          sha256_file(KB_ROOT / "store/CURRENT") == current_before and read_pointer(kb.cfg, "public")["version"] == "0001")
    check("no new store version, no STAGING pointer, no embeddings",
          sorted(p.name for p in (KB_ROOT / "store/versions").iterdir()) == ["0001"]
          and not (KB_ROOT / "store/STAGING").exists() and not (KB_ROOT / "embeddings").exists())
    report = kb.verify()
    check("kb.verify(): ok, no problems, no warnings, no override", report["ok"] and not report["warnings"]
          and report["active_override"] is None, report)
    check("journal: no open operations", kb.journal.open_operations() == [])
    out["registry_after"] = {"intake-2027-jan-feb": {k: ai[k] for k in ("status", "units", "validation",
                                                                         "metadata_history")},
                             "roadmap-2027": {k: ar[k] for k in ("status", "units", "validation", "prior_approval",
                                                                  "notes", "correction_history", "metadata_history")}}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, c in out["checks"].items():
        print("PASS" if c["ok"] else "FAIL", name, "" if c["ok"] else c["detail"])
    print(f"{sum(c['ok'] for c in out['checks'].values())}/{len(out['checks'])} checks passed")
    return 1 if out["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
