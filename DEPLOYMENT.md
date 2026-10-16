# MSU AI Assistant: deployment, operation and rollback

## What runs

A Streamlit app with three pages. The entry point is `msu_app.py` (`st.navigation`); the start scripts run it.

| Page | File | Access |
|---|---|---|
| Chat assistant | `app.py` (still runs on its own, too) | Everyone on the local host |
| Programme explorer | `ui/programme_explorer.py`: search and filter the 2027 advert programmes, with every route (duration, modes, requirements, page) | Everyone on the local host |
| Admin | `ui/admin.py`: documents, KB versions, rules review, analytics, accounts | Signed-in staff only (see *Admin* below) |

The profile is chosen with `MSU_ASSISTANT_PROFILE`:

| Profile | Knowledge base | Use |
|---|---|---|
| **`c3_intake_0006`** (default) | Staging pointer, verified version **0006** (manifest `04169e83…`): MSU Humanities Yearbook, MSU Sciences Yearbook Vol. 2, MSU 2027 Road Map **and the MSU January/February 2027 Intake Advert**; 10,979 passages. The yearbook and road-map records are identical to 0005. | Local demonstration with the 2027 intake information. The owner approved this on 2026-10-14 for the **local demonstration only**; it is not authorised for public internet hosting. |
| `c3_public_0005` | Active public pointer, verified version **0005** (manifest `25956ff5…`): yearbooks + road map; no advert. | The configuration that passed the pre-registered public release gates. |
| `baseline` | Stage 6 yearbook index (`faiss_store_v2`), S7-0 prompt. | Rollback to the pre-C3 app. |

**Common to the two C3 profiles:**
- Routed hybrid search → top 10 → MiniLM reranker → top 5.
- G2 grounding prompt + F2 evidence formatting (`src/c3_candidate.py`, a byte-identical copy of the frozen `remediation/candidate.py`). G2 tells the model to present the 2027 advert as the current requirement and to attribute differing yearbook rules. F2 labels every passage's source type and marks a missing commencement date as "not stated" (never inferred from the intake name).
- **App prompt C4** (`C4_SYSTEM_PROMPT` in `src/profiles.py`, version `r-g2-grounding-v1+F2+c4-descriptors`). It is G2 plus three documented edits:
  - "MSU documents searched" wording;
  - never call a mode full-time or part-time, and print campus–mode pairs only as the advert shows them;
  - print combined durations as written, without linking a duration to a mode the evidence does not link.

  `build_c3_messages` (the evaluated G2 prompt) is kept byte-identical for the parity tests.
- **Programme lookup** (`ProgrammeLookupRetriever`, intake profile): when a question names an advert programme, all of that programme's advert routes (up to 4 passages) are placed first. The data come from `src/programme_lookup.py`: 222 advert records, sha-checked.
- `openai/gpt-oss-20b` via Groq: temperature 0, reasoning medium, 4,096 completion tokens. If the model returns no final answer, the app retries once with light reasoning on the same evidence.
- Profiles only *read* knowledge-base versions. No pointer is written or switched. The intake profile reads the staging version as the local-demo actor `msu-assistant-local-demo`.

**Parity.** `tests/test_c3_profile.py` proves the app reproduces the evaluated retrieval (top 5) and the byte-identical prompts for all 18 public (0005) and all 22 intake (0006) held-out questions.

**Evaluated quality on the held-out set (`remediation/REMEDIATION_FINAL_REPORT.md`):**
- Public questions: 0 critical claims; reliable-sufficient 0.833.
- Intake questions: 0 critical claims; reliable-sufficient 0.545, below the 0.80 intake-readiness bar. Intake answers therefore need the most care in demonstrations.

**Safeguards (`src/safeguards.py`):**
- Question length limit (1,000 characters) and control-character removal.
- Retrieved passages containing instruction-like text are withheld from the model. No passage in KB 0005 or 0006 matches, so evaluated behaviour is unchanged.
- Visible notes under the answer:
  - missing or invalid evidence citations;
  - an admissions reminder (intake profile: the 2027 advert is the current source for the January/February 2027 intake and yearbook regulations may be older; confirm with MSU Admissions);
  - on the intake profile, when an answer cites both an advert passage and a yearbook passage: "Where they differ, the 2027 advert applies";
  - on the public profile only, any mention of an "advert", which is not among the public sources.
