"""
db.py — SQLite helper layer.

Schema (4 tables):
  papers             — one row per uploaded PDF
  sub_questions      — one row per sub-question (a/b/c) extracted from a paper
  canonical_questions — deduplicated question groups across papers
  appearances        — join: which sub_questions map to which canonical
"""

import sqlite3
from pathlib import Path
from typing import Optional


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> None:
    """Create all tables if they don't exist."""
    conn = get_conn(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS papers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            filename        TEXT NOT NULL,
            subject_code    TEXT NOT NULL,
            subject_name    TEXT NOT NULL,
            month           TEXT,
            year            INTEGER,
            pdf_type        TEXT,           -- 'native' or 'scanned'
            total_pages     INTEGER,
            uploaded_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(filename)
        );

        CREATE TABLE IF NOT EXISTS sub_questions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id        INTEGER NOT NULL REFERENCES papers(id),
            module_no       INTEGER NOT NULL,   -- 1-5
            q_no            INTEGER NOT NULL,   -- 1-10
            sub_q           TEXT NOT NULL,      -- 'a', 'b', 'c'
            is_or_alt       INTEGER NOT NULL,   -- 0=primary(odd q_no), 1=OR-alt(even q_no)
            text            TEXT NOT NULL,
            marks           INTEGER,
            bloom_level     TEXT,               -- L1-L6
            course_outcome  TEXT                -- CO1-CO5
        );

        CREATE TABLE IF NOT EXISTS canonical_questions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_code        TEXT NOT NULL,
            module_no           INTEGER NOT NULL,
            representative_text TEXT NOT NULL,  -- clearest/most recent phrasing
            topic_label         TEXT,           -- Ollama-generated 3-5 word label
            avg_marks           REAL,
            frequency           INTEGER DEFAULT 0,   -- # distinct papers it appeared in
            weighted_score      REAL DEFAULT 0.0,    -- frequency × recency decay
            last_seen_year      INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_canonical_subject_module
            ON canonical_questions(subject_code, module_no);

        CREATE TABLE IF NOT EXISTS appearances (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id        INTEGER NOT NULL REFERENCES canonical_questions(id),
            sub_question_id     INTEGER NOT NULL REFERENCES sub_questions(id),
            paper_id            INTEGER NOT NULL REFERENCES papers(id),
            year                INTEGER,
            q_no                INTEGER,
            sub_q               TEXT,
            marks               INTEGER,
            UNIQUE(sub_question_id)
        );

        CREATE INDEX IF NOT EXISTS idx_appearances_canonical
            ON appearances(canonical_id);
    """)
    conn.commit()
    conn.close()


# ── Papers ─────────────────────────────────────────────────────────────────────

def insert_paper(db_path: str, paper: dict) -> Optional[int]:
    """Insert a paper. Returns new id, or None if filename already exists."""
    conn = get_conn(db_path)
    try:
        cur = conn.execute(
            """INSERT OR IGNORE INTO papers
               (filename, subject_code, subject_name, month, year, pdf_type, total_pages)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (paper["filename"], paper["subject_code"], paper["subject_name"],
             paper.get("month"), paper.get("year"), paper.get("pdf_type"),
             paper.get("total_pages")),
        )
        conn.commit()
        if cur.lastrowid == 0:
            row = conn.execute(
                "SELECT id FROM papers WHERE filename=?", (paper["filename"],)
            ).fetchone()
            return row["id"] if row else None
        return cur.lastrowid
    finally:
        conn.close()


