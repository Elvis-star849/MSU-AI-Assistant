"""Admin dashboard (sign-in required): knowledge-base status, documents (upload, stage, approve, publish, roll back),
rules review, analytics and accounts. All actions go through src/admin_service.py, which checks permissions on the
server side; the knowledge-base service keeps its own journal and role checks."""
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

from src import admin_service as admin
from src.auth import ROLES, AuthError, UserStore

st.title("Admin")
store = UserStore()
LOG_PATH = Path(os.environ.get("MSU_QUESTION_LOG", "").strip() or "logs/questions.jsonl")


def on_localhost() -> bool:
    try:
        host = (st.context.headers.get("Host") or "").split(":")[0]
    except Exception:
        host = ""
    return host in ("localhost", "127.0.0.1", "")


# ---------------------------------------------------------------- sign-in / first-run setup
user = st.session_state.get("admin_user")
if user is None:
    if not store.has_users():
        st.subheader("First-run setup")
        if not on_localhost():
            st.error("The first administrator account can only be created from the computer running the assistant.")
            st.stop()
        st.caption("No administrator account exists yet. Create one (passwords: at least 10 characters). The account "
                   "is stored locally in instance/admin_users.json with a salted hash.")
        with st.form("setup"):
            name = st.text_input("Administrator user name")
            pw = st.text_input("Password", type="password")
            pw2 = st.text_input("Repeat password", type="password")
            if st.form_submit_button("Create administrator"):
                if pw != pw2:
                    st.error("The passwords do not match.")
                else:
                    try:
                        st.session_state.admin_user = store.create(name, pw, "admin")
                        st.rerun()
                    except AuthError as error:
                        st.error(str(error))
        st.stop()
    with st.form("login"):
        name = st.text_input("User name")
        pw = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in"):
            try:
                st.session_state.admin_user = store.authenticate(name, pw)
                st.rerun()
            except AuthError as error:
                st.error(str(error))
    st.stop()

top = st.columns([4, 1])
top[0].caption(f"Signed in as **{user.name}** ({user.role})")
if top[1].button("Sign out"):
    st.session_state.pop("admin_user", None)
    st.rerun()

names = [("Overview", "view"), ("Documents", "view"), ("Rules review", "review"), ("Analytics", "view"),
         ("Accounts", "manage_users")]
visible = [(n, p) for n, p in names if user.can(p)]
tabs = dict(zip([n for n, _ in visible], st.tabs([n for n, _ in visible])))


def action(fn, *args, success="Done."):
    try:
        result = fn(user, *args)
        st.success(success)
        return result
    except (AuthError, ValueError) as error:
        st.error(str(error))
    except Exception as error:                     # KB errors carry clear messages; never show a stack trace
        st.error(f"{error.__class__.__name__}: {error}")


try:
    kb = admin.open_kb()
except Exception as error:
    st.error(f"The knowledge base could not be opened: {error}")
    st.stop()

# ---------------------------------------------------------------- overview
with tabs["Overview"]:
    status = admin.kb_status(user, kb)
    c = st.columns(3)
    c[0].metric("Public version", (status["pointers"].get("public") or {}).get("version", "—"))
    c[1].metric("Staging version", (status["pointers"].get("staging") or {}).get("version", "—"))
    c[2].metric("Documents", len(status["documents"]))
    st.caption(f"Profile: {status['profile']} · two-person rule: {status['two_person_rule']}")
    st.dataframe(pd.DataFrame(status["documents"]), hide_index=True, width="stretch")
    if st.button("Verify knowledge-base integrity"):
        st.json(action(admin.verify, kb, success="Verification finished.") or {}, expanded=False)

# ---------------------------------------------------------------- documents
with tabs["Documents"]:
    st.caption("Upload → validate → stage (visible only in the intake/staging profile) → approve → publish. "
               "Publishing changes the public knowledge base, which the assistant uses after a restart.")
    if user.can("upload"):
        with st.form("upload", clear_on_submit=True):
            st.subheader("Upload a document")
            f = st.file_uploader("PDF, DOCX or TXT (max 25 MB)", type=["pdf", "docx", "txt"])
            title = st.text_input("Title", placeholder="e.g. MSU August 2027 Intake Advert")
            label = st.text_input("Source label (shown in citations)", placeholder="e.g. MSU August 2027 Intake Advert")
            valid_for = st.text_input("Valid for (optional)", placeholder="e.g. August 2027 intake")
            notes = st.text_area("Notes (optional)")
            stage_now = st.checkbox("Stage after successful validation")
            if st.form_submit_button("Upload and validate") and f is not None:
                report = action(admin.upload_document, kb, f.name, f.getvalue(), title, label, valid_for, notes, None,
                                stage_now, success="Upload processed.")
                if report:
                    st.write(f"**Status:** {report.get('status')}")
                    st.json(report, expanded=False)
    docs = [d for d in admin.kb_status(user, kb)["documents"] if not d["base"]]
    if docs:
        st.subheader("Documents")
        choice = st.selectbox("Document", [f"{d['doc_id']} v{d['doc_version']} — {d['status']}" for d in docs])
        d = docs[[f"{x['doc_id']} v{x['doc_version']} — {x['status']}" for x in docs].index(choice)]
        if user.can("review"):
            with st.expander("History"):
                st.json(admin.document_history(user, kb, d["doc_id"]), expanded=False)
        cols = st.columns(3)
        if user.can("upload") and d["status"] == "validated" and cols[0].button("Stage"):
            action(admin.stage_document, kb, d["doc_id"], d["doc_version"], success="Staged.")
        if user.can("publish"):
            with st.form("decide"):
                basis = st.text_input("Approval basis / reason (recorded in the journal)")
                b1, b2, b3 = st.columns(3)
                if b1.form_submit_button("Approve") and d["status"] == "staged":
                    action(admin.approve_document, kb, d["doc_id"], d["doc_version"], basis, success="Approved.")
                if b2.form_submit_button("Reject"):
                    action(admin.reject_document, kb, d["doc_id"], d["doc_version"], basis or "rejected", success="Rejected.")
                if b3.form_submit_button("Withdraw") and d["status"] == "published":
                    action(admin.withdraw_document, kb, d["doc_id"], d["doc_version"], basis or "withdrawn",
                           success="Withdrawn.")
    if user.can("publish"):
        st.subheader("Publish or roll back")
        with st.form("publish"):
            confirm = st.text_input("Type PUBLISH to build a new public version from the approved documents")
            if st.form_submit_button("Publish") and confirm == "PUBLISH":
                st.json(action(admin.publish, kb, success="Published.") or {}, expanded=False)
        with st.form("rollback"):
            version = st.text_input("Roll back to public version (e.g. 0005)")
            reason = st.text_input("Reason")
            if st.form_submit_button("Roll back") and version:
                action(admin.rollback, kb, version.strip(), reason, success="Rolled back.")

