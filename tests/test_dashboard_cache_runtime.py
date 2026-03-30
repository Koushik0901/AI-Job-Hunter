from __future__ import annotations

import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from db import init_db, save_jobs
from dashboard.backend import main, repository
import dashboard.backend.cache as cache_module
from dashboard.backend.cache import DashboardCache


class FakeRedisClient:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def setex(self, key: str, ttl_seconds: int, value: str) -> bool:
        del ttl_seconds
        self.data[key] = value
        return True

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.data:
                deleted += 1
                del self.data[key]
        return deleted

    def scan_iter(self, match: str, count: int = 200):
        del count
        prefix = match[:-1] if match.endswith("*") else match
        for key in list(self.data):
            if match.endswith("*"):
                if key.startswith(prefix):
                    yield key
            elif key == match:
                yield key

    def close(self) -> None:
        return None


@contextmanager
def _client_with_cache(monkeypatch):
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    db_path = Path(handle.name)

    fake_cache = DashboardCache("redis://127.0.0.1:6379/0")
    fake_cache._client = FakeRedisClient()  # type: ignore[attr-defined]
    fake_cache._startup_once = True  # type: ignore[attr-defined]
    fake_cache._health = {  # type: ignore[attr-defined]
        "configured": True,
        "healthy": True,
        "message": "Local Redis container already running.",
    }

    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(cache_module, "redis", object())
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))
    monkeypatch.setattr(main, "get_dashboard_cache", lambda: fake_cache)
    monkeypatch.setattr(main, "_warm_dashboard_cache", lambda: None)

    conn = init_db(str(db_path))
    try:
        save_jobs(
            conn,
            [
                {
                    "url": f"https://example.com/jobs/platform-engineer-{db_path.stem}",
                    "company": "Example",
                    "title": "Platform Engineer",
                    "location": "Remote",
                    "posted": "2026-03-01",
                    "ats": "greenhouse",
                    "description": "Build platform systems.",
                }
            ],
        )
        job_id = repository.get_job_id_by_url(conn, f"https://example.com/jobs/platform-engineer-{db_path.stem}")
        assert job_id is not None
        with TestClient(main.app) as client:
            yield client, str(job_id), fake_cache
    finally:
        conn.close()
        if db_path.exists():
            db_path.unlink()


def test_cached_endpoints_emit_miss_hit_and_304(monkeypatch) -> None:
    with _client_with_cache(monkeypatch) as (client, job_id, _fake_cache):
        jobs_response = client.get("/api/jobs")
        assert jobs_response.status_code == 200
        assert jobs_response.headers["x-cache"] == "MISS"
        assert jobs_response.headers["cache-control"] == "private, no-cache"
        jobs_etag = jobs_response.headers["etag"]

        jobs_hit = client.get("/api/jobs")
        assert jobs_hit.status_code == 200
        assert jobs_hit.headers["x-cache"] == "HIT"
        assert jobs_hit.headers["etag"] == jobs_etag

        jobs_revalidated = client.get("/api/jobs", headers={"If-None-Match": jobs_etag})
        assert jobs_revalidated.status_code == 304
        assert jobs_revalidated.headers["x-cache"] == "REVALIDATED"

        detail_response = client.get(f"/api/jobs/{job_id}")
        assert detail_response.status_code == 200
        assert detail_response.headers["x-cache"] == "MISS"

        detail_hit = client.get(f"/api/jobs/{job_id}")
        assert detail_hit.status_code == 200
        assert detail_hit.headers["x-cache"] == "HIT"

        health_response = client.get("/api/health")
        assert health_response.status_code == 200
        assert health_response.headers["cache-control"] == "no-store"
        payload = health_response.json()
        assert payload["services"]["redis"]["healthy"] is True


def test_assistant_endpoints_emit_miss_hit_and_304(monkeypatch) -> None:
    with _client_with_cache(monkeypatch) as (client, job_id, _fake_cache):
        client.post(f"/api/jobs/{job_id}/decision", json={"recommendation": "apply_now"})

        assistant_paths = [
            "/api/meta/daily-briefing/latest",
            "/api/meta/action-queue",
            "/api/actions/today",
            "/api/meta/conversion",
            "/api/meta/source-quality",
            "/api/meta/profile-gaps",
            "/api/profile/insights",
        ]

        for path in assistant_paths:
            first = client.get(path)
            assert first.status_code == 200
            assert first.headers["x-cache"] == "MISS"
            assert first.headers["cache-control"] == "private, no-cache"
            etag = first.headers["etag"]

            second = client.get(path)
            assert second.status_code == 200
            assert second.headers["x-cache"] == "HIT"
            assert second.headers["etag"] == etag

            revalidated = client.get(path, headers={"If-None-Match": etag})
            assert revalidated.status_code == 304
            assert revalidated.headers["x-cache"] == "REVALIDATED"


