"""
db.py — database schema and engine (SQLAlchemy Core).

The same tables work on SQLite (local) and Postgres (Supabase). The Supabase
migration in supabase/migrations mirrors this file and additionally turns on
row-level security so the tables are not reachable through Supabase's public
REST API — only this server (connecting as the database owner) can touch them.

Tables:
  papers           — one row per upload, with its moderation status
  sub_questions    — questions extracted from a paper
  topics           — deduplicated question groups per subject+module
  topic_appearances— which sub_questions belong to which topic
  subject_snapshots— the published, precomputed data for each subject
  blocked_uploaders— pseudonymous uploaders a moderator has blocked
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, MetaData,
    String, Table, Text, create_engine, event, text,
)

from server.config import settings

metadata = MetaData()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Paper lifecycle:
#   processing ─▶ awaiting_confirmation ─▶ processing (matching) ─▶ approved | review
#        └──────▶ rejected (not a paper)                               review ─▶ approved | rejected
#   failed = an internal error; a moderator can reprocess it.
PAPER_STATUSES = ("processing", "awaiting_confirmation", "review", "approved", "rejected", "failed")

papers = Table(
    "papers", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("status", String(24), nullable=False, default="processing"),
    Column("stage", String(24), nullable=False, default="queued"),
    Column("status_reason", Text),
    Column("subject_code", String(16)),
    Column("subject_name", String(200)),
    Column("exam_year", Integer),
    Column("exam_month", String(16)),
    Column("paper_type", String(16), nullable=False, default="see"),   # 'see' = semester-end, 'model'
    Column("session_key", String(64)),
    Column("detected", Text),              # JSON: what the extractor guessed, shown on the confirm step
    Column("filename", String(255), nullable=False),
    Column("content_hash", String(64), nullable=False, unique=True),
    Column("storage_key", String(255), nullable=False),
    Column("pdf_type", String(16)),
    Column("page_count", Integer),
    Column("question_count", Integer),
    Column("modules_found", Integer),
    Column("upload_token_hash", String(64), nullable=False),
    Column("uploader_hash", String(64)),
    Column("reviewed_by", String(255)),
    Column("reviewed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow),
)

# One live paper per exam session (e.g. BCS502 January 2025) — a second upload of the
# same session can never be counted twice, it has to go through review.
Index(
    "uq_papers_live_session", papers.c.session_key, unique=True,
    sqlite_where=text("status = 'approved'"), postgresql_where=text("status = 'approved'"),
)
Index("ix_papers_subject_status", papers.c.subject_code, papers.c.status)

sub_questions = Table(
    "sub_questions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("paper_id", Integer, ForeignKey("papers.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("module_no", Integer, nullable=False),
    Column("q_no", Integer, nullable=False),
    Column("sub_q", String(4), nullable=False),
    Column("is_or_alt", Integer, nullable=False, default=0),
    Column("text", Text, nullable=False),
    Column("marks", Integer),
    Column("bloom_level", String(4)),
    Column("course_outcome", String(8)),
)

topics = Table(
    "topics", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("subject_code", String(16), nullable=False),
    Column("module_no", Integer, nullable=False),
    Column("stable_key", String(16), nullable=False),   # survives rebuilds, so "studied" ticks stick
    Column("label", String(120)),
    Column("representative_text", Text, nullable=False),
    Column("avg_marks", Float),
    Column("frequency", Integer, nullable=False, default=0),
    Column("weighted_score", Float, nullable=False, default=0.0),
    Column("last_seen_year", Integer),
)
Index("ix_topics_subject_module", topics.c.subject_code, topics.c.module_no)

topic_appearances = Table(
    "topic_appearances", metadata,
    Column("topic_id", Integer, ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
    Column("sub_question_id", Integer, ForeignKey("sub_questions.id", ondelete="CASCADE"), primary_key=True),
)

subject_snapshots = Table(
    "subject_snapshots", metadata,
    Column("subject_code", String(16), primary_key=True),
    Column("subject_name", String(200), nullable=False),
    Column("paper_count", Integer, nullable=False),
    Column("topic_count", Integer, nullable=False),
    Column("min_year", Integer),
    Column("max_year", Integer),
    Column("data", Text, nullable=False),            # JSON served as-is to the website
    Column("cheatsheet_pdf", LargeBinary),
    Column("questions_csv", Text),
    Column("updated_at", DateTime(timezone=True), nullable=False, default=utcnow),
)


blocked_uploaders = Table(
    "blocked_uploaders", metadata,
    Column("uploader_hash", String(64), primary_key=True),
    Column("reason", Text),
    Column("blocked_by", String(255)),
    Column("created_at", DateTime(timezone=True), nullable=False, default=utcnow),
)


def _make_engine():
    url = settings.database_url
    if url.startswith("sqlite"):
        from pathlib import Path
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
        return eng
    # Small pool: Render free has one process; Supabase free allows limited connections.
    return create_engine(url, pool_size=3, max_overflow=2, pool_pre_ping=True)


engine = _make_engine()


def init_db() -> None:
    metadata.create_all(engine)
    if engine.dialect.name == "postgresql":
        # Same guarantee as the Supabase migration, in case tables were created here:
        # without RLS, Supabase's public REST API could read these tables.
        with engine.begin() as conn:
            for table in metadata.sorted_tables:
                conn.execute(text(f'alter table "{table.name}" enable row level security'))
