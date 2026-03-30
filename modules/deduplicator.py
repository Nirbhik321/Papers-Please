"""
deduplicator.py — Module-level semantic deduplication.

Groups sub_questions from the same (subject, module) across ALL papers
into canonical questions using Sentence-BERT + cosine similarity.

Key rule: position (q_no, sub_q) is IRRELEVANT for identity.
  Paper A: Module 2, Q.3a → "Explain CRC encoder"
  Paper B: Module 2, Q.4b → "Define CRC. Explain CRC encoder operation"
  → Same canonical question (similarity > threshold)

Algorithm: centroid-based greedy clustering.
  Each new question is compared to the CENTROID (mean embedding) of each
  existing cluster, not just the first member.  This correctly merges
  paraphrases even when the seed and candidate are not directly close.

Threshold: 0.70 — tuned for academic paraphrase similarity on MiniLM-L6.
  0.80+ is too strict (misses "explain X" vs "describe X with diagram")
  0.60- is too loose (may merge different topics in the same module)
"""

import re
import numpy as np
from modules import embedder


SIMILARITY_THRESHOLD = 0.70   # lower than before — catches real paraphrases
MIN_TEXT_LENGTH = 12           # ignore garbage OCR fragments


# ── OCR noise cleaner ──────────────────────────────────────────────────────────

_LEADING_JUNK = re.compile(
    r"^[\s_\-|.]*"               # leading underscores, pipes, dashes
    r"(?:[a-c]\.?\s*)?"          # sub-question label "a." "b." etc.
    r"(?:Q\.?\s*\d{1,2}\.?\s*)?" # question number "Q.3" etc.
    r"(?:[a-c]\.?\s*)?"          # second sub-label (Q.3a.)
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


# ── Main deduplication ─────────────────────────────────────────────────────────

def deduplicate(
    sub_questions: list[dict],
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[dict]:
    """
    Group sub_questions into canonical question clusters.

    Args:
        sub_questions: list of sub_question dicts from db.get_sub_questions_for_module()
                       Each dict must have: id, text, marks, year, paper_id, q_no, sub_q
        threshold: cosine similarity above which two questions are "the same"

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

    embeddings = embedder.encode(clean_texts)   # shape (N, 384), L2-normalised

    # ── Centroid-based greedy clustering ──────────────────────────────────────
    # For each new question, compare against the centroid of every existing
    # cluster.  Assign to the most similar cluster if sim >= threshold,
    # otherwise start a new cluster.
    #
    # Centroid is kept as the running mean of member embeddings (no re-encode).

    n = len(valid)
    cluster_members:   list[list[int]]    = []   # indices into `valid`
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
