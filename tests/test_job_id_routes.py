from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from db import init_db, save_jobs
from dashboard.backend import repository
from dashboard.backend import main


@pytest.fixture()
def client_and_job(monkeypatch: pytest.MonkeyPatch):
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    db_path = Path(handle.name)
    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))
    main.cache.delete_pattern("dashboard:v1:*")
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
        main.cache.delete_pattern("dashboard:v1:*")
        if db_path.exists():
            db_path.unlink()


def test_job_endpoints_accept_job_id(client_and_job) -> None:
    client, job_id, job_url = client_and_job

    detail_response = client.get(f"/api/jobs/{job_id}")
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    assert detail_payload["id"] == job_id
    assert detail_payload["url"] == job_url

    patch_response = client.patch(f"/api/jobs/{job_id}/tracking", json={"status": "staging"})
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["id"] == job_id
    assert patched["tracking_status"] == "staging"

    artifacts_response = client.get(f"/api/jobs/{job_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()
    assert len(artifacts) == 2
    assert {item["artifact_type"] for item in artifacts} == {"resume", "cover_letter"}
    assert all(item["job_id"] == job_id for item in artifacts)

    starter_status = client.get(f"/api/jobs/{job_id}/artifacts/starter/status")
    assert starter_status.status_code == 200
    starter_payload = starter_status.json()
    assert starter_payload["job_id"] == job_id
    assert starter_payload["job_url"] == job_url
