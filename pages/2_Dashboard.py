"""
2_Dashboard.py — Subject analysis dashboard with cheat sheet export.

Pick one subject from the dropdown; only that subject's analysis is built
and rendered. Single-paper mode is automatically activated when only one
paper exists for the selected subject.
"""

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from modules.db import init_db
from modules.scorer import format_years, format_appearances, MAX_MODULE_MARKS
from modules.exporter import generate_cheat_sheet, generate_csv
from theme import inject_theme, exam_header, stamp, mark_circle
from data_cache import get_distinct_subjects_cached, get_module_analysis_cached, db_version

DB_PATH = str(Path(__file__).parent.parent / "data" / "papers.db")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
init_db(DB_PATH)

inject_theme()

exam_header(
    title="DASHBOARD",
    subtitle="Every subject that's been uploaded, ranked and ready to study.",
    time="Browse freely",
    max_marks="All subjects included",
    show_usn=False,
)


# ── Helper: render one module ──────────────────────────────────────────────────

def render_module(steps: list[dict], total_papers: int, module_no: int):
    single_paper = (total_papers == 1)

    if not steps:
        st.info("No questions found for this module.")
        return

    if single_paper:
        st.subheader(f"Module {module_no} — Topics in this paper")
        st.caption("Ranked by marks. Upload more papers to see repeat patterns.")
    else:
        st.subheader(f"Module {module_no} — Most Repeated Questions")

    for step in steps:
        freq       = step["frequency"]
        freq_pct   = step["frequency_pct"]
        label      = step.get("topic_label") or step["representative_text"][:55]
        avg_m      = step.get("avg_marks") or 0
        years      = step.get("years", [])
        appearances = step.get("appearances", [])
        text       = step["representative_text"]

        with st.container(border=True):
            if single_paper:
                header = f"**{label}**  —  {int(avg_m)}M"
                st.markdown(header)
            else:
                if freq_pct >= 0.8:
                    circle = mark_circle(f"{int(freq_pct*100)}%", "high")
                elif freq_pct >= 0.5:
                    circle = mark_circle(f"{int(freq_pct*100)}%", "mid")
                else:
                    circle = mark_circle(f"{int(freq_pct*100)}%", "low")
                st.markdown(
                    f'{circle}<strong>{label}</strong>&nbsp;&nbsp;'
                    f'<span class="marks-bracket">[{freq}/{total_papers} papers · {int(avg_m)}M avg]</span>',
                    unsafe_allow_html=True,
                )

            col_bar, col_meta = st.columns([2, 3])

            with col_bar:
                if not single_paper:
                    st.progress(freq_pct, text=f"{freq_pct * 100:.0f}% of papers")
                st.caption(f"**Average marks:** {int(avg_m)}M")
                if years:
                    st.caption(f"**Years seen:** {format_years(years)}")

            with col_meta:
                if appearances:
                    st.caption(f"**Found in:** {format_appearances(appearances)}")
                st.markdown(f'*"{text}"*')

    st.divider()

    # Marks ladder
    if single_paper:
        st.subheader("Topics by Marks")
        st.caption("Study these topics to cover the module's marks.")
    else:
        st.subheader("Marks You Can Lock In")

    ladder_rows = []
    for step in steps:
        cum = step.get("cumulative_expected", 0)
        label_short = (step.get("topic_label") or "...")[:35]
        ladder_rows.append({
            "Priority": f"#{step['rank']}",
            "Topic": label_short,
            "Expected marks": f"~{cum:.0f}M / {MAX_MODULE_MARKS}M",
            "Full coverage": "YES" if step["full_coverage"] else "",
        })

    st.dataframe(pd.DataFrame(ladder_rows), use_container_width=True, hide_index=True)

    full_at = next((s for s in steps if s["full_coverage"]), None)
    if full_at:
        n = full_at["rank"]
        st.success(
            f"Study the top {n} topic{'s' if n > 1 else ''} "
            f"to cover the full module (~{int(MAX_MODULE_MARKS)}M expected)"
        )


# ── Main: pick one subject, render only that one ────────────────────────────────
# Previously this rendered every subject's cards simultaneously (all expanded).
# Streamlit builds and sends the *entire* rendered tree on every single click
# anywhere on the page, regardless of what's expanded/active — so with many
# subjects, every click got slower forever. Picking one subject at a time keeps
# each rerun scoped to only what's on screen.

