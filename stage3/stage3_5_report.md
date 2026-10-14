# Stage 3.5 report: final verification, Stage 4 handoff, retention and Git strategy

Date: 2026-10-13. Verification script: `stage3/run_3_5.py`. Results: `stage3/stage3_5_results.json`. Handoff: `stage3/stage4_handoff/`.

**Not done:**
- no Stage 4, Stage 5 or Django work;
- no change to the app, which still runs on `faiss_store_v2`;
- no change to frozen artefacts, `.gitignore` or the archived versions (nothing deleted or pruned);
- nothing committed or pushed.

**The real knowledge base was not written by Stage 3.5:** every file was re-hashed before and after and is identical. All write tests ran on a temporary copy.

**Result: 23/23 verification checks passed. 184/184 tests passed. Integrity: PASS. App check: PASS.** There were no failures and no deviations.

## 1. End-to-end verification

| Area | Result |
|---|---|
| **Registry** | 4 documents: yearbook-humanities and yearbook-sciences-v2 `published` (frozen base), `roadmap-2027` `published` (1 formal approval), `intake-2027-jan-feb` **`staged`, no knowledge-base approval** |
| **Approval metadata** | Road map: *officially approved university document*, with the two corrected dates as the approved dates, the DRAFT filename kept, the original-source correction history kept, and "no signatory or reference provided". Intake: *officially approved university source document*; publication approval is separate and pending. No "not verified / not obtained" wording in the current metadata. |
| **Provenance** | Datasets, source PDFs, frozen units and validation and staging reports all match their recorded SHA-256. Each source PDF equals the copy in `data/source_pdfs` and the Step 1 hash. |
| **Journal** | 38 entries, 19 operations (seed 1, register 2, validate 6, metadata update 4, stage 2, approve 1, publish 2, refresh staging 1). **All committed**: no open operations, no aborts, no torn lines. Every committed version exists. |
| **Pointers** | `CURRENT` = **0005** (public, **10,753** passages); `STAGING` = **0006** (staging, **10,979** passages); both manifest hashes match |
| **All versions** | 0001, 0005, 0006 (active) and 0002–0004 (archive): **all 6 pass full verification** |
| **Frozen base** | In 0001, 0005 and 0006, the 10,732 yearbook records are **byte-identical** (CRLF included) and their vectors **bit-identical** (`numpy.array_equal`) to `faiss_store_v2`; fingerprints `545d…` / `7ce5…` / `4a4a…`. No yearbook passage was re-embedded at any stage. |
| **Intake isolation** | The public version has no intake rows in the identifier map, the chunk records, the registry snapshot or the manifest. Its FAISS index has exactly 10,753 rows and its BM25 corpus 10,753 documents; intake-only terms score 0; the course-code map equals v2. Staging holds all 226 intake passages. |
| **Embedding cache** | 247 vectors for revision `5c38ec7c…`, **bit-identical to staging rows 10,732–10,978**; `missing()` reports nothing to embed |
| **Reuse without the model** | The embedder was replaced by one that raises if called. **After a restart, `refresh_staging` and `publish` were no-ops**, and a **forced full rebuild of the staging content from the cache alone produced files byte-identical to 0006** (chunks, passages, index, registry snapshot; same content signature), in 9.1 s |
| **Rollback safeguards (copy)** | Normal rollback to 0001 suspends the road map; publish does not resurrect it; rolling forward restores it. An emergency rollback blocks publish (`OverrideActive`), is reported by `verify()`, and `restore_registry` reconciles. A withdrawn document cannot be reinstated by rollback without an explicit approval (`ReinstatementRequired`), and nothing changes. |
| **`kb.verify()`** (real KB) | OK: 0 problems, 0 warnings, no override (10.5 s) |

### Application unchanged

- **Configuration:** `src/evidence.py` `CONFIGURATIONS["main"]["index"]` is still `faiss_store_v2`.
- **Offline app check:** `Assistant.create(offline=True)` uses `faiss_store_v2` (10,732 records), so a 2027 road map question returns only yearbook passages, as expected before Stage 5.
- **Streamlit:** started headless; health 200 and page 200; stopped afterwards.

## 2. Tests and integrity

- `python -m unittest discover -s tests -t .`: **184 tests OK** (91 s).
- `python stage3/integrity.py after`: **PASS**.
  - 0 of 143 protected files changed or missing;
  - git HEAD `eb9ccff` unchanged;
  - the new files in protected folders are the 24 knowledge-base code and test files.

## 3. Stage 4 evaluation handoff

| File | Contents |
|---|---|
| `stage3/stage4_handoff/stage4_evaluation_plan.md` | Proposed plan: systems, metrics, procedure, constraints |
| `stage3/stage4_handoff/stage4_questions_draft.json` | **Draft** question set (built from the registered data by the script below) |
| `stage3/stage4_handoff/build_stage4_questions.py` | Rebuilds the draft; expected facts, record IDs and pages are read from the datasets |

