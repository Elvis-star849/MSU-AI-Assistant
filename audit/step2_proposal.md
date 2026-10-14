# Step 2 Proposal: Extract and Validate Both New PDFs

**Date:** 2026-10-12 · **Status:** proposal only, nothing implemented
**Inputs:** `msu docs\MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf`, `msu docs\2027 DRAFT ROADMAP fin (1).pdf`

The layout findings below come from read-only inspection: rendered page images, both libraries' table output, and a **throwaway prototype run in my scratch folder** (not in the project). The prototype's numbers are evidence about the layout. They are not results.

---

## Part A: Confirmations

### A1. Existing chunk IDs
- **The new index will be append-only.** `faiss_store_v3/` will start with records 0–10,731 copied **byte for byte** from `faiss_store_v2/chunks.jsonl` (text, page and heading). New chunks get IDs from 10,732 upwards.
- **The existing vectors will be reused, not re-embedded.** They will be read from `faiss_store_v2` with `reconstruct_n` and checked against v2's `vectors_checksum`. Only the new chunks are embedded, with the same pinned model revision (`bge-small-en-v1.5 @ 5c38ec7`). That turns a ~70-minute rebuild into minutes, and the yearbook part is provably unchanged.
- **The existing loader will not be used for v3.** The new file names make it unsafe: `load_all_documents()` sorts paths, so `2027 DRAFT ROADMAP…` would load **before** `HUMANITIES…` and `MSU JANUARY…` **between** the two yearbooks. That would renumber every chunk. v3 will use an explicit, ordered file list.
- **The running app is unaffected by the new PDFs.** It loads the saved index and never reads `msu docs`. However, the new PDFs mean that rebuilding `faiss_store` from the folder with the old code (notebook Stage 4, or `python -m src.vectorstore`) would **no longer reproduce** the frozen fingerprint. Those rebuild paths must not be run. A later step can record the yearbook file hashes so the baseline stays reproducible.
- The index work belongs to a later step. **Step 2 only extracts.**

### A2. Fingerprint validation
There are three levels of fingerprint:

| Level | What | When checked |
|---|---|---|
| **Source** | SHA-256 of each PDF, recorded in a source registry | Extraction refuses to run if a PDF's hash differs from the registry. A new roadmap version therefore needs a deliberate re-registration |
| **Extraction** | SHA-256 of the canonical JSON of the extracted records, plus the extractor version | Recorded in the extraction report. A re-run must reproduce it exactly (determinism check) |
| **Corpus** (later step) | The v3 manifest records `base_corpus_fingerprint` (must equal the frozen `sha256:545d…`, recomputed over records 0–10,731) plus the fingerprint of the new records | Checked at v3 load |

**Current source hashes:**
- Intake advert: `c6c76718…3695f3`
- Roadmap: `c9790a92…6c3b75`

The hard-coded `CORPUS_FINGERPRINT` in `src/evidence.py` stays untouched, and the app keeps using v2 until a later approved step.

### A3. Both PDFs are available for inspection: yes
| | Intake advert | Roadmap |
|---|---|---|
| Pages | 37, landscape A4 | 1, portrait A4 |
| Origin | Word for Microsoft 365, created 2026-10-12 | Word 2016, author "DEPUTY REGISTRAR", created 2026-10-06 |
| Text layer | Yes, with 0 replacement characters (no OCR needed) | Yes |
| Encrypted | No | No |
| Structure | One 3-column ruled table per page (pp. 1–36), plus a contact block on p. 37 | One 2-column ruled table (30 rows), plus an "NB" note |

### A4. The notebook
- **The original `msu_chatbot_pipeline.ipynb` will never be opened for writing.** Its SHA-256 (`130a2dbd…db78b2`) is recorded now and will be checked before and after every step.
- **A new notebook, `msu_chatbot_pipeline_v3.ipynb`, will be created in a later step**, not in Step 2. It will contain no extraction logic: it will import the Step 2 functions and display their results (see Part I).

---

