"""
MSU AI Admissions Assistant: entry point with page navigation (localhost demonstration).

    streamlit run msu_app.py          (scripts/start_assistant.ps1 does this)

Pages: Chat assistant (app.py, unchanged as a page), Programme explorer (ui/programme_explorer.py) and Admin
(ui/admin.py, sign-in required). app.py can still be run on its own.
"""
import streamlit as st

pages = [st.Page("app.py", title="Chat assistant", icon="🎓", default=True),
         st.Page("ui/programme_explorer.py", title="Programme explorer", icon="🔎"),
         st.Page("ui/admin.py", title="Admin", icon="🔐")]
st.navigation(pages).run()
