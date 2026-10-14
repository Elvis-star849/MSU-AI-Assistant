"""Stage 3 integrity record: SHA-256 of every protected file, before and after Stage 3 work.

Usage (from the MSU-AI-Assistant root):
    python stage3/integrity.py before      -> writes stage3/integrity_before.json
    python stage3/integrity.py after       -> writes stage3/integrity_after.json and compares with "before"

Protected: frozen indexes, evaluation records, notebooks, existing source code and tests, the app, configuration,
the document datasets in ../msu docs, the source PDFs and the Stage 2 outputs. `.env` is deliberately skipped (its
contents are never read). New files are reported separately and are not an integrity failure.
Exits non-zero if any protected file changed or disappeared.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # MSU-AI-Assistant
DOCS = ROOT.parent / "msu docs"
OUT = ROOT / "stage3"

PROTECTED_DIRS = ["faiss_store", "faiss_store_v2", "eval", "notebook", "src", "tests", ".streamlit",
                  "data/source_pdfs", "stage2"]
PROTECTED_FILES = ["app.py", "msu_chatbot_pipeline.ipynb", "requirements.txt", ".gitignore", ".env.example",
                   "README.md", "LICENSE"]
SKIP_PARTS = {"__pycache__", ".git"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def protected_files():
    files = []
    for d in PROTECTED_DIRS:
        files += [p for p in (ROOT / d).rglob("*") if p.is_file() and not SKIP_PARTS & set(p.parts)]
    files += [ROOT / f for f in PROTECTED_FILES if (ROOT / f).is_file()]
    files += [p for p in DOCS.rglob("*") if p.is_file()]
    return sorted(set(files))


def key(path: Path) -> str:
    return path.relative_to(ROOT.parent).as_posix()     # e.g. "MSU-AI-Assistant/src/vectorstore.py"


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def snapshot():
    return {"files": {key(p): sha256(p) for p in protected_files()},
            "git_head": git("rev-parse", "HEAD"),
            "git_status": git("status", "--porcelain").splitlines()}


def main(label):
    snap = snapshot()
    (OUT / f"integrity_{label}.json").write_text(json.dumps(snap, indent=1) + "\n", encoding="utf-8")
    print(f"{label}: {len(snap['files'])} protected files hashed; git HEAD {snap['git_head'][:7]}")
    if label == "before":
        return 0
    before = json.loads((OUT / "integrity_before.json").read_text(encoding="utf-8"))
    changed = sorted(k for k in before["files"] if k in snap["files"] and before["files"][k] != snap["files"][k])
    missing = sorted(k for k in before["files"] if k not in snap["files"])
    added = sorted(k for k in snap["files"] if k not in before["files"])
    print(f"changed: {len(changed)}  missing: {len(missing)}  new (allowed): {len(added)}")
    for k in changed + missing:
        print("  PROTECTED FILE ALTERED:", k)
    for k in added:
        print("  new:", k)
    if snap["git_head"] != before["git_head"]:
        print("  GIT HEAD CHANGED:", before["git_head"], "->", snap["git_head"])
    ok = not changed and not missing and snap["git_head"] == before["git_head"]
    print("INTEGRITY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "before"))
