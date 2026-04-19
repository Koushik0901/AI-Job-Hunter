from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


from ai_job_hunter.commands import daily_briefing as daily_briefing_command
from ai_job_hunter.db import init_db, save_enrichment, save_jobs
from ai_job_hunter.dashboard.backend import main, repository
from ai_job_hunter.notify import format_daily_briefing_message


def _seed_briefing_state(conn) -> tuple[str, str]:
    repository.save_profile(
        conn,
        {
            "years_experience": 4,
            "skills": ["python", "sql", "mlops"],
            "desired_job_titles": ["ML Engineer"],
            "target_role_families": ["ml engineer"],
            "requires_visa_sponsorship": False,
        },
    )
    save_jobs(
        conn,
        [
            {
                "url": "https://example.com/apply-now",
                "company": "Apply Co",
                "title": "ML Engineer",
                "location": "Remote",
                "posted": datetime.now(timezone.utc).date().isoformat(),
                "ats": "greenhouse",
                "description": "Build applied ML systems",
            },
            {
                "url": "https://example.com/follow-up",
                "company": "Follow Co",
                "title": "Applied Scientist",
                "location": "Remote",
                "posted": datetime.now(timezone.utc).date().isoformat(),
                "ats": "ashby",
                "description": "Applied science role",
            },
        ],
    )
    save_enrichment(
        conn,
        "https://example.com/apply-now",
        {
            "role_family": "ml engineer",
            "required_skills": '["python", "sql"]',
            "preferred_skills": '["mlops"]',
            "enrichment_status": "ok",
            "visa_sponsorship": "yes",
        },
    )
    save_enrichment(
        conn,
        "https://example.com/follow-up",
        {
            "role_family": "applied scientist",
            "required_skills": '["python"]',
            "preferred_skills": '["experimentation"]',
            "enrichment_status": "ok",
            "visa_sponsorship": "yes",
        },
    )
    apply_job_id = str(repository.get_job_id_by_url(conn, "https://example.com/apply-now"))
    follow_job_id = str(repository.get_job_id_by_url(conn, "https://example.com/follow-up"))
    repository.save_job_decision(conn, job_id=apply_job_id, recommendation="apply_now")
    submitted_at = (datetime.now(timezone.utc).date() - timedelta(days=8)).isoformat()
    repository.create_event(
        conn,
        follow_job_id,
        {
            "event_type": "application_submitted",
            "title": "Applied",
            "body": "Submitted last week",
            "event_at": submitted_at,
        },
    )
    return apply_job_id, follow_job_id


@pytest.fixture()
def temp_db_path() -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    handle.close()
    path = Path(handle.name)
    try:
        yield path
    finally:
        if path.exists():
            path.unlink()


def test_refresh_daily_briefing_persists_one_row_per_day(temp_db_path: Path) -> None:
    conn = init_db(str(temp_db_path))
    try:
        apply_job_id, follow_job_id = _seed_briefing_state(conn)
        first = repository.refresh_daily_briefing(conn, trigger_source="scheduled")
        second = repository.refresh_daily_briefing(conn, trigger_source="scrape")

        count_row = conn.execute("SELECT COUNT(*) FROM daily_briefings").fetchone()
        assert int(count_row[0] if count_row else 0) == 1
        assert first["brief_date"] == second["brief_date"]
        assert first["apply_now"][0]["job_id"] == apply_job_id
        assert any(item["job_id"] == follow_job_id for item in second["follow_ups_due"])
        assert second["trigger_source"] == "scrape"
    finally:
        conn.close()


def test_daily_briefing_send_endpoint_dedupes_same_day(temp_db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = init_db(str(temp_db_path))
    try:
        _seed_briefing_state(conn)
    finally:
        conn.close()

    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(temp_db_path), ""))
    calls = {"count": 0}

    def _fake_notify(briefing, token, chat_id, console=None):
        calls["count"] += 1
        return ["briefing chunk"]

    monkeypatch.setattr(main, "notify_daily_briefing", _fake_notify)
    monkeypatch.setattr(main, "telegram_message_hash", lambda chunks: "hash-1")

    with TestClient(main.app) as client:
        latest_response = client.get("/api/meta/daily-briefing/latest")
        assert latest_response.status_code == 200
        refresh_response = client.post("/api/meta/daily-briefing/refresh")
        assert refresh_response.status_code == 200
        first_send = client.post("/api/meta/daily-briefing/send")
        assert first_send.status_code == 200
        assert first_send.json()["telegram_sent_at"] is not None
        second_send = client.post("/api/meta/daily-briefing/send")
        assert second_send.status_code == 200

    assert calls["count"] == 1


def test_format_daily_briefing_message_handles_quiet_day() -> None:
    chunks = format_daily_briefing_message(
        {
            "brief_date": "2026-03-28",
            "summary_line": "Quiet day: no urgent actions.",
            "quiet_day": True,
            "apply_now": [],
            "follow_ups_due": [],
            "watchlist": [],
            "profile_gaps": ["Add stronger evidence for MLOps."],
            "signals": ["No application outcomes yet; use today to build the first clean signal set."],
        }
    )
    assert chunks
    assert all(len(chunk) <= 4096 for chunk in chunks)
    assert "Quiet day" in chunks[0]


def test_daily_briefing_cli_refresh_only_generates_without_sending(temp_db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn = init_db(str(temp_db_path))
    try:
        _seed_briefing_state(conn)
    finally:
        conn.close()

    monkeypatch.setattr(daily_briefing_command, "_resolve_db", lambda: (str(temp_db_path), "", str(temp_db_path)))

    def _unexpected_notify(*args, **kwargs):
        raise AssertionError("notify_daily_briefing should not be called in refresh-only mode")

    monkeypatch.setattr(daily_briefing_command, "notify_daily_briefing", _unexpected_notify)
    daily_briefing_command.run(SimpleNamespace(db=None, refresh_only=True, send_now=False))

    conn = init_db(str(temp_db_path))
    try:
        briefing = repository.get_daily_briefing(conn)
        assert briefing is not None
        assert briefing["generated_at"]
        assert briefing["telegram_sent_at"] is None
    finally:
        conn.close()
