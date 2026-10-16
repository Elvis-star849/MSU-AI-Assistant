# GPT-OSS-120B vs GPT-OSS-20B: integration and evaluation report

**Date:** 2026-10-14
**Status:** complete. Both models ran on the same 40 frozen held-out questions with byte-identical evidence. Answers were graded blind under the frozen rubric.
**Changes:** uncommitted and left for review. Nothing committed, pushed or deployed. `GROQ_MODEL` is still `openai/gpt-oss-20b`.

## 1. Executive summary

- **GPT-OSS-120B did not perform better.**

  | | GPT-OSS-20B | GPT-OSS-120B |
  |---|---|---|
  | Sufficient | 34/40 (85.0%) | 31/40 (77.5%) |
  | Partially sufficient | 6 | 9 |
  | Insufficient | 0 | 0 |
  | Critical unsupported claims | 0 | 0 |
  | Correct abstentions | 6/6 | 6/6 |

- **The difference is within run-to-run noise.** It is 3 questions on a sample of 40, and every disagreement comes down to one minor issue: a small unsupported descriptor or a misread table row. Earlier work measured a 0.318 run-to-run flip rate for 20B on this set. The fair reading is **no measurable accuracy gain from 120B**, not "20B is better".
- **Where 120B was better:**
  - It cited evidence by number in 100% of answers that should be answered, against 94.1% for 20B.
  - Its graded attribution was correct in 100% of those answers, against 88.2%.
  - Its answers were longer and more structured, with tables and explicit advert-vs-yearbook notes.
- **Where 120B was worse:**
  - It added more small unsupported details: 8 answers against 4.
  - It sometimes quoted its own instructions to the user ("developer instruction", "rule 9"; 3 answers, none for 20B).
  - It is slower: median generation 1.00 s against 0.64 s, p95 2.54 s against 1.49 s.
  - It costs about 1.5× as much: US$0.0221 against US$0.0144 for the 40 questions.
- **Recommendation: Option A.** Keep GPT-OSS-20B as the default and leave GPT-OSS-120B as an optional, tested alternative.

## 2. Files modified (all uncommitted)

| File | Change |
|---|---|
| `src/llm/config.py` | `load_config(..., model_env=None)` reads `GROQ_MODEL_2` (or `GROQ_MODEL_<n>`) only when selected. Adds `ModelSelectionError` and `LLMConfig.model_env`. The default path is unchanged. |
| `src/llm/__init__.py` | Exports `ModelSelectionError`. |
| `src/assistant.py` | `Assistant.create(..., model_env=None)`. Adds `generation_settings()`: a selected model changes only `model`. Adds `selected_model_env()` (`MSU_ASSISTANT_MODEL_ENV`). The configuration is checked before index loading. |
| `app.py` | Optional `MSU_ASSISTANT_MODEL_ENV` and the secrets bridge for `GROQ_MODEL_2`. An invalid selection stops with a clear message. The About text names the active model. The default call is unchanged. No UI redesign. |
| `healthcheck.py` | `--model-env`. An explicitly selected model that is missing makes the check unhealthy. |
| `.env.example` | `GROQ_MODEL_2=openai/gpt-oss-120b` |
| `.env` | Not modified. It already contained `GROQ_MODEL_2=openai/gpt-oss-120b`. |
| `DEPLOYMENT.md` | The new variables, the health-check command and the test count. |
| `tests/test_model_selection.py` | New: 15 tests. |
| `evaluation/gpt_oss_comparison/*.py` | New: `smoke_test.py`, `run_comparison.py`, `evidence_check.py`, `grade_and_score.py`. |
| `evaluation/results/gpt_oss_comparison/` | New: all results (§16). |

Unchanged:
- FAISS, BM25, hybrid routing, reranking and embeddings;
- the prompts (`src/c3_candidate.py` is still byte-identical to the frozen candidate);
- knowledge bases 0005 and 0006 and their pointers;
- the frozen questions, keys and earlier results.

## 3. Configuration and integration

```env
GROQ_MODEL=openai/gpt-oss-20b        # unchanged default
GROQ_MODEL_2=openai/gpt-oss-120b     # optional; used only when selected
```

