"""
4_Admin.py — Admin overview: all uploaded papers, per-subject stats, and
destructive actions (delete a paper, wipe the database).

Not linked from anywhere in the app's UI. Reachable only by direct URL
(<deployed-url>/admin) — see app.py for the routing setup. There is no
login on this page (by design, per project decision): treat the URL itself
as the secret, and don't share it or post it publicly.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from modules.db import (
    get_all_papers,
    get_distinct_subjects,
    init_db,
    delete_paper,
    clear_all_data,
)

DB_PATH = str(Path(__file__).parent.parent / "data" / "papers.db")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
init_db(DB_PATH)

st.title("🛠️ Admin")
st.caption(
    "This page isn't linked anywhere in the app — you're only here because you "
    "have the direct URL. Don't share this link publicly."
)

papers = get_all_papers(DB_PATH)
subjects = get_distinct_subjects(DB_PATH)

if not papers:
    st.info("No papers uploaded yet.")
    st.stop()

df = pd.DataFrame(papers)

# ── Overview metrics ─────────────────────────────────────────────────────────
st.subheader("Overview")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Papers", len(papers))
m2.metric("Subjects", len(subjects))

pdf_types = df["pdf_type"].fillna("unknown").value_counts().to_dict()
m3.metric("Native PDFs", pdf_types.get("native", 0))
m4.metric("Scanned PDFs", pdf_types.get("scanned", 0))

years = sorted({str(p.get("year")) for p in papers if p.get("year")})
if years:
    st.caption(f"Years represented: {', '.join(years)}")

st.divider()

# ── Per-subject breakdown ────────────────────────────────────────────────────
st.subheader("Papers per Subject")

if subjects:
    subj_df = pd.DataFrame(subjects).rename(columns={
        "subject_code": "Subject Code",
        "subject_name": "Subject Name",
        "paper_count": "Papers",
        "min_year": "From Year",
        "max_year": "To Year",
    })
    st.dataframe(subj_df, use_container_width=True, hide_index=True)

    chart_df = pd.DataFrame(subjects).set_index("subject_code")[["paper_count"]]
    chart_df.columns = ["Papers"]
    st.bar_chart(chart_df)
else:
    st.info("No subjects yet.")

st.divider()

# ── All papers — searchable / filterable / deletable ────────────────────────
st.subheader("All Uploaded Papers")

col_filter, col_search = st.columns([1, 2])
subject_filter = col_filter.selectbox(
    "Filter by subject", ["All subjects"] + sorted(df["subject_code"].unique().tolist())
)
search_term = col_search.text_input("Search filename", placeholder="e.g. BCS502 or JAN 2025")

filtered = papers
if subject_filter != "All subjects":
    filtered = [p for p in filtered if p["subject_code"] == subject_filter]
if search_term.strip():
    term = search_term.strip().lower()
    filtered = [p for p in filtered if term in p["filename"].lower()]

st.caption(f"Showing {len(filtered)} of {len(papers)} paper(s)")

for p in filtered:
    with st.container(border=True):
        col_info, col_del = st.columns([5, 1])
        period = f"{p.get('month') or '?'} {p.get('year') or '?'}"
        col_info.markdown(
            f"📄 `{p['filename']}`  \n"
            f"**{p['subject_code']}** — {p.get('subject_name', '?')}  |  "
            f"{period}  |  *{p.get('pdf_type', '?')}*"
        )
        if col_del.button("Delete", key=f"admin_del_{p['id']}", type="secondary"):
            try:
                delete_paper(DB_PATH, p["id"])
                st.success(f"Deleted **{p['filename']}**.")
                st.rerun()
            except Exception as e:
                st.error(f"Could not delete paper: {e}")

st.divider()

# ── Danger zone ───────────────────────────────────────────────────────────────
with st.expander("⚠️ Danger Zone — Reset everything"):
    st.warning(
        "This permanently deletes **all papers and analysis** for **every subject**, "
        "for every user of the app. This cannot be undone."
    )
    col_confirm, col_btn = st.columns([3, 1])
    confirm_text = col_confirm.text_input(
        "Type DELETE to confirm",
        placeholder="DELETE",
        label_visibility="collapsed",
        key="admin_confirm_delete",
    )
    if col_btn.button("Clear All Data", type="primary", key="admin_clear_all"):
        if confirm_text.strip().upper() == "DELETE":
            try:
                clear_all_data(DB_PATH)
                st.success("All data cleared.")
                st.rerun()
            except Exception as e:
                st.error(f"Reset failed: {e}")
        else:
            st.error("Type DELETE in the box first to confirm.")