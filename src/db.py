"""
db.py — SQLite persistence layer (local file or Turso libsql cloud).

Turso support uses the hrana HTTP API directly via `requests` — no compiled
extension needed, works on Windows and Linux alike.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

_ATS_TYPES = frozenset({
    "greenhouse",
    "lever",
    "ashby",
    "workable",
    "smartrecruiters",
})


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
            application_status TEXT,
            first_seen  TEXT NOT NULL,
            last_seen   TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS company_sources (
            id          INTEGER PRIMARY KEY,
            name        TEXT NOT NULL,
            ats_type    TEXT NOT NULL,
            ats_url     TEXT NOT NULL,
            slug        TEXT NOT NULL,
            enabled     INTEGER NOT NULL DEFAULT 1,
            source      TEXT,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_company_sources_url ON company_sources(ats_url)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_company_sources_ats_slug ON company_sources(ats_type, slug)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_company_sources_enabled ON company_sources(enabled)")
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN application_status TEXT")
    except Exception:
        pass
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
            required_skills      TEXT,
            preferred_skills     TEXT,
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_company_source(
    conn: Any,
    *,
    name: str,
    ats_type: str,
    ats_url: str,
    slug: str,
    enabled: bool = True,
    source: str = "manual",
) -> None:
    """Insert or update one company source row."""
    ats = (ats_type or "").strip().lower()
    if ats not in _ATS_TYPES:
        raise ValueError(f"Unsupported ats_type: {ats_type}")
    now = _utc_now_iso()
    params = (name, ats, ats_url, slug, 1 if enabled else 0, source, now, now)
    try:
        conn.execute(
            """
            INSERT INTO company_sources (name, ats_type, ats_url, slug, enabled, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ats_url) DO UPDATE SET
                name=excluded.name,
                ats_type=excluded.ats_type,
                slug=excluded.slug,
                enabled=excluded.enabled,
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            params,
        )
    except Exception:
        conn.execute(
            """
            UPDATE company_sources
            SET name=?, ats_url=?, enabled=?, source=?, updated_at=?
            WHERE ats_type=? AND slug=?
            """,
            (name, ats_url, 1 if enabled else 0, source, now, ats, slug),
        )
    conn.commit()


def list_company_sources(conn: Any, enabled_only: bool = False) -> list[dict[str, Any]]:
    """List company sources, optionally filtering to enabled rows only."""
    sql = """
        SELECT id, name, ats_type, ats_url, slug, enabled, source, created_at, updated_at
        FROM company_sources
    """
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY ats_type, slug"
    rows = conn.execute(sql).fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "ats_type": row[2],
            "ats_url": row[3],
            "slug": row[4],
            "enabled": bool(row[5]),
            "source": row[6] or "",
            "created_at": row[7],
            "updated_at": row[8],
        }
        for row in rows
    ]


def load_enabled_company_sources(conn: Any) -> list[dict[str, Any]]:
    """Return enabled company source rows in the scrape-friendly shape."""
    rows = list_company_sources(conn, enabled_only=True)
    return [
        {
            "name": row["name"],
            "ats_type": row["ats_type"],
            "ats_url": row["ats_url"],
            "slug": row["slug"],
            "enabled": True,
        }
        for row in rows
    ]


def set_company_source_enabled(conn: Any, slug_or_id: str, enabled: bool) -> int:
    """Enable/disable one company source by integer id or slug."""
    now = _utc_now_iso()
    try:
        row_id = int(slug_or_id)
        conn.execute(
            "UPDATE company_sources SET enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, now, row_id),
        )
    except ValueError:
        conn.execute(
            "UPDATE company_sources SET enabled=?, updated_at=? WHERE lower(slug)=lower(?)",
            (1 if enabled else 0, now, slug_or_id),
        )
    changed = conn.execute("SELECT changes()").fetchone()
    conn.commit()
    return int(changed[0]) if changed else 0


def find_company_by_url_or_slug_segment(conn: Any, slug: str, ats_url: str) -> str | None:
    """Return existing company name if URL exists or slug appears in URL path segments."""
    candidates = list_company_sources(conn, enabled_only=False)
    slug_l = (slug or "").strip().lower()
    for row in candidates:
        existing_url = row["ats_url"]
        if existing_url == ats_url:
            return row["name"]
        path_parts = [p.lower() for p in urlparse(existing_url).path.strip("/").split("/") if p]
        if slug_l and slug_l in path_parts:
            return row["name"]
    return None


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


def set_application_status(conn: Any, url: str, status: str | None) -> int:
    """Set application_status for a job URL. Returns changed row count."""
    normalized = (status or "").strip().lower() or None
    valid = {"applied", "interviewing", "offer", "rejected", "withdrawn", "not_applied"}
    if normalized not in valid and normalized is not None:
        raise ValueError(f"Invalid status: {status}")
    conn.execute("UPDATE jobs SET application_status=? WHERE url=?", (normalized, url))
    changed = conn.execute("SELECT changes()").fetchone()
    conn.commit()
    return int(changed[0]) if changed else 0


def prune_not_applied_older_than_days(conn: Any, days: int, dry_run: bool = True) -> int:
    """Prune jobs older than N days if not applied/interview pipeline and has parseable posted date."""
    if days <= 0:
        raise ValueError("days must be > 0")
    protected = ("applied", "interviewing", "offer", "rejected", "withdrawn")
    placeholders = ", ".join("?" for _ in protected)
    where = f"""
        (application_status IS NULL OR application_status = '' OR application_status = 'not_applied')
        AND (posted IS NOT NULL AND posted != '')
        AND date(posted) <= date('now', ?)
        AND (application_status IS NULL OR application_status NOT IN ({placeholders}))
    """
    params: tuple[Any, ...] = (f"-{days} day",) + protected
    if dry_run:
        row = conn.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params).fetchone()
        return int(row[0]) if row else 0
    conn.execute(f"DELETE FROM jobs WHERE {where}", params)
    changed = conn.execute("SELECT changes()").fetchone()
    conn.commit()
    return int(changed[0]) if changed else 0


def load_unenriched_jobs(conn: Any, force: bool = False) -> list[dict[str, Any]]:
    """Return jobs to enrich.

    force=False (default): only jobs never enriched or with a failed enrichment.
    force=True: all jobs that have a description, regardless of existing enrichment status.
    """
    if force:
        rows = conn.execute("""
            SELECT url, company, title, location, description
            FROM jobs
            WHERE description IS NOT NULL AND description != ''
        """).fetchall()
    else:
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
