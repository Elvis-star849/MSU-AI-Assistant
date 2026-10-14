# Stage 3.3b report: safety tasks before Stage 3.4

Date: 2026-10-13. Real-KB script: `stage3/run_3_3b.py`; results: `stage3/stage3_3b_results.json`.

**Not done:**
- no embeddings;
- no staging or public version built (only `0001` exists, and there is no `STAGING` pointer);
- `CURRENT` unchanged (same file hash, `0001`);
- no change to the app, frozen indexes, evaluation files or main notebook;
- no merging or deletion of near-duplicate records (all 247 passages kept);
- nothing committed or pushed.

## 1. What was implemented

| Requirement | Implementation (`src/kb/`) |
|---|---|
| `suspended` status | `states.py`: `published → suspended`; `suspended → published / withdrawn`. Withdrawn and superseded stay terminal; making them public again needs the explicit `reinstatement` path (`REINSTATEMENT`). |
| Registry-aware rollback | `service.rollback(version, actor, reason, reinstate=None)`. In **one journaled operation** (begin with the intended registry state → pointer → registry → commit): published documents missing from the target become `suspended`; suspended documents present in it become `published`. Withdrawn or superseded documents present in it need `reinstate={"basis", "documents": [[id, v], …], "decision_date"}`, otherwise `ReinstatementRequired` is raised and **nothing changes**. Each reinstatement adds an approval record (`decision: reinstated`, previous status, context). In production the two-person rule stops the approver who withdrew a document from reinstating it. Staging is refreshed afterwards. |
| Emergency rollback | `rollback(..., emergency=True)`: pointer only, plus a journaled `active_override`. **Blocked while active:** publish, withdraw, supersede, republish and any further rollback (`OverrideActive`). |
| Reconciliation | `reconcile_plan()` (read-only difference) and `reconcile(actor, mode, reason, reinstate=None)`. `accept_index` keeps CURRENT and aligns the registry to it, using the same rules as a normal rollback. `restore_registry` builds a new public version from the registry. Both clear the override. |
| Re-publishing | `republish(doc, version, actor, basis)`: `suspended → published` with a recorded decision. |
| Consistency | `consistency()` compares the registry's visible set (document, version, **status**) with CURRENT and with STAGING, using manifests only. **Frozen base:** each base document must be present, published and cover exactly its frozen rows. **Any difference is an error**, except the expected public difference while an override is active, which is a warning. Every write operation now ends with `_assert_consistent()` and raises `IntegrityError` if this fails. `verify()` reports it as problems. |
| Metadata correction | `update_metadata(doc, version, changes, actor, reason)`: journaled; allowed only in `uploaded` or `validated`; editable fields only (title, source label, adapter, adapter options, valid_for, correction history, excluded units, notes, prior approval). A validated version returns to `uploaded`, its units and report are **detached but kept** (`metadata_history`), and it must be validated again before staging. Identical values are a no-op. Staged, approved, published and base versions are refused. |
| Content-addressed validation files | Revalidation writes `units/<doc>@v<n>.<sha12>.jsonl` and `validation/<doc>@v<n>.<sha12>.json`, so earlier files are never overwritten. |
| Readable headings | `adapters.py`: optional per-group `heading_labels` (raw value → readable text); invalid label maps are rejected. |
| CLI | `rollback --emergency --reinstate-basis … --reinstate DOC:V`, `reconcile-plan`, `reconcile {accept_index,restore_registry}`, `republish`, `update-metadata` |

### Bug found and fixed while testing

A rollback interrupted just after its journal `begin` was aborted correctly by recovery. However, recovery then moved the **rollback target**, an older, valid public version, into quarantine. This came from Stage 3.1 recovery code, which assumed every operation's target was a version it had created.
- **Fix:** each journal entry now records `new_version`, and only versions created by the interrupted operation are quarantined.
- **Regression test:** `TestRecoveryOfNewOperations.test_crash_during_normal_rollback` now asserts that both versions still exist.

## 2. Applied to the real knowledge base

Both changes went through `update_metadata` and revalidation. **15/15 checks passed.**

### Intake: readable information-record headings

| Record | Before | After |
|---|---|---|
| MSU-JF2027-INFO-01 | `Section: application_procedure` | `Section: How to apply for the January/February 2027 intake` |
| MSU-JF2027-INFO-02 | `Section: application_fee` | `Section: Application fee for the January/February 2027 intake` |
| MSU-JF2027-INFO-03 | `Section: fee_payment_banking_details` | `Section: Paying the application fee: bank accounts and deposit slip` |
| MSU-JF2027-INFO-04 | `Section: enquiries_contacts` | `Section: Admissions enquiries: phone, WhatsApp and email` |

**What did not change:**
- **Passages:** all 226 still have the same record IDs, pages and **text**; only these four headings differ.
- **Files:** the dataset and source PDF (name, SHA-256 and stored copy) are unchanged.
- **Earlier version:** the earlier units file is kept and referenced in `metadata_history`.

The intake is `validated`, still has **no approvals**, and was revalidated with 0 errors and 0 warnings.

### Road map: explicit approval wording (`prior_approval`)

```
decision:                      approved for use in the MSU AI Assistant
decision_date:                 2026-10-13
scope:                         Use of the corrected 2027 road map as a source document for this assistant only.
basis:                         The project owner approved the corrected 2027 road map for use in the MSU AI Assistant on 2026-10-13.
not_claimed:                   This is not an independent verification of the dates and not a formal approval of the road
                               map by the Midlands State University Registry or any other university body.
registry_verification:         not performed
university_registry_approval:  not obtained and not claimed
```

