"""
scorer.py — Frequency × recency × marks scoring for canonical questions.

Scoring formula:
  weighted_score = sum over unique papers of (DECAY ^ (current_year - paper_year))

  Where DECAY = 0.85, meaning (in 2025):
    2025 paper → weight 1.00
    2024 paper → weight 0.85
    2023 paper → weight 0.72
    2022 paper → weight 0.61
    2021 paper → weight 0.52
  Undated model papers count as a year older than the subject's earliest exam.

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


def fill_missing_marks(sub_questions: list[dict], question_marks: int = MAX_MODULE_MARKS) -> list[dict]:
    """
    OCR often loses the narrow marks column. A VTU question's parts total 20, so
    each part without marks gets an equal share of what its siblings leave over.
    Returns copies; parts with marks are untouched.
    """
    by_question: dict[tuple, list[dict]] = {}
    for q in sub_questions:
        by_question.setdefault((q.get("paper_id"), q.get("q_no")), []).append(q)
    filled = {}
    for parts in by_question.values():
        unknown = [p for p in parts if not p.get("marks")]
        if not unknown:
            continue
        left = max(question_marks - sum(p["marks"] for p in parts if p.get("marks")), 0)
        for p in unknown:
            filled[id(p)] = round(left / len(unknown)) or None
    return [{**q, "marks": filled[id(q)]} if id(q) in filled else q for q in sub_questions]


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
    # Model question papers carry no exam date. They are published with the scheme, before
    # its first exam, so date them a year before the earliest real exam rather than treating
    # them as the newest papers (which would rank them above last year's exam).
    dated = [a["year"] for c in canonicals for a in c.get("appearances", []) if a.get("year")]
    undated_year = min(dated) - 1 if dated else current_year

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
            RECENCY_DECAY ** max(0, current_year - (a.get("year") or undated_year))
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

    # Ties (common when most topics have appeared once) go to the topic seen in more papers,
    # then to the one worth more marks, so the order never depends on clustering order
    scored.sort(key=lambda x: (x["weighted_score"], x["frequency"], x.get("avg_marks") or 0), reverse=True)
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
