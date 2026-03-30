"""
detector.py — PDF format detection and table extraction.

Strategy:
  1. Try pdfplumber native table extraction (works for digital PDFs).
  2. If no tables found or too little text → treat as scanned.
  3. For scanned PDFs: render page at 300 DPI, detect table grid with
     OpenCV HoughLines, crop each cell individually, OCR with Tesseract.
     Cell-level OCR is dramatically more accurate than full-page OCR.
"""

import re
from pathlib import Path
from typing import Optional

import numpy as np
import pdfplumber
import pytesseract
import fitz  # PyMuPDF — fast page-to-image
from PIL import Image


# ── Constants ─────────────────────────────────────────────────────────────────

DPI = 300
MIN_NATIVE_TEXT_PER_PAGE = 100   # chars — below this, treat as scanned
MIN_TABLE_COLS = 3               # a valid question table has at least 3 cols


# ── Public API ────────────────────────────────────────────────────────────────

def detect_and_extract(pdf_path: str) -> tuple[str, list[list[str]]]:
    """
    Main entry point.
    Returns (pdf_type, raw_table_rows) where pdf_type is 'native' or 'scanned'
    and raw_table_rows is a flat list of rows from ALL pages combined.
    Each row is a list of cell strings.
    """
    pdf_path = str(pdf_path)

    # Try native first
    rows, ok = _extract_native(pdf_path)
    if ok:
        return "native", rows

    # Fall back to scanned
    rows = _extract_scanned(pdf_path)
    return "scanned", rows


# ── Native extraction ──────────────────────────────────────────────────────────

def _extract_native(pdf_path: str) -> tuple[list[list[str]], bool]:
    """
    Use pdfplumber to extract tables from a native (text-based) PDF.
    Returns (rows, success). success=False if the PDF appears to be scanned.
    """
    all_rows: list[list[str]] = []
    total_text = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            total_text += len(text)

            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row:
                        cleaned = [str(c).strip() if c else "" for c in row]
                        if any(cleaned):
                            all_rows.append(cleaned)

    avg_text = total_text / max(1, 1)
    if total_text < MIN_NATIVE_TEXT_PER_PAGE or not all_rows:
        return [], False

    return all_rows, True


# ── Scanned extraction ─────────────────────────────────────────────────────────

def _extract_scanned(pdf_path: str) -> list[list[str]]:
    """
    Render each page at 300 DPI and run full-page Tesseract (PSM 4).

    For clean VTU table scans Tesseract reliably detects table borders as
    pipe characters '|', giving output like:
        Q.3 | a. | Define Redundancy... | 08 | L2 | CO2

    We split on '|' to reconstruct cell arrays — no OpenCV grid detection
    needed, avoiding the misalignment errors that cell-level cropping caused.
    """
    doc = fitz.open(pdf_path)
    all_rows: list[list[str]] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        gray = _page_to_array(page, DPI)
        rows = _ocr_page_to_rows(gray)
        all_rows.extend(rows)

    doc.close()
    return all_rows


def _page_to_array(page: fitz.Page, dpi: int) -> np.ndarray:
    """Render a PDF page to a grayscale numpy uint8 array."""
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w)
    return arr