def test_mutations_invalidate_related_cache_keys(monkeypatch) -> None:
    with _client_with_cache(monkeypatch) as (client, job_id, fake_cache):
        stats_key = fake_cache.stats_key()
        events_key = fake_cache.job_events_key(job_id)
        detail_key = fake_cache.job_detail_key(job_id)
        jobs_key = fake_cache.jobs_list_key(
            {
                "status": None,
                "q": None,
                "ats": None,
                "company": None,
                "posted_after": None,
                "posted_before": None,
                "sort": "match_desc",
                "limit": 200,
                "offset": 0,
            }
        )

        fake_cache.set_cached_envelope(stats_key, {"ok": True}, 30)
        fake_cache.set_cached_envelope(events_key, [], 90)
        fake_cache.set_cached_envelope(detail_key, {"id": job_id}, 300)
        fake_cache.set_cached_envelope(jobs_key, {"items": [], "total": 0}, 60)
        assistant_keys = [
            fake_cache.daily_briefing_key("2026-03-29"),
            fake_cache.action_queue_key(),
            fake_cache.actions_today_key(),
            fake_cache.conversion_key(),
            fake_cache.source_quality_key(),
            fake_cache.profile_gaps_key(),
            fake_cache.profile_insights_key(),
        ]
        for key in assistant_keys:
            fake_cache.set_cached_envelope(key, {"ok": True}, 60)

        event_response = client.post(
            f"/api/jobs/{job_id}/events",
            json={"event_type": "note", "title": "Reached out", "body": "", "event_at": "2026-03-02"},
        )
        assert event_response.status_code == 200
        assert fake_cache.get_cached_envelope(events_key) is None
        assert fake_cache.get_cached_envelope(stats_key) is None
        assert all(fake_cache.get_cached_envelope(key) is None for key in assistant_keys)

        fake_cache.set_cached_envelope(detail_key, {"id": job_id}, 300)
        fake_cache.set_cached_envelope(jobs_key, {"items": [], "total": 0}, 60)
        fake_cache.set_cached_envelope(stats_key, {"ok": True}, 30)
        for key in assistant_keys:
            fake_cache.set_cached_envelope(key, {"ok": True}, 60)

        patch_response = client.patch(f"/api/jobs/{job_id}/tracking", json={"status": "staging"})
        assert patch_response.status_code == 200
        assert fake_cache.get_cached_envelope(detail_key) is None
        assert fake_cache.get_cached_envelope(jobs_key) is None
        assert fake_cache.get_cached_envelope(stats_key) is None
        assert all(fake_cache.get_cached_envelope(key) is None for key in assistant_keys)

        fake_cache.set_cached_envelope(detail_key, {"id": job_id}, 300)
        fake_cache.set_cached_envelope(jobs_key, {"items": [], "total": 0}, 60)
        fake_cache.set_cached_envelope(stats_key, {"ok": True}, 30)
        for key in assistant_keys:
            fake_cache.set_cached_envelope(key, {"ok": True}, 60)

        decision_response = client.post(f"/api/jobs/{job_id}/decision", json={"recommendation": "apply_now"})
        assert decision_response.status_code == 200
        assert fake_cache.get_cached_envelope(detail_key) is None
        assert fake_cache.get_cached_envelope(jobs_key) is None
        assert fake_cache.get_cached_envelope(stats_key) is None
        assert all(fake_cache.get_cached_envelope(key) is None for key in assistant_keys)

        client.post(f"/api/jobs/{job_id}/decision", json={"recommendation": "apply_now"})
        queue_response = client.get("/api/actions/today")
        assert queue_response.status_code == 200
        action_id = next(
            item["id"]
            for item in queue_response.json()["items"]
            if item["job_id"] == job_id and item["action_type"] == "apply"
        )
        fake_cache.set_cached_envelope(detail_key, {"id": job_id}, 300)
        fake_cache.set_cached_envelope(jobs_key, {"items": [], "total": 0}, 60)
        fake_cache.set_cached_envelope(stats_key, {"ok": True}, 30)
        for key in assistant_keys:
            fake_cache.set_cached_envelope(key, {"ok": True}, 60)

        complete_response = client.post(f"/api/actions/{action_id}/complete")
        assert complete_response.status_code == 200
        assert fake_cache.get_cached_envelope(detail_key) is None
        assert fake_cache.get_cached_envelope(jobs_key) is None
        assert fake_cache.get_cached_envelope(stats_key) is None
        assert all(fake_cache.get_cached_envelope(key) is None for key in assistant_keys)

        queue_response = client.get("/api/meta/action-queue")
        assert queue_response.status_code == 200
        action_id = next(
            item["id"]
            for item in queue_response.json()["items"]
            if item["job_id"] == job_id and item["action_type"] == "follow_up"
        )

        fake_cache.set_cached_envelope(detail_key, {"id": job_id}, 300)
        fake_cache.set_cached_envelope(jobs_key, {"items": [], "total": 0}, 60)
        fake_cache.set_cached_envelope(stats_key, {"ok": True}, 30)
        for key in assistant_keys:
            fake_cache.set_cached_envelope(key, {"ok": True}, 60)

        defer_response = client.post(f"/api/actions/{action_id}/defer", json={"days": 2})
        assert defer_response.status_code == 200
        assert fake_cache.get_cached_envelope(detail_key) is None
        assert fake_cache.get_cached_envelope(jobs_key) is None
        assert fake_cache.get_cached_envelope(stats_key) is None
        assert all(fake_cache.get_cached_envelope(key) is None for key in assistant_keys)

        fake_cache.set_cached_envelope(detail_key, {"id": job_id}, 300)
        fake_cache.set_cached_envelope(jobs_key, {"items": [], "total": 0}, 60)
        fake_cache.set_cached_envelope(stats_key, {"ok": True}, 30)
        for key in assistant_keys:
            fake_cache.set_cached_envelope(key, {"ok": True}, 60)

        suppress_response = client.post(f"/api/jobs/{job_id}/suppress", json={"reason": "not now"})
        assert suppress_response.status_code == 200
        assert fake_cache.get_cached_envelope(detail_key) is None
        assert fake_cache.get_cached_envelope(jobs_key) is None
        assert fake_cache.get_cached_envelope(stats_key) is None
        assert all(fake_cache.get_cached_envelope(key) is None for key in assistant_keys)

        profile_response = client.post("/api/profile/skills", json={"skill": "GraphQL"})
        assert profile_response.status_code == 200
        assert fake_cache.get_cached_envelope(detail_key) is None
        assert fake_cache.get_cached_envelope(jobs_key) is None
        assert fake_cache.get_cached_envelope(stats_key) is None
        assert all(fake_cache.get_cached_envelope(key) is None for key in assistant_keys)


