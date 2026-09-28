"""
main.py — the HTTP API.

  Public, read-only (served from precomputed snapshots, no heavy work):
    GET  /healthz                              keep-alive ping target
    GET  /api/stats · /api/subjects · /api/catalog · /api/recent
    GET  /api/subjects/{code}                  everything the subject page needs
    GET  /api/subjects/{code}/cheatsheet.pdf · /questions.csv
  Uploads (anyone, rate-limited, bot-checked):
    POST /api/uploads                          → {id, token}
    GET  /api/uploads/{id}                     status, needs X-Upload-Token
    POST /api/uploads/{id}/confirm             uploader confirms subject + session
  Moderation (require_admin):
    /api/admin/...

Run locally:  uvicorn server.main:app --reload
"""

import json
import logging
import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, select

from modules import embedder
from server import catalog, ingest
from server.auth import require_admin
from server.config import settings
from server.db import blocked_uploaders, engine, init_db, papers, sub_questions, subject_snapshots
from server.security import hash_ip, looks_like_pdf, token_matches, upload_limiter, verify_turnstile
from server.worker import worker

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    worker.start()
    # Load the embedding model in the background so the first upload isn't slow
    threading.Thread(target=embedder.warm_up, daemon=True).start()
    yield


app = FastAPI(title="Papers Please API", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Upload-Token"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def client_ip(request: Request) -> str:
    # Behind Render's proxy the real client is the last hop it appended.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _cached(content: str | bytes, media_type: str, max_age: int = 60, **headers) -> Response:
    return Response(content, media_type=media_type, headers={
        "Cache-Control": f"public, max-age={max_age}, s-maxage={max_age * 5}", **headers})


def _code_or_404(code: str) -> str:
    norm = catalog.normalize_code(code)
    if not norm:
        raise HTTPException(404, "No such subject.")
    return norm


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"ok": True}


# ── Public reads ───────────────────────────────────────────────────────────────

@app.get("/api/stats")
def stats():
    with engine.connect() as conn:
        live = conn.execute(select(func.count()).select_from(papers).where(papers.c.status == "approved")).scalar()
        subjects = conn.execute(select(func.count()).select_from(subject_snapshots)).scalar()
        updated = conn.execute(select(func.max(subject_snapshots.c.updated_at))).scalar()
    return {"papers": live, "subjects": subjects, "updatedAt": updated.isoformat() if updated else None}


@app.get("/api/subjects")
def list_subjects():
    with engine.connect() as conn:
        rows = conn.execute(select(
            subject_snapshots.c.subject_code, subject_snapshots.c.subject_name, subject_snapshots.c.paper_count,
            subject_snapshots.c.topic_count, subject_snapshots.c.min_year, subject_snapshots.c.max_year,
            subject_snapshots.c.updated_at,
        )).all()
    return [
        {"code": r.subject_code, "name": r.subject_name, "branch": catalog.branch_of(r.subject_code),
         "semester": catalog.semester_of(r.subject_code), "paperCount": r.paper_count,
         "topicCount": r.topic_count, "minYear": r.min_year, "maxYear": r.max_year,
         "updatedAt": r.updated_at.isoformat() if r.updated_at else None}
        for r in rows
    ]


@app.get("/api/catalog")
def list_catalog():
    return catalog.catalog()


@app.get("/api/recent")
def recent(limit: int = 6):
    limit = max(1, min(limit, 20))
    with engine.connect() as conn:
        rows = conn.execute(
            select(papers).where(papers.c.status == "approved")
            .order_by(papers.c.reviewed_at.desc()).limit(limit)
        ).mappings().all()
    return [
        {"code": r["subject_code"], "name": r["subject_name"],
         "label": catalog.session_label(r["paper_type"], r["exam_month"], r["exam_year"]),
         "addedAt": r["reviewed_at"].isoformat() if r["reviewed_at"] else None}
        for r in rows
    ]


