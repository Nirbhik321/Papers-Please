"""
ingest.py — the life of an upload, from file to live data.

  create_upload   quick checks passed → store file, create a 'processing' paper
  process_paper   sandboxed extraction → reject non-papers, else ask the uploader to confirm
  confirm_paper   uploader fixes subject/session → queue matching
  match_paper     duplicate + sanity checks → auto-approve, or send to moderator review
  approve/reject/replace/delete/reprocess   moderator actions

Every change to what's live ends with the subject being republished.
"""

import json
import re
import tempfile
from pathlib import Path

import numpy as np
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from modules import detector, embedder
from server import catalog
from server.config import settings
from server.db import engine, papers, sub_questions, utcnow
from server.sandbox import ExtractionError, run_extraction
from server.security import display_filename, new_upload_token, sha256_hex
from server.storage import key_for, storage

DUPLICATE_THRESHOLD = 0.90     # share of questions matching → "same paper"
MIN_QUESTIONS, MIN_MODULES = 5, 3     # below this it isn't a question paper at all
GOOD_QUESTIONS, GOOD_MODULES = 8, 4   # below this a human should look


class DuplicateUpload(Exception):
    def __init__(self, paper: dict):
        self.paper = paper


class ActionError(Exception):
    """A moderator/uploader action that isn't allowed in the paper's current state."""


def get_paper(pid: int) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(select(papers).where(papers.c.id == pid)).mappings().first()
    return dict(row) if row else None


def _set(pid: int, **values) -> None:
    with engine.begin() as conn:
        conn.execute(update(papers).where(papers.c.id == pid).values(**values, updated_at=utcnow()))


def _questions(pid: int) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(sub_questions).where(sub_questions.c.paper_id == pid)
            .order_by(sub_questions.c.module_no, sub_questions.c.q_no, sub_questions.c.sub_q)
        ).mappings().all()
    return [dict(r) for r in rows]


# ── Upload ─────────────────────────────────────────────────────────────────────

def create_upload(data: bytes, filename: str, uploader_hash: str | None) -> tuple[int, str]:
    content_hash = sha256_hex(data)
    with engine.connect() as conn:
        existing = conn.execute(select(papers).where(papers.c.content_hash == content_hash)).mappings().first()
    if existing:
        raise DuplicateUpload(dict(existing))

    key = key_for(content_hash)
    storage.put(key, data)
    token, token_hash = new_upload_token()
    with engine.begin() as conn:
        pid = conn.execute(insert(papers).values(
            status="processing", stage="queued", filename=display_filename(filename),
            content_hash=content_hash, storage_key=key, upload_token_hash=token_hash,
            uploader_hash=uploader_hash, created_at=utcnow(), updated_at=utcnow(),
        )).inserted_primary_key[0]
    return pid, token


# ── Extraction ─────────────────────────────────────────────────────────────────

def process_paper(pid: int) -> None:
    paper = get_paper(pid)
    if not paper or paper["status"] != "processing":
        return
    _set(pid, stage="reading")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "upload.pdf"
            path.write_bytes(storage.get(paper["storage_key"]))
            result = run_extraction(str(path), settings.max_pages, settings.extract_timeout_s)
    except ExtractionError as e:
        _finish_rejected(pid, e.reason, discard_file=e.rejected) if e.rejected else \
            _set(pid, status="failed", stage="done", status_reason=e.reason)
        return

    qs = [q for q in result["sub_questions"] if 1 <= q["module_no"] <= 5]
    modules_found = len({q["module_no"] for q in qs})
    if len(qs) < MIN_QUESTIONS or modules_found < MIN_MODULES:
        _finish_rejected(
            pid,
            "This doesn't look like a VTU question paper — we found "
            f"{len(qs)} question{'s' if len(qs) != 1 else ''} across {modules_found} module"
            f"{'s' if modules_found != 1 else ''}. Nothing from it was saved.",
            discard_file=True,
        )
        return

    detected = _detect_metadata(paper["filename"], result["content_meta"])
    with engine.begin() as conn:
        conn.execute(delete(sub_questions).where(sub_questions.c.paper_id == pid))
        conn.execute(insert(sub_questions), [
            {"paper_id": pid, "module_no": q["module_no"], "q_no": q["q_no"], "sub_q": q["sub_q"],
             "is_or_alt": q["is_or_alt"], "text": " ".join(q["text"].split())[:2000], "marks": q.get("marks"),
             "bloom_level": q.get("bloom_level"), "course_outcome": q.get("course_outcome")}
            for q in qs
        ])
        conn.execute(update(papers).where(papers.c.id == pid).values(
            status="awaiting_confirmation", stage="confirm", detected=json.dumps(detected),
            subject_code=detected["subjectCode"], subject_name=detected["subjectName"],
            exam_year=detected["examYear"], exam_month=detected["examMonth"],
            paper_type=detected["paperType"], pdf_type=result["pdf_type"],
            page_count=result["page_count"], question_count=len(qs),
            modules_found=modules_found, updated_at=utcnow(),
        ))


