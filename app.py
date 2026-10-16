"""
MSU AI Assistant (Streamlit chat interface).

Run from the project root:  streamlit run app.py          (see DEPLOYMENT.md)
Configuration (environment variables or .streamlit/secrets.toml; never committed):
  GROQ_API_KEY            required for answers (without it the app shows retrieved passages only)
  MSU_ASSISTANT_PROFILE   c3_intake_0006 (default: + 2027 intake advert) | c3_public_0005 | baseline (rollback)
  MSU_ASSISTANT_OFFLINE   1 = retrieval-only mode (no Groq calls)
  MSU_ASSISTANT_MODEL_ENV optional: GROQ_MODEL_2 answers with the second model (default: the accepted GPT-OSS 20B)
  MSU_QUESTION_LOG        question log file (default logs/questions.jsonl; "off" disables it). Metadata only by default.
  MSU_QUESTION_LOG_TEXT   1 = also store the question text (e-mails/phone numbers removed). Default: not stored.
  MSU_ASSISTANT_DEV_MODE  1 = developer/admin mode: show Technical details (router, extracted results, retrieval).
                          Server-side setting; visitors cannot switch it on from the page.
Every message is routed (src/admissions_flow.py): eligibility checker, documents (RAG) or a fixed out-of-scope reply.
UI only: the RAG pipeline is src/assistant.py; follow-ups and chats are src/conversation.py.
"""
import os
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # models are cached locally; never wait on the network at startup

import streamlit as st

from src.assistant import ACCEPTED_MODEL, EXAMPLE_QUESTIONS, Assistant, escape_markdown, selected_model_env
from src.admissions_flow import QUESTION_LOG, handle_message
from src.conversation import ChatStore
from src.extract_grades import A_GRADES, O_GRADES, SUBJECTS, from_form
from src.llm import ModelSelectionError, load_config
from src.profiles import ADVERT_SOURCE, BASELINE, INTAKE, LABELS, ROADMAP_SOURCE, ProfileError, current_profile
from src.router import ELIGIBILITY, OUT_OF_SCOPE
from src.eligibility_answer import ICON, TITLES, by_faculty
from src.eligibility_engine import CONDITIONAL, MEETS, NOT_MET, OTHER_ROUTE
from src import entry_routes as er
from src.admissions_adviser import ICON as ROUTE_ICON, STATUS_SHORT
from src.applicant_profile import CONFIRMED, INFERRED
from src.programme_lookup import card_markdown, programme_groups


def _secrets_to_env():
    """Hosted deployments may supply settings as Streamlit secrets; copy them into the process environment (where
    src/llm/config.py reads them) without ever displaying them. A local .env file keeps working as before."""
    try:
        secrets = dict(st.secrets)
    except Exception:
        return
    for name in ("GROQ_API_KEY", "GROQ_MODEL", "GROQ_MODEL_2", "MSU_ASSISTANT_PROFILE", "MSU_ASSISTANT_OFFLINE",
                 "MSU_ASSISTANT_MODEL_ENV"):
        if name in secrets and not os.environ.get(name):
            os.environ[name] = str(secrets[name])


_secrets_to_env()
OFFLINE = os.environ.get("MSU_ASSISTANT_OFFLINE", "").strip().lower() in ("1", "true", "yes")
MODEL_ENV = selected_model_env()      # None = the accepted default model
_log_setting = os.environ.get("MSU_QUESTION_LOG", "").strip()
LOG_PATH = None if _log_setting.lower() == "off" else Path(_log_setting) if _log_setting else QUESTION_LOG
FORM_ROWS = 5
ELIGIBILITY_EXAMPLES = [                 # illustrative applicant profiles (not evaluation questions)
    "I have Mathematics A, Physics B and Chemistry B. What can I study?",
    "I have 5 O-Level passes including Maths and English, and I'm 30 years old. What programme can I do?",
    "I have a diploma in Accounting. What can I study?",
    "What about mature entry?",
]
FACT_SOURCE = {"stated": "you told me", CONFIRMED: "you confirmed", INFERRED: "my assumption: please check"}
_TRUE = ("1", "true", "yes")
LOG_TEXT = os.environ.get("MSU_QUESTION_LOG_TEXT", "").strip().lower() in _TRUE
DEV_MODE = os.environ.get("MSU_ASSISTANT_DEV_MODE", "").strip().lower() in _TRUE

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
def load_assistant(offline: bool, model_env=None) -> Assistant:
    """Loaded once per application process (about a minute): yearbook index, embedding model, reranker, metadata."""
    if model_env:                       # optional second model; the default call is unchanged
        return Assistant.create(offline=offline, model_env=model_env)
    return Assistant.create(offline=offline)


