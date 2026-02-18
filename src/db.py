"""
db.py — SQLite / SQLite Cloud persistence layer.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any


def init_db(db_url: str) -> Any:
    """Open the jobs database (local SQLite file or SQLite Cloud URL) and ensure the schema exists."""
    if db_url.startswith("sqlitecloud://"):
        import sqlitecloud  # type: ignore[import]
        conn = sqlitecloud.connect(db_url)
    else:
        conn = sqlite3.connect(db_url)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            url         TEXT PRIMARY KEY,
            company     TEXT,
            title       TEXT,
            location    TEXT,
            posted      TEXT,
            ats         TEXT,
            description TEXT,
            first_seen  TEXT NOT NULL,
            last_seen   TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_enrichments (
            url                  TEXT PRIMARY KEY REFERENCES jobs(url),
            work_mode            TEXT,
            remote_geo           TEXT,
            seniority            TEXT,
            role_family          TEXT,
            years_exp_min        INTEGER,
            years_exp_max        INTEGER,
            must_have_skills     TEXT,
            nice_to_have_skills  TEXT,
            tech_stack           TEXT,
            salary_min           INTEGER,
            salary_max           INTEGER,
            salary_currency      TEXT,
            visa_sponsorship     TEXT,
            red_flags            TEXT,
            enriched_at          TEXT,
            enrichment_status    TEXT,
            enrichment_model     TEXT
        )
    """)
    conn.commit()
    return conn


def save_jobs(
    conn: sqlite3.Connection, jobs: list[dict[str, Any]]
) -> tuple[int, int, list[dict[str, Any]]]:
    """Upsert jobs into the database. Returns (new_count, updated_count, new_jobs)."""
    now = datetime.now(timezone.utc).isoformat()[:10]
    new_count = 0
    updated_count = 0
    new_jobs: list[dict[str, Any]] = []

    for job in jobs:
        url = job.get("url", "")
        if not url:
            continue
        existing = conn.execute("SELECT 1 FROM jobs WHERE url = ?", (url,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO jobs (url, company, title, location, posted, ats, description, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    url,
                    job.get("company", ""),
                    job.get("title", ""),
                    job.get("location", ""),
                    job.get("posted", ""),
                    job.get("ats", ""),
                    job.get("description", ""),
                    now,
                    now,
                ),
            )
            new_count += 1
            new_jobs.append(job)
        else:
            conn.execute(
                "UPDATE jobs SET company=?, title=?, location=?, posted=?, ats=?, description=?, last_seen=? "
                "WHERE url=?",
                (
                    job.get("company", ""),
                    job.get("title", ""),
                    job.get("location", ""),
                    job.get("posted", ""),
                    job.get("ats", ""),
                    job.get("description", ""),
                    now,
                    url,
                ),
            )
            updated_count += 1

    conn.commit()
    return new_count, updated_count, new_jobs


def load_unenriched_jobs(conn: Any) -> list[dict[str, Any]]:
    """Return jobs that have never been enriched or whose last enrichment failed."""
    rows = conn.execute("""
        SELECT j.url, j.company, j.title, j.location, j.description
        FROM jobs j
        LEFT JOIN job_enrichments e ON j.url = e.url
        WHERE e.url IS NULL OR e.enrichment_status != 'ok'
    """).fetchall()
    return [
        {
            "url": row[0],
            "company": row[1],
            "title": row[2],
            "location": row[3],
            "description": row[4],
        }
        for row in rows
    ]


def save_enrichment(conn: Any, url: str, enrichment: dict[str, Any]) -> None:
    """Upsert one enrichment row into job_enrichments."""
    conn.execute(
        """
        INSERT OR REPLACE INTO job_enrichments (
            url, work_mode, remote_geo, seniority, role_family,
            years_exp_min, years_exp_max,
            must_have_skills, nice_to_have_skills, tech_stack,
            salary_min, salary_max, salary_currency,
            visa_sponsorship, red_flags,
            enriched_at, enrichment_status, enrichment_model
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            enrichment.get("work_mode"),
            enrichment.get("remote_geo"),
            enrichment.get("seniority"),
            enrichment.get("role_family"),
            enrichment.get("years_exp_min"),
            enrichment.get("years_exp_max"),
            enrichment.get("must_have_skills"),
            enrichment.get("nice_to_have_skills"),
            enrichment.get("tech_stack"),
            enrichment.get("salary_min"),
            enrichment.get("salary_max"),
            enrichment.get("salary_currency"),
            enrichment.get("visa_sponsorship"),
            enrichment.get("red_flags"),
            enrichment.get("enriched_at"),
            enrichment.get("enrichment_status"),
            enrichment.get("enrichment_model"),
        ),
    )
    conn.commit()
