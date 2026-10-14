"""
MSU AI Assistant (Streamlit chat interface).

Run from the project root:  streamlit run app.py          (see DEPLOYMENT.md)
Configuration (environment variables or .streamlit/secrets.toml; never committed):
  GROQ_API_KEY            required for answers (without it the app shows retrieved passages only)
  MSU_ASSISTANT_PROFILE   c3_intake_0006 (default: + 2027 intake advert) | c3_public_0005 | baseline (rollback)
  MSU_ASSISTANT_OFFLINE   1 = retrieval-only mode (no Groq calls)
UI only: the RAG pipeline is src/assistant.py; follow-ups and chats are src/conversation.py.
"""
import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # models are cached locally; never wait on the network at startup

import streamlit as st

from src.assistant import EXAMPLE_QUESTIONS, Assistant, escape_markdown
from src.conversation import ChatStore
from src.profiles import ADVERT_SOURCE, BASELINE, INTAKE, LABELS, ROADMAP_SOURCE, ProfileError, current_profile


def _secrets_to_env():
    """Hosted deployments may supply settings as Streamlit secrets; copy them into the process environment (where
    src/llm/config.py reads them) without ever displaying them. A local .env file keeps working as before."""
    try:
        secrets = dict(st.secrets)
    except Exception:
        return
    for name in ("GROQ_API_KEY", "GROQ_MODEL", "MSU_ASSISTANT_PROFILE", "MSU_ASSISTANT_OFFLINE"):
        if name in secrets and not os.environ.get(name):
            os.environ[name] = str(secrets[name])


_secrets_to_env()
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


def source_type(document):
    if document == ADVERT_SOURCE:
        return "2027 intake advert · current for the January/February 2027 intake"
    if document == ROADMAP_SOURCE:
        return "2027 academic road map"
    return "Yearbook regulations · may be older than the 2027 advert"


def render_sources(sources):
    with st.expander(f"Sources ({len(sources)})"):
        st.caption("Numbers match the evidence numbers cited in the answer. Page numbers are PDF page numbers, "
                   "which may differ from the printed document page numbers.")
        for s in sources:
            st.markdown(f"**[{s['number']}] {s['document']}** — PDF page {s['pdf_page']}  \n"
                        f"*{source_type(s['document'])}*  \n"
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
        raw = getattr(result, "raw_answer", None)
        if raw and raw != result.answer:
            st.caption("Answer wording corrected (references to documents 'you provided' or requests to supply "
                       "documents). Original model text:")
            st.text(raw)
        if result.sources:
            st.dataframe([{"#": s["number"], "chunk": s["chunk_id"], "retrieval rank": s["retrieval_rank"],
                           "retrieval score": s["retrieval_score"], "rerank score": s["rerank_score"],
                           "route": s["route"]} for s in result.sources], hide_index=True)


def render_safety_notes(notes):
    """Safeguard notes from src/safeguards.py: cautions are warnings, the admissions reminder is an info box."""
    for note in notes or []:
        if note.get("kind") in ("admissions", "sources"):
            st.info(note["text"], icon="🎓")
        elif note.get("kind") == "tip":
            st.info(note["text"], icon="💡")
        else:
            st.warning(note["text"], icon="⚠️")


def render_assistant_message(turn):
    """1 answer, 2 safeguard notes, 3 ambiguity warning, 4 'Interpreted as', 5 Sources, 6 Technical details.
    A response with no answer in the knowledge base (result.not_found) shows the answer only."""
    result = turn.result
    if getattr(result, "not_found", False):
        # No answer in the knowledge base: show the main answer only (no sources, technical details or notes).
        if result.status == "no_evidence":
            st.info(result.answer, icon="🔎")
        else:
            st.markdown(result.answer)
        return
    if result.status == "answered":
        st.markdown(result.answer)
    elif result.status == "no_evidence":
        st.info(result.answer, icon="🔎")
    else:
        st.error(result.error_message, icon="❗")
    render_safety_notes(getattr(result, "safety_notes", None))
    if result.ambiguity:
        render_ambiguity(result.ambiguity)
    if turn.resolution.is_followup:
        st.caption(f"Interpreted as: {escape_markdown(turn.resolution.standalone)}")
    searched = getattr(result, "normalised_question", None)
    if searched:
        st.caption(f"Searched as: {escape_markdown(searched)}")
    if result.sources:
        render_sources(result.sources)
    render_technical(turn)


def render_user_message(chat_id, index, question):
    with st.container(key=f"umsg-{chat_id}-{index}"):
        with st.chat_message("user"):
            st.markdown(escape_markdown(question))


try:
    PROFILE = current_profile()
except ProfileError as error:
    st.error(f"The assistant could not start: {error}.", icon="❗")
    st.stop()

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
    st.caption(f"Configuration: {LABELS[PROFILE]}")
    with st.expander("About"):
        knowledge = {
            INTAKE: "MSU Humanities Yearbook, MSU Sciences Yearbook Vol. 2, the approved MSU 2027 Road Map and the MSU "
                    "January/February 2027 Intake Advert (knowledge base version 0006, 10,979 passages). For the 2027 "
                    "intake, the advert is the current source; yearbook regulations may be older.",
            BASELINE: "MSU Humanities Yearbook and MSU Sciences Yearbook Vol. 2 (10,732 passages).",
        }.get(PROFILE, "MSU Humanities Yearbook, MSU Sciences Yearbook Vol. 2 and the approved MSU 2027 Road Map "
                       "(public knowledge base version 0005, 10,753 passages). The 2027 intake advert is not used.")
        st.markdown(
            f"**Knowledge source:** {knowledge}\n\n"
            "**How it works:** your question is matched against these documents (semantic, keyword and course-code "
            "search); the 10 best passages are re-ranked and the top 5 are given to GPT-OSS 20B (via Groq), which "
            "answers **only from those passages** and cites them. Sources are listed under each answer.\n\n"
            "**Basic contextual follow-up support:** a short follow-up such as *How many credits is it?* is "
            "rewritten into a complete question (shown as *Interpreted as …*) before searching. Earlier answers "
            "are never used as evidence. Complex references or topic changes may require a complete standalone "
            "question.\n\n"
            "**Limitations:** answers cover only what these documents contain; yearbook regulations may be older "
            "than current requirements; page numbers are PDF pages; the assistant can make mistakes (for example "
            "small unsupported details), so check important details in the sources and confirm admissions matters "
            "with MSU.")
    if OFFLINE:
        st.info("Retrieval-only mode: answers are not generated.")

# ---------------------------------------------------------------- startup
loading = st.empty()
try:
    with loading.status("Loading the MSU knowledge base and models (about a minute on first start)…", expanded=False):
        assistant = load_assistant(OFFLINE)
except ProfileError as error:
    loading.empty()
    st.error(f"The assistant could not start: {error}. The knowledge base was not changed.", icon="❗")
    st.stop()
except Exception:
    loading.empty()
    st.error("The assistant could not start: the knowledge base or models failed to load. "
             "Please check the installation and restart the application.", icon="❗")
    st.stop()
loading.empty()

# ---------------------------------------------------------------- conversation
st.title("MSU AI Assistant")
st.caption("Controlled demonstration. Answers are generated only from official MSU documents and cite their sources; "
           "they can contain mistakes. Check the sources, and confirm admissions decisions with MSU.")
if assistant.llm_unavailable_reason:
    st.warning(f"{assistant.llm_unavailable_reason} Retrieved document passages will still be shown.", icon="ℹ️")

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
            with st.spinner("Searching the MSU documents and writing a grounded answer…"):
                chat.ask(assistant, question)
    st.rerun()
