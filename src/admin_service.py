"""
Admin operations behind the admin page (no UI code). Every function first checks the signed-in user's permission
(src/auth.require), then calls the existing knowledge-base service (src/kb/service.py), which checks its own roles
again and keeps the journal, versioning, staging, approval, publication and rollback rules.

Documents: upload (validated by src/upload_validation, then registered and validated by the KB service; optionally
staged), stage, approve, reject, publish, withdraw, roll back, verify, history.
Rules: the recorded corrections, the open questions, the audit summary, and review notes (recorded only; they never
change a rule).
Analytics: aggregates of the privacy-preserving question log (metadata only).

The knowledge base root is MSU_KB_ROOT or knowledge_base/. Publishing changes what the public assistant uses after a
restart; nothing here runs automatically.
"""
import json
import os
import re
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.auth import User, require
from src.upload_validation import check_upload

ROOT = Path(__file__).resolve().parents[1]
REVIEW_NOTES = ROOT / "instance" / "rule_review_notes.jsonl"


def kb_root() -> Path:
    return Path(os.environ.get("MSU_KB_ROOT") or ROOT / "knowledge_base")


def open_kb(root: Optional[Path] = None):
    from src.kb.config import KBConfig
    from src.kb.service import KnowledgeBase
    return KnowledgeBase(KBConfig(root=Path(root or kb_root())))


def actor(user: User):
    from src.kb.config import Actor
    return Actor(f"admin-ui:{user.name}", user.kb_roles)


def make_doc_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:48].strip("-") or "document"
    return f"{slug}-{time.strftime('%Y%m%d')}"


# ------------------------------------------------------------------ documents
def kb_status(user: User, kb) -> Dict[str, Any]:
    require(user, "view")
    return kb.status()


def document_history(user: User, kb, doc_id: str) -> Dict[str, Any]:
    require(user, "review")
    return kb.history(doc_id)


def upload_document(user: User, kb, file_name: str, data: bytes, title: str, source_label: str,
                    valid_for: str = "", notes: str = "", doc_id: Optional[str] = None, stage: bool = False,
                    scan: bool = True) -> Dict[str, Any]:
    """Validate the file, register it (status 'uploaded'), run the KB validation and, if asked, stage it (staging is
    visible only to the intake/staging profile, never to the public profile). Returns a report for the page."""
    require(user, "upload")
    check = check_upload(file_name, data, scan=scan)
    report: Dict[str, Any] = {"file": check.__dict__}
    if not check.ok:
        report["status"] = "rejected"
        return report
    if not (title or "").strip() or not (source_label or "").strip():
        report.update(status="rejected", problems=["a title and a source label are required"])
        return report
    meta = {"doc_id": doc_id or make_doc_id(title), "title": title.strip(), "source_label": source_label.strip(),
            "adapter": check.adapter}
    if valid_for:
        meta["valid_for"] = valid_for.strip()
    if notes:
        meta["notes"] = notes.strip()
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / check.file_name
        path.write_bytes(data)
        reg = kb.register_upload(path, meta, actor(user))
    report["registered"] = reg
    if reg.get("no_op"):
        report["status"] = "already registered"
        return report
    val = kb.validate(reg["doc_id"], reg["doc_version"], actor(user))
    report["validation"] = {"ok": val.get("ok"), "errors": val.get("errors", [])[:20],
                            "warnings": val.get("warnings", [])[:20], "units": val.get("unit_count") or val.get("units")}
    if not val.get("ok"):
        report["status"] = "validation failed"
        return report
    report["status"] = "validated"
    if stage:
        report["staged"] = kb.stage(reg["doc_id"], reg["doc_version"], actor(user))
        report["status"] = "staged"
    return report


def stage_document(user: User, kb, doc_id: str, doc_version: int) -> Dict[str, Any]:
    require(user, "upload")
    return kb.stage(doc_id, doc_version, actor(user))


def approve_document(user: User, kb, doc_id: str, doc_version: int, basis: str) -> Dict[str, Any]:
    require(user, "publish")
    if not (basis or "").strip():
        raise ValueError("an approval basis is required")
    return kb.approve(doc_id, doc_version, actor(user), basis=basis.strip())