To select the second model:
- CLI tools: `--model-env GROQ_MODEL_2`
- Python: `load_config(model_env="GROQ_MODEL_2")` or `Assistant.create(model_env="GROQ_MODEL_2")`
- App: `MSU_ASSISTANT_MODEL_ENV=GROQ_MODEL_2`

**Errors:**
- An unknown variable name, or a selected variable that is unset or blank, raises a clear `ModelSelectionError`. The app never silently falls back to another model.
- No model identifier is hard-coded in the selection logic.

**Generation settings, identical for both models:**
- temperature 0;
- reasoning effort medium;
- 4,096 completion tokens;
- `include_reasoning=False`.

## 4. Smoke-test results

| | Before enablement (earlier today) | After enablement |
|---|---|---|
| HTTP status | 403 `model_permission_blocked_org` | **200** |
| Returned model | — | **`openai/gpt-oss-120b`** |
| Answer | none | "Second-quarter face-to-face tuition runs from **12 April 2027** to **21 May 2027** on the **Main academic calendar (First Semester)**【Evidence 1, MSU 2027 Road Map, p. 1】." Correct and cited. |
| Model latency / pipeline latency | — | 0.99 s / 1.88 s |
| Tokens | — | 2,414 prompt, 167 completion (99 reasoning); Groq compute 0.47 s |
| Request ID | `req_01m4wsf0zae8sa9ecz1bfdxmgq` and two others | `req_01m4wvbqksevnavepgpwby0z4e` |

**All five checks pass:**
1. The request reaches Groq.
2. The returned model is 120B.
3. The answer is usable.
4. Grounding and citation work: Evidence 1 is cited and no safeguard note fired.
5. The answer was rendered through the assistant pipeline: profile `c3_public_0005`, all 5 sources attached.

**Account rate limits** (from the 120B response headers): 500,000 requests per day and 250,000 tokens per minute. These are the same Developer-plan limits as 20B.

`smoke_test_GROQ_MODEL_2.json` now holds the successful run. The earlier 403 is preserved in `GROQ_MODEL_2/api_errors.jsonl` and `comparison_status.json`.

## 5. Evaluation methodology

**Dataset:** the remediation held-out set v1, 40 questions in 8 strata:
- 18 public questions on KB 0005;
- 22 intake questions on KB 0006;
- questions `88a0ba05…`, keys `2fbe4971…`; keys frozen before any held-out generation.

The questions and keys were not modified. The set runs on the Stage 6 best retrieval configuration (routed hybrid → top 10 → MiniLM → top 5). It was already consumed by the pre-registered HO1 evaluation, with results published, so no unreleased holdout was compromised. That earlier use is a limitation shared equally by both models. The separate Stage 6 retrieval holdout (`eval/stage6/holdout_questions.json`) has only a retrieval-sufficiency key, so it is not suited to grading answers.

**Identical evidence:**
- Retrieval was done once and frozen in `HO_S_C3_inputs.json` (sha256 `21f6f2ce…`). Both models received those byte-identical messages.
- `evidence_check.py` re-ran the app's own retrievers, query clean-up and C3 message builder offline. All 40 messages matched (`evidence_references.json`).
- **MRR@5 = 0.787** on this evidence. This is a retrieval metric, identical for both models by construction, and says nothing about LLM quality.

**Passes:**
- The 20B pass (`GROQ_MODEL`) and the 120B pass (`GROQ_MODEL_2`) ran back to back on 2026-10-14, one answer per question.
- Pacing was 3 s between calls; up to 3 retries with backoff were allowed.
- No retries were needed.

**Grading:** the frozen Stage 4 §5 rubric, unchanged.
- Correctness, completeness and attribution, each scored 0–2.
- Unsupported claims, each marked minor or critical.
- Refusal and conflict handling.
- "Any unsupported claim prevents Sufficient."
- The HO1 conventions were applied, for example:
  - an invented "2027 yearbook" date counts as minor;
  - yearbook rules framed as an "alternative" count as minor;
  - an unsupported claim that a differently titled yearbook programme is the same programme counts as minor.