def model_label() -> str:
    """'GPT-OSS 20B' for the default; the selected model when MSU_ASSISTANT_MODEL_ENV is set."""
    model = load_config(model_env=MODEL_ENV).settings.model if MODEL_ENV else ACCEPTED_MODEL
    return model.split("/")[-1].upper().replace("GPT-OSS-", "GPT-OSS ")


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


def router_line(turn):
    flow = getattr(turn, "flow", None)
    router = flow.debug.get("router") if flow is not None else None
    return f"**Router:** {router['label']} ({router['reason']})  \n" if router else ""


def render_technical(turn):
    result, resolution = turn.result, turn.resolution
    with st.expander("Technical details"):
        st.markdown(router_line(turn) + f"**Retrieval query:** {escape_markdown(resolution.standalone)}  \n"
                    f"**Follow-up rule:** {resolution.rule}  \n**Retrieval route:** {result.route or '—'}  \n"
                    f"**Model:** {result.model or '—'}  \n**Prompt:** {result.prompt_version}  \n"
                    "**Timings (ms):** " + ", ".join(f"{k} {v:,.0f}" for k, v in result.timings_ms.items()) +
                    (f"  \n**Tokens:** {result.usage.get('total_tokens')}" if result.usage else ""))
        raw = getattr(result, "raw_answer", None)
        if raw and raw != result.answer:
            st.caption("Answer wording corrected (references to documents 'you provided', requests to supply "
                       "documents, or 'full-time'/'part-time' qualifiers that no source states). Original model text:")
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


def suggest(label, question, key):
    """A one-click follow-up: the question is asked as if the user had typed it."""
    if st.button(label, key=key, icon=":material/arrow_forward:"):
        st.session_state.pending_question = question
        st.rerun()


def render_eligibility_tabs(answer, key):
    """Every programme, per outcome, in the engine's order (nothing is dropped)."""
    tabs = st.tabs([f"{ICON[o]} {label} ({answer.counts[o]})" for o, label in
                    ((MEETS, "Meets"), (CONDITIONAL, "Conditional"), (NOT_MET, "Does not meet"), (OTHER_ROUTE, "Other routes"))])
    for tab, outcome in zip(tabs, (MEETS, CONDITIONAL, NOT_MET, OTHER_ROUTE)):
        with tab:
            items = answer.sections[outcome]
            if not items:
                st.caption("No programmes in this group.")
                continue
            st.caption(TITLES[outcome])
            st.markdown(by_faculty(items, outcome != OTHER_ROUTE, answer.evaluation.o_level_given))


def route_lines(results):
    """Detailed-assessment lines for one route, grouped by status (nothing is dropped)."""
    out = []
    for status in (er.MEETS, er.POSSIBLE, er.NEEDS_INFO, er.NOT_MET):
        group = sorted((r for r in results if r.status == status), key=lambda r: (r.faculty, r.programme))
        if not group:
            continue
        out.append(f"\n**{ROUTE_ICON[status]} {STATUS_SHORT[status]} ({len(group)})**\n")
        for r in group:
            detail = "; ".join(r.outstanding[:2])
            out.append(f"- **{r.programme}**" + (f" — {detail}" if detail else "") + f" *(advert p. {r.page})*")
    return "\n".join(out)


def render_detailed_assessment(reply, key):
    """The full deterministic results behind one control: every programme, every route."""
    a = reply.assessment
    with st.expander("Detailed assessment (all programmes and entry routes)", expanded=reply.expand_detail):
        st.caption("Every programme in the January/February 2027 intake advert, checked route by route against what "
                   "you have told me. Only ✅ means the advertised requirements are met; 🟡 and 🔎 are not confirmed "
                   "eligibility. The Admissions Office makes the final decision.")
        tabs = st.tabs([er.ROUTE_NAMES[x] for x in (er.NORMAL_A, er.NORMAL_O, er.SPECIAL, er.MATURE)])
        with tabs[0]:
            if reply.detail is not None:
                st.caption(f"A Level points (best three passes): {reply.detail.evaluation.points_best_three}")
                render_eligibility_tabs(reply.detail, key)
            else:
                rows = a.by_route(er.NORMAL_A)
                if rows and all(r.status == er.NOT_MET for r in rows):
                    st.markdown(f"You told me you don't have A Levels. These {len(rows)} programmes ask for A Level "
                                "passes through normal entry (the other tabs show the other routes):")
                    st.markdown("\n".join(f"- {r.programme} *(advert p. {r.page})*"
                                           for r in sorted(rows, key=lambda r: (r.faculty, r.programme))))
                else:
                    st.markdown(route_lines(rows) if rows else
                                "Tell me your A Level subjects and grades to check this route.")
        for tab, route, empty in ((tabs[1], er.NORMAL_O, "Tell me your O Level results to check this route."),
                                  (tabs[2], er.SPECIAL, "Tell me about any certificate, diploma or other post-school "
                                                        "qualification to check this route."),
                                  (tabs[3], er.MATURE, "Tell me your age, O Level results and work experience to check "
                                                       "this route.")):
            with tab:
                rows = a.by_route(route)
                st.markdown(route_lines(rows) if rows else empty)
                if route == er.MATURE:
                    st.caption("The 2027 advert lists mature entry for 18 programmes; for others, ask the Admissions "
                               "Office. General rule: " + er.GENERAL_MATURE_CITE + ".")


