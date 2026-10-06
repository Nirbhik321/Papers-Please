"""
deduplicator.py — Module-level semantic deduplication.

Groups sub_questions from the same (subject, module) across ALL papers
into canonical questions using Sentence-BERT + cosine similarity.

Key rule: position (q_no, sub_q) is IRRELEVANT for identity.
  Paper A: Module 2, Q.3a → "Explain CRC encoder"
  Paper B: Module 2, Q.4b → "Define CRC. Explain CRC encoder operation"
  → Same canonical question (similarity > threshold)

Algorithm: average-linkage agglomerative clustering (default).
  Start with every question on its own and repeatedly merge the two groups
  whose questions are, on average, most similar — until no pair of groups
  averages above the threshold. Unlike a single seed or centroid, the decision
  uses every pairwise similarity, so one odd phrasing can't drag a group off.
  The older centroid-based greedy clustering is kept as method="greedy".

Model + threshold were chosen on hand-labelled VTU papers (eval/, 4 subjects),
picking τ on three subjects and scoring on the fourth: gte-small + average linkage
chose τ = 0.925 in every fold. gte-small's cosine scores are compressed towards 1,
so its threshold is much higher than other models' (see eval/results/RESULTS.md).
"""

import re
import numpy as np
from modules import embedder


SIMILARITY_THRESHOLD = 0.925  # chosen by leave-one-subject-out evaluation (see docstring)
MIN_TEXT_LENGTH = 12           # ignore garbage OCR fragments


# ── OCR noise cleaner ──────────────────────────────────────────────────────────

_LEADING_JUNK = re.compile(
    r"^[\s_\-|.]*"                    # leading underscores, pipes, dashes
    r"(?:[a-c](?:[.)]|\s)\s*)?"       # sub-question label "a." "b)" "c " — never the start of a word
    r"(?:Q\.?\s*\d{1,2}\.?\s*)?"      # question number "Q.3" etc.
    r"(?:[a-c](?:[.)]|\s|$)\s*)?"     # second sub-label (Q.3a. / Q.3 a)
    r"[\s_\-|.]*",
    re.IGNORECASE,
)
_TRAILING_JUNK = re.compile(r"[\s_\-|.]+$")
_MULTI_SPACE   = re.compile(r"\s{2,}")

# Common OCR run-together prefixes like "AWith" → "With", "Ps Develop" → "Develop"
_OCR_PREFIX = re.compile(r"^[A-Z][a-z]?(With|Explain|Describe|Define|List|Derive|Illustrate)\b")


def _clean_for_embed(text: str) -> str:
    """
    Strip OCR artifacts before embedding so the model sees clean academic text.

    Removes:
      - Leading sub-question labels ("a.", "Q.3", "_b.", pipes)
      - Trailing punctuation noise
      - OCR run-together prefixes ("AWith" → "With", "Ps Develop" → "Develop")
      - Excess whitespace
    """
    text = _LEADING_JUNK.sub("", text).strip()
    text = _TRAILING_JUNK.sub("", text).strip()

    # Fix OCR prefix stuck to a word: "AWith" → "With"
    m = _OCR_PREFIX.match(text)
    if m:
        text = text[m.start(1):]   # slice from the real word start

    text = _MULTI_SPACE.sub(" ", text)
    return text.strip()


def _greedy_clusters(embeddings: np.ndarray, threshold: float) -> list[list[int]]:
    """Original algorithm: greedy assignment to the nearest centroid, then one refinement pass."""
    # ── Centroid-based greedy clustering  (pass 1) ────────────────────────────
    # For each new question, compare against the centroid of every existing
    # cluster.  Assign to the most similar cluster if sim >= threshold,
    # otherwise start a new cluster.
    #
    # Centroid is kept as the running mean of member embeddings (no re-encode).

    n = len(embeddings)
    cluster_members:   list[list[int]]    = []   # indices into the embedding rows
    cluster_centroids: list[np.ndarray]   = []   # mean embedding per cluster

    for i in range(n):
        vec = embeddings[i]

        best_sim   = -1.0
        best_clust = -1

        for ci, centroid in enumerate(cluster_centroids):
            # centroid is already L2-normalised (we re-normalise after each update)
            sim = float(vec @ centroid)
            if sim > best_sim:
                best_sim   = sim
                best_clust = ci

        if best_sim >= threshold:
            # Add to existing cluster and update centroid
            cluster_members[best_clust].append(i)
            old = cluster_centroids[best_clust]
            n_members = len(cluster_members[best_clust])
            new_centroid = old + (vec - old) / n_members   # incremental mean
            norm = np.linalg.norm(new_centroid)
            cluster_centroids[best_clust] = new_centroid / norm if norm > 0 else new_centroid
        else:
            # Start a new cluster
            cluster_members.append([i])
            cluster_centroids.append(vec.copy())

    # ── Refinement pass (pass 2) ───────────────────────────────────────────────
    # Recompute centroids from scratch (removes incremental-mean drift), then
    # reassign every item to the nearest centroid.  Items whose best centroid
    # similarity is below the threshold remain singletons instead of being
    # forced into an existing cluster.  One pass is enough for stability in
    # practice (academic text clusters are rarely ambiguous at 0.70).

    def _recompute_centroids(members: list[list[int]]) -> list[np.ndarray]:
        centroids = []
        for idxs in members:
            raw = embeddings[idxs].mean(axis=0)
            norm = np.linalg.norm(raw)
            centroids.append(raw / norm if norm > 0 else raw)
        return centroids

    cluster_centroids = _recompute_centroids(cluster_members)
    centroid_matrix = np.stack(cluster_centroids)   # (K, D)

    # Cosine sims for all items against all centroids in one matrix multiply
    sims_matrix = embeddings @ centroid_matrix.T     # (N, K)

    new_members: list[list[int]] = [[] for _ in cluster_members]
    for i in range(n):
        best_ci  = int(np.argmax(sims_matrix[i]))
        best_sim = float(sims_matrix[i, best_ci])
        if best_sim >= threshold:
            new_members[best_ci].append(i)
        else:
            # No cluster is close enough — keep as its own singleton
            new_members.append([i])

    # Drop empty clusters that lost all their members to better fits
    cluster_members = [m for m in new_members if m]
    return cluster_members