def _snapshot(code: str, column):
    with engine.connect() as conn:
        value = conn.execute(select(column).where(subject_snapshots.c.subject_code == code)).scalar()
    if value is None:
        raise HTTPException(404, "No papers have been published for this subject yet.")
    return value


@app.get("/api/subjects/{code}")
def subject(code: str):
    return _cached(_snapshot(_code_or_404(code), subject_snapshots.c.data), "application/json")


@app.get("/api/subjects/{code}/cheatsheet.pdf")
def cheatsheet(code: str):
    code = _code_or_404(code)
    return _cached(_snapshot(code, subject_snapshots.c.cheatsheet_pdf), "application/pdf", max_age=300,
                   **{"Content-Disposition": f'attachment; filename="{code}_cheat_sheet.pdf"'})


@app.get("/api/subjects/{code}/questions.csv")
def questions_csv(code: str):
    code = _code_or_404(code)
    return _cached(_snapshot(code, subject_snapshots.c.questions_csv), "text/csv", max_age=300,
                   **{"Content-Disposition": f'attachment; filename="{code}_question_bank.csv"'})


# ── Uploads ────────────────────────────────────────────────────────────────────

def _upload_view(paper: dict) -> dict:
    """What the uploader sees about their own upload."""
    preview, per_module = [], {}
    if paper["status"] in ("awaiting_confirmation", "review", "approved", "processing"):
        with engine.connect() as conn:
            for q in conn.execute(select(sub_questions).where(sub_questions.c.paper_id == paper["id"])
                                  .order_by(sub_questions.c.module_no, sub_questions.c.q_no)).mappings():
                per_module.setdefault(q["module_no"], q)
        preview = [
            {"module": q["module_no"], "where": f"Q{q['q_no']}{q['sub_q']}", "marks": q["marks"], "text": q["text"]}
            for q in list(per_module.values())[:3]
        ]
    return {
        "id": paper["id"],
        "filename": paper["filename"],
        "status": paper["status"],
        "stage": paper["stage"],
        "reason": paper["status_reason"],
        "detected": json.loads(paper["detected"]) if paper["detected"] else None,
        "subjectCode": paper["subject_code"],
        "subjectName": paper["subject_name"],
        "examYear": paper["exam_year"],
        "examMonth": paper["exam_month"],
        "paperType": paper["paper_type"],
        "pageCount": paper["page_count"],
        "questionCount": paper["question_count"],
        "modulesFound": paper["modules_found"],
        "preview": preview,
    }


@app.post("/api/uploads", status_code=201)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    turnstile_token: str | None = Form(default=None, alias="cf-turnstile-response"),
):
    ip = client_ip(request)
    uploader = hash_ip(ip)
    with engine.connect() as conn:
        if conn.execute(select(blocked_uploaders).where(blocked_uploaders.c.uploader_hash == uploader)).first():
            raise HTTPException(403, "Uploads from this connection have been blocked.")
    if not upload_limiter.allow(uploader):
        raise HTTPException(429, "Too many uploads — try again in an hour.")
    if not await verify_turnstile(turnstile_token, ip):
        raise HTTPException(400, "Please complete the human check and try again.")

    limit = settings.max_upload_bytes
    declared = int(request.headers.get("content-length") or 0)
    if declared > limit + 64 * 1024:
        raise HTTPException(413, f"Files must be under {settings.max_upload_mb} MB.")
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Files must be under {settings.max_upload_mb} MB.")
    if not data or not looks_like_pdf(data):
        raise HTTPException(415, "Only PDF files can be uploaded.")

    try:
        pid, token = ingest.create_upload(data, file.filename or "upload.pdf", uploader)
    except ingest.DuplicateUpload as dup:
        status = dup.paper["status"]
        msg = {
            "approved": "This exact file is already in the bank — thanks anyway!",
            "rejected": "This exact file was checked before and couldn't be used.",
        }.get(status, "This exact file has already been uploaded and is being checked.")
        return JSONResponse({"duplicate": True, "status": status, "message": msg}, status_code=409)
    worker.process(pid)
    return {"id": pid, "token": token}


