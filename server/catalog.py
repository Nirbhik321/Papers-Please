"""
catalog.py — the subject list (subjects.yaml) plus exam-session helpers.
"""

import re

from modules.detector import SUBJECT_CODE_RE, VTU_SUBJECT_MAP

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

_BRANCHES = {
    "CS": "CSE", "IS": "ISE", "AI": "AIML", "AD": "AIDS", "CM": "CCE",
    "CB": "CSBS", "CI": "CSE (AI&ML)", "CD": "CSE (DS)", "CY": "CSE (CY)", "CO": "CSE (IoT)",
}
_CODE_PARTS = re.compile(r"^B([A-Z]+?)L?(\d)(\d{2})[A-Z]?$")


def normalize_code(code: str) -> str | None:
    code = (code or "").strip().upper()
    m = SUBJECT_CODE_RE.fullmatch(code)
    return m.group(1).upper() if m else None


def is_known(code: str) -> bool:
    return code in VTU_SUBJECT_MAP


def subject_name(code: str) -> str | None:
    return VTU_SUBJECT_MAP.get(code)


def branch_of(code: str) -> str:
    m = _CODE_PARTS.match(code)
    return _BRANCHES.get(m.group(1), "Common") if m else "Common"


def semester_of(code: str) -> int | None:
    m = _CODE_PARTS.match(code)
    return int(m.group(2)) if m else None


def catalog() -> list[dict]:
    return [
        {"code": c, "name": n, "branch": branch_of(c), "semester": semester_of(c)}
        for c, n in sorted(VTU_SUBJECT_MAP.items())
    ]


# ── Exam sessions ──────────────────────────────────────────────────────────────
# VTU runs two semester-end sessions a year: "Dec/Jan" and "June/July". Papers get
# labelled either way ("Dec 2024", "Jan 2025", "Dec 2024-Jan 2025"), so we fold
# them onto one canonical month so duplicates of the same exam are recognised.

def normalize_session(month: str | None, year: int | None) -> tuple[str | None, int | None]:
    if not month or month not in MONTHS or not year:
        return month, year
    if month in ("November", "December"):
        return "January", year + 1
    if month == "February":
        return "January", year
    if month in ("May", "June", "August"):
        return "July", year
    return month, year


def session_key(code: str, paper_type: str, month: str | None, year: int | None) -> str | None:
    """Only one live semester-end paper per subject+session. Model papers can have several sets."""
    if paper_type != "see" or not month or not year:
        return None
    return f"{code}:see:{year}:{month[:3].lower()}"


def session_label(paper_type: str, month: str | None, year: int | None, short: bool = False) -> str:
    if paper_type == "model":
        base = "Model" if short else "Model paper"
        return f"{base} {str(year)[-2:] if short and year else year or ''}".strip()
    if month and year:
        return f"{month[:3]} {str(year)[-2:] if short else year}"
    return str(year) if year else "Undated"
