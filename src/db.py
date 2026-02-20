"""
db.py — SQLite persistence layer (local file or Turso libsql cloud).

Turso support uses the hrana HTTP API directly via `requests` — no compiled
extension needed, works on Windows and Linux alike.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Turso HTTP API wrapper — sqlite3-compatible interface
# ---------------------------------------------------------------------------

class _TursoCursor:
    """Minimal sqlite3-compatible cursor backed by a Turso HTTP response."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self._idx = 0

    def fetchall(self) -> list[tuple]:
        return self._rows

    def fetchone(self) -> tuple | None:
        if self._idx < len(self._rows):
            row = self._rows[self._idx]
            self._idx += 1
            return row
        return None


class _TursoConnection:
    """
    sqlite3-compatible connection using the Turso hrana HTTP API.

    Each execute() call is a single HTTP POST to /v2/pipeline.
    commit() is a no-op — Turso auto-commits each statement.
    """

    def __init__(self, url: str, auth_token: str) -> None:
        import requests as req
        self._session = req.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        })
        # libsql://db-name.turso.io  →  https://db-name.turso.io/v2/pipeline
        self._endpoint = url.replace("libsql://", "https://") + "/v2/pipeline"

    @staticmethod
    def _to_arg(val: Any) -> dict:
        if val is None:
            return {"type": "null"}
        if isinstance(val, bool):
            return {"type": "integer", "value": str(int(val))}
        if isinstance(val, int):
            return {"type": "integer", "value": str(val)}
        if isinstance(val, float):
            return {"type": "float", "value": val}
        return {"type": "text", "value": str(val)}

    @staticmethod
    def _from_val(val: dict) -> Any:
        t = val.get("type", "null")
        if t == "null":
            return None
        if t == "integer":
            return int(val["value"])
        if t == "float":
            return float(val["value"])
        return val.get("value")

    def execute(self, sql: str, params: tuple = ()) -> _TursoCursor:
        payload = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": sql,
                        "args": [self._to_arg(p) for p in params],
                    },
                },
                {"type": "close"},
            ]
        }
        resp = self._session.post(self._endpoint, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        result = data["results"][0]
        if result["type"] == "error":
            raise Exception(result["error"]["message"])
        rows: list[tuple] = []
        if result["type"] == "ok":
            r = result["response"].get("result", {})
            for row in r.get("rows", []):
                rows.append(tuple(self._from_val(v) for v in row))
        return _TursoCursor(rows)

    def commit(self) -> None:
        pass  # Turso auto-commits each statement

    def close(self) -> None:
        self._session.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db(db_url: str, auth_token: str = "") -> Any:
    """Open the jobs database (local SQLite file or Turso libsql URL) and ensure the schema exists."""
    if db_url.startswith("libsql://"):
        conn: Any = _TursoConnection(db_url, auth_token)
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
            canada_eligible      TEXT,
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
    # Migrations: add new columns to existing DBs (try/except — column may already exist)
    for col in ("canada_eligible TEXT", "required_skills TEXT", "preferred_skills TEXT"):
        try:
            conn.execute(f"ALTER TABLE job_enrichments ADD COLUMN {col}")
            conn.commit()
        except Exception:
            pass  # column already exists
    conn.commit()
    return conn


def save_jobs(
    conn: Any, jobs: list[dict[str, Any]]
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
            url, work_mode, remote_geo, canada_eligible, seniority, role_family,
            years_exp_min, years_exp_max,
            required_skills, preferred_skills,
            salary_min, salary_max, salary_currency,
            visa_sponsorship, red_flags,
            enriched_at, enrichment_status, enrichment_model
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            enrichment.get("work_mode"),
            enrichment.get("remote_geo"),
            enrichment.get("canada_eligible"),
            enrichment.get("seniority"),
            enrichment.get("role_family"),
            enrichment.get("years_exp_min"),
            enrichment.get("years_exp_max"),
            enrichment.get("required_skills"),
            enrichment.get("preferred_skills"),
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