The registry `notes` say the same.
- **Unchanged:** the DRAFT filename `2027 DRAFT ROADMAP fin (1).pdf` and both entries of the correction history.
- **Passages:** the 21 passages are content-identical (same units SHA-256).
- **Status:** `validated`; the formal knowledge-base approval follows staging in 3.4.

### Idempotency on the real KB

Repeating both updates and both validations produced 4 no-ops: the registry is byte-identical and no journal entries were added.

## 3. Tests

`python -m unittest discover -s tests -t .`: **184 tests OK**, in 93 s:
- 75 original;
- 79 knowledge-base tests from Stages 3.1 and 3.3, with one outdated rollback test replaced;
- 30 new in `tests/test_kb_rollback.py`.

| Group (new) | Tests | Covers |
|---|---|---|
| States | 3 | suspended transitions; reinstatement only with the explicit flag; suspended never visible |
| Registry-aware rollback | 4 | suspension; **publish does not bring back rolled-back content**; rolling forward restores; republish with a recorded decision; suspended → withdrawn |
| Reinstatement prevention | 4 | refused without approval with **no change at all**; explicit reinstatement recorded; two-person rule; superseded version reinstated while its successor is suspended |
| Emergency override and reconciliation | 6 | pointer-only move; all 5 blocked operations; divergence reported as warnings; `accept_index`; `restore_registry`; no-op; events recorded |
| Consistency errors | 3 | a registry/index difference is an error (also caught by the post-operation check); frozen-base mismatch; staged documents without a staging version |
| Recovery of the new operations | 3 | crash at begin / after pointer / after registry in a rollback; crash after the emergency pointer switch keeps the override; crash in reconciliation completes |
| Metadata update | 5 | validated → uploaded, units detached and kept, **revalidation required** before staging, only headings change; no-op; forbidden fields and states (staged, approved, published, base); journaled; crash recovery |
| Heading labels | 2 | mapping and fallback; invalid maps rejected |

**Mutation check:** each safeguard was disabled in memory, and the tests failed:
- rollback without registry alignment: 8 of 8 tests fail;
- override that blocks nothing: 1 of 6 (the test that checks all five blocked operations);
- consistency check that always passes: 9 of 9.

The unchanged code passes 30/30.

## 4. Integrity

`python stage3/integrity.py after`: **PASS**.
- 0 of 143 protected files changed or missing.
- git HEAD `eb9ccff` unchanged.
- The new files in protected folders are the 23 Stage 3.1 files plus `tests/test_kb_rollback.py`.

## 5. Files changed or created in Stage 3.3b

| File | Change |
|---|---|
| `src/kb/states.py` | `suspended`, reinstatement path |
| `src/kb/errors.py` | `OverrideActive`, `ReinstatementRequired` |
| `src/kb/adapters.py` | `heading_labels` |
| `src/kb/service.py` | rollback / emergency / reconcile / republish / update_metadata / consistency; content-addressed validation files; `new_version` recovery fix |
| `src/kb/__main__.py` | new CLI commands |
| `tests/test_kb_rollback.py` | new (30 tests) |
| `tests/test_kb_service.py` | outdated rollback test replaced |
| `stage3/run_3_3b.py`, `stage3_3b_results.json`, `stage3_3b_report.md` | new |
| `audit/stage3_architecture_proposal.md` | L12 marked resolved; 3.3b recorded |
| `knowledge_base/registry.json` | `metadata_history`, new units and validation references, road map wording, intake headings |
| `knowledge_base/units/…<sha12>.jsonl`, `knowledge_base/validation/…<sha12>.json` | new revalidation files (earlier files kept) |
| `knowledge_base/ingest_log.jsonl` | + 4 committed operations |

## 6. Remaining limitations and decisions

| # | Item | Proposal |
|---|---|---|
| D1 | **Road map passage text.** The 21 passages contain `STATUS: Approved 2027 road map for this project.`, taken from the corrected dataset. It is accurate, but the assistant could read it as an official approval. Changing it means editing the protected dataset `msu docs/2027/2027_ROADMAP_RAG_Ready_v2.json`, or adding a passage-level text override. | **Decision needed.** Recommended: a Stage 2-style corrected dataset (v3) with the line *"STATUS: Approved by the project owner for use in this assistant; not verified or formally approved by the MSU Registry."*, registered as road map document version 2 before staging. v1 would be rejected, with a reason. |
| L1 | Reconciliation is per mode (accept CURRENT, or restore the registry), not a free per-document choice | Enough for the current workflow; per-document choices can be added for Django |
| L2 | The two-person rule for reinstatement compares with the actor of the last status change | Fine for the current model; Django should map real user identities |
| L3 | Only one test guards each of the five blocked operations under an override | It asserts all five; add per-operation tests if the list grows |
| L4 | Content-addressed validation files accumulate (small JSON) | Harmless; prune with a future archive command if needed |
| L5 | Near-duplicate crowding (271 lexical pairs) | Stage 4 evaluation, as agreed |

**Stage 3.4 readiness.** The safety prerequisites are in place: registry-aware rollback, a guarded emergency path, error-level consistency checks and metadata correction. Before 3.4 the only open item is decision D1.
