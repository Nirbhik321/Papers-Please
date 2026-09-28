"""
auth.py — who is allowed into the moderation API.

Two ways in, either is enough:
  - ADMIN_TOKEN: a long random shared secret, handy locally and for scripts.
  - A Supabase Auth session whose email is listed in ADMIN_EMAILS. The token
    is checked by asking Supabase who it belongs to (cached for a minute).
Students never need an account.
"""

import hashlib
import hmac
import time

import httpx
from fastapi import Header, HTTPException

from server.config import settings

_cache: dict[str, tuple[float, str]] = {}
_TTL = 60


def _supabase_email(token: str) -> str | None:
    key = hashlib.sha256(token.encode()).hexdigest()
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    try:
        r = httpx.get(f"{settings.supabase_url}/auth/v1/user", timeout=10,
                      headers={"Authorization": f"Bearer {token}", "apikey": settings.supabase_anon_key})
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    email = (r.json().get("email") or "").lower()
    _cache[key] = (time.monotonic(), email)
    return email


def require_admin(authorization: str = Header(default="")) -> str:
    """FastAPI dependency: returns the moderator's name, or raises 401/403."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Sign in to moderate.")
    if settings.admin_token and hmac.compare_digest(token, settings.admin_token):
        return "admin-token"
    if settings.supabase_url and settings.supabase_anon_key:
        email = _supabase_email(token)
        if email and email in settings.admin_emails:
            return email
        if email:
            raise HTTPException(403, "This account isn't a moderator.")
    raise HTTPException(401, "Your session has expired — sign in again.")
