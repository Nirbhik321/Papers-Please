"""
embedder.py — Sentence-BERT encoding for semantic similarity.

Uses paraphrase-MiniLM-L6-v2 (~90 MB, CPU-only, no GPU needed).
This model is explicitly trained on paraphrase pairs, making it far better
than all-MiniLM-L6-v2 at detecting "Explain X" ≈ "Describe the working of X"
which is the dominant pattern in exam question deduplication.

Model is loaded once and cached for the process lifetime.
"""

import numpy as np
from sentence_transformers import SentenceTransformer


_MODEL_NAME = "paraphrase-MiniLM-L6-v2"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"  Loading Sentence-BERT ({_MODEL_NAME})...")
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def encode(texts: list[str], batch_size: int = 64) -> np.ndarray:
    """
    Encode a list of strings into L2-normalised embedding vectors.
    Returns ndarray of shape (N, 384).
    """
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    model = _get_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,  # L2 norm → cosine sim = dot product
        show_progress_bar=False,
    )
    return embeddings.astype(np.float32)


def cosine_similarity_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between every pair (a[i], b[j]).
    Since vectors are already L2-normalised, this is just a dot product.
    Returns ndarray of shape (len(a), len(b)).
    """
    return a @ b.T
