# Stage 3.3 report: registration, validation and dry run of the 2027 documents

Date: 2026-10-13. Script: `stage3/run_3_3.py`. Full results: `stage3/stage3_3_dry_run.json` (all checks, registry entries, token statistics, near-duplicate lists, samples and per-passage traceability).

**Not done:**
- no embeddings (the engine ran with an embedder that raises if called; no `knowledge_base/embeddings/` folder exists);
- no staging or public version (only `0001` exists, and there is no `STAGING` pointer);
- `CURRENT` unchanged (same file hash, still `0001`);
- no change to the app, the frozen indexes, the evaluation files or the main notebook;
- nothing committed or pushed.

## 1. Result: 30/30 checks passed, 0 validation errors, 0 engine warnings

| Document | doc_id | Status now | Passages | Pages | Tokens max / median |
|---|---|---|---|---|---|
| MSU 2027 Road Map | `roadmap-2027` v1 | `validated`, with the owner's prior approval recorded | **21** events | all p. 1 (of 1) | 293 / 253 |
| MSU January/February 2027 Intake Advert | `intake-2027-jan-feb` v1 | `validated`, **not approved** | **226** (222 programmes + 4 information) | 1–37 (of 37) | 423 / 198 |
| **Total new** | | | **247** | | limit 512 |

### Why "validated" and not yet "staged" or "approved"

These are deliberate and match the approved design.
- **Staged:** in the engine, staging is the step that embeds the passages and builds the staging index, and this stage forbids both. The intake is therefore one step before staged: registered, validated, its passages frozen, invisible to all search and unapproved. It becomes `staged` in 3.4.
- **Approved:** an approval can only be applied after staging, so that it refers to exactly the tested passages. The owner's 2026-10-13 confirmation of the roadmap is recorded now as a structured `prior_approval` in its registry entry. In 3.4 it is applied as the formal approval once the roadmap is staged.

`prior_approval` is a new optional metadata field. It required a small engine change, described in §8.

## 2. Hashes and source traceability

| Item | SHA-256 | Matches |
|---|---|---|
| Road map source PDF `2027 DRAFT ROADMAP fin (1).pdf` | `c9790a92ba690fcf02b77d9cbadd057f36c3be369e7997eecdbd52df9c6c3b75` | Step 1 record; dataset `source.sha256`; every event's `source_sha256` |
| Intake source PDF `MSU JANUARY FEBRUARY 2027 INTAKE ADVERT.pdf` | `c6c767189da07a9b5b0bfaca0aa8583eb2db68ebcb4c3b05ea6f09a6b8267c95` | Step 1 record; dataset `source.sha256`; all 226 records' `source_sha256` |
| Road map dataset `2027_ROADMAP_RAG_Ready_v2.json` | `27f98ef3c0f4df82874f2db495dc7ca3fd4d3838ad396db004accb3d07f4ed17` | Stage 2 `validation_report.json` |
| Intake dataset `MSU_2027_Intake_Corrected_v2.json` | `a91f01d6c67f3f90e21d99f03408eed7d01a18d9dcd8def1ea3d76898a470cbc` | Stage 2 `validation_report.json` |

**Traceability:**
- All four files were copied into `knowledge_base/uploads/<sha256>/<original name>`, and the copies were re-hashed.
- The frozen passage files `knowledge_base/units/<doc>@v1.jsonl` match their registry hashes.
- Every passage records its record ID, page, source file name, unit type and future `passage_uid` (`stage3_3_dry_run.json → traceability`).
- The road map keeps its original **DRAFT** filename.

## 3. Validation results

