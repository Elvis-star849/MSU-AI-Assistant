# Stage 2 corrected edition (v2): 2026-10-13

These are corrected copies, stored in `RAG/msu docs/2027/`. The originals in `RAG/msu docs/2027/originals/` are unchanged, and each v2 file records the original's SHA-256 in `derived_from`. Nothing here has been indexed.

## Files

| File | Purpose |
|---|---|
| `msu docs/2027/MSU_2027_Intake_Corrected_v2.json` | Corrected intake advert, with 222 programme records and 4 information records |
| `msu docs/2027/2027_ROADMAP_RAG_Ready_v2.json` | Corrected 2027 road map, with 21 events and 4 semester summaries |
| `build_corrected.py` | Rebuilds both v2 files from the originals and the source PDFs. Output is identical on every run. |
| `validate_corrected.py` | 60 automated checks; writes `validation_report.{md,json}` |

Rebuild and validate:

```
cd MSU-AI-Assistant
python stage2/build_corrected.py      # PDFs default to data/source_pdfs/
python stage2/validate_corrected.py
```

## Source PDFs

| Document | Filename | SHA-256 |
|---|---|---|
| Intake advert | `MSU-AI-Assistant/data/source_pdfs/MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf` (37 pp.) | `c6c767189da07a9b5b0bfaca0aa8583eb2db68ebcb4c3b05ea6f09a6b8267c95` |
| Road map | `MSU-AI-Assistant/data/source_pdfs/2027 DRAFT ROADMAP fin (1).pdf` (1 p.) | `c9790a92ba690fcf02b77d9cbadd057f36c3be369e7997eecdbd52df9c6c3b75` |

## Intake changes

1. **MSU-JF2027-107 and -108: start date corrected from January 2027 to February 2027.** Updated in `commencement`, `commencement_basis` and the `COMMENCEMENT:` line of `rag_text`. On -099 and -100 the date was already February; only their `commencement_basis` was added.
2. **MSU-JF2027-133: list marker moved.** The "i." now starts the first entry requirement, in both the structured list and `rag_text`.
3. **Traceability.** A top-level `source` block holds the filename, SHA-256 and page count. Each record carries `source_document` (now the real filename, not `…ADVERT(1).pdf`) and `source_sha256`.
4. **Four new searchable records** in `information_records`. Each has `source_text` copied verbatim from the PDF, plus `source_page`, `facts` and `rag_text`:
   - INFO-01: how to apply (p. 1)
   - INFO-02: application fee (p. 36). Two separate passages, joined with ` [...] `.
   - INFO-03: bank accounts and deposit slip (p. 36)
   - INFO-04: enquiry contacts (p. 37)
5. **Verification metadata.** `verification_status` and `verification_note` are replaced by a `verification` object on every record:
   - `automated` (passed)
   - `visual_page_check`
   - `prior_check` (the old values, kept as history)
   - `human_approval` (**pending**)

   A top-level block records that the project owner accepted the audit report. Approval of the individual records is still pending.
6. **Same keys on every record.** Missing optional keys (`commencement`, `commencement_basis`, `application_channel`, `faculty_conditions_inherited`, `duration_by_mode`) were added as `null`. The redundant `duration_normalized: null` was removed from -037 and -146.

No other programme content changed. The validator compares every record with the original to confirm this.

## Road map changes

1. **Status.** The top-level `status` is `approved`, with `status_basis`: "Confirmed by the project owner on 2026-10-13 as the approved 2027 road map for this project. Not independently verified with the Registry." The source filename containing DRAFT is kept in `source.filename`.
2. **Events.** `dates_as_written` is replaced by three fields:
   - `dates`: the approved dates
   - `dates_in_source`: the dates exactly as printed in the PDF
   - `date_corrected`: true or false

   | Event | `dates_in_source` | `dates` |
   |---|---|---|
   | RM2027-11 Semester Break | 13/09/2026 - 17/09/2027 | 13/09/2027 - 17/09/2027 |
   | RM2027-13 Examinations | 01/11/2027 - 12/11/202 | 01/11/2027 - 12/11/2027 |

3. **Correction records.** `corrections_applied` now also has `event_id`, `dates_in_source` and `basis`.
4. **RAG text.** A `STATUS:` line was added to every event and every semester summary. A `DATE CORRECTION:` line was added for the two corrected dates.
5. **Source fields.** Every event and summary carries `source_document`, `source_sha256` and `source_page`.