def _ocr_page_to_rows(gray: np.ndarray) -> list[list[str]]:
    """
    Use Tesseract image_to_data (PSM 6) to get word-level bounding boxes,
    then reconstruct the VTU table using FIXED proportional column boundaries.

    VTU CBCS papers have a consistent 6-column table layout:
      Q.No (5-12%) | Sub (12-17%) | Text (17-74%) | M (74-83%) | L (83-89%) | C (89-98%)

    Using fixed proportions avoids the column-detection failure that occurs
    when page headers or footers skew the gap-based auto-detection.
    """
    pil = Image.fromarray(gray)
    page_w = gray.shape[1]

    # Fixed column boundaries as fraction of page width (VTU CBCS standard layout)
    # Tuned from actual paper measurements at 300 DPI (2550px wide, Letter/A4)
    col_splits = [
        0,                     # left edge
        int(page_w * 0.13),   # Q.No | Sub boundary
        int(page_w * 0.17),   # Sub | Text boundary
        int(page_w * 0.74),   # Text | M boundary
        int(page_w * 0.83),   # M | L boundary
        int(page_w * 0.89),   # L | C boundary
        page_w,               # right edge
    ]
    # col_splits defines 6 buckets: [0-1], [1-2], [2-3], [3-4], [4-5], [5-6]
    n_cols = len(col_splits) - 1

    data = pytesseract.image_to_data(
        pil,
        output_type=pytesseract.Output.DICT,
        config="--psm 6",
    )

    # Collect valid words with positions
    words: list[dict] = []
    for i, word in enumerate(data["text"]):
        conf = data["conf"][i]
        if str(conf) in ("-1", "") or not word.strip():
            continue
        cx = data["left"][i] + data["width"][i] // 2
        cy = data["top"][i] + data["height"][i] // 2
        words.append({"text": word.strip(), "cx": cx, "cy": cy})

    if not words:
        return []

    # Group words into horizontal bands by vertical centre
    ROW_TOLERANCE = 14   # pixels at 300 DPI
    words.sort(key=lambda w: w["cy"])

    bands: list[list[dict]] = []
    current_band: list[dict] = [words[0]]
    band_cy = words[0]["cy"]

    for w in words[1:]:
        if abs(w["cy"] - band_cy) <= ROW_TOLERANCE:
            current_band.append(w)
        else:
            bands.append(current_band)
            current_band = [w]
            band_cy = w["cy"]
    bands.append(current_band)

    # Assign each word to its column bucket and build rows
    rows: list[list[str]] = []
    for band in bands:
        # Sort words left-to-right so word order within a cell is correct
        band.sort(key=lambda w: w["cx"])
        buckets: list[list[str]] = [[] for _ in range(n_cols)]
        for w in band:
            cx = w["cx"]
            col_idx = n_cols - 1
            for ci in range(n_cols):
                if col_splits[ci] <= cx < col_splits[ci + 1]:
                    col_idx = ci
                    break
            buckets[col_idx].append(w["text"])

        cells = [" ".join(b) for b in buckets]
        # Strip trailing empty cells
        while cells and not cells[-1].strip():
            cells.pop()
        if any(c.strip() for c in cells):
            rows.append(cells)

    return rows


# ── Metadata extraction from filename ─────────────────────────────────────────

VTU_SUBJECT_MAP = {
    "BCS501": "Software Engineering",
    "BCS502": "Computer Networks",
    "BCS503": "Theory of Computation",
    "BCS504": "Design and Analysis of Algorithms",
    "BCS505": "Database Management Systems",
    "BCS506": "Operating Systems",
    "BCS507": "Computer Organization",
    "BCS515D": "Distributed Systems",
    "BCS516D": "Cloud Computing",
    "BCS517D": "Machine Learning",
    "BCS518D": "Artificial Intelligence",
    "BCS519D": "Data Science",
    "BCS521D": "Internet of Things",
    "BCS522D": "Blockchain Technology",
}

MONTH_MAP = {
    "jan": "January", "feb": "February", "mar": "March", "apr": "April",
    "may": "May", "jun": "June", "jul": "July", "aug": "August",
    "sep": "September", "oct": "October", "nov": "November", "dec": "December",
    "june": "June", "july": "July",
}