def _finish_rejected(pid: int, reason: str, discard_file: bool) -> None:
    paper = get_paper(pid)
    if discard_file and paper:
        try:
            storage.delete(paper["storage_key"])   # keep the hash so a re-upload is answered instantly
        except Exception:
            pass
    _set(pid, status="rejected", stage="done", status_reason=reason)


_MODEL_HINT = re.compile(r"\b(model|mqp|sample)\b", re.IGNORECASE)


def _detect_metadata(filename: str, content_meta: dict) -> dict:
    name_meta = detector.parse_filename_metadata(filename)
    # An explicit code in the filename beats a code guessed from the subject title
    # (the same title, e.g. "Computer Networks", exists under several branches).
    code = name_meta["subject_code"] if name_meta["subject_code"] != "UNKNOWN" else content_meta.get("subject_code")
    code = catalog.normalize_code(code or "") or None
    month, year = catalog.normalize_session(
        name_meta["month"] or content_meta.get("month"), name_meta["year"] or content_meta.get("year"))
    is_model = (_MODEL_HINT.search(filename.replace("_", " "))
                or "mqp" in (name_meta.get("exam_type"), content_meta.get("exam_type")))
    paper_type = "model" if is_model else "see"
    return {
        "subjectCode": code,
        "subjectName": catalog.subject_name(code) if code else None,
        "examYear": year,
        "examMonth": month,
        "paperType": paper_type,
    }


# ── Confirmation by the uploader ───────────────────────────────────────────────

def confirm_paper(pid: int, subject_code: str, exam_year: int | None, exam_month: str | None, paper_type: str) -> None:
    paper = get_paper(pid)
    if not paper or paper["status"] != "awaiting_confirmation":
        raise ActionError("This upload isn't waiting for confirmation.")
    code = catalog.normalize_code(subject_code)
    if not code:
        raise ActionError("That doesn't look like a VTU subject code (e.g. BCS502).")
    if paper_type not in ("see", "model"):
        raise ActionError("Unknown paper type.")
    this_year = utcnow().year
    if paper_type == "see" and not (exam_year and 2015 <= exam_year <= this_year + 1):
        raise ActionError("Pick the exam year.")
    if paper_type == "see" and exam_month not in catalog.MONTHS:
        raise ActionError("Pick the exam month.")
    if exam_year and not (2015 <= exam_year <= this_year + 1):
        raise ActionError("That year doesn't look right.")
    month, year = catalog.normalize_session(exam_month, exam_year)

    _set(pid, status="processing", stage="matching", subject_code=code,
         subject_name=catalog.subject_name(code) or paper["subject_name"] or code,
         exam_year=year, exam_month=month if paper_type == "see" else None, paper_type=paper_type,
         session_key=catalog.session_key(code, paper_type, month, year))


def match_paper(pid: int) -> None:
    """Decide: publish automatically, or hold for a moderator."""
    paper = get_paper(pid)
    if not paper or paper["status"] != "processing" or paper["stage"] != "matching":
        return
    code = paper["subject_code"]
    reasons = []

    if not catalog.is_known(code):
        reasons.append(f"{code} isn't in our subject list yet.")
    if (paper["question_count"] or 0) < GOOD_QUESTIONS or (paper["modules_found"] or 0) < GOOD_MODULES:
        reasons.append(f"Only {paper['question_count']} questions in {paper['modules_found']} of 5 modules "
                       "were found — possibly a partial or unclear scan.")

    same_session = None
    if paper["session_key"]:
        with engine.connect() as conn:
            same_session = conn.execute(select(papers.c.id).where(
                papers.c.session_key == paper["session_key"], papers.c.status == "approved",
                papers.c.id != pid)).first()
        if same_session:
            label = catalog.session_label("see", paper["exam_month"], paper["exam_year"])
            reasons.append(f"We already have the {label} paper for {code}.")

    match = best_match(pid)
    if match and match["score"] >= DUPLICATE_THRESHOLD and not same_session:
        reasons.append(f"{round(match['score'] * 100)}% of its questions match a live paper "
                       f"({match['label']}) — probably the same paper.")

    if reasons:
        _set(pid, status="review", stage="done", status_reason=" ".join(reasons))
        return
    try:
        _set(pid, status="approved", stage="publishing", reviewed_by="auto", reviewed_at=utcnow(),
             status_reason=None)
    except IntegrityError:   # another copy of the session went live a moment ago
        _set(pid, status="review", stage="done", status_reason="Another paper for this session just went live.")
        return
    publish(pid, code)


def publish(pid: int | None, code: str) -> None:
    from server.analysis import rebuild_subject
    rebuild_subject(code)
    if pid:
        _set(pid, stage="done")


