# MSU AI Assistant: Architecture Audit (read-only)

**Date:** 2026-10-12
**Scope:** `RAG\MSU-AI-Assistant` (git HEAD `eb9ccff`). The two other projects under `RAG\` are summarised in §9.
**Method:** I read every module in `src/`, `app.py`, the index manifests, the build and evaluation scripts, the freeze records and all notebooks. I re-hashed the frozen files and ran the test suite. No project files were changed, and `git status` is clean after the audit.
**Purpose:** to show what has to change, and what must stay untouched, before more documents can be added.

---

## 1. Summary

The system is a carefully frozen two-document RAG pipeline: PyMuPDF pages are split into 800-character chunks, embedded with bge-small, and searched through FAISS plus BM25 with code-aware routing. A heading-aware index is reranked with MiniLM, and the top 5 passages go to a grounded prompt answered by Groq `gpt-oss-20b`.

The engineering is solid: every stage has fingerprints, hash-locked baselines, a held-out evaluation and 75 passing tests.

**The design assumes exactly two yearbooks.** Adding documents is not a drop-in change. The corpus fingerprint is hard-coded, so the app will refuse to load a rebuilt index. Chunk IDs are global positions, so new files can renumber every chunk. Source labels, heading rules, course-code detection and the frozen prompt are all yearbook-specific. A full rebuild needs about 34 minutes of CPU embedding for each index. All frozen evaluation records belong to the current corpus fingerprint.

---

## 2. Pipeline

```
msu docs/*.pdf
  │  src/data_loader.py      PyMuPDF page text → clean_page_text() → drop pages < 30 chars → exact-page MD5 dedupe
  ▼
page Documents {source, file_name, page}
  │  src/embedding.py        RecursiveCharacterTextSplitter(800, overlap 150, ["\n\n","\n",". "," ",""])
  │                          chunk_id = global position; prepend "[<source>, p. N]" header
  ▼
faiss_store/   (Stage 4, frozen)   bge-small-en-v1.5, normalised, IndexFlatIP + BM25Okapi (rebuilt at load)
  │  src/structure.py + src/heading_store.py   adds "Section: PART > section > sub" heading per chunk
  ▼
faiss_store_v2/ (S6-3, used by the app)  same chunks/IDs; embeds header + heading + body; BM25 on heading + body
  │  src/retrieval_v2.routed_search   course code in query? → code-filtered hybrid RRF (k=60, 50/50 candidates,
  │                                   T1 = vector-rank tie-break) : vector-only
  │  src/rerank.py           MiniLM-L-6 cross-encoder over top 10 (heading + passage) → top 5
  │  src/evidence.py         Stage6Retriever("main"); checks the hard-coded CORPUS_FINGERPRINT
  ▼
src/context.py   prompt s7-0-baseline-v1 (numbered evidence: source, page, heading, text; no scores)
src/answer.py → src/llm/ (provider-independent; Groq client; temp 0, reasoning medium, 4096 tokens, 2 retries)
src/assistant.py   statuses, friendly errors, ambiguity notes (display only), offline mode
src/conversation.py  rule-based follow-up rewriting, in-memory chats
app.py             Streamlit UI, HF_HUB_OFFLINE=1, @cache_resource load (~1 min)
```

---

## 3. Components

### 3.1 PDF loading (`src/data_loader.py`)
- `MSU_DOCS_DIR` is a **hard-coded absolute path** (`C:\Users\donal\OneDrive\Desktop\RAG\msu docs`). The loader picks up every `**/*.pdf` recursively, plus `*.txt`, `*.csv` and `*.docx`.
- PDFs are read page by page with PyMuPDF, and the stored `page` is the 1-based PDF page. Cleaning normalises characters, removes the printed page number on the first line, collapses dot leaders and joins list markers to their text.
- **`source_label()` only recognises file names starting with `HUMANITIES` or `SCIENCES`.** Any other file is labelled with its raw file stem, and that label is what users see in citations.
- **Dedupe:** an MD5 of whitespace-normalised, lower-cased page text, keeping the first occurrence in **sorted file-path order**. As a result, the Sciences volume contributes 1,029 of its 1,132 pages; the rest are blank pages or duplicates of Humanities pages. Shared front matter such as the Act and General Regulations is indexed **only under the Humanities label**.
- Non-PDF loaders set no `page`. Those chunks get a `[source]` header with no page, and the UI shows the PDF page as `None`. `Docx2txtLoader` needs the `docx2txt` package, which is **not in `requirements.txt`**. Markdown files are not loaded at all.
- No OCR. Scanned PDFs would produce empty pages, which are silently dropped by the 30-character check.

### 3.2 Chunking and embeddings (`src/embedding.py`)
- Chunks are 800 characters with 150 overlap; the choice is justified in the notebook (90% of paragraphs are ≤ about 620 characters). In the current index the median chunk is 662 characters, the 95th percentile 826 and the maximum 839.
- Each chunk gets a citation header, and `chunk_id` is the chunk's position in the whole corpus.
- The embedding model is `BAAI/bge-small-en-v1.5` (384 dimensions, normalised) with a query prefix. Embedding runs on CPU, and **a full corpus takes about 33 minutes** according to the notebook.
- `langchain_text_splitters` is imported but only arrives as a dependency of `langchain`.

### 3.3 Indexes
| | `faiss_store/` (Stage 4 baseline) | `faiss_store_v2/` (app) |
|---|---|---|
| Chunks | 10,732 (Hum 5,614 / Sci 5,118) | same records + `heading` field |
| Embedded text | header + body | header + heading line + body |
| FAISS | `IndexFlatIP` (exact search, no incremental add) | same |
| BM25 | body only, rebuilt at load (~3 s) | heading + body |
| Built | notebook `msu_chatbot_pipeline.ipynb` Stage 4 | `eval/stage6/build_s6_3_index.py`, 2,023 s |
| Integrity checks | config, counts, dimension, record fields, chunk-ID order, corpus fingerprint, vector checksum | plus heading fingerprint and `structure_version` |

- **v2 is built from v1's `chunks.jsonl`, not from the PDFs.** A new corpus therefore needs both builds, which means two full embedding passes (about 70 minutes).
- `build_s6_3_index.py` **asserts that the baseline hashes are unchanged and that the corpus fingerprint equals the frozen one**, so by design it cannot build a new corpus.
- 10,695 of 10,732 chunks have a heading.

### 3.4 Retrieval (`retrieval_v2.py`, `rerank.py`, `evidence.py`)
- **Routing:** a query mentioning a course code that exists in the index (regex `[A-Za-z]{2,6}\s?\d{3}`; uppercase-only on the corpus side) goes to hybrid RRF restricted to chunks containing that code. All other queries use vector search only, because BM25 fusion hurt natural-language questions in Stage 4.
- **Reranking:** MiniLM reranks the top 10 using the heading plus the passage, and the best 5 become evidence. There is also a fallback configuration (v1 index, no reranker), but the app never uses it.
- **`evidence.py` hard-codes `CORPUS_FINGERPRINT`.** Any rebuilt corpus fails `load()` and the app will not start.
- There is no relevance threshold. Vector search always returns 5 results, so `NO_EVIDENCE_MESSAGE` is effectively unreachable for natural-language questions. Out-of-scope handling relies entirely on the prompt (R2 in `stage7_requirements.md`, still open).

### 3.5 Generation and UI
- The prompt `s7-0-baseline-v1` is frozen and hash-recorded in S7-1. **Its wording names "the MSU yearbooks"**, and so do `NO_EVIDENCE_MESSAGE` and the UI text.
- The LLM layer is clean and provider-independent: API keys are never logged, provider errors are mapped to friendly categories, and reasoning output is excluded. Only Groq models `openai/gpt-oss-20b` and `-120b` are allowed.
- Course-code ambiguity metadata (`ambiguity.py`) is rebuilt from all records at startup and shown in the UI only. It is not passed to the prompt yet (S7-4 has not been evaluated).
- Follow-up questions are rewritten by rules using only the user's earlier questions; earlier answers are never used as evidence.

---

## 4. Frozen evaluation records (verified)

| Record | Content | Status |
|---|---|---|
| `eval/stage5_*` | 35 development questions (10 natural language, 10 exact code, 10 code in context, 5 out of scope), runs, 0/1/2 chunk grades, failures, spot check | **All 9 files match `baseline_hashes.json`** |
| `eval/stage6/holdout_questions.json` | 35 held-out questions, seed 20261009, frozen 2026-10-07 (read-only file attribute) | matches |
| `eval/stage6/s6_6_*` | Final held-out comparison. Arm 0 (Stage 4 baseline): Top-1 16/30, Top-5 28, MRR@10 0.702. **Arm 3 (accepted): Top-1 25/30, Top-3 28, Top-5 28, MRR@10 0.883** | **All 32 hashes in `s6_6_freeze.json` match** |
| `eval/stage7/s7_1_*` | Prompt experiment with 30 questions and 3 arms, blind grading. Arm 0 (baseline prompt) kept: correctness 30/30, groundedness 29/30, 0 hallucinations | freeze recorded; integrity snapshots up to `before_commit` (2026-10-09) |
| Tests | `python -m unittest discover -s tests -t .` | **75 tests, all pass** (12 s). `pytest` is not installed in this interpreter |

Grades are keyed by **chunk ID and corpus fingerprint**. Every one of these records describes the current two-yearbook corpus only.

---

## 5. Notebooks

| Notebook | Role |
|---|---|
| `msu_chatbot_pipeline.ipynb` | **The reference notebook** for Stages 1–4 (load, clean, chunk, embed, build and verify `faiss_store`, routed retrieval). It builds the index only if `faiss_store/` is missing |
| `1-rag_evaluation.ipynb` | LangSmith / OpenAI evaluation tutorial; not used for the MSU corpus |
| `agenticrag/1-agenticrag.ipynb`, `typesense.ipynb`, `PageIndex_…ipynb`, `notebook/document.ipynb`, `notebook/pdf_loader.ipynb` | Tutorials (LangGraph, Typesense, PageIndex, Chroma) that use `../data` or external APIs; **not connected to the MSU system** |

---

## 6. What blocks adding documents

| # | Issue | Where | Effect |
|---|---|---|---|
| 1 | Hard-coded corpus fingerprint | `src/evidence.py:13` | The app refuses any rebuilt index |
| 2 | v2 build script asserts the frozen corpus | `eval/stage6/build_s6_3_index.py` | A new script is needed; the old one must stay as the record |
| 3 | `chunk_id` is a global position, and files load in sorted path order | `embedding.py`, `data_loader.py` | A file sorting before `HUMANITIES…` (e.g. `ACADEMIC…pdf`) renumbers every existing chunk. Files sorting after `SCIENCES…`, or loaded explicitly after the yearbooks, keep IDs 0–10,731 unchanged |
| 4 | Dedupe keeps whichever copy loads first | `data_loader.py` | A new document repeating yearbook pages could take over those pages and change their citations |
| 5 | `source_label()` only knows two prefixes | `data_loader.py:35` | New sources are cited by raw file name |
| 6 | Non-PDF files have no page or section metadata; `.md` isn't loaded; `docx2txt` is missing | `data_loader.py` | Weak citations, or a loader crash for `.docx` |
| 7 | Heading rules are tuned to yearbooks | `structure.py` | Handbooks, notices and web pages will get few useful headings. They won't break, but they get less benefit |
| 8 | Course-code regex is broad | `vectorstore.py:48` | Capitalised tokens in new documents (`USD 450`, `ROOM 101`, `ZIMSEC 2025`, form numbers) become "codes" and force code-filtered routing for matching queries |
| 9 | The prompt and messages say "yearbooks" | `context.py`, `assistant.py`, `app.py` | Wording changes mean a new prompt version, which must be evaluated against s7-0 |
| 10 | Full rebuild only, about 34 minutes per index on CPU | FAISS `IndexFlatIP`, v2 built from v1 | About 70 minutes per corpus change. Exact search is still fine at this scale (~11k–30k vectors) |
| 11 | No out-of-scope threshold | `assistant.py` | More documents mean more near-miss passages; R2 is still open |
| 12 | The frozen evaluation only covers the yearbooks | `eval/` | New documents need their own questions. Yearbook results must be re-run on the new corpus to check for regressions |

---

## 7. Other observations

- **Dead or legacy code:** `src/search.py` uses the wrong index file names, a different embedding model, an empty Groq key and a broken `from data_loader import`. It is not imported anywhere.
- **Dependencies:** most packages are unpinned (only `python-dotenv`, `groq` and `streamlit` are pinned). `chromadb`, `typesense`, `langgraph` and `langchain_openai` are only used by the tutorials. The exact tested environment is recorded in `s6_6_freeze.json` (Python 3.12.3, torch 2.14.0+cpu, sentence-transformers 6.1.0, faiss 1.15.1).
- **Models** must already be in the Hugging Face cache, because the app sets `HF_HUB_OFFLINE=1`. Their hashes are checked in the Stage 7 integrity files.
- **Secrets:** `.env` exists locally, is Git-ignored and is not tracked. It was not opened during this audit.
- **Loose files:** `books.jsonl` and `bash.exe.stackdump` sit in the repository root. The stackdump is ignored; `books.jsonl` looks like tutorial data.
- **Note on the evaluation set in `RAG\eval\`:** because of the dedupe in §3.1, questions about shared front matter (Act, General Regulations, history) will be cited as **Humanities pages only**. Count a Humanities-only citation as correct for those questions.

---

## 8. Recommendations for the expansion (not implemented)

1. **Leave everything frozen as it is.** Build a new corpus version in `faiss_store_v3/` with its own manifest, plus a new build script.
2. **Load documents in an explicit order** (yearbooks first, then new documents) so chunk IDs 0–10,731 stay identical. That lets the existing grades be mapped across by ID and text.
3. **Replace `source_label()` with a document registry** (file → label, document type, year, authority) and store those fields in each record's metadata.
4. **Decide the dedupe policy per document** (for example, never let a new document take over a yearbook page) and record it in the manifest.
5. **Add page or section metadata for non-PDF formats**, add `.md` support and add `docx2txt` to the requirements, or convert everything to PDF or Markdown first.
6. **Tighten course-code detection,** for example by only treating codes found in module-title lines or programme tables as codes.
7. **Make the expected fingerprint configuration-driven** (read it from the active manifest, plus a recorded approval) instead of a constant in `evidence.py`.
8. **Re-evaluate:** run Stage 5 and the S6-6 held-out set on v3 as a regression check, and add a new question set for the new documents. If the wording changes, evaluate a new prompt version against s7-0.

---

## 9. Other projects under `RAG\`

| Project | Stack | Corpus | Relevance |
|---|---|---|---|
| `msu-assistant/` | Chroma, Ollama (`nomic-embed-text`, `llama3.2:3b`), router, language setting; config via environment variables; no git history | `knowledge_base/` with 33 files: **MSU student handbook PDF**, FAQ CSV, 3 sample `.md` files, scraped website `.md` pages | It already loads multiple formats, and its `knowledge_base/` contains likely **candidate documents** for the expansion |
| `New folder/msu-admissions-chatbot/` | FastAPI and a JavaScript widget; FAQ plus page-section matching; optional OpenAI-compatible LLM | `data/pages.json` (scraped msu.ac.zw admissions pages), `data/faq.json` | Another source of web content and FAQs; separate system |
