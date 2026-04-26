"""
scorer.py — Frequency × recency × marks scoring for canonical questions.

Scoring formula:
  weighted_score = sum over unique papers of (DECAY ^ (current_year - paper_year))

  Where DECAY = 0.85, meaning:
    2025 paper → weight 1.00
    2024 paper → weight 0.85
    2023 paper → weight 0.72
    2022 paper → weight 0.61
    2021 paper → weight 0.52

  frequency = count of DISTINCT papers the question appeared in
  expected_marks = (frequency / total_papers) × avg_marks

The "guaranteed marks" calculation:
  Rank questions by weighted_score DESC.
  Accumulate expected_marks top-down.
  When cumulative ≥ max_module_marks → student has full coverage.
"""

from datetime import date

RECENCY_DECAY = 0.85
MAX_MODULE_MARKS = 20   # each module contributes max 20M to exam total


def score_canonicals(
    canonicals: list[dict],
    total_papers: int,
    current_year: int | None = None,
) -> list[dict]:
    """
    Add scoring fields to each canonical dict and sort by weighted_score DESC.

    Args:
        canonicals: output of deduplicator.deduplicate()
        total_papers: total number of papers uploaded for this subject
        current_year: reference year for recency decay (defaults to this year)

    Returns:
        Same list, sorted by weighted_score DESC, with added fields:
          frequency, frequency_pct, weighted_score, expected_marks,
          years (sorted desc), last_seen_year
    """
    if current_year is None:
        current_year = date.today().year

    scored = []
    for c in canonicals:
        appearances = c.get("appearances", [])

        # Deduplicate by paper — same paper can have same question in Q3 and Q4
        # (shouldn't happen, but guard against it)
        seen_papers: set[int] = set()
        unique_appearances: list[dict] = []
        for a in appearances:
            if a["paper_id"] not in seen_papers:
                seen_papers.add(a["paper_id"])
                unique_appearances.append(a)

        frequency = len(seen_papers)
        years = sorted(
            {a["year"] for a in unique_appearances if a.get("year")}, reverse=True
        )
        last_seen_year = years[0] if years else None

        weighted_score = sum(
            RECENCY_DECAY ** max(0, current_year - (a.get("year") or current_year))
            for a in unique_appearances
        )

        frequency_pct = frequency / max(total_papers, 1)
        expected_marks = frequency_pct * c.get("avg_marks", 0)

        scored.append({
            **c,
            "frequency": frequency,
            "frequency_pct": frequency_pct,
            "weighted_score": round(weighted_score, 4),
            "expected_marks": round(expected_marks, 2),
            "years": years,
            "last_seen_year": last_seen_year,
        })

    scored.sort(key=lambda x: x["weighted_score"], reverse=True)
    return scored


def build_marks_ladder(
    scored_canonicals: list[dict],
    max_marks: int = MAX_MODULE_MARKS,
) -> list[dict]:
    """
    Build the cumulative "marks you lock in" ladder.

    Returns list of steps (one per canonical question), each with:
      rank, topic_label, representative_text, frequency, frequency_pct,
      avg_marks, expected_marks, cumulative_expected, years,
      full_coverage (bool — cumulative has hit max_marks)
    """
    steps = []
    cumulative = 0.0

    for rank, c in enumerate(scored_canonicals, start=1):
        cumulative += c["expected_marks"]
        steps.append({
            "rank": rank,
            "topic_label": c.get("topic_label") or c["representative_text"][:50],
            "representative_text": c["representative_text"],
            "frequency": c["frequency"],
            "frequency_pct": c["frequency_pct"],
            "avg_marks": c.get("avg_marks", 0),
            "expected_marks": c["expected_marks"],
            "cumulative_expected": round(min(cumulative, max_marks), 2),
            "years": c.get("years", []),
            "full_coverage": cumulative >= max_marks,
            "appearances": c.get("appearances", []),
        })
        if cumulative >= max_marks * 1.5:
            # More than enough coverage — stop the ladder here
            break

    return steps


def format_years(years: list[int]) -> str:
    """Format a list of years into a readable string."""
    if not years:
        return "—"
    if len(years) == 1:
        return str(years[0])
    return ", ".join(str(y) for y in sorted(years, reverse=True))


def format_appearances(appearances: list[dict]) -> str:
    """
    Format the 'found in' metadata string.
    e.g. "Q3a(2025) · Q4b(2024) · Q3a(2023)"
    """
    parts = []
    for a in sorted(appearances, key=lambda x: x.get("year") or 0, reverse=True):
        year = a.get("year", "?")
        q_no = a.get("q_no", "?")
        sub_q = a.get("sub_q", "?")
        parts.append(f"Q{q_no}{sub_q}({year})")
    return " · ".join(parts)
