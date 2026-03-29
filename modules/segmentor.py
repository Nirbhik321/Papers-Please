"""
segmentor.py — F05 F06
Detects question boundaries using regex patterns.
Extracts metadata: marks, section, question number.
Returns a list of Question dicts ready for DB insertion.
"""

import re
from pathlib import Path


# ── Regex patterns ────────────────────────────────────────────────────────────

# Question start patterns — covers most Indian university exam paper formats
QUESTION_START = re.compile(
    r"""
    ^\s*                            # optional leading whitespace
    (?:
        Q\.?\s*\d+                  # Q1, Q.1, Q 1
        | Question\s+\d+            # Question 1
        | \d{1,2}\s*[\.\)]         # 1. or 1)
        | \([a-zA-Z]\)              # (a) (b)
        | [a-zA-Z]\s*[\.\)]        # a. b.
        | Part\s+[A-Z]              # Part A
        | Section\s+[A-Z\d]        # Section A, Section 1
        | UNIT\s+[IVX\d]+          # UNIT I, UNIT 1
    )
    [\s\:\-]+                       # separator after number
    """,
    re.VERBOSE | re.IGNORECASE | re.MULTILINE
)

# Marks patterns — [5 marks], (10), [CO2-5], 5M
MARKS_PATTERN = re.compile(
    r"""
    [\[\(]
    \s*(\d{1,3})\s*
    (?:marks?|M|Marks)?
    \s*
    [\]\)]
    |
    \b(\d{1,2})\s*[Mm]\b
    """,
    re.VERBOSE
)

# Section header — standalone lines that are just a heading
SECTION_HEADER = re.compile(
    r"^(Part|Section|UNIT|Module)\s+[A-Z0-9IVX]+\s*$",
    re.IGNORECASE | re.MULTILINE
)


def _extract_marks(text: str) -> int | None:
    """Pull the first marks value found in question text."""
    match = MARKS_PATTERN.search(text)
    if match:
        val = match.group(1) or match.group(2)
        if val:
            return int(val)
    return None


def _clean_text(text: str) -> str:
    """Strip question numbers, marks brackets, excess whitespace."""
    # Remove marks indicators
    text = MARKS_PATTERN.sub("", text)
    # Remove leading question number/label
    text = re.sub(
        r"^[\s]*(?:Q\.?\s*\d+|Question\s+\d+|\d{1,2}\s*[\.\)]|\([a-zA-Z]\)|[a-zA-Z]\s*[\.\)])"
        r"[\s:\-]+",
        "", text, flags=re.IGNORECASE
    )
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _detect_section(line: str, current_section: str) -> str:
    """Return new section name if line is a section header, else current."""
    if SECTION_HEADER.match(line.strip()):
        return line.strip()
    return current_section


def segment_questions(
    raw_text: str,
    year: int | None,
    subject: str,
    source_file: str,
    ocr_confidence: float = 1.0,
    min_length: int = 10,
) -> list[dict]:
    """
    Split raw paper text into individual questions.
    Returns list of question dicts ready for db.insert_question().
    """
    lines = raw_text.split("\n")
    questions: list[dict] = []
    current_lines: list[str] = []
    current_section = "General"

    def flush(lines_buf: list[str]) -> None:
        text = " ".join(l.strip() for l in lines_buf if l.strip())
        if len(text) < min_length:
            return
        marks = _extract_marks(text)
        cleaned = _clean_text(text)
        if len(cleaned) < min_length:
            return
        questions.append({
            "text": cleaned,
            "year": year,
            "subject": subject,
            "section": current_section,
            "marks": marks,
            "source_file": source_file,
            "ocr_confidence": ocr_confidence,
        })

    for line in lines:
        # Skip page break markers inserted by ingestion
        if "PAGE BREAK" in line:
            continue

        # Track section headers
        new_section = _detect_section(line, current_section)
        if new_section != current_section:
            current_section = new_section
            if current_lines:
                flush(current_lines)
                current_lines = []
            continue

        # Detect question start
        if QUESTION_START.match(line):
            if current_lines:
                flush(current_lines)
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush final question
    if current_lines:
        flush(current_lines)

    return questions


def parse_filename_metadata(filename: str) -> tuple[int | None, str]:
    """
    Try to extract year and subject from filename.
    Expects format like: 2021_data_structures.pdf
    Returns (year, subject).
    """
    stem = Path(filename).stem
    parts = stem.split("_")

    year = None
    for part in parts:
        if re.fullmatch(r"20\d{2}|19\d{2}", part):
            year = int(part)
            break

    subject_parts = [p for p in parts if not re.fullmatch(r"\d{4}", p)]
    subject = " ".join(subject_parts).replace("-", " ").title() if subject_parts else "Unknown"

    return year, subject