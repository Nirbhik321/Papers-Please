"""Upload safety: every hostile or junk file must be refused without touching live data."""

from server.tests.conftest import ADMIN, make_pdf, upload


def status(client, created):
    body = created.json()
    return client.get(f"/api/uploads/{body['id']}", headers={"X-Upload-Token": body["token"]}).json()


def test_health(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_rejects_non_pdf(client):
    r = upload(client, b"MZ\x90\x00 definitely an exe", "paper.pdf")
    assert r.status_code == 415


def test_rejects_oversized_file(client):
    r = upload(client, b"%PDF-1.7\n" + b"0" * (11 * 1024 * 1024))
    assert r.status_code == 413


def test_rejects_encrypted_pdf(client, drain):
    created = upload(client, make_pdf(encrypt=True))
    assert created.status_code == 201
    drain()
    s = status(client, created)
    assert s["status"] == "rejected"
    assert "Password" in s["reason"]


def test_rejects_too_many_pages(client, drain):
    created = upload(client, make_pdf(pages=9, text="page"))
    drain()
    s = status(client, created)
    assert s["status"] == "rejected"
    assert "9 pages" in s["reason"]


def test_rejects_oversized_pages(client, drain):
    created = upload(client, make_pdf(size=(5000, 5000), text="poster"))
    drain()
    assert status(client, created)["status"] == "rejected"


def test_rejects_pdf_that_is_not_a_question_paper(client, drain):
    created = upload(client, make_pdf(pages=2, text="My lab record, nothing to see"))
    drain()
    s = status(client, created)
    assert s["status"] == "rejected"
    assert "doesn't look like a VTU question paper" in s["reason"]


def test_exact_duplicate_is_answered_without_reprocessing(client):
    data = make_pdf(text="duplicate me")
    assert upload(client, data).status_code == 201
    again = upload(client, data, "renamed-copy.pdf")
    assert again.status_code == 409
    assert again.json()["duplicate"] is True


def test_status_needs_the_uploaders_token(client):
    created = upload(client, make_pdf(text="token check")).json()
    assert client.get(f"/api/uploads/{created['id']}").status_code == 404
    assert client.get(f"/api/uploads/{created['id']}", headers={"X-Upload-Token": "guess"}).status_code == 404


def test_hostile_filename_is_neutralised(client, drain):
    created = upload(client, make_pdf(text="path"), "../../etc/passwd\x00.pdf")
    s = status(client, created)
    assert "/" not in s["filename"] and ".." not in s["filename"].split("_")[0]
    rows = client.get("/api/admin/papers", headers=ADMIN).json()
    row = next(r for r in rows if r["id"] == created.json()["id"])
    assert row["filename"] == s["filename"]


def test_admin_api_requires_auth(client):
    assert client.get("/api/admin/papers").status_code == 401
    assert client.get("/api/admin/papers", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/admin/papers", headers=ADMIN).status_code == 200


def test_rate_limit(client, monkeypatch):
    from server import main
    from server.security import RateLimiter
    monkeypatch.setattr(main, "upload_limiter", RateLimiter(2, 3600))
    upload(client, make_pdf(text="rl1"))
    upload(client, make_pdf(text="rl2"))
    assert upload(client, make_pdf(text="rl3")).status_code == 429


def test_blocked_uploader(client, monkeypatch):
    from server.security import hash_ip
    client.post(f"/api/admin/uploaders/{hash_ip('testclient')}/block", json={"reason": "spam"}, headers=ADMIN)
    try:
        assert upload(client, make_pdf(text="blocked")).status_code == 403
    finally:
        from sqlalchemy import delete
        from server.db import blocked_uploaders, engine
        with engine.begin() as conn:
            conn.execute(delete(blocked_uploaders))


def test_keepalive_touches_the_database(client):
    assert client.get("/api/keepalive").json() == {"ok": True}
