"""
1_Upload.py — Upload PDFs and trigger the pipeline.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

import pipeline
from modules.db import get_all_papers, init_db, delete_paper, clear_all_data

DB_PATH = str(Path(__file__).parent.parent / "data" / "papers.db")
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
init_db(DB_PATH)

st.set_page_config(page_title="Upload | Papers Please", page_icon="📄", layout="wide")

st.title("📄 Upload Question Papers")

st.info(
    "**Papers accumulate — they are never overwritten.** "
    "Upload more papers for the same subject and the analysis updates automatically. "
    "Different subjects (BCS502, BCS503 …) each get their own section in the Dashboard. "
    "Files don't need a specific name — the subject is read from the PDF content too.",
    icon="ℹ️",
)

# ── Upload widget ───────────────────────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "Drop your PDFs here",
    type=["pdf"],
    accept_multiple_files=True,
    help=(
        "Naming files like 'JAN 2025 BCS502.pdf' gives the best metadata. "
        "If the name doesn't contain a subject code the system will try to read it from the PDF."
    ),
)

col_force, col_run = st.columns([1, 3])
force = col_force.checkbox("Force re-process (ignore cache)", value=False)

if uploaded_files and col_run.button("Process Papers", type="primary"):
    # Save to disk first
    saved_paths: list[str] = []
    save_errors: list[str] = []
    for uf in uploaded_files:
        try:
            dest = RAW_DIR / uf.name
            dest.write_bytes(uf.read())
            saved_paths.append(str(dest))
        except Exception as e:
            save_errors.append(f"Could not save {uf.name}: {e}")

    if save_errors:
        for msg in save_errors:
            st.warning(msg)

    if not saved_paths:
        st.error("No files could be saved. Check disk space and try again.")
        st.stop()

    # Run pipeline with a clean step-by-step status display
    step_log: list[str] = []
    progress_bar = st.progress(0)
    status_box = st.empty()

    def _on_progress(msg: str, pct: float):
        progress_bar.progress(max(0, min(100, int(pct))))
        step_log.append(msg)
        # Show last 12 steps — clean list, no code block
        lines = "\n".join(f"• {l}" for l in step_log[-12:])
        status_box.markdown(lines)

    summary: dict = {}
    pipeline_ok = True

    try:
        summary = pipeline.run(
            pdf_paths=saved_paths,
            db_path=DB_PATH,
            force=force,
            progress_callback=_on_progress,
        )
    except Exception as e:
        pipeline_ok = False
        status_box.empty()
        st.error(
            f"An unexpected error stopped the pipeline: **{type(e).__name__}**\n\n"
            f"{str(e)[:300]}\n\n"
            "Try re-uploading the file or check that the PDF is not corrupted."
        )

    progress_bar.progress(100)

    if pipeline_ok:
        status_box.empty()
        st.divider()
        st.subheader("Results")
        c1, c2, c3 = st.columns(3)
        c1.metric("Papers Added", summary.get("papers_added", 0))
        c2.metric("Questions Extracted", summary.get("sub_questions_added", 0))
        c3.metric("Subjects Updated", len(summary.get("subjects_processed", [])))

        errors = summary.get("errors", [])
        if errors:
            with st.expander(f"⚠️ {len(errors)} file(s) had issues — click to see details"):
                for err in errors:
                    st.warning(err)
        else:
            st.success(
                "All papers processed successfully. "
                "Head to the **Dashboard** to see your analysis."
            )

# ── Papers in database ──────────────────────────────────────────────────────────
st.divider()
st.subheader("Papers in Database")

papers = get_all_papers(DB_PATH)

if not papers:
    st.info("No papers uploaded yet. Use the uploader above to get started.")
else:
    df = pd.DataFrame(papers)
    subjects_present = df["subject_code"].unique().tolist()
    st.caption(
        f"{len(papers)} paper(s) across {len(subjects_present)} subject(s): "
        + ", ".join(subjects_present)
    )

    for subj in subjects_present:
        subj_papers = [p for p in papers if p["subject_code"] == subj]
        subj_name = subj_papers[0]["subject_name"]

        with st.expander(
            f"**{subj}** — {subj_name}  ({len(subj_papers)} paper(s))",
            expanded=True,
        ):
            for p in subj_papers:
                col_info, col_del = st.columns([5, 1])
                period = f"{p.get('month') or '?'} {p.get('year') or '?'}"
                col_info.markdown(
                    f"📄 `{p['filename']}`  —  {period}  |  *{p.get('pdf_type', '?')}*"
                )
                if col_del.button("Remove", key=f"del_{p['id']}", type="secondary"):
                    try:
                        delete_paper(DB_PATH, p["id"])
                        st.success(
                            f"Removed **{p['filename']}**. "
                            "Re-upload papers for this subject to refresh its analysis."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not remove paper: {e}")

# ── Danger zone ─────────────────────────────────────────────────────────────────
st.divider()
with st.expander("⚠️ Danger Zone — Reset everything"):
    st.warning(
        "This permanently deletes **all papers and analysis** from the database. "
        "Use this to start completely fresh."
    )
    col_confirm, col_btn = st.columns([3, 1])
    confirm_text = col_confirm.text_input(
        "Type DELETE to confirm",
        placeholder="DELETE",
        label_visibility="collapsed",
    )
    if col_btn.button("Clear All Data", type="primary"):
        if confirm_text.strip().upper() == "DELETE":
            try:
                clear_all_data(DB_PATH)
                st.success("All data cleared. You can now start fresh.")
                st.rerun()
            except Exception as e:
                st.error(f"Reset failed: {e}")
        else:
            st.error("Type DELETE in the box first to confirm.")