## Part B: Layout findings

### Intake advert
1. **There are always three logical columns:** PROGRAMME/DURATION, ENTRY REQUIREMENTS and MODE OF ENTRY. After clustering vertical rules within 4 pt, every page has the same column boundaries: x ≈ 65, 256, 561 and 710.
2. **Word drew some cell borders 1 pt apart** (x = 65 versus 66, and 256 versus 257). Because of that, **both PyMuPDF and pdfplumber detect 4–5 columns** on pp. 4, 5, 33 and 36, and split one programme name over three "rows" (for example, Records and Archives Management on p. 4). Both libraries' automatic table output is therefore unsafe as-is.
3. **Faculty banners** are rows spanning the full width, in bold and centred. They often contain **red notes that state facts**:
   - "All programmes, unless indicated otherwise, commence in January 2027" (Education)
   - "commence in August 2027. Applications to be submitted online only" (Engineering, Medicine)
   - "'O' level Mathematics and English Language with B or better Required" (Law)

   **The Law banner sits in the middle column only** (p. 26), so it does not look like a full-width row. In total there are 11 banners (10 faculties plus the Graduate School of Business Leadership).
4. **Rows continue across page breaks.** The continuation row has an empty programme cell; examples are pp. 1→2 and 32→33.
5. **Some cells are merged:** for Biomedical Sciences (p. 26), the entry-requirements cell spans the Entry and Mode columns, and the programme has **no duration and no mode stated**.
6. **One programme can appear in several rows with different durations and modes.** For example, Industrial Sociology runs 4 years (conventional) and 3 years (weekend school). These are separate records, not duplicates.
7. **Other non-programme content:** an introduction paragraph on p. 1 (general requirement: five 'O' levels at grade C including English), and contacts on p. 37 (phone, WhatsApp, email).

### Roadmap
1. **Both libraries extract the same 30 × 2 table**, with no differences between them.
2. **The rows form a hierarchy:** track (main calendar, or FACULTY OF EDUCATION BLOCK RELEASE) → semester → activity. That gives **21 events**.
3. **The semester breaks are in italics.** A note says block release and weekend dates may vary, and the file name says **DRAFT**.
4. **There are two errors in the source document:**
   - Second Semester break: **`13/09/2026 - 17/09/2027`**. The start year is 2026, giving a span of more than a year; it is most likely 2027.
   - Second Semester examinations: **`01/11/2027 - 12/11/202`**. The year is cut short; block release has the same dates ending `12/11/2027`.
5. **Date formats vary:** `5/01/2027`, `3/09/2027`, hyphen versus en dash, and with or without spaces.

### What the throwaway prototype showed
I tried a simple geometric extraction in my scratch folder.
- **What worked:** 217 programme rows, 12 continuation rows merged, and 11 records spanning pages joined correctly.
- **What it got wrong:**
  - Only **7 of 11 banners** were recognised (Education, Engineering, Medicine and Law were missed). As a result, the LLB and Biomedical Sciences records were **wrongly assigned to the Graduate School**.
  - The merged Biomedical cell was **split across two columns**, with the Law banner glued into its entry text.
  - Words in banners came out in the wrong order ("…RESOURCES ('O' Level Maths…) MANAGEMENT").
  - Two note rows ("All programmes in the Faculty of…") were taken for programmes.

These are the specific failure types the design and validation below are built to catch.

---

## Part C: Comparing extraction methods

| Criterion | PyMuPDF 1.28.2 | pdfplumber 0.11.10 |
|---|---|---|
| Already in the project environment and recorded in the freeze | **Yes** | No (tested in an isolated scratch environment only) |
| Automatic table detection on these PDFs | Phantom columns on pp. 4, 5, 33, 36 | **Same phantom columns**, plus extra 1-column tables on 10 pages |
| Roadmap table | 30 × 2, correct | 30 × 2, identical |
| Word coordinates and ruling-line geometry | `get_text("words")`, `get_drawings()` | `extract_words()`, `.lines` / `.rects` |
| Font weight, italics and colour (needed for banners and breaks) | `get_text("dict")` span flags and colour | `chars` font name and colour |
| Speed (37 pages) | About 1 s | Several times slower |
| Matches the yearbook loader | Yes (`data_loader.py` uses PyMuPDF) | No |