def parse_content_metadata(rows: list[list[str]]) -> dict:
    """
    Extract subject_code, subject_name, month, year from the extracted table rows.

    VTU papers always start with a standard header block:
      Row N:   "Fifth Semester B.E./B.Tech. Degree Examination, Dec.2024/Jan.2025"
      Row N+1: "Computer Networks"   (or subject name)

    This is the fallback when the filename carries no useful metadata.
    """
    meta: dict = {"subject_code": None, "subject_name": None, "month": None, "year": None}

    # Reverse map: subject name → code (case-insensitive partial match)
    name_to_code = {v.lower(): k for k, v in VTU_SUBJECT_MAP.items()}

    found_exam_line = False

    for row in rows[:15]:
        text = " ".join(c for c in row if c).strip()
        if not text:
            continue

        # ── Date / exam line ──────────────────────────────────────────────────
        if "examination" in text.lower() or "degree exam" in text.lower():
            found_exam_line = True
            # Year: take the maximum 4-digit year in the line
            years = re.findall(r"\b(20\d{2}|19\d{2})\b", text)
            if years and not meta["year"]:
                meta["year"] = max(int(y) for y in years)
            # Month: look for month abbreviations (Dec, Jan, June, July …)
            if not meta["month"]:
                for abbr, full in MONTH_MAP.items():
                    if re.search(r"\b" + abbr + r"\b", text, re.IGNORECASE):
                        meta["month"] = full
                        break
            continue

        # ── Subject name line — short line after the exam header ──────────────
        # Heuristic: 3–60 chars, no digits, appears right after the exam line
        if found_exam_line and not meta["subject_name"]:
            clean = text.strip()
            if 3 < len(clean) < 65 and not re.search(r"\d", clean):
                # Skip obvious non-subject lines
                skip_words = {"time", "note", "max", "marks", "answer", "module",
                              "hours", "hrs", "bloom", "course", "outcome"}
                if not any(w in clean.lower() for w in skip_words):
                    meta["subject_name"] = clean
                    # Try to match against known subjects
                    for name_lower, code in name_to_code.items():
                        if name_lower in clean.lower() or clean.lower() in name_lower:
                            meta["subject_code"] = code
                            break

        # ── Inline subject code (e.g. "BCS502" anywhere in header rows) ───────
        if not meta["subject_code"]:
            code_match = re.search(r"\b(BCS\d{3}[A-Z]?)\b", text, re.IGNORECASE)
            if code_match:
                code = code_match.group(1).upper()
                meta["subject_code"] = code
                meta["subject_name"] = meta["subject_name"] or VTU_SUBJECT_MAP.get(code, code)

    return meta


def parse_filename_metadata(filename: str) -> dict:
    """
    Extract subject_code, subject_name, month, year from VTU filename.
    Examples:
      'JAN 2025 BCS502.pdf'               → {code: BCS502, name: Computer Networks, month: January, year: 2025}
      'july 2025 BCS502.pdf'              → {code: BCS502, name: Computer Networks, month: July, year: 2025}
      'BCS503 mqp 2022-2023.pdf'          → {code: BCS503, name: TOC, month: None, year: 2023}
    """
    stem = Path(filename).stem
    text = stem.replace("_", " ").replace("-", " ")

    # Subject code
    code_match = re.search(r"\b(BCS\d{3}[A-Z]?)\b", stem, re.IGNORECASE)
    subject_code = code_match.group(1).upper() if code_match else "UNKNOWN"
    subject_name = VTU_SUBJECT_MAP.get(subject_code, subject_code)

    # Year — take the latest 4-digit year found
    years = re.findall(r"\b(20\d{2}|19\d{2})\b", text)
    year = max(int(y) for y in years) if years else None
    if not year:
        two_digit = re.search(r"\b([2-9]\d)\b", text)
        if two_digit:
            yr = int(two_digit.group(1))
            if 20 <= yr <= 50:
                year = 2000 + yr

    # Month
    month = None
    for abbr, full in MONTH_MAP.items():
        if re.search(r"\b" + abbr + r"\b", text, re.IGNORECASE):
            month = full
            break

    return {
        "subject_code": subject_code,
        "subject_name": subject_name,
        "month": month,
        "year": year,
    }