_db_v = db_version(DB_PATH)
subjects = get_distinct_subjects_cached(DB_PATH, _db_v)

if not subjects:
    st.info("No papers in the database yet. Go to **Upload** to add papers.")
    st.stop()

subject_options = {
    f"{s['subject_code']} — {s['subject_name']}": s for s in subjects
}
selected_label = st.selectbox(
    f"Subject  ({len(subjects)} available)",
    list(subject_options.keys()),
)
subj = subject_options[selected_label]

subject_code  = subj["subject_code"]
subject_name  = subj["subject_name"]
paper_count   = subj["paper_count"]
min_yr        = subj.get("min_year") or "?"
max_yr        = subj.get("max_year") or "?"
single_paper  = (paper_count == 1)

year_range = str(min_yr) if min_yr == max_yr else f"{min_yr}–{max_yr}"
mode_badge = "Single Paper" if single_paper else f"{paper_count} papers"

st.markdown(
    f'{stamp(subject_code)}&nbsp;&nbsp;**{subject_name}**&nbsp;&nbsp;'
    f'<span class="marks-bracket">[{mode_badge} · {year_range}]</span>',
    unsafe_allow_html=True,
)

if single_paper:
    st.info(
        "Only 1 paper available. Showing topic structure and marks breakdown. "
        "Upload more papers of the same subject to unlock repeat-pattern analysis.",
        icon="📋",
    )

# Load analysis
try:
    module_ladders, total_papers_loaded = get_module_analysis_cached(
        DB_PATH, subject_code, _db_v
    )
except Exception as e:
    st.error(
        f"Could not load analysis for {subject_code}: {str(e)[:200]}. "
        "Try re-uploading the papers."
    )
    st.stop()

if not module_ladders:
    st.warning(
        "No analysis data found. "
        "The papers may still be processing or the PDF could not be parsed."
    )
    st.stop()

# Summary metrics row
total_canonicals = sum(len(s) for s in module_ladders.values())
modules_covered  = len(module_ladders)

m1, m2, m3 = st.columns(3)
m1.metric("Unique Question Topics", total_canonicals)
m2.metric("Modules with Data", modules_covered)
if not single_paper:
    guaranteed = sum(
        1 for steps in module_ladders.values()
        for s in steps if s["frequency_pct"] >= 1.0
    )
    m3.metric("Topics in ALL Papers", guaranteed)
else:
    total_marks = sum(
        s.get("avg_marks") or 0
        for steps in module_ladders.values()
        for s in steps
    )
    m3.metric("Total Marks Mapped", f"{int(total_marks)}M")

st.divider()

# Module tabs
module_tabs = st.tabs(
    [f"Module {n}" for n in sorted(module_ladders.keys())]
)
for tab, module_no in zip(module_tabs, sorted(module_ladders.keys())):
    with tab:
        render_module(module_ladders[module_no], total_papers_loaded, module_no)

# Export
st.divider()
col_pdf, col_csv = st.columns(2)

with col_pdf:
    if st.button(
        f"Generate Cheat Sheet PDF — {subject_code}",
        key=f"pdf_{subject_code}",
        type="primary",
    ):
        with st.spinner("Building PDF..."):
            try:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    out_path = tmp.name

                generate_cheat_sheet(
                    subject_name=subject_name,
                    subject_code=subject_code,
                    module_ladders=module_ladders,
                    total_papers=total_papers_loaded,
                    output_path=out_path,
                )

                with open(out_path, "rb") as f:
                    pdf_bytes = f.read()

                st.download_button(
                    label=f"Download {subject_code} Cheat Sheet",
                    data=pdf_bytes,
                    file_name=f"{subject_code}_cheat_sheet.pdf",
                    mime="application/pdf",
                    key=f"dl_{subject_code}",
                )

            except Exception as e:
                st.error(
                    f"PDF generation failed: {str(e)[:200]}. "
                    "Try again or check that all papers are processed."
                )

with col_csv:
    csv_data = generate_csv(
        subject_name=subject_name,
        subject_code=subject_code,
        module_ladders=module_ladders,
        total_papers=total_papers_loaded,
    )
    st.download_button(
        label=f"Download Question Bank CSV — {subject_code}",
        data=csv_data,
        file_name=f"{subject_code}_question_bank.csv",
        mime="text/csv",
        key=f"csv_{subject_code}",
    )