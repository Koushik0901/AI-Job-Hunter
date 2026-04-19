from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


from ai_job_hunter.db import init_db, save_enrichment, save_jobs
from ai_job_hunter.dashboard.backend import main
from ai_job_hunter.dashboard.backend.job_description_pdf import (
    build_job_description_filename,
    export_job_description_pdf,
    render_job_description_html,
)


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


def _seed_job(db_path: Path, *, formatted_description: str | None) -> str:
    conn = init_db(str(db_path))
    url = "https://example.com/jobs/ml-engineer"
    try:
        save_jobs(
            conn,
            [
                {
                    "url": url,
                    "company": "Acme AI",
                    "title": "ML Engineer",
                    "location": "Remote, Canada",
                    "posted": "2026-03-10",
                    "ats": "greenhouse",
                    "description": "Raw description",
                }
            ],
        )
        if formatted_description is not None:
            save_enrichment(
                conn,
                url,
                {
                    "work_mode": "remote",
                    "remote_geo": "Canada",
                    "canada_eligible": "yes",
                    "seniority": "mid",
                    "role_family": "ml",
                    "years_exp_min": 3,
                    "years_exp_max": 6,
                    "minimum_degree": "Bachelor",
                    "required_skills": "[]",
                    "preferred_skills": "[]",
                    "formatted_description": formatted_description,
                    "salary_min": None,
                    "salary_max": None,
                    "salary_currency": None,
                    "visa_sponsorship": "unknown",
                    "red_flags": "[]",
                    "enriched_at": "2026-03-16T12:00:00Z",
                    "enrichment_status": "ok",
                    "enrichment_model": "test-model",
                },
            )
        row = conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
        assert row and row[0]
        return str(row[0])
    finally:
        conn.close()


def test_build_job_description_filename_slugifies_company_and_title() -> None:
    filename = build_job_description_filename({"company": "Acme AI", "title": "Senior ML Engineer", "id": "job-123"})
    assert filename == "acme-ai-senior-ml-engineer-job-description.pdf"


def test_render_job_description_html_includes_header_and_markdown_content() -> None:
    html = render_job_description_html(
        {
            "id": "job-123",
            "url": "https://example.com/jobs/ml-engineer",
            "company": "Acme AI",
            "title": "ML Engineer",
            "location": "Remote, Canada",
            "posted": "2026-03-10",
            "ats": "greenhouse",
            "enrichment": {
                "formatted_description": "# Overview\n\n- Python\n- SQL\n\n| Skill | Level |\n| --- | --- |\n| Python | Strong |",
            },
        }
    )
    assert "Acme AI" in html
    assert "<h1>ML Engineer</h1>" in html
    assert "<li>Python</li>" in html
    assert "<table>" in html


def test_render_job_description_html_strips_unsafe_html_and_urls() -> None:
    html = render_job_description_html(
        {
            "id": "job-123",
            "url": "https://example.com/jobs/ml-engineer",
            "company": "Acme AI",
            "title": "ML Engineer",
            "location": "Remote, Canada",
            "posted": "2026-03-10",
            "ats": "greenhouse",
            "enrichment": {
                "formatted_description": (
                    "# Overview\n\n"
                    '<img src="http://169.254.169.254/latest/meta-data" />\n\n'
                    '[unsafe local link](file:///etc/passwd)\n\n'
                    '<script>alert("x")</script>\n\n'
                    "Normal paragraph."
                ),
            },
        }
    )
    assert "<img" not in html
    assert "<script" not in html
    assert "file:///etc/passwd" not in html
    assert "Normal paragraph." in html


def test_export_job_description_pdf_returns_pdf_bytes() -> None:
    pdf_bytes = export_job_description_pdf(
        {
            "id": "job-123",
            "url": "https://example.com/jobs/ml-engineer",
            "company": "Acme AI",
            "title": "ML Engineer",
            "location": "Remote, Canada",
            "posted": "2026-03-10",
            "ats": "greenhouse",
            "enrichment": {
                "formatted_description": "# Overview\n\n- Python\n- SQL",
            },
        }
    )
    assert pdf_bytes.startswith(b"%PDF")


def test_job_description_pdf_route_returns_attachment(client_and_db) -> None:
    client, db_path = client_and_db
    job_id = _seed_job(
        db_path,
        formatted_description="# Overview\n\n- Python\n- SQL\n\n## Notes\n\nStrong communication.",
    )

    response = client.get(f"/api/jobs/{job_id}/description/pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attachment; filename=acme-ai-ml-engineer-job-description.pdf" in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")


def test_job_description_pdf_route_returns_409_when_formatted_markdown_missing(client_and_db) -> None:
    client, db_path = client_and_db
    job_id = _seed_job(db_path, formatted_description=None)

    response = client.get(f"/api/jobs/{job_id}/description/pdf")

    assert response.status_code == 409
    assert "Formatted job description is not available yet" in response.text
