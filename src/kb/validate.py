"""
Validation of a document's passage units before they are staged.

Errors block staging: no units, duplicate or invalid record_id, wrong source label, empty text, page out of range,
more than max_tokens in the indexed text, correction history pointing at records that do not exist, and problems the
adapter found (e.g. a record whose source SHA-256 differs from the registered source file).
Warnings are reported for review: course codes (they switch questions to code-aware search), exact duplicates
within the document or against passages already in the store.
"""
import hashlib
import re
import statistics
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional

from src.heading_store import index_text
from src.kb.adapters import body_of
from src.kb.ids import check_record_id
from src.vectorstore import course_codes


def text_key(text: str) -> str:
    """Hash of a passage body, ignoring the citation header, case and whitespace (exact-duplicate detection)."""
    return hashlib.sha256(re.sub(r"\s+", " ", body_of(text)).strip().lower().encode("utf-8")).hexdigest()


def validate_units(units: List[Dict[str, Any]], *, entry: Dict[str, Any], token_counter: Callable[[str], int],
                   max_tokens: int = 512, page_count: Optional[int] = None,
                   adapter_problems: Iterable[str] = (), existing_text_keys: Iterable[str] = ()) -> Dict[str, Any]:
    errors: List[str] = list(adapter_problems)
    warnings: List[str] = []
    if not units:
        errors.append("the document produced no passages")

    ids = Counter(u["record_id"] for u in units)
    errors += [f"duplicate record_id {rid} ({n} times)" for rid, n in ids.items() if n > 1]
    tokens = []
    existing = set(existing_text_keys)
    seen: Dict[str, str] = {}
    codes: Dict[str, List[str]] = {}
    for u in units:
        rid = u["record_id"]
        try:
            check_record_id(rid)
        except Exception as e:
            errors.append(str(e))
        if u["source"] != entry["source_label"]:
            errors.append(f"{rid}: source {u['source']!r} differs from the registered label {entry['source_label']!r}")
        if not body_of(u["text"]).strip():
            errors.append(f"{rid}: empty passage")
        if page_count is not None and not (1 <= u["page"] <= page_count):
            errors.append(f"{rid}: page {u['page']} outside 1..{page_count}")
        n = token_counter(index_text(u))
        tokens.append(n)
        if n > max_tokens:
            errors.append(f"{rid}: {n} tokens > {max_tokens} (would be truncated by the embedding model)")
        found = course_codes(body_of(u["text"]), uppercase_only=True)
        if found:
            codes[rid] = found
        key = text_key(u["text"])
        if key in seen:
            warnings.append(f"{rid}: same text as {seen[key]}")
        else:
            seen[key] = rid
        if key in existing:
            warnings.append(f"{rid}: same text as a passage already in the store")

    for c in entry.get("correction_history") or []:
        if c.get("event_id") and c["event_id"] not in ids:
            errors.append(f"correction_history refers to {c['event_id']}, which is not a record of this document")
    if codes:
        warnings.append(f"course codes found in {len(codes)} passages (these route questions to code-aware search): "
                        + "; ".join(f"{k}: {', '.join(v)}" for k, v in list(codes.items())[:20]))

    stats = {"passages": len(units), "unit_types": dict(Counter(u["unit_type"] for u in units)),
             "tokens_max": max(tokens) if tokens else 0,
             "tokens_median": statistics.median(tokens) if tokens else 0,
             "pages": [min(u["page"] for u in units), max(u["page"] for u in units)] if units else None,
             "course_codes": codes}
    return {"ok": not errors, "errors": errors, "warnings": warnings, "stats": stats,
            "samples": [units[i] for i in sorted({0, len(units) // 2, len(units) - 1}) if units]}
