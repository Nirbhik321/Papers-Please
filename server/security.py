"""
security.py — cheap checks that run before an upload is accepted.

Nothing here parses the PDF: anything that does (and could be attacked by a
malicious file) runs in the sandboxed subprocess in sandbox.py.
"""

import hashlib
import hmac
import re
import secrets
import threading
import time
import unicodedata
from collections import defaultdict, deque

import httpx

from server.config import settings


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_ip(ip: str) -> str:
    """Pseudonymous uploader id — lets moderators block/roll back an abuser without storing IPs."""
    return hmac.new(settings.ip_hash_salt.encode(), ip.encode(), hashlib.sha256).hexdigest()[:16]


def new_upload_token() -> tuple[str, str]:
    """(token for the uploader, hash we store). Only the uploader can confirm their upload."""
    token = secrets.token_urlsafe(24)
    return token, sha256_hex(token.encode())


def token_matches(token: str, stored_hash: str) -> bool:
    return bool(token) and hmac.compare_digest(sha256_hex(token.encode()), stored_hash)


_UNSAFE = re.compile(r"[^\w .()\-]+")


def display_filename(name: str) -> str:
    """The uploader's filename, only for display: no paths, no control chars, bounded length."""
    name = unicodedata.normalize("NFKC", name or "").replace("\\", "/").split("/")[-1]
    name = _UNSAFE.sub("_", name).strip(" .") or "upload.pdf"
    return name[-120:]


def looks_like_pdf(data: bytes) -> bool:
    # The PDF header must appear in the first 1 KB (the spec allows a little leading junk).
    return b"%PDF-" in data[:1024]


class RateLimiter:
    """Sliding-window limiter, in memory — fine for a single server process."""

    def __init__(self, limit: int, window_s: int):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


upload_limiter = RateLimiter(settings.uploads_per_hour, 3600)


async def verify_turnstile(token: str | None, ip: str) -> bool:
    """Cloudflare Turnstile bot check. Skipped when no secret is configured (local dev)."""
    if not settings.turnstile_secret:
        return True
    if not token:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={"secret": settings.turnstile_secret, "response": token, "remoteip": ip},
            )
        return bool(r.json().get("success"))
    except Exception:
        return False
