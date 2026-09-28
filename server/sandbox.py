"""
sandbox.py — read an untrusted PDF in a separate, locked-down process.

PDF parsers and OCR are the part of the system a malicious file would attack
(parser bugs, decompression bombs, huge page images). So all of it runs in a
child process that:
  - gets a scrubbed environment (no database URL, no API keys),
  - has a wall-clock timeout, and on Linux also CPU/memory/file-size limits,
  - is thrown away after one file — a crash or hang can't affect the server.

The child prints one JSON object on stdout; the parent only ever trusts that.

Run as:  python -m server.sandbox <pdf_path> <max_pages>
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MAX_PAGE_POINTS = 2000        # ~70 cm — real exam pages are 595×842 (A4)
MAX_IMAGE_PIXELS = 40_000_000 # PIL decompression-bomb guard (A4 @ 300 DPI ≈ 8.7M)


class ExtractionError(Exception):
    """The file was refused or couldn't be read. `reason` is safe to show the uploader."""

    def __init__(self, reason: str, rejected: bool = True):
        super().__init__(reason)
        self.reason = reason
        self.rejected = rejected   # False = our fault (timeout/crash), worth a retry by a moderator


# ── Parent side ────────────────────────────────────────────────────────────────

def _limit_resources(cpu_seconds: int):
    def apply():   # runs in the child just before exec (POSIX only)
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024 * 1024,) * 2)
        os.setsid()
    return apply


def _child_env() -> dict:
    keep = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE",
            "TESSDATA_PREFIX", "LANG", "LC_ALL")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_extraction(pdf_path: str, max_pages: int, timeout_s: int) -> dict:
    """Extract questions from `pdf_path` in a sandboxed child process."""
    kwargs = {}
    if os.name == "posix":
        kwargs["preexec_fn"] = _limit_resources(timeout_s)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "server.sandbox", str(pdf_path), str(max_pages)],
            cwd=ROOT, env=_child_env(), capture_output=True, timeout=timeout_s, **kwargs,
        )
    except subprocess.TimeoutExpired:
        raise ExtractionError("Reading this file took too long.", rejected=False)

    try:
        result = json.loads(proc.stdout.decode("utf-8", "replace").strip().splitlines()[-1])
    except Exception:
        raise ExtractionError("This file could not be read as a PDF.", rejected=proc.returncode != 0)
    if not result.get("ok"):
        raise ExtractionError(result.get("reason") or "This file could not be read.")
    return result


# ── Child side ─────────────────────────────────────────────────────────────────

def _child(pdf_path: str, max_pages: int) -> dict:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

    import pymupdf
    try:
        doc = pymupdf.open(pdf_path)
    except Exception:
        return {"ok": False, "reason": "This file is not a valid PDF."}
    with doc:
        if doc.needs_pass or doc.is_encrypted:
            return {"ok": False, "reason": "Password-protected PDFs can't be read."}
        pages = doc.page_count
        if pages == 0:
            return {"ok": False, "reason": "This PDF has no pages."}
        if pages > max_pages:
            return {"ok": False, "reason": f"This PDF has {pages} pages — a question paper has at most {max_pages}."}
        for page in doc:
            if page.rect.width > MAX_PAGE_POINTS or page.rect.height > MAX_PAGE_POINTS:
                return {"ok": False, "reason": "This PDF has oversized pages and doesn't look like a question paper."}

    from modules import detector, parser
    pdf_type, rows = detector.detect_and_extract(pdf_path)
    sub_questions = parser.parse_rows(rows)
    return {
        "ok": True,
        "pdf_type": pdf_type,
        "page_count": pages,
        "row_count": len(rows),
        # Native PDFs keep their header outside the question table — read it too
        "content_meta": detector.parse_content_metadata(
            (detector.header_rows(pdf_path) if pdf_type == "native" else []) + rows),
        "sub_questions": sub_questions,
    }


if __name__ == "__main__":
    import contextlib
    import io
    # Libraries print progress to stdout — keep stdout for our single JSON line.
    noise = io.StringIO()
    try:
        with contextlib.redirect_stdout(noise):
            out = _child(sys.argv[1], int(sys.argv[2]))
    except Exception as e:  # never leak a traceback to the uploader
        out = {"ok": False, "reason": "This file could not be read.", "error": type(e).__name__}
    sys.stdout.write(json.dumps(out) + "\n")