**Recommendation: PyMuPDF, with geometry-driven extraction rather than its automatic table finder.**
- Column bands come from the clustered vertical rules, with a check that each page has exactly 4 boundaries.
- Row bands come from horizontal rules that cross the programme column.
- Words are assigned to a cell by their centre point.
- Spans with formatting are used to classify banners, notes and italics.

pdfplumber brings no accuracy gain, and adding it would be a new dependency. **No change to `requirements.txt` is needed.** The roadmap uses the same machinery: two columns, with PyMuPDF's table output as a cross-check.

---

## Part D: Extracting complete programme records

The extraction runs in this order:

1. **Page geometry.** Find the column boundaries per page. The page fails if it doesn't have 4 boundaries, which would mean the layout changed.
2. **Row bands.** Find horizontal rules spanning the programme column. For each band, record **which internal column boundaries are actually drawn** in it. A missing boundary means a **merged cell** (Biomedical: no rule at x ≈ 561, so the entry text spans columns 2–3).
3. **Classify each row:**
   - **Header:** "PROGRAMME/DURATION".
   - **Banner:** bold, centred text containing FACULTY / SCHOOL / GRADUATE SCHOOL, in a full-width row *or* in the middle column with the outer cells empty (the Law case). The banner gives `faculty` (the bold line, in reading order); red and remaining lines become `faculty_notes`.
   - **Note row:** a full-width row of non-bold text, attached to the current faculty as a note.
   - **Continuation:** an empty programme cell. Its text is appended to the previous record, including across page breaks, and the record's `pages` and per-page bounding boxes are extended.
   - **Programme:** everything else.
4. **Reading order inside a cell:** words are sorted by line (y) and then by x within the cell's band, never across cells.
5. **Parsing the fields.** The raw cell text is always kept.
   - `title` and `durations`: regex for `N years`, `1½ years`, `1 ½ years`, `N months`, `-3 years Visiting/ Weekend School` (a variant duration with its condition), and `(HEEE)`-style codes.
   - `modes`: split against a controlled vocabulary of campuses {Gweru, Zvishavane, Harare, Bulawayo, Kwekwe} × study modes {Conventional, Visiting, Weekend School, Weekend Class, Block Release}. Case is normalised ("Gweru conventional"). Any unknown text is kept and flagged. "Weekend Class" and "Weekend School" are **not** merged.
   - `entry_requirements`: kept as text. Labelled sub-pathways ("Mature Entry", "Special Entry", "Normal Entry") are detected as optional sub-fields, without rewriting the wording.
   - `faculty_notes`: inherited from the banner (commencement month, online-only applications, faculty-wide 'O'-level rules), because these apply to every programme beneath it.
6. **Document-level records:** `general_requirements` (the p. 1 introduction) and `contacts` (p. 37).

---

## Part E: Extracting roadmap events

