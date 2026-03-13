from __future__ import annotations

import os
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
from dashboard.backend import main
from services.company_registry_service import candidate_slugs


@pytest.fixture()
def client_and_db(monkeypatch: pytest.MonkeyPatch):
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    db_path = Path(handle.name)
    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))
    client = TestClient(main.app)
    try:
        yield client, db_path
    finally:
        if db_path.exists():
            db_path.unlink()


def test_workspace_overview_counts_desired_titles(client_and_db):
    client, _ = client_and_db
    put_response = client.put(
        "/api/profile",
        json={
            "years_experience": 3,
            "skills": ["Python"],
            "desired_job_titles": ["Machine Learning Engineer"],
        },
    )
    assert put_response.status_code == 200

    response = client.get("/api/workspace/overview")
    assert response.status_code == 200
    payload = response.json()
    assert payload["desired_job_titles_count"] == 1
    assert payload["has_profile_basics"] is True


def test_company_source_create_and_list(client_and_db):
    client, _ = client_and_db
    create_response = client.post(
        "/api/company-sources",
        json={
            "name": "OpenAI",
            "ats_type": "ashby",
            "slug": "openai",
            "ats_url": "https://jobs.ashbyhq.com/openai",
            "enabled": True,
            "source": "manual",
        },
    )
    assert create_response.status_code == 200
    assert create_response.json()["slug"] == "openai"

    list_response = client.get("/api/company-sources")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 1
    assert payload[0]["name"] == "OpenAI"
    assert payload[0]["enabled"] is True


def test_company_source_probe_endpoint_uses_service_result(client_and_db, monkeypatch: pytest.MonkeyPatch):
    client, _ = client_and_db
    monkeypatch.setattr(
        main,
        "probe_company_sources",
        lambda query, extra_slugs=None: {
            "query": query,
            "company_name": "OpenAI",
            "slugs": ["openai"],
            "inferred": None,
            "matches": [
                {
                    "name": "OpenAI",
                    "slug": "openai",
                    "ats_type": "ashby",
                    "ats_url": "https://jobs.ashbyhq.com/openai",
                    "jobs": 12,
                }
            ],
            "zero_job_matches": [],
        },
    )
    response = client.post("/api/company-sources/probe", json={"query": "OpenAI"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["company_name"] == "OpenAI"
    assert payload["matches"][0]["slug"] == "openai"
    assert payload["matches"][0]["jobs"] == 12


def test_workspace_prune_preview_creates_operation_record(client_and_db):
    client, db_path = client_and_db
    conn = init_db(str(db_path))
    try:
        save_jobs(
            conn,
            [
                {
                    "url": "https://example.com/old-role",
                    "company": "Acme",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2025-01-01",
                    "ats": "greenhouse",
                    "description": "x",
                }
            ],
        )
    finally:
        conn.close()

    response = client.post("/api/workspace/operations/prune-preview", json={"days": 30})
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "prune_preview"
    assert payload["status"] == "completed"
    assert payload["summary"]["affected"] >= 1

    operations_response = client.get("/api/workspace/operations")
    assert operations_response.status_code == 200
    operations = operations_response.json()
    assert any(item["id"] == payload["id"] for item in operations)


def test_candidate_slugs_preserves_hyphenated_slug_input():
    slugs = candidate_slugs("valsoft-corp")
    assert "valsoft-corp" in slugs
    assert "valsoftcorp" in slugs