def render_flow_message(turn, key="", is_last=False):
    """Admissions-adviser and out-of-scope turns: answer, quick replies (last turn only), Detailed assessment.
    Routing labels and Technical details appear only in developer mode."""
    flow = turn.flow
    if flow.status == "error":
        st.warning(flow.answer, icon="ℹ️")
    else:
        st.markdown(flow.answer)
    reply = flow.data
    if reply is not None and getattr(reply, "assessment", None) is not None:
        if reply.shortlist or reply.detail is not None or reply.expand_detail:
            render_detailed_assessment(reply, key)
    if reply is not None and is_last and getattr(reply, "quick_replies", None):
        cols = st.columns(len(reply.quick_replies))
        for i, (col, label) in enumerate(zip(cols, reply.quick_replies)):
            with col:
                suggest(label, label, f"qr-{key}-{i}")
    if not DEV_MODE:
        return
    st.caption(flow.caption)
    with st.expander("Technical details"):
        st.markdown(router_line(turn) + f"**Path:** {flow.path}  \n**Status:** {flow.status}")
        details = {k: v for k, v in flow.debug.items() if k != "router"}
        if details:
            st.json(details, expanded=False)


def render_profile_panel(chat):
    """What the adviser knows about the applicant, where each detail came from, and Start new assessment."""
    profile = chat.applicant
    with st.expander("Your assessment", expanded=bool(profile is not None and not profile.is_empty())):
        if profile is None or profile.is_empty():
            st.caption("Tell the assistant about your qualifications and your admissions profile will appear here.")
        else:
            st.caption("Only what you have told me in this chat. Nothing is saved.")
            for row in profile.summary():
                st.markdown(f"**{row['label']}:** {row['value']}  \n*{FACT_SOURCE.get(row['status'], row['status'])}*")
        with st.popover("Start new assessment", icon=":material/restart_alt:", width="stretch"):
            st.markdown("This clears the details above, so nothing from the current assessment is used again.")
            if st.button("Yes, start a new assessment", key="confirm-new-assessment", type="primary", width="stretch"):
                st.session_state.pending_action = "reset_confirmed"
                st.session_state.elig_form = None
                st.rerun()


def documents_caption(sources):
    seen = []
    for s in sources:
        label = f"{s['document']} p. {s['pdf_page']}"
        if label not in seen:
            seen.append(label)
    return "Documents: " + "; ".join(seen)


def render_programme_details(turn):
    """Structured details (all routes) from the 2027 intake advert for a programme the question names; intake profile
    only, because the advert is not part of the public knowledge base."""
    if PROFILE != INTAKE:
        return
    try:
        groups = programme_groups(turn.resolution.standalone, max_groups=2)
    except Exception:
        return
    if groups:
        with st.expander("Programme details (2027 intake advert)"):
            st.caption("Exact entries from the advert for every route of the programme. Confirm admissions decisions "
                       "with MSU.")
            for g in groups:
                st.markdown(card_markdown(g))


def render_assistant_message(turn, key="", is_last=False):
    """1 answer, 2 safeguard notes, 3 ambiguity warning, 4 'Interpreted as', 5 path caption, 6 Sources,
    7 Technical details. A response with no answer in the knowledge base (result.not_found) shows the answer only.
    Eligibility-checker and out-of-scope turns are rendered by render_flow_message."""
    if getattr(turn, "path", "INFO") in (ELIGIBILITY, OUT_OF_SCOPE):
        render_flow_message(turn, key, is_last)
        return
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
        st.caption(documents_caption(result.sources))
        render_sources(result.sources)
        render_programme_details(turn)
    if DEV_MODE:
        render_technical(turn)


def render_user_message(chat_id, index, question):
    with st.container(key=f"umsg-{chat_id}-{index}"):
        with st.chat_message("user"):
            st.markdown(escape_markdown(question))


try:
    PROFILE = current_profile()
    MODEL_LABEL = model_label()
except (ProfileError, ModelSelectionError) as error:
    st.error(f"The assistant could not start: {error}.", icon="❗")
    st.stop()

# ---------------------------------------------------------------- state
if "chats" not in st.session_state:
    st.session_state.chats = ChatStore()
