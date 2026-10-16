# Router + eligibility checker: acceptance report

**Date:** 2026-10-15
**Scope:** the ten improvement requests for the router and eligibility checker.
**Status of the code:** runs on localhost only. Nothing committed, pushed or deployed. The published knowledge base is unchanged. `GROQ_MODEL` is unchanged (`openai/gpt-oss-20b`).

**Legend:**
- **Implemented:** built and verified by automated and live tests.
- **Partial:** built, with a stated gap.
- **Human verification:** needs a decision by a person with authority (MSU Admissions or the project owner).

## Summary

| # | Requirement | Status |
|---|---|---|
| 1 | Deterministic programme prioritisation | **Implemented**; ordering rule needs owner confirmation |
| 2 | O Level handling | **Implemented** |
| 3 | Rules audit against the 2027 advert | **Implemented** (report); **human verification** for 12 confirmed mismatches and 102 ambiguous rules |
| 4 | Router regression tests | **Implemented** |
| 5 | Privacy-preserving question log | **Implemented** |
| 6 | Developer/admin mode for technical details | **Implemented** for localhost; **partial** for hosting (no authentication) |
| 7 | Failure tests; no unsupported eligibility decisions | **Implemented**; one residual risk documented |
| 8 | GPT-OSS-120B work kept separate | **Implemented** (two verified patch files; both sets still in the working tree) |
| 9 | Complete unit, integration and browser regression | **Implemented**: all passing |
| 10 | This report | Done |

## 1. Deterministic programme prioritisation: Implemented

**Code:** `src/eligibility_answer.py` (`present`, `subject_match_score`, `mentioned_programmes`).

**Ordering within each list:**
1. Programmes whose A Level rule *names* the applicant's own subjects (the count of distinct named subjects).
2. Then faculty.
3. Then programme name.

The order is deterministic, and every programme the checker returned is kept. The model sees the first 10 per list; "show all" lists every one, and the counts are always complete.

**Named programmes:**
- An exact name match ("Can I do Computer Science?") is answered first, labelled `exact`.
- Related matches ("Biotechnology" → "Biotechnology and Bioinformatics") follow, labelled `related`.
- The applicant's own results ("Mathematics A", "English B") are never treated as programme names. A live test caught "English" matching the "English and Communication" programme; this is now fixed.

**Tests:**
- order is identical across runs and has the same membership as the checker;
- Computer Science, Software Engineering and Cybersecurity rank first for a Computer Science applicant;
- the exact match comes first;
- "show all" is complete.
- In the live browser, the Computer Science applicant sees Computer Science first.

**Owner decision:** the ranking rule (named subjects, then faculty, then name) is an engineering choice. Confirm it suits MSU.

## 2. O Level handling: Implemented

- **Without O Level results**, the checker's `eligible_confirm` list is presented as "**Conditional: meets the A Level requirements only … not a full eligibility result**". The model is instructed never to call these eligible, and a code-written summary line states "0 meet the advertised requirements · N conditional A Level matches".
- **The O Level request:** when O Level details are missing and there are conditional matches, the answer ends with an explicit request for O Level English, Mathematics and the number of passes.
- **Completing the check:** the reply ("English B, Maths C, 6 passes"):
  - routes to ELIGIBILITY, because the router sees that O Level results were asked for;
  - is read as O Level results, because the extraction sees the assistant's question;
  - is merged with the earlier A Levels, giving a full check.
- **Live:** 0 → 27 programmes meeting the requirements for the test applicant.
- **Follow-ups without results**, such as "Why can't I do Biotechnology?", reuse the results already given; no re-extraction.
  - A live run caught re-extraction sometimes losing the A Levels; this is now fixed.

## 3. Rules audit: Implemented; rules need human verification

**Report:** `evaluation/results/eligibility_rules_audit/RULES_VERIFICATION_REPORT.md`, with the per-programme CSV and JSON alongside.

**Findings:**
- All 141 undergraduate and diploma programmes are covered.
- Name, faculty, duration, modes and page match the advert for all 141.
- **12 confirmed mismatches:**
  - **7 high impact:** Faculty of Agriculture programmes miss the faculty's "O Level Maths required for all programmes";
  - **5 low impact.**
- 102 rules contain wording a person must interpret.
- 27 are consistent.

**The rules file was not changed.** Its sha256 is identical to the file you supplied; this is tested.

**Interim safeguard:** programmes with a confirmed high or medium mismatch, or an open question, carry a visible "Rule under review" warning (14 programmes). They are never shown as fully meeting the requirements.

**Needs your approval and MSU Admissions:**
- the proposed fixes in report §3;
- the questions in §4: Engineering third A Level, LLB "B or better" scope, Humanities/Social Sciences subjects, the subject taxonomy.

## 4. Router regression tests: Implemented

- **Mocked tests** (`tests/test_eligibility_hardening.py::RouterRegressionTests`) cover:
  - **tuition vs fees:** "face-to-face tuition" goes to documents, "how much is tuition" is out of scope;
  - **deadlines without the word "deadline":** "last day to apply", "until when can I submit", "applications close", "by when should I apply", "too late to apply", "how long do I have to get my application in";
  - **follow-ups:** after a grades question, after an O Level request, "show all" only after an eligibility answer;
  - **programme names:** "Banking and Finance", "Applied Accounting", "Actuarial Science" are never out of scope;
  - **unrelated questions:** WiFi, weather and Council go to documents.
- **Live regression** with the real `gpt-oss-20b` (`evaluation/router_regression/`, 41 labelled cases × 2 repeats): **82/82**. Results are in `evaluation/results/router_regression/`.
  - The first run scored 78/82: the model correctly labelled two deadline paraphrases as out of scope, but the code confirmation check rejected them. The check was widened and the result is 82/82.
