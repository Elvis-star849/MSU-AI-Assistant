import hashlib
import re
from pathlib import Path
from typing import List, Any

import pymupdf
from langchain_core.documents import Document
from langchain_community.document_loaders import TextLoader, CSVLoader
from langchain_community.document_loaders import Docx2txtLoader

# Folder holding the MSU source documents (yearbooks, regulations, etc.)
MSU_DOCS_DIR = r"C:\Users\donal\OneDrive\Desktop\RAG\msu docs"

# Pages with less text than this are treated as blank (covers, separators)
MIN_PAGE_CHARS = 30

# Characters in the MSU PDFs that should be normalised to plain equivalents
_CHAR_FIXES = {
    "\u2024": ".",   # one-dot leader used instead of full stop
    "\u2060": "",    # invisible word joiner
    "\u00a0": " ",   # non-breaking space
    "\u2010": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u25cf": "•", "\u25aa": "•",
}
_CHAR_TABLE = str.maketrans(_CHAR_FIXES)

# A line holding only a list marker: "•", "o", "-", "6.", "28A.", "2.1", "3.4.1.", "a.", "b)", "ii.", "(iv)", "(a)"
_LONE_MARKER_LINE = re.compile(
    r"^(•|o|-|\d{1,3}[A-Z]?\.(?:\d{1,3}\.?)*|[a-zA-Z][.)]|[ivxlc]{1,5}[.)]|\((?:[a-z]|[ivxlc]{1,5}|\d{1,2})\))\n(?=\S)",
    re.MULTILINE,
)


def source_label(file_name: str) -> str:
    """Short human-readable name for a source file, used in citations."""
    upper = file_name.upper()
    if upper.startswith("HUMANITIES"):
        return "MSU Humanities Yearbook"
    if upper.startswith("SCIENCES"):
        return "MSU Sciences Yearbook Vol. 2"
    return Path(file_name).stem


def clean_page_text(text: str) -> str:
    """Normalise characters, strip the leading printed page number, join lone list markers and tidy whitespace."""
    text = text.translate(_CHAR_TABLE)
    # Printed page number on its own first line, e.g. "146 \n"
    text = re.sub(r"^\s*\d{1,4}\s*\n", "", text, count=1)
    # Table-of-contents dot leaders: "Fees ............ 23" / "Fees ……… 23"
    text = re.sub(r"(?:\.\s*){4,}|…+", " ... ", text)
    # Trailing spaces on lines, then collapse runs of spaces and blank lines
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)
    # Join a lone bullet / list number onto the line it belongs to: "6.\nLEARNING" -> "6. LEARNING"
    text = _LONE_MARKER_LINE.sub(r"\1 ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _dedupe_key(text: str) -> str:
    normalised = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.md5(normalised.encode("utf-8")).hexdigest()


def load_pdf(pdf_file: Path) -> List[Document]:
    """Load a PDF page by page with PyMuPDF, returning cleaned Documents with citation metadata."""
    docs = []
    with pymupdf.open(pdf_file) as pdf:
        for page_index, page in enumerate(pdf):
            text = clean_page_text(page.get_text())
            if len(text) < MIN_PAGE_CHARS:
                continue
            docs.append(Document(
                page_content=text,
                metadata={
                    "source": source_label(pdf_file.name),
                    "file_name": pdf_file.name,
                    "page": page_index + 1,  # 1-based PDF page number
                },
            ))
    return docs


def load_all_documents(data_dir: str = MSU_DOCS_DIR, dedupe: bool = True) -> List[Any]:
    """
    Load all supported files from the data directory and convert to LangChain document structure.
    Supported: PDF, TXT, CSV, Word.
    When dedupe is True, pages whose text is identical to an already-loaded page
    (e.g. the university Act repeated in every yearbook) are kept only once.
    """
    data_path = Path(data_dir).resolve()
    print(f"[INFO] Data path: {data_path}")
    documents = []

    pdf_files = sorted(data_path.glob('**/*.pdf'))
    print(f"[INFO] Found {len(pdf_files)} PDF files")
    for pdf_file in pdf_files:
        try:
            loaded = load_pdf(pdf_file)
            print(f"[INFO] Loaded {len(loaded)} pages from {pdf_file.name}")
            documents.extend(loaded)
        except Exception as e:
            print(f"[ERROR] Failed to load PDF {pdf_file}: {e}")

    other_loaders = {"*.txt": TextLoader, "*.csv": CSVLoader, "*.docx": Docx2txtLoader}
    for pattern, loader_cls in other_loaders.items():
        for file in sorted(data_path.glob(f"**/{pattern}")):
            try:
                loaded = loader_cls(str(file)).load()
                for doc in loaded:
                    doc.metadata.update({"source": source_label(file.name), "file_name": file.name})
                print(f"[INFO] Loaded {len(loaded)} docs from {file.name}")
                documents.extend(loaded)
            except Exception as e:
                print(f"[ERROR] Failed to load {file}: {e}")

    if dedupe:
        seen = set()
        unique = []
        for doc in documents:
            key = _dedupe_key(doc.page_content)
            if key not in seen:
                seen.add(key)
                unique.append(doc)
        print(f"[INFO] Removed {len(documents) - len(unique)} duplicate pages")
        documents = unique

    print(f"[INFO] Total loaded documents: {len(documents)}")
    return documents


# Example usage
if __name__ == "__main__":
    docs = load_all_documents()
    print(f"Loaded {len(docs)} documents.")
    print("Example document:", docs[0] if docs else None)
