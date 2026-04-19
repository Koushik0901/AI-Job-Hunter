from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


from ai_job_hunter.db import create_workspace_operation, init_db, save_jobs
from ai_job_hunter.dashboard.backend import repository
from ai_job_hunter.dashboard.backend import main


@pytest.fixture()
def client_and_job(monkeypatch: pytest.MonkeyPatch):
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    db_path = Path(handle.name)
    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))
    client = TestClient(main.app)
    job_url = f"https://example.com/jobs/platform-engineer-{db_path.stem}"

    conn = init_db(str(db_path))
    try:
        save_jobs(
            conn,
            [
                {
                    "url": job_url,
                    "company": "Example",
                    "title": "Platform Engineer",
                    "location": "Remote",
                    "posted": "2026-03-01",
                    "ats": "greenhouse",
                    "description": "Build platform systems.",
                }
            ],
        )
        job_id = repository.get_job_id_by_url(conn, job_url)
        assert job_id is not None
        detail = repository.get_job_detail(conn, str(job_id))
        assert detail is not None
        yield client, str(job_id), job_url
    finally:
        conn.close()
        if db_path.exists():
            db_path.unlink()


def test_job_endpoints_accept_job_id(client_and_job) -> None:
    client, job_id, job_url = client_and_job

    detail_response = client.get(f"/api/jobs/{job_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["id"] == job_id
    assert detail_payload["url"] == job_url
    assert detail_payload["pinned"] is False

    patch_response = client.patch(f"/api/jobs/{job_id}/tracking", json={"status": "staging"})
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["id"] == job_id
    assert patched["tracking_status"] == "staging"
    assert patched["pinned"] is False

    pin_response = client.patch(f"/api/jobs/{job_id}/tracking", json={"pinned": True})
    assert pin_response.status_code == 200
    pinned = pin_response.json()
    assert pinned["id"] == job_id
    assert pinned["pinned"] is True

    events_response = client.get(f"/api/jobs/{job_id}/events")
    assert events_response.status_code == 200
    assert events_response.json() == []


def test_action_queue_and_insights_endpoints(client_and_job) -> None:
    client, job_id, _ = client_and_job

    decision_response = client.post(f"/api/jobs/{job_id}/decision", json={"recommendation": "apply_now"})
    assert decision_response.status_code == 200
    assert decision_response.json()["recommendation"] == "apply_now"

    queue_response = client.get("/api/actions/today")
    assert queue_response.status_code == 200
    queue_items = queue_response.json()["items"]
    assert any(item["job_id"] == job_id for item in queue_items)

    apply_action = next(item for item in queue_items if item["job_id"] == job_id and item["action_type"] == "apply")
    complete_response = client.post(f"/api/actions/{apply_action['id']}/complete")
    assert complete_response.status_code == 200
    assert complete_response.json()["status"] == "completed"

    refreshed_queue = client.get("/api/meta/action-queue")
    assert refreshed_queue.status_code == 200
    assert refreshed_queue.headers.get("Server-Timing")
    refreshed_items = refreshed_queue.json()["items"]
    assert any(item["job_id"] == job_id and item["action_type"] == "follow_up" for item in refreshed_items)

    insights_response = client.get("/api/profile/insights")
    assert insights_response.status_code == 200
    assert "top_missing_signals" in insights_response.json()


def test_manual_job_endpoint_returns_immediate_stub_and_schedules_finalize(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    db_path = Path(handle.name)
    scheduled: list[tuple[str, str]] = []

    def fake_finalize(job_id: str, url: str) -> None:
        scheduled.append((job_id, url))

    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))
    monkeypatch.setattr(main, "_background_finalize_manual_job", fake_finalize)

    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/api/jobs/manual",
                json={
                    "url": f"https://example.com/manual-{db_path.stem}",
                    "company": "Manual Co",
                    "title": "Applied Scientist",
                    "location": "Remote",
                    "posted": "2026-03-20",
                    "ats": "manual",
                    "status": "staging",
                    "description": "Build and ship applied ML systems.",
                },
            )

            duplicate_response = client.post(
                "/api/jobs/manual",
                json={
                    "url": f"https://example.com/manual-{db_path.stem}",
                    "company": "Manual Co",
                    "title": "Applied Scientist",
                    "location": "Remote",
                    "posted": "2026-03-20",
                    "ats": "manual",
                    "status": "staging",
                    "description": "Build and ship applied ML systems.",
                },
            )

        assert response.status_code == 200
        assert duplicate_response.status_code == 200
        payload = response.json()
        duplicate_payload = duplicate_response.json()
        assert payload["tracking_status"] == "staging"
        assert payload["enrichment"] is None
        assert payload["match"] is None
        assert payload["recommendation"] is None
        assert payload["recommendation_reasons"] == []
        assert payload["duplicate_detected"] is False
        assert duplicate_payload["duplicate_detected"] is True
        assert duplicate_payload["duplicate_match_kind"] == "url"
        assert duplicate_payload["duplicate_of_job_id"] == payload["id"]
        assert scheduled == [(payload["id"], payload["url"])]
    finally:
        if db_path.exists():
            db_path.unlink()


def test_bootstrap_endpoint_returns_cache_metadata(client_and_job) -> None:
    client, _, _ = client_and_job

    response = client.get("/api/bootstrap")

    assert response.status_code == 200
    assert response.headers.get("Server-Timing")
    payload = response.json()
    assert "recommended_jobs" in payload
    assert "action_queue" in payload
    assert "cache" in payload


