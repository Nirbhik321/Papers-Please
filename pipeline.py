"""
pipeline.py
Orchestrates the full Review-1 pipeline:
  ingest → segment → embed → cluster → label → score → export

Called by both cli.py and the Streamlit upload page.
Each stage checks for existing output and skips if already done
(unless force=True is passed).
"""

import json
import os
from pathlib import Path

import pandas as pd
import yaml


def load_config(config_path: str = "config.yaml") -> dict:
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def run(
    pdf_paths: list[str],
    subject: str | None = None,
    config_path: str = "config.yaml",
    force: bool = False,
    progress_callback=None,  # optional callable(stage: str, pct: int)
) -> dict:
    """
    Main pipeline entry point.
    Returns a summary dict with counts and output paths.
    """
    cfg = load_config(config_path)
    db_path = cfg["paths"]["db_path"]
    extracted_dir = cfg["paths"]["extracted_dir"]
    embeddings_dir = cfg["paths"]["embeddings_dir"]
    output_dir = cfg["paths"]["output_dir"]

    os.makedirs(extracted_dir, exist_ok=True)
    os.makedirs(embeddings_dir, exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    # ── Stage 0: Init DB ──────────────────────────────────────────────────────
    from modules.db import init_db
    init_db(db_path)

    # ── Stage 1: Ingest + Segment ─────────────────────────────────────────────
    _progress(progress_callback, "Ingesting PDFs...", 5)
    from modules.ingestion import load_pdf, pages_to_text
    from modules.segmentor import segment_questions, parse_filename_metadata
    from modules.db import insert_question, get_all_questions

    all_questions_inserted = 0
    for pdf_path in pdf_paths:
        fname = Path(pdf_path).name
        extracted_path = Path(extracted_dir) / (Path(pdf_path).stem + ".json")

        if not force and extracted_path.exists():
            print(f"  Skipping {fname} (already extracted)")
            continue

        print(f"\n  Processing: {fname}")
        pages = load_pdf(
            pdf_path,
            min_chars_per_page=cfg["ingestion"]["min_chars_per_page"],
            dpi=cfg["ingestion"]["ocr_dpi"],
        )
        full_text, mean_conf = pages_to_text(pages)

        year_from_file, subject_from_file = parse_filename_metadata(fname)
        year = year_from_file
        subj = subject or subject_from_file

        questions = segment_questions(
            raw_text=full_text,
            year=year,
            subject=subj,
            source_file=fname,
            ocr_confidence=mean_conf,
            min_length=cfg["segmentation"]["min_question_length"],
        )

        for q in questions:
            insert_question(db_path, q)

        # Save extracted JSON for inspection
        with open(extracted_path, "w") as f:
            json.dump(questions, f, indent=2)

        print(f"  Extracted {len(questions)} questions from {fname}")
        all_questions_inserted += len(questions)

    # ── Stage 2: Embed ────────────────────────────────────────────────────────
    _progress(progress_callback, "Generating embeddings...", 30)
    from modules.embedder import encode_questions, reduce_umap, load_question_ids
    from modules.db import get_all_questions

    all_qs = get_all_questions(db_path, canonical_only=False)
    if not all_qs:
        return {"error": "No questions found. Check your PDFs."}

    texts = [q["text"] for q in all_qs]
    ids = [q["id"] for q in all_qs]

    vectors_768 = encode_questions(
        texts=texts,
        question_ids=ids,
        model_name=cfg["embedding"]["model_name"],
        batch_size=cfg["embedding"]["batch_size"],
        cache_dir=embeddings_dir,
        force=force,
    )

    # ── Stage 3: UMAP ─────────────────────────────────────────────────────────
    _progress(progress_callback, "Reducing dimensions...", 50)
    vectors_5d = reduce_umap(
        vectors_768,
        n_components=cfg["clustering"]["umap_n_components_cluster"],
        n_neighbors=cfg["clustering"]["umap_n_neighbors"],
        min_dist=cfg["clustering"]["umap_min_dist"],
        cache_dir=embeddings_dir,
        cache_name="vectors_5d",
        force=force,
    )
    vectors_2d = reduce_umap(
        vectors_768,
        n_components=cfg["clustering"]["umap_n_components_vis"],
        n_neighbors=cfg["clustering"]["umap_n_neighbors"],
        min_dist=cfg["clustering"]["umap_min_dist"],
        cache_dir=embeddings_dir,
        cache_name="vectors_2d",
        force=force,
    )

    # ── Stage 4: Cluster ──────────────────────────────────────────────────────
    _progress(progress_callback, "Clustering questions...", 65)
    from modules.clusterer import cluster_questions, get_cluster_summary
    from modules.db import update_cluster

    id_to_cluster = cluster_questions(
        vectors_5d,
        question_ids=ids,
        min_cluster_size=cfg["clustering"]["hdbscan_min_cluster_size"],
        min_samples=cfg["clustering"]["hdbscan_min_samples"],
    )

    cluster_to_qids = get_cluster_summary(id_to_cluster)

    # ── Stage 5: Label ────────────────────────────────────────────────────────
    _progress(progress_callback, "Labelling topics...", 75)
    from modules.labeller import label_clusters
    from modules.db import upsert_cluster_label

    qid_to_text = {q["id"]: q["text"] for q in all_qs}
    cluster_labels = label_clusters(cluster_to_qids, qid_to_text)

    # Write cluster ids and labels back to DB
    for qid, cid in id_to_cluster.items():
        label = cluster_labels.get(cid, f"Topic {cid}") if cid >= 0 else "Noise"
        update_cluster(db_path, qid, cid, label)

    for cid, qids in cluster_to_qids.items():
        label = cluster_labels.get(cid, f"Topic {cid}")
        rep = qid_to_text.get(qids[0], "")[:100]
        upsert_cluster_label(db_path, cid, label, len(qids), rep)

    # ── Stage 6: Score ────────────────────────────────────────────────────────
    _progress(progress_callback, "Scoring questions...", 85)
    from modules.scorer import compute_scores
    from modules.db import update_scores

    all_qs_fresh = get_all_questions(db_path, canonical_only=True)
    scored = compute_scores(
        all_qs_fresh,
        decay=cfg["scoring"]["recency_decay"],
        heat_high=cfg["scoring"]["heat_high_threshold"],
        heat_mid=cfg["scoring"]["heat_mid_threshold"],
    )

    for q in scored:
        update_scores(
            db_path,
            question_id=q["id"],
            heat_score=q["heat_score"],
            heat_tag=q["heat_tag"],
            frequency_raw=q["frequency_raw"],
            years_appeared=json.loads(q.get("years_appeared", "[]")),
        )

    # ── Stage 7: Export CSV ───────────────────────────────────────────────────
    _progress(progress_callback, "Exporting question bank...", 93)
    bank_path = _export_bank(scored, output_dir)

    # ── Stage 8: Scatter plot ─────────────────────────────────────────────────
    _progress(progress_callback, "Building visualisation...", 97)
    import numpy as np
    from modules.visualiser import build_scatter

    q_ids_loaded = load_question_ids(embeddings_dir)
    scatter_path = build_scatter(
        vectors_2d=vectors_2d,
        question_ids=q_ids_loaded.tolist() if q_ids_loaded is not None else ids,
        questions=scored,
        output_path=str(Path(output_dir) / "cluster_scatter.html"),
    )

    _progress(progress_callback, "Done!", 100)

    return {
        "total_questions": len(scored),
        "total_clusters": len(cluster_to_qids),
        "papers_processed": len(pdf_paths),
        "bank_path": bank_path,
        "scatter_path": scatter_path,
        "db_path": db_path,
    }


def _export_bank(questions: list[dict], output_dir: str) -> str:
    """Export question bank to CSV sorted by heat_score descending."""
    rows = []
    for q in questions:
        rows.append({
            "Question": q["text"],
            "Topic": q.get("cluster_label") or "Unclustered",
            "Years Appeared": q.get("years_appeared", "[]"),
            "Frequency": q.get("frequency_raw", 1),
            "Heat Score": round(q.get("heat_score", 0), 3),
            "Heat Tag": q.get("heat_tag", "LOW"),
            "Marks": q.get("marks", ""),
            "Subject": q.get("subject", ""),
            "Section": q.get("section", ""),
        })

    df = pd.DataFrame(rows).sort_values("Heat Score", ascending=False)
    path = str(Path(output_dir) / "question_bank.csv")
    df.to_csv(path, index=False)
    print(f"  Question bank saved → {path}")
    return path


def _progress(callback, stage: str, pct: int) -> None:
    print(f"[{pct:3d}%] {stage}")
    if callback:
        callback(stage, pct)