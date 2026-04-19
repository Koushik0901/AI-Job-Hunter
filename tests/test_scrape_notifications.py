from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


from ai_job_hunter.commands import scrape_jobs
from ai_job_hunter.db import init_db, list_overdue_staging_jobs, save_jobs, suppress_job_id
from ai_job_hunter.notify import format_overdue_staging_message


def _scrape_args(**overrides):
    defaults = {
        "db": None,
        "no_location_filter": False,
        "limit": 20,
        "no_enrich": False,
        "no_notify": False,
        "no_enrich_llm": True,
        "enrich_backfill": False,
        "re_enrich_all": False,
        "jd_reformat_missing": False,
        "jd_reformat_all": False,
        "sort_by": "match",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _insert_staging_tracking(conn, *, url: str, status: str, entered_at: datetime, due_at: datetime | None) -> str:
    row = conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
    assert row and row[0]
    job_id = str(row[0])
    conn.execute(
        """
        INSERT INTO job_tracking (job_id, url, status, staging_entered_at, staging_due_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            url,
            status,
            entered_at.isoformat(),
            due_at.isoformat() if due_at else None,
            entered_at.isoformat(),
        ),
    )
    conn.commit()
    return job_id


@pytest.fixture()
def db_conn(tmp_path: Path):
    db_path = tmp_path / "jobs.db"
    conn = init_db(str(db_path))
    try:
        yield conn, db_path
    finally:
        try:
            conn.close()
        except Exception:
            pass


def test_list_overdue_staging_jobs_filters_and_falls_back(db_conn):
    conn, _ = db_conn
    now = datetime(2026, 3, 13, 17, 0, tzinfo=timezone.utc)
    save_jobs(
        conn,
        [
            {
                "url": "https://example.com/overdue-explicit",
                "company": "Acme",
                "title": "ML Engineer",
                "location": "Remote",
                "posted": "2026-03-01",
                "ats": "ashby",
                "description": "desc",
            },
            {
                "url": "https://example.com/overdue-fallback",
                "company": "Beta",
                "title": "Data Engineer",
                "location": "Toronto, ON",
                "posted": "2026-03-01",
                "ats": "greenhouse",
                "description": "desc",
            },
            {
                "url": "https://example.com/not-overdue",
                "company": "Gamma",
                "title": "Backend Engineer",
                "location": "Remote",
                "posted": "2026-03-01",
                "ats": "lever",
                "description": "desc",
            },
            {
                "url": "https://example.com/not-staging",
                "company": "Delta",
                "title": "Platform Engineer",
                "location": "Remote",
                "posted": "2026-03-01",
                "ats": "lever",
                "description": "desc",
            },
            {
                "url": "https://example.com/suppressed-overdue",
                "company": "Echo",
                "title": "Analytics Engineer",
                "location": "Remote",
                "posted": "2026-03-01",
                "ats": "lever",
                "description": "desc",
            },
        ],
    )
    explicit_entered = now - timedelta(hours=55)
    fallback_entered = now - timedelta(hours=50)
    fresh_entered = now - timedelta(hours=10)
    explicit_id = _insert_staging_tracking(
        conn,
        url="https://example.com/overdue-explicit",
        status="staging",
        entered_at=explicit_entered,
        due_at=now - timedelta(hours=7),
    )
    _insert_staging_tracking(
        conn,
        url="https://example.com/overdue-fallback",
        status="staging",
        entered_at=fallback_entered,
        due_at=None,
    )
    _insert_staging_tracking(
        conn,
        url="https://example.com/not-overdue",
        status="staging",
        entered_at=fresh_entered,
        due_at=now + timedelta(hours=20),
    )
    _insert_staging_tracking(
        conn,
        url="https://example.com/not-staging",
        status="applied",
        entered_at=explicit_entered,
        due_at=now - timedelta(hours=7),
    )
    suppressed_id = _insert_staging_tracking(
        conn,
        url="https://example.com/suppressed-overdue",
        status="staging",
        entered_at=explicit_entered,
        due_at=now - timedelta(hours=3),
    )
    suppress_job_id(conn, job_id=suppressed_id, created_by="test")

    overdue_jobs = list_overdue_staging_jobs(conn, reference_at=now)

    assert [job["url"] for job in overdue_jobs] == [
        "https://example.com/overdue-explicit",
        "https://example.com/overdue-fallback",
    ]
    assert overdue_jobs[0]["job_id"] == explicit_id
    assert overdue_jobs[0]["overdue_hours"] == 7
    assert overdue_jobs[1]["staging_due_at"] == (fallback_entered + timedelta(hours=48)).isoformat()


def test_format_overdue_staging_message_chunks_large_payload():
    overdue_jobs = [
        {
            "company": f"Company {index}",
            "title": f"Senior Machine Learning Engineer {index} with long title text",
            "location": "Remote, Canada",
            "url": f"https://example.com/jobs/{index}",
            "overdue_hours": 72 + index,
        }
        for index in range(80)
    ]

    chunks = format_overdue_staging_message(overdue_jobs, "2026-03-13")

    assert len(chunks) > 1
    assert all(len(chunk) <= 4096 for chunk in chunks)
    assert "staging job(s) overdue" in chunks[0]
    assert "Overdue by 3d" in chunks[0]


def test_scrape_run_sends_overdue_alert_even_without_new_jobs(db_conn, monkeypatch: pytest.MonkeyPatch, capsys):
    conn, db_path = db_conn
    now = datetime.now(timezone.utc) - timedelta(hours=50)
    save_jobs(
        conn,
        [
            {
                "url": "https://example.com/overdue-only",
                "company": "Acme",
                "title": "ML Engineer",
                "location": "Remote",
                "posted": "2026-03-01",
                "ats": "ashby",
                "description": "desc",
            }
        ],
    )
    _insert_staging_tracking(
        conn,
        url="https://example.com/overdue-only",
        status="staging",
        entered_at=now,
        due_at=None,
    )
    conn.close()

    monkeypatch.setattr(scrape_jobs, "_resolve_db", lambda: (str(db_path), "", str(db_path)))
    monkeypatch.setattr(
        scrape_jobs,
        "execute_workspace_operation",
        lambda *args, **kwargs: {"jobs": [], "new_jobs": [], "new_count": 0, "updated_count": 0},
    )
    monkeypatch.setattr(scrape_jobs, "render_jobs_table", lambda *args, **kwargs: None)
    calls = {"new": 0, "overdue": 0}
    monkeypatch.setattr(scrape_jobs, "notify_new_jobs", lambda *args, **kwargs: calls.__setitem__("new", calls["new"] + 1))
    monkeypatch.setattr(
        scrape_jobs,
        "notify_overdue_staging_jobs",
        lambda jobs, *args, **kwargs: calls.__setitem__("overdue", len(jobs)),
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("DESCRIPTION_FORMAT_MODEL", "test-model")

    scrape_jobs.run(_scrape_args())

    assert calls == {"new": 0, "overdue": 1}
    assert "No new jobs - no Telegram notification sent." in capsys.readouterr().err


def test_scrape_run_sends_new_and_overdue_as_separate_notifications(db_conn, monkeypatch: pytest.MonkeyPatch):
    conn, db_path = db_conn
    entered = datetime.now(timezone.utc) - timedelta(hours=60)
    save_jobs(
        conn,
        [
            {
                "url": "https://example.com/overdue-and-new",
                "company": "Acme",
                "title": "ML Engineer",
                "location": "Remote",
                "posted": "2026-03-01",
                "ats": "ashby",
                "description": "desc",
            }
        ],
    )
    _insert_staging_tracking(
        conn,
        url="https://example.com/overdue-and-new",
        status="staging",
        entered_at=entered,
        due_at=None,
    )
    conn.close()

    monkeypatch.setattr(scrape_jobs, "_resolve_db", lambda: (str(db_path), "", str(db_path)))
    monkeypatch.setattr(
        scrape_jobs,
        "execute_workspace_operation",
        lambda *args, **kwargs: {
            "jobs": [{"url": "https://example.com/overdue-and-new"}],
            "new_jobs": [{"url": "https://example.com/overdue-and-new", "company": "Acme", "title": "ML Engineer"}],
            "new_count": 1,
            "updated_count": 0,
        },
    )
    monkeypatch.setattr(scrape_jobs, "render_jobs_table", lambda *args, **kwargs: None)
    calls = {"new": 0, "overdue": 0}
    monkeypatch.setattr(
        scrape_jobs,
        "notify_new_jobs",
        lambda jobs, *args, **kwargs: calls.__setitem__("new", len(jobs)),
    )
    monkeypatch.setattr(
        scrape_jobs,
        "notify_overdue_staging_jobs",
        lambda jobs, *args, **kwargs: calls.__setitem__("overdue", len(jobs)),
    )
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("DESCRIPTION_FORMAT_MODEL", "test-model")

    scrape_jobs.run(_scrape_args())

    assert calls == {"new": 1, "overdue": 1}


def test_scrape_run_no_notify_suppresses_both_notification_types(db_conn, monkeypatch: pytest.MonkeyPatch):
    conn, db_path = db_conn
    entered = datetime.now(timezone.utc) - timedelta(hours=60)
    save_jobs(
        conn,
        [
            {
                "url": "https://example.com/silent-run",
                "company": "Acme",
                "title": "ML Engineer",
                "location": "Remote",
                "posted": "2026-03-01",
                "ats": "ashby",
                "description": "desc",
            }
        ],
    )
    _insert_staging_tracking(
        conn,
        url="https://example.com/silent-run",
        status="staging",
        entered_at=entered,
        due_at=None,
    )
    conn.close()

    monkeypatch.setattr(scrape_jobs, "_resolve_db", lambda: (str(db_path), "", str(db_path)))
    monkeypatch.setattr(
        scrape_jobs,
        "execute_workspace_operation",
        lambda *args, **kwargs: {
            "jobs": [{"url": "https://example.com/silent-run"}],
            "new_jobs": [{"url": "https://example.com/silent-run", "company": "Acme", "title": "ML Engineer"}],
            "new_count": 1,
            "updated_count": 0,
        },
    )
    monkeypatch.setattr(scrape_jobs, "render_jobs_table", lambda *args, **kwargs: None)
    calls = {"new": 0, "overdue": 0}
    monkeypatch.setattr(scrape_jobs, "notify_new_jobs", lambda *args, **kwargs: calls.__setitem__("new", calls["new"] + 1))
    monkeypatch.setattr(scrape_jobs, "notify_overdue_staging_jobs", lambda *args, **kwargs: calls.__setitem__("overdue", calls["overdue"] + 1))
    monkeypatch.setenv("TELEGRAM_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("DESCRIPTION_FORMAT_MODEL", "test-model")

    scrape_jobs.run(_scrape_args(no_notify=True))

    assert calls == {"new": 0, "overdue": 0}
