# Stage 4 evaluation plan: revision 3 (prepared for freeze)

**Status:** revision 3. The question set and answer keys of draft revision 2 were accepted for freeze preparation on 2026-10-13; revision 3 adds the owner's safeguards (§10). It is frozen only by `stage4/freeze_stage4.py` once all freeze checks pass. **No retrieval or generation run has been executed, and no Groq API call is authorised.** Changes are listed in `CHANGELOG_stage4_draft.md`.

**Files in `stage3/stage4_handoff/`:**
- `stage4_questions_draft.json`: draft questions and system-specific answer keys, with verified evidence.
- `stage4_answer_evidence.md`: every evidence quote with its verification result.
- `regression_review_copy.md`: readable copy of the 35 frozen regression questions and A1–A5. The frozen file is unchanged.
- `build_stage4_questions.py`: rebuilds and re-verifies the three files above from the registered data.

## 1. Objective

The evaluation answers two separate questions with evidence:

1. **Stage 5 go/no-go:** can public version **0005** (yearbooks + 2027 road map) replace `faiss_store_v2` in the assistant?
2. **Intake readiness:** is the staged intake (staging **0006**) ready for the owner's publication decision? This is a separate decision; it does not authorise publication.

## 2. Systems

| Code | Index | Retrieval | Content |
|---|---|---|---|
| **baseline** | `faiss_store_v2` | `Stage6Retriever("main")` (accepted Stage 6) | yearbooks |
| **public** | knowledge base `CURRENT` = 0005 | `PublicRetriever`, same accepted settings | yearbooks + 2027 road map |
| **staging** | knowledge base `STAGING` = 0006 | `StagingRetriever` (administrator) | yearbooks + road map + staged intake |

**Generation settings:**
- model `openai/gpt-oss-20b`, temperature 0;
- frozen prompt `s7-0-baseline-v1`, unchanged (it says "MSU yearbooks"; its effect is measured, and any change is Stage 5);
- `max_retries` set to 0 for the evaluation, so no automatic retries.

## 3. Question sets and duplicates

| Set | IDs | Count | Notes |
|---|---|---|---|
| Frozen regression | N/E/C/O from `eval/stage5_questions.json` | 35 | unchanged; keys are the frozen "sufficient" text and pages; see `regression_review_copy.md` |
| Ambiguous code | A1–A5 | 5 | the answer must mention every meaning in the ambiguity note, or ask which programme applies |
| Road map | R01–R13 | 13 | system-specific keys (§4) |
| Intake | I01–I15 | 15 | system-specific keys (§4) |
| New out of scope | X03–X06 | 4 | must decline; X04 and X06 are near-domain traps |
| Overlap cases | O4 (= X01 UK visa), O5 (= X02 gym) | 2 | **unchanged frozen questions**, counted once (as O4/O5) in every aggregate; also run on staging and **reported separately** |
| Cross-document | C01–C02 | 2 | yearbook + intake |
| **Unique questions** | | **74** | |

**Duplicates.** X01 and X02 were identical to the frozen O4 and O5. They are no longer separate questions: `X01` and `X02` remain only as aliases in `overlap_cases`. Aggregate metrics use O4/O5 once per system. The extra staging runs of O4/O5 appear in a separate overlap table and never enter a total twice.

## 4. Answer keys

Each question has a key **per system**:

| Field | Meaning |
|---|---|
| `behaviour` | `answer`, `partial`, `not_available` or `decline` |
| `required` | elements a sufficient answer must contain |
| `evidence` | verbatim quotes with `passage_uid`, PDF page and citation, each verified in the registered record **and** on the original PDF page |
| `acceptable_citations` | citations that count as correct attribution |
| `forbidden` | claims that are unsupported-claim failures |
| `full_credit`, `partial_credit` | where the line needs to be explicit |

### 4.1 Intake questions: unpublished does not mean "refuse"

The public and baseline keys distinguish between information that is **genuinely unavailable** and **facts that already exist in the yearbooks**:

