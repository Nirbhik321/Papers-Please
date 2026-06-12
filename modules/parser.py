"""
parser.py — Convert raw table rows into structured sub_question records.

VTU CBCS paper table — 6 logical columns:
  Q.No | Sub | Question text | Marks | Bloom | CO

BUT scanned PDFs produce messy rows with variable column counts (8-10),
garbled Q.No values ("Qa", "O22", "0.7"), and noisy marks ("(06—", "} 10").

Strategy:
  1. Auto-detect which column index serves which role (text length heuristic).
  2. Use loose regex with fallback for all value extraction.
  3. Infer Q.No from a running counter when sub_q='a' starts a new question.
  4. Detect module headers by looking for "Module" keyword or short numeric cells.
"""

import re
from typing import Optional


# ── Loose value patterns ───────────────────────────────────────────────────────

# Q.No — catches "Q.1", "Q1", "O.4", "0.7", "oO6", "O22" (Q doubled digit)
_Q_NO_LOOSE = re.compile(
    r"[Qq0Oo][.\s]?[Oo0]?(\d{1,2})",   # e.g. Q.1, O.4, 0.7, oO6 (→6), O22 (→2)
)
# Also handle "O22" → Q.2 (digit doubled): [QqOo0]\d\d where both digits same
_Q_NO_DOUBLED = re.compile(r"[QqOo0](\d)\1")   # "O22" → group(1)="2"

# Sub-question — first letter a/b/c in a short cell
_SUB_Q_LOOSE = re.compile(r"^[^a-cA-C]*([a-cA-C])[.\s]*$")

# Marks — any 1-2 digit number in range 2-20
_MARKS_LOOSE = re.compile(r"\b(\d{1,2})\b")

# Bloom level — L followed by 1-6 anywhere in cell
_BLOOM_LOOSE = re.compile(r"L\s*([1-6])", re.IGNORECASE)

# Course outcome — CO or CQ or Cco followed by a digit
_CO_LOOSE = re.compile(r"C[Ooq][Qq]?\s*(\d)", re.IGNORECASE)

# Module header — "Module" keyword (or garbled OCR approximations) or "Module — N"
_MODULE_STRICT = re.compile(r"module\s*[-–—=~]*\s*(\d)", re.IGNORECASE)
# Garbled "Module" patterns: M+vowel+d or Mod/Modu fragments
_MODULE_FUZZY  = re.compile(
    r"(?:Mod(?:u|v|ul|ule)?|M[aeiouv][dg]|Mfod)\w*\s*[-–—=~P]+\s*([1-5])",
    re.IGNORECASE,
)
# Second fuzzy: catches more garbled OCR combos like "MoDuLe =P 2", "Mfdule – 4"
_MODULE_FUZZY2 = re.compile(
    r"M[0oO][dD][uUvV]?\w{0,3}\s*[-–—=~|P]+\s*([1-5])",
    re.IGNORECASE,
)

# Patterns that disqualify a row from being a module header heuristic
_SUB_Q_LABEL_PAT = re.compile(r"\b[a-cA-C]\s*[.\)]\s")   # "a. " or "b) "
_Q_NO_PAT        = re.compile(r"[QqOo0]\s*[.\s]?\s*\d")   # Q.1, O.4, O22

# OR separator row
_OR_ROW = re.compile(r"^\s*(?:P?OR|0R)\s*$", re.IGNORECASE)

