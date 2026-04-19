from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_job_hunter.db import init_db, save_jobs
from ai_job_hunter.dashboard.backend import artifacts as artifact_svc
from ai_job_hunter.dashboard.backend import main, repository


@pytest.fixture()
def client_with_job(monkeypatch: pytest.MonkeyPatch):
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    db_path = Path(handle.name)
    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))

    client = TestClient(main.app)
    conn = init_db(str(db_path))
    try:
        url = f"https://example.com/jobs/ml-platform-{db_path.stem}"
        save_jobs(
            conn,
            [
                {
                    "url": url,
                    "company": "Example AI",
                    "title": "Senior ML Platform Engineer",
                    "location": "Remote",
                    "posted": "2026-04-10",
                    "ats": "greenhouse",
                    "description": "Build model delivery systems and experimentation platforms.",
                }
            ],
        )
        job_id = repository.get_job_id_by_url(conn, url)
        assert job_id is not None
        yield client, conn, str(job_id)
    finally:
        conn.close()
        if db_path.exists():
            db_path.unlink()


def test_agent_chat_keeps_backward_compatible_plain_response(client_with_job) -> None:
    client, _, _ = client_with_job

    response = client.post(
        "/api/agent/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reply"]
    assert payload["output_kind"] == "none"
    assert payload["operation_id"] is None


def test_agent_gateway_returns_structured_discovery_output(client_with_job) -> None:
    client, _, _ = client_with_job

    response = client.post(
        "/api/agent/chat",
        json={
            "messages": [{"role": "user", "content": "/discover ml platform"}],
            "skill_invocation": {
                "name": "discover",
                "arguments": "ml platform",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["response_mode"] == "skill"
    assert payload["output_kind"] == "discovery"
    assert payload["operation_id"] is None
    assert payload["output_payload"]["items"]
    assert payload["output_payload"]["items"][0]["company"] == "Example AI"


def test_agent_gateway_resume_requires_selected_job(client_with_job) -> None:
    client, _, _ = client_with_job

    response = client.post(
        "/api/agent/chat",
        json={
            "messages": [{"role": "user", "content": "/resume emphasize leadership"}],
            "skill_invocation": {
                "name": "resume",
                "arguments": "emphasize leadership",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_kind"] == "none"
    assert "Select a queued role first" in payload["reply"]


def test_agent_gateway_resume_returns_operation_metadata(
    client_with_job,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, conn, job_id = client_with_job
    artifact_svc.save_base_document(
        "resume",
        "resume.md",
        "# Resume\n\nImpact bullets.",
        b"# Resume",
        "text/markdown",
        conn,
    )
    conn.commit()

    from ai_job_hunter.dashboard.backend.agent_gateway.core_access import CoreActionClient

    monkeypatch.setattr(
        CoreActionClient,
        "enqueue_resume_generation",
        lambda self, selected_job_id, base_doc_id: {
            "id": "op-test-resume",
            "kind": "artifact_generate",
            "params": {
                "job_id": selected_job_id,
                "artifact_type": "resume",
                "base_doc_id": base_doc_id,
            },
        },
    )

    response = client.post(
        "/api/agent/chat",
        json={
            "messages": [{"role": "user", "content": "/resume emphasize experiments"}],
            "skill_invocation": {
                "name": "resume",
                "arguments": "emphasize experiments",
                "selected_job_id": job_id,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_kind"] == "resume"
    assert payload["operation_id"] == "op-test-resume"
    assert payload["output_payload"]["job_id"] == job_id


def test_agent_gateway_critique_uses_active_artifact(client_with_job) -> None:
    client, conn, job_id = client_with_job
    artifact = artifact_svc.save_artifact(
        job_id,
        "resume",
        "# Candidate Name\n\n## Experience\n- Led ML experimentation for 3 launches.",
        None,
        "test",
        conn,
    )

    response = client.post(
        "/api/agent/chat",
        json={
            "messages": [{"role": "user", "content": "/critique tighten the opening"}],
            "skill_invocation": {
                "name": "critique",
                "arguments": "tighten the opening",
                "selected_job_id": job_id,
                "active_artifact_id": artifact["id"],
                "active_output_kind": "resume",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["output_kind"] == "critique"
    assert payload["output_payload"]["artifact_id"] == artifact["id"]
    assert payload["output_payload"]["artifact_type"] == "resume"
    assert payload["output_payload"]["summary"]