| Check | Result |
|---|---|
| Record IDs | Road map RM2027-01…21 in order; intake in dataset order; **247 IDs and future `passage_uid`s unique** |
| Semester summaries | **Excluded.** RM2027-S1…S4 are not among the passages; `excluded_units` records 4 IDs and the reason |
| Page references | Road map: 21 × p. 1 (the PDF has 1 page). Intake: every page within 1–37 and equal to the dataset's `source_page`; information records on pp. 1, 36, 36, 37 |
| Commencement (all 222 programmes) | Passage `COMMENCEMENT:` line = dataset field = the advert's rule: **February 2027: 4** (-099, -100, -107, -108); January 2027: 39 (Education default); August 2027: 21 (Engineering 20 + Biomedical Sciences 1); not stated: 158 (faculties whose banner gives no date) |
| Field completeness | Complete. The only gap is the one documented in Stage 2: **MSU-JF2027-146 Biomedical Sciences**, where the advert states no duration and no mode of entry, and the passage says "Not stated in the advert" |
| Road map corrections | RM2027-11 and RM2027-13 show the approved dates plus a `DATE CORRECTION:` line with the original PDF text. The registry `correction_history` equals the dataset's `corrections_applied` (event ID, dates in source, approved dates, basis) |
| Prior approval | actor `project-owner`, decision `approved`, decision date **2026-10-13**, registry verification **not performed**, evidence quoted |
| Token limit (real bge-small tokenizer, header + heading + body) | Max 423 (MSU-JF2027-058); 0 passages over 512 |
| Exact duplicates | None within the 247, and none against the 10,732 base passages |
| Course codes | None detected, so no new passage can switch questions to code-aware search |
| `kb.verify()` | OK, no warnings; journal has no open operations |

## 4. Near-duplicates: lexical dry-run method

Semantic near-duplicates (cosine ≥ 0.97) need embeddings, so they are computed automatically at staging in 3.4. This dry run used word-set overlap (Jaccard) on passage bodies.

| Comparison | Result |
|---|---|
| New passages vs the yearbook base (closest BM25 match for each) | Highest overlap **0.45**; **none ≥ 0.5**. No new passage repeats yearbook content. |
| Within the new passages (threshold 0.85) | **271 pairs:** 259 intake, 12 road map |

**What the within-document pairs are (warning, not an error).** They are genuinely different records that share most of their text. For example:
- MSU-JF2027-047 and -048: MA Museum Studies vs MA Archaeology, overlap 1.0 (only the programme title differs, and both names also appear in the shared requirement text);
- the 8 M.Ed. programmes on p. 20 that share one requirement cell (-118…-125);
- programme pairs that differ only in mode or duration (for example -009 and -010);
- Education Block Release road map events vs the main-calendar events with the same dates.

These are correct as data. The risk is that several near-identical records **crowd the top 5** for a question about one of them. The heading (faculty › programme) and the reranker should separate them; this must be measured in Stage 4 as planned. The full top-25 list is in `stage3_3_dry_run.json → near_duplicates_lexical`.

## 5. Samples

Shortened; full text in the JSON.

| passage_uid | Page | Tokens | Heading |
|---|---|---|---|
| `roadmap-2027/v1/RM2027-01` | 1 | 231 | Section: Main academic calendar > First Semester > Commencement of Registration |
| `roadmap-2027/v1/RM2027-11` | 1 | 293 | Section: Main academic calendar > Second Semester > Semester Break |
| `roadmap-2027/v1/RM2027-13` | 1 | 274 | Section: Main academic calendar > Second Semester > Examinations |
| `intake-2027-jan-feb/v1/MSU-JF2027-107` | 18 | 184 | Section: Faculty of Education > Bachelor of Education Honours Degree in Science and Applied Technologies |
| `intake-2027-jan-feb/v1/MSU-JF2027-146` | 26 | 203 | Section: Faculty of Medicine and Health Sciences > Bachelor of Science in Biomedical Sciences |
| `intake-2027-jan-feb/v1/MSU-JF2027-INFO-02` | 36 | 101 | Section: application_fee |

Example passage (RM2027-11):

```
[MSU 2027 Road Map, p. 1]
DOCUMENT: Midlands State University – Road Map 2027 (Deputy Registrar, Academic Affairs)
CALENDAR: Main academic calendar – Official dates for the commencement of semesters.
SEMESTER: Second Semester
ACTIVITY: Semester Break
DATES: 13/09/2027 - 17/09/2027
DATE CORRECTION: The source PDF prints 13/09/2026 - 17/09/2027; the approved date is 13/09/2027 - 17/09/2027.
STATUS: Approved 2027 road map for this project.
…
```

## 6. Unresolved warnings and findings (for review before 3.4)

