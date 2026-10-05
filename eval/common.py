"""Paths, data loading and small helpers shared by every experiment."""

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

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def paper_id(filename: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", Path(filename).stem).strip("_")


def paper_index() -> list[dict]:
    """Every PDF in data/raw (refreshed, so newly added papers are picked up)."""
    known = {p["file"]: p for p in json.loads(PAPERS_INDEX.read_text("utf-8"))} if PAPERS_INDEX.exists() else {}
    out = []
    for pdf in sorted(RAW.glob("*.pdf")):
        out.append(known.get(pdf.name) or {"file": pdf.name, "id": paper_id(pdf.name), "pages": []})
    return out


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
    return (1, paper["exam_year"], MONTHS.index(month) + 1 if month in MONTHS else 0)


def session_label(paper: dict) -> str:
    if paper.get("paper_type") == "model":
        return f"Model{' ' + str(paper['exam_year']) if paper.get('exam_year') else ''}"
    return f"{(paper.get('exam_month') or '?')[:3]} {paper.get('exam_year') or '?'}"


def norm_text(t: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).split())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
