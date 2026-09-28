"""
app.py — Streamlit entry point and page router.

Controls which pages appear in the sidebar. The Admin page is registered
with st.navigation (so it's routable) but deliberately left out of the
sidebar links below, so it's only reachable if you know the URL:

    <your-deployed-url>/admin

Run with: streamlit run app.py
"""

import sys

import streamlit as st

from theme import inject_theme, exam_header

st.set_page_config(
    page_title="Papers Please",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Pre-warm the heavy backend import chain ──────────────────────────────────
# pipeline.py pulls in detector/deduplicator/parser/scorer/tagger, which in
# turn load things like OCR/PDF libraries and an embedding model. That's a
# genuinely slow one-time cost. Without this, it fires the moment you click
# into whichever tab needs it first (Upload, or Dashboard/Graph via the
# cache layer) — so your first click into that tab freezes for several
# seconds. Importing it here means it happens once, right when the app
# starts (or on the very first request to reach the server), instead of
# unpredictably on your first visit to each tab. Every visit after that,
# from any tab, is fast — Python caches the import for the life of the
# server process, shared across everyone using the app.
if "pipeline" not in sys.modules:
    with st.spinner("Warming up (first load only — every tab will be fast after this)…"):
        import pipeline  # noqa: F401
else:
    import pipeline  # noqa: F401 — already warm, this is effectively free


def home():
    inject_theme()

    exam_header(
        title="PAPERS PLEASE",
        subtitle="A community question bank — every branch, every semester, VTU-wide",
        time="However long you need",
        max_marks="No cap — it's shared",
        note="Upload what you have, use what you need. Answers below are optional but recommended.",
    )

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown("**Ranked topics**")
        st.caption("See which questions repeat across years, ranked by how often they show up.")
    with col_b:
        st.markdown("**Marks calculator**")
        st.caption("\"Study these N topics → guaranteed M marks.\" No guesswork.")
    with col_c:
        st.markdown("**Cheat sheet PDF**")
        st.caption("One click to a printable summary per subject.")

    st.write("")
    cta1, cta2, _ = st.columns([1, 1, 3])
    with cta1:
        st.page_link(upload_page, label="Upload papers →", icon="📄")
    with cta2:
        st.page_link(dashboard_page, label="Browse a subject →", icon="📊")


home_page  = st.Page(home, title="Home", icon="📚", url_path="", default=True)
upload_page = st.Page("pages/1_Upload.py", title="Upload", icon="📄", url_path="upload")
dashboard_page = st.Page("pages/2_Dashboard.py", title="Dashboard", icon="📊", url_path="dashboard")
graph_page = st.Page("pages/3_Graph.py", title="Question Graph", icon="🕸️", url_path="graph")

# Admin is included so it's routable by direct URL, but it is NOT added to the
# sidebar links below — that's what keeps it off the main page / nav menu.
admin_page = st.Page("pages/4_Admin.py", title="Admin", icon="🛠️", url_path="admin")

pg = st.navigation(
    [home_page, upload_page, dashboard_page, graph_page, admin_page],
    position="hidden",
)

with st.sidebar:
    st.page_link(home_page, label="Home", icon="📚")
    st.page_link(upload_page, label="Upload", icon="📄")
    st.page_link(dashboard_page, label="Dashboard", icon="📊")
    st.page_link(graph_page, label="Question Graph", icon="🕸️")
    # No link to admin_page here on purpose.

pg.run()