def get_all_papers(db_path: str) -> list[dict]:
    conn = get_conn(db_path)
    rows = conn.execute(
        "SELECT * FROM papers ORDER BY year DESC, month DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def paper_exists(db_path: str, filename: str) -> bool:
    conn = get_conn(db_path)
    row = conn.execute(
        "SELECT id FROM papers WHERE filename=?", (filename,)
    ).fetchone()
    conn.close()
    return row is not None


# ── Sub-questions ───────────────────────────────────────────────────────────────

def delete_sub_questions_for_paper(db_path: str, paper_id: int) -> None:
    """Remove all sub_questions for a paper (used before force re-insert)."""
    conn = get_conn(db_path)
    conn.execute("DELETE FROM sub_questions WHERE paper_id=?", (paper_id,))
    conn.commit()
    conn.close()


def insert_sub_questions(db_path: str, paper_id: int, sub_qs: list[dict]) -> list[int]:
    """Bulk insert sub_questions. Returns list of inserted ids."""
    conn = get_conn(db_path)
    ids = []
    for q in sub_qs:
        cur = conn.execute(
            """INSERT INTO sub_questions
               (paper_id, module_no, q_no, sub_q, is_or_alt, text, marks, bloom_level, course_outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (paper_id, q["module_no"], q["q_no"], q["sub_q"], q["is_or_alt"],
             q["text"], q.get("marks"), q.get("bloom_level"), q.get("course_outcome")),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return ids


def get_sub_questions_for_module(db_path: str, subject_code: str, module_no: int) -> list[dict]:
    """All sub_questions for a given subject+module across all papers."""
    conn = get_conn(db_path)
    rows = conn.execute(
        """SELECT sq.*, p.year, p.month, p.subject_code
           FROM sub_questions sq
           JOIN papers p ON sq.paper_id = p.id
           WHERE p.subject_code = ? AND sq.module_no = ?
           ORDER BY p.year DESC""",
        (subject_code, module_no),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_sub_questions(db_path: str, subject_code: str) -> list[dict]:
    conn = get_conn(db_path)
    rows = conn.execute(
        """SELECT sq.*, p.year, p.month, p.subject_code
           FROM sub_questions sq
           JOIN papers p ON sq.paper_id = p.id
           WHERE p.subject_code = ?
           ORDER BY sq.module_no, p.year DESC""",
        (subject_code,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Canonical questions ─────────────────────────────────────────────────────────

def upsert_canonical(db_path: str, canonical: dict) -> int:
    """Insert or update a canonical question. Returns id."""
    conn = get_conn(db_path)
    existing = conn.execute(
        "SELECT id FROM canonical_questions WHERE id=?", (canonical.get("id", -1),)
    ).fetchone()

    if existing:
        conn.execute(
            """UPDATE canonical_questions
               SET representative_text=?, topic_label=?, avg_marks=?,
                   frequency=?, weighted_score=?, last_seen_year=?
               WHERE id=?""",
            (canonical["representative_text"], canonical.get("topic_label"),
             canonical.get("avg_marks"), canonical.get("frequency", 0),
             canonical.get("weighted_score", 0.0), canonical.get("last_seen_year"),
             canonical["id"]),
        )
        cid = canonical["id"]
    else:
        cur = conn.execute(
            """INSERT INTO canonical_questions
               (subject_code, module_no, representative_text, topic_label,
                avg_marks, frequency, weighted_score, last_seen_year)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (canonical["subject_code"], canonical["module_no"],
             canonical["representative_text"], canonical.get("topic_label"),
             canonical.get("avg_marks"), canonical.get("frequency", 0),
             canonical.get("weighted_score", 0.0), canonical.get("last_seen_year")),
        )
        cid = cur.lastrowid

    conn.commit()
    conn.close()
    return cid


def get_canonicals_for_module(db_path: str, subject_code: str, module_no: int) -> list[dict]:
    conn = get_conn(db_path)
    rows = conn.execute(
        """SELECT * FROM canonical_questions
           WHERE subject_code=? AND module_no=?
           ORDER BY weighted_score DESC""",
        (subject_code, module_no),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_canonicals(db_path: str, subject_code: str) -> list[dict]:
    conn = get_conn(db_path)
    rows = conn.execute(
        """SELECT * FROM canonical_questions
           WHERE subject_code=?
           ORDER BY module_no, weighted_score DESC""",
        (subject_code,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_distinct_subjects(db_path: str) -> list[dict]:
    conn = get_conn(db_path)
    rows = conn.execute(
        """SELECT DISTINCT subject_code, subject_name,
                  COUNT(*) as paper_count,
                  MIN(year) as min_year,
                  MAX(year) as max_year
           FROM papers
           GROUP BY subject_code
           ORDER BY subject_code"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Appearances ─────────────────────────────────────────────────────────────────

def insert_appearance(db_path: str, appearance: dict) -> None:
    conn = get_conn(db_path)
    conn.execute(
        """INSERT OR IGNORE INTO appearances
           (canonical_id, sub_question_id, paper_id, year, q_no, sub_q, marks)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (appearance["canonical_id"], appearance["sub_question_id"],
         appearance["paper_id"], appearance.get("year"),
         appearance.get("q_no"), appearance.get("sub_q"), appearance.get("marks")),
    )
    conn.commit()
    conn.close()


def get_appearances_for_canonical(db_path: str, canonical_id: int) -> list[dict]:
    conn = get_conn(db_path)
    rows = conn.execute(
        """SELECT a.*, p.filename, p.month
           FROM appearances a
           JOIN papers p ON a.paper_id = p.id
           WHERE a.canonical_id=?
           ORDER BY a.year DESC""",
        (canonical_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_paper(db_path: str, paper_id: int) -> str:
    """
    Delete a paper and all its sub_questions from the DB.
    Returns the subject_code so the caller can re-run analysis.
    Canonical questions for that subject are also wiped so the next
    pipeline run rebuilds them from the remaining papers.
    """
    conn = get_conn(db_path)
    row = conn.execute(
        "SELECT subject_code FROM papers WHERE id=?", (paper_id,)
    ).fetchone()
    subject_code = dict(row)["subject_code"] if row else ""

    conn.execute(
        "DELETE FROM sub_questions WHERE paper_id=?", (paper_id,)
    )
    conn.execute("DELETE FROM papers WHERE id=?", (paper_id,))

    # Wipe canonicals for that subject so re-analysis is triggered on next upload
    if subject_code:
        conn.execute(
            "DELETE FROM appearances WHERE canonical_id IN "
            "(SELECT id FROM canonical_questions WHERE subject_code=?)",
            (subject_code,),
        )
        conn.execute(
            "DELETE FROM canonical_questions WHERE subject_code=?", (subject_code,)
        )

    conn.commit()
    conn.close()
    return subject_code


def clear_all_data(db_path: str) -> None:
    """Wipe every table — full reset."""
    conn = get_conn(db_path)
    conn.executescript("""
        DELETE FROM appearances;
        DELETE FROM canonical_questions;
        DELETE FROM sub_questions;
        DELETE FROM papers;
    """)
    conn.commit()
    conn.close()


def delete_canonicals_for_subject(db_path: str, subject_code: str) -> None:
    """Remove all canonical questions + appearances for a subject (before re-dedup)."""
    conn = get_conn(db_path)
    conn.execute(
        "DELETE FROM appearances WHERE canonical_id IN "
        "(SELECT id FROM canonical_questions WHERE subject_code=?)",
        (subject_code,),
    )
    conn.execute(
        "DELETE FROM canonical_questions WHERE subject_code=?", (subject_code,)
    )
    conn.commit()
    conn.close()
