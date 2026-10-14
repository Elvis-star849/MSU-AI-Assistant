# MSU AI Assistant: deployment, operation and rollback

## What runs

A Streamlit chat app (`app.py`). The profile is chosen with `MSU_ASSISTANT_PROFILE`:

| Profile | Knowledge base | Use |
|---|---|---|
| **`c3_intake_0006`** (default) | Staging pointer, verified version **0006** (manifest `04169e83…`): MSU Humanities Yearbook, MSU Sciences Yearbook Vol. 2, MSU 2027 Road Map **and the MSU January/February 2027 Intake Advert**; 10,979 passages. The yearbook and road-map records are identical to 0005. | Local demonstration with the 2027 intake information. The owner approved this on 2026-10-14 for the **local demonstration only**; it is not authorised for public internet hosting. |
| `c3_public_0005` | Active public pointer, verified version **0005** (manifest `25956ff5…`): yearbooks + road map; no advert. | The configuration that passed the pre-registered public release gates. |
| `baseline` | Stage 6 yearbook index (`faiss_store_v2`), S7-0 prompt. | Rollback to the pre-C3 app. |

**Common to the two C3 profiles:**
- Routed hybrid search → top 10 → MiniLM reranker → top 5.
- G2 grounding prompt + F2 evidence formatting (`src/c3_candidate.py`, a byte-identical copy of the frozen `remediation/candidate.py`). G2 tells the model to present the 2027 advert as the current requirement and to attribute differing yearbook rules. F2 labels every passage's source type and marks a missing commencement date as "not stated" (never inferred from the intake name).
- `openai/gpt-oss-20b` via Groq: temperature 0, reasoning medium, 4,096 completion tokens.
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
- The model's answer text is never rewritten.
- Errors such as rate limit, timeout or an empty response show a friendly message, and the retrieved sources stay visible.

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

## Start, check, stop (Windows host, current deployment)

```powershell
.\scripts\start_assistant.ps1                    # detached server, intake profile, http://127.0.0.1:8502, logs in logs\
python healthcheck.py --url http://127.0.0.1:8502   # profile, key present, KB 0005, retrieval, web server
python healthcheck.py --live-llm                 # adds one real answer (< US$0.001)
python scripts\e2e_live_ui.py --url http://127.0.0.1:8502   # 18 live browser checks on the intake profile (~17 Groq calls)
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
  - `python -m unittest discover -s tests -t .` (204 tests; about 2 minutes, including the parity tests, which load the real indexes);
  - `python -m unittest remediation/tests/test_candidate.py`.
- **Changing the public KB version:** after an approved KB publish, the profile refuses to start, because the pointer is no longer 0005. That is intended. Re-evaluate first, then update `EXPECTED_PUBLIC` in `src/profiles.py`.
- **Logs:** `logs/assistant.out.log` and `logs/assistant.err.log`. API keys are never logged; the LLM layer redacts credentials.
- **Dependencies:** upgrade only with the full test suite and `scripts/e2e_live_ui.py` passing.

## Known limitations (communicate these in demonstrations)

- **Accuracy:** answers can contain small unsupported details, such as an invented "2027" yearbook date or a misnamed source. The same question can be answered slightly differently from run to run.
- **Admissions:** information comes from yearbook regulations, which may be older than current requirements. The 2027 intake advert is not published in the assistant.
- **Retrieval:** some questions about single rows in long tables can miss the right passage.
- **Untested surfaces:** multi-turn follow-ups are basic and were not part of the C3 evaluation.
- **Grading:** quality figures come from AI-assisted blind grading; there has been no human owner review yet.

## Hosting status

The app is deployed on this Windows workstation at `http://127.0.0.1:8502`, local access only, and verified live.

Internet or university hosting is **not** set up, because it needs all of:
1. an approved MSU host, or a hosting account (for example Streamlit Community Cloud or a university server) with the owner's login;
2. a Groq key stored in that host's secret store;
3. authorisation to expose the MSU documents (yearbooks and road map) publicly or to the campus network.

When these are available: copy the repository branch **and** the `knowledge_base/` data to the host, install `requirements-app.txt`, pre-cache the two models, set `GROQ_API_KEY` as a host secret, start with `scripts/start_assistant.sh`, and run `healthcheck.py --url` and `scripts/e2e_live_ui.py` against the host URL.