**Blinding:**
- Each of the 80 answers had a random label, and the two answers to each question were shown in random order.
- The label mapping was sealed and hash-committed before grading (`blind/mapping_commitment.json`).
- The grades were hash-committed before unsealing (`blind/grades_commitment.json`).
- The grader's input is kept verbatim in `blind/grades_input.jsonl`.

Grading was AI-assisted (Claude), by one grader, with no owner review.

**Failure source:** every answer that was not fully sufficient was classified as a retrieval or generation failure, using the frozen retrieval report (`target_in_top5`).

## 6. Accuracy comparison

| Metric | GPT-OSS-20B | GPT-OSS-120B |
|---|---|---|
| Questions completed | 40/40 | 40/40 |
| Correct answers (sufficient) | **34 (85.0%)** | 31 (77.5%) |
| Partially correct | 6 | 9 |
| Incorrect answers (insufficient) | 0 | 0 |
| Answers with unsupported claims | **4** (all minor) | 8 (all minor) |
| Critical unsupported claims | 0 | 0 |
| Citation accuracy: graded attribution fully correct (answer items) | 88.2% | **100%** |
| Answer items citing an evidence number | 94.1% | **100%** |
| Citations pointing to an existing passage | 100% | 100% |
| Correct abstentions (6 decline/not-available items) | 6/6 | 6/6 |
| Failed or inappropriate refusals | 0 / 0 | 0 / 0 |
| Mishandled conflicts | 0 | 0 |
| Average generation latency | **0.77 s** | 1.28 s |
| Median generation latency | **0.64 s** | 1.00 s |
| P95 generation latency | **1.49 s** | 2.54 s |
| Average prompt tokens | 1,917 | 1,917 (identical inputs) |
| Average completion tokens | 337 | 353 |
| Average reasoning tokens | 216 | 183 |
| Total tokens | 90,172 | 90,792 |
| Cost (40 questions) | **US$0.0144** | US$0.0221 |
| API errors during the pass | 0 | 0 (one earlier 403 from the blocked gate call) |

**By stratum (sufficient / n):**

| Stratum (area) | 20B | 120B |
|---|---|---|
| S1 prerequisite tables | 4/5 | 4/5 |
| S2 multiple routes (admissions) | 4/6 | 4/6 |
| S3 ambiguous durations | **5/5** | 2/5 |
| S4 commencement dates | 4/5 | 4/5 |
| S5 yearbook vs advert (multi-document, admissions) | 2/4 | 2/4 |
| S6 academic calendar | 4/4 | 4/4 |
| S7 ordinary control | 7/7 | 7/7 |
| S8 decline | 4/4 | 4/4 |

The whole gap comes from S3. On H12, H13 and H15, 120B added a small unsupported detail: "full-time", a duration-to-mode mapping the advert does not make, or "the same programme". On both public and intake questions the models are otherwise equal.

**Questions where the outcome differed:**
- **120B better on 3:**
  - H05: 20B wrote "2027 yearbook";
  - H09: 20B wrote "full-time";
  - H24: 20B overstated the advert's O-level Maths requirement.
- **20B better on 6:**
  - H02: 120B misread a table row;
  - H11 and H13: 120B wrote "full-time";
  - H12: 120B claimed "the same programme";
  - H15: 120B made a duration-to-mode mapping;
  - H25: 120B misstated the advert difference.

## 7. Grounding and hallucination analysis

- **Neither model made a critical claim:** no wrong dates, entry requirements, durations, campuses or modes, and no yearbook rule presented as overriding the 2027 advert.
- **All unsupported claims were minor.** The descriptors added were "full-time" (one 20B answer, two 120B), "2027 yearbook", "main academic calendar", and duration-to-mode mappings.
- **120B surfaces its instructions** ("as per the developer instruction", "according to rule 9") in 3 of 40 answers; 20B never did. This is not a factual error, but it reads oddly to students.
- **Both models sometimes write "the documents you provided"** (5 answers in total; 4 of them 120B). The app's existing `present_answer` wording correction already rewrites this phrasing for users.
- **Retrieval vs generation:**
  - Only H02 involves a retrieval miss: the Computer Science table was not retrieved.
  - On H02, 20B said cautiously that no prerequisite is given (sufficient); 120B read a cut-off row of another table as the answer (partial).
  - H07, where one advert route was not retrieved, limited both models equally.
  - Every other shortfall is a generation issue.
