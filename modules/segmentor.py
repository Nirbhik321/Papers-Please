"""
segmentor.py — F05 F06
Tuned for VTU (Visvesvaraya Technological University) exam paper format.

VTU paper structure:
  - Questions numbered Q.1 – Q.10 (or Q.01 – Q.10)
  - Sub-questions labelled a / b / c inside a table:
        | a | Question text | 10 | L2 | CO2 |
  - Section headers: Module - 1, Module-2, Module -- 3
  - OR separator between question pairs per module
  - Marks, Bloom's taxonomy level, and Course Outcome in trailing columns
"""

import re
from pathlib import Path


# ── VTU course code → readable subject name ────────────────────────────────────
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


# ── Regex patterns ─────────────────────────────────────────────────────────────

# Question start — covers VTU Q.01 style + standard formats
QUESTION_START = re.compile(
    r"""
    ^\s*                            # optional leading whitespace
    (?:
        Q\.?\s*0?\d{1,2}           # Q1, Q.1, Q.01, Q 1, Q.10
        | Question\s+\d+           # Question 1
        | \d{1,2}\s*[\.\)]         # 1. or 1)
        | \([a-zA-Z]\)             # (a) (b)
        | [a-zA-Z]\s*[\.\)]        # a.  b.  c.
        | Part\s+[A-Z]             # Part A
        | Section\s+[A-Z\d]        # Section A
        | UNIT\s+[IVX\d]+          # UNIT I
    )
    [\s\:\-\|]+                    # separator after label
    """,
    re.VERBOSE | re.IGNORECASE | re.MULTILINE
)

# Marks: [5], (10), 5M, or VTU bare number adjacent to Bloom level marker
MARKS_PATTERN = re.compile(
    r"""
    [\[\(]
    \s*(\d{1,3})\s*
    (?:marks?|M|Marks)?
    \s*
    [\]\)]
    |
    \b(\d{1,2})\s*[Mm]\b
    |
    \b(\d{1,2})\s+L[1-6]\b        # VTU: "10 L2" — number then Bloom level
    """,
    re.VERBOSE
)

# VTU metadata: Bloom level, course outcome, OCR variants
VTU_NOISE = re.compile(
    r"\bL[1-6]\b|\bCO\d+\b|\bcol\b|\bco[1-9]\b",
    re.IGNORECASE
)

# Section header — Module - 1, Module-2, Module -- 3, UNIT I, Part A
SECTION_HEADER = re.compile(
    r"^(Part|Section|UNIT|Module)\s*[-–—]{0,2}\s*[A-Z0-9IVX]+\s*$",
    re.IGNORECASE | re.MULTILINE
)

# OR separator between question pairs (also catches OCR misread "POR", "0R")
OR_LINE = re.compile(r"^\s*(?:P?OR|0R)\s*$", re.IGNORECASE)

# Lines that are pure header/noise — skip entirely
SKIP_LINE = re.compile(
    r"""
    ^\s*(?:
        Time\s*:                        # "Time: 3 hrs"
        | Max\.?\s*Marks                # "Max. Marks: 100"
        | Note\s*[:\d]                  # "Note: Answer any..." / "Note: 01."
        | \d+\.\s+Answer\s+any          # "01. Answer any FIVE..."
        | Answer\s+any                  # instruction line
        | Bloom                         # "Bloom's Taxonomy"
        | Course\s+Out                  # "Course Outcomes"
        | Taxonomy                      # table header row
        | \*+\s*$                       # lines of stars/separators
        | [-=]{5,}                      # horizontal rules
        | Page\s+\d+                    # "Page 01 of 02"
        | \d+\s+of\s+\d+               # "1 of 2"
        | .*Degree\s+Examination        # "Fifth Semester B.E. Degree Examination"
        | .*Semester\s+B\.?[ET]         # "Fifth Semester B.E." / "B.Tech."
        | .*B\.?\s*Tech.*Degree         # "B.Tech. Degree"
        | Model\s+Question\s+Paper      # "Model Question Paper-1"
        | .*CBCS\s+Scheme               # scheme header
        | Draw\s+transition             # "Draw transition diagrams..."
        | .*Bloom.s\s*\|?\s*COs        # table column header row
        | \d{0,2}\.?\s*M\s*:\s*Marks    # "M: Marks..." or "2. M: Marks..." table header
        | L\s*:\s*Bloom                 # "L: Bloom's level" residual header
        | C\s*:\s*Course\s+Out         # "C: Course outcomes" variant
        | \bLevel\b\s*$                 # lone "Level" header cell
    )
    """,
    re.VERBOSE | re.IGNORECASE
)


