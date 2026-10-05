"""Run the production extractor (the same sandboxed subprocess uploads use) over every paper."""

import time

from eval.common import RAW, SYSTEM_DIR, paper_index, write_json


def run(force: bool = False) -> dict:
    from server.sandbox import run_extraction

    out = {}
    for p in paper_index():
        target = SYSTEM_DIR / f"{p['id']}.json"
        if target.exists() and not force:
            continue
        t0 = time.perf_counter()
        r = run_extraction(str(RAW / p["file"]), max_pages=10, timeout_s=900)
        r["seconds"] = time.perf_counter() - t0
        r["paper_id"] = p["id"]
        r["file"] = p["file"]
        write_json(target, r)
        out[p["id"]] = r
        print(f"  extracted {p['id']:<40} {r['pdf_type']:<8} {len(r['sub_questions']):>3} q  {r['seconds']:.1f}s")
    return out