chats: ChatStore = st.session_state.chats

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("## MSU AI Assistant")
    st.button("New chat", icon=":material/add:", key="new-chat", width="stretch",
              on_click=chats.new_chat)
    search = st.text_input("Search chats", placeholder="Search chats...", key="search-chats",
                           label_visibility="collapsed")
    st.caption("Chat history")
    history = chats.history(search)
    if not history:
        st.caption("No matching chats." if search.strip() else "Your chats will appear here.")
    for session in history:
        st.button(session.title, key=f"chat-{session.id}", width="stretch",
                  type="primary" if session.id == chats.current_id else "tertiary",
                  on_click=chats.switch, args=(session.id,))
    with st.expander("Check what I can study (results form)"):
        st.caption("Optional. Saved results are added to your current assessment with your next message (once). "
                   "Based on the January/February 2027 intake advert.")
        with st.form("eligibility-form"):
            rows = []
            for i in range(FORM_ROWS):
                c1, c2 = st.columns([3, 1])
                subject = c1.selectbox(f"A Level subject {i + 1}", ["—"] + SUBJECTS, key=f"elig-subject-{i}")
                grade = c2.selectbox("Grade", ["—"] + list(A_GRADES), key=f"elig-grade-{i}")
                rows.append((None if subject == "—" else subject, None if grade == "—" else grade))
            english = st.selectbox("O Level English grade", ["Not given"] + list(O_GRADES), key="elig-o-english")
            maths = st.selectbox("O Level Mathematics grade", ["Not given"] + list(O_GRADES), key="elig-o-maths")
            passes = st.selectbox("Number of O Level passes", ["Not given"] + list(range(0, 16)), key="elig-o-passes")
            if st.form_submit_button("Save my results", width="stretch"):
                st.session_state.elig_form = from_form(
                    [(s, g) for s, g in rows if s and g], None if english == "Not given" else english,
                    None if maths == "Not given" else maths, None if passes == "Not given" else passes)
        saved = st.session_state.get("elig_form")
        if saved is not None and saved.a_level:
            st.caption("Saved: " + ", ".join(f"{s} {g}" for s, g in saved.a_level.items()))
            if st.button("Clear saved results", key="elig-clear", width="stretch"):
                st.session_state.elig_form = None
                st.rerun()
        elif saved is not None:
            st.caption("No A Level subject with a grade was selected.")
    render_profile_panel(chats.current)
    st.caption(f"Configuration: {LABELS[PROFILE]}" + (" · developer mode" if DEV_MODE else ""))
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
            f"search); the 10 best passages are re-ranked and the top 5 are given to {MODEL_LABEL} (via Groq), which "
            "answers **only from those passages** and cites them. Sources are listed under each answer.\n\n"
            "**Admissions adviser:** tell the assistant about your qualifications (A Levels, O Levels, a certificate "
            "or diploma), your age and work experience. It asks one question at a time and suggests programmes "
            "through every route the January/February 2027 advert describes: normal entry, special entry with a "
            "qualification and mature entry. Fixed rules decide (no AI decides eligibility); only ✅ means the "
            "advertised requirements are met, and **Detailed assessment** under an answer shows every programme. "
            "Meeting the advertised requirements does not guarantee a place.\n\n"
            "**Programme explorer** (page menu): search and filter all 2027 intake programmes and their routes.\n\n"
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
        assistant = load_assistant(OFFLINE, MODEL_ENV)
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
        if columns[i % 2].button(example, key=f"example-{i}", width="stretch"):
            clicked = example
    if PROFILE == INTAKE:
        st.markdown("##### Check what you can study (2027 intake)")
        columns = st.columns(2)
        for i, example in enumerate(ELIGIBILITY_EXAMPLES):
            if columns[i % 2].button(example, key=f"elig-example-{i}", width="stretch"):
                clicked = example

for i, turn in enumerate(chat.turns):
    render_user_message(chat.id, i, turn.question)
    with st.container(key=f"amsg-{chat.id}-{i}"):
        with st.chat_message("assistant", avatar=":material/school:"):
            render_assistant_message(turn, f"{chat.id}-{i}", is_last=i == len(chat.turns) - 1)

prompt = st.chat_input("Ask anything about MSU...", key="chat-input")
action = st.session_state.pop("pending_action", None)
question = "Start a new assessment" if action else (clicked or prompt or st.session_state.pop("pending_question", None))
if question and question.strip():
    index = len(chat.turns)
    render_user_message(chat.id, index, question)
    with st.container(key=f"amsg-{chat.id}-{index}"):
        with st.chat_message("assistant", avatar=":material/school:"):
            with st.spinner("Working on your question…"):
                form = st.session_state.get("elig_form")
                turn = handle_message(chat, assistant, question, form=form, log_path=LOG_PATH, log_text=LOG_TEXT,
                                      action=action)
                if form is not None and turn.path == ELIGIBILITY:
                    st.session_state.elig_form = None      # a saved form is used once, never for a later applicant
    st.rerun()
