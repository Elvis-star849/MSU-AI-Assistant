# MSU AI Admissions Assistant: final report for this phase

Date: 2026-10-16. The app runs on **localhost only** (`http://127.0.0.1:8502`).

- Nothing was committed, pushed, deployed or published.
- The published knowledge base (0005) is unchanged, and the official source documents are unchanged.
- The earlier GPT-OSS-120B experiments and eligibility work are preserved (change sets 01 and 02, unchanged).
- The sealed evaluation was **not** run.

## 1. What was implemented

### Eligibility

- **Engine** (`src/eligibility_engine.py`): built on the supplied checker.
  - It gives every programme one of four outcomes: *meets* the advertised requirements, *conditional*, *does not
    meet* (with the reason), or *other route* (diploma, employment or mature entry; not decided by grades).
  - It reports the A Level points of the best three passes.
  - Consistency with the checker is enforced by tests: anything the engine says *meets*, the checker also says is
    eligible; every checker positive is also positive in the engine; and *does not meet* is always a checker
    *not eligible*.
- **Answers without the model** (`src/eligibility_answer.py`). The model cannot add programmes, change categories
  or counts, or add requirements.
  - Programmes the applicant names come first, then programmes ranked by relevance.
  - The UI shows result tabs per outcome, with "show all" and follow-up buttons.
  - Every answer says that meeting the requirements does not guarantee a place and that the Admissions Office
    decides.
- **Results parsing** (`src/results_parser.py`) is deterministic. It handles A Level and O Level results, the reply
  to the O Level question, and corrections ("actually Economics is A"). The model is used only for messages the
  parser cannot read, so most eligibility turns make **0 API calls**.
- **Rules:**
  - five unambiguous corrections (C1–C5) were applied to a copy of the rules; each has its old value, the advert
    page, a justification and a regression test, and the supplied file is kept unchanged;
  - open questions live in `rule_overrides.json` as strict and lenient readings: meeting only the lenient reading
    gives *conditional*, with the question shown, never *meets*;
  - the advert's "preferably" notes are quoted, not decided.
- **Router** (`src/router.py`): deterministic shortcuts handle most messages. The model is used only for the rest,
  and an out-of-scope label from the model is accepted only when the question has a money or deadline word.
  Fees, payments, scholarships and cut-off points get a fixed reply. A deadline the advert itself prints is quoted
  with its page.

### Retrieval and answers (documents path)

- BGE + FAISS + BM25 hybrid search, MiniLM reranking and Groq are all kept. **Programme lookup**
  (`src/programme_lookup.py` and `ProgrammeLookupRetriever`) puts every advert route of a named programme in the
  evidence.
- **C4 prompt**: G2 plus three documented edits:
  - "MSU documents searched" wording;
  - no full-time/part-time labels, and campus–mode pairs only as printed;
  - combined durations as printed.

  The evaluated C3/G2 prompt stays byte-identical, so the parity tests still pass.
- **Answer checks** (`src/safeguards.py`, `src/conflicts.py`):
  - facts that are not in the evidence get a visible *unverified* note;
  - unsupported "full-time"/"part-time" wording is removed (the original is kept);
  - campus–mode pairs the advert does not show get a note;
  - duration conflicts between the advert and a yearbook are disclosed;
  - "not found" answers show the answer only (abstention).
- **Reliability:** if the model returns an empty answer, or degenerates into a long run of one character, the app
  retries once with light reasoning on the same evidence. Otherwise it shows a friendly error, and the sources stay
  visible.

### Advanced features

- **Admin page** (`ui/admin.py` → `src/admin_service.py` → the existing `src/kb/service.KnowledgeBase`):
  - upload PDF, DOCX or TXT (new prose adapters for DOCX and TXT), then validate, stage, approve, publish (type
    PUBLISH) and roll back;
  - duplicate detection and replacement come from the KB service;
  - tabs for rules review with the conflicts table, analytics and accounts.
- **Authentication and roles** (`src/auth.py`):
  - PBKDF2-SHA256 hashes and lockout;
  - roles viewer, reviewer, uploader, publisher and admin, checked on the server for every action;
  - first-run setup works on localhost only.
