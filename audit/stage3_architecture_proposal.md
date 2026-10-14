# Stage 3: incremental document ingestion and indexing (revision 3)

Status: architecture approved 2026-10-13. Stage 3.0 and 3.1 are approved for implementation; Stage 3.2 onwards need further approval.

## 1. Decisions and requirements

| Ref | Decision / requirement |
|---|---|
| D1 | The 2027 intake stays **staged** until the project owner explicitly approves its publication |
| D2 | Two-person approval (approver ≠ uploader) is **configurable**: off in the development prototype, **on in production** |
| D3 | The knowledge base lives inside `MSU-AI-Assistant/` during development; it moves outside OneDrive before production |
| D4 | Retention: the frozen base version plus the **10 most recent public versions**; older versions are archived, never deleted |
| R1 | Versioned stores with `CURRENT` (public) and `STAGING` pointers, plus rollback |
| R2 | Roadmap: only the **21 events** are indexed; the 4 semester summaries stay in the dataset for evaluation |
| R3 | Staged documents are never reachable by public search. Staging search requires an explicit staging retriever and an authorised administrator. |
| R4 | Public and staging are separate index versions, each with its own FAISS index **and its own BM25 statistics** |
| R5 | Future Django admin: upload, validate, approve and publish without code edits; staging access for authorised administrators only |
| R6 | Registry and ingestion engine are independent of any user interface |
| R7 | Inactive-record filtering verified on the installed FAISS, with a tested fallback |
| R8 | FAISS, BM25, metadata and document status are published together as one version |
| R9 | Stable external document and record IDs. Internal FAISS positions may change. |
| R10 | Idempotent ingestion, duplicate detection, safe recovery after interrupted writes |
| R11 | Roadmap approved on the owner's confirmation, keeping its DRAFT source filename and correction history |
| R12 | The **10,732 yearbook records are preserved byte for byte**; extra identifiers live in a separate mapping file |
| R13 | Frozen research indexes, notebooks, evaluation results and the accepted Stage 6 implementation are not modified |

## 2. Verified facts

All checked on 2026-10-13 in the project environment.

| Fact | Consequence |
|---|---|
| FAISS 1.15.1: `IndexFlatIP.search(..., params=SearchParameters(sel=IDSelectorNot(IDSelectorBatch(ids))))` and `IDSelectorBitmap`. Test on 10,983 × 384 vectors: 0 leaks, exact top-10 against brute force, 0.73 ms per query. | The search-time filter works (R7). |
| Over-fetching `k + number of inactive`, then filtering in Python: 0 leaks, exact, 1.02 ms per query | Tested fallback (R7) |
| FAISS pads with `-1` when fewer than k rows are eligible | Callers drop `-1` |
| `reconstruct_n` returns bit-identical vectors | Versions are built without re-embedding |
| `rank_bm25.BM25Okapi` cannot be updated incrementally. `FaissVectorStore.load` rebuilds BM25 and the course-code map from the records on every load. | If inactive text were only filtered at search time, it would still shape BM25 statistics. So staged and withdrawn documents are **physically excluded** from public versions (R3, R4). |
| The existing loader requires `chunk_id` = position, matching counts, corpus fingerprint, vectors checksum, model, chunk settings 800/150, and (heading store) `structure_version` v2 plus the heading fingerprint | Every version is written in that exact format and opened by the existing loader |
| The 21 roadmap events and 226 intake records are ≤ 393 tokens each (limit 512) and contain no course codes | One record = one passage |
| `faiss_store_v2` is 26 MB (16 MB vectors, 9.7 MB records) | About 26–30 MB per version |

## 3. Layers

```
Interfaces (thin):   CLI  python -m src.kb …   |   notebook v3   |   Django admin (later)
                                  │ calls only
Service API:         src/kb/service.py  KnowledgeBase
                     roles · state machine · two-person rule · audit journal · lock · recovery
                                  │
Engine:              registry (JSON backend; Django backend later) · adapters · validators ·
                     embedding cache · version builder · pointers · retention
                                  │ writes
Store:               knowledge_base/store/versions/NNNN/   CURRENT   STAGING
                                  │ read by
Retrieval:           PublicRetriever (CURRENT only) · StagingRetriever (STAGING, administrators only)
```

