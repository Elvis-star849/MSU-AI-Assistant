# Stage 3.2 report: knowledge-base base version 0001

Date: 2026-10-13. Script: `stage3/run_3_2.py`. Full machine-readable results: `stage3/stage3_2_results.json`.

**Not done:**
- no 2027 documents ingested;
- no passage embeddings generated (the build ran with an embedder that raises if called, and no `knowledge_base/embeddings/` folder exists);
- no re-chunking;
- no application change;
- no frozen artefact changed;
- nothing committed or pushed.

## 1. Result

Version **0001** was built from `faiss_store_v2` in 8.7 s and `CURRENT` points to it. **All 22 checks passed** and there were no failures.

## 2. Checksums (SHA-256)

| File | `faiss_store_v2` (frozen) | `knowledge_base/store/versions/0001` | Result |
|---|---|---|---|
| `chunks.jsonl` | `a58bc3d7ea8478ca2c40d4ec288324c32692b549708f0a8733a4c52282bd136c` | `a58bc3d7ea8478ca2c40d4ec288324c32692b549708f0a8733a4c52282bd136c` | **byte-identical** (10,732 lines, all CRLF) |
| `index.faiss` | `5cbc37d0499c442a764dd20ebee3b239129ff9aa87d7c0f02796694b1289f466` | `5cbc37d0499c442a764dd20ebee3b239129ff9aa87d7c0f02796694b1289f466` | **byte-identical** |
| `manifest.json` | `535a13bd18c174358e3a80304c05d9246150e6baa531cd58c28f499dfd8dae09` | `0e6213342b8319596ccbdd6eaec755dcdd16667e6ad6dc2b3b1239a6a709b685` | Differs, as designed: the same existing fields plus the `kb` block, without `created_at` |
| `passages.jsonl` | — | `84ac6c5d2aa9ecf22856362d02ef3c870965e4b7881173a6b2dc1d1c2d657864` | New: external identifiers, 10,732 rows |
| `registry_snapshot.json` | — | `f66519e6650bfb03debcd1b83b0bedca8b6be25d29eb937a36a81c7924bb9d6d` | New |

`faiss_store_v2/` was re-hashed after the build and is unchanged.

| Fingerprint (recomputed from v0001) | Value | Matches |
|---|---|---|
| Record count | 10,732 | v2 manifest |
| Corpus fingerprint | `sha256:545d0dabe1fbe022baf9dd5dfaadaaee6637490e9a2f5fef9e04cf1d455e41f5` | v2 manifest **and** `eval/stage6/s6_6_freeze.json` |
| Heading fingerprint | `sha256:7ce5f4d96a17b4498b3de1240afb563c5b73cefd9ef92114e6c467cd49c68b8c` | v2 manifest |
| FAISS vectors checksum | `sha256:4a4abafb5234021ec95d7020a7f91a8697a99e2b1fb9cd543c1a105b655218fc` | v2 manifest |
| `kb.base.chunks_sha256` | `a58bc3d7…136c` | v2 `chunks.jsonl` file hash |

**Other checks that passed:**
- **Records:** they keep exactly the original six fields.
- **Settings:** the embedding, BM25 and structure settings were carried over unchanged.
- **Document ranges:** `yearbook-humanities` is rows 0–5,613 (5,614 passages); `yearbook-sciences-v2` is rows 5,614–10,731 (5,118 passages).
- **Identifiers:** `passages.jsonl` has one unique `passage_uid` per row, from `yearbook-humanities/v1/c00000` to `yearbook-sciences-v2/v1/c10731`.
- **Service checks:** `kb.verify()` passed with no warnings. Re-running the seed is a no-op (0.02 s). The journal has no open operations.

## 3. Retrieval comparison: v2 (accepted Stage 6 "main") against v0001 (`PublicRetriever`)

**Setup:**
- **Queries:** the 35 frozen Stage 5 questions plus 5 ambiguous-code queries from the frozen Stage 6 list of 246 ambiguous codes, 40 in total.
- **Models:** both pipelines used the same MiniLM reranker instance and the same query-embedding model.
- **Compared per query:**
  - routed top-10 candidates (chunk ID, score, route);
  - reranked top 5 (chunk ID, rerank score, page, source, full text);
  - ambiguity notes.

| Category | Queries | Route | Identical |
|---|---|---|---|
| Natural language | 10 | vector | 10/10 |
| Exact code | 10 | code_hybrid | 10/10 |
| Code in context | 10 | code_hybrid | 10/10 |
| Out of scope | 5 | vector | 5/5 |
| Ambiguous code | 5 | code_hybrid | 5/5 |
| **Total** | **40** | | **40/40** |

**Examples:**
- **N3** (Council chair): top results Sciences p. 19, Humanities p. 18 in both.
- **E3** (SEMA 204): the ambiguity note SEMA204 appears in both.
- **A1–A5:** the notes ACC135, ACC136, AECS131, HAWS443 and HAWS444 appear identically in both.

The course-code map is identical (5,559 codes), and so is the ambiguous-code metadata (246 codes). The full per-query table is in `stage3_2_results.json → retrieval_comparison`.

## 4. Timings and memory

Measured on this machine (CPU).

