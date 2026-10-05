"""
Baseline for the ONNX comparison: the same model through sentence-transformers + PyTorch.
Runs in a separate interpreter that has torch installed:
    <python-with-torch> eval/bench_torch.py data/eval/bench_texts.json
Prints one JSON line.
"""

import json
import os
import sys
import time

import psutil

texts = json.load(open(sys.argv[1], encoding="utf-8"))
proc = psutil.Process(os.getpid())
rss0 = proc.memory_info().rss
t_import = time.perf_counter()
import torch  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

torch.set_num_threads(1)   # match the production ONNX session
model = SentenceTransformer(sys.argv[2] if len(sys.argv) > 2 else "paraphrase-MiniLM-L6-v2", device="cpu")
load_s = time.perf_counter() - t_import
rss1 = proc.memory_info().rss
model.encode(texts[:8], normalize_embeddings=True)
t0 = time.perf_counter()
model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
secs = time.perf_counter() - t0
print(json.dumps({
    "texts": len(texts), "seconds": secs, "ms_per_text": 1000 * secs / len(texts),
    "import_and_load_s": load_s, "model_rss_mb": (rss1 - rss0) / 1e6,
    "process_rss_mb": proc.memory_info().rss / 1e6, "torch": torch.__version__,
    "model": sys.argv[2] if len(sys.argv) > 2 else "paraphrase-MiniLM-L6-v2",
}))