**Question sets (draft, for your review and freezing):**
- **Regression:** the 35 frozen Stage 5 questions, referenced by SHA-256, plus 5 ambiguous-code queries.
- **Road map:** 13 questions (R01–R13), answerable in public and staging.
- **Intake:** 15 questions (I01–I15). They are answerable in staging only; in public the expected answer is "not in the available documents".
- **Out of scope:** 6 questions (X01–X06), including two near-domain traps: another university's fee, and 2028 dates.
- **Cross-document:** 2 questions (C01–C02), on fee refunds and the late fee, combining yearbook and intake.

All expected passages were checked to exist in staging 0006.

| Flagged case | Observation | Stage 4 check |
|---|---|---|
| **Campus gym** (X02 = O5) | `RM2027-02` enters the top 5 (public and staging) | still declined; no citation of the road map as support |
| **UK student visa** (X01 = O4) | `MSU-JF2027-INFO-01` enters the staging top 5 | still declined; no MSU application steps given as visa advice |
| **Second-semester examinations** (R08) | `RM2027-21` (block release, same dates) ranks above `RM2027-13` | correct dates and correct calendar named |
| **Mining Engineering** (I10) | Two yearbook Mining passages rank above the intake records (rank 4) | 2027 advert requirements used and sources attributed correctly |