- **Multi-document reasoning (S5):** equal at 2/4. Both models label the 2027 advert as current and the yearbook as older. Both had one answer framing the yearbook as an alternative (H23).

## 8. Citation reliability

- 120B's citations were more consistent: an evidence number on every answer that should cite one, and fully correct attribution on every graded item.
- 20B gave two answers with no evidence number:
  - H34 cited the yearbook page by name only;
  - H02 was a cautious no-information answer.
- One 20B answer's only numeric citation (H23, Evidence 4) did not contain the cited requirement.
- In the app, a missing number triggers the "no evidence citation" note. This is the one dimension where 120B was clearly better, but it did not translate into more correct answers.

## 9. Performance and token usage

| | 20B | 120B |
|---|---|---|
| Retrieval (model-independent, offline, 40 questions) | mean 777 ms, median 782 ms | same |
| Generation, client wall time: mean / median / p95 | 0.77 / 0.64 / 1.49 s | 1.28 / 1.00 / 2.54 s |
| Groq-reported compute time, mean | 0.49 s | 0.99 s |
| Estimated end-to-end, median (retrieval + generation) | ≈ 1.4 s | ≈ 1.8 s |
| Completion / reasoning tokens, mean | 337 / 216 | 353 / 183 |
| Longest completion | 1,465 tokens | 1,045 tokens |
| Answer length, mean | 457 characters | 654 characters |

- Prompt tokens are identical because the inputs are identical; all usage figures come from Groq's own response data.
- 120B uses fewer reasoning tokens but writes longer visible answers.
- At these volumes, both models cost a fraction of a cent per question.

## 10. Groq API reliability and limits

- **120B was blocked at the organisation level** (HTTP 403) until it was enabled today. Since then: 1 smoke call and 40 evaluation calls, all HTTP 200, with no rate-limit errors, timeouts, retries or other failures.
- **20B:** 40 evaluation calls with no errors, plus about 22 calls for the smoke test, health check and browser E2E, also without errors.
- **Limits** (actual response headers, both models): 500,000 requests per day and 250,000 tokens per minute. The evaluation used at most about 2.6 k tokens per call at a 3 s pace, far below the limits.
- **Total live spend for this evaluation:** about US$0.04. That covers both passes (US$0.0365) plus the smoke tests, health check and browser E2E.

## 11. Automated test results

| Suite | Result |
|---|---|
| `python -m unittest discover -s tests -t .` | **240 run, 240 passed, 0 failed** (re-run after the evaluation; 194 s) |
| `remediation/tests/test_candidate.py` | 11 passed |
| `healthcheck.py --url http://127.0.0.1:8502 --live-llm` | healthy |
| `scripts/e2e_live_ui.py` (live browser, default 20B) | **20/20 passed**. Covers citation display, Sources, and not-found answers with no Sources and no Technical details. |

The 15 new tests in `tests/test_model_selection.py` cover:
- `GROQ_MODEL_2` read from the environment and from `.env`;
- the default unchanged;
- explicit selection switches only the model;
- a missing optional variable is harmless;
- a missing or invalid selection gives a clear error before index loading;
- the key is never exposed;
- both models get the same retriever, prompt builder, prompt version and settings apart from `model`;
- the app stops cleanly on an invalid selection.

## 12. Three detailed answer comparisons

### H02 (public, S1 table): retrieval miss; 20B handled it better

