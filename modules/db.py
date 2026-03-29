"""
db.py — F07
SQLite question store with FTS5 full-text search.
All pipeline stages read/write through these helpers.
"""

import sqlite3
import json
from pathlib import Path


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str) -> None:
    """Create tables if they don't exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS questions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            text            TEXT NOT NULL,
            year            INTEGER,
            subject         TEXT,
            section         TEXT,
            marks           INTEGER,
            source_file     TEXT,
            ocr_confidence  REAL DEFAULT 1.0,
            cluster_id      INTEGER DEFAULT -1,
            cluster_label   TEXT,
            heat_score      REAL DEFAULT 0.0,
            heat_tag        TEXT DEFAULT 'LOW',
            frequency_raw   INTEGER DEFAULT 1,
            years_appeared  TEXT DEFAULT '[]',
            is_canonical    INTEGER DEFAULT 1,
            alias_of        INTEGER DEFAULT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS questions_fts
        USING fts5(text, content='questions', content_rowid='id');

        CREATE TABLE IF NOT EXISTS clusters (
            cluster_id      INTEGER PRIMARY KEY,
            label           TEXT,
            size            INTEGER,
            representative  TEXT
        );
    """)

    conn.commit()
    conn.close()


def insert_question(db_path: str, question: dict) -> int:
    """Insert a question and return its new id."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO questions
            (text, year, subject, section, marks, source_file,
             ocr_confidence, years_appeared)
        VALUES
            (:text, :year, :subject, :section, :marks, :source_file,
             :ocr_confidence, :years_appeared)
    """, {
        "text": question["text"],
        "year": question.get("year"),
        "subject": question.get("subject"),
        "section": question.get("section"),
        "marks": question.get("marks"),
        "source_file": question.get("source_file"),
        "ocr_confidence": question.get("ocr_confidence", 1.0),
        "years_appeared": json.dumps([question.get("year")] if question.get("year") else []),
    })
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def get_all_questions(db_path: str, canonical_only: bool = True) -> list[dict]:
    """Return all questions as list of dicts."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    query = "SELECT * FROM questions"
    if canonical_only:
        query += " WHERE is_canonical = 1"
    query += " ORDER BY heat_score DESC"
    rows = cur.execute(query).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_questions_by_cluster(db_path: str, cluster_id: int) -> list[dict]:
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM questions WHERE cluster_id = ? AND is_canonical = 1",
        (cluster_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_cluster(db_path: str, question_id: int, cluster_id: int, label: str) -> None:
    conn = get_connection(db_path)
    conn.execute(
        "UPDATE questions SET cluster_id = ?, cluster_label = ? WHERE id = ?",
        (cluster_id, label, question_id)
    )
    conn.commit()
    conn.close()


def update_scores(db_path: str, question_id: int, heat_score: float,
                  heat_tag: str, frequency_raw: int, years_appeared: list) -> None:
    conn = get_connection(db_path)
    conn.execute("""
        UPDATE questions
        SET heat_score = ?, heat_tag = ?, frequency_raw = ?, years_appeared = ?
        WHERE id = ?
    """, (heat_score, heat_tag, frequency_raw, json.dumps(years_appeared), question_id))
    conn.commit()
    conn.close()


def upsert_cluster_label(db_path: str, cluster_id: int, label: str, size: int, representative: str) -> None:
    conn = get_connection(db_path)
    conn.execute("""
        INSERT INTO clusters (cluster_id, label, size, representative)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cluster_id) DO UPDATE SET
            label = excluded.label,
            size = excluded.size,
            representative = excluded.representative
    """, (cluster_id, label, size, representative))
    conn.commit()
    conn.close()


def get_stats(db_path: str) -> dict:
    """Return summary stats for the dashboard header."""
    conn = get_connection(db_path)
    total = conn.execute("SELECT COUNT(*) FROM questions WHERE is_canonical=1").fetchone()[0]
    topics = conn.execute("SELECT COUNT(DISTINCT cluster_id) FROM questions WHERE cluster_id >= 0").fetchone()[0]
    papers = conn.execute("SELECT COUNT(DISTINCT source_file) FROM questions").fetchone()[0]
    top_row = conn.execute(
        "SELECT cluster_label, heat_score FROM questions WHERE is_canonical=1 ORDER BY heat_score DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return {
        "total_questions": total,
        "total_topics": topics,
        "total_papers": papers,
        "top_topic": top_row["cluster_label"] if top_row else "—",
        "top_score": round(top_row["heat_score"] * 100) if top_row else 0,
    }