def _own_paper(pid: int, token: str) -> dict:
    paper = ingest.get_paper(pid)
    if not paper or not token_matches(token, paper["upload_token_hash"]):
        raise HTTPException(404, "Upload not found.")
    return paper


@app.get("/api/uploads/{pid}")
def upload_status(pid: int, x_upload_token: str = Header(default="")):
    return _upload_view(_own_paper(pid, x_upload_token))


class ConfirmBody(BaseModel):
    subjectCode: str = Field(max_length=16)
    examYear: int | None = None
    examMonth: str | None = Field(default=None, max_length=16)
    paperType: Literal["see", "model"] = "see"


@app.post("/api/uploads/{pid}/confirm")
def confirm(pid: int, body: ConfirmBody, x_upload_token: str = Header(default="")):
    _own_paper(pid, x_upload_token)
    try:
        ingest.confirm_paper(pid, body.subjectCode, body.examYear, body.examMonth, body.paperType)
    except ingest.ActionError as e:
        raise HTTPException(400, str(e))
    worker.match(pid)
    return _upload_view(ingest.get_paper(pid))


# ── Moderation ─────────────────────────────────────────────────────────────────

def _admin_row(p: dict) -> dict:
    return {
        "id": p["id"], "filename": p["filename"], "status": p["status"], "stage": p["stage"],
        "reason": p["status_reason"], "subjectCode": p["subject_code"], "subjectName": p["subject_name"],
        "examYear": p["exam_year"], "examMonth": p["exam_month"], "paperType": p["paper_type"],
        "session": catalog.session_label(p["paper_type"], p["exam_month"], p["exam_year"]),
        "pdfType": p["pdf_type"], "pageCount": p["page_count"], "questionCount": p["question_count"],
        "modulesFound": p["modules_found"], "uploader": p["uploader_hash"], "reviewedBy": p["reviewed_by"],
        "createdAt": p["created_at"].isoformat() if p["created_at"] else None,
    }


@app.get("/api/admin/me")
def admin_me(who: str = Depends(require_admin)):
    return {"user": who, "counts": ingest.counts()}


@app.get("/api/admin/papers")
def admin_papers(status: str | None = None, subject: str | None = None, who: str = Depends(require_admin)):
    q = select(papers).order_by(papers.c.created_at.desc()).limit(500)
    if status:
        q = q.where(papers.c.status == status)
    if subject:
        q = q.where(papers.c.subject_code == subject.upper())
    with engine.connect() as conn:
        return [_admin_row(dict(r)) for r in conn.execute(q).mappings()]


@app.get("/api/admin/papers/{pid}")
def admin_paper(pid: int, who: str = Depends(require_admin)):
    paper = ingest.get_paper(pid)
    if not paper:
        raise HTTPException(404, "No such paper.")
    with engine.connect() as conn:
        qs = conn.execute(select(sub_questions).where(sub_questions.c.paper_id == pid)
                          .order_by(sub_questions.c.module_no, sub_questions.c.q_no, sub_questions.c.sub_q)).mappings().all()
        clash = None
        if paper["session_key"]:
            clash = conn.execute(select(papers).where(
                papers.c.session_key == paper["session_key"], papers.c.status == "approved",
                papers.c.id != pid)).mappings().first()

    comparison = None
    if paper["status"] != "approved" and qs:
        if clash:
            against = dict(clash)
        else:
            best = ingest.best_match(pid)
            against = ingest.get_paper(best["paper_id"]) if best else None
        if against:
            comparison = {"against": _admin_row(against), **ingest.compare_papers(pid, against["id"])}

    return {
        **_admin_row(paper),
        "detected": json.loads(paper["detected"]) if paper["detected"] else None,
        "questions": [
            {"module": q["module_no"], "where": f"Q{q['q_no']}{q['sub_q']}", "marks": q["marks"], "text": q["text"]}
            for q in qs
        ],
        "comparison": comparison,
    }


