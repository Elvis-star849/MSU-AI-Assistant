"""
Stable external identifiers.

doc_id       permanent document name             "intake-2027-jan-feb"
doc_version  increases when the content changes  1
record_id    permanent within a document version "MSU-JF2027-107", "p0018-c03", "c00123"
passage_uid  permanent external key              "intake-2027-jan-feb/v1/MSU-JF2027-107"
record_key   links a record across versions      "intake-2027-jan-feb/MSU-JF2027-107"

chunk_id (the FAISS row) is internal and is never used as an external reference.
"""
import re

from src.kb.errors import InvalidIdentifier

_DOC_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def check_doc_id(doc_id: str) -> str:
    if not isinstance(doc_id, str) or not _DOC_ID.match(doc_id) or "--" in doc_id:
        raise InvalidIdentifier(f"doc_id must be 3-64 lower-case letters, digits and single hyphens: {doc_id!r}")
    return doc_id


def check_record_id(record_id: str) -> str:
    if not isinstance(record_id, str) or not _RECORD_ID.match(record_id):
        raise InvalidIdentifier(f"record_id must be 1-128 letters, digits, '.', '_' or '-': {record_id!r}")
    return record_id


def check_version(doc_version: int) -> int:
    if not isinstance(doc_version, int) or isinstance(doc_version, bool) or doc_version < 1:
        raise InvalidIdentifier(f"doc_version must be a positive integer: {doc_version!r}")
    return doc_version


def passage_uid(doc_id: str, doc_version: int, record_id: str) -> str:
    return f"{check_doc_id(doc_id)}/v{check_version(doc_version)}/{check_record_id(record_id)}"


def record_key(doc_id: str, record_id: str) -> str:
    return f"{check_doc_id(doc_id)}/{check_record_id(record_id)}"


def doc_key(doc_id: str, doc_version: int) -> str:
    """File-name form used for units and reports: "intake-2027-jan-feb@v1"."""
    return f"{check_doc_id(doc_id)}@v{check_version(doc_version)}"


def base_record_id(chunk_id: int) -> str:
    """Record id of a frozen yearbook row; base rows never move, so this is stable."""
    return f"c{chunk_id:05d}"


def prose_record_id(page: int, n: int) -> str:
    return f"p{page:04d}-c{n:02d}"
