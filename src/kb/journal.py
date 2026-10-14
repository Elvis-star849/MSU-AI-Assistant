"""
Append-only operation journal (knowledge_base/ingest_log.jsonl).

Every write operation records "begin" (with the intended registry state when the registry will change), then
"commit" or "abort". An operation with "begin" but neither "commit" nor "abort" was interrupted; recovery completes or
aborts it. Entries are also the audit trail (actor, time, hashes).
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List


class Journal:
    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, entry: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def entries(self) -> List[Dict[str, Any]]:
        if not self.path.is_file():
            return []
        out = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    out.append({"event": "corrupt_line", "raw": line[:200]})   # a torn final line after a crash
        return out

    def open_operations(self) -> List[Dict[str, Any]]:
        """'begin' entries that have no matching 'commit' or 'abort'."""
        begun, closed = {}, set()
        for e in self.entries():
            if e.get("event") == "begin":
                begun[e["op_id"]] = e
            elif e.get("event") in ("commit", "abort"):
                closed.add(e.get("op_id"))
        return [e for op, e in begun.items() if op not in closed]

    def history(self, doc_id: str) -> List[Dict[str, Any]]:
        return [e for e in self.entries() if doc_id in (e.get("doc_ids") or [])]
