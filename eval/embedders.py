"""
Candidate sentence-embedding models, all run the same way as production:
ONNX Runtime + tokenizers, pooling as each model's sentence-transformers config says,
L2-normalised so cosine similarity is a dot product.
"""

import time
from functools import lru_cache
from pathlib import Path

import numpy as np

# name → (Hugging Face repo, pooling, text prefix)
MODELS = {
    "paraphrase-MiniLM-L6-v2":  ("sentence-transformers/paraphrase-MiniLM-L6-v2", "mean", ""),   # previous production
    "all-MiniLM-L6-v2":         ("sentence-transformers/all-MiniLM-L6-v2", "mean", ""),
    "paraphrase-mpnet-base-v2": ("sentence-transformers/paraphrase-mpnet-base-v2", "mean", ""),
    "all-mpnet-base-v2":        ("sentence-transformers/all-mpnet-base-v2", "mean", ""),
    "bge-small-en-v1.5":        ("BAAI/bge-small-en-v1.5", "cls", ""),
    "gte-small":                ("thenlper/gte-small", "mean", ""),
    "e5-small-v2":              ("intfloat/e5-small-v2", "mean", "query: "),
    "arctic-embed-xs":          ("Snowflake/snowflake-arctic-embed-xs", "cls", ""),
    "mxbai-embed-xsmall-v1":    ("mixedbread-ai/mxbai-embed-xsmall-v1", "mean", ""),
}
PRODUCTION = "paraphrase-MiniLM-L6-v2"   # deployed until the evaluation below
DEPLOYED = "mxbai-embed-xsmall-v1"        # deployed now (average linkage, τ = 0.725)


class OnnxEncoder:
    def __init__(self, name: str, max_tokens: int = 128):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        self.name = name
        self.repo, self.pooling, self.prefix = MODELS[name]
        try:
            model_path = hf_hub_download(self.repo, "onnx/model.onnx")
        except Exception:
            model_path = hf_hub_download(self.repo, "model.onnx")
        self.size_mb = Path(model_path).stat().st_size / 1e6
        tok = Tokenizer.from_file(hf_hub_download(self.repo, "tokenizer.json"))
        tok.enable_truncation(max_length=max_tokens)
        tok.enable_padding()
        self.tokenizer = tok
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1      # same as production; makes timings comparable
        self.session = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self._cache: dict[str, np.ndarray] = {}
        self.seconds = 0.0

    def _run(self, texts: list[str]) -> np.ndarray:
        enc = self.tokenizer.encode_batch([self.prefix + t for t in texts])
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = self.session.run(None, feeds)[0]
        if self.pooling == "cls":
            pooled = hidden[:, 0]
        else:
            m = mask[:, :, None].astype(np.float32)
            pooled = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
        return pooled / np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        """Memoised per text, so threshold sweeps don't re-embed."""
        todo = [t for t in dict.fromkeys(texts) if t not in self._cache]
        t0 = time.perf_counter()
        for i in range(0, len(todo), batch_size):
            chunk = todo[i:i + batch_size]
            for t, v in zip(chunk, self._run(chunk)):
                self._cache[t] = v.astype(np.float32)
        self.seconds += time.perf_counter() - t0
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        return np.stack([self._cache[t] for t in texts])


@lru_cache(maxsize=None)
def get(name: str) -> OnnxEncoder:
    return OnnxEncoder(name)
