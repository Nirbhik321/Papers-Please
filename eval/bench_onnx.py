"""
The production encoder (ONNX Runtime + tokenizers), measured in a fresh interpreter so the
memory figure covers the runtime import and model load and nothing else in the process:
    python -m eval.bench_onnx data/eval/bench_texts.json mxbai-embed-xsmall-v1
Prints one JSON line, with the same fields as eval/bench_torch.py.
"""

import json
import os
import sys
import time

import psutil

texts = json.load(open(sys.argv[1], encoding="utf-8"))
name = sys.argv[2]
proc = psutil.Process(os.getpid())
rss0 = proc.memory_info().rss
t_import = time.perf_counter()
from eval import embedders  # noqa: E402

enc = embedders.OnnxEncoder(name)
load_s = time.perf_counter() - t_import
rss1 = proc.memory_info().rss
enc.encode(texts[:8])
enc._cache.clear()
t0 = time.perf_counter()
enc.encode(texts)
secs = time.perf_counter() - t0
print(json.dumps({
    "texts": len(texts), "seconds": secs, "ms_per_text": 1000 * secs / len(texts),
    "import_and_load_s": load_s, "model_rss_mb": (rss1 - rss0) / 1e6, "model_file_mb": enc.size_mb,
    "process_rss_mb": proc.memory_info().rss / 1e6, "model": name,
}))
