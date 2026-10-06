"""
embedder.py — Sentence-BERT encoding for semantic similarity.

Uses sentence-transformers/all-MiniLM-L12-v2 (384-d, ~133 MB), run through ONNX
Runtime instead of PyTorch, so the install is ~100 MB instead of ~2 GB and it fits
in a 512 MB server.

Chosen by evaluation on labelled VTU papers (eval/): of the 20 embedding models
compared, it grouped same-meaning exam questions best among those that fit the
server (average-linkage clustering), and picked the same threshold whichever
subject was held out. Models four to ten times larger did not do better.

The model files are downloaded from the Hugging Face hub on first use (or
baked into the Docker image at build time) and cached for the process lifetime.
"""

import numpy as np

_REPO = "sentence-transformers/all-MiniLM-L12-v2"
_MAX_TOKENS = 128   # exam questions are short; the evaluation used the same limit
_DIM = 384

_session = None
_tokenizer = None


def _load():
    global _session, _tokenizer
    if _session is None:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        print(f"  Loading embedding model ({_REPO}, ONNX)...")
        model_path = hf_hub_download(_REPO, "onnx/model.onnx")
        tok_path = hf_hub_download(_REPO, "tokenizer.json")

        tokenizer = Tokenizer.from_file(tok_path)
        tokenizer.enable_truncation(max_length=_MAX_TOKENS)
        tokenizer.enable_padding()

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1   # small shared CPU — don't oversubscribe
        _session = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
        _tokenizer = tokenizer
    return _session, _tokenizer


def warm_up() -> None:
    """Download/load the model now instead of on the first request."""
    _load()


def encode(texts: list[str], batch_size: int = 32) -> np.ndarray:
    """
    Encode a list of strings into L2-normalised embedding vectors.
    Returns ndarray of shape (N, 384).
    """
    if not texts:
        return np.zeros((0, _DIM), dtype=np.float32)
    session, tokenizer = _load()
    input_names = {i.name for i in session.get_inputs()}

    out: list[np.ndarray] = []
    for start in range(0, len(texts), batch_size):
        batch = tokenizer.encode_batch(texts[start:start + batch_size])
        ids = np.array([e.ids for e in batch], dtype=np.int64)
        mask = np.array([e.attention_mask for e in batch], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in input_names:
            feeds["token_type_ids"] = np.zeros_like(ids)

        hidden = session.run(None, feeds)[0]                    # (B, T, 384)
        # Mean pooling over real tokens (the model's pooling config)
        m = mask[:, :, None].astype(np.float32)
        pooled = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        out.append(pooled / np.clip(norms, 1e-12, None))        # L2 norm → cosine = dot

    return np.vstack(out).astype(np.float32)


def cosine_similarity_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between every pair (a[i], b[j]).
    Since vectors are already L2-normalised, this is just a dot product.
    Returns ndarray of shape (len(a), len(b)).
    """
    return a @ b.T