- **Question:** Does HCSCI237 Data Communications and Computer Networks have a prerequisite in the BSc Honours in Computer Science?
- **Expected:** no prerequisite is listed for HCSCI237 (CS table, Sciences Yearbook Vol. 2, p. 898).
- **Evidence:** the CS p. 898 table was **not** retrieved. Evidence 5 is the CS Level 4 table, where "(HCSCI237)" appears only as the prerequisite of HCSE433, on a row cut off as "IoT and Cloud Systems Engineering (HCSCI237)". Evidence 4 is the Computer Systems Engineering table.
- **GPT-OSS-20B:** "The documents provided do not contain any information about a prerequisite for HCSCI237 … in the BSc Honours in Computer Science program." Graded **sufficient**: the conclusion is consistent with the key and invents nothing, but it is uncited.
- **GPT-OSS-120B:** "…lists HCSCI237 … (shown as 'IoT and Cloud Systems Engineering (HCSCI237)') without any prerequisite being recorded【Evidence 5】. Therefore, the documents … do not specify a prerequisite." Graded **partially sufficient**, with one minor claim: it treats a cut-off row in which HCSCI237 is *another module's prerequisite* as HCSCI237's own entry. The 20B runs graded in HO1 made the same error.
- **Better: 20B.** Both conclusions match the key, but 120B's justification misreads the table and cites it as support. That matters because it would mislead a student checking the source.

### H25 (intake, S5 advert vs yearbook): 20B better on admissions interpretation

- **Question:** What are the entry requirements for the Master of Arts Degree in Monitoring and Evaluation?
- **Expected:** the 2027 advert requirement, "A relevant Bachelor's Degree plus a special Honours or certificate in Monitoring and Evaluation", attributed to the advert. If the yearbook is shown, its requirement is attributed to it and the difference is stated.
- **Evidence:** the advert (p. 6) and the yearbook (p. 207): "Honours degree in M&E or Development Studies or any first degree plus a Postgraduate Diploma in M&E …; work experience an added advantage".
- **GPT-OSS-20B:** a two-row table. The advert is labelled current with its exact requirement plus the general O-level requirement; the yearbook is labelled older with its requirement. A note says the advert is the most recent requirement. Graded **sufficient**.
- **GPT-OSS-120B:** the same table plus a "Differences" section stating that the advert "does **not** mention the need for an Honours degree". Graded **partially sufficient**, with one minor claim: the advert explicitly requires "a special Honours or certificate". The answer also says "According to rule 9…" and "the documents you provided".
- **Better: 20B.** It gave the correct current requirement with clean attribution. 120B's extra analysis introduced a factual misstatement about the advert, which is the kind of error that matters for admissions.

### H24 (intake, S5 advert vs yearbook): 120B better

- **Question:** What are the entry requirements for the Bachelor of Commerce Honours Degree in Data Science and Informatics?
- **Expected:** the 2027 advert requirement, "A pass in 'A' Level Mathematics or Statistics and any other A level subject; ND/HND in an IT-related field or any other relevant qualification or confirmation of employment in IT", attributed to the advert. Yearbook differences stated if shown.
- **Evidence:** the advert (p. 10, with faculty note "'O' level Maths required for **some** programmes") and the yearbook (p. 465 normal entry; p. 466 mature entry).
- **GPT-OSS-20B:** gives the advert requirement as current and the yearbook as earlier, and states the differences correctly, but adds that "**both documents** require the standard O-level English and Mathematics conditions". Graded **partially sufficient**, with one minor claim: the advert record requires English only, and its Maths note applies to "some programmes".
- **GPT-OSS-120B:** a table with the advert requirement as current, listing the advertised modes, and yearbook normal and mature entry each labelled "older … not the current advertised requirements". Graded **sufficient**.
- **Better: 120B.** Its structure kept each requirement with its source. 20B's summary line overgeneralised an O-level Maths requirement onto the advert.

**Pattern across the three:** 120B writes longer, more analytical answers. That helps keep sources apart (H24) but also creates more room for small unsupported statements (H25, H02, and the S3 duration answers).

## 13. Problems encountered and resolutions