The engine has no Django, Streamlit or web imports.

## 4. Identifiers (R9, R12)

| ID | Example | Stability |
|---|---|---|
| `doc_id` | `roadmap-2027`, `intake-2027-jan-feb`, `yearbook-humanities`, `yearbook-sciences-v2` | Permanent |
| `doc_version` | `1` | Permanent; increases when the document's content (SHA-256) changes |
| `record_id` | `RM2027-11`, `MSU-JF2027-107`; prose PDFs `p0018-c03`; yearbook base `c00123` | Permanent within a document version |
| `passage_uid` | `intake-2027-jan-feb/v1/MSU-JF2027-107` | Permanent; the external key for citations, logs, evaluation and Django |
| `record_key` | `intake-2027-jan-feb/MSU-JF2027-107` | Permanent across document versions |
| `chunk_id` | `10745` | **Internal** FAISS position. Base rows 0–10,731 never move; other rows can move between versions. |

**`chunks.jsonl` keeps exactly the existing record schema:** `chunk_id, source, file_name, page, text, heading`.
- Lines 1–10,732 of every version are a **byte-for-byte copy** of `faiss_store_v2/chunks.jsonl`.
- All extra identifiers live in a separate `passages.jsonl`, one line per row, in the same order:

```json
{"chunk_id": 10745, "passage_uid": "roadmap-2027/v1/RM2027-14", "record_key": "roadmap-2027/RM2027-14", "doc_id": "roadmap-2027", "doc_version": 1, "record_id": "RM2027-14", "unit_type": "roadmap_event"}
```

## 5. Store layout and the consistent version unit (R1, R4, R8)

```
knowledge_base/
  registry.json                 document registry (JSON backend)
  kb_config.json                optional: {"profile": "development" | "production", "two_person_rule": …}
  uploads/<sha256>/<original name>      content-addressed, never edited
  units/<doc_id>@v<n>.jsonl     validated passages of one document version (immutable)
  validation/<doc_id>@v<n>.json validation and dry-run reports
  embeddings/<model key>/batch-*.npz    embedding cache, keyed by passage-text hash
  store/
    versions/NNNN/
      index.faiss               FAISS IndexFlatIP
      chunks.jsonl              existing schema; base lines copied byte for byte
      passages.jsonl            external identifiers, one line per row
      registry_snapshot.json    the exact registry entries this version contains
      manifest.json             existing manifest fields + "kb" block
    CURRENT                     {"version": "NNNN", "kind": "public",  "manifest_sha256": "…"}
    STAGING                     {"version": "NNNN", "kind": "staging", "manifest_sha256": "…"}
  ingest_log.jsonl              append-only journal (begin / commit / abort, with actor and hashes)
  quarantine/                   leftovers from interrupted operations (never deleted automatically)
  archive/                      versions outside retention (never deleted automatically)
  .lock                         single-writer lock
```

- Version numbers come from **one sequence** shared by public and staging versions.
- `0001` is always the frozen base (public, yearbooks only).
- BM25 and the course-code map are **not stored**. Each store rebuilds them from its own `chunks.jsonl` on load, so a public version's BM25 statistics include only public text, and a staging version's only staging text (R4). The manifest records a `bm25_corpus_fingerprint`, which is re-checked on load.

**The manifest's `kb` block** is added next to the unchanged existing fields:

