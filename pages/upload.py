"""
pages/1_Upload.py — F33
PDF upload interface with live progress bar.
Saves uploaded files, runs the full pipeline, shows summary.
"""

import os
import tempfile
from pathlib import Path

import streamlit as st
import yaml

st.set_page_config(page_title="Upload — ExamLens", layout="wide")
st.title("Upload Question Papers")
st.caption("Supports native text PDFs and scanned PDFs (OCR applied automatically)")

# ── Inputs ────────────────────────────────────────────────────────────────────
col1, col2 = st.columns([2, 1])
with col1:
    uploaded_files = st.file_uploader(
        "Drop your question papers here",
        type=["pdf"],
        accept_multiple_files=True,
        help="You can upload multiple years at once. Name files like 2021_subject.pdf for best results.",
    )
with col2:
    subject_override = st.text_input(
        "Subject (optional)",
        placeholder="e.g. Data Structures",
        help="Leave blank to auto-detect from filename",
    )
    force_rerun = st.checkbox("Force re-process all files", value=False)

st.divider()

# ── Run pipeline ──────────────────────────────────────────────────────────────
if uploaded_files:
    st.write(f"**{len(uploaded_files)} file(s) selected:**")
    for f in uploaded_files:
        st.write(f"  - {f.name}")

    if st.button("Process Papers", type="primary", use_container_width=True):
        # Save uploaded files to data/raw/
        raw_dir = Path("data/raw")
        raw_dir.mkdir(parents=True, exist_ok=True)
        saved_paths = []
        for uf in uploaded_files:
            save_path = raw_dir / uf.name
            with open(save_path, "wb") as f:
                f.write(uf.read())
            saved_paths.append(str(save_path))

        # Progress display
        status_text = st.empty()
        progress_bar = st.progress(0)

        def update_progress(stage: str, pct: int):
            status_text.write(f"**{stage}**")
            progress_bar.progress(pct)

        try:
            from pipeline import run
            result = run(
                pdf_paths=saved_paths,
                subject=subject_override or None,
                force=force_rerun,
                progress_callback=update_progress,
            )

            if "error" in result:
                st.error(result["error"])
            else:
                st.success("Pipeline complete!")
                progress_bar.progress(100)
                status_text.empty()

                # Summary metrics
                m1, m2, m3 = st.columns(3)
                m1.metric("Questions Extracted", result["total_questions"])
                m2.metric("Topics Found", result["total_clusters"])
                m3.metric("Papers Processed", result["papers_processed"])

                st.info("Navigate to **Question Bank** in the sidebar to explore results.")

        except Exception as e:
            st.error(f"Pipeline failed: {e}")
            raise
else:
    st.info("Upload one or more PDF question papers above to begin.")