def _action(fn, *args):
    try:
        return fn(*args)
    except ingest.ActionError as e:
        raise HTTPException(400, str(e))


@app.post("/api/admin/papers/{pid}/approve")
def admin_approve(pid: int, who: str = Depends(require_admin)):
    _action(ingest.approve, pid, who)
    worker.publish(ingest.get_paper(pid)["subject_code"], pid)
    return _admin_row(ingest.get_paper(pid))


class RejectBody(BaseModel):
    reason: str = Field(default="", max_length=500)


@app.post("/api/admin/papers/{pid}/reject")
def admin_reject(pid: int, body: RejectBody, who: str = Depends(require_admin)):
    code = _action(ingest.reject, pid, who, body.reason)
    if code:
        worker.publish(code)
    return _admin_row(ingest.get_paper(pid))


class ReplaceBody(BaseModel):
    replaces: int


@app.post("/api/admin/papers/{pid}/replace")
def admin_replace(pid: int, body: ReplaceBody, who: str = Depends(require_admin)):
    _action(ingest.replace, pid, body.replaces, who)
    worker.publish(ingest.get_paper(pid)["subject_code"], pid)
    return _admin_row(ingest.get_paper(pid))


@app.post("/api/admin/papers/{pid}/reprocess")
def admin_reprocess(pid: int, who: str = Depends(require_admin)):
    _action(ingest.reprocess, pid)
    worker.process(pid)
    return _admin_row(ingest.get_paper(pid))


class EditBody(BaseModel):
    subjectCode: str = Field(max_length=16)
    examYear: int | None = None
    examMonth: str | None = Field(default=None, max_length=16)
    paperType: Literal["see", "model"] = "see"


@app.patch("/api/admin/papers/{pid}")
def admin_edit(pid: int, body: EditBody, who: str = Depends(require_admin)):
    paper = ingest.get_paper(pid)
    if not paper:
        raise HTTPException(404, "No such paper.")
    if paper["status"] == "approved":
        raise HTTPException(400, "Reject the live paper before editing it.")
    code = catalog.normalize_code(body.subjectCode)
    if not code:
        raise HTTPException(400, "That doesn't look like a VTU subject code.")
    if body.examMonth and body.examMonth not in catalog.MONTHS:
        raise HTTPException(400, "Unknown month.")
    month, year = catalog.normalize_session(body.examMonth, body.examYear)
    ingest._set(pid, subject_code=code, subject_name=catalog.subject_name(code) or paper["subject_name"] or code,
                exam_year=year, exam_month=month if body.paperType == "see" else None, paper_type=body.paperType,
                session_key=catalog.session_key(code, body.paperType, month, year))
    return _admin_row(ingest.get_paper(pid))


@app.delete("/api/admin/papers/{pid}")
def admin_delete(pid: int, who: str = Depends(require_admin)):
    code = _action(ingest.delete_paper, pid)
    if code:
        worker.publish(code)
    return {"deleted": pid}


class BlockBody(BaseModel):
    reason: str = Field(default="", max_length=500)


@app.post("/api/admin/uploaders/{uploader}/block")
def admin_block(uploader: str, body: BlockBody, who: str = Depends(require_admin)):
    with engine.begin() as conn:
        conn.execute(delete(blocked_uploaders).where(blocked_uploaders.c.uploader_hash == uploader))
        conn.execute(insert(blocked_uploaders).values(uploader_hash=uploader[:64], reason=body.reason, blocked_by=who))
    return {"blocked": uploader}


@app.post("/api/admin/subjects/{code}/rebuild")
def admin_rebuild(code: str, who: str = Depends(require_admin)):
    worker.publish(_code_or_404(code))
    return {"queued": code.upper()}