| # | Finding | Effect | Proposal |
|---|---|---|---|
| W1 | 271 lexical near-duplicate pairs within the new documents (§4) | Possible crowding of the top 5 | Measure in Stage 4 (crowding metric); no data change |
| W2 | **The four information-record headings use the dataset's snake-case topic** (`Section: application_fee`, `fee_payment_banking_details`, …) | Weaker heading signal for embedding and reranking of the fee, bank and contact passages (their body text is still clear) | Before staging, give them readable headings ("Application fee", "Bank accounts for the application fee", …) through an adapter option such as `heading_labels`; needs F1 |
| F1 | **Engine gap:** a registered document's metadata (for example `adapter_options`) can't be corrected before staging. Registering the same file again is a no-op even after the old entry is rejected, so the only route is a changed file. | Blocks fixing W2 cleanly | Add a journaled `update_metadata(doc_id, version, changes, actor)`, allowed only in `uploaded` or `validated`, which resets the status to `uploaded` so validation must be re-run. Or allow a new version when the earlier version with the same SHA-256 was rejected. Small, with tests. |
| W3 | 158 programmes have no commencement date | Correct: the advert states none for those faculties | None; the assistant should say "not stated" |
| W4 | MSU-JF2027-146 has no duration or mode of entry | Correct, documented in Stage 2 | None |

## 7. Required safety task before Stage 3.4: registry-aware rollback

Stage 3.4 will create the first public version that contains a non-base document. From then on, a rollback can make the registry and the public index disagree. The next `publish`, `withdraw` or `supersede` would then **silently restore** content that was rolled back. Details and the proposed design are in `stage3_2_report.md §7`.

**Required before 3.4. It is not implemented, pending your separate approval.**
1. New status `suspended`, with transitions `published → suspended`, `suspended → published` (re-publish with approval) and `suspended → withdrawn`.
2. `rollback` sets every published document missing from the target version to `suspended`, in the same journaled, crash-recoverable operation. It refuses to make a withdrawn or superseded document visible again without an explicit, recorded approval.
3. An emergency pointer-only rollback stays available, but it sets an `active_override` that **blocks** publish, withdraw and supersede until `kb reconcile` resolves each difference.
4. `verify()` treats any difference between `CURRENT` and the registry's published set as an **error**.
5. Tests: each path, plus a crash at each step.

I recommend approving the rollback task together with F1 (and W2 if you want readable headings) as a short **Stage 3.3b** before 3.4.

## 8. Code changed in this stage

`src/kb/service.py` gained an optional `prior_approval` metadata field:
- it must contain `actor`, `decision`, `decision_date` and `basis`;
- it is stored as evidence only and does not change the status.

`tests/test_kb_service.py` gained two tests for it (`TestPriorApproval`). These two files were new in Stage 3.1. No protected or pre-existing file changed.

## 9. Tests and integrity

- `python -m unittest discover -s tests -t .`: **154 tests OK** (75 original + 79 knowledge-base tests), 59 s.
- `python stage3/integrity.py after`: **PASS**. 0 of 143 protected files changed or missing; git HEAD `eb9ccff`; the only new files in protected folders are the 23 Stage 3.1 code and test files.

## 10. Files created or changed

| Path | Notes |
|---|---|
| `stage3/run_3_3.py` | New: registration, validation and dry-run script |
| `stage3/stage3_3_dry_run.json` | New: full results |
| `stage3/stage3_3_report.md` | New: this report |
| `stage3/integrity_after.json` | Refreshed |
| `src/kb/service.py`, `tests/test_kb_service.py` | `prior_approval` (§8) |
| `audit/stage3_architecture_proposal.md` | Adds the Stage 3.3b safety task to the sequence |
| `knowledge_base/registry.json` | + `roadmap-2027` v1 and `intake-2027-jan-feb` v1, both `validated` |
| `knowledge_base/uploads/<sha256>/…` | 4 files: 2 datasets, 2 source PDFs |
| `knowledge_base/units/roadmap-2027@v1.jsonl`, `intake-2027-jan-feb@v1.jsonl` | Frozen passages |
| `knowledge_base/validation/roadmap-2027@v1.json`, `intake-2027-jan-feb@v1.json` | Engine validation reports |
| `knowledge_base/ingest_log.jsonl` | + 4 operations (2 registrations, 2 validations), all committed |

`knowledge_base/` is now 30 MB and is still untracked by git.
