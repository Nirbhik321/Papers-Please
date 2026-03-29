"""
app.py
Streamlit multi-page entry point.
Run with: streamlit run app.py
"""

import streamlit as st

st.set_page_config(
    page_title="ExamLens",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.title("ExamLens")
st.sidebar.caption("Semantic Question Intelligence")
st.sidebar.divider()

st.title("ExamLens")
st.markdown(
    "Upload your previous year question papers on the **Upload** page to get started. "
    "The system will extract, cluster, and score every question automatically."
)

col1, col2, col3 = st.columns(3)
with col1:
    st.info("**Step 1** — Upload PDFs on the Upload page")
with col2:
    st.info("**Step 2** — Wait for the pipeline to run (~1–2 min)")
with col3:
    st.info("**Step 3** — Explore the Question Bank")