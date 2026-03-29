"""
pages/2_Question_Bank.py — F34 F36
Question bank viewer with:
- Stats dashboard header (F36)
- Filterable question table (F34)
- Cluster scatter plot (F14)
- CSV download
"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Question Bank — ExamLens", layout="wide")

# ── Load config ───────────────────────────────────────────────────────────────
import yaml
try:
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    db_path = cfg["paths"]["db_path"]
    embeddings_dir = cfg["paths"]["embeddings_dir"]
    output_dir = cfg["paths"]["output_dir"]
except FileNotFoundError:
    st.error("config.yaml not found. Make sure you run from the examlens/ directory.")
    st.stop()

# ── Check DB exists ───────────────────────────────────────────────────────────
if not Path(db_path).exists():
    st.title("Question Bank")
    st.info("No data yet — go to **Upload** and process some papers first.")
    st.stop()

from modules.db import get_all_questions, get_stats

# ── F36: Stats dashboard header ───────────────────────────────────────────────
st.title("Question Bank")
stats = get_stats(db_path)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Questions", stats["total_questions"])
c2.metric("Topics Found", stats["total_topics"])
c3.metric("Papers Processed", stats["total_papers"])
c4.metric("Top Topic", stats["top_topic"], f"{stats['top_score']}% heat")

st.divider()

# ── Load questions ─────────────────────────────────────────────────────────────
questions = get_all_questions(db_path, canonical_only=True)
if not questions:
    st.info("No questions found. Upload some papers first.")
    st.stop()

# Build dataframe
rows = []
for q in questions:
    years = json.loads(q.get("years_appeared") or "[]")
    years_str = ", ".join(str(y) for y in sorted(set(y for y in years if y)) )
    rows.append({
        "id": q["id"],
        "Question": q["text"],
        "Topic": q.get("cluster_label") or "Unclustered",
        "Heat": q.get("heat_tag", "LOW"),
        "Score": round(q.get("heat_score", 0), 3),
        "Frequency": q.get("frequency_raw", 1),
        "Marks": q.get("marks") or "—",
        "Years": years_str or str(q.get("year") or "—"),
        "Subject": q.get("subject") or "—",
        "Section": q.get("section") or "—",
    })

df = pd.DataFrame(rows).sort_values("Score", ascending=False)

# ── F34: Filters ──────────────────────────────────────────────────────────────
st.subheader("Filters")
fcol1, fcol2, fcol3 = st.columns(3)

with fcol1:
    topics = ["All"] + sorted(df["Topic"].unique().tolist())
    selected_topic = st.selectbox("Topic", topics)

with fcol2:
    heat_options = ["All", "HIGH", "MEDIUM", "LOW"]
    selected_heat = st.selectbox("Heat Tag", heat_options)

with fcol3:
    subjects = ["All"] + sorted(df["Subject"].unique().tolist())
    selected_subject = st.selectbox("Subject", subjects)

# Apply filters
filtered = df.copy()
if selected_topic != "All":
    filtered = filtered[filtered["Topic"] == selected_topic]
if selected_heat != "All":
    filtered = filtered[filtered["Heat"] == selected_heat]
if selected_subject != "All":
    filtered = filtered[filtered["Subject"] == selected_subject]

st.caption(f"Showing {len(filtered)} of {len(df)} questions")

# ── Colour-coded table ────────────────────────────────────────────────────────

def heat_color(val):
    if val == "HIGH":
        return "background-color: #fde8e8; color: #A32D2D; font-weight: 600"
    elif val == "MEDIUM":
        return "background-color: #fef3cd; color: #BA7517; font-weight: 600"
    return "color: #888"

display_cols = ["Question", "Topic", "Heat", "Score", "Frequency", "Marks", "Years"]
styled = (
    filtered[display_cols]
    .style
    .map(heat_color, subset=["Heat"])
    .format({"Score": "{:.3f}"})
)

st.dataframe(styled, use_container_width=True, height=420)

# ── Download ───────────────────────────────────────────────────────────────────
csv_bytes = filtered[display_cols].to_csv(index=False).encode("utf-8")
st.download_button(
    label="Download CSV",
    data=csv_bytes,
    file_name="question_bank_filtered.csv",
    mime="text/csv",
    use_container_width=True,
)

st.divider()

# ── F14: Scatter plot ─────────────────────────────────────────────────────────
st.subheader("Semantic Topic Clusters")
st.caption("Each dot is a question. Colour = topic cluster. Hover to read the question.")

import numpy as np
from pathlib import Path

vec2d_path = Path(embeddings_dir) / "vectors_2d.npy"
ids_path = Path(embeddings_dir) / "question_ids.npy"

if vec2d_path.exists() and ids_path.exists():
    vectors_2d = np.load(str(vec2d_path))
    question_ids = np.load(str(ids_path)).tolist()

    from modules.visualiser import get_plotly_figure
    fig = get_plotly_figure(vectors_2d, question_ids, questions)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Run the pipeline first to generate the cluster visualisation.")