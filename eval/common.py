"""Paths, data loading and small helpers shared by every experiment."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_DATA = ROOT / "data" / "eval"              # gitignored: page images, ground truth, cached system output
PAPERS_INDEX = EVAL_DATA / "papers.json"
GT_PAPERS = EVAL_DATA / "ground_truth" / "papers"
GT_GROUPS = EVAL_DATA / "ground_truth" / "groups"
SYSTEM_DIR = EVAL_DATA / "system"
RESULTS = ROOT / "eval" / "results"             # committed: aggregate numbers + figures only
FIGURES = RESULTS / "figures"
RAW = ROOT / "data" / "raw"

# Added on 2026-10-06, after the parser rules were frozen, so they test the frozen extraction.
# BCS304 is a whole new subject; it was later used to select the deployed grouping model, so only
# the earlier pick (mxbai-embed-xsmall, tau=0.725) is a prospective grouping test on it. The BCS501
# additions are new scans (two of them second scans of development exams) and two new exams.
HELD_OUT_SUBJECTS = {"BCS304"}
_BCS501 = "VTU_Question_Paper_of_BCS501_Software_Engineering_and_Project_Management_"
HELD_OUT_PAPERS = {
    "BCS304",
    "VTU_Question_Paper_of_BCS304_Data_Structures_and_Applications_Jan_Fab_2024_1",
    "VTU_Question_Paper_of_BCS304_Data_Structures_and_Applications_Dec_2024_Jan_2025_0001_1",
    _BCS501 + "June_July_2025_0001_1_1",      # make-up exam, two pages on one A3 sheet
    _BCS501 + "June_July_2025_0001",          # second scan of JuneJuly_2025
    _BCS501 + "Dec_2024_Jan_2025",            # second scan of BCS501_regular_paper
    _BCS501 + "Dec_2025_Jan_2026_0001_2",     # the newest exam
}

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def paper_id(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", Path(filename).stem).strip("_")


def paper_index() -> list[dict]:
    """Every distinct PDF in data/raw (refreshed, so newly added papers are picked up).

    Byte-identical copies ("x (1).pdf") are skipped, keeping the shortest name, as uploads
    are deduplicated by hash in production.
    """
    known = {p["file"]: p for p in json.loads(PAPERS_INDEX.read_text("utf-8"))} if PAPERS_INDEX.exists() else {}
    first_seen = {name: i for i, name in enumerate(known)}
    by_hash = {}
    for pdf in sorted(RAW.glob("*.pdf"), key=lambda p: (len(p.name), p.name)):
        by_hash.setdefault(hashlib.sha256(pdf.read_bytes()).hexdigest(), pdf)
    # A re-saved copy has different bytes but the same text layer; keep the earliest-known file
    by_text = {}
    for pdf in sorted(by_hash.values(), key=lambda p: (first_seen.get(p.name, len(first_seen)), len(p.name), p.name)):
        text = _text_layer(pdf)
        by_text.setdefault(hashlib.sha256(text.encode()).hexdigest() if len(text) > 200 else pdf.name, pdf)
    out = []
    for pdf in sorted(by_text.values()):
        out.append(known.get(pdf.name) or {"file": pdf.name, "id": paper_id(pdf.name), "pages": []})
    return out


def _text_layer(pdf: Path) -> str:
    import pymupdf
    with pymupdf.open(pdf) as doc:
        return " ".join("".join(page.get_text() for page in doc).split())


def load_gt_papers() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(GT_PAPERS.glob("*.json"))}


def load_gt_groups() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(GT_GROUPS.glob("*.json"))}


def load_system() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(SYSTEM_DIR.glob("*.json"))}


def qref(pid: str, q: dict) -> str:
    return f"{pid}:Q{q['q_no']}{q['sub_q']}"


def session_order(paper: dict) -> tuple:
    """Sort key: model papers first (they're published before exams), then exams by date."""
    if paper.get("paper_type") == "model" or not paper.get("exam_year"):
        return (0, paper.get("exam_year") or 0, 0)
    month = paper.get("exam_month")
    # A make-up exam is sat a few weeks after the regular one of the same session
    return (1, paper["exam_year"], (MONTHS.index(month) + 1 if month in MONTHS else 0) + 0.5 * bool(paper.get("makeup")))


def session_label(paper: dict) -> str:
    if paper.get("paper_type") == "model":
        return f"Model{' ' + str(paper['exam_year']) if paper.get('exam_year') else ''}"
    label = f"{(paper.get('exam_month') or '?')[:3]} {paper.get('exam_year') or '?'}"
    return label + " make-up" if paper.get("makeup") else label


def norm_text(t: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).split())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
