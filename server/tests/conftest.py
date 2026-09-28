"""Test setup: a throwaway SQLite database and storage folder, and a known admin token."""

import io
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="papers-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(_tmp / "storage")
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["TURNSTILE_SECRET_KEY"] = ""
os.environ["SUPABASE_URL"] = ""
os.environ["REVALIDATE_URL"] = ""
os.environ["UPLOADS_PER_HOUR"] = "1000"

import pymupdf  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.db import init_db  # noqa: E402
from server.main import app  # noqa: E402
from server.worker import worker  # noqa: E402

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
ADMIN = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture(scope="session")
def client():
    init_db()
    # No `with`: the app's background worker thread stays off, tests run jobs via drain().
    return TestClient(app)


@pytest.fixture
def drain():
    return worker.drain


def make_pdf(pages: int = 1, text: str = "Hello", encrypt: bool = False, size=(595, 842)) -> bytes:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=size[0], height=size[1])
        page.insert_text((72, 72), f"{text} {i}")
    buf = io.BytesIO()
    if encrypt:
        doc.save(buf, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    else:
        doc.save(buf)
    return buf.getvalue()


def real_paper(name: str) -> bytes:
    path = RAW / name
    if not path.exists():
        pytest.skip(f"sample paper {name} not available (data/ is not committed)")
    return path.read_bytes()


def upload(client, data: bytes, name: str = "paper.pdf"):
    return client.post("/api/uploads", files={"file": (name, data, "application/pdf")})