# Skip rows (page headers/footers)
_SKIP_ROW = re.compile(
    r"""
    ^\s*(?:
        \d+\s+of\s+\d+
        | Page\s+\d+
        | USN
        | CBCS
        | Time\s*:
        | Max\.?\s*Marks
        | Note\s*[:\d]
        | Answer\s+any
        | M\s*[:,]\s*Marks
        | \*{3,}
        | [-=]{10,}
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Words that indicate a line is a real question (not a header)
_QUESTION_WORDS = re.compile(
    r"\b(?:explain|define|describe|discuss|derive|prove|show|compare|"
    r"differentiate|list|write|draw|illustrate|state|evaluate|analyse|"
    r"analyze|outline|find|solve|with|what|how|why|briefly|note)\b",
    re.IGNORECASE,
)


def _get_cell(row: list[str], col_idx: int) -> str:
    if col_idx < 0 or col_idx >= len(row):
        return ""
    return (row[col_idx] or "").strip()


# ── Value extractors (all loose/fuzzy) ────────────────────────────────────────

def _extract_q_no(cell: str) -> Optional[int]:
    """Extract question number from garbled OCR like 'O22', '0.7', 'Qa'."""
    cell = cell.strip()
    if not cell:
        return None
    # Doubled digit: O22 → 2, Q33 → 3 (OCR doubles the digit)
    m = _Q_NO_DOUBLED.search(cell)
    if m:
        return int(m.group(1))
    # Standard Q.No with digit
    m = _Q_NO_LOOSE.search(cell)
    if m:
        val = int(m.group(1))
        if 1 <= val <= 10:
            return val
    return None


def _extract_sub_q(cell: str) -> Optional[str]:
    """Extract sub-question label (a/b/c) from garbled cell like 'be', 'ce', 'rh'."""
    cell = cell.strip()
    if not cell:
        return None
    # Direct match: starts with a/b/c (period or space optional)
    m = re.match(r"^([a-cA-C])", cell)
    if m:
        return m.group(1).lower()
    return None


def _extract_marks(cell: str) -> Optional[int]:
    """Extract marks from noisy cell like '(06—', '/ 06', '} 10', '110'."""
    # Find all 1-2 digit numbers in range 4-20
    candidates = [int(m) for m in re.findall(r"\b(\d{1,2})\b", cell)
                  if 4 <= int(m) <= 20]
    # Prefer multiples of 2 (VTU marks are always even: 4,6,8,10,12)
    multiples = [v for v in candidates if v % 2 == 0]
    if multiples:
        return multiples[0]
    return candidates[0] if candidates else None


def _extract_bloom(cell: str) -> Optional[str]:
    m = _BLOOM_LOOSE.search(cell)
    return f"L{m.group(1)}" if m else None


def _extract_co(cell: str) -> Optional[str]:
    m = _CO_LOOSE.search(cell)
    return f"CO{m.group(1)}" if m else None


# ── Module header detection ────────────────────────────────────────────────────

def _detect_module(row: list[str], text_col: int) -> Optional[int]:
    """Return module number if this row is a module header, else None.

    Guarding against false positives:
    - Sub-question label rows ("a. Explain ...")
    - Q.No rows ("Q.3 ...")
    - Rows with marks-range numbers (4-20)
    """
    full = " ".join(c for c in row if c).strip()

    # Strict: "Module – 3" or "Module = 1" (even with OCR noise in separator)
    m = _MODULE_STRICT.search(full)
    if m:
        return int(m.group(1))

    # Fuzzy pass 1: garbled "Module" OCR like "Mfodwle =P"
    m = _MODULE_FUZZY.search(full)
    if m:
        return int(m.group(1))

    # Fuzzy pass 2: covers more OCR combos
    m = _MODULE_FUZZY2.search(full)
    if m:
        return int(m.group(1))

    # Heuristic: short isolated row containing only a digit 1-5.
    # Apply STRICT guards to avoid false positives on garbled Q.No rows:
    #   - must be ≤ 20 chars (tighter than before)
    #   - must not look like "a. something" (sub-question label)
    #   - must not look like "Q.3" (Q.No cell)
    #   - must not contain a marks-range number (4-20)
    #   - must not contain question-verb words
    if (
        len(full) <= 20
        and not _QUESTION_WORDS.search(full)
        and not _SUB_Q_LABEL_PAT.search(full)
        and not _Q_NO_PAT.search(full)
        and not any(4 <= int(d) <= 20 for d in re.findall(r"\b(\d{1,2})\b", full))
        and "?" not in full
    ):
        digits = re.findall(r"\b([1-5])\b", full)
        if len(digits) == 1:          # exactly one module digit, no ambiguity
            return int(digits[0])

    return None


def _q_no_to_module(q_no: int) -> int:
    """
    Infer VTU module number from question number.
    VTU CBCS: Q.1-2 → M1, Q.3-4 → M2, Q.5-6 → M3, Q.7-8 → M4, Q.9-10 → M5
    """
    if q_no <= 2:
        return 1
    elif q_no <= 4:
        return 2
    elif q_no <= 6:
        return 3
    elif q_no <= 8:
        return 4
    else:
        return 5


# ── Main parser ────────────────────────────────────────────────────────────────

def parse_rows(raw_rows: list[list[str]]) -> list[dict]:
    """
    Convert raw table rows from detector.py into sub_question records.

    The detector always outputs rows using fixed VTU CBCS column layout:
      col 0: Q.No | col 1: Sub | col 2: Text | col 3: M | col 4: L | col 5: C

    Because PSM 6 sometimes merges the narrow M/L/C columns, we scan ALL
    right-side cells (cols 3+) for marks, bloom, and CO patterns instead of
    looking at a single fixed column index.
    """
    if not raw_rows:
        return []

    # Fixed column positions (match detector.py's col_splits layout)
    Q_NO_COL  = 0
    SUB_Q_COL = 1
    TEXT_COL  = 2
    # Cols 3, 4, 5 are M, L, C — we scan all of them for values

    sub_questions: list[dict] = []
    current_module = 0
    current_q_no = 0
    current_text_lines: list[str] = []
    current_sub_q: Optional[str] = None
    current_marks: Optional[int] = None
    current_bloom: Optional[str] = None
    current_co: Optional[str] = None

    def flush():
        nonlocal current_text_lines, current_sub_q, current_marks, current_bloom, current_co, current_module
        text = " ".join(current_text_lines).strip()
        text = _clean_question_text(text)
        # Auto-repair module from q_no if still unset
        effective_module = current_module or (
            _q_no_to_module(current_q_no) if current_q_no > 0 else 0
        )
        if text and len(text) > 10 and effective_module > 0 and current_q_no > 0 and current_sub_q:
            sub_questions.append({
                "module_no": effective_module,
                "q_no": current_q_no,
                "sub_q": current_sub_q,
                "is_or_alt": 1 if current_q_no % 2 == 0 else 0,
                "text": text,
                "marks": current_marks,
                "bloom_level": current_bloom,
                "course_outcome": current_co,
            })
        current_text_lines = []
        current_sub_q = None
        current_marks = None
        current_bloom = None
        current_co = None

    def _scan_right_cells(row: list[str]) -> tuple:
        """Scan cols 3+ for marks, bloom, co — handles column merging by PSM 6."""
        marks = bloom = co = None
        right_text = " ".join(row[3:]) if len(row) > 3 else ""
        # Also include text col fragments that accidentally captured metadata
        marks = _extract_marks(right_text)
        bloom = _extract_bloom(right_text)
        co    = _extract_co(right_text)
        return marks, bloom, co

    _SUB_Q_SEQUENCE = ["a", "b", "c", "d"]
    last_sub_q_idx = -1

    for row in raw_rows:
        full = " ".join(c for c in row if c).strip()
        if not full:
            continue

        if _SKIP_ROW.match(full):
            continue

        # Module header check
        mod_no = _detect_module(row, TEXT_COL)
        if mod_no:
            flush()
            current_module = mod_no
            last_sub_q_idx = -1
            # Preset q_no so the next sub_q='a' lands on the right question number.
            # VTU: Module M starts at Q.(2M-1), so the question BEFORE that is 2M-2.
            current_q_no = (mod_no - 1) * 2
            continue

        text_cell = _get_cell(row, TEXT_COL)

        if _OR_ROW.match(text_cell) or _OR_ROW.match(full):
            continue

        # Extract structured values
        q_no_val  = _extract_q_no(_get_cell(row, Q_NO_COL))
        sub_q_raw = _get_cell(row, SUB_Q_COL)
        sub_q_val = _extract_sub_q(sub_q_raw)

        # Scan ALL right-side cells for marks/bloom/co (handles PSM-6 merging)
        marks_val, bloom_val, co_val = _scan_right_cells(row)

        # Is this row a new sub-question?
        text_is_question = (
            len(text_cell) > 20
            and _QUESTION_WORDS.search(text_cell)
        )
        has_sub_q_label = sub_q_val is not None

        if text_is_question:
            flush()

            if sub_q_val:
                current_sub_q = sub_q_val
                last_sub_q_idx = (
                    _SUB_Q_SEQUENCE.index(sub_q_val)
                    if sub_q_val in _SUB_Q_SEQUENCE
                    else last_sub_q_idx + 1
                )
            else:
                last_sub_q_idx += 1
                if last_sub_q_idx >= len(_SUB_Q_SEQUENCE):
                    last_sub_q_idx = 0
                current_sub_q = _SUB_Q_SEQUENCE[last_sub_q_idx]

            if q_no_val:
                current_q_no = q_no_val
            elif current_sub_q == "a":
                current_q_no += 1

            # Always sync module from Q.No — handles garbled/missing headers.
            # We only move forward (never reduce module number) to avoid noise.
            if current_q_no > 0:
                inferred = _q_no_to_module(current_q_no)
                if inferred >= current_module:
                    current_module = inferred

            current_text_lines = [text_cell]
            current_marks = marks_val
            current_bloom = bloom_val
            current_co = co_val

        elif has_sub_q_label and text_cell:
            # Row with sub_q label and short/no text — update context
            if q_no_val:
                current_q_no = q_no_val
            current_sub_q = sub_q_val
            last_sub_q_idx = (
                _SUB_Q_SEQUENCE.index(sub_q_val)
                if sub_q_val in _SUB_Q_SEQUENCE
                else last_sub_q_idx + 1
            )
            if sub_q_val == "a":
                current_q_no += 1
            if marks_val:
                current_marks = marks_val
            if bloom_val:
                current_bloom = bloom_val
            if co_val:
                current_co = co_val
            # If text cell also has question content, start accumulating
            if len(text_cell) > 20 and _QUESTION_WORDS.search(text_cell):
                current_text_lines = [text_cell]

        elif text_cell and len(text_cell) > 8 and current_sub_q is not None:
            # Continuation line
            current_text_lines.append(text_cell)
            if marks_val and not current_marks:
                current_marks = marks_val
            if bloom_val and not current_bloom:
                current_bloom = bloom_val
            if co_val and not current_co:
                current_co = co_val

    flush()
    return sub_questions


# ── Text cleaner ───────────────────────────────────────────────────────────────

_VTU_META = re.compile(r"\b(?:L[1-6]|CO\d+|col\b|co[1-9]\b)\b", re.IGNORECASE)
_MARKS_INLINE = re.compile(r"\[?\s*\d{1,2}\s*\]?\s*(?:marks?|M\b)?", re.IGNORECASE)
_LEADING_LABEL = re.compile(r"^(?:Q\.?\s*\d{1,2}|[a-c]\.)\s*", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s{2,}")


def _clean_question_text(text: str) -> str:
    """Strip question labels, marks tags, bloom/CO metadata, and extra whitespace."""
    text = _LEADING_LABEL.sub("", text)
    text = _VTU_META.sub("", text)
    text = re.sub(r"[|]", " ", text)
    text = _WHITESPACE.sub(" ", text)
    return text.strip(" .,;:")