def average_linkage(sim: np.ndarray, threshold: float) -> list[list[int]]:
    """
    Average-linkage agglomerative clustering on a cosine-similarity matrix.

    Repeatedly merges the two clusters with the highest mean pairwise similarity
    while that mean is above `threshold` (equivalent to scikit-learn's
    AgglomerativeClustering(metric="cosine", linkage="average",
    distance_threshold=1 - threshold)). Lance–Williams updates keep each merge O(k).
    """
    n = len(sim)
    if n == 0:
        return []
    clusters = [[i] for i in range(n)]
    sizes = np.ones(n)
    M = sim.astype(np.float64).copy()
    np.fill_diagonal(M, -np.inf)
    alive = np.ones(n, dtype=bool)
    while alive.sum() > 1:
        masked = np.where(alive[:, None] & alive[None, :], M, -np.inf)
        a, b = np.unravel_index(np.argmax(masked), masked.shape)
        if masked[a, b] <= threshold:
            break
        a, b = min(a, b), max(a, b)
        merged = (sizes[a] * M[a] + sizes[b] * M[b]) / (sizes[a] + sizes[b])
        M[a, :] = merged
        M[:, a] = merged
        M[a, a] = -np.inf
        sizes[a] += sizes[b]
        clusters[a] += clusters[b]
        alive[b] = False
        M[b, :] = -np.inf
        M[:, b] = -np.inf
    return [sorted(clusters[i]) for i in range(n) if alive[i]]


# ── Main deduplication ─────────────────────────────────────────────────────────

def deduplicate(
    sub_questions: list[dict],
    threshold: float = SIMILARITY_THRESHOLD,
    encode=None,
    method: str = "average",
) -> list[dict]:
    """
    Group sub_questions into canonical question clusters.

    Args:
        sub_questions: list of sub_question dicts from db.get_sub_questions_for_module()
                       Each dict must have: id, text, marks, year, paper_id, q_no, sub_q
        threshold: cosine similarity above which two questions are "the same"
        encode: texts -> L2-normalised embeddings; defaults to embedder.encode
                (the evaluation swaps in other models here)
        method: "average" (average-linkage agglomerative, default) or "greedy"
                (the original two-pass centroid clustering)

    Returns:
        List of canonical dicts:
          {
            representative_text,  # most recent / longest clean phrasing
            avg_marks,
            appearances: [{sub_question_id, paper_id, year, q_no, sub_q, marks}]
          }
    """
    valid = [
        q for q in sub_questions
        if len(q["text"].strip()) >= MIN_TEXT_LENGTH
    ]
    if not valid:
        return []

    # Clean texts for embedding — keep originals for storage
    clean_texts = [_clean_for_embed(q["text"]) for q in valid]

    # Drop entries that became empty after cleaning
    pairs = [(q, ct) for q, ct in zip(valid, clean_texts) if len(ct) >= MIN_TEXT_LENGTH]
    if not pairs:
        return []
    valid, clean_texts = zip(*pairs)
    valid = list(valid)
    clean_texts = list(clean_texts)

    embeddings = (encode or embedder.encode)(clean_texts)   # shape (N, D), L2-normalised

    if method == "greedy":
        cluster_members = _greedy_clusters(embeddings, threshold)
    else:
        cluster_members = average_linkage(embeddings @ embeddings.T, threshold)

    # ── Build canonical records ────────────────────────────────────────────────
    canonicals: list[dict] = []

    for indices in cluster_members:
        cluster_sqs = [valid[i] for i in indices]

        # Representative = most recent AND longest phrasing
        # (recent = higher year; tie-break by text length)
        cluster_sqs_sorted = sorted(
            cluster_sqs,
            key=lambda q: (q.get("year") or 0, len(q["text"])),
            reverse=True,
        )
        representative_text = cluster_sqs_sorted[0]["text"]

        marks_values = [q["marks"] for q in cluster_sqs if q.get("marks")]
        avg_marks = float(np.mean(marks_values)) if marks_values else 0.0

        appearances = [
            {
                "sub_question_id": q["id"],
                "paper_id":        q["paper_id"],
                "year":            q.get("year"),
                "q_no":            q["q_no"],
                "sub_q":           q["sub_q"],
                "marks":           q.get("marks"),
            }
            for q in cluster_sqs
        ]

        canonicals.append({
            "representative_text": representative_text,
            "avg_marks":  avg_marks,
            "appearances": appearances,
        })

    return canonicals