- **Upload validation** (`src/upload_validation.py`): file type by content, a 25 MB limit, macros,
  instruction-like text, and a Microsoft Defender scan.
- **Programme explorer** (`ui/programme_explorer.py`): search and filter the 222 advert records, with every route
  and page.
- **Privacy:** the question log stores metadata only (route, status, latency, counts). Question text is stored only
  with `MSU_QUESTION_LOG_TEXT=1`, and then with e-mail addresses and phone numbers removed. Technical details appear
  only with `MSU_ASSISTANT_DEV_MODE=1`.
- **Navigation:** `msu_app.py` provides three pages: Chat assistant, Programme explorer and Admin.

## 2. Files

The change set for this phase is `MSU-AI-Assistant_changesets/03_admissions_system.patch`; its full file list is in
`MANIFEST.txt`.

New modules:
- `src/eligibility_engine.py`, `src/results_parser.py`, `src/programme_lookup.py`, `src/conflicts.py`;
- `src/auth.py`, `src/admin_service.py`, `src/upload_validation.py`;
- `ui/admin.py`, `ui/programme_explorer.py`, `msu_app.py`.

Rules:
- `src/eligibility/MSU_Eligibility_Rules.json` (corrected) and `MSU_Eligibility_Rules.supplied.json` (original);
- `src/eligibility/rule_overrides.json`;
- `evaluation/eligibility_audit/{corrections.json, apply_corrections.py}`.

Changed:
- `app.py`, `src/assistant.py`, `src/admissions_flow.py`, `src/router.py`, `src/extract_grades.py`,
  `src/eligibility_answer.py`, `src/profiles.py`, `src/safeguards.py`, `src/kb/adapters.py`;
- the start scripts, `.gitignore` (`instance/`) and `DEPLOYMENT.md`.

Tests:
- new: `tests/test_eligibility_engine.py`, `tests/test_admin.py`, `tests/test_admin_ui.py`;
- rewritten: `tests/test_router_and_flow.py`, `tests/test_eligibility_hardening.py`;
- browser scripts: `scripts/e2e_eligibility_ui.py`, `scripts/e2e_live_ui.py`.

Evaluation:
- `evaluation/admissions_eval/` (dev set 46, sealed set 60 frozen, `run_eval.py` grader v4).

## 3. Test results (actual, final code)

| Suite | Result |
|---|---|
| Unit and integration (`python -m unittest discover -s tests -t .`) | **337 tests, OK** |
| Supplied checker tests (`src/eligibility/test_checker.py`) | **25/25** |
| Browser, eligibility and pages (`scripts/e2e_eligibility_ui.py`, live localhost) | **12/12** |
| Browser, documents path (`scripts/e2e_live_ui.py`, live localhost, real Groq) | **20/20** |
| Live router regression (41 cases × 2, real model) | **82/82** |
| Corrected rules up to date (`apply_corrections.py --check`) | OK |

Two browser failures on the first run were fixed and then re-tested:
1. a "not found" answer in the new C4 wording still showed sources;
2. an empty model answer.

Browser reports are in `browser/`; screenshots are in `logs/e2e*/`.

**Rules audit after the corrections:**
- 141 programmes are covered;
- 12 rules were corrected and 0 confirmed mismatches remain;
- 27 rules are consistent;
- 102 need human verification, mostly undefined "relevant" or "equivalent" wording;
- 7 open questions affect results, and those results are shown as conditional.

## 4. Accuracy and consistency (dev set only)

Final run: `evaluation/results/admissions_eval/dev_20261016T081436Z/` (46 questions × 2 runs, fresh chat for each
question, grader v4).

| | Run 1 | Run 2 |
|---|---|---|
| Fully sufficient | 46/46 (100%) | 46/46 (100%) |
| Critical claims (forbidden fact or wrong campus/mode) | 0 | 0 |
| Unverified-fact notes (minor unsupported claims) | 0 | 0 |
| Correct abstentions | 11/11 | 11/11 |
| Median latency | 2.2 s | 2.6 s |

Consistency: the same label in 100% of questions, and the same facts in 100%.

