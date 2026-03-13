from __future__ import annotations

import fnmatch
import sys
from pathlib import Path
from typing import Any

from fastapi import Request

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from db import init_db, save_jobs
from dashboard.backend import main, repository


class _MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.zsets: dict[str, dict[str, float]] = {}

    def get_json(self, key: str) -> dict[str, Any] | list[Any] | None:
        value = self.values.get(key)
        if isinstance(value, (dict, list)):
            return value
        return None

    def set_json(self, key: str, value: dict[str, Any] | list[Any], ttl_seconds: int) -> None:
        self.values[key] = value

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)

    def expire(self, key: str, ttl_seconds: int) -> None:
        return None

    def delete_pattern(self, pattern: str) -> None:
        for key in list(self.values):
            if fnmatch.fnmatch(key, pattern):
                self.values.pop(key, None)

    def zadd(self, key: str, members: dict[str, float]) -> None:
        bucket = self.zsets.setdefault(key, {})
        bucket.update(members)

    def zcard(self, key: str) -> int:
        return len(self.zsets.get(key, {}))

    def zrange(self, key: str, start: int, end: int) -> list[str]:
        members = sorted(self.zsets.get(key, {}).items(), key=lambda item: item[1])
        if end < 0:
            sliced = members[start:]
        else:
            sliced = members[start : end + 1]
        return [member for member, _score in sliced]

    def zrem(self, key: str, *members: str) -> None:
        bucket = self.zsets.get(key, {})
        for member in members:
            bucket.pop(member, None)


def _request(client_id: str) -> Request:
    return Request({"type": "http", "headers": [(b"x-client-id", client_id.encode())]})


def test_tracking_update_invalidates_other_client_job_cache(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "cache-test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))
    monkeypatch.setattr(main, "cache", _MemoryCache())

    conn = init_db(str(db_path))
    try:
        save_jobs(
            conn,
            [
                {
                    "url": "https://example.com/cache-job",
                    "company": "Cache Co",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-03-01",
                    "ats": "greenhouse",
                    "description": "Build production AI systems.",
                    "source": "manual",
                }
            ],
        )
    finally:
        conn.close()

    conn = init_db(str(db_path))
    try:
        job_id = repository.get_job_id_by_url(conn, "https://example.com/cache-job")
        assert job_id is not None
    finally:
        conn.close()

    before_a = main.get_job(str(job_id), _request("client-a"))
    before_b = main.get_job(str(job_id), _request("client-b"))

    assert before_a.tracking_status == "not_applied"
    assert before_b.tracking_status == "not_applied"

    updated = main.patch_tracking(str(job_id), main.TrackingPatchRequest(status="staging"), _request("client-a"))
    after_b = main.get_job(str(job_id), _request("client-b"))

    assert updated.tracking_status == "staging"
    assert after_b.tracking_status == "staging"
