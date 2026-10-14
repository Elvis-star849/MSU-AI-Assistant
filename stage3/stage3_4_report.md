# Stage 3.4 report: embedding, staging and the first public knowledge-base version

Date: 2026-10-13. Script: `stage3/run_3_4.py`. Full results: `stage3/stage3_4_results.json`.

**Not done:**
- no change to the Streamlit app, which still uses `faiss_store_v2` through `src/evidence.py`;
- no change to frozen research artefacts;
- nothing committed or pushed.

**Result: 28/28 checks passed. 184/184 tests passed. Protected-file integrity: PASS.**

## 0. Approval metadata corrected first (owner clarification of 2026-10-13)

Both documents were corrected through the journaled `update_metadata` operation and then revalidated (0 errors, 0 warnings). Their passages are unchanged (same units SHA-256).

| Document | Recorded now |
|---|---|
| `roadmap-2027` | **Officially approved university document** (project owner confirmation, 2026-10-13). The two corrected dates **are the approved dates**: RM2027-11 Semester Break 13/09/2027 – 17/09/2027 and RM2027-13 Examinations 01/11/2027 – 12/11/2027. `approval_reference`: *"None recorded: no Registry signatory or approval reference number was provided."* The `correction_history` keeps the original PDF text (`13/09/2026 - 17/09/2027`, `01/11/2027 - 12/11/202`) for traceability; its basis now reads "Approved date …". The source file `2027 DRAFT ROADMAP fin (1).pdf` is kept unchanged; a note says the word DRAFT does not change the approved status. |
| `intake-2027-jan-feb` | **Officially approved university source document** (project owner confirmation, 2026-10-13), same `approval_reference` note. A separate statement says that **publishing its passages in the assistant is a separate technical approval, still pending (D1).** |

**Wording check:** the current registry metadata no longer contains "not independently verified", "not obtained", "not a formal approval", "not performed" or "not claimed". The earlier wording survives only in the journaled `metadata_history`, as the audit trail of the correction. The 3.3b wording is superseded.

**Unchanged by design:**
- the protected dataset `msu docs/2027/2027_ROADMAP_RAG_Ready_v2.json`, as instructed (no v3);
- its 21 events;
- their passage text, including `STATUS: Approved 2027 road map for this project.` and the `DATE CORRECTION:` lines. Both are now accurate as written.

## 1. Embedding (real model, pinned revision)

