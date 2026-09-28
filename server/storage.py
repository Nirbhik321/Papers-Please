"""
storage.py — where original uploaded PDFs are kept.

Files are stored under their SHA-256 hash, never under the name the uploader
sent, so a crafted filename can't escape the folder or overwrite anything.
Originals are private: they are only read back by the worker, never served.
"""

from pathlib import Path

import httpx

from server.config import settings


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("storage key escapes the storage folder")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class SupabaseStorage:
    """Private Supabase Storage bucket, accessed with the service-role key."""

    def __init__(self, url: str, service_key: str, bucket: str):
        self.base = f"{url}/storage/v1/object"
        self.bucket = bucket
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    def put(self, key: str, data: bytes) -> None:
        r = httpx.post(
            f"{self.base}/{self.bucket}/{key}", content=data, timeout=60,
            headers={**self.headers, "Content-Type": "application/pdf", "x-upsert": "true"},
        )
        r.raise_for_status()

    def get(self, key: str) -> bytes:
        r = httpx.get(f"{self.base}/authenticated/{self.bucket}/{key}", headers=self.headers, timeout=60)
        r.raise_for_status()
        return r.content

    def delete(self, key: str) -> None:
        r = httpx.request("DELETE", f"{self.base}/{self.bucket}", json={"prefixes": [key]},
                          headers=self.headers, timeout=30)
        r.raise_for_status()


def key_for(content_hash: str) -> str:
    return f"papers/{content_hash[:2]}/{content_hash}.pdf"


storage = (
    SupabaseStorage(settings.supabase_url, settings.supabase_service_key, settings.supabase_bucket)
    if settings.use_supabase_storage
    else LocalStorage(settings.storage_dir)
)