Caveats, stated honestly:
- **This is the development set. The system was improved while looking at it, so the figures are optimistic.** The
  previous final-code run (`dev_20261016T080739Z`) scored 97.8% in run 1, because one answer degenerated into a run
  of dashes. That led to the degenerate-answer retry.
- An earlier manual check of 10 answers found problems the automatic grader missed: full-time/part-time labels and
  a duration linked to the wrong mode. Those led to the C4 edits and the checks above. D018 (every mode given the
  same 4 years) is still a debatable minor mapping.
- The grader uses regular expressions over keys taken from the advert and road-map records. It is strict about
  unsupported facts, but it is not a human judgement.
- **The independent measure is the frozen sealed set** (60 items, sha `5827e6f3b15b46d5`). It has not been run,
  and is reserved for you (see §6).

## 5. Limitations and rules that need official clarification

All the items for MSU are in `HUMAN_REVIEW.md`:
- confirmation of corrections C1–C5;
- 9 open eligibility questions (third science for 126/129, LLB "B or better", Actuarial points, "preferably", the
  subject taxonomy, and others);
- 5 advert-versus-yearbook duration conflicts;
- the precedence policy;
- the **admissions phone number**: the advert's p. 37 gives 054 2260029 and WhatsApp 0716626820, while the
  specified fixed reply uses (054) 2260496, which is a general switchboard line;
- the deadline-quoting policy.

Other limitations:
- KB 0006 (with the advert) is staging, and is used by the local intake profile only.
- Eligibility covers the advertised A Level routes. Diploma, employment and mature-entry routes are shown as text
  and are not decided.
- Multi-turn follow-ups on the documents path are basic.
- Answers depend on Groq. Rate limits or outages show a friendly error, and eligibility still works because it
  uses no model.
- The account store and question log are local files. That is fine for one workstation, but not for multi-user
  hosting.

## 6. Start and demonstrate

```powershell
cd C:\Users\donal\OneDrive\Desktop\RAG\MSU-AI-Assistant
.\scripts\start_assistant.ps1          # http://127.0.0.1:8502 (intake profile, technical details hidden)
python healthcheck.py --url http://127.0.0.1:8502
.\scripts\stop_assistant.ps1
```

Demo script (about 10 minutes):
1. **Chat, eligibility:**
   - "I have Mathematics A, Computer Science A and Economics B, what can I study?" shows the points, the tabs, the
     conditional results and the O Level request.
   - Reply "English B, Maths C, 6 passes" and the check completes.
   - "Sorry, actually Economics is A" is a correction.
   - "Why can't I do Biotechnology?"
2. **Chat, documents:**
   - "How long is the BSc Honours in Human Resource Management and how is it offered?" shows all routes, the
     sources and the programme-details panel.
   - "What are the entry requirements for the Master of Commerce in Strategic Marketing?"
3. **Abstention and scope:**
   - "What is the WiFi password for the MSU library?"
   - "How much are the fees?" gets the fixed reply.
   - "What is the application deadline for Mining Engineering?" quotes the advert, p. 23.
4. **Programme explorer:** filter by faculty or level and open a programme.
5. **Admin:**
   - create the first administrator (on localhost) or run `python -m src.auth create USER --role admin`;
   - show Documents, Rules review (open questions and conflicts) and Analytics;
   - **do not press Publish on the real KB.** To demo uploads safely, start with `MSU_KB_ROOT` pointing at a copy.

Sealed evaluation (owner only, when you are ready to review):
`$env:MSU_SEALED_EVAL_AUTHORISED="1"; python evaluation/admissions_eval/run_eval.py --set sealed --runs 2`.

## 7. Readiness for a controlled MSU demonstration

**Ready for a controlled, staff-facing demonstration on this workstation, with conditions:**
- present it as a prototype; eligibility results are "advertised requirements", not admission decisions;
- state the open rule questions, and that the sealed accuracy figure is still pending;
- do not use real applicant data, and do not publish KB 0006 without your authorisation.

**Not ready** for applicants or public hosting. That needs:
- answers to the `HUMAN_REVIEW.md` items, especially the phone number and the rule questions;
- the sealed evaluation at ≥90% with 0 critical claims, reviewed by you;
- an approved host with managed secrets and accounts.
