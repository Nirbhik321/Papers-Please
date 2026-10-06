"""
Candidate sentence-embedding models, all run the same way as production:
ONNX Runtime + tokenizers, pooling as each model's sentence-transformers config says,
L2-normalised so cosine similarity is a dot product.
"""

import time
from functools import lru_cache
from pathlib import Path

import numpy as np

# name → (Hugging Face repo, pooling, text prefix). Pooling is each model's own
# sentence-transformers 1_Pooling config; prefixes are the ones the model cards ask for.
MODELS = {
    "paraphrase-MiniLM-L6-v2":   ("sentence-transformers/paraphrase-MiniLM-L6-v2", "mean", ""),   # previous production
    "all-MiniLM-L6-v2":          ("sentence-transformers/all-MiniLM-L6-v2", "mean", ""),
    "multi-qa-MiniLM-L6":        ("sentence-transformers/multi-qa-MiniLM-L6-cos-v1", "mean", ""),
    "all-MiniLM-L12-v2":         ("sentence-transformers/all-MiniLM-L12-v2", "mean", ""),
    "all-distilroberta-v1":      ("sentence-transformers/all-distilroberta-v1", "mean", ""),
    "paraphrase-mpnet-base-v2":  ("sentence-transformers/paraphrase-mpnet-base-v2", "mean", ""),
    "all-mpnet-base-v2":         ("sentence-transformers/all-mpnet-base-v2", "mean", ""),
    "bge-small-en-v1.5":         ("BAAI/bge-small-en-v1.5", "cls", ""),
    "bge-base-en-v1.5":          ("BAAI/bge-base-en-v1.5", "cls", ""),
    "bge-large-en-v1.5":         ("BAAI/bge-large-en-v1.5", "cls", ""),
    "gte-small":                 ("thenlper/gte-small", "mean", ""),
    "gte-base":                  ("thenlper/gte-base", "mean", ""),
    "e5-small-v2":               ("intfloat/e5-small-v2", "mean", "query: "),
    "e5-base-v2":                ("intfloat/e5-base-v2", "mean", "query: "),
    "arctic-embed-xs":           ("Snowflake/snowflake-arctic-embed-xs", "cls", ""),
    "arctic-embed-s":            ("Snowflake/snowflake-arctic-embed-s", "cls", ""),
    "arctic-embed-m":            ("Snowflake/snowflake-arctic-embed-m", "cls", ""),
    "nomic-embed-text-v1.5":     ("nomic-ai/nomic-embed-text-v1.5", "mean", "clustering: "),
    "mxbai-embed-xsmall-v1":     ("mixedbread-ai/mxbai-embed-xsmall-v1", "mean", ""),
    "mxbai-embed-large-v1":      ("mixedbread-ai/mxbai-embed-large-v1", "cls", ""),
    # Lexical baselines: no neural model at all
    "tfidf-word":                (None, "tfidf", "word"),
    "tfidf-char":                (None, "tfidf", "char"),
}
LEXICAL = {k for k, v in MODELS.items() if v[1] == "tfidf"}
LEXICAL_CORPUS: list[str] = []     # texts the lexical baselines fit their IDF weights on (set per run)
# Order in which the parallel evaluation starts models: large ones spread out so they don't load together
MODEL_ORDER = ["bge-large-en-v1.5", "tfidf-word", "all-MiniLM-L6-v2", "gte-small", "mxbai-embed-large-v1", "tfidf-char",
               "paraphrase-MiniLM-L6-v2", "mxbai-embed-xsmall-v1", "nomic-embed-text-v1.5", "multi-qa-MiniLM-L6",
               "arctic-embed-xs", "bge-small-en-v1.5", "all-mpnet-base-v2", "e5-small-v2", "all-MiniLM-L12-v2",
               "gte-base", "arctic-embed-s", "paraphrase-mpnet-base-v2", "bge-base-en-v1.5", "all-distilroberta-v1",
               "e5-base-v2", "arctic-embed-m"]


def family(name: str) -> str:
    if name in LEXICAL:
        return "lexical"
    repo = MODELS[name][0]
    return {"sentence-transformers": "sentence-transformers", "BAAI": "bge", "thenlper": "gte", "intfloat": "e5",
            "Snowflake": "arctic", "nomic-ai": "nomic", "mixedbread-ai": "mxbai"}[repo.split("/")[0]]
PRODUCTION = "paraphrase-MiniLM-L6-v2"   # deployed until the evaluation below
DEPLOYED = "all-MiniLM-L12-v2"            # deployed now (average linkage, τ = 0.675)
PREVIOUS_PICK = "mxbai-embed-xsmall-v1"   # picked on the first three subjects (τ = 0.725)


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


class LexicalEncoder:
    """TF-IDF vectors (word unigrams+bigrams, or character 3-5-grams), L2-normalised, so the
    same clustering code runs on them. IDF weights come from the question texts only."""

    # TF-IDF cosines between paraphrases are far lower than embedding cosines
    thresholds = [round(0.05 + 0.025 * i, 4) for i in range(31)]   # 0.05 … 0.80

    def __init__(self, name: str, corpus: list[str]):
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.name = name
        kind = MODELS[name][2]
        self.vec = (TfidfVectorizer(lowercase=True, ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
                    if kind == "word" else
                    TfidfVectorizer(lowercase=True, analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True))
        self.vec.fit(corpus)
        self.size_mb = 0.0
        self.seconds = 0.0

    def encode(self, texts: list[str], batch_size: int = 0) -> np.ndarray:
        t0 = time.perf_counter()
        if not texts:
            return np.zeros((0, 1), dtype=np.float32)
        X = self.vec.transform(texts).toarray().astype(np.float32)
        X /= np.clip(np.linalg.norm(X, axis=1, keepdims=True), 1e-12, None)
        self.seconds += time.perf_counter() - t0
        return X


@lru_cache(maxsize=None)
def get(name: str):
    if name in LEXICAL:
        if not LEXICAL_CORPUS:
            raise ValueError("set embedders.LEXICAL_CORPUS before using a lexical baseline")
        return LexicalEncoder(name, list(LEXICAL_CORPUS))
    return OnnxEncoder(name)
