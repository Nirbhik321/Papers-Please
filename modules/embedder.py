"""
embedder.py — F09 F10
Sentence-BERT encoding + UMAP reduction.
Caches all numpy arrays to disk so re-runs are instant.
"""

from pathlib import Path

import numpy as np
from tqdm import tqdm


def _cache_path(cache_dir: str, name: str) -> Path:
    return Path(cache_dir) / f"{name}.npy"


def _load_cache(cache_dir: str, name: str) -> np.ndarray | None:
    p = _cache_path(cache_dir, name)
    if p.exists():
        return np.load(str(p), allow_pickle=False)
    return None


def _save_cache(cache_dir: str, name: str, array: np.ndarray) -> None:
    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    np.save(str(_cache_path(cache_dir, name)), array)


def encode_questions(
    texts: list[str],
    question_ids: list[int],
    model_name: str = "all-mpnet-base-v2",
    batch_size: int = 64,
    cache_dir: str = "data/embeddings",
    force: bool = False,
) -> np.ndarray:
    """
    F09 — Encode questions with Sentence-BERT.
    Returns float32 array of shape (n_questions, 768).
    Loads from cache unless force=True.
    """
    if not force:
        cached = _load_cache(cache_dir, "vectors_768d")
        cached_ids = _load_cache(cache_dir, "question_ids")
        if cached is not None and cached_ids is not None:
            if len(cached) == len(texts):
                print(f"  Loaded {len(cached)} embeddings from cache")
                return cached

    print(f"  Encoding {len(texts)} questions with {model_name}...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name)

    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=False,
    )
    embeddings = embeddings.astype(np.float32)

    _save_cache(cache_dir, "vectors_768d", embeddings)
    _save_cache(cache_dir, "question_ids", np.array(question_ids, dtype=np.int64))
    print(f"  Saved embeddings to {cache_dir}/")
    return embeddings


def reduce_umap(
    embeddings: np.ndarray,
    n_components: int,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    cache_dir: str = "data/embeddings",
    cache_name: str | None = None,
    force: bool = False,
    random_state: int = 42,
) -> np.ndarray:
    """
    F10 — UMAP dimensionality reduction.
    cache_name: if given, saves/loads from cache.
    """
    if cache_name and not force:
        cached = _load_cache(cache_dir, cache_name)
        if cached is not None and len(cached) == len(embeddings):
            print(f"  Loaded UMAP {n_components}d from cache")
            return cached

    print(f"  Running UMAP → {n_components} dimensions...")
    import umap
    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        random_state=random_state,
        verbose=False,
    )
    reduced = reducer.fit_transform(embeddings).astype(np.float32)

    if cache_name:
        _save_cache(cache_dir, cache_name, reduced)
    return reduced


def load_question_ids(cache_dir: str) -> np.ndarray | None:
    return _load_cache(cache_dir, "question_ids")