# ── Duplicate detection ────────────────────────────────────────────────────────

def compare_papers(pid_a: int, pid_b: int) -> dict:
    """How much of paper A appears in paper B, question by question."""
    a, b = _questions(pid_a), _questions(pid_b)
    if not a or not b:
        return {"score": 0.0, "pairs": []}
    sims = embedder.cosine_similarity_matrix(embedder.encode([q["text"] for q in a]),
                                             embedder.encode([q["text"] for q in b]))
    best = sims.argmax(axis=1)
    pairs = [
        {"a": {"where": f"Q{qa['q_no']}{qa['sub_q']}", "text": qa["text"]},
         "b": {"where": f"Q{b[j]['q_no']}{b[j]['sub_q']}", "text": b[j]["text"]},
         "similarity": round(float(sims[i, j]), 3)}
        for i, (qa, j) in enumerate(zip(a, best))
    ]
    score = float(np.mean([p["similarity"] >= 0.85 for p in pairs]))
    return {"score": round(score, 3), "pairs": pairs}


def best_match(pid: int) -> dict | None:
    """The live paper of the same subject most similar to this one."""
    paper = get_paper(pid)
    with engine.connect() as conn:
        others = conn.execute(select(papers).where(
            papers.c.subject_code == paper["subject_code"], papers.c.status == "approved",
            papers.c.id != pid)).mappings().all()
    best = None
    for other in others:
        result = compare_papers(pid, other["id"])
        if not best or result["score"] > best["score"]:
            best = {"paper_id": other["id"], "score": result["score"],
                    "label": catalog.session_label(other["paper_type"], other["exam_month"], other["exam_year"])}
    return best


# ── Moderator actions ──────────────────────────────────────────────────────────

def approve(pid: int, by: str) -> None:
    paper = get_paper(pid)
    if not paper or paper["status"] not in ("review", "rejected", "awaiting_confirmation"):
        raise ActionError("Only papers in review (or rejected) can be approved.")
    if not paper["subject_code"]:
        raise ActionError("Set the subject before approving.")
    if not _questions(pid):
        raise ActionError("This paper has no extracted questions — reprocess it first.")
    try:
        _set(pid, status="approved", stage="publishing", reviewed_by=by, reviewed_at=utcnow(), status_reason=None)
    except IntegrityError:
        raise ActionError("Another live paper already covers this exam session — use Replace instead.")


def reject(pid: int, by: str, reason: str) -> str | None:
    paper = get_paper(pid)
    if not paper:
        raise ActionError("No such paper.")
    was_live = paper["status"] == "approved"
    _set(pid, status="rejected", stage="done", reviewed_by=by, reviewed_at=utcnow(),
         status_reason=(reason or "Rejected by a moderator.")[:500])
    return paper["subject_code"] if was_live else None


def replace(new_pid: int, old_pid: int, by: str) -> None:
    new, old = get_paper(new_pid), get_paper(old_pid)
    if not new or not old or old["status"] != "approved":
        raise ActionError("Pick a live paper to replace.")
    if new["subject_code"] != old["subject_code"]:
        raise ActionError("Both papers must be for the same subject.")
    with engine.begin() as conn:
        conn.execute(update(papers).where(papers.c.id == old_pid).values(
            status="rejected", stage="done", status_reason=f"Replaced by upload #{new_pid}.",
            reviewed_by=by, reviewed_at=utcnow(), updated_at=utcnow()))
        conn.execute(update(papers).where(papers.c.id == new_pid).values(
            status="approved", stage="publishing", session_key=old["session_key"],
            exam_year=old["exam_year"], exam_month=old["exam_month"], paper_type=old["paper_type"],
            reviewed_by=by, reviewed_at=utcnow(), status_reason=None, updated_at=utcnow()))


def delete_paper(pid: int) -> str | None:
    paper = get_paper(pid)
    if not paper:
        raise ActionError("No such paper.")
    with engine.begin() as conn:
        conn.execute(delete(papers).where(papers.c.id == pid))
    try:
        storage.delete(paper["storage_key"])
    except Exception:
        pass
    return paper["subject_code"] if paper["status"] == "approved" else None


def reprocess(pid: int) -> None:
    paper = get_paper(pid)
    if not paper:
        raise ActionError("No such paper.")
    if paper["status"] == "approved":
        raise ActionError("Reject the live paper before reprocessing it.")
    with engine.begin() as conn:
        conn.execute(delete(sub_questions).where(sub_questions.c.paper_id == pid))
    _set(pid, status="processing", stage="queued", status_reason=None)


def counts() -> dict:
    with engine.connect() as conn:
        rows = conn.execute(select(papers.c.status, func.count()).group_by(papers.c.status)).all()
    return {status: n for status, n in rows}