def test_dashboard_cache_startup_starts_local_stopped_container(monkeypatch) -> None:
    import dashboard.backend.cache as cache_module

    calls: list[list[str]] = []

    class FakeRedisModule:
        @staticmethod
        def from_url(url: str, **kwargs):
            del url, kwargs
            return FakeRedisClient()

    def fake_run(command: list[str], capture_output: bool, text: bool, timeout: int, check: bool):
        del capture_output, text, timeout, check
        calls.append(command)
        if command == ["docker", "inspect", "ai-job-hunter-redis"]:
            return type("Completed", (), {"returncode": 0, "stdout": json.dumps([{"State": {"Running": False}}]), "stderr": ""})()
        if command == ["docker", "start", "ai-job-hunter-redis"]:
            return type("Completed", (), {"returncode": 0, "stdout": "ai-job-hunter-redis", "stderr": ""})()
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(cache_module, "redis", FakeRedisModule)
    monkeypatch.setattr(cache_module.subprocess, "run", fake_run)

    cache = DashboardCache("redis://127.0.0.1:6379/0")
    cache.startup()

    health = cache.health()
    assert health["healthy"] is True
    assert health["message"] == "Local Redis container started."
    assert calls[0] == ["docker", "inspect", "ai-job-hunter-redis"]
    assert calls[1] == ["docker", "start", "ai-job-hunter-redis"]