def reject_document(user: User, kb, doc_id: str, doc_version: int, reason: str) -> Dict[str, Any]:
    require(user, "publish")
    return kb.reject(doc_id, doc_version, actor(user), reason)


def withdraw_document(user: User, kb, doc_id: str, doc_version: int, reason: str) -> Dict[str, Any]:
    require(user, "publish")
    return kb.withdraw(doc_id, doc_version, actor(user), reason)


def publish(user: User, kb) -> Dict[str, Any]:
    require(user, "publish")
    return kb.publish(actor(user))


def rollback(user: User, kb, version_id: str, reason: str) -> Dict[str, Any]:
    require(user, "publish")
    if not (reason or "").strip():
        raise ValueError("a reason is required")
    return kb.rollback(version_id, actor(user), reason.strip())


def verify(user: User, kb) -> Dict[str, Any]:
    require(user, "view")
    return kb.verify()


# ------------------------------------------------------------------ rules review
def rules_overview(user: User) -> Dict[str, Any]:
    require(user, "review")
    from src.eligibility_engine import RULES, open_questions
    corrections = json.loads((ROOT / "evaluation/eligibility_audit/corrections.json").read_text(encoding="utf-8"))
    audit_path = ROOT / "evaluation/results/eligibility_rules_audit/rules_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))["summary"] if audit_path.exists() else {}
    return {"rules_version": RULES["meta"].get("version"), "programmes": len(RULES["programmes"]),
            "corrections": corrections["corrections"], "open_questions": open_questions(),
            "audit": {k: audit.get(k) for k in ("status_counts", "reviewed_status_counts", "ambiguity_types")},
            "notes": review_notes(user)}


def record_review_note(user: User, programme_id: str, decision: str, note: str) -> Dict[str, Any]:
    """Record a reviewer's note or a confirmation received from MSU Admissions. It does not change any rule: a
    correction still goes through corrections.json with evidence and the regression tests."""
    require(user, "review")
    if decision not in ("confirmed_as_coded", "needs_change", "question_sent_to_admissions", "note"):
        raise ValueError("unknown decision")
    entry = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": user.name, "programme_id": programme_id,
             "decision": decision, "note": (note or "").strip()[:2000]}
    REVIEW_NOTES.parent.mkdir(parents=True, exist_ok=True)
    with open(REVIEW_NOTES, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def review_notes(user: User) -> List[Dict[str, Any]]:
    require(user, "review")
    if not REVIEW_NOTES.exists():
        return []
    return [json.loads(l) for l in REVIEW_NOTES.read_text(encoding="utf-8").splitlines() if l.strip()]


# ------------------------------------------------------------------ analytics
def analytics(user: User, log_path: Path) -> Dict[str, Any]:
    """Aggregates of the metadata-only question log."""
    require(user, "view")
    rows = []
    if Path(log_path).exists():
        for line in Path(log_path).read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    info = [r for r in rows if r.get("route") == "INFO"]
    lat = sorted(r["latency_ms"] for r in rows if isinstance(r.get("latency_ms"), (int, float)))
    return {"questions": len(rows),
            "by_route": dict(Counter(r.get("route") for r in rows)),
            "router_reasons": dict(Counter(r.get("router_reason") for r in rows)),
            "documents_not_found": sum(1 for r in info if r.get("not_found")),
            "documents_answered": sum(1 for r in info if r.get("status") == "answered" and not r.get("not_found")),
            "errors": sum(1 for r in rows if r.get("status") in ("error", "generation_error", "retrieval_error")),
            "eligibility_follow_ups": sum(1 for r in rows if r.get("route") == "ELIGIBILITY" and r.get("status") == "follow_up"),
            "results_read_by": dict(Counter(r.get("results_method") for r in rows if r.get("results_method"))),
            "latency_ms": {"median": lat[len(lat) // 2] if lat else None,
                           "p95": lat[min(len(lat) - 1, int(0.95 * (len(lat) - 1)))] if lat else None},
            "by_day": dict(sorted(Counter((r.get("timestamp") or "")[:10] for r in rows).items()))}