def test_dashboard_events_stream_yields_initial_payload(client_and_job) -> None:
    client, _, _ = client_and_job

    response = client.get("/api/events/stream?once=true")

    assert response.status_code == 200
    payload_line = next(
        line
        for line in response.text.splitlines()
        if line.startswith("data: ")
    )
    payload = json.loads(payload_line.removeprefix("data: "))
    assert payload["event"] in {"ready", "refresh"}
    assert "scope" in payload
    assert "at" in payload


def test_operation_events_stream_emits_completed_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    db_path = Path(handle.name)
    operation_id = "test-op-stream"

    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))

    conn = init_db(str(db_path))
    try:
        create_workspace_operation(
            conn,
            {
                "id": operation_id,
                "kind": "artifact_generate",
                "status": "completed",
                "params": {"job_id": "job-1"},
                "summary": {"artifact_id": 12},
            },
        )
        with TestClient(main.app) as client:
            with client.stream("GET", f"/api/operations/{operation_id}/events") as response:
                assert response.status_code == 200
                chunks: list[str] = []
                for chunk in response.iter_text():
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    if "data:" in chunk:
                        break
    finally:
        conn.close()
        if db_path.exists():
            db_path.unlink()

    payload_line = next(line for chunk in chunks for line in chunk.splitlines() if line.startswith("data: "))
    payload = json.loads(payload_line.removeprefix("data: "))
    assert payload["id"] == operation_id
    assert payload["status"] == "completed"


def test_manual_job_endpoint_reuses_existing_job_for_duplicate_content(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    db_path = Path(handle.name)
    scheduled: list[tuple[str, str]] = []

    def fake_finalize(job_id: str, url: str) -> None:
        scheduled.append((job_id, url))

    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))
    monkeypatch.setattr(main, "_background_finalize_manual_job", fake_finalize)

    try:
        with TestClient(main.app) as client:
            first_response = client.post(
                "/api/jobs/manual",
                json={
                    "url": "https://example.com/manual-content-a",
                    "company": "Manual Co",
                    "title": "Applied Scientist",
                    "location": "Remote",
                    "posted": "2026-03-20",
                    "ats": "manual",
                    "status": "staging",
                    "description": "Build and ship applied ML systems.",
                },
            )
            second_response = client.post(
                "/api/jobs/manual",
                json={
                    "url": "https://example.com/manual-content-b",
                    "company": "Manual Co",
                    "title": "Applied Scientist",
                    "location": "Remote",
                    "posted": "2026-03-02",
                    "ats": "manual",
                    "status": "staging",
                    "description": "Build and ship applied ML systems.",
                },
            )

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        first_payload = first_response.json()
        second_payload = second_response.json()
        assert first_payload["duplicate_detected"] is False
        assert second_payload["duplicate_detected"] is True
        assert second_payload["duplicate_of_job_id"] == first_payload["id"]
        assert second_payload["duplicate_match_kind"] == "content"
        assert second_payload["id"] == first_payload["id"]
        assert scheduled == [(first_payload["id"], first_payload["url"])]
    finally:
        if db_path.exists():
            db_path.unlink()


def test_manual_job_processing_completes_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    db_path = Path(handle.name)

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))
    monkeypatch.setattr(repository, "recompute_match_scores", lambda conn, urls=None, progress_callback=None: 1)

    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/api/jobs/manual",
                json={
                    "url": f"https://example.com/manual-processing-{db_path.stem}",
                    "company": "Manual Co",
                    "title": "Applied Scientist",
                    "location": "Remote",
                    "posted": "2026-03-20",
                    "ats": "manual",
                    "status": "staging",
                    "description": "Build and ship applied ML systems.",
                },
            )

            job_id = response.json()["id"]
            detail_response = client.get(f"/api/jobs/{job_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["processing"]["state"] == "processing"
        assert payload["processing"]["step"] == "queued"
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["processing"]["state"] == "ready"
        assert detail["processing"]["step"] == "complete"
        assert detail["processing"]["last_processed_at"] is not None
    finally:
        if db_path.exists():
            db_path.unlink()


def test_retry_processing_requeues_failed_job(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    db_path = Path(handle.name)
    calls = {"count": 0}

    def _recompute(conn, urls=None, progress_callback=None):
        del conn, urls, progress_callback
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return 1

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))
    monkeypatch.setattr(repository, "recompute_match_scores", _recompute)

    try:
        with TestClient(main.app) as client:
            response = client.post(
                "/api/jobs/manual",
                json={
                    "url": f"https://example.com/manual-retry-{db_path.stem}",
                    "company": "Manual Co",
                    "title": "Applied Scientist",
                    "location": "Remote",
                    "posted": "2026-03-20",
                    "ats": "manual",
                    "status": "staging",
                    "description": "Build and ship applied ML systems.",
                },
            )
            job_id = response.json()["id"]

            failed_detail = client.get(f"/api/jobs/{job_id}")
            assert failed_detail.status_code == 200
            assert failed_detail.json()["processing"]["state"] == "failed"
            assert "boom" in str(failed_detail.json()["processing"]["last_error"] or "")

            retry_response = client.post(f"/api/jobs/{job_id}/retry-processing")
            assert retry_response.status_code == 200
            assert retry_response.json()["processing"]["state"] == "processing"
            assert retry_response.json()["processing"]["retry_count"] == 1

            refreshed_detail = client.get(f"/api/jobs/{job_id}")
            assert refreshed_detail.status_code == 200
            assert refreshed_detail.json()["processing"]["state"] == "ready"
            assert refreshed_detail.json()["processing"]["retry_count"] == 1

            retry_again = client.post(f"/api/jobs/{job_id}/retry-processing")
            assert retry_again.status_code == 200
            assert retry_again.json()["processing"]["state"] == "ready"
            assert retry_again.json()["processing"]["retry_count"] == 1
    finally:
        if db_path.exists():
            db_path.unlink()