```json
"kb": {
  "format_version": 1,
  "kind": "public",
  "version": "0003",
  "parent": "0002",
  "seed": false,
  "base": {"chunk_count": 10732, "chunks_sha256": "…", "corpus_fingerprint": "sha256:545d0dab…",
           "heading_fingerprint": "sha256:7ce5f4d9…", "vectors_checksum": "sha256:4a4abafb…"},
  "documents": [
    {"doc_id": "yearbook-humanities", "doc_version": 1, "status": "published", "base": true,
     "chunk_range": [0, 5613], "passages": 5614, "content_fingerprint": "sha256:…", "vectors_checksum": "sha256:…"},
    {"doc_id": "yearbook-sciences-v2", "doc_version": 1, "status": "published", "base": true,
     "chunk_range": [5614, 10731], "passages": 5118, "content_fingerprint": "sha256:…", "vectors_checksum": "sha256:…"},
    {"doc_id": "roadmap-2027", "doc_version": 1, "status": "published", "base": false,
     "chunk_range": [10732, 10752], "passages": 21, "units_sha256": "…",
     "content_fingerprint": "sha256:…", "vectors_checksum": "sha256:…"}],
  "passages_sha256": "…",
  "registry_snapshot_sha256": "…",
  "bm25_corpus_fingerprint": "sha256:…",
  "inactive_chunk_ids": [],
  "embedding": {"model": "BAAI/bge-small-en-v1.5", "revision": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
                "recipe": "heading_store.index_text"},
  "content_signature": "sha256:…"
}
```

- `seed` is true only for `0001`.
- `content_signature` identifies what a version contains (kind, base, documents, registry snapshot), but not its number or parent. Rebuilding identical content is therefore a no-op.
- The manifest holds no operation IDs or timestamps. Operation IDs and times are kept in the journal, so a rebuild with the same inputs is byte-identical.

The yearbook ranges were checked against `faiss_store_v2/chunks.jsonl`: Humanities 0–5,613, Sciences 5,614–10,731. That file ends every line with CRLF, and the builder copies base lines as raw bytes and reuses the base file's line ending for new rows.

- `content_fingerprint` hashes `record_id, source, file_name, page, heading, text` and **not** `chunk_id`, so a document keeps the same fingerprint when it moves.
- `base.chunks_sha256` is the SHA-256 of the raw bytes of the first 10,732 lines; in `0001` it equals the SHA-256 of the whole of `faiss_store_v2/chunks.jsonl`.

**Loading a version re-checks everything:**
- the existing loader checks;
- the base block hashes;
- each document's content fingerprint and vectors checksum;
- `passages.jsonl` against the records;
- the registry snapshot hash;
- document statuses for the version's kind;
- the BM25 corpus fingerprint;
- the pointer's manifest hash.

## 6. Document states, public and staging access (R3, R5)

```
uploaded ─validate─► validated ─stage─► staged ─approve─► approved ─publish─► published ─► superseded
    ▲ update_metadata    │                 │                  │                    ├──────► withdrawn
    └────────────────────┘                 │                  │                    └──────► suspended (rollback)
    └─────────── reject ─┴─────────────────┴──────────────────┘ ──► rejected          suspended ─► published / withdrawn
withdrawn / superseded ─► published only by a rollback or reconciliation with a recorded reinstatement approval
```

| Version kind | Contains |
|---|---|
| public (`CURRENT`) | base + `published` documents only |
| staging (`STAGING`) | base + `published` + `staged` + `approved` documents |

**Public access:** `PublicRetriever` opens only `CURRENT`. It refuses a version whose snapshot contains any document that isn't `published`.

**Staging access:**
- `StagingRetriever` opens only `STAGING`, and requires an `Actor` with the role `kb_admin` or `kb_approver`; otherwise it raises `PermissionDenied`.
- The public app has no setting that selects it.
- In Django, these roles map to administrator groups and permissions, and the staging search page sits behind the admin login.

**Roles enforced by the service:**

| Role | Can do |
|---|---|
| `kb_uploader` | upload, validate, stage |
| `kb_approver` | approve, reject, publish, withdraw, supersede, roll back, staging search |
| `kb_admin` | everything, plus unlock and recovery |

**Two-person rule (D2):** when enabled, the approver must differ from the uploader.
- It is off in the `development` profile and on in the `production` profile.
- The `KB_PROFILE` environment variable or `kb_config.json` selects the profile.
- An explicit `two_person_rule` setting overrides the profile.