| Step | Result | Time |
|---|---|---|
| Model check | `BAAI/bge-small-en-v1.5` at revision `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, the one that produced the frozen vectors. The embedder refuses any other revision. | — |
| Stage `roadmap-2027` | 21 passages embedded; staging version built | 17.1 s (including model load) |
| Stage `intake-2027-jan-feb` | 226 passages embedded; staging version rebuilt | 68.0 s |
| Embedding cache | 247 vectors in `knowledge_base/embeddings/<model key>/` (453 KB); no passage embedded twice | — |
| Base passages | **Not re-embedded**: vectors for rows 0–10,731 copied, checksum `4a4abafb…` = `faiss_store_v2` | — |

## 2. Approval, publication and versions

| Step | Result | Time |
|---|---|---|
| Formal knowledge-base approval of `roadmap-2027` | decision date 2026-10-13; basis: officially approved university document including its approved corrected dates; approved for publication in the assistant; no reference invented | 11.9 s (staging rebuilt) |
| Publish | public version built, `CURRENT` switched, staging refreshed, retention applied | 19.9 s |
| Publishing again | **No-op**, no new version | — |

| Pointer | Version | Passages | Documents (chunk range, status) |
|---|---|---|---|
| `CURRENT` (public) | **0005** | **10,753** | yearbook-humanities 0–5,613 · yearbook-sciences-v2 5,614–10,731 · roadmap-2027 10,732–10,752 (published) |
| `STAGING` | **0006** | **10,979** | the same + intake-2027-jan-feb 10,753–10,978 (**staged**, no approval) |

**Version history:**
- `0001`: the frozen base, kept.
- `0002`–`0004`: intermediate staging builds (roadmap staged; plus intake; roadmap approved). These were moved to `knowledge_base/archive/` by retention, never deleted.

### Checksums (SHA-256)

| File | Public 0005 | Staging 0006 |
|---|---|---|
| `chunks.jsonl` | `7a9658d0…891721c` | `ea08e9ef…a52b84f` |
| `index.faiss` | `f459ca77…640da06` | `f1508177…6ef5b` |
| `manifest.json` | `25956ff5…a1c82c` | `04169e83…d1c9aca6` |
| `passages.jsonl` | `909cfcb4…1aec6a` | `174c3303…b84f` |
| `registry_snapshot.json` | `b6bcb576…a30d` | `04de197c…5224` |

**Both versions:**
- the first 10,732 lines of `chunks.jsonl` are **byte-identical** to `faiss_store_v2/chunks.jsonl`, CRLF included;
- base fingerprints: corpus `545d0dab…`, heading `7ce5f4d9…`, vectors `4a4abafb…` (also recomputed from the FAISS rows);
- `faiss_store_v2` was re-hashed and is unchanged.

## 3. Isolation: the staged intake is absent from the public index

| Check | Result |
|---|---|
| Public identifier mapping | 0 intake rows |
| Public full-corpus vector search (all 10,753 rows ranked) | 0 intake passages |
| Public BM25 for intake-only terms (`COBZZWHA`, `4575486039200`, `0716626820`, which appear 0 times in the yearbooks) | no hits. Staging finds all three. |
| BM25 statistics | separate corpora: public 10,753 documents, staging 10,979; different BM25 corpus fingerprints |
| Course-code map | identical to v2 in both versions (no new codes) |
| Public results for all 49 test queries | no intake passage |
| Staging access | `StagingRetriever` refused a non-administrator (`PermissionDenied`) |

## 4. Retrieval

### 4.1 Frozen regression set: 35 Stage 5 questions + 5 ambiguous-code queries, against the accepted v2 pipeline

| | Identical to v2 (top 5 chunk IDs and rerank scores) | Differences |
|---|---|---|
| Public 0005 | **39/40** | O5 "What time does the campus gym open?" (out of scope): `RM2027-02` (orientation week) enters the top 5 |
| Staging 0006 | **38/40** | O5 as above; O4 "How do I apply for a UK student visa?" (out of scope): `MSU-JF2027-INFO-01` (how to apply) enters the top 5 |

**All 35 in-scope questions are unaffected** (natural language, exact code, code in context, ambiguous code). The two changed questions are out of scope. The new passages are loosely related, so the answer step should still decline. This needs checking in Stage 4.

### 4.2 New-document samples

| # | Question | Expected | Staging rank | Public |
|---|---|---|---|---|
| S1 | Application fee for the Jan/Feb 2027 intake | INFO-02 | **1** | absent (correct, staged) |
| S2 | When does B.Ed. Hons Science and Applied Technologies start? | MSU-JF2027-107 | **1** | absent (correct) |
| S3 | Entry requirements for Mining Engineering | -132 / -133 | **4** (two yearbook Mining passages rank above) | absent (correct) |
| S4 | Bank accounts for the application fee | INFO-03 | **1** | absent (correct) |
| S5 | How to contact MSU admissions | INFO-04 | **1** | absent (correct) |
| S6 | Second semester examinations 2027 | RM2027-13 | **2** (RM2027-21, the Education block-release exams with the same dates, ranks 1) | found |
| S7 | Second semester break 2027 | RM2027-11 | **1** | found |
| S8 | First semester registration 2027 | RM2027-01 | **1** | found |
| S9 | Education block-release first-semester exams | RM2027-17 | **1** | found |

All 9 expected passages are in the staging top 5, and the 4 road map ones are also in the public top 5.

### 4.3 Semantic near-duplicates (cosine ≥ 0.97, computed at staging)

| Document | Pairs within the document | Pairs vs the public store |
|---|---|---|
| roadmap-2027 | 23 (e.g. RM2027-15/16, 0.999: two Education face-to-face tuition blocks) | 0 |
| intake-2027-jan-feb | 47 (e.g. -130/-131, -127/-128: same programme, different mode or duration) | 0 |

These are kept as agreed. S6 shows the expected kind of crowding, where two correct events share the same dates. Stage 4 will measure the effect.

### 4.4 Latency (per query)

| Pipeline | Median | Max |
|---|---|---|
| v2 | 360 ms | 1,010 ms |
| Public 0005 | 375 ms | 860 ms |
| Staging 0006 | 365 ms | 930 ms |

## 5. Rollback test, on a temporary copy of `knowledge_base/`

The test ran on a copy, so that the real road map history does not carry a test suspension and restore.

1. Rollback to `0001` (12.8 s): `roadmap-2027` published → **suspended**. `verify()` OK with no warnings.
2. `publish()` afterwards: the road map **stayed out**; it was not resurrected.
3. Rollback forward to `0005` (12.4 s): suspended → **published**. `verify()` OK.
4. Afterwards, the real knowledge base was confirmed untouched: `CURRENT` 0005, `verify()` OK.

## 6. Timings and memory

| Operation | Time |
|---|---|
| Load + full verification: public / staging | 4.1 s / 4.2 s |
| `kb.verify()` (both versions, uploads, units, consistency) | 8.0 s |
| Approve (+ staging rebuild) / publish (+ staging refresh) | 11.9 s / 19.9 s |

| Memory (RSS / peak) | MB |
|---|---|
| Start | 460 / 460 |
| After staging (embedding model loaded) | 677 / 931 |
| After loading v2 + public + staging retrievers | 1,239 / 1,288 |
| End | 1,322 / 1,449 |

## 7. Integrity and tests

- `python stage3/integrity.py after`: **PASS**.
  - 0 of 143 protected files changed or missing;
  - git HEAD `eb9ccff`;
  - the new files in protected folders are only the knowledge-base code and tests (24).
- `python -m unittest discover -s tests -t .`: **184 tests OK** (90 s).
- `kb.verify()`: OK; no problems, no warnings, no override. The journal has no open operations.

## 8. Files

| Path | Notes |
|---|---|
| `stage3/run_3_4.py`, `stage3_4_results.json`, `stage3_4_report.md` | New |
| `knowledge_base/store/versions/0005` (public), `0006` (staging); `CURRENT` → 0005, `STAGING` → 0006 | New versions |
| `knowledge_base/archive/0002–0004` | Intermediate staging versions (retention; not deleted) |
| `knowledge_base/embeddings/<model key>/` | 247 cached vectors |
| `knowledge_base/registry.json`, `ingest_log.jsonl`, `units/`, `validation/` | Corrected approval metadata, statuses, approvals, staging reports; all operations committed |

`knowledge_base/` is now **170 MB**, 85 MB of it in `archive/`. It is untracked by git.

## 9. Observations and remaining limitations

| # | Item | Proposal |
|---|---|---|
| O1 | Out-of-scope questions O4 and O5 now retrieve loosely related new passages | Stage 4: check the answers still decline; consider a relevance threshold later |
| O2 | Crowding: S6 ranks the block-release exams (same dates) above the main-calendar exams; S3 ranks two yearbook Mining passages above the intake records | Stage 4 crowding metric, as agreed; no data changes |
| O3 | Disk use: every intermediate staging build is kept in `archive/` (85 MB after one ingestion) | Propose a separate retention rule for staging versions (for example, archive only the last 2 superseded ones and move others to a compressed cold store), with your approval |
| O4 | The running Streamlit app still uses `faiss_store_v2` | Switching to `PublicRetriever` (CURRENT) and the prompt update are Stage 5, after the Stage 4 evaluation |
| O5 | `knowledge_base/` is not covered by `.gitignore` or a commit decision | Decide before any commit (for example: commit the registry, units and reports; git-ignore the versions, archive and embeddings, which can be rebuilt) |
