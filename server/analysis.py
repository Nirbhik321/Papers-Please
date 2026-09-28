"""
analysis.py — rebuild a subject's ranking and publish it.

Runs after any change to a subject's approved papers. It regroups every
question (deduplicator), scores the groups (scorer), labels them (tagger),
and writes one precomputed snapshot: the JSON the website renders, the
cheat-sheet PDF and the CSV question bank. Students only ever read snapshots,
so reading a subject never runs any of this work.
"""

import json
import secrets
import tempfile
import threading
from collections import Counter
from pathlib import Path

import httpx
from sqlalchemy import delete, insert, select

from modules import deduplicator, exporter, scorer, tagger
from server import catalog
from server.config import settings
from server.db import engine, papers, sub_questions, subject_snapshots, topic_appearances, topics, utcnow

MODULE_MARKS = scorer.MAX_MODULE_MARKS


def _approved_papers(conn, code: str) -> list[dict]:
    rows = conn.execute(
        select(papers).where(papers.c.subject_code == code, papers.c.status == "approved")
    ).mappings().all()
    month_idx = {m: i for i, m in enumerate(catalog.MONTHS)}
    return sorted(
        (dict(r) for r in rows),
        key=lambda p: (p["exam_year"] or 0, month_idx.get(p["exam_month"], -1), p["paper_type"] == "see"),
        reverse=True,
    )


def _previous_topics(conn, code: str) -> dict[int, tuple[str, str | None]]:
    """sub_question_id → (stable_key, label) from the last build, to keep keys stable."""
    rows = conn.execute(
        select(topic_appearances.c.sub_question_id, topics.c.stable_key, topics.c.label)
        .join(topics, topics.c.id == topic_appearances.c.topic_id)
        .where(topics.c.subject_code == code)
    ).all()
    return {r.sub_question_id: (r.stable_key, r.label) for r in rows}


def rebuild_subject(code: str) -> dict | None:
    """Recompute and store the snapshot for one subject. Returns the snapshot data."""
    with engine.begin() as conn:
        live = _approved_papers(conn, code)
        if not live:
            conn.execute(delete(topics).where(topics.c.subject_code == code))
            conn.execute(delete(subject_snapshots).where(subject_snapshots.c.subject_code == code))
            data = None
        else:
            data, ladders = _build(conn, code, live)
            pdf, csv_text = _exports(data, ladders)
            years = [p["exam_year"] for p in live if p["exam_year"]]
            conn.execute(delete(subject_snapshots).where(subject_snapshots.c.subject_code == code))
            conn.execute(insert(subject_snapshots).values(
                subject_code=code, subject_name=data["name"], paper_count=data["paperCount"],
                topic_count=data["topicCount"], min_year=min(years, default=None),
                max_year=max(years, default=None), data=json.dumps(data), cheatsheet_pdf=pdf,
                questions_csv=csv_text, updated_at=utcnow(),
            ))
    _revalidate_async(["/", f"/s/{code}"])
    return data