**Search-time filter (R7):** in addition, `KBStore` applies FAISS `IDSelectorNot(IDSelectorBatch(inactive))` to vector search, masks BM25 scores, and drops inactive rows from the course-code map. In correctly built versions the inactive list is empty, so the filter is a safeguard. The over-fetch fallback is selectable and tested against brute force.

## 7. Idempotency, duplicates, recovery (R10)

- **Upload:**
  - the same SHA-256 for the same `doc_id` returns the existing entry (no-op);
  - the same SHA-256 under another `doc_id` is rejected (`DuplicateDocument`);
  - new content for an existing `doc_id` becomes `doc_version + 1`.
- **Validate / stage / publish:**
  - repeating an operation with no registry change is a no-op;
  - builds are deterministic, with no timestamps in versions, so identical inputs give identical files.
- **Duplicates:**
  - duplicate `record_id` within a document: error;
  - exact text already in the target store, or repeated within the document: warning;
  - near-duplicate (cosine ≥ 0.97) to existing passages: warning, listed in the staging report.
- **Embedding cache:**
  - keyed by the SHA-256 of the indexed text, the model revision and the recipe;
  - written batch by batch, each batch atomically;
  - an interrupted embedding resumes;
  - rebuilds never re-embed.
- **Write protocol:**
  1. Take the single-writer lock (it records process ID, host and time).
  2. Recover from earlier failures.
  3. Write a journal `begin` entry, including the intended registry state.
  4. Build in `store/versions/.tmp-<op>/`, flush, then **verify by loading**.
  5. Rename the folder to `NNNN`.
  6. Atomically replace the pointer.
  7. Write the registry atomically.
  8. Write a journal `commit` entry.
- **Recovery (automatic, at the next write):**
  - leftover `.tmp-*` folders and versions from aborted operations move to `quarantine/`;
  - a `begin` entry with no `commit` is completed if its pointer was already switched, or aborted otherwise;
  - a lock left by a dead process on the same host is released and reported;
  - any other held lock needs `kb unlock --force` (`kb_admin`).
- **Windows / OneDrive:** file replaces and renames retry with backoff when another process holds the file. `CURRENT` only ever names a complete, verified version.

## 8. The first documents (R2, R11)

These are registered in Stage 3.3, not now.

| doc_id | Source label | Passages | Status |
|---|---|---|---|
| `yearbook-humanities`, `yearbook-sciences-v2` | MSU Humanities Yearbook; MSU Sciences Yearbook Vol. 2 | 10,732 (frozen base) | published (base) |
| `roadmap-2027` | MSU 2027 Road Map | **21** events | published, on the owner's confirmation |
| `intake-2027-jan-feb` | MSU January/February 2027 Intake Advert | **226** (222 programmes + 4 information records) | staged until explicitly approved (D1) |

That makes **247 new passages** (226 + 21):

| Version | Passages |
|---|---|
| Staging (base + roadmap + intake) | **10,979** |
| First public version after the base (base + roadmap) | **10,753** |

**Roadmap registry entry (abridged):**

