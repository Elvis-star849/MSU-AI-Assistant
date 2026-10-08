# Stage 6 plan: controlled retrieval experiments

Status: **approved 2026-10-07**. Experiments run one at a time, with a review stop after each.

## Decisions agreed
- **Latency limit:** reranking may add up to 1.5 s median and 3 s at the 95th percentile per question on this CPU. This is an experimental limit; latency is recorded now and optimised later if needed.
- **Rerankers:** `BAAI/bge-reranker-base` (main) and `cross-encoder/ms-marco-MiniLM-L-6-v2` (fast comparison), to measure the quality/speed trade-off.
- **Held-out set:** generated with the Stage 5 sampling procedure and a new seed, reviewed by the user, then frozen before development. No questions are designed around N4 or C10.
- **Thresholds:** +2 on the development set and +3 on the held-out set. These are pre-agreed decision criteria for this project, not statistical proof; with 30 scored questions the sample is small.

## Ground rules
1. **Stage 5 is the baseline and is never edited.**
   - `eval/stage6/baseline_hashes.json` records the hashes of the Stage 5 files and the frozen system.
   - Before every run, the hashes are checked and the baseline routed mode is re-run to confirm it reproduces Stage 5 exactly.
2. **The frozen system is not touched.**
   - `src/vectorstore.py` and `faiss_store/` stay identical byte for byte.
   - Stage 6 code goes in new modules (`src/retrieval_v2.py`, `src/rerank.py`) that call the store's public `vector_search` and `bm25_search`.
   - Any new index goes in its own folder with its own manifest and fingerprint.
3. **The Stage 5 questions are now the development set.** Results on them are development evidence only.
4. **One change per experiment**, compared against the best configuration accepted so far.
5. **Every experiment reports:**
   - Top-1, Top-3 and Top-5 by category and overall, plus MRR@10.
   - A per-question improved / worse / unchanged table.
   - Latency where relevant: median and 95th percentile per question, plus model load time.
6. **Grading new chunks:**
   - Chunks without a grade are graded blind with the 0/1/2 scale, in shuffled batches with no system information.
   - Grades are added to `eval/stage6/grades.json`, keyed by chunk ID and corpus fingerprint. Stage 5 grades are never changed; disagreements are logged as notes.
7. **Default acceptance rule (development set):**
   - **Accept** only if no category's Top-5 drops, overall Top-5 doesn't drop, Top-1 or Top-3 improves by at least 2, and latency is within the limit.
   - **Reject** any Top-5 regression unless the user explicitly accepts the trade.
   - A difference of 1 counts as no change.
8. **Experiment log:** `eval/stage6/experiments.json` records each experiment's ID, date, hypothesis, change, fixed settings, results, decision and reason.

## Experiments, in order
| ID | What | Rebuild index? |
|---|---|---|
| S6-0 | Preparation: user spot-check of Stage 5 grades; draft, review and freeze the held-out set; logs and hash checks | No |
| S6-1 | Tie-break: T1 (vector rank wins ties) and T2 (neutral: better single rank, then chunk order) in code-aware hybrid. Decision is provisional until after S6-2 | No |
| S6-2 | Cross-encoder reranking of routed top-N, N = 5 (control), 10, 20, 30, with both rerankers. Side measurement: out-of-scope versus in-scope reranker scores | No |
| S6-1 confirmed | Final keep/drop of the tie-break, given the S6-2 result | No |
| S6-3 | Heading-aware chunks: section heading added to the indexed text, in a new index version `faiss_store_v2/` | Yes (new version) |
| S6-4 | Module cards. Only run if, after S6-3, a description-answer code question is still a Top-5 miss or code questions score below 16/20 at Top-1 | Yes (new version) |
| S6-5 | Ambiguity: a Stage 7 requirement (name each meaning, or ask which programme), plus optional `ambiguous_code` metadata with no ranking change | No |
| S6-6 | Final: frozen Stage 4 routed baseline versus final Stage 6 system on the sealed held-out set, with blind pooled grading | No |

**Pool-size rule for S6-2 (fixed in advance):** choose the smallest N within 1 question of the best Top-1 and Top-5 that meets the latency limit.

**Held-out claim rule for S6-6:** an improvement is claimed only if all of these hold:
- Top-5 is no lower than the baseline.
- Top-1 improves by at least 3.
- More questions improve than get worse.
- Latency is within the limit.

Otherwise the result is reported as it is and no improvement is claimed. Development-set and held-out results are shown side by side.

The details for each experiment (problem, hypothesis, what changes, what stays fixed, metrics, criteria, risks) are as approved in the Stage 6 review conversation of 2026-10-07.
