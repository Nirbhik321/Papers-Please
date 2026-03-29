"""
labeller.py — F12
Auto-labels each cluster using spaCy noun chunk extraction.
Picks the most frequent noun phrases across all questions in a cluster.
"""

from collections import Counter


def _extract_noun_chunks(texts: list[str], nlp) -> list[str]:
    """Run spaCy on a list of texts and return all noun chunks."""
    chunks = []
    for doc in nlp.pipe(texts, batch_size=32):
        for chunk in doc.noun_chunks:
            clean = chunk.text.strip().lower()
            # Filter out single very common words and short chunks
            if len(clean) > 3 and clean not in {"the", "this", "that", "which", "what"}:
                chunks.append(clean)
    return chunks


def label_clusters(
    cluster_to_qids: dict[int, list[int]],
    qid_to_text: dict[int, str],
    top_n: int = 3,
) -> dict[int, str]:
    """
    For each cluster, find the most distinctive noun phrases
    and join the top N into a human-readable label.

    Returns dict: {cluster_id: label_string}
    """
    print("  Labelling clusters with spaCy...")
    import spacy

    try:
        # Keep parser enabled — noun_chunks requires the dependency parse
        nlp = spacy.load("en_core_web_sm", disable=["ner"])
    except OSError:
        print("  Warning: en_core_web_sm not found, using simple keyword extraction")
        print("  Fix: python -m spacy download en_core_web_sm")
        return _label_fallback(cluster_to_qids, qid_to_text, top_n)

    labels: dict[int, str] = {}

    for cluster_id, qids in cluster_to_qids.items():
        texts = [qid_to_text[qid] for qid in qids if qid in qid_to_text]
        if not texts:
            labels[cluster_id] = f"Topic {cluster_id}"
            continue

        chunks = _extract_noun_chunks(texts, nlp)
        if not chunks:
            labels[cluster_id] = f"Topic {cluster_id}"
            continue

        # Pick top N most common noun phrases
        counter = Counter(chunks)
        top_phrases = [phrase for phrase, _ in counter.most_common(top_n)]
        label = " · ".join(p.title() for p in top_phrases)
        labels[cluster_id] = label

    return labels


def _label_fallback(
    cluster_to_qids: dict[int, list[int]],
    qid_to_text: dict[int, str],
    top_n: int = 3,
) -> dict[int, str]:
    """
    Simple keyword fallback when spaCy model isn't available.
    Strips stopwords and picks most frequent content words.
    """
    STOPWORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "shall", "can",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "what", "which", "how", "when", "where", "why", "who",
        "explain", "describe", "define", "write", "find", "give",
        "list", "state", "discuss", "derive", "prove", "show",
    }
    labels: dict[int, str] = {}
    for cluster_id, qids in cluster_to_qids.items():
        texts = [qid_to_text[qid] for qid in qids if qid in qid_to_text]
        words: list[str] = []
        for text in texts:
            words.extend(
                w.lower().strip(".,?!()[]")
                for w in text.split()
                if w.lower().strip(".,?!()[]") not in STOPWORDS
                and len(w) > 3
            )
        counter = Counter(words)
        top = [w for w, _ in counter.most_common(top_n)]
        labels[cluster_id] = " · ".join(w.title() for w in top) if top else f"Topic {cluster_id}"
    return labels