- **Defence in depth:**
  - keyword guard, with no model call;
  - the model's out-of-scope label accepted only when the question contains a money or deadline word;
  - any error or invalid output goes to the documents path.
- In live traffic the confirmation check overrode one wrong out-of-scope label, and the invalid-output fallback triggered once.

## 5. Privacy-preserving question log: Implemented

- **Default:** `logs/questions.jsonl` records only metadata:
  - timestamp;
  - route;
  - router reason;
  - status;
  - not-found flag and number of sources (documents path);
  - list counts and results source (eligibility path);
  - question length.
- There is no question text and there are no qualifications. A test verifies that no subject names or text appear. Live, 29 new lines were metadata only.
- **Opt-in:** `MSU_QUESTION_LOG_TEXT=1` also stores the question text, with e-mail addresses and phone numbers removed. Names cannot be reliably removed. `MSU_QUESTION_LOG=off` disables the log.
- **Housekeeping:** the 64 lines written earlier today under the old format contain *my synthetic test questions*, not real applicants. Delete or keep them as you prefer.

## 6. Developer/admin mode: Implemented for localhost, partial for hosting

- **Server-side switch:** `MSU_ASSISTANT_DEV_MODE=1` at server start. Visitors cannot switch it on from the page.
- **Default (off):** no Technical details panels and no extracted results, router labels, checker counts or retrieval internals. Users see only the answer, a path caption ("Eligibility checker", "Documents: …", "Out of scope") and Sources.
- **Verified** by UI tests in both modes and by live browser runs in both modes (10/10 each).
- **Gap for hosting:** this is a process-level switch, not authentication. Before any shared deployment, admin features need real login and roles.
- Extracted results are held only in the user's session memory, which is needed for "show all" and follow-ups. They are never shown in default mode and never logged.

## 7. Failure handling: Implemented, with one residual risk

**Tested** (`FailureTests`, plus the earlier flow tests):

| Failure | Behaviour | Can it produce an eligibility decision? |
|---|---|---|
| Router: rate limit, timeout, connection, server, authentication, permission, empty, bad request, unknown | Documents path (INFO) | No |
| Extraction: same error kinds | "Service busy" message; checker not run | No |
| Extraction: malformed output (not JSON, list, wrong types, "A+", unknown subject, bad pass count) | Error message or a question for the missing detail; checker not run | No |
| Answer writing: any error, or an empty answer | Deterministic rendering of the checker's own result | Only the checker's decision |
| Answer names a programme not in the checker payload | Replaced by the deterministic rendering | No |
| Answer contains money amounts or guarantee wording | Replaced by the deterministic rendering | No |
| Rate limit | One retry after 2 s (tested), then the friendly message | — |
| No model configured | Keyword guard still works; the sidebar form plus deterministic rendering | Only the checker's decision |

**Residual risk:** the model's prose could put a programme that *is* in the payload under the wrong heading, for example a not-eligible programme the applicant asked about. Programme presence is verified in code, but its placement in the prose is not. Mitigations:
- the code-written counts line;
- the conditional titles;
- each asked-about programme carries its list in the payload.

A full fix would render the lists deterministically and let the model write only a short introduction. That is a design choice for you.

## 8. Change-set separation: Implemented

The two sets of uncommitted work are preserved in the working tree. They are also saved, outside the repository, as two patch files:

- `C:\Users\donal\OneDrive\Desktop\RAG\MSU-AI-Assistant_changesets\01_gpt_oss_120b.patch`: the GPT-OSS-120B work (second model, evaluation, report).
- `…\02_eligibility.patch`: the router and eligibility work, applied after 01.
- `MANIFEST.txt`: the files in each set. `app.py` and `DEPLOYMENT.md` appear in both; each patch carries only its own edits.

**Verified** in a temporary git worktree (removed afterwards; nothing committed):
- both patches apply cleanly, in order, to HEAD (`5019856`);
- the result is identical to the current working tree for every changed file.
- The eligibility code was decoupled from the 120B helpers, so 02 contains no 120B code.

## 9. Test results (final code)

| Suite | Result |
|---|---|
| `python -m unittest discover -s tests -t .` (unit and integration, including UI tests and parity tests on the real indexes) | **299 passed, 0 failed** |
| `src/eligibility/test_checker.py` (your checker tests) | **25/25** |
| `remediation/tests/test_candidate.py` | pass |
| `scripts/e2e_live_ui.py` (live browser regression, default mode) | **20/20** |
| `scripts/e2e_eligibility_ui.py` (live browser, eligibility paths), default mode / developer mode | **10/10** / **10/10** |
| `evaluation/router_regression` (live, real model, 41 cases × 2) | **82/82** |

**Live runs found and fixed three issues** after the mocked tests had passed:
- the O Level reply was treated as a programme name;
- a re-extraction intermittently lost the A Levels;
- the confirmation check was too narrow for deadline paraphrases.

## 10. Still open

**Needs human verification:**
1. Approve or reject the proposed rule fixes (Agriculture O Level Maths; Mining Engineering text).
2. MSU Admissions answers to the open rule questions and the subject taxonomy.
3. Confirm the programme ordering rule.
4. Confirm the out-of-scope contact details (admissions@admin.msu.ac.zw, (054) 2260496); they were given in your specification and not checked against the documents.

**Engineering follow-ups (optional):**
- Render the eligibility lists deterministically, to remove the residual risk in §7.
- Add real authentication before any shared hosting.
- Each message now makes one extra model call for routing, about 0.3–1 s.