```json
{
  "doc_id": "roadmap-2027",
  "doc_version": 1,
  "title": "MSU 2027 Road Map",
  "source_label": "MSU 2027 Road Map",
  "adapter": "json_records",
  "adapter_options": {"groups": [{"name": "events", "path": "events", "id": "id", "text": "rag_text",
                                  "page": "source_page", "heading": ["calendar_group", "semester", "activity"],
                                  "unit_type": "roadmap_event"}],
                      "source_sha256_field": "source_sha256"},
  "dataset": {"name": "2027_ROADMAP_RAG_Ready_v2.json", "sha256": "…", "path": "uploads/<sha256>/2027_ROADMAP_RAG_Ready_v2.json"},
  "source_file": {"name": "2027 DRAFT ROADMAP fin (1).pdf",
                  "sha256": "c9790a92ba690fcf02b77d9cbadd057f36c3be369e7997eecdbd52df9c6c3b75",
                  "path": "uploads/c9790a92…/2027 DRAFT ROADMAP fin (1).pdf"},
  "status": "published",
  "approvals": [{
    "actor": "project-owner",
    "decision": "approved",
    "decision_date": "2026-10-13",
    "basis": "The project owner confirmed that the corrected 2027 road map is the approved version for this project.",
    "evidence": null,
    "registry_verification": "not performed",
    "recorded_at": "<time recorded in Stage 3.3>",
    "two_person_rule": false}],
  "correction_history": [
    {"event_id": "RM2027-11", "item": "Second Semester – Semester Break",
     "dates_in_source": "13/09/2026 - 17/09/2027", "approved_dates": "13/09/2027 - 17/09/2027"},
    {"event_id": "RM2027-13", "item": "Second Semester – Examinations",
     "dates_in_source": "01/11/2027 - 12/11/202", "approved_dates": "01/11/2027 - 12/11/2027"}],
  "excluded_units": {"semester_summaries": {"count": 4,
                     "reason": "Kept in the dataset for evaluation and possible later inclusion; not indexed."}},
  "history": [{"from": null, "to": "uploaded", "actor": "…", "at": "…", "reason": "…"}, "…"]
}
```

The approval record stores the **decision date (2026-10-13)** separately from the time it is recorded, so the history stays accurate. The correction history is copied from the dataset's `corrections_applied` and checked against it at validation.

## 9. Django readiness (R5, R6)

| Admin screen (later) | Service call | Role |
|---|---|---|
| Upload form | `register_upload(dataset, metadata, actor, source_file=…)` | uploader |
| Validate | `validate(doc_id, version, actor)` | uploader |
| Stage for testing | `stage(doc_id, version, actor)` (embedding runs as a background job) | uploader |
| Staging search | `StagingRetriever.open(kb, actor)` | approver / admin |
| Approve / reject | `approve(..., basis, decision_date)` / `reject(..., reason)` | approver; two-person rule in production |
| Publish / withdraw / supersede / roll back | `publish` / `withdraw` / `supersede` / `rollback` | approver |
| History | `history(doc_id)` | any staff role |

- The `RegistryBackend` interface has `JsonRegistry` now; a Django-model backend can implement the same methods later. The interface only loads and saves the whole registry state: `documents` plus `pointer_events` (rollbacks).
- Every long operation accepts a progress callback, so a worker (Celery, Django-Q or a management command) can run it without engine changes.
- New documents of known types need only metadata. A new layout needs one adapter, or a JSON dataset that follows the record schema.

## 10. Adapters

| Adapter | Input | Passage | Heading |
|---|---|---|---|
| `json_records` | JSON dataset; `adapter_options.groups` is an **ordered list** (the order of passages in the index); each group gives its `name`, dataset `path`, `id`, `text` and `page` fields, `heading` fields and `unit_type` | 1 record = `[<source label>, p. N]\n` + record text | `Section: ` + heading fields joined with ` > ` |
| `pdf_prose` | Text PDF | Existing cleaning and 800/150 splitter, citation header | none (structure rules are yearbook-specific) |

**Validation checks:**
- *Errors:* schema; unique `record_id`; non-empty text; page in range; tokens ≤ 512; source SHA-256 consistent with the registered source file.
- *Warnings:* course codes detected; exact duplicates.

## 11. What is not modified (R13)

**Not modified:**
- `faiss_store/` and `faiss_store_v2/`;
- `eval/`, `notebook/`, `msu_chatbot_pipeline.ipynb`;
- all existing `src/` modules (including the Stage 6 modules, `evidence.py`, `context.py` and `assistant.py`), `app.py` and `tests/`;
- `requirements.txt` and `.gitignore`;
- `../msu docs/`, `data/source_pdfs/` and `stage2/`.

All new code is in `src/kb/` and `tests/test_kb_*.py`. `stage3/integrity.py` checks all of the above before and after each step.

## 12. Technical limitations