| Operation | Time |
|---|---|
| Build version 0001: verified read of `faiss_store_v2`, write, full verification of the new version, pointer and registry | **8.7 s** |
| Load + full verification of v0001 | **3.9 s** (read 0.10 s, existing checks 0.17 s, BM25 build 1.77 s, KB checks and hashing about 1.9 s) |
| Load + verification without the BM25 corpus re-check | 2.9 s |
| Reference: load + verification of frozen v2 with the existing loader | 2.1 s |
| `kb.verify()` (both pointers, uploads, units) | 3.8 s |
| Base-material load (repeated at the start of every future rebuild) | 2.7 s |
| Cold start, v2 retriever (index + query model + MiniLM + warm-up) | 3.6 s |
| Cold start, v0001 `PublicRetriever` (verified load + models + warm-up) | 4.9 s |
| Retrieval per query, v2: median / max | 336 ms / 928 ms |
| Retrieval per query, v0001: median / max | 352 ms / 1,119 ms |
| Seed again (no-op) | 0.02 s |

Retrieval latency is dominated by the query embedding and the MiniLM reranking, which are the same in both pipelines. The 16 ms difference between the medians is within run-to-run variation, because the queries alternate between the two pipelines on the same machine.

| Memory (process, RSS / peak working set) | MB |
|---|---|
| Start (libraries imported) | 460 / 460 |
| After building 0001 | 481 / 687 |
| After loading v0001 twice + v2 once | 673 / 765 |
| After loading both retrievers with models | 1,123 / 1,155 |
| End | 1,193 / 1,278 |

A single version with its BM25 index takes about 100–200 MB. The peak during a build is about 210 MB above baseline. `knowledge_base/` takes 27.5 MB on disk.

**Implication for Stage 3.3 and 3.4:** each rebuild loads the base (2.7 s), plans, writes and fully verifies (about 4 s), so a staging or public rebuild should take about 10–15 s at this size. Embedding the 247 new passages is the only model-bound step.

## 5. Tests and integrity

- `python -m unittest discover -s tests -t .`: **152 tests OK**, the 75 existing plus 77 knowledge-base tests, in 55.5 s.
- `python stage3/integrity.py after`: **PASS**.
  - 0 of the 143 protected files changed or missing;
  - git HEAD `eb9ccff` unchanged;
  - the only new files in the protected folders are the 23 Stage 3.1 code and test files.

  The protected set includes `faiss_store/`, `faiss_store_v2/`, `eval/`, the notebooks, `app.py`, all existing `src/` files and `../msu docs`.

## 6. Files created in Stage 3.2

| File | Notes |
|---|---|
| `stage3/run_3_2.py` | Build, verification, comparison and measurement script |
| `stage3/stage3_2_results.json` | All checks, hashes, the per-query comparison, timings and memory |
| `stage3/stage3_2_report.md` | This report |
| `stage3/integrity_after.json` | Refreshed |
| `knowledge_base/registry.json` | 2 base documents, status `published` (base) |
| `knowledge_base/ingest_log.jsonl` | `seed_base` operation: begin and commit |
| `knowledge_base/store/CURRENT` | Points to `0001` with its manifest hash |
| `knowledge_base/store/versions/0001/` | `chunks.jsonl`, `index.faiss`, `manifest.json`, `passages.jsonl`, `registry_snapshot.json` |

`knowledge_base/` is untracked by git. Before any commit we must decide whether to commit it or git-ignore it (27.5 MB, regenerable from `faiss_store_v2`); `.gitignore` was not changed.

## 7. Limitation: rollback leaves the registry unchanged, and a proposed reconciliation

**The problem.** `rollback` points `CURRENT` back to an earlier verified public version, but the registry keeps its current statuses. For example:
- document X is published in version 0005;
- the owner rolls back to 0003, which does not contain X;
- the registry still says X is `published`.

That causes two risks:
- `status` and `history` show X as published while the public index doesn't contain it. `verify()` reports this as a warning.
- The next `publish`, `withdraw` or `supersede` rebuilds from the registry and **silently brings X back**, undoing the rollback.

The reverse case also exists. If X was withdrawn after 0003, rolling back to 0003 makes X publicly visible again while the registry says `withdrawn`.

**Proposal for a later stage (not implemented):**
1. **New status `suspended`.** Allowed transitions: `published → suspended`, `suspended → published` (re-publish, recorded with its approval) and `suspended → withdrawn`.
2. **Rollback becomes registry-aware and atomic.** In one journaled operation (the same begin / pointer / registry / commit protocol, so crash recovery stays correct):
   - documents published in the registry but absent from the target version are set to `suspended`, with reason `rolled back to NNNN`;
   - a document present in the target version but `withdrawn` or `superseded` in the registry is **refused**, unless the approver confirms that the withdrawal should be lifted. That confirmation is recorded as a new approval, never silently.
3. **Rollback without suspension, kept as a guarded emergency mode.** This is a pure pointer rollback with no registry changes. While it is active, the registry records an `active_override`, and `publish`, `withdraw` and `supersede` are **blocked** until the override is resolved. `kb reconcile --plan` shows the registry-versus-index difference; `kb reconcile --apply` takes explicit per-document choices (suspend, withdraw or re-publish).
4. **Guarantee.** After any committed operation, the set of documents visible in `CURRENT` equals the registry's `published` set. `verify()` turns that from a warning into an error.
5. **Governance.** In production the two-person rule applies to rollback and to reconciliation choices.
6. **Tests to add:**
   - rollback suspends;
   - publish is blocked during an override;
   - each reconcile path;
   - the refused reinstatement;
   - a crash at each step of a rollback with suspensions.

**Recommendation:** implement (1), (2) and (4) as the normal rollback, and keep (3) only for emergencies. This would be a small change to `service.rollback`, `states.py` and `verify()`, with no change to the store format.

## 8. Failures

None. The only correction to the run was the reporting of one timing: the in-script "v2 retriever load" timed only the lazy constructor (0.0 s). It was measured separately as the 3.6 s cold start shown above.
