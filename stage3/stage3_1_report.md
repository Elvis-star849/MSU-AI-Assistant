# Stage 3.0–3.1 report: ingestion engine and automated tests

Date: 2026-10-13. Scope: engine code and synthetic tests only.

**Not done in this step:**
- no real v3 index built;
- no 2027 documents ingested;
- no embedding model loaded;
- nothing committed or pushed.

## 3.0 Integrity snapshot

`stage3/integrity.py before` hashed 143 protected files and recorded git HEAD `eb9ccff`. The protected set covers:
- the frozen indexes;
- `eval/`, `notebook/` and the main notebook;
- all existing `src/` and `tests/` files;
- `app.py` and the configuration files;
- `../msu docs`, `data/source_pdfs` and `stage2/`.

`.env` is deliberately not read.

## 3.1 Code (all new; no existing file modified)

| File | Purpose |
|---|---|
| `src/kb/errors.py`, `ids.py`, `config.py`, `states.py` | Errors; stable IDs; profiles (two-person rule off in development, on in production), roles, `Actor`; state machine |
| `src/kb/fsutil.py`, `lock.py`, `journal.py` | Atomic writes with Windows/OneDrive retries; single-writer lock (stale-lock detection uses `OpenProcess` on Windows); journal |
| `src/kb/registry.py` | `RegistryBackend` interface + `JsonRegistry` |
| `src/kb/adapters.py`, `validate.py` | `json_records` (ordered record groups), `pdf_prose`; validation errors and warnings |
| `src/kb/embeddings.py` | Revision-checked sentence-transformers embedder; content-addressed, resumable embedding cache |
| `src/kb/store.py` | `KBStore(HeadingAwareStore)`: full verification on load, search-time filter (selector / over-fetch), `passage_uid` on results |
| `src/kb/versions.py` | Builder (temp folder → verify → number), pointers with manifest hash, retention |
| `src/kb/service.py` | `KnowledgeBase` service API, including crash recovery |
| `src/kb/retriever.py` | `PublicRetriever` (CURRENT only), `StagingRetriever` (STAGING, administrators only), using the accepted Stage 6 settings |
| `src/kb/__init__.py`, `__main__.py` | Package and CLI |
| `tests/kb_helpers.py`, `tests/test_kb_*.py` | 77 tests on synthetic data |

About 3,400 lines in total.

## Test results

`python -m unittest discover -s tests -t .` ran **152 tests, OK**: the 75 existing tests plus 77 new ones, in 57 s.

| Suite | Tests | Covers |
|---|---|---|
| `test_kb_core` | 15 | IDs, state transitions, profiles and roles, atomic JSON, lock (including a stale lock from a really dead process and a lock from another host), journal with a torn line, registry ordering |
| `test_kb_ingest` | 13 | Adapters (group order, header and heading, provenance mismatch, selected groups only), PDF prose, validation errors and warnings, embedding cache (no re-embedding, **resume after a crash mid-embedding**, model mismatch) |
| `test_kb_store` | 16 | **Base chunk lines and index byte-identical to the frozen store** (CRLF preserved), fingerprints reproduced, frozen store untouched, identifiers only in `passages.jsonl`; tampering with any file is rejected; filter equals brute force for both methods; no-filter results identical to `HeadingAwareStore` |
| `test_kb_service` | 24 | Workflow; **staged text absent from public FAISS, BM25 and the code map**; separate BM25 statistics; permissions, staging access, two-person rule; exact approval record; idempotency and duplicates; `passage_uid` stable after positions move; supersede, withdraw, reject; rollback and divergence warning; retention; **byte-identical rebuilds** |
| `test_kb_recovery` | 9 | Simulated crash at every step of publish and stage, and in a registry-only operation: aborted before the pointer switch, completed after it; stale lock after a killed process; live lock blocks writers but not readers; a corrupt version is detected |

**Mutation check:** I broke three behaviours deliberately (staged documents visible in public; filter ignored; recovery always aborts). Each made the relevant tests fail (4/5, 2/4, 3/4).

## Integrity after Stage 3.1

`stage3/integrity.py after` reported:
- **PASS:** 0 protected files changed, 0 missing;
- 23 new files (the code and tests above);
- git HEAD unchanged.

No `knowledge_base/` folder was created, because the tests use temporary folders only.

## Problems found and fixed during implementation

1. **Record-group order:** a dict of groups would lose its order, because the registry is saved with sorted keys. Groups are now an ordered list, and the proposal was updated.
2. **Determinism:** an operation ID inside the manifest would make identical rebuilds differ. It was removed; recovery matches operations by the target version recorded in the journal.
3. **CRLF line endings:** `faiss_store_v2/chunks.jsonl` uses CRLF line endings. The builder copies base lines as raw bytes and reuses the base file's line ending.
4. **Open file handle:** `seed_base` left a file handle open, which on Windows can block a later rename. Fixed.
5. **Abort after a pointer switch:** an ordinary error after a pointer switch would have been recorded as aborted, leaving the registry out of step with the index. Such an operation is now left open, and recovery completes it.
6. **Validate write order:** `validate` wrote its files after the journal `begin`. The files are now written first, so recovery can safely complete the operation.
7. **Process check on Windows:** `os.kill(pid, 0)` sends CTRL+C on Windows. Process checks use `OpenProcess` instead.

## Known limitations and items for Stage 3.2

- **Not yet exercised:** the real embedder and the Hugging Face tokenizer, by design (no model loading in tests). They are first used in 3.2 and 3.3.
- **Performance at real scale is unmeasured.** Each operation loads and verifies the store version two or three times. At 10,732 rows this is expected to take seconds; it will be measured in 3.2.
- **Rollback leaves the registry unchanged.** `verify()` reports the divergence until the next publish.
- **Stale locks:** automatic release of a stale lock only works on the same host. Other hosts need `kb unlock` (`kb_admin`).
