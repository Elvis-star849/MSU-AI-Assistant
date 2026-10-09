# RAG-Tutorials

## MSU AI Assistant demo (presentation prototype)

A Streamlit app that answers questions from the MSU Humanities Yearbook and MSU Sciences Yearbook Vol. 2 using the
accepted pipeline: Stage 6 retrieval (T1 tie-break, heading-aware index, top 10, MiniLM reranking, top 5 evidence),
the `s7-0-baseline-v1` grounded prompt and `openai/gpt-oss-20b` via Groq. Answers show numbered sources with the
document, PDF page and section, in a chat interface.

### Setup (once)

```bash
pip install -r requirements.txt
cp .env.example .env        # then put your Groq key in .env (never commit .env)
```

The embedding and reranker models must already be in the local Hugging Face cache (they are on the development
machine); the app runs with `HF_HUB_OFFLINE=1`.

### Run

```bash
streamlit run app.py
```

Open http://localhost:8501. The first start loads the index and models (about a minute; a loading message is shown).
After that, each question takes a few seconds.

Retrieval-only backup mode (no Groq calls; shows the retrieved yearbook passages only), e.g. if the network fails:

```bash
MSU_ASSISTANT_OFFLINE=1 streamlit run app.py              # Git Bash / macOS / Linux
$env:MSU_ASSISTANT_OFFLINE="1"; streamlit run app.py      # PowerShell
```

### Before presenting

- Start the app a few minutes early and ask one question so everything is loaded.
- Confirm `.env` has the Groq key and that the Groq account limits allow the planned number of questions.
- Keep screenshots as a fallback in case the venue network fails.

### Prototype limitations

- Basic contextual follow-up support: a short follow-up such as "How many credits is it?" after "Describe
  BM134" is rewritten by simple rules into a standalone question (shown as "Interpreted as: ...") before searching.
  Earlier answers are never used as evidence. Complex references or topic changes may require the user to ask a
  complete standalone question.
- Chats (New chat, Search chats, Chat history) exist only for the current browser session; nothing is stored.
- Answers only cover what the two yearbooks contain. Page numbers are PDF pages, not necessarily printed pages.
- Course codes with more than one title are flagged from metadata, but the answer itself is not ambiguity-aware yet.