# ── Line pre-processor ─────────────────────────────────────────────────────────

def _preprocess_line(line: str) -> str:
    """
    Normalize a raw OCR line from a VTU paper.
    - Drops pure table-border lines (|---|---|)
    - Replaces ALL pipe characters with spaces so that SKIP_LINE prefix
      checks work correctly (internal table separators survive strip()
      and would otherwise break the start-of-line match)
    - Collapses repeated whitespace
    """
    stripped = line.strip()
    # Drop pure table-border lines
    if re.match(r'^[\|\-\+\s=]+$', stripped):
        return ""
    # Replace ALL pipes with spaces so SKIP_LINE prefix checks work correctly
    stripped = stripped.replace("|", " ")
    # Collapse repeated whitespace
    stripped = re.sub(r"\s{2,}", " ", stripped).strip()
    return stripped


def _ascii_ratio(text: str) -> float:
    """Fraction of printable ASCII characters in text. Low ratio = garbled OCR."""
    if not text:
        return 0.0
    printable_ascii = sum(1 for c in text if 32 <= ord(c) < 127)
    return printable_ascii / len(text)


# Question signal words — at least one must appear for a block to be kept
_QUESTION_SIGNAL = re.compile(
    r"\b(?:what|how|why|when|where|which|who|whom|whose"
    r"|explain|define|describe|discuss|derive|prove|show"
    r"|compare|differentiate|list|write|draw|illustrate"
    r"|state|evaluate|analyse|analyze|outline|summarise|summarize"
    r"|design|implement|construct|calculate|find|solve)\b"
    r"|\?",
    re.IGNORECASE
)


def _looks_like_question(text: str) -> bool:
    """Return True if text contains at least one question-signal word or '?'."""
    return bool(_QUESTION_SIGNAL.search(text))


# ── Marks & text helpers ───────────────────────────────────────────────────────

def _extract_marks(text: str) -> int | None:
    """Pull the first marks value from question text."""
    match = MARKS_PATTERN.search(text)
    if match:
        val = match.group(1) or match.group(2) or match.group(3)
        if val:
            return int(val)
    return None


def _clean_text(text: str) -> str:
    """
    Strip question numbers, marks, VTU metadata (Bloom level, CO),
    and excess whitespace from question text.
    """
    # Remove marks indicators (all patterns)
    text = MARKS_PATTERN.sub("", text)
    # Remove VTU metadata columns (L2, CO2, col, co1...)
    text = VTU_NOISE.sub("", text)
    # Remove leading question number/label (Q.1, Q.01, a., (b), 1.)
    text = re.sub(
        r"^[\s]*(?:Q\.?\s*0?\d{1,2}|Question\s+\d+|\d{1,2}\s*[\.\)]"
        r"|\([a-zA-Z]\)|[a-zA-Z]\s*[\.\)])"
        r"[\s:\-\|]+",
        "", text, flags=re.IGNORECASE
    )
    # Remove residual pipe characters
    text = text.replace("|", " ")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Strip OCR garbage prefix that appears before the first question signal word.
    # e.g. "Co e™~¬CSMModde =D MT CC Lact What is data communication?"
    # → "What is data communication?"
    first_signal = _QUESTION_SIGNAL.search(text)
    if first_signal and first_signal.start() > 0:
        # Only strip prefix if the garbage preamble is short (< 60 chars)
        preamble = text[:first_signal.start()]
        if len(preamble) < 120:
            text = text[first_signal.start():]
    return text.strip()