1. Read the 30 rows (geometry method, cross-checked against PyMuPDF's table output; they must agree row for row).
2. Use a state machine to classify each row:
   - `track` banner: "FACULTY OF EDUCATION BLOCK RELEASE". The main calendar is the default track.
   - `semester` row: "First Semester" or "Second Semester", with an empty date cell.
   - Blank spacer rows are skipped.
   - Every other row is an **event**.
3. Parse the dates with a tolerant pattern: `d{1,2}/d{2}/d{2,4}`, with an optional range separator (`-` or `–`, spaces optional). The output fields are `start`, `end` (ISO dates), `date_text` (raw), and `kind` (`single` or `range`).
4. Capture the italic flag (semester break), the document status `draft`, the title "ROAD MAP: 2027" and the NB note (which becomes a document-level note).

---

## Part F: Detecting errors

| Check | Applies to | Rule | Example it catches |
|---|---|---|---|
| Layout drift | both | Exactly 4 column boundaries on each intake page (3 on the roadmap); a header row only on p. 1 | A future advert layout |
| **Word coverage** | both | Every word inside the table area is assigned to **exactly one** field; nothing dropped, nothing duplicated. Words outside tables must be in a known block (intro, page number, contacts, NB) | Lost or doubled text |
| **Merged cells** | intake | A row band with a missing internal rule gets `merged_cells=[1,2]`. A record then can't have text in the Mode column, and `modes` is set to null with an issue | Biomedical Sciences |
| **Merged rows** | intake | A programme cell containing two degree titles ("Bachelor… Bachelor…" or "Master… Master…") or two durations without a variant marker | Two programmes in one row |
| **Banner check** | intake | Exactly 11 banners, matched against a list of expected faculty and school names; every record has a faculty; the faculty sequence is in document order | The prototype's 7/11 |
| Missing fields | intake | A missing `durations` / `modes` / `entry_requirements` gives `null` plus an issue entry (`missing_duration`, …). **Never filled in by guessing** | Biomedical (no duration, no mode); "Master of Arts in M&E" |
| Unknown vocabulary | intake | Any mode text outside the controlled vocabulary is flagged | Typos, new campuses |
| Programme-like note rows | intake | Rows starting "All programmes…" are classified as notes, not programmes | The prototype's "All…" records |
| **Date validity** | roadmap | 4-digit year; year = 2027 (from the title); valid calendar date; `end ≥ start`; span ≤ 120 days; events in order within each semester | **`13/09/2026 - 17/09/2027`**, **`12/11/202`** |
| Library cross-check | roadmap | Geometry rows must match PyMuPDF table rows | Extraction bugs |
| Determinism | both | Two runs give an identical extraction fingerprint | Non-determinism |

**Policy for errors in the source documents:** the raw `date_text` is always kept. A flagged record carries `issues: [...]` and, where a correction is obvious, a `suggested` value **labelled as a suggestion**, never written into `start`/`end`. How the assistant should present these dates is **a decision for you** (see Part K).

---

## Part G: Example records (expected output; text verified on the page images)

**Normal programme, spanning two pages (pp. 1–2)**
```json
{
  "record_type": "programme",
  "record_id": "intake2027-p001-r04",
  "source": "MSU January/February 2027 Intake Advert",
  "faculty": "FACULTY OF AGRICULTURE, ENVIRONMENT AND NATURAL RESOURCES MANAGEMENT",
  "faculty_notes": ["'O' Level Maths required for all programmes"],
  "programme_raw": "Master of Science Degree in Applied Agricultural Economics - 2 years",
  "title": "Master of Science Degree in Applied Agricultural Economics",
  "durations": [{"value": "2 years", "condition": null}],
  "entry_requirements": "To be eligible for the programme, a candidate must normally be a holder of at least a lower second class (2.2) first degree in Agriculture, Agricultural Economics; Economics; or any other related programme from a recognized University.",
  "modes": [{"campus": "Gweru", "mode": "Block Release"}],
  "pages": [1, 2],
  "bboxes": {"1": ["x0", "y0", "x1", "y1"], "2": ["…"]},
  "merged_cells": [],
  "issues": []
}
```

**Variant duration (p. 5)**
```json
{
  "title": "Bachelor of Arts Honours Degree in Translation and Intercultural Communication",
  "durations": [{"value": "4 years", "condition": null},
                {"value": "3 years", "condition": "Visiting/ Weekend School"}],
  "modes": [{"campus": "Zvishavane", "mode": "Conventional"}, {"campus": "Zvishavane", "mode": "Visiting"},
            {"campus": "Bulawayo", "mode": "Weekend School"}, {"campus": "Bulawayo", "mode": "Conventional"}],
  "faculty": "FACULTY OF ARTS AND HUMANITIES", "pages": [5], "issues": []
}
```

**Merged cell with fields missing in the source (p. 26)**
```json
{
  "title": "Bachelor of Science in Biomedical Sciences",
  "faculty": "FACULTY OF MEDICINE AND HEALTH SCIENCES",
  "faculty_notes": ["'O' Level Mathematics is a Requirement",
                    "The programme commences in August 2027. Applications to be submitted online only."],
  "entry_requirements": "'A' Level Passes in Chemistry with an A and any two in Mathematics, Physics or Biology",
  "durations": null, "modes": null, "merged_cells": [1, 2], "pages": [26],
  "issues": ["missing_duration", "missing_modes", "merged_entry_mode_cell"]
}
```

**Roadmap event, normal**
```json
{"record_type": "event", "record_id": "roadmap2027-r06", "source": "MSU 2027 Academic Road Map (DRAFT)",
 "status": "draft", "track": "Main calendar", "semester": "First Semester",
 "activity": "Face to face tuition - First Quarter", "date_text": "23/02/2027 – 02/04/2027",
 "start": "2027-02-23", "end": "2027-04-02", "kind": "range", "italic": false, "issues": []}
```

**Roadmap events with errors in the source**
```json
{"semester": "Second Semester", "activity": "Semester Break", "date_text": "13/09/2026 - 17/09/2027",
 "start": "2026-09-13", "end": "2027-09-17", "italic": true,
 "issues": ["year_mismatch_start: 2026 vs document year 2027", "span_exceeds_120_days"],
 "suggested": {"start": "2027-09-13", "reason": "suggestion only; not applied"}}

{"semester": "Second Semester", "activity": "Examinations", "date_text": "01/11/2027 - 12/11/202",
 "start": "2027-11-01", "end": null,
 "issues": ["truncated_year_end: '202'"],
 "suggested": {"end": "2027-11-12", "reason": "block-release exams give 01/11/2027 - 12/11/2027; suggestion only"}}
```

---

## Part H: Files

**To create** (all new; nothing existing is changed):

| File | Purpose |
|---|---|
| `src/source_registry.py` | Registry of documents: file name, display label, document type, status (draft/final), issuer, SHA-256. Includes `verify_sources()` |
| `src/extract_common.py` | Shared geometry (column and row bands, ruling lines, merged-cell detection), span formatting, word-coverage accounting, date parsing |
| `src/extract_intake.py` | `extract_intake(pdf_path) -> ExtractionResult` (programme records, banners, notes, general requirements, contacts, issues, coverage) |
| `src/extract_roadmap.py` | `extract_roadmap(pdf_path) -> ExtractionResult` (events, document notes, issues) |
| `tests/test_extract_intake.py`, `tests/test_extract_roadmap.py` | `unittest` tests (the project's style): counts, banners, the specific records in Part G, merged-cell and continuation cases, date-error detection, determinism |
| `eval/stage8/run_extract.py` | Runs both extractors, checks source hashes and the frozen-file hashes before and after, and writes the artefacts below |
| `eval/stage8/make_verification_sheet.py` | Builds the side-by-side verification sheet (see Part I) |
| `eval/stage8/source_hashes.json` | Frozen source hashes for the two new PDFs, plus the yearbooks for reference |
| `eval/stage8/intake_records.json`, `roadmap_events.json` | Extracted records |
| `eval/stage8/extraction_report.json` | Counts, issues, coverage, extraction fingerprint, environment |
| `eval/stage8/verification_sheet.md` + `eval/stage8/verify/*.png` | Page crops next to the extracted fields, for manual checking |
| `eval/stage8/integrity_before.json`, `integrity_after.json` | Hashes of all frozen files, the original notebook and both indexes |

**To modify:** none. In particular, `src/data_loader.py`, `src/embedding.py`, `src/vectorstore.py`, `src/evidence.py`, `src/context.py`, `app.py`, `faiss_store*/`, `eval/stage5*`, `eval/stage6/`, `eval/stage7/`, `msu_chatbot_pipeline.ipynb` and `requirements.txt` all stay as they are. No commit and no push.

---

## Part I: Verifying against the original pages, and reuse in the notebook

**Verification:**
1. **Automatic checks:** all of Part F, run in the tests and in `run_extract.py`.
2. **Counts against a manual count.** Before running the extractor, I count programme rows per page from the rendered images and record that count in `source_hashes.json` as a reference. The extractor must match it per page, with zero difference allowed.
3. **Side-by-side sheet.** For each checked record, the sheet shows a PNG crop of the record's exact region on each page (PyMuPDF `get_pixmap(clip=bbox)`) next to the extracted JSON fields. The checked records are:
   - **all** records spanning pages,
   - **all** records with merged cells or issues,
   - the first record after each banner,
   - **20 records chosen at random** (seed recorded),
   - **all 21** roadmap events.

   You (and ChatGPT, if you like) mark each one ✔/✘.
4. **Acceptance:** zero errors in the sheet. Any ✘ means the extractor is fixed and the **whole** check runs again, not just the failed record.

**Reuse in the notebook (later step):** the extractors are pure functions with no printing and no file writes. `msu_chatbot_pipeline_v3.ipynb` will:
- run `from src.extract_intake import extract_intake`,
- display the records as a pandas table, list the issues, and show the page crops,
- **contain no copy of the extraction logic.**

The same `ExtractionResult` objects will feed the later chunking step (one "programme card" per record and one chunk per roadmap event or semester). The notebook, the tests and the index builder will therefore all use one implementation.

---

## Part J: Risks

| Risk | Mitigation |
|---|---|
| **The roadmap is a DRAFT;** dates may change | Hash-pinned source; `status: draft` on every event; re-extraction is a deliberate step; the answer should say "draft" (prompt decision later) |
| **Errors in the source** (2026 year, truncated year) | Raw text is always kept, with flags and labelled suggestions only; you decide how they are presented |
| Banner detection depends on formatting (bold, centred, red) | Exact 11-banner check against the expected list; fails loudly |
| Merged cells and records continuing across pages | Rule-presence detection per band; mandatory side-by-side check of every such record |
| Mode vocabulary drift ("Weekend Class") | Controlled vocabulary with flags; no silent merging |
| The new PDFs break reproducibility of the frozen baseline through the old loader | Never rebuild v1/v2 from the folder; v3 uses an explicit file list; yearbook hashes are recorded |
| The extraction fingerprint changes with the library version | PyMuPDF version recorded in the report; tests pin the expected records |
| Course-code false positives later (e.g. "HEEE", "ZIMSEC") | Out of scope for Step 2; noted for the indexing step (audit item 8) |

## Part K: Acceptance criteria for Step 2
1. Source hashes match the registry, and the frozen-file, index and original-notebook hashes are **identical before and after**.
2. **Intake:** programme counts match the manual per-page count exactly; **11/11** banners found; every record has a faculty; word coverage is 100% (each table word assigned exactly once); every missing or unparsed field is flagged with an issue (no silent gaps).
3. **Roadmap:** **21** events in 2 tracks × 2 semesters; geometry and table extraction agree on every row; **exactly 2** date issues (the two listed in Part B) and no false alarms.
4. The verification sheet has **zero ✘**.
5. Two runs give the same extraction fingerprint.
6. All 75 existing tests still pass, and the new tests pass.
7. `git status` shows only the new files listed in Part H.

**Decisions I need from you:**
1. **Source date errors:** keep the raw text, flag it, and show "suggested" values only as suggestions (my recommendation)? Or correct them in the records?
2. **Folder name** `eval/stage8/` for the artefacts?
3. **Notebook timing:** create `msu_chatbot_pipeline_v3.ipynb` after Step 2 is accepted (my recommendation), or during Step 2?

## Next action
Once you approve (with answers to the three decisions), I will implement Part H, run the extraction and the checks, produce the verification sheet, and **stop for your review**. I will not index, commit or push. The scratch prototype and the temporary pdfplumber environment stay outside the project and will be deleted.