- Each source under an answer is labelled: *2027 intake advert · current*, *Yearbook regulations · may be older*, or *2027 academic road map*.
- Answer checks against the evidence (C3 profiles):
  - facts such as dates, durations, degree classes, module codes and "full-time"/"part-time" that are not found in the evidence get a visible *unverified* note;
  - unsupported "full-time"/"part-time" descriptors are removed from the text (the original is kept under *Technical details*);
  - a campus–mode pair the advert does not show gets a note;
  - when the cited advert and yearbook give different durations for a programme (`src/conflicts.py`), a conflict note is shown.

  No other rewriting happens.
- Errors such as rate limit, timeout or an empty response show a friendly message, and the retrieved sources stay visible.

**Intake question handling (C3 profiles only; `baseline` is unchanged):**

| Fix | What it does |
|---|---|
| Query clean-up (`src/query_normalise.py`) | Corrects common misspellings of admissions words ("requrements" → "requirements") and resolves "the following / next / this intake" to "the 2027 intake". The UI shows a *Searched as …* caption when the question was changed. None of the 80 evaluated questions is altered (tested). |
| Advert supplement (`IntakeAwareRetriever` in `src/profiles.py`, intake profile) | For an admissions question whose top 5 contains no advert passage, the advert records alone are searched (vector + BM25, then MiniLM rerank, relevance floor 1.0) and up to 2 replace the lowest-ranked passages. Calendar (road-map) questions and questions that already retrieved an advert passage are untouched. None of the 22 evaluated intake questions changes (tested). |
| Wording on misses (`present_answer`, `miss_tip` in `src/safeguards.py`) | "The documents you provided / the documents provided" becomes "the MSU documents I searched". Sentences asking the user to supply documents are removed. A misses-only tip suggests naming the programme. The original model text is shown under *Technical details* whenever the wording was corrected. |

## Router and admissions adviser

Every chat message is routed first (`src/admissions_flow.py`):

| Path | When | What happens |
|---|---|---|
| **Admissions adviser** | The applicant describes their qualifications, age or work experience; asks what they can study; asks "Can I study <programme>?", about mature entry or "what if I don't have A Levels?"; or answers the adviser's question | `src/admissions_adviser.py` keeps a structured applicant profile for the chat, asks **one** high-value question at a time, and gives a short shortlist once enough is known. Everything is decided by fixed rules (`src/entry_routes.py`, `src/eligibility_engine.py`) and rendered **without the model**. |
| **Documents (RAG)** | Programmes, named-programme requirements, campuses, calendar, services, anything else | The retrieval pipeline above. |
| **Out of scope** | Fees, payments, bank details, application deadlines, scholarships, cut-off points | A fixed reply with the Admissions Office contact; no model answer. Exception: if the advert itself prints a deadline for the named programme (e.g. Mining Engineering, 31 March 2027, p. 23), that sentence is quoted with its page, together with the contact. |

**Routing.** Deterministic first, in this order:
- a keyword guard for out-of-scope topics;
- "show all";
- adviser signals (`router.adviser_reason`): a reply to the adviser's question or confirmation, a new-assessment request, "those were my brother's results", mature entry, "without A Levels", the applicant's own qualifications, age or work experience, and "Can I study <advert programme>?";
- results in the message;
- eligibility phrases.

Only the rest go to GROQ_MODEL at temperature 0. The model's out-of-scope label is accepted only if the question has a money or deadline word.

**Applicant profile** (`src/applicant_profile.py`). It holds A Levels, O Levels (subjects, grades, number of passes, one sitting), post-school qualifications (kind and field), age, work experience (years and field), employment and interests. Every fact records its source:
- *stated*;
- *confirmed*: the applicant kept earlier details for the same person;
- *inferred*: for example "5 passes including Maths" → Mathematics passed at grade C or better.