def _detect_section(line: str, current_section: str) -> str:
    """Return new section name if line is a section header, else current."""
    if SECTION_HEADER.match(line.strip()):
        return line.strip()
    return current_section


# ── Main segmentor ─────────────────────────────────────────────────────────────

def segment_questions(
    raw_text: str,
    year: int | None,
    subject: str,
    source_file: str,
    ocr_confidence: float = 1.0,
    min_length: int = 10,
) -> list[dict]:
    """
    Split raw VTU paper text into individual questions.
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
        # Reject blocks that are mostly garbled symbols (dark/rotated scan pages)
        if _ascii_ratio(text) < 0.72:
            return
        marks = _extract_marks(text)
        cleaned = _clean_text(text)
        if len(cleaned) < min_length:
            return
        # Secondary quality check after cleaning
        if _ascii_ratio(cleaned) < 0.72:
            return
        # Must contain at least one question signal word or '?' to be a question
        if not _looks_like_question(cleaned):
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

        # Normalize line (strip table pipes etc.)
        line = _preprocess_line(line)
        if not line:
            continue

        # Skip known header/noise lines
        if SKIP_LINE.match(line):
            continue

        # OR separator — flush current question, don't start a new one
        if OR_LINE.match(line):
            if current_lines:
                flush(current_lines)
                current_lines = []
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


# ── Filename metadata parser ───────────────────────────────────────────────────

def parse_filename_metadata(filename: str) -> tuple[int | None, str]:
    """
    Extract year and subject from VTU-style filenames.

    Handles patterns like:
      JAN 2025 BCS502.pdf        → (2025, "Computer Networks")
      BCS503 mqp 2022-2023.pdf   → (2023, "Theory of Computation")
      DS JUNE JULY 25.pdf        → (2025, "DS")
      BCS515D - VTU QP Dec 2024-Jan 2025.pdf → (2025, "Distributed Systems")
      JuneJuly_2025.pdf          → (2025, "Unknown")
    """
    stem = Path(filename).stem
    # Normalise separators
    text = stem.replace("_", " ").replace("-", " ")

    # ── Year extraction ────────────────────────────────────────────────────────
    year: int | None = None

    # Collect ALL 4-digit years and take the latest (handles ranges like 2024-Jan 2025)
    all_four_digit = re.findall(r"\b(20\d{2}|19\d{2})\b", text)
    if all_four_digit:
        year = max(int(y) for y in all_four_digit)
    else:
        # 2-digit year like "25" → 2025, "24" → 2024
        two_digit = re.search(r"\b([2-9]\d)\b", text)
        if two_digit:
            yr = int(two_digit.group(1))
            if 20 <= yr <= 50:   # sanity: 2020–2050
                year = 2000 + yr

    # ── Subject extraction ─────────────────────────────────────────────────────
    # Try VTU course code first (e.g. BCS502, BCS515D)
    code_match = re.search(r"\b(BCS\d{3}[A-Z]?)\b", stem, re.IGNORECASE)
    if code_match:
        code = code_match.group(1).upper()
        subject = VTU_SUBJECT_MAP.get(code, code)   # fall back to code itself
        return year, subject

    # No course code — strip digits, year tokens, common exam words
    noise_words = {
        "vtu", "qp", "mqp", "pyq", "dec", "jan", "feb", "mar", "apr",
        "may", "jun", "jul", "aug", "sep", "oct", "nov", "june", "july",
        "sol", "solution", "model", "regular", "paper", "set", "exam",
        "question", "bank", "imp", "important", "midsem", "endsem",
        "semester", "theory", "computation", "cbcs",
    }
    parts = [
        p for p in re.split(r"[\s\-_]+", stem)
        if p.lower() not in noise_words
        and not re.fullmatch(r"\d+", p)
        and len(p) > 1
    ]
    subject = " ".join(parts).title() if parts else "Unknown"

    return year, subject
