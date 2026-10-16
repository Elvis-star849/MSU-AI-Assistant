"""Programme explorer: search and filter the January/February 2027 intake programmes (structured advert records).
Read-only; every route of a programme is shown with its advert page. Intake profile only (the advert is not part of
the public knowledge base)."""
import streamlit as st

from src.profiles import INTAKE, ProfileError, current_profile
from src.programme_lookup import card_markdown, facets, search

st.title("Programme explorer")
st.caption("January/February 2027 intake programmes as advertised, with every study route (duration, modes, entry "
           "requirements) and the advert page. Confirm admissions decisions with MSU.")
try:
    profile = current_profile()
except ProfileError as error:
    st.error(f"Unavailable: {error}")
    st.stop()
if profile != INTAKE:
    st.info("The 2027 intake advert is not part of this configuration's knowledge base, so the explorer is not "
            "available here.")
    st.stop()

f = facets()
c1, c2 = st.columns([2, 1])
text = c1.text_input("Search programme or faculty", placeholder="e.g. Computer Science, Psychology, Engineering",
                     key="px-text")
level = c2.selectbox("Level", ["All"] + f["level"], key="px-level")
c3, c4, c5 = st.columns(3)
faculty = c3.selectbox("Faculty", ["All"] + f["faculty"], key="px-faculty")
campus = c4.selectbox("Campus", ["All"] + f["campus"], key="px-campus")
mode = c5.selectbox("Study mode", ["All"] + f["mode"], key="px-mode")

groups = search(text, None if faculty == "All" else faculty, None if level == "All" else level,
                None if campus == "All" else campus, None if mode == "All" else mode)
st.markdown(f"**{len(groups)} programme(s)**, {sum(len(g.routes) for g in groups)} route(s)")
PAGE = 25
pages = max(1, (len(groups) + PAGE - 1) // PAGE)
page = st.number_input("Page", 1, pages, 1, key="px-page") if pages > 1 else 1
for g in groups[(page - 1) * PAGE:page * PAGE]:
    modes = sorted({m for r in g.routes for m in r["modes"]})
    with st.expander(f"{g.programme} — {', '.join(modes[:3])}{'…' if len(modes) > 3 else ''}"):
        st.markdown(card_markdown(g))