# ---------------------------------------------------------------- rules review
if "Rules review" in tabs:
    with tabs["Rules review"]:
        ov = admin.rules_overview(user)
        st.caption(f"Eligibility rules {ov['rules_version']} · {ov['programmes']} programmes. Corrections need "
                   "unambiguous advert evidence (evaluation/eligibility_audit/corrections.json); open questions stay "
                   "conditional for applicants until MSU Admissions answers them.")
        st.subheader("Corrections applied")
        st.dataframe(pd.DataFrame([{"id": c["id"], "field": c["field"], "programmes": ", ".join(c["programmes"]),
                                    "pages": ", ".join(map(str, c["source_pages"])), "evidence": c["evidence"]}
                                   for c in ov["corrections"]]), hide_index=True, width="stretch")
        st.subheader(f"Open questions for MSU Admissions ({len(ov['open_questions'])})")
        st.dataframe(pd.DataFrame(ov["open_questions"]), hide_index=True, width="stretch")
        with st.form("note"):
            pid = st.selectbox("Programme", sorted({q["id"] for q in ov["open_questions"]}))
            decision = st.selectbox("Decision", ["question_sent_to_admissions", "confirmed_as_coded", "needs_change", "note"])
            note = st.text_area("Note (who confirmed, how, when)")
            if st.form_submit_button("Record note"):
                action(admin.record_review_note, pid, decision, note, success="Recorded (rules are not changed).")
        if ov["notes"]:
            st.dataframe(pd.DataFrame(ov["notes"]), hide_index=True, width="stretch")
        st.caption("Audit: " + json.dumps(ov["audit"].get("reviewed_status_counts") or {}))
        st.subheader("Advert vs yearbook: duration conflicts")
        st.caption("Programmes whose yearbook regulation states a different duration from the 2027 advert. Disclosed "
                   "to applicants in answers; not resolved automatically.")
        try:
            from src.conflicts import duration_conflicts
            st.dataframe(pd.DataFrame(duration_conflicts()), hide_index=True, width="stretch")
        except Exception as error:
            st.caption(f"Conflict scan unavailable: {error.__class__.__name__}")

# ---------------------------------------------------------------- analytics
with tabs["Analytics"]:
    a = admin.analytics(user, LOG_PATH)
    st.caption("From the privacy-preserving question log (metadata only: no question text or applicant results unless "
               "text logging was explicitly enabled).")
    c = st.columns(4)
    c[0].metric("Questions", a["questions"])
    c[1].metric("Answered from documents", a["documents_answered"])
    c[2].metric("Not found in documents", a["documents_not_found"])
    c[3].metric("Median latency (ms)", a["latency_ms"]["median"] or "—")
    if a["by_route"]:
        st.bar_chart(pd.Series(a["by_route"], name="questions"))
    if a["by_day"]:
        st.line_chart(pd.Series(a["by_day"], name="questions per day"))
    st.json({k: a[k] for k in ("router_reasons", "results_read_by", "errors", "eligibility_follow_ups", "latency_ms")},
            expanded=False)

# ---------------------------------------------------------------- accounts
if "Accounts" in tabs:
    with tabs["Accounts"]:
        st.dataframe(pd.DataFrame([{"user": n, "role": r} for n, r in store.users().items()]), hide_index=True)
        with st.form("new-user", clear_on_submit=True):
            n = st.text_input("New user name")
            r = st.selectbox("Role", ROLES)
            p = st.text_input("Initial password (at least 10 characters)", type="password")
            if st.form_submit_button("Create account"):
                try:
                    store.create(n, p, r, by=user)
                    st.success(f"Created {n} ({r}).")
                except AuthError as error:
                    st.error(str(error))
