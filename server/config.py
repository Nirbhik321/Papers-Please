"""
config.py — all settings come from environment variables.

Locally everything has a working default (SQLite + files on disk), so
`uvicorn server.main:app` runs with zero setup. In production (Render) the
same code talks to Supabase Postgres and Supabase Storage once the Supabase
variables are set. A `.env` file in the project root is read if present.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader — KEY=VALUE lines, # comments. Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _list(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{(ROOT / 'data' / 'app.db').as_posix()}"
    # Supabase/Render hand out postgres:// or postgresql:// — use the psycopg 3 driver
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_database_url)

    # Storage for original uploads. Local folder unless Supabase is configured.
    storage_dir: Path = field(default_factory=lambda: Path(os.environ.get("STORAGE_DIR", ROOT / "data" / "storage")))
    supabase_url: str = field(default_factory=lambda: os.environ.get("SUPABASE_URL", "").rstrip("/"))
    supabase_service_key: str = field(default_factory=lambda: os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))
    supabase_anon_key: str = field(default_factory=lambda: os.environ.get("SUPABASE_ANON_KEY", ""))
    supabase_bucket: str = field(default_factory=lambda: os.environ.get("SUPABASE_BUCKET", "uploads"))

    # Moderator access: a shared token (local/dev) and/or Supabase-authenticated emails.
    admin_token: str = field(default_factory=lambda: os.environ.get("ADMIN_TOKEN", ""))
    admin_emails: list[str] = field(default_factory=lambda: [e.lower() for e in _list("ADMIN_EMAILS")])

    # Upload protection
    turnstile_secret: str = field(default_factory=lambda: os.environ.get("TURNSTILE_SECRET_KEY", ""))
    max_upload_mb: int = field(default_factory=lambda: int(os.environ.get("MAX_UPLOAD_MB", "10")))
    max_pages: int = field(default_factory=lambda: int(os.environ.get("MAX_PAGES", "6")))
    uploads_per_hour: int = field(default_factory=lambda: int(os.environ.get("UPLOADS_PER_HOUR", "10")))
    extract_timeout_s: int = field(default_factory=lambda: int(os.environ.get("EXTRACT_TIMEOUT_S", "120")))
    ip_hash_salt: str = field(default_factory=lambda: os.environ.get("IP_HASH_SALT", "papers-please-local"))

    # Web frontend
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS") or ["http://localhost:3000"])
    revalidate_url: str = field(default_factory=lambda: os.environ.get("REVALIDATE_URL", ""))
    revalidate_secret: str = field(default_factory=lambda: os.environ.get("REVALIDATE_SECRET", ""))

    @property
    def use_supabase_storage(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


settings = Settings()