def _build(conn, code: str, live: list[dict]) -> tuple[dict, dict]:
    by_id = {p["id"]: p for p in live}
    total = len(live)
    name = catalog.subject_name(code) or live[0]["subject_name"] or code

    sqs = [
        {**dict(r), "year": by_id[r.paper_id]["exam_year"]}
        for r in conn.execute(select(sub_questions).where(sub_questions.c.paper_id.in_(list(by_id)))).mappings()
    ]
    previous = _previous_topics(conn, code)
    conn.execute(delete(topics).where(topics.c.subject_code == code))

    used_keys: set[str] = set()
    modules_out, ladders = [], {}
    for module_no in range(1, 6):
        module_sqs = [q for q in sqs if q["module_no"] == module_no]
        if not module_sqs:
            continue
        scored = scorer.score_canonicals(deduplicator.deduplicate(module_sqs), total)
        if total == 1:   # nothing repeats yet — rank by marks instead
            scored.sort(key=lambda c: c.get("avg_marks") or 0, reverse=True)

        text_by_sq = {q["id"]: q["text"] for q in module_sqs}
        topics_out = []
        for rank, c in enumerate(scored, start=1):
            sq_ids = [a["sub_question_id"] for a in c["appearances"]]
            key, label = _carry_over(sq_ids, previous, used_keys)
            if not label:
                label = tagger.generate_topic_label([text_by_sq[i] for i in sq_ids])
            label = _clean_label(label)
            c["topic_label"] = label

            topic_id = conn.execute(insert(topics).values(
                subject_code=code, module_no=module_no, stable_key=key, label=label,
                representative_text=c["representative_text"], avg_marks=c["avg_marks"],
                frequency=c["frequency"], weighted_score=c["weighted_score"],
                last_seen_year=c["last_seen_year"],
            )).inserted_primary_key[0]
            conn.execute(insert(topic_appearances), [
                {"topic_id": topic_id, "sub_question_id": i} for i in sq_ids
            ])

            session_ids = [p["id"] for p in live if p["id"] in {a["paper_id"] for a in c["appearances"]}]
            topics_out.append({
                "key": key,
                "rank": rank,
                "label": label,
                "text": c["representative_text"],
                "frequency": c["frequency"],
                "frequencyPct": round(c["frequency_pct"], 4),
                "avgMarks": round(c["avg_marks"] or 0, 1),
                "expectedMarks": round(c["expected_marks"], 2),
                "sessions": session_ids,
                "wordings": [
                    {"session": a["paper_id"], "where": f"Q{a['q_no']}{a['sub_q']}",
                     "marks": a.get("marks"), "text": text_by_sq[a["sub_question_id"]]}
                    for a in sorted(c["appearances"], key=lambda a: session_ids.index(a["paper_id"]))
                ],
            })

        ladder, full_at, cum = [], None, 0.0
        for t in topics_out:
            cum += t["expectedMarks"]
            ladder.append({"rank": t["rank"], "label": t["label"],
                           "cumulative": round(min(cum, MODULE_MARKS), 1), "full": cum >= MODULE_MARKS})
            if cum >= MODULE_MARKS:
                full_at = t["rank"]
                break
        modules_out.append({"no": module_no, "topics": topics_out, "ladder": ladder, "fullAt": full_at})

        # Same shape the PDF/CSV exporters already understand
        enriched = [{**c, "years": c["years"], "appearances": c["appearances"]} for c in scored]
        ladders[module_no] = scorer.build_marks_ladder(enriched, max_marks=MODULE_MARKS)

    years = [p["exam_year"] for p in live if p["exam_year"]]
    data = {
        "code": code,
        "name": name,
        "branch": catalog.branch_of(code),
        "semester": catalog.semester_of(code),
        "updatedAt": utcnow().isoformat(),
        "paperCount": total,
        "topicCount": sum(len(m["topics"]) for m in modules_out),
        "minYear": min(years, default=None),
        "maxYear": max(years, default=None),
        "moduleMarks": MODULE_MARKS,
        "sessions": [
            {"id": p["id"], "type": p["paper_type"], "source": p["pdf_type"],
             "label": catalog.session_label(p["paper_type"], p["exam_month"], p["exam_year"]),
             "short": catalog.session_label(p["paper_type"], p["exam_month"], p["exam_year"], short=True)}
            for p in live
        ],
        "modules": modules_out,
    }
    return data, ladders


def _carry_over(sq_ids, previous, used_keys) -> tuple[str, str | None]:
    """Reuse the stable key (and label) of the old topic that shared most of these questions."""
    votes = Counter(previous[i] for i in sq_ids if i in previous)
    for (key, label), _ in votes.most_common():
        if key not in used_keys:
            used_keys.add(key)
            return key, label
    key = secrets.token_hex(6)
    used_keys.add(key)
    return key, None


def _clean_label(label: str) -> str:
    label = " ".join((label or "").split())[:80]
    return label or "Untitled topic"


def _exports(data: dict, ladders: dict) -> tuple[bytes, str]:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "sheet.pdf"
        exporter.generate_cheat_sheet(data["name"], data["code"], ladders, data["paperCount"], str(out))
        pdf = out.read_bytes()
    csv_text = exporter.generate_csv(data["name"], data["code"], ladders, data["paperCount"])
    return pdf, csv_text


def _revalidate_async(paths: list[str]) -> None:
    """Tell the Next.js site to refresh the affected pages (on-demand ISR)."""
    if not settings.revalidate_url:
        return

    def send():
        try:
            httpx.post(settings.revalidate_url, json={"paths": paths}, timeout=10,
                       headers={"Authorization": f"Bearer {settings.revalidate_secret}"})
        except Exception:
            pass   # pages still refresh on their normal timer

    threading.Thread(target=send, daemon=True).start()