The sidebar **Your assessment** panel shows each fact with its source. Nothing is guessed: a value is recorded only if its words are in the message. The model is used only to attach A Level grade letters to subjects that the parser cannot match (as before, validated against the applicant's words).

**Entry routes** (`src/entry_routes.py`):
- *normal entry with A Levels*: the eligibility engine;
- *normal entry with O Levels only*: 4 advert programmes;
- *special entry*: the qualification lines of each advert entry, plus the general Special Entry rule for degree holders;
- *mature entry*: the 18 programmes whose advert entry states it. Their conditions are in `src/eligibility/entry_routes.json`, built by `evaluation/eligibility_audit/build_entry_routes.py` from the advert wording, which asserts that every condition is visible in the quoted text. `--check` verifies the file.

**Statuses:**
- ✅ **meets the advertised requirements**: grade-decided routes only;
- 🟡 **possible**: every checkable condition is met, and the Admissions Office still assesses relevance, recognition, interviews or tests;
- 🔎 **could be possible**: details still needed;
- not met.

Special and mature routes are never ✅. Age alone never makes mature entry possible.

**Conversation policy:**
- *Ask before recommending.* Gating questions come first when their answer changes the whole picture (at most 3 in a row): A Levels or a post-school qualification? subjects and grades; the qualification's field; age; which mature-entry age applies (23 or 24 only, with Skip); work experience.
- *Recommend.* The shortlist has at most 5 entries. Each gives the programme, the route, the advert wording, why it fits, what is still needed, and the page.
- *Follow up.* After the shortlist comes one question, chosen as the unknown that would settle the most top candidates. An unchanged shortlist is not repeated.
- *No match yet.* If nothing fits, the adviser says so kindly and asks about other routes.

**Stale data.** A new applicant's details are never merged silently:
- a fresh self-description that conflicts with earlier details, or a different full set of A Levels, gets a confirmation question ("same person or new assessment?") before anything is applied;
- "Those were my brother's results" removes that set of results, including later corrections to it;
- **Start new assessment** (in the chat, or the sidebar button) always needs explicit confirmation;
- a new chat starts an empty profile;
- the saved results form is applied once, then cleared.

**Detailed assessment.** Under a recommendation, an optional control lists every programme, route by route, including the engine's A Level tabs. Counts and internal labels are not shown in the conversation. Routing captions and Technical details appear only with `MSU_ASSISTANT_DEV_MODE=1`.

Every answer says that meeting the advertised requirements does not guarantee a place.
- **Rules:**
  - `src/eligibility/MSU_Eligibility_Rules.json` is the corrected rules file (corrections C1–C5 in `evaluation/eligibility_audit/corrections.json`, built by `apply_corrections.py`). The supplied file is kept unchanged as `MSU_Eligibility_Rules.supplied.json`.
  - Open questions live in `src/eligibility/rule_overrides.json`, as strict and lenient readings. An applicant who meets only the lenient reading gets *conditional*, with the question shown, never *meets*.
  - `rule_warnings.json` (written by the audit) is informational only.
  - Items for MSU: `evaluation/results/final_system/HUMAN_REVIEW.md`.
- The **Technical details** panels and routing captions (router label, extracted results, checker counts, retrieval internals) appear only in developer/admin mode: start the server with `MSU_ASSISTANT_DEV_MODE=1` (server-side; visitors cannot switch it on). "Not found" document answers show the answer only.
- Question log `logs/questions.jsonl`: privacy-preserving metadata by default (timestamp, route, router reason, status, adviser question key, focus, shortlist size, question length; no question text, no qualifications, no age). `MSU_QUESTION_LOG_TEXT=1` also stores the question text with e-mail addresses and phone numbers removed. `MSU_QUESTION_LOG=off` disables the log.
- Checker tests: `cd src/eligibility && python test_checker.py` (25 tests). Entry routes: `python evaluation/eligibility_audit/build_entry_routes.py --check`.
- Rules: `python evaluation/eligibility_audit/apply_corrections.py --check` and `python evaluation/eligibility_audit/audit_rules.py`.
- Live router regression (41 labelled cases, real model): `python evaluation/router_regression/run_router_regression.py --repeat 2`.

## Admin (documents, knowledge-base versions, rules review)

The Admin page wraps the existing KB service (`src/kb/service.py` via `src/admin_service.py`). Every action is checked on the server (`src/auth.require`) and recorded in the KB journal with the user name.

- **Accounts** (`src/auth.py`):
  - passwords are hashed with PBKDF2-SHA256, need at least 10 characters, and repeated failures lock the account;
  - roles are `viewer` < `reviewer` < `uploader` < `publisher` < `admin`;
  - first run: on localhost only, the Admin page offers to create the first administrator. Or use `python -m src.auth create USER --role admin`;
  - the account file is `instance/admin_users.json` (git-ignored), or `MSU_ADMIN_USERS`.
- **Documents:**
  - upload PDF, DOCX or TXT, up to 25 MB;
  - checks before anything is stored (`src/upload_validation.py`): file type by content, macros, instruction-like text, and a Microsoft Defender scan when available;
  - then register → validate → stage → approve → **publish** (type `PUBLISH` to confirm). Rollback goes to an earlier version. Duplicates are detected by hash; replacing a document supersedes the old one.
  - Staging builds a new version directory; the published version is never edited in place.
- **Rules review:** the corrected rules, open questions, the duration conflicts, and reviewer notes (`instance/rule_review_notes.jsonl`).
- **Analytics:** counts from the metadata-only question log (route, status, latency, results method). No question text unless `MSU_QUESTION_LOG_TEXT=1`.
- `MSU_KB_ROOT` points the Admin page at another KB root (the tests use an isolated copy). **Publishing on the real `knowledge_base/` changes what the public profile serves: do it only with the owner's authorisation.**

## Evaluation

- Dev set (46 items; keys derived from the advert and road-map records): `python evaluation/admissions_eval/run_eval.py --set dev --runs 2`. Results go to `evaluation/results/admissions_eval/dev_<stamp>/`.
- Grader v4 is strict:
  - an *unverified* note makes an answer not sufficient;
  - a campus–mode pair the advert does not show is critical.
- Sealed set (60 items, frozen, `sealed/SEALED.json`) is **owner only**: `MSU_SEALED_EVAL_AUTHORISED=1 python evaluation/admissions_eval/run_eval.py --set sealed --runs 2`. Without the variable, the script refuses to run.

## Requirements

**Software:** Python 3.12 and `pip install -r requirements-app.txt` (pinned app dependencies).

**Data on the host (not in git):**
- `knowledge_base/` (store, pointers, versions 0005 and 0006);
- `faiss_store_v2/` (tracked);
- the cached Hugging Face models `BAAI/bge-small-en-v1.5` and the MiniLM cross-encoder. The app runs with `HF_HUB_OFFLINE=1`, so the models must already be in the local cache.

**Secrets:** never commit secrets. `.env`, `.streamlit/secrets.toml` and `logs/` are git-ignored.

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Required for answers. Set it as an environment variable or in `.env` / `.streamlit/secrets.toml`. Without it, the app shows the retrieved passages only. |
| `MSU_ASSISTANT_PROFILE` | `c3_intake_0006` (default), `c3_public_0005`, or `baseline` (rollback). Any other value stops the app at startup. |
| `MSU_ASSISTANT_OFFLINE` | `1` = retrieval-only mode, no Groq calls. |
| `GROQ_MODEL_2` | Optional second model (for example `openai/gpt-oss-120b`). Not used unless selected; leaving it unset changes nothing. |
| `MSU_ASSISTANT_DEV_MODE` | `1` = show the *Technical details* panels (server-side; visitors cannot switch it on). |
| `MSU_QUESTION_LOG` / `MSU_QUESTION_LOG_TEXT` | `off` disables the question log; `1` also stores question text (e-mail addresses and phone numbers removed). |
| `MSU_ADMIN_USERS` | Admin account file (default `instance/admin_users.json`). |
| `MSU_KB_ROOT` | Knowledge-base root for the Admin page (default `knowledge_base/`). |
| `MSU_ASSISTANT_MODEL_ENV` | Optional. `GROQ_MODEL_2` answers with the second model, with identical retrieval, prompt and generation settings. Unset = the accepted `openai/gpt-oss-20b`. A missing or invalid variable stops the app with a clear message instead of falling back silently. Evaluation status: `evaluation/results/gpt_oss_comparison/GPT_OSS_120B_EVALUATION_REPORT.md`. |

## Start, check, stop (Windows host, current deployment)

```powershell
.\scripts\start_assistant.ps1                    # detached server, intake profile, http://127.0.0.1:8502, logs in logs\
python healthcheck.py --url http://127.0.0.1:8502   # profile, key present, KB 0005, retrieval, web server
python healthcheck.py --live-llm                 # adds one real answer (< US$0.001)
python healthcheck.py --live-llm --model-env GROQ_MODEL_2   # the same check with the optional second model
python scripts\e2e_live_ui.py --url http://127.0.0.1:8502          # 20 live browser checks (documents path, ~20 Groq calls)
python scripts\e2e_eligibility_ui.py --url http://127.0.0.1:8502   # 12 checks: eligibility, router paths, explorer, admin
python scripts\e2e_adviser_ui.py --url http://127.0.0.1:8502      # 19 checks: adviser conversations (no model calls)
.\scripts\stop_assistant.ps1
```

On Linux or macOS: `scripts/start_assistant.sh [profile] [port]`. Set `MSU_BIND_ADDRESS=0.0.0.0` only on an approved, access-controlled host.

**Startup and health:**
- First start takes about 30–60 s while the index and models load.
- Streamlit serves `GET /_stcore/health`, which returns `ok`.
- The page title is "MSU AI Assistant", and the sidebar shows the active configuration.

## Rollback (fastest first)

1. **Configuration, seconds.** Without the advert:

   ```powershell
   .\scripts\stop_assistant.ps1
   .\scripts\start_assistant.ps1 -Profile c3_public_0005
   ```

   Or back to the pre-C3 app:

   ```powershell
   .\scripts\stop_assistant.ps1
   .\scripts\start_assistant.ps1 -Profile baseline
   ```

   This restores the previous app: Stage 6 yearbook index and the S7-0 prompt. Verified by a rollback drill.
2. **Code:** `git switch main`, or `git checkout baseline-pre-c3` (tag on the last pre-C3 commit `eb9ccff`), then restart.
3. **Emergency:** start with `MSU_ASSISTANT_OFFLINE=1` (retrieval only, no LLM calls).

No step changes the knowledge base, so rollback cannot lose data. Pointers are switched only through the KB administration tools (`src/kb`), never by the app.

## Maintenance

- **Tests:**
  - `python -m unittest discover -s tests -t .` (372 tests; about 4–5 minutes, including the parity tests, which load the real indexes);
  - `python -m unittest remediation/tests/test_candidate.py`.
- **Changing the public KB version:** after an approved KB publish, the profile refuses to start, because the pointer is no longer 0005. That is intended. Re-evaluate first, then update `EXPECTED_PUBLIC` in `src/profiles.py`.
- **Logs:** `logs/assistant.out.log` and `logs/assistant.err.log`. API keys are never logged; the LLM layer redacts credentials.
- **Dependencies:** upgrade only with the full test suite and `scripts/e2e_live_ui.py` passing.

## Known limitations (communicate these in demonstrations)

- **Accuracy:** answers can contain small unsupported details, such as an invented "2027" yearbook date or a misnamed source. The same question can be answered slightly differently from run to run.
- **Admissions:** the 2027 advert is in staging KB 0006, which is used by the local intake profile only and is not published. Yearbook regulations may be older. Eligibility results depend on rules that still have open questions (`HUMAN_REVIEW.md`); those results are shown as conditional.
- **Retrieval:** some questions about single rows in long tables can miss the right passage.
- **Untested surfaces:** multi-turn follow-ups on the documents path are basic. The eligibility conversation (O Level reply, corrections, "why not") is covered by unit and browser tests.
- **Grading:** quality figures come from AI-assisted blind grading; there has been no human owner review yet.

## Hosting status

The app is deployed on this Windows workstation at `http://127.0.0.1:8502`, local access only, and verified live.

Internet or university hosting is **not** set up, because it needs all of:
1. an approved MSU host, or a hosting account (for example Streamlit Community Cloud or a university server) with the owner's login;
2. a Groq key stored in that host's secret store;
3. authorisation to expose the MSU documents (yearbooks and road map) publicly or to the campus network.

When these are available: copy the repository branch **and** the `knowledge_base/` data to the host, install `requirements-app.txt`, pre-cache the two models, set `GROQ_API_KEY` as a host secret, start with `scripts/start_assistant.sh`, and run `healthcheck.py --url` and `scripts/e2e_live_ui.py` against the host URL.
