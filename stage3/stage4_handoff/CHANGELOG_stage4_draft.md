# Change log: Stage 4 draft, revision 1 → revision 2 (2026-10-13)

The owner's review is applied. **Everything remains DRAFT:** nothing is frozen and nothing has been executed. No change was made to source data, frozen files, retrieval code, prompts, the app, the knowledge base or git.

## A. Answer-key verification: discrepancies found in revision 1

All keys were rebuilt from the registered datasets and frozen yearbook chunks. Each evidence quote is now verified in the registered record **and** on the original PDF page: 97/97 quotes verified (§4.5 of the plan explains the two approved corrections and the page-level limitation). **No discrepancy was found in the source data.** These were errors in my revision-1 keys:

| Q | Revision 1 | Finding | Revision 2 |
|---|---|---|---|
| **I04** | "apply online via www.msu.ac.zw or obtain a form from an Admissions Office" | The advert says to *visit* www.msu.ac.zw *for information* on programmes and how to apply, that applicants *can apply online* **or** obtain a form physically at the Admissions Office of **five named campuses**, and it adds "in addition to the specified 'A' level subjects or diplomas". | Exact wording and all five campuses; misreading "via the website" is listed as forbidden |
| **I06** | January 2027, no basis given | The date is **derived** from the Faculty of Education banner (p. 13), not stated in the programme row (p. 14) | Evidence = banner p. 13 + row p. 14; the key says it is derived |
| **I08** | "duration not stated; must not invent one", for all systems | **The Sciences Yearbook (p. 726) states "3 Years (General), 4 Years (Honours)."** Revision 1 would have penalised a correct, yearbook-sourced answer. Entry rules also differ (advert: Chemistry **with an A**). | Public/baseline: answer from the yearbook. Staging: the advert is silent **and** the yearbook duration, each attributed; the conflict is noted |
| **I09** | omitted the 'A' level rule; one key for all systems | The yearbook (p. 619) has **different** LLB requirements (English B only; 'A' level English Literature or History + two others; ten semesters) and says Kwekwe Campus is *scheduled to host* the Faculty of Law (p. 76) | System-specific keys; conflicting-evidence requirement |
| **I10** | the visiting route omitted its 'O' level requirement and proof of employment; routes summarised in one list | Both routes have the 5 'O' levels incl. Mathematics, English and Combined Science; only -133 has the employment and proof requirements; only -132 has the year-2 ZNQF entry and the 31 March deadline. **The yearbook (p. 692) Visiting School rule differs from the advert's visiting route.** | Two explicitly separate routes; merging = critical K5; yearbook key for public |
| **I11** | advert only | The yearbook (pp. 604–605) gives 1½ years and its own requirement wording | Public/baseline key from the yearbook; staging attributes both |
| I01, I05, I07, C01, C02 | — | Meaning confirmed against record and PDF | Exact wording, evidence attached; C01 gets per-system citations |

## B. Plan and question-set changes

| # | Change | Reason (owner instruction) |
|---|---|---|
| 1 | **System-specific keys** (baseline / public 0005 / staging 0006) for every new question, with behaviour, required, evidence, acceptable citations and forbidden claims | "Define system-specific answer keys and citation expectations" |
| 2 | **Intake keys no longer require refusal merely because the intake is unpublished:** public/baseline expect an answer or partial answer where the yearbooks contain the facts (I04, I08, I09, I10, I11, partly I01 and I07), and `not_available` only where nothing exists | "Do not automatically require refusal…" |
| 3 | **Exam equivalence rules** for R05, R08, R11: identical dates are acceptable only with the correct calendar or student group; otherwise partial credit | owner instruction on equivalent records |
| 4 | **Mining:** conventional and visiting routes defined separately (§4.4); merging is a critical failure | owner instruction |
| 5 | **Duplicates:** X01/X02 removed as separate items and kept only as aliases of O4/O5 in `overlap_cases`; aggregates count O4/O5 once; staging runs of O4/O5 are reported separately | owner instruction |
| 6 | **Readable copy** of the 35 frozen questions and A1–A5 (`regression_review_copy.md`); the frozen file is unchanged (SHA-256 recorded) | owner instruction |
| 7 | **Complete blind-grading rubric** (§5): correctness, completeness, attribution, unsupported claims (critical vs minor), refusal (appropriate / inappropriate / failed), conflicting evidence; overall-label rules; CRITICAL flag; blinding commitment | owner instruction |
| 8 | **Exact call matrix** (§6): 154 calls; 158 is a planning ceiling only; duplicate effect explained; no automatic retries (`max_retries` = 0) | owner instruction |
| 9 | **Go/no-go criteria** (§7): critical K1–K7 (any one = no-go) separated from non-critical N1–N6 thresholds; a separate intake-readiness decision | owner instruction |
| 10 | Approved road map dates carry two evidence items: the approved value (record) and the printed original (PDF), with "unverified" wording forbidden in answers | consistency with the owner's approval of the corrected dates |
| 11 | Extra traps: I04 postgraduate procedure (Humanities pp. 141–142) used for undergraduates; R10 orientation vs tuition; R12 online learning vs break; I12/I11/I15 sibling-record citations | found during verification |
| 12 | `build_stage4_questions.py` rewritten: verifies every quote and writes the evidence table and the regression copy; reports discrepancies instead of correcting anything | owner instruction |

## C. Known limitations (stated in the plan)

- Evidence verification is page-level; identical text in two rows of one page (main vs block release examination dates) cannot be separated by it. This is flagged as a caution on RM2027-13.
- Yearbook evidence for the public/baseline keys was located by text search of the frozen chunks, not by running retrieval. Whether retrieval actually surfaces those passages is measured in Stage 4 step 2.

---

# Freeze preparation and freeze (2026-10-13)

The owner accepted draft revision 2 for freeze preparation, subject to safeguards.

| # | Change | Reason |
|---|---|---|
| 13 | Plan → **revision 3**. §10 adds binding safeguards: answer isolation; historical yearbook vs approved 2027 advert (an older requirement presented as overriding the advert = critical unsupported claim and mishandled conflict); critical failure = no-go for the run plus written diagnosis; no tuning or editing on results (corrections only via a new, re-frozen version, never pooled); reproducibility checks before every run. The §5 critical-claim definition now includes the yearbook-override case. | owner safeguards |
| 14 | The frozen set is **split** into `stage4_questions.json` (id, set, category, question, systems only) and `stage4_answer_keys.json` (all keys, evidence, passage IDs, forbidden claims, notes, frozen regression keys) | answer isolation |
| 15 | `stage4/run_retrieval_only.py`. It reads only the questions file and never references the keys file. It refuses to start on any hash or pointer mismatch, any non-question field or key pattern in the questions file, or an existing output folder. It has a `--check-only` mode, asserts no LLM module is imported, and re-hashes the knowledge base after a run. | isolation, reproducibility |
| 16 | `stage4/freeze_stage4.py` with checks F1–F7 (byte-identical rebuild, counts and IDs, key completeness, source references in each system's index, call matrix, isolation, plan safeguards). It refuses to write on any failure and refuses to overwrite a different frozen set. | owner instruction |
| 17 | **F3 checker correction.** The first freeze attempt was correctly **refused**: F3 required a `sufficient` field for O1–O5. The frozen file defines out-of-scope questions by category plus a `check` note instead. F3 now requires the `check` note for them, and the keys file records their expected behaviour as `decline`. The frozen regression file is unchanged; the error was in my checker. | found by the freeze checks |
| 18 | Per-system call split corrected in the freeze check: baseline 44, public 74, staging 36 (total unchanged at 154) | arithmetic in my first version of the check |
