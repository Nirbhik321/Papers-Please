"""
clusterer.py — F11
HDBSCAN clustering on UMAP-reduced embeddings.
Writes cluster_id back to DB for every question.
"""

import numpy as np


def cluster_questions(
    vectors_5d: np.ndarray,
    question_ids: list[int],
    min_cluster_size: int = 5,
    min_samples: int = 3,
) -> dict[int, int]:
    """
    Run HDBSCAN on 5-dimensional UMAP vectors.
    Returns dict: {question_id: cluster_id}
    Cluster -1 means noise (outlier).

    Falls back to a single cluster (0) when there are too few points
    for HDBSCAN to build its KD-tree (n_points < min_samples).
    """
    n_points = len(vectors_5d)

    # HDBSCAN requires at least min_samples points to build its KD-tree.
    # With too few questions, assign everything to one cluster and skip.
    if n_points < min_samples:
        print(f"  Too few points ({n_points}) for HDBSCAN "
              f"(min_samples={min_samples}) — assigning to single cluster.")
        return {int(qid): 0 for qid in question_ids}

    print(f"  Running HDBSCAN (min_cluster_size={min_cluster_size})...")
    import hdbscan

    # Clamp min_cluster_size so it never exceeds the point count
    effective_min_cluster = min(min_cluster_size, n_points)

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=effective_min_cluster,
        min_samples=min_samples,
        metric="euclidean",
        cluster_selection_method="eom",
    )
    labels = clusterer.fit_predict(vectors_5d)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = int((labels == -1).sum())
    print(f"  Found {n_clusters} clusters, {n_noise} noise points")

    return {int(qid): int(label) for qid, label in zip(question_ids, labels)}


def get_cluster_summary(id_to_cluster: dict[int, int]) -> dict[int, list[int]]:
    """
    Invert the mapping: {cluster_id: [question_ids]}
    Excludes noise cluster (-1).
    """
    summary: dict[int, list[int]] = {}
    for qid, cid in id_to_cluster.items():
        if cid == -1:
            continue
        summary.setdefault(cid, []).append(qid)
    return summary