"""
Validation of documents uploaded through the admin page, before anything is registered in the knowledge base.

    check_upload(file_name, data) -> UploadCheck

- the extension must be .pdf, .docx or .txt, and the content must really be that type (magic bytes / structure);
- size limit (MAX_BYTES), non-empty, a clean file name;
- PDF: opens, not encrypted, has a text layer; DOCX: a valid Word zip with word/document.xml, no macros, no embedded
  executables; TXT: UTF-8 without NUL bytes;
- SHA-256 fingerprint (duplicates are refused by the knowledge-base service itself);
- prompt-injection screening: passages with instruction-like text aimed at the model are listed as warnings (the
  assistant also withholds such passages at answer time, src/safeguards.screen_evidence);
- optional malware scan with Microsoft Defender (MpCmdRun.exe) when it is available; otherwise reported as not scanned.
Uploaded files are treated as untrusted data: they are never executed, and nothing in them can change instructions.
"""
import hashlib
import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

MAX_BYTES = 25 * 1024 * 1024
ADAPTER_FOR = {".pdf": "pdf_prose", ".docx": "docx_prose", ".txt": "text_prose"}
SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
DEFENDER = [Path(r"C:\Program Files\Windows Defender\MpCmdRun.exe")]


@dataclass
class UploadCheck:
    ok: bool
    file_name: str
    adapter: Optional[str] = None
    sha256: str = ""
    size: int = 0
    problems: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    malware_scan: str = "not scanned"


def safe_file_name(name: str) -> str:
    name = Path(name or "upload").name                        # no directories
    cleaned = SAFE_NAME.sub("_", name).strip(" .") or "upload"
    return cleaned[:120]


def _pdf_checks(data: bytes, problems: List[str]) -> str:
    if not data.startswith(b"%PDF-"):
        problems.append("the file is not a PDF (missing %PDF header)")
        return ""
    import pymupdf
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass:
                problems.append("the PDF is encrypted")
                return ""
            text = "".join(page.get_text() for page in pdf)
    except Exception as error:                                # corrupt PDF
        problems.append(f"the PDF cannot be opened ({error.__class__.__name__})")
        return ""
    if len(text.strip()) < 50:
        problems.append("the PDF has no text layer (scanned image?); OCR is not enabled, so it needs manual handling")
    return text


def _docx_checks(data: bytes, problems: List[str]) -> str:
    if not data.startswith(b"PK\x03\x04"):
        problems.append("the file is not a .docx (not a zip archive)")
        return ""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
            if "word/document.xml" not in names:
                problems.append("the zip archive is not a Word document (no word/document.xml)")
                return ""
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                problems.append("the document contains macros, which are not accepted")
            if any(n.lower().endswith((".exe", ".dll", ".bat", ".cmd", ".js", ".vbs", ".ps1")) for n in names):
                problems.append("the document contains embedded program files, which are not accepted")
            total = sum(i.file_size for i in z.infolist())
            if total > 20 * MAX_BYTES:
                problems.append("the document expands to an unreasonable size (possible zip bomb)")
                return ""
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except zipfile.BadZipFile:
        problems.append("the .docx file is damaged")
        return ""
    return re.sub(r"<[^>]+>", " ", xml)


def _txt_checks(data: bytes, problems: List[str]) -> str:
    if b"\x00" in data:
        problems.append("the text file contains binary data")
        return ""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        problems.append("the text file is not UTF-8")
        return ""


def defender_scan(data: bytes, suffix: str) -> str:
    exe = next((p for p in DEFENDER if p.exists()), None) or shutil.which("MpCmdRun.exe")
    if not exe:
        return "not scanned (no malware scanner available)"
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / f"upload{suffix}"
        path.write_bytes(data)
        try:
            r = subprocess.run([str(exe), "-Scan", "-ScanType", "3", "-File", str(path), "-DisableRemediation"],
                               capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"not scanned ({error.__class__.__name__})"
    if r.returncode == 0:
        return "clean (Microsoft Defender)"
    if r.returncode == 2:
        return "THREAT FOUND (Microsoft Defender)"
    return f"not scanned (scanner exit code {r.returncode})"


def check_upload(file_name: str, data: bytes, scan: bool = True) -> UploadCheck:
    name = safe_file_name(file_name)
    suffix = Path(name).suffix.lower()
    res = UploadCheck(False, name, ADAPTER_FOR.get(suffix), hashlib.sha256(data or b"").hexdigest(), len(data or b""))
    if suffix not in ADAPTER_FOR:
        res.problems.append("only .pdf, .docx and .txt files are accepted")
        return res
    if not data:
        res.problems.append("the file is empty")
        return res
    if len(data) > MAX_BYTES:
        res.problems.append(f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
        return res
    text = {".pdf": _pdf_checks, ".docx": _docx_checks, ".txt": _txt_checks}[suffix](data, res.problems)
    if text:
        from src.safeguards import INJECTION
        hits = sorted({m.group(0).lower() for m in INJECTION.finditer(text)})
        if hits:
            res.warnings.append("instruction-like text found (" + ", ".join(hits[:5]) + "); such passages are withheld "
                                "from the model at answer time. Review before approving.")
    if scan and not res.problems:
        res.malware_scan = defender_scan(data, suffix)
        if res.malware_scan.startswith("THREAT"):
            res.problems.append("the malware scanner reported a threat")
    res.ok = not res.problems
    return res