| # | Limitation | Handling |
|---|---|---|
| L1 | BM25 is rebuilt on every load (seconds at about 11,000 passages) | Fine at this scale; revisit beyond about 100,000 passages |
| L2 | Filtering alone would leave inactive text in BM25 statistics | Physical exclusion (§6) |
| L3 | `IndexFlatIP` scans every vector (0.7 ms per query at 11,000) | Fine to about 10⁶; an approximate index needs a new evaluation |
| L4 | Windows / OneDrive may hold files during replace or rename | Retries; the pointer is unchanged on failure; relocation before production (D3) |
| L5 | The running app caches the loaded store | A new version is seen after a restart until Stage 5 adds a version check |
| L6 | Each version is a full copy (about 26–30 MB) | Retention and archive (D4) |
| L7 | Re-embedding on different hardware can differ in the last bits | Base vectors are only copied; new vectors are cached; the model revision is checked |
| L8 | No universal table extractor | One adapter per new layout, or schema-valid JSON |
| L9 | Non-base `chunk_id`s change between versions | External references use `passage_uid` |
| L10 | The loader requires 800/150 in the manifest | Kept; each document records its own adapter options |
| L11 | One writer at a time | Lock; Django queues jobs |
| L12 | A rollback could leave the registry and CURRENT disagreeing | **Resolved in Stage 3.3b**: registry-aware rollback (`suspended`), explicit reinstatement approval, guarded emergency override with `reconcile`, consistency differences are errors (see `stage3/stage3_3b_report.md`) |
| L13 | Django is not installed | A later stage, with a new dependency approval |

## 13. Files (Stage 3.1)

`src/kb/`:

| File | Contents |
|---|---|
| `__init__.py`, `__main__.py` | CLI |
| `errors.py`, `ids.py`, `config.py` | Errors; IDs; config, profiles and `Actor` |
| `states.py` | State machine |
| `fsutil.py` | Hashing, atomic writes with retries |
| `lock.py`, `journal.py` | Single-writer lock; journal and recovery records |
| `registry.py` | `RegistryBackend`, `JsonRegistry` |
| `adapters.py` | `json_records`, `pdf_prose` |
| `validate.py` | Validation checks |
| `embeddings.py` | Embedder interface, sentence-transformers embedder, embedding cache |
| `store.py` | `KBStore(HeadingAwareStore)`: verification, filtering, `passage_uid` |
| `versions.py` | Builder, pointers, retention |
| `retriever.py` | `PublicRetriever`, `StagingRetriever` |
| `service.py` | `KnowledgeBase` |

`tests/`:
- `kb_helpers.py`: a synthetic base store, hash embedder and fake reranker; no model downloads.
- `test_kb_*.py`

`stage3/integrity.py`, `stage3/integrity_before.json`, `stage3/integrity_after.json`.

## 14. Implementation sequence

| Step | Work | Gate |
|---|---|---|
| 3.0 | Integrity snapshot of protected files | done |
| 3.1 | Engine and automated tests on synthetic data only | **Review 1** |
| 3.2 | Build `0001` from `faiss_store_v2` (no embedding); prove byte-identical base lines and `545d…` / `7ce5…` / `4a4a…` | Review 2 |
| 3.3 | Register the roadmap (approved, as in §8) and the intake; validation and dry-run reports | Review 3 |
| 3.3b | **Done 2026-10-13.** Required safety task before 3.4: registry-aware rollback, with a `suspended` status, suspension in the same journaled operation, a guarded emergency override that blocks publishing until reconciled, and `verify()` treating any CURRENT/registry difference as an error. Also, if approved: `update_metadata` before staging (F1) and readable information-record headings (W2). See `stage3/stage3_2_report.md §7` and `stage3/stage3_3_report.md §6–7`. | Review 3b |
| 3.4 | Embed 247 passages. Build staging (10,979) and the first public version after the base (10,753). Prove the intake is absent from public FAISS, BM25 and the code map. Test rollback. | Review 4 |
| 3.5 | Notebook v3 (service calls only), final integrity check, report | Final review |

Nothing is committed or pushed without approval.
