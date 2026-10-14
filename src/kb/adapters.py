"""
Adapters turn one registered document into passage units:
    {"record_id", "unit_type", "source", "file_name", "page", "heading", "text"}
where text starts with the citation header "[<source label>, p. N]" exactly like the yearbook chunks.

json_records  validated JSON datasets; adapter_options:
                {"groups": [{"name": "events", "path": "events", "id": "id", "text": "rag_text",
                             "page": "source_page", "heading": ["calendar_group", "semester", "activity"],
                             "heading_labels": {"raw value": "Readable heading"},       (optional)
                             "unit_type": "roadmap_event"}, ...],
                 "source_sha256_field": "source_sha256"}          (optional provenance check per record)
pdf_prose     text PDFs, split like the yearbooks (clean_page_text + 800/150 recursive splitter);
              adapter_options: {"chunk_size": 800, "chunk_overlap": 150, "min_page_chars": 30}

Adding a document of a known type needs only registry metadata; a new layout needs a new adapter here.
"""
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.kb.errors import ValidationFailed
from src.kb.ids import check_record_id, prose_record_id

Unit = Dict[str, Any]


def citation_header(source_label: str, page) -> str:
    return f"[{source_label}, p. {page}]" if page else f"[{source_label}]"


def heading_from(record: Dict[str, Any], fields: List[str], labels: Dict[str, str] = None) -> str:
    """'Section: ' + the heading fields joined by ' > '. `labels` maps raw field values to readable text
    (e.g. "application_fee" -> "Application fee"); unmapped values are used as they are."""
    labels = labels or {}
    parts = [labels.get(str(record[f]).strip(), str(record[f]).strip()) for f in fields
             if record.get(f) not in (None, "")]
    return "Section: " + " > ".join(parts) if parts else ""


def _display_name(entry: Dict[str, Any]) -> str:
    return (entry.get("source_file") or entry["dataset"])["name"]


class JsonRecordsAdapter:
    name = "json_records"

    def extract(self, entry: Dict[str, Any], dataset_path: Path) -> Tuple[List[Unit], List[str]]:
        """Returns (units, problems). Problems are validation errors found while reading the dataset."""
        options = entry.get("adapter_options") or {}
        groups = options.get("groups")
        if not isinstance(groups, list) or not groups:
            raise ValidationFailed("json_records needs adapter_options.groups: a non-empty list")
        data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
        sha_field = options.get("source_sha256_field")
        expected_sha = (entry.get("source_file") or {}).get("sha256")
        units, problems = [], []
        for g in groups:
            for key in ("name", "path", "id", "text", "page"):
                if key not in g:
                    raise ValidationFailed(f"group {g.get('name')!r} lacks {key!r}")
            labels = g.get("heading_labels") or {}
            if not isinstance(labels, dict) or not all(isinstance(k, str) and isinstance(v, str) and v.strip()
                                                       for k, v in labels.items()):
                raise ValidationFailed(f"group {g['name']!r}: heading_labels must map strings to non-empty strings")
            records = data.get(g["path"])
            if not isinstance(records, list):
                problems.append(f"group {g['name']}: dataset has no list at {g['path']!r}")
                continue
            for i, rec in enumerate(records):
                where = f"{g['name']}[{i}]"
                rid, text, page = rec.get(g["id"]), rec.get(g["text"]), rec.get(g["page"])
                try:
                    check_record_id(rid)
                except Exception as e:
                    problems.append(f"{where}: {e}")
                    continue
                if not isinstance(text, str) or not text.strip():
                    problems.append(f"{rid}: empty text field {g['text']!r}")
                    continue
                if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                    problems.append(f"{rid}: page field {g['page']!r} must be a positive integer, got {page!r}")
                    continue
                if sha_field and expected_sha and rec.get(sha_field) != expected_sha:
                    problems.append(f"{rid}: {sha_field} {rec.get(sha_field)!r} does not match the registered "
                                    f"source file {expected_sha}")
                units.append({"record_id": rid, "unit_type": g.get("unit_type", g["name"]),
                              "source": entry["source_label"], "file_name": _display_name(entry), "page": page,
                              "heading": heading_from(rec, g.get("heading", []), labels),
                              "text": f"{citation_header(entry['source_label'], page)}\n{text.strip()}"})
        return units, problems


class PdfProseAdapter:
    name = "pdf_prose"

    def extract(self, entry: Dict[str, Any], dataset_path: Path) -> Tuple[List[Unit], List[str]]:
        import pymupdf
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from src.data_loader import _dedupe_key, clean_page_text

        options = {"chunk_size": 800, "chunk_overlap": 150, "min_page_chars": 30, **(entry.get("adapter_options") or {})}
        splitter = RecursiveCharacterTextSplitter(chunk_size=options["chunk_size"],
                                                  chunk_overlap=options["chunk_overlap"], length_function=len,
                                                  separators=["\n\n", "\n", ". ", " ", ""])
        units, problems, seen = [], [], set()
        with pymupdf.open(dataset_path) as pdf:
            if pdf.needs_pass:
                return [], ["PDF is encrypted"]
            for page_index, page in enumerate(pdf):
                text = clean_page_text(page.get_text())
                if len(text) < options["min_page_chars"]:
                    continue
                key = _dedupe_key(text)
                if key in seen:
                    continue
                seen.add(key)
                for n, chunk in enumerate(splitter.split_text(text)):
                    units.append({"record_id": prose_record_id(page_index + 1, n), "unit_type": "prose",
                                  "source": entry["source_label"], "file_name": _display_name(entry),
                                  "page": page_index + 1, "heading": "",
                                  "text": f"{citation_header(entry['source_label'], page_index + 1)}\n{chunk}"})
        if not units:
            problems.append("no text extracted (scanned PDF without a text layer?)")
        return units, problems


ADAPTERS = {a.name: a for a in (JsonRecordsAdapter(), PdfProseAdapter())}


def get_adapter(name: str):
    if name not in ADAPTERS:
        raise ValidationFailed(f"unknown adapter {name!r}; available: {sorted(ADAPTERS)}")
    return ADAPTERS[name]


def body_of(text: str) -> str:
    """Passage text without its citation header (what BM25 and the code map read)."""
    return re.sub(r"^\[[^\]\n]*\]\n", "", text, count=1)
