"""
MSU AI Assistant - presentation prototype (Streamlit chat interface).

Run from the project root:  streamlit run app.py
Retrieval-only backup mode (no Groq calls):  set MSU_ASSISTANT_OFFLINE=1 before starting.
UI only: the RAG pipeline is src/assistant.py (unchanged); follow-ups and chats are src/conversation.py.
"""
import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # models are cached locally; never wait on the network at startup

import streamlit as st

from src.assistant import EXAMPLE_QUESTIONS, Assistant, escape_markdown
from src.conversation import ChatStore

OFFLINE = os.environ.get("MSU_ASSISTANT_OFFLINE", "").strip().lower() in ("1", "true", "yes")

# Presentation-only CSS: students' messages on the left, assistant messages on the right, as bubbles.
CHAT_CSS = """
<style>
[class*="st-key-umsg-"] { max-width: 75%; width: fit-content !important; margin-right: auto; }
[class*="st-key-amsg-"] { max-width: 85%; width: fit-content !important; min-width: 45%; margin-left: auto; }
[class*="st-key-umsg-"] [data-testid="stChatMessage"] {
  background: rgba(31, 78, 121, 0.08); border-radius: 18px; padding: 0.6rem 1rem; }
[class*="st-key-amsg-"] [data-testid="stChatMessage"] {
  flex-direction: row-reverse; border: 1px solid rgba(49, 51, 63, 0.15); border-radius: 18px; padding: 0.6rem 1rem; }
[class*="st-key-amsg-"] [data-testid="stChatMessageContent"] { margin-right: 0.5rem; }
</style>
"""

st.set_page_config(page_title="MSU AI Assistant", page_icon="🎓", layout="centered")
st.html(CHAT_CSS)


@st.cache_resource(show_spinner=False)
def load_assistant(offline: bool) -> Assistant:
    """Loaded once per application process (about a minute): yearbook index, embedding model, reranker, metadata."""
    return Assistant.create(offline=offline)


def render_ambiguity(notes):
    for note in notes:
        meanings = []
        for t in note["titles"]:
            pages = ", ".join(p.replace(" p. ", ", PDF page ") for p in t["pages"])
            found = "" if t["in_results"] else " — not among the passages retrieved for this question"
            meanings.append(f"- **{escape_markdown(t['title'])}** ({pages}){found}")
        st.warning(f"**{note['code']} is listed with more than one title in the yearbooks.** "
                   "Check which programme applies to you:\n" + "\n".join(meanings), icon="⚠️")


def render_sources(sources):
    with st.expander(f"Sources ({len(sources)})"):
        st.caption("Numbers match the evidence numbers cited in the answer. Page numbers are PDF page numbers, "
                   "which may differ from the printed yearbook page numbers.")
        for s in sources:
            st.markdown(f"**[{s['number']}] {s['document']}** — PDF page {s['pdf_page']}  \n"
                        f"**Section at start of passage:** {escape_markdown(s['heading']) if s['heading'] else '—'}")
            with st.container(height=180, border=True):
                st.markdown(escape_markdown(s["passage"]))


def render_technical(turn):
    result, resolution = turn.result, turn.resolution
    with st.expander("Technical details"):
        st.markdown(f"**Retrieval query:** {escape_markdown(resolution.standalone)}  \n"
                    f"**Follow-up rule:** {resolution.rule}  \n**Retrieval route:** {result.route or '—'}  \n"
                    f"**Model:** {result.model or '—'}  \n**Prompt:** {result.prompt_version}  \n"
                    "**Timings (ms):** " + ", ".join(f"{k} {v:,.0f}" for k, v in result.timings_ms.items()) +
                    (f"  \n**Tokens:** {result.usage.get('total_tokens')}" if result.usage else ""))
        if result.sources:
            st.dataframe([{"#": s["number"], "chunk": s["chunk_id"], "retrieval rank": s["retrieval_rank"],
                           "retrieval score": s["retrieval_score"], "rerank score": s["rerank_score"],
                           "route": s["route"]} for s in result.sources], hide_index=True)


