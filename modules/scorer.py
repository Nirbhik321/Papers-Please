"""
scorer.py — F16 F17
Frequency scoring with recency decay and heat tag assignment.
Operates per-cluster on canonical questions.
"""

import json
from collections import defaultdict


def compute_scores(
    questions: list[dict],
    decay: float = 0.85,
    heat_high: float = 0.7,
    heat_mid: float = 0.4,
) -> list[dict]:
    """
    For each question compute:
      - frequency_raw: how many times this question (text) appeared across papers
      - weighted_score: sum of decay^(max_year - year) per appearance
      - heat_score: normalised 0-1 within cluster
      - heat_tag: HIGH / MEDIUM / LOW

    questions: list of dicts from db.get_all_questions()
    Returns same list with scores filled in.
    """
    if not questions:
        return questions

    years = [q["year"] for q in questions if q.get("year")]
    max_year = max(years) if years else 2024

    # Group by cluster for normalisation
    cluster_groups: dict[int, list[dict]] = defaultdict(list)
    for q in questions:
        cluster_groups[q.get("cluster_id", -1)].append(q)

    scored = []
    for cluster_id, cluster_qs in cluster_groups.items():
        # Compute weighted scores within cluster
        for q in cluster_qs:
            years_appeared = json.loads(q.get("years_appeared", "[]"))
            if not years_appeared and q.get("year"):
                years_appeared = [q["year"]]

            raw_count = len(years_appeared)
            weighted = sum(
                decay ** (max_year - yr)
                for yr in years_appeared
                if yr is not None
            )
            q["frequency_raw"] = raw_count
            q["_weighted"] = weighted

        # Normalise within cluster
        max_w = max((q["_weighted"] for q in cluster_qs), default=1.0)
        if max_w == 0:
            max_w = 1.0

        for q in cluster_qs:
            heat = q["_weighted"] / max_w
            q["heat_score"] = round(heat, 4)
            if heat >= heat_high:
                q["heat_tag"] = "HIGH"
            elif heat >= heat_mid:
                q["heat_tag"] = "MEDIUM"
            else:
                q["heat_tag"] = "LOW"
            del q["_weighted"]
            scored.append(q)

    return scored


def assign_heat_tag(score: float, heat_high: float = 0.7, heat_mid: float = 0.4) -> str:
    if score >= heat_high:
        return "HIGH"
    elif score >= heat_mid:
        return "MEDIUM"
    return "LOW"