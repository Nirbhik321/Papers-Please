"""
visualiser.py — F14
Plotly interactive 2D scatter plot.
Each dot = one question. Colour = cluster. Hover = full question text.
"""

import json
import numpy as np


def build_scatter(
    vectors_2d: np.ndarray,
    question_ids: list[int],
    questions: list[dict],
    output_path: str = "output/cluster_scatter.html",
) -> str:
    """
    Build and save an interactive Plotly scatter plot.
    Returns the path to the saved HTML file.
    """
    import plotly.graph_objects as go

    # Build lookup by id
    qid_map = {q["id"]: q for q in questions}

    # Prepare data per cluster
    cluster_data: dict[int, dict] = {}
    for i, qid in enumerate(question_ids):
        q = qid_map.get(int(qid))
        if q is None:
            continue
        cid = q.get("cluster_id", -1)
        if cid not in cluster_data:
            cluster_data[cid] = {
                "x": [], "y": [], "texts": [], "ids": [],
                "label": q.get("cluster_label") or (f"Cluster {cid}" if cid >= 0 else "Noise"),
            }
        cluster_data[cid]["x"].append(float(vectors_2d[i, 0]))
        cluster_data[cid]["y"].append(float(vectors_2d[i, 1]))
        cluster_data[cid]["texts"].append(q["text"][:120] + "..." if len(q["text"]) > 120 else q["text"])
        cluster_data[cid]["ids"].append(qid)

    traces = []
    colors = [
        "#378ADD", "#1D9E75", "#BA7517", "#A32D2D", "#7F77DD",
        "#D85A30", "#1a7a4a", "#6d28d9", "#0891b2", "#be185d",
        "#15803d", "#b45309", "#1d4ed8", "#7c3aed", "#047857",
    ]

    # Noise cluster last, greyed out
    sorted_clusters = sorted(cluster_data.keys(), key=lambda x: (x == -1, x))

    for i, cid in enumerate(sorted_clusters):
        data = cluster_data[cid]
        color = "#CCCCCC" if cid == -1 else colors[i % len(colors)]
        opacity = 0.4 if cid == -1 else 0.85

        traces.append(go.Scatter(
            x=data["x"],
            y=data["y"],
            mode="markers",
            name=data["label"],
            marker=dict(size=7, color=color, opacity=opacity,
                        line=dict(width=0.5, color="white")),
            text=data["texts"],
            hovertemplate="<b>%{text}</b><extra>" + data["label"] + "</extra>",
        ))

    fig = go.Figure(traces)
    fig.update_layout(
        title="Question Semantic Clusters",
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False, title=""),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False, title=""),
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(
            orientation="v",
            x=1.01, y=1,
            bordercolor="#EEEEEE",
            borderwidth=1,
            font=dict(size=11),
        ),
        margin=dict(l=20, r=20, t=50, b=20),
        height=600,
    )

    import os
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.write_html(output_path, include_plotlyjs="cdn")
    print(f"  Scatter plot saved → {output_path}")
    return output_path


def get_plotly_figure(
    vectors_2d: np.ndarray,
    question_ids: list[int],
    questions: list[dict],
):
    """
    Return a Plotly Figure object (for embedding directly in Streamlit).
    Same as build_scatter but returns fig instead of saving HTML.
    """
    import plotly.graph_objects as go

    qid_map = {q["id"]: q for q in questions}
    cluster_data: dict[int, dict] = {}

    for i, qid in enumerate(question_ids):
        q = qid_map.get(int(qid))
        if q is None:
            continue
        cid = q.get("cluster_id", -1)
        if cid not in cluster_data:
            cluster_data[cid] = {
                "x": [], "y": [], "texts": [],
                "label": q.get("cluster_label") or (f"Cluster {cid}" if cid >= 0 else "Noise"),
            }
        cluster_data[cid]["x"].append(float(vectors_2d[i, 0]))
        cluster_data[cid]["y"].append(float(vectors_2d[i, 1]))
        text = q["text"][:120] + "..." if len(q["text"]) > 120 else q["text"]
        cluster_data[cid]["texts"].append(text)

    colors = [
        "#378ADD", "#1D9E75", "#BA7517", "#A32D2D", "#7F77DD",
        "#D85A30", "#1a7a4a", "#6d28d9", "#0891b2", "#be185d",
        "#15803d", "#b45309", "#1d4ed8", "#7c3aed", "#047857",
    ]

    traces = []
    sorted_clusters = sorted(cluster_data.keys(), key=lambda x: (x == -1, x))
    for i, cid in enumerate(sorted_clusters):
        data = cluster_data[cid]
        color = "#CCCCCC" if cid == -1 else colors[i % len(colors)]
        opacity = 0.4 if cid == -1 else 0.85
        traces.append(go.Scatter(
            x=data["x"], y=data["y"],
            mode="markers",
            name=data["label"],
            marker=dict(size=7, color=color, opacity=opacity,
                        line=dict(width=0.5, color="white")),
            text=data["texts"],
            hovertemplate="<b>%{text}</b><extra>" + data["label"] + "</extra>",
        ))

    fig = go.Figure(traces)
    fig.update_layout(
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(orientation="v", x=1.01, y=1, font=dict(size=11)),
        margin=dict(l=10, r=10, t=10, b=10),
        height=520,
    )
    return fig