| Question | Public / baseline expectation | Yearbook evidence (verified) |
|---|---|---|
| I01 fee | `partial`: amount not available; "application fees are non-refundable" acceptable | Humanities p. 130 |
| I02 bank accounts, I03 contacts, I05/I06/I13 start dates, I14 modes | `not_available` | none |
| I04 how to apply | `partial`: general procedure (Admissions Office in hard or soft copy, or online platform) | Humanities p. 129 (pp. 141–142 are **postgraduate**: an attribution trap) |
| I07 HEEE start and deadline | `not_available` (the 5-year duration may be cited) | Sciences p. 636 |
| **I08 Biomedical duration** | **`answer`: 3 years (General), 4 years (Honours)** | Sciences p. 726 |
| **I09 LLB** | `partial`: English Language B at 'O' level; 'A' level English Literature or History plus two others; ten semesters; "Kwekwe Campus … scheduled to host the Faculty of Law" acceptable with that wording | Humanities pp. 619, 76 |
| **I10 Mining Engineering** | **`answer`** from the yearbook: normal, special and visiting entry, kept distinct | Sciences p. 692 |
| **I11 M.Ed. Food Technology** | **`answer`**: 1½ years; BEd or equivalent, or a degree/PGDE | Humanities pp. 604–605 |
| I12 MA Museum Studies | `not_available` (the yearbook refers to the general regulations) | Humanities p. 162 |
| I15 HEEE visiting route | `not_available` for the visiting route (general 5-year rules only if labelled as such) | Sciences p. 636 |

**Staging keys** require the advert facts and, where the yearbook also applies, **correct attribution of each source**.

### 4.2 Conflicting or complementary evidence (staging)

| Case | Advert (2027) | Yearbook | Requirement |
|---|---|---|---|
| I08 Biomedical | duration not stated; 'A' level Chemistry **with an A** + any two of Mathematics, Physics, Biology | 3 years (General) / 4 years (Honours); 'A' level Chemistry + two of Biology, Mathematics, Physics | give the yearbook duration **and** say the advert does not state one; attribute each entry rule |
| I09 LLB | 'O' level **Mathematics and** English Language at B or better; Kwekwe Conventional; 5 years | 'O' level English Language at B or better; ten semesters | point out the difference; attribute each |
| I10 Mining (visiting) | National Diploma in Mining, Geology, Survey or relevant + currently employed in mining | Visiting School: 'A' level Mathematics, Physics, science + 'O' level Mathematics and English + employment within the minerals industry | attribute each; never merge |
| I11 M.Ed. Food Technology | list of qualifying degrees (BSc Education, BEd, BSc + PGDE, Grad DE, Grad CE …) | BEd or equivalent, or a degree/PGDE | complementary wording; attribute |
| C01 refunds | non-refundable | non-refundable | either citation correct |

### 4.3 Road map examination questions (equivalent records)

**R05, R08 and R11** have rows with **identical dates** in the other calendar:

| Question | Pair |
|---|---|
| R05 | RM2027-07 main ↔ RM2027-17 block release |
| R08 | RM2027-13 main ↔ RM2027-21 block release |
| R11 | RM2027-17 block release ↔ RM2027-07 main |

- **Full credit:** the correct dates **and** the correct calendar or student group, or both calendars correctly distinguished.
- **Partial credit:** correct dates attributed only to the other calendar, or no calendar identified.

**Identical dates alone are never proof of a fully correct answer.** Related traps:
- R10: orientation 5/01/2027 vs face-to-face tuition 5/01–8/01/2027;
- R12: online learning vs the semester break starting the same day;
- R02 and R13: conventional vs block release orientation.

### 4.4 Mining Engineering (I10)

| Route | Record | Duration and mode | Requirements |
|---|---|---|---|
| **Conventional** | MSU-JF2027-132 | 4 years, Zvishavane Conventional | 5 'O' levels incl. Mathematics, English, Combined Science; 'A' level Mathematics, Physics + another science; National Diploma holders may enter year 2 (ZNQF); deadline 31 March 2027 |
| **Visiting** | MSU-JF2027-133 | 3 years, Zvishavane Visiting | 5 'O' levels incl. Mathematics, English, Combined Science; National Diploma in Mining, Geology, Survey or other relevant diploma; currently employed in the mining industry; proof of employment |

**Never merge the routes.** Attributing any requirement of one route to the other is a **critical failure (K5)**. In public, the yearbook's normal, special and visiting entry must likewise stay distinct.

### 4.5 Evidence verification and its limits