**Also covered:**
- **Grounding traps:**
  - R07 must give 13/09/**2027**, never 2026;
  - I08 must say the Biomedical duration is not stated;
  - I13 must say no start date is stated;
  - I05 must say February, not the January faculty default;
  - C02 must not use the intake fee as the late fee;
  - X06 must not reuse 2027 dates.
- **Crowding cases:** R05, R08, I10, I11 (8 M.Ed. records), I12 (-047/-048), I15 (-127/-128).
- **Source attribution:** each answerable question has its expected source label and page.

**Proposed procedure** (details in the plan):
1. Freeze the questions.
2. Retrieval-only run (no API calls).
3. Generation run with the frozen prompt (the number of Groq calls needs your approval).
4. Blind grading by you.
5. Go / no-go for Stage 5.

Stage 4 also measures the effect of the frozen prompt's "MSU yearbooks" wording; any prompt change is Stage 5.

## 4. Disk usage and a proposed staging-version retention policy

| Item | MB |
|---|---|
| `knowledge_base/` total | **170.1** |
| `store/versions/0001` (frozen base) | 27.5 |
| `store/versions/0005` (public, CURRENT) | 27.6 |
| `store/versions/0006` (staging, STAGING) | 28.2 |
| `archive/` (0002–0004: intermediate staging builds of this ingestion) | **84.0** |
| `embeddings/` | 0.4 |
| `uploads/` (2 datasets + 2 source PDFs) | 1.5 |
| `units/`, `validation/`, registry + journal | 0.6 / 0.05 / 0.3 |
| Reference: `faiss_store_v2` | 25.3 |

**Current behaviour:**
- The base plus the 10 newest public versions stay active (D4).
- **Every superseded staging version is moved to `archive/` and never deleted.** One ingestion of two documents produced 3 archived staging builds (84 MB). At about 28 MB per build and 3–4 builds per ingestion, `archive/` grows by about 100 MB per ingestion.

**Proposed policy (not implemented; nothing pruned):**
1. **Public versions:** unchanged. The base `0001` and the 10 newest public versions stay in `store/versions/`; older public versions move to `archive/` and are **never pruned automatically**. Public versions are the audit trail of what users could see.
2. **Staging versions:** keep the `STAGING` target plus the **one previous** staging version in `store/versions/`; move older ones to `archive/` (as now).
3. **Archived staging versions become eligible for pruning** only when all of the following hold:
   - (a) no pointer refers to them and no emergency override is active;
   - (b) they are older than the newest 2 archived staging versions **and** older than 30 days;
   - (c) a **rebuild proof** passes: rebuilding the version's content from the registry snapshot, frozen units and embedding cache gives the same `content_signature`. Stage 3.5 showed such a rebuild is byte-identical.
4. **Pruning keeps a tombstone:** `archive/NNNN/` retains `manifest.json`, `registry_snapshot.json` and `passages.jsonl` (about 2 MB), so the version stays auditable and rebuildable. Only `index.faiss` and `chunks.jsonl` (about 26 MB) are removed.
5. **Pruning is an explicit, journaled `kb prune --staging` operation** (`kb_admin`; dry-run first; two-person rule in production), never a side effect.

**Effect today:** 0002–0004 would keep about 6 MB of tombstones instead of 84 MB, once eligible after 30 days. Implementing this needs your approval.

## 5. Recommended Git tracking strategy (not applied)

Current git state:
- `faiss_store/` and `faiss_store_v2/` (about 50 MB) are **already tracked**;
- all Stage 2–3 work is untracked;
- the five moved tutorial files show as deleted.

| Track (commit) | Size | Why |
|---|---|---|
| `src/kb/`, `tests/test_kb_*.py`, `tests/kb_helpers.py` | ~0.2 MB (without `__pycache__`) | Source code and tests |
| `stage2/`, `stage3/` (scripts, reports, results JSON, integrity records, Stage 4 handoff), `audit/` | ~0.6 MB | Evidence and reproducibility of every step |
| `eval/test_questions/` | 0.1 MB | Test material (new files only; frozen `eval/` stages untouched) |
| `data/source_pdfs/` | 0.8 MB | Original source documents (small; keeps provenance inside the repo) |
| `knowledge_base/registry.json`, `ingest_log.jsonl` | 0.3 MB | Source of truth for status, approvals and history; audit journal |
| `knowledge_base/units/`, `validation/` | 0.65 MB | Frozen passages and validation evidence |
| `knowledge_base/uploads/` | 1.6 MB | Content-addressed copies of the datasets, which otherwise live **outside** the repo in `../msu docs` |
| `knowledge_base/embeddings/` | 0.45 MB | **Recommended to track.** It is small, and it is the one artefact that cannot be regenerated bit-for-bit on other hardware (L7) |
| `knowledge_base/store/CURRENT`, `STAGING` and, per version, `manifest.json` + `registry_snapshot.json` + `passages.jsonl` | ~2.2 MB per version | Small; they make each version auditable and rebuildable |

| Do not track (proposed `.gitignore` additions) | Why |
|---|---|
| `knowledge_base/store/versions/*/index.faiss`, `knowledge_base/store/versions/*/chunks.jsonl` | Large (about 26 MB per version) and rebuildable byte-identically from the tracked registry, units, embeddings and `faiss_store_v2` |
| `knowledge_base/archive/` | Large; rebuildable from the tracked manifests and snapshots |
| `knowledge_base/quarantine/`, `knowledge_base/.lock` | Transient |
| `__pycache__/` | Already ignored |

**Proposed `.gitignore` lines** (to apply only after your approval):

```
knowledge_base/store/versions/*/index.faiss
knowledge_base/store/versions/*/chunks.jsonl
knowledge_base/archive/
knowledge_base/quarantine/
knowledge_base/.lock
```

**Alternative.** Keep the active versions' large files in **Git LFS**, consistent with how the frozen stores are already committed. This allows a clone to serve immediately, without a rebuild step. It needs LFS on the remote.

**Proposed commit sequence** (after approval, on a feature branch, not `master`):
1. Move the five tutorial files out (deletions).
2. Stage 2 (`audit/`, `stage2/`, `eval/test_questions/`, `data/source_pdfs/`).
3. Knowledge-base engine and tests (`src/kb/`, tests).
4. Knowledge-base data and metadata, plus Stage 3 evidence (`knowledge_base/` as above, `stage3/`).

`.env` stays ignored and is never read.

## 6. Remaining risks

| # | Risk | Mitigation / next step |
|---|---|---|
| R1 | Out-of-scope questions now retrieve loosely related new passages (gym, visa) | Stage 4 decline-rate check; consider a relevance threshold or prompt guidance in Stage 5 |
| R2 | Near-duplicate crowding (23 road map, 47 intake semantic pairs) can push the intended record down (R08, I10) | Stage 4 crowding metrics; options for later: a sibling-collapse rule or extra heading detail (each needs approval) |
| R3 | The frozen prompt says "MSU yearbooks" while the index now holds other MSU documents | Measured in Stage 4; prompt versioning in Stage 5 |
| R4 | Disk growth from archived staging builds (~100 MB per ingestion) | Retention policy §4 (approval needed) |
| R5 | `knowledge_base/` is inside OneDrive (L4); sync could hold files during a publish | Safe (pointer unchanged on failure, retries); move outside OneDrive before production (D3) |
| R6 | Nothing is under version control yet (Stages 2–3) | Git strategy §5 (approval needed) |
| R7 | The intake's record-level publication approval is still pending | Stage 4 staging evaluation informs that decision |
| R8 | Re-embedding on other hardware may differ in the last bits | Embedding cache kept (and recommended for git); base vectors are only ever copied |

## 7. Files created in Stage 3.5

| File | Notes |
|---|---|
| `stage3/run_3_5.py`, `stage3/stage3_5_results.json`, `stage3/stage3_5_report.md` | Verification script, results, this report |
| `stage3/stage4_handoff/stage4_evaluation_plan.md`, `stage4_questions_draft.json`, `build_stage4_questions.py` | Stage 4 handoff |
| `stage3/integrity_after.json` | Refreshed |

No file in `knowledge_base/`, the app, the frozen artefacts or `.gitignore` was changed.