| Problem | Resolution |
|---|---|
| 120B blocked for the organisation (HTTP 403 `model_permission_blocked_org`) | Enabled by the owner. The smoke test then passed and the evaluation resumed from its unattempted state, with no rerun of anything already done. |
| The app's default call changed signature (11 UI tests failed) | Fixed: the default call is unchanged. |
| Health check stayed healthy with a missing explicitly selected model | Fixed: it is now unhealthy. |
| Smoke-test fact check missed "12 April" written with a no-break space | Fixed the check to use `\W*`. The saved 20B record was re-evaluated without a new call. |
| Grading consistency with HO1 | During grading, completeness for answers giving only the advertised duration and the "same programme" identity claim were aligned with HO1 conventions. This was done while blind, before the grades were committed. |

## 14. Remaining limitations

- **Sample size and variability.** One answer per question per model; a 3-question difference on 40 questions, with a known run-to-run flip rate of about 0.32 for 20B. A repeated run (3 per model, about US$0.11) would be needed to claim any difference with confidence.
- **Single AI-assisted grader** with no owner review, as in HO1. The strict rule that any minor claim prevents "sufficient" drives every difference observed.
- **Reused holdout.** The held-out set was used once before; both models are affected equally.
- **The model shown in Technical details is the requested model.** The returned model is verified in the evaluation and smoke-test records, not in the UI.

## 15. Recommended model for MSU

**Option A: keep GPT-OSS-20B as the default.**

| Factor | Finding |
|---|---|
| Accuracy | No gain from 120B: 31 against 34 sufficient, within noise. Zero critical claims for both. |
| Admissions, calendar and multi-document | Equal on S2, S5 and S6. 120B weaker on S3 durations because of added descriptors. |
| Citations | 120B better: always numbered, attribution 100%. |
| Latency | 120B about 1.6× slower at the median, 1.7× at p95. |
| Cost and tokens | 120B about 1.5× the cost, at the same token volume. |
| Operations | 20B is the evaluated and gated configuration. Switching would require a fresh release-gate evaluation. Option C needs a question classifier, a new failure mode with no measured benefit to justify it. |

Option B (switch to 120B) is not supported by the measurements. Option C (route complex questions to 120B) is not supported either: 120B did not do better on the complex strata (S2, S5).

GPT-OSS-120B stays available as an optional, tested alternative (`MSU_ASSISTANT_MODEL_ENV=GROQ_MODEL_2`). That is useful as a fallback if 20B becomes unavailable on Groq.

## 16. Next steps before hosting

1. Keep `GROQ_MODEL=openai/gpt-oss-20b`; no configuration change is needed.
2. Optionally, if the citation advantage of 120B matters: repeat both passes 3× (about US$0.11) and grade blind to see whether the accuracy gap is real before any reconsideration.
3. Consider a small prompt-independent safeguard: the app could flag answers that mention "developer instruction" or "rule N". This matters only if 120B is ever used.
4. Get an owner review of the graded differences: `per_question_grades.csv` and `blind/view_H02.md`, `view_H24.md`, `view_H25.md`.
5. Hosting is unaffected and still requires an approved host, a host secret and authorisation to expose documents (DEPLOYMENT.md).

## Files in this folder

| File | Contents |
|---|---|
| `comparison_summary.json` | Aggregate metrics per model, per-stratum results, failure sources, MRR (retrieval), the ten largest differences |
| `per_question_grades.csv` | 80 rows: grades, claims, latency and tokens per question and model |
| `GROQ_MODEL/`, `GROQ_MODEL_2/` | `results.jsonl` (answers, usage, latency, rate-limit headers, request IDs), `run_meta.json` (settings and inputs fingerprint), `api_errors.jsonl` (120B: the earlier 403) |
| `evidence_references.json` | KB versions and manifests, retrieval configuration, per-question top-5 references and message hashes (all identical to frozen), retrieval latency |
| `blind/` | `view_H01–H40.md` (blind views with key and evidence), `SEALED_mapping.json` plus `mapping_commitment.json`, `grades_input.jsonl`, `grades_work.json` plus `grades_commitment.json` |
| `smoke_test_GROQ_MODEL_2.json`, `smoke_test_GROQ_MODEL.json` | Live smoke tests: model, HTTP status, latency, usage, rate-limit headers |
| `comparison_status.json` | Machine-readable status, history of the 403 blocker, dataset fingerprints, headline results |
