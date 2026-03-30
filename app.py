"""
app.py — Streamlit entry point.
Run with: streamlit run app.py
"""

import streamlit as st

st.set_page_config(
    page_title="Papers Please",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📚 Papers Please")
st.markdown(
    """
    **Exam intelligence for VTU students.**

    Upload your past question papers and get:
    - Ranked topics by frequency across years
    - Sub-question level analysis per module
    - "Study X topics → guaranteed Y marks" calculator
    - Printable cheat sheet PDF

    ---
    👈 Use the sidebar to navigate to **Upload** or **Dashboard**.
    """
)
