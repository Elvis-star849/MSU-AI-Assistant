# Stage 2 (repeat): review of the user-supplied JSON conversions

Date: 2026-10-13. Read-only review. No project files, indexes, frozen evaluations, notebooks, prompts or the app were modified.

## Inputs

| File | Location | Notes |
|---|---|---|
| `MSU_2027_Intake_Corrected.json` | `RAG/msu docs/` | 222 programme records, 11 faculties, edition "2026-10-13 source-aware canonical ingestion edition" |
| `2027_ROADMAP_RAG_Ready.json` | `RAG/msu docs/` | 21 events + 4 semester summaries |
| Intake PDF (reference) | `RAG/unrelated/New folder (2)/MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf` | SHA-256 `c6c76718…` (unchanged from Step 1) |
| Roadmap PDF (reference) | `Downloads/2027 DRAFT ROADMAP fin (1).pdf` | SHA-256 `c9790a92…` (unchanged from Step 1) |

Both PDFs have been moved out of `msu docs`. That folder now holds only the two yearbook PDFs and the two JSON files. The existing loader globs only `**/*.pdf`, so the frozen corpus fingerprint is reproducible from that folder again (the Step 1 blocker no longer applies).

## Method

1. **Word coverage:** for each PDF page, compare the bag of words against the JSON records for that page, with a ±1 page window for rows that cross a page break.
2. **Row attribution:** geometry-based row bands (horizontal rules) and columns (x = 65/256/561/710). Each record is matched to its PDF row, and its requirement and mode words are compared cell by cell.
3. **Visual check:** every page flagged in step 2 (pp. 20, 21, 22, 23, 26, 27, 29, 34) was rendered and read.
4. **Roadmap:** all 21 events compared against the PDF text layer.

## Results: intake

| Check | Result |
|---|---|
| JSON words that do not exist anywhere in the PDF | **0** (nothing invented) |
| PDF table words missing from the JSON | **0** (only page numbers and the "Undergraduate/Postgraduate" heading on p.1) |
| Records with an unmatched or duplicated PDF row | 0 |
| Shared merged cell (p.20, 8 × M.Ed.) copied to every record | Correct |
| Rows crossing a page break (e.g. HEEE p.21→22, Telecom p.26→27, MSc IR p.34→35) | Joined correctly |
| Biomedical Sciences: no duration, no mode | Correct ("Not stated in the advert", `modes_of_entry: []`) |
| Faculty banners → `faculty_note`, online-only, August 2027 | Correct for all 11 faculties |
| Other flags raised by the automated checker | All explained by banners, merged cells or repeated titles, and confirmed correct by eye |

### Defects found

| # | Record(s) | Severity | Finding |
|---|---|---|---|
| D1 | MSU-JF2027-107, -108 (p.18) | **High** (wrong answer) | PDF says "Gweru Conventional (commences February 2027)". The mode note was captured, but `commencement` is "January 2027" and the rag_text says `COMMENCEMENT: January 2027`. The same fix that was applied to -099/-100 was not applied here. Should be "February 2027". |
| D2 | MSU-JF2027-133 (p.23) | Low | List marker out of place: `"…Ordinary Level including i."` / `"Mathematics, English…"`. The "i." belongs at the start of the first item. |
| D3 | -128, -130, -131, -133 | Cosmetic | The last list item "Attach proof of employment…" lost its numbering (PDF shows "iv." on -128 only; the others are unnumbered in the PDF too). No action needed. |
| D4 | All records | Low | `source_document` says `…INTAKE ADVERT(1).pdf`, but the file is `…INTAKE ADVERT.pdf`, and no SHA-256 is recorded. Add `source_sha256` so the Step 1 registry can bind the JSON to the PDF. |
| D5 | -021, -041, -069 | Info | Mode variants "Harare Weekend Class", "Bulawayo Weekend" and campus-less "Block Release" are faithful to the PDF and flagged properly (-041 has a note). Keep as is. |
| D6 | Top-level | Medium (retrieval) | `how_to_apply`, the fees, the bank accounts and `enquiries` (p.1 intro and p.37 contacts) exist only as top-level fields with no `rag_text`. If ingestion indexes only per-record `rag_text`, questions like "What is the application fee?" will find nothing. They need their own records. |
| D7 | `verification_status` | Process | 217/222 records are self-labelled `not_individually_verified`. This review now covers all 222 by word coverage and row attribution. Only D1 and D2 need fixing. |

## Results: roadmap

| Check | Result |
|---|---|
| Events | 21/21 present, correct calendar, semester, activity and order |
| Dates (19 unchanged events) | All match the PDF exactly; ISO start/end correct |
| RM2027-11 Semester Break | PDF: `13/09/2026 - 17/09/2027` → JSON: `13/09/2027 - 17/09/2027` |
| RM2027-13 Examinations | PDF: `01/11/2027 - 12/11/202` → JSON: `01/11/2027 - 12/11/2027` |

### Defects found

| # | Severity | Finding |
|---|---|---|
| R1 | Medium (traceability) | `dates_as_written` on RM2027-11 and -13 holds the **corrected** text, not what is written. The original text survives nowhere in the file (`corrections_applied` records only the new value). Add `dates_in_source` (raw) and keep the corrected value in `dates_as_written`/ISO fields, or rename. |
| R2 | Medium | No draft status anywhere. The source file is named "2027 DRAFT ROADMAP". Add `"status": "draft"` at the top level and a line in each `rag_text` so the assistant can say the dates are provisional. |
| R3 | Low | The corrections are reasonable inferences (all other dates are 2027) but are not confirmed by the Registry. Mark them as `"correction_basis": "inferred"`. |
| R4 | Info | Each event appears twice for retrieval (event record + semester summary). That is fine, but expect duplicate hits in the top 5. Stage 3 should decide whether to index one or both. |

## Verdict

- **Intake: accept after fixing D1 (required) and D2, and adding D4 and D6.** The conversion is otherwise accurate and complete: no lost, invented or misattributed text was found across all 222 records.
- **Roadmap: accept after R1 and R2.** The content is correct, but the provenance of the two corrected dates and the draft status must be preserved.

## Integrity

- `msu_chatbot_pipeline.ipynb` SHA-256 is unchanged (`130a2dbd…`).
- `git status` in MSU-AI-Assistant is clean.
- Review scripts live only in the session scratchpad (`review/cover.py`, `review/attr.py`).