def render_assistant_message(turn):
    """1 answer, 2 ambiguity warning, 3 'Interpreted as', 4 Sources (collapsed), 5 Technical details (collapsed)."""
    result = turn.result
    if result.status == "answered":
        st.markdown(result.answer)
    elif result.status == "no_evidence":
        st.info(result.answer, icon="🔎")
    else:
        st.error(result.error_message, icon="❗")
    if result.ambiguity:
        render_ambiguity(result.ambiguity)
    if turn.resolution.is_followup:
        st.caption(f"Interpreted as: {escape_markdown(turn.resolution.standalone)}")
    if result.sources:
        render_sources(result.sources)
    render_technical(turn)


def render_user_message(chat_id, index, question):
    with st.container(key=f"umsg-{chat_id}-{index}"):
        with st.chat_message("user"):
            st.markdown(escape_markdown(question))


# ---------------------------------------------------------------- state
if "chats" not in st.session_state:
    st.session_state.chats = ChatStore()
chats: ChatStore = st.session_state.chats

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## MSU AI Assistant")
    st.button("New chat", icon=":material/add:", key="new-chat", use_container_width=True,
              on_click=chats.new_chat)
    search = st.text_input("Search chats", placeholder="Search chats...", key="search-chats",
                           label_visibility="collapsed")
    st.caption("Chat history")
    history = chats.history(search)
    if not history:
        st.caption("No matching chats." if search.strip() else "Your chats will appear here.")
    for session in history:
        st.button(session.title, key=f"chat-{session.id}", use_container_width=True,
                  type="primary" if session.id == chats.current_id else "tertiary",
                  on_click=chats.switch, args=(session.id,))
    with st.expander("About"):
        st.markdown(
            "**Knowledge source:** MSU Humanities Yearbook and MSU Sciences Yearbook Vol. 2 (10,732 passages).\n\n"
            "**How it works:** your question is matched against the yearbooks (semantic, keyword and course-code "
            "search); the 10 best passages are re-ranked and the top 5 are given to GPT-OSS 20B (via Groq), which "
            "answers **only from those passages**. Sources are listed under each answer.\n\n"
            "**Basic contextual follow-up support:** a short follow-up such as *How many credits is it?* is "
            "rewritten into a complete question (shown as *Interpreted as …*) before searching. Earlier answers "
            "are never used as evidence. Complex references or topic changes may require a complete standalone "
            "question.\n\n"
            "**Limitations:** answers cover only what the two yearbooks contain; page numbers are PDF pages; "
            "this is a prototype and can make mistakes, so check important details in the sources.")
    if OFFLINE:
        st.info("Retrieval-only mode: answers are not generated.")

# ---------------------------------------------------------------- startup
loading = st.empty()
try:
    with loading.status("Loading the MSU yearbook index and models (about a minute on first start)…", expanded=False):
        assistant = load_assistant(OFFLINE)
except Exception:
    loading.empty()
    st.error("The assistant could not start: the yearbook index or models failed to load. "
             "Please check the installation and restart the application.", icon="❗")
    st.stop()
loading.empty()

# ---------------------------------------------------------------- conversation
st.title("MSU AI Assistant")
if assistant.llm_unavailable_reason:
    st.warning(f"{assistant.llm_unavailable_reason} Retrieved yearbook passages will still be shown.", icon="ℹ️")

chat = chats.current
clicked = None
if not chat.turns:
    st.markdown("#### How can I help you with MSU today?")
    columns = st.columns(2)
    for i, example in enumerate(EXAMPLE_QUESTIONS):
        if columns[i % 2].button(example, key=f"example-{i}", use_container_width=True):
            clicked = example

for i, turn in enumerate(chat.turns):
    render_user_message(chat.id, i, turn.question)
    with st.container(key=f"amsg-{chat.id}-{i}"):
        with st.chat_message("assistant", avatar=":material/school:"):
            render_assistant_message(turn)

prompt = st.chat_input("Ask anything about MSU...", key="chat-input")
question = clicked or prompt
if question and question.strip():
    index = len(chat.turns)
    render_user_message(chat.id, index, question)
    with st.container(key=f"amsg-{chat.id}-{index}"):
        with st.chat_message("assistant", avatar=":material/school:"):
            with st.spinner("Searching the yearbooks and writing a grounded answer…"):
                chat.ask(assistant, question)
    st.rerun()
