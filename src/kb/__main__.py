"""
Command-line interface to the knowledge-base service (a thin wrapper; all logic is in src/kb/service.py).

    python -m src.kb [--root knowledge_base] [--actor NAME --roles kb_admin,...] <command> ...

    status | verify | history DOC_ID
    register DATASET META_JSON [--source-file PDF]
    validate DOC_ID VERSION | stage DOC_ID VERSION
    approve DOC_ID VERSION --basis TEXT [--decision-date YYYY-MM-DD] [--evidence TEXT] [--registry-verification TEXT]
    reject DOC_ID VERSION --reason TEXT | withdraw DOC_ID VERSION --reason TEXT
    publish | refresh-staging | recover | unlock
    rollback VERSION --reason TEXT [--emergency] [--reinstate-basis TEXT --reinstate DOC_ID:VERSION ...]
    reconcile-plan | reconcile {accept_index,restore_registry} --reason TEXT [--reinstate-basis ... --reinstate ...]
    republish DOC_ID VERSION --basis TEXT [--decision-date YYYY-MM-DD]
    update-metadata DOC_ID VERSION CHANGES_JSON --reason TEXT
"""
import argparse
import json
import sys
from pathlib import Path

from src.kb.config import Actor, KBConfig
from src.kb.errors import KBError
from src.kb.service import KnowledgeBase


def reinstate(args):
    if not getattr(args, "reinstate", None):
        return None
    return {"basis": args.reinstate_basis,
            "documents": [[d.rsplit(":", 1)[0], int(d.rsplit(":", 1)[1])] for d in args.reinstate]}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.kb")
    p.add_argument("--root", default="knowledge_base")
    p.add_argument("--actor", default="cli")
    p.add_argument("--roles", default="", help="comma-separated: kb_uploader, kb_approver, kb_admin")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("verify")
    sub.add_parser("publish")
    sub.add_parser("refresh-staging")
    sub.add_parser("unlock")
    sub.add_parser("recover")
    h = sub.add_parser("history"); h.add_argument("doc_id")
    r = sub.add_parser("register"); r.add_argument("dataset"); r.add_argument("meta_json")
    r.add_argument("--source-file")
    for name in ("validate", "stage"):
        s = sub.add_parser(name); s.add_argument("doc_id"); s.add_argument("version", type=int)
    a = sub.add_parser("approve"); a.add_argument("doc_id"); a.add_argument("version", type=int)
    a.add_argument("--basis", required=True); a.add_argument("--decision-date")
    a.add_argument("--evidence"); a.add_argument("--registry-verification")
    for name in ("reject", "withdraw"):
        s = sub.add_parser(name); s.add_argument("doc_id"); s.add_argument("version", type=int)
        s.add_argument("--reason", required=True)
    rb = sub.add_parser("rollback"); rb.add_argument("version"); rb.add_argument("--reason", required=True)
    rb.add_argument("--emergency", action="store_true")
    rc = sub.add_parser("reconcile"); rc.add_argument("mode", choices=["accept_index", "restore_registry"])
    rc.add_argument("--reason", required=True)
    for parser in (rb, rc):
        parser.add_argument("--reinstate-basis"); parser.add_argument("--reinstate", action="append", default=[])
    sub.add_parser("reconcile-plan")
    rp = sub.add_parser("republish"); rp.add_argument("doc_id"); rp.add_argument("version", type=int)
    rp.add_argument("--basis", required=True); rp.add_argument("--decision-date")
    um = sub.add_parser("update-metadata"); um.add_argument("doc_id"); um.add_argument("version", type=int)
    um.add_argument("changes_json"); um.add_argument("--reason", required=True)
    args = p.parse_args(argv)

    kb = KnowledgeBase(KBConfig(root=Path(args.root)))
    actor = Actor(args.actor, frozenset(r for r in args.roles.split(",") if r))
    try:
        if args.cmd == "status":
            out = kb.status()
        elif args.cmd == "verify":
            out = kb.verify()
        elif args.cmd == "history":
            out = kb.history(args.doc_id)
        elif args.cmd == "register":
            meta = json.loads(Path(args.meta_json).read_text(encoding="utf-8"))
            out = kb.register_upload(Path(args.dataset), meta, actor,
                                     source_file=Path(args.source_file) if args.source_file else None)
        elif args.cmd == "validate":
            out = kb.validate(args.doc_id, args.version, actor)
        elif args.cmd == "stage":
            out = kb.stage(args.doc_id, args.version, actor, progress=lambda d, t: print(f"embedded {d}/{t}"))
        elif args.cmd == "approve":
            out = kb.approve(args.doc_id, args.version, actor, basis=args.basis, decision_date=args.decision_date,
                             evidence=args.evidence, registry_verification=args.registry_verification)
        elif args.cmd == "reject":
            out = kb.reject(args.doc_id, args.version, actor, args.reason)
        elif args.cmd == "withdraw":
            out = kb.withdraw(args.doc_id, args.version, actor, args.reason)
        elif args.cmd == "publish":
            out = kb.publish(actor)
        elif args.cmd == "refresh-staging":
            out = kb.refresh_staging(actor)
        elif args.cmd == "rollback":
            out = kb.rollback(args.version, actor, args.reason, emergency=args.emergency, reinstate=reinstate(args))
        elif args.cmd == "reconcile-plan":
            out = kb.reconcile_plan()
        elif args.cmd == "reconcile":
            out = kb.reconcile(actor, args.mode, args.reason, reinstate=reinstate(args))
        elif args.cmd == "republish":
            out = kb.republish(args.doc_id, args.version, actor, basis=args.basis, decision_date=args.decision_date)
        elif args.cmd == "update-metadata":
            out = kb.update_metadata(args.doc_id, args.version,
                                     json.loads(Path(args.changes_json).read_text(encoding="utf-8")), actor, args.reason)
        elif args.cmd == "recover":
            out = kb.recover(actor)
        else:
            out = kb.unlock(actor)
    except KBError as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