- **Result:** 97 quotes checked; 97 verified in the registered record and on the PDF page.
- **Approved corrections:** for RM2027-11 and RM2027-13, the approved values (13/09/2027–17/09/2027; 01/11/2027–12/11/2027) are verified in the registered record. They are *not printed in the PDF* by design; the printed originals (13/09/**2026**…, …12/11/**202**) are verified separately.
- **Limitation:** verification is **page-level**. Where two rows on a page carry identical text (the main vs block release examination dates), a page match cannot tell which row printed it. The RM2027-13 approved date matches the page only because the block release row RM2027-21 carries the same text, and this is marked as a caution in the JSON. Row-to-event association was verified row by row in Stage 2.

## 5. Blind-grading rubric

The grader (the project owner) sees: the question, the system-specific key (required, forbidden, acceptable citations), the answer, and the passages that were given to the model, shown with their citations. System labels are hidden, and the order is randomised.

**Before grading starts:**
- a blinding commitment records the SHA-256 of the label mapping, as in S7-1;
- the automatic checks (retrieval metrics, citation matching, isolation and forbidden-string scan) run first and are shown to the grader as hints, never as grades.

| Dimension | Scale | Definition |
|---|---|---|
| **Correctness** | 2 correct / 1 partly correct / 0 incorrect | the facts stated match the key (for `not_available` or `decline` keys: correctly says the information is not available) |
| **Completeness** | 2 all required elements / 1 some / 0 none | against `required`; for `not_available` keys, 2 = clearly says what is missing without inventing |
| **Source attribution** | 2 correct / 1 partly / 0 wrong or missing | each fact cited to a passage that contains it and whose citation is in `acceptable_citations`; citing a sibling record (for example a near-duplicate programme) = 1 |
| **Unsupported claims** | count, each marked *critical* or *minor* | a claim not supported by the cited evidence, or listed in `forbidden`. **Critical:** any wrong or invented date, fee, account number, contact, entry requirement, duration, campus or mode; a citation to a passage that does not contain the claim; **or a historical yearbook requirement presented as the current 2027 requirement where the approved 2027 intake advert differs, or presented as overriding it.** **Minor:** harmless paraphrase or extra context. |
| **Refusal** | appropriate / inappropriate refusal / failed refusal / n.a. | *Inappropriate refusal:* the key expects `answer` or `partial` but the system declines. *Failed refusal:* the key expects `decline` or `not_available` but the system supplies substantive content or cites loosely related passages as support. |
| **Conflicting evidence** | handled / partly / mishandled / n.a. | *Handled:* both sources named, the difference stated, and nothing presented as agreed when it is not. *Mishandled:* one source silently chosen, or the sources merged. |

**Overall label** (derived from the dimensions):

| Label | Condition |
|---|---|
| **Sufficient** | Correctness 2, Completeness ≥ 1, Attribution ≥ 1, no unsupported claims, Refusal appropriate or n.a., Conflict handled or n.a. |
| **Partially sufficient** | Correctness ≥ 1, no critical unsupported claim, and not Sufficient |
| **Insufficient** | Correctness 0, or any critical unsupported claim, or a failed refusal, or a mishandled conflict on a fact the question asks about |
| **CRITICAL flag** | added independently to any answer containing a K-failure (§7) |

## 6. Generation-call matrix (planning ceiling, not authorisation)

| # | Questions | Systems | Calls |
|---|---|---|---|
| 1 | 35 frozen regression (includes O4, O5) | baseline, public | 70 |
| 2 | A1–A5 | baseline, public | 10 |
| 3 | O4, O5 (overlap cases) | staging | 2 |
| 4 | R01–R13 | public, staging | 26 |
| 5 | I01–I15 | public, staging | 30 |
| 6 | X03–X06 | baseline, public, staging | 12 |
| 7 | C01–C02 | public, staging | 4 |
| | **Total** | | **154** |

**How duplicates affect the count:**
- The earlier draft counted 158 calls. It ran X01/X02 on three systems (6 calls) although they duplicate O4/O5, which row 1 already runs on baseline and public.
- Removing that duplication saves 4 calls, keeping only the staging runs of O4/O5 (row 3): 158 − 6 + 2 = **154**.
- **Ceiling: 158 calls** (planning only). The 4-call margin is **not** an automatic retry budget.

**Not in the matrix:**
- Intake on baseline: its key equals the public key, and public differs from baseline only by the road map.
- Road map on baseline: the key expects `not_available`. This optional control would add 13 calls and needs separate approval.

**Execution rules (when authorised):**
- one run at temperature 0;
- **no automatic retries**: any failed call is logged and reported, and a rerun needs explicit approval;
- the matrix, question SHA-256 and call log are written before and after the run;
- estimated volume about 3,000 tokens per call, roughly 0.46 million tokens.

## 7. Go / no-go criteria for Stage 5

### Critical failures: any single occurrence on **public** means **no-go**

| ID | Failure |
|---|---|
| K1 | **Isolation leak:** a public answer or citation contains an intake-only fact or an intake passage |
| K2 | **Critical unsupported claim** (as defined in §5) in any public answer |
| K3 | **Approved-date error:** R07 or R08 gives 13/09/2026, "12/11/202", or calls the approved dates unverified or uncertain |
| K4 | **Failed refusal** on any out-of-scope question (O1–O5, X03–X06), including citing the road map for the gym question |
| K5 | **Route merge** in I10 or I15 (applies to the staging intake-readiness decision; in public, merging the yearbook's normal, special and visiting entry) |
| K6 | **Regression collapse:** a frozen regression question graded Sufficient on baseline is Insufficient on public |
| K7 | **Integrity failure during the evaluation:** `kb.verify()` not OK, `CURRENT`/`STAGING` changed, or any protected-file hash changed |

### Non-critical criteria: reported; each must meet its threshold for "go"

| ID | Measure | Threshold |
|---|---|---|
| N1 | Retrieval regression: in-scope frozen questions with top 5 identical to baseline | ≥ 95% (Stage 3.4: 100%); every difference explained |
| N2 | Hit@5 of the expected passages: road map on public; intake on staging | ≥ 12/13; ≥ 14/15 (Hit@1 and MRR reported) |
| N3 | Answer quality | road map on public: ≥ 11/13 Sufficient; frozen regression: at most 1 question downgraded Sufficient → Partially sufficient |
| N4 | Source attribution | ≥ 90% of answered public questions with attribution score 2 |
| N5 | Ranking differences | crowding and equivalent-record cases (R05, R08, R11, I10, I11, I12, I15), the gym and visa retrieval, and Hit@1 below rank 1: **reported, non-blocking** unless they cause a K-failure or an N3 shortfall |
| N6 | Latency | public median end-to-end ≤ baseline median + 15% |

**Decision rule:** **Go** = 0 K-failures on public **and** all N1–N4 and N6 thresholds met. Otherwise **no-go**, with the failing items listed.

### Intake readiness: a separate decision for the owner, not a publication

| Measure | Requirement |
|---|---|
| Critical failures | 0 (K1 n.a.; K2, K4, K5 apply to staging answers) |
| I01–I15 graded on staging | ≥ 13/15 Sufficient |
| I08, I09, I10 | must be Sufficient (they test conflicting-evidence handling and route separation) |
| Overlap case O4 on staging | must decline (no MSU application steps given as visa advice) |

## 8. Procedure (each step stops for owner review)

1. Owner review of this draft, then **freeze**: `stage4_questions.json` + SHA-256 + blinding commitment.
2. Retrieval-only run (no API calls): N1, N2, isolation, flagged cases.
3. Generation run per §6, only after explicit authorisation of the call count.
4. Automatic checks, then blind grading by the owner (§5).
5. Report: go / no-go (§7) and intake readiness.

## 9. Constraints (unchanged)

**Not modified:**
- frozen research artefacts (`faiss_store/`, `faiss_store_v2/`, `eval/` stages 5–7, the main notebook, the Stage 6 modules);
- the prompt, the retrieval algorithms, the app and the knowledge base.

Stage 4 outputs go to a new `stage4/` folder. Nothing is committed or pushed without approval.

## 10. Safeguards (binding for every Stage 4 run)

1. **Answer isolation.**
   - **Two files.** The frozen set is split in two:
     - `stage4/frozen/stage4_questions.json` holds only question IDs, set, question text and the systems that run each question;
     - `stage4/frozen/stage4_answer_keys.json` holds keys, evidence, expected passage IDs, forbidden claims, grading notes, tags, the ambiguity notes and the frozen regression keys.
   - **Who reads what.** The retrieval and generation runners read **only** the questions file and never open the keys file. The runner refuses to start if the questions file contains any key field, passage ID or key text. The keys file is read only by the scoring step after a run, and by the grader.
   - **What the model sees.** The prompt contains only the question and the retrieved evidence (frozen prompt `s7-0-baseline-v1`).
2. **Historical yearbook requirements vs the approved 2027 intake advert.**
   - Answers must keep them distinct and attributed. Conflicting requirements must never be silently merged.
   - An older (yearbook) requirement must never be presented as overriding the 2027 advert. Doing so is a *mishandled conflict* and a *critical unsupported claim* (§5, K2).
   - In public 0005, where the advert is unpublished, yearbook facts are acceptable **only** when attributed to the yearbook and not presented as 2027 requirements.
3. **Critical failure means no-go for that run.** Any K-failure (§7) makes the current evaluation run a no-go and requires a written diagnosis (cause, affected questions, evidence) before any further run is proposed.
4. **No tuning on results.**
   - The retrieval system, prompts and settings are not changed in response to Stage 4 results.
   - The frozen questions, keys and plan are not edited. Any correction requires a new, separately approved and re-frozen version (`stage4_questions_v2`), and results from different versions are never pooled.
5. **Reproducibility.** The frozen files are canonical JSON with recorded SHA-256. Each run first re-verifies the hashes, the knowledge-base pointers and manifests, `faiss_store_v2` and the retrieval code, and stops on any mismatch.
