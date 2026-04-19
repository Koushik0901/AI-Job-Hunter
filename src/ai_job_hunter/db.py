"""
db.py — SQLite persistence layer (local file or Turso libsql cloud).

Turso support uses the hrana HTTP API directly via `requests` — no compiled
extension needed, works on Windows and Linux alike.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

_ATS_TYPES = frozenset(
    {
        "greenhouse",
        "lever",
        "ashby",
        "workable",
        "smartrecruiters",
        "recruitee",
        "teamtailor",
    }
)

_ZERO_WIDTH_CHARS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060]")
_MALFORMED_NBSP_RE = re.compile(
    r"&(?:(?:nsbp)|(?:nbps)|(?:bnsp)|(?:bnps))(?:;)?", re.IGNORECASE
)
_INLINE_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
_OPEN_PAREN_SPACE_RE = re.compile(r"\(\s+")
_CLOSE_PAREN_SPACE_RE = re.compile(r"\s+\)")
_LIST_LINE_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _column_exists(conn: Any, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except Exception:
        return False
    return any(str(row[1]) == column for row in rows)


def _add_column_if_missing(conn: Any, table: str, column: str, ddl: str) -> None:
    if _column_exists(conn, table, column):
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    except Exception:
        # Race between readers or a concurrent migrator — safe to ignore.
        pass


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
        self._session.headers.update(
            {
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
            }
        )
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
        # Each execute() call is a single HTTP POST to /v2/pipeline.
        # We wrap it in a single-request pipeline.
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

    def __enter__(self) -> _TursoConnection:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # We DON'T close the underlying session if we're pooling
        pass

    def close(self) -> None:
        # Manual close if really needed
        self._session.close()


# ---------------------------------------------------------------------------
# Connection Pooling for Turso
# ---------------------------------------------------------------------------

_TURSO_CONNECTION_CACHE: dict[str, _TursoConnection] = {}


def _get_turso_connection(url: str, auth_token: str) -> _TursoConnection:
    key = f"{url}|{auth_token}"
    if key not in _TURSO_CONNECTION_CACHE:
        _TURSO_CONNECTION_CACHE[key] = _TursoConnection(url, auth_token)
    return _TURSO_CONNECTION_CACHE[key]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_db(db_url: str, auth_token: str = "") -> Any:
    """Open the jobs database (local SQLite file or Turso libsql URL) and ensure the schema exists."""
    if db_url.startswith("libsql://"):
        conn: Any = _get_turso_connection(db_url, auth_token)
    else:
        conn = sqlite3.connect(db_url)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id          TEXT,
            url         TEXT PRIMARY KEY,
            company     TEXT,
            title       TEXT,
            location    TEXT,
            posted      TEXT,
            ats         TEXT,
            description TEXT,
            application_status TEXT,
            source      TEXT NOT NULL DEFAULT 'scraped',
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
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_company_sources_url ON company_sources(ats_url)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_company_sources_ats_slug ON company_sources(ats_type, slug)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_company_sources_enabled ON company_sources(enabled)"
    )
    _add_column_if_missing(conn, "jobs", "id", "id TEXT")
    _add_column_if_missing(conn, "jobs", "application_status", "application_status TEXT")
    _add_column_if_missing(conn, "jobs", "source", "source TEXT NOT NULL DEFAULT 'scraped'")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_id ON jobs(id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_enrichments (
            job_id               TEXT UNIQUE REFERENCES jobs(id),
            url                  TEXT PRIMARY KEY REFERENCES jobs(url),
            work_mode            TEXT,
            remote_geo           TEXT,
            canada_eligible      TEXT,
            seniority            TEXT,
            role_family          TEXT,
            years_exp_min        INTEGER,
            years_exp_max        INTEGER,
            minimum_degree       TEXT,
            required_skills      TEXT,
            preferred_skills     TEXT,
            formatted_description TEXT,
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
    _add_column_if_missing(conn, "job_enrichments", "job_id", "job_id TEXT")
    _add_column_if_missing(conn, "job_enrichments", "minimum_degree", "minimum_degree TEXT")
    _add_column_if_missing(conn, "job_enrichments", "formatted_description", "formatted_description TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_tracking (
            job_id               TEXT UNIQUE REFERENCES jobs(id),
            url                  TEXT PRIMARY KEY REFERENCES jobs(url),
            status               TEXT NOT NULL DEFAULT 'not_applied',
            priority             TEXT NOT NULL DEFAULT 'medium',
            pinned               INTEGER NOT NULL DEFAULT 0,
            applied_at           TEXT,
            next_step            TEXT,
            target_compensation  TEXT,
            staging_entered_at   TEXT,
            staging_due_at       TEXT,
            processing_state     TEXT NOT NULL DEFAULT 'ready',
            processing_step      TEXT NOT NULL DEFAULT 'complete',
            processing_message   TEXT NOT NULL DEFAULT 'Job is ready.',
            processing_last_at   TEXT,
            processing_last_error TEXT,
            processing_retry_count INTEGER NOT NULL DEFAULT 0,
            updated_at           TEXT NOT NULL
        )
    """)
    _add_column_if_missing(conn, "job_tracking", "job_id", "job_id TEXT")
    _add_column_if_missing(conn, "job_tracking", "staging_entered_at", "staging_entered_at TEXT")
    _add_column_if_missing(conn, "job_tracking", "staging_due_at", "staging_due_at TEXT")
    _add_column_if_missing(conn, "job_tracking", "pinned", "pinned INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "job_tracking", "processing_state", "processing_state TEXT NOT NULL DEFAULT 'ready'")
    _add_column_if_missing(conn, "job_tracking", "processing_step", "processing_step TEXT NOT NULL DEFAULT 'complete'")
    _add_column_if_missing(conn, "job_tracking", "processing_message", "processing_message TEXT NOT NULL DEFAULT 'Job is ready.'")
    _add_column_if_missing(conn, "job_tracking", "processing_last_at", "processing_last_at TEXT")
    _add_column_if_missing(conn, "job_tracking", "processing_last_error", "processing_last_error TEXT")
    _add_column_if_missing(conn, "job_tracking", "processing_retry_count", "processing_retry_count INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_tracking_status ON job_tracking(status)"
    )
    if _column_exists(conn, "job_tracking", "staging_due_at"):
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_tracking_staging_due ON job_tracking(staging_due_at)"
        )
    if _column_exists(conn, "job_tracking", "staging_due_at"):
        conn.execute(
            """
            UPDATE job_tracking
            SET staging_entered_at = COALESCE(staging_entered_at, updated_at),
                staging_due_at = COALESCE(
                    staging_due_at,
                    datetime(COALESCE(staging_entered_at, updated_at), '+48 hours')
                )
            WHERE status = 'staging'
            """
        )
    _migrate_job_processing_states(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_suppressions (
            id          INTEGER PRIMARY KEY,
            job_id      TEXT UNIQUE REFERENCES jobs(id),
            url         TEXT NOT NULL UNIQUE,
            company     TEXT,
            reason      TEXT,
            scope       TEXT NOT NULL DEFAULT 'url',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL,
            created_by  TEXT NOT NULL DEFAULT 'ui',
            active      INTEGER NOT NULL DEFAULT 1
        )
    """)
    _add_column_if_missing(conn, "job_suppressions", "job_id", "job_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_suppressions_active_created ON job_suppressions(active, created_at DESC)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_events (
            id          INTEGER PRIMARY KEY,
            job_id      TEXT NOT NULL REFERENCES jobs(id),
            url         TEXT NOT NULL REFERENCES jobs(url),
            event_type  TEXT NOT NULL,
            title       TEXT NOT NULL,
            body        TEXT,
            event_at    TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)
    _add_column_if_missing(conn, "job_events", "job_id", "job_id TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_events_url ON job_events(url)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_events_job_id ON job_events(job_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_events_event_at ON job_events(event_at DESC)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candidate_profile (
            id                        INTEGER PRIMARY KEY,
            years_experience          INTEGER NOT NULL DEFAULT 0,
            skills                    TEXT NOT NULL DEFAULT '[]',
            desired_job_titles        TEXT NOT NULL DEFAULT '[]',
            target_role_families      TEXT NOT NULL DEFAULT '[]',
            requires_visa_sponsorship INTEGER NOT NULL DEFAULT 0,
            education                 TEXT NOT NULL DEFAULT '[]',
            degree                    TEXT,
            degree_field              TEXT,
            score_version             INTEGER NOT NULL DEFAULT 1,
            updated_at                TEXT NOT NULL
        )
    """)
    _add_column_if_missing(conn, "candidate_profile", "education", "education TEXT NOT NULL DEFAULT '[]'")
    _add_column_if_missing(conn, "candidate_profile", "degree", "degree TEXT")
    _add_column_if_missing(conn, "candidate_profile", "degree_field", "degree_field TEXT")
    _add_column_if_missing(conn, "candidate_profile", "score_version", "score_version INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "candidate_profile", "desired_job_titles", "desired_job_titles TEXT NOT NULL DEFAULT '[]'")
    _add_column_if_missing(conn, "candidate_profile", "full_name", "full_name TEXT")
    _add_column_if_missing(conn, "candidate_profile", "email", "email TEXT")
    _add_column_if_missing(conn, "candidate_profile", "phone", "phone TEXT")
    _add_column_if_missing(conn, "candidate_profile", "linkedin_url", "linkedin_url TEXT")
    _add_column_if_missing(conn, "candidate_profile", "portfolio_url", "portfolio_url TEXT")
    _add_column_if_missing(conn, "candidate_profile", "city", "city TEXT")
    _add_column_if_missing(conn, "candidate_profile", "country", "country TEXT DEFAULT 'Canada'")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_match_scores (
            job_id            TEXT UNIQUE REFERENCES jobs(id),
            url               TEXT PRIMARY KEY REFERENCES jobs(url),
            profile_version   INTEGER NOT NULL,
            score             INTEGER NOT NULL,
            raw_score         INTEGER NOT NULL DEFAULT 0,
            band              TEXT NOT NULL,
            breakdown_json    TEXT NOT NULL,
            reasons_json      TEXT NOT NULL,
            confidence        TEXT NOT NULL,
            computed_at       TEXT NOT NULL,
            source_hash       TEXT NOT NULL
        )
    """)
    _add_column_if_missing(conn, "job_match_scores", "job_id", "job_id TEXT")
    _add_column_if_missing(conn, "job_match_scores", "raw_score", "raw_score INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_job_match_scores_job_id ON job_match_scores(job_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_match_scores_profile_score ON job_match_scores(profile_version, score DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_match_scores_computed_at ON job_match_scores(computed_at DESC)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workspace_operations (
            id           TEXT PRIMARY KEY,
            kind         TEXT NOT NULL,
            status       TEXT NOT NULL,
            params_json  TEXT NOT NULL DEFAULT '{}',
            summary_json TEXT NOT NULL DEFAULT '{}',
            log_tail     TEXT NOT NULL DEFAULT '',
            started_at   TEXT NOT NULL,
            finished_at  TEXT,
            error        TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_dashboard_snapshots (
            job_id               TEXT NOT NULL REFERENCES jobs(id),
            profile_version      INTEGER NOT NULL,
            url                  TEXT NOT NULL,
            company              TEXT NOT NULL DEFAULT '',
            title                TEXT NOT NULL DEFAULT '',
            location             TEXT NOT NULL DEFAULT '',
            posted               TEXT NOT NULL DEFAULT '',
            ats                  TEXT NOT NULL DEFAULT '',
            status               TEXT NOT NULL DEFAULT 'not_applied',
            priority             TEXT NOT NULL DEFAULT 'medium',
            pinned               INTEGER NOT NULL DEFAULT 0,
            updated_at           TEXT,
            match_score          INTEGER,
            raw_score            INTEGER,
            match_band           TEXT,
            desired_title_match  INTEGER NOT NULL DEFAULT 0,
            snapshot_updated_at  TEXT NOT NULL,
            payload_json         TEXT NOT NULL DEFAULT '{}',
            PRIMARY KEY (job_id, profile_version)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_dashboard_snapshots_profile_score ON job_dashboard_snapshots(profile_version, match_score DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_dashboard_snapshots_profile_status ON job_dashboard_snapshots(profile_version, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_dashboard_snapshots_profile_updated ON job_dashboard_snapshots(profile_version, updated_at DESC)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_decisions (
            job_id                   TEXT PRIMARY KEY REFERENCES jobs(id),
            recommendation_override  TEXT NOT NULL,
            note                     TEXT,
            updated_at               TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_actions (
            id           INTEGER PRIMARY KEY,
            job_id       TEXT NOT NULL REFERENCES jobs(id),
            action_type  TEXT NOT NULL,
            priority     TEXT NOT NULL,
            due_at       TEXT NOT NULL,
            reason       TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'pending',
            source       TEXT NOT NULL DEFAULT 'system',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL,
            completed_at TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_actions_status_due ON job_actions(status, due_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_actions_job_type ON job_actions(job_id, action_type)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_outcomes (
            id           INTEGER PRIMARY KEY,
            job_id       TEXT NOT NULL UNIQUE REFERENCES jobs(id),
            outcome_type TEXT NOT NULL,
            reason_code  TEXT,
            details_json TEXT NOT NULL DEFAULT '{}',
            recorded_at  TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_outcomes_type_recorded ON job_outcomes(outcome_type, recorded_at DESC)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_briefings (
            brief_date             TEXT PRIMARY KEY,
            generated_at           TEXT NOT NULL,
            payload_json           TEXT NOT NULL DEFAULT '{}',
            telegram_sent_at       TEXT,
            telegram_message_hash  TEXT,
            trigger_source         TEXT NOT NULL DEFAULT 'scheduled'
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_daily_briefings_generated ON daily_briefings(generated_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_operations_started ON workspace_operations(started_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_operations_kind_status ON workspace_operations(kind, status)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS base_documents (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_type    TEXT NOT NULL,
            filename    TEXT NOT NULL,
            content_md  TEXT NOT NULL,
            content_raw BLOB,
            mime_type   TEXT,
            is_default  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS application_queue (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id       TEXT NOT NULL REFERENCES jobs(id),
            status       TEXT NOT NULL DEFAULT 'queued',
            sort_order   INTEGER NOT NULL DEFAULT 0,
            queued_at    TEXT NOT NULL DEFAULT (datetime('now')),
            processed_at TEXT
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_application_queue_job_id ON application_queue(job_id)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_artifacts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id        TEXT NOT NULL REFERENCES jobs(id),
            artifact_type TEXT NOT NULL,
            content_md    TEXT NOT NULL,
            base_doc_id   INTEGER REFERENCES base_documents(id),
            version       INTEGER NOT NULL DEFAULT 1,
            is_active     INTEGER NOT NULL DEFAULT 1,
            generated_by  TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_artifacts_job_type ON job_artifacts(job_id, artifact_type)"
    )
    try:
        rows = conn.execute(
            "SELECT url FROM jobs WHERE id IS NULL OR trim(id) = ''"
        ).fetchall()
        for row in rows:
            if not row or not row[0]:
                continue
            conn.execute(
                "UPDATE jobs SET id = ? WHERE url = ?", (str(uuid.uuid4()), str(row[0]))
            )
    except Exception:
        pass
    try:
        conn.execute(
            """
            UPDATE job_enrichments
            SET job_id = (
                SELECT j.id FROM jobs j WHERE j.url = job_enrichments.url
            )
            WHERE job_id IS NULL OR trim(job_id) = ''
            """
        )
    except Exception:
        pass
    try:
        conn.execute(
            """
            UPDATE job_tracking
            SET job_id = (
                SELECT j.id FROM jobs j WHERE j.url = job_tracking.url
            )
            WHERE job_id IS NULL OR trim(job_id) = ''
            """
        )
    except Exception:
        pass
    try:
        conn.execute(
            """
            UPDATE job_suppressions
            SET job_id = (
                SELECT j.id FROM jobs j WHERE j.url = job_suppressions.url
            )
            WHERE job_id IS NULL OR trim(job_id) = ''
            """
        )
    except Exception:
        pass
    try:
        conn.execute(
            """
            UPDATE job_events
            SET job_id = (
                SELECT j.id FROM jobs j WHERE j.url = job_events.url
            )
            WHERE job_id IS NULL OR trim(job_id) = ''
            """
        )
    except Exception:
        pass
    try:
        conn.execute(
            """
            UPDATE job_match_scores
            SET job_id = (
                SELECT j.id FROM jobs j WHERE j.url = job_match_scores.url
            )
            WHERE job_id IS NULL OR trim(job_id) = ''
            """
        )
    except Exception:
        pass
    conn.commit()
    return conn


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(raw: Any) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{normalized}T00:00:00+00:00")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _job_id_for_url(conn: Any, url: str) -> str | None:
    row = conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
    if not row or not row[0]:
        return None
    return str(row[0])


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


def get_company_source_by_id(conn: Any, row_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, name, ats_type, ats_url, slug, enabled, source, created_at, updated_at
        FROM company_sources
        WHERE id = ?
        """,
        (row_id,),
    ).fetchone()
    if not row:
        return None
    return {
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


def update_company_source(
    conn: Any,
    row_id: int,
    *,
    enabled: bool | None = None,
    name: str | None = None,
    source: str | None = None,
) -> dict[str, Any] | None:
    existing = get_company_source_by_id(conn, row_id)
    if not existing:
        return None
    next_enabled = existing["enabled"] if enabled is None else bool(enabled)
    next_name = (
        existing["name"] if name is None else str(name).strip() or existing["name"]
    )
    next_source = existing["source"] if source is None else str(source).strip()
    now = _utc_now_iso()
    conn.execute(
        """
        UPDATE company_sources
        SET name = ?, enabled = ?, source = ?, updated_at = ?
        WHERE id = ?
        """,
        (next_name, 1 if next_enabled else 0, next_source, now, row_id),
    )
    conn.commit()
    return get_company_source_by_id(conn, row_id)


def find_company_by_url_or_slug_segment(
    conn: Any, slug: str, ats_url: str
) -> str | None:
    """Return existing company name if URL exists or slug appears in URL path segments."""
    candidates = list_company_sources(conn, enabled_only=False)
    slug_l = (slug or "").strip().lower()
    for row in candidates:
        existing_url = row["ats_url"]
        if existing_url == ats_url:
            return row["name"]
        path_parts = [
            p.lower() for p in urlparse(existing_url).path.strip("/").split("/") if p
        ]
        if slug_l and slug_l in path_parts:
            return row["name"]
    return None


def _normalize_description_entities(text: str) -> str:
    value = str(text or "")
    for _ in range(3):
        value = _MALFORMED_NBSP_RE.sub("&nbsp;", value)
        next_value = html.unescape(value)
        if next_value == value:
            break
        value = next_value
    return value


def _normalize_description_line(line: str) -> str:
    value = _ZERO_WIDTH_CHARS_RE.sub("", str(line or "").replace("\t", " "))
    value = value.replace("\xa0", " ")
    value = _INLINE_SPACE_RE.sub(" ", value)
    value = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", value)
    value = _OPEN_PAREN_SPACE_RE.sub("(", value)
    value = _CLOSE_PAREN_SPACE_RE.sub(")", value)
    return value.strip()


def normalize_description_text(raw: Any) -> str:
    """Normalize scraped/manual job descriptions before persistence."""
    if raw is None:
        return ""
    text = (
        _normalize_description_entities(str(raw))
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    text = _ZERO_WIDTH_CHARS_RE.sub("", text)
    text = text.replace("\xa0", " ")

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)

    cleaned_blocks: list[str] = []
    for block in blocks:
        cleaned_lines = [_normalize_description_line(line) for line in block]
        cleaned_lines = [line for line in cleaned_lines if line]
        if not cleaned_lines:
            continue
        if len(cleaned_lines) > 1 and any(_LIST_LINE_RE.match(line) for line in block):
            cleaned_blocks.append("\n".join(cleaned_lines))
        else:
            cleaned_blocks.append(" ".join(cleaned_lines))

    return "\n\n".join(cleaned_blocks).strip()


def save_jobs(
    conn: Any, jobs: list[dict[str, Any]]
) -> tuple[int, int, list[dict[str, Any]]]:
    """Upsert jobs into the database. Returns (new_count, updated_count, new_jobs)."""
    now = datetime.now(timezone.utc).isoformat()[:10]
    new_count = 0
    updated_count = 0
    new_jobs: list[dict[str, Any]] = []
    suppressed_urls = load_active_suppressed_urls(conn)

    for job in jobs:
        url = job.get("url", "")
        if not url:
            continue
        if url in suppressed_urls:
            continue
        normalized_job = dict(job)
        normalized_job["description"] = normalize_description_text(
            job.get("description", "")
        )
        source = str(job.get("source") or "scraped").strip().lower()
        if not source:
            source = "scraped"
        existing = conn.execute("SELECT 1 FROM jobs WHERE url = ?", (url,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO jobs (id, url, company, title, location, posted, ats, description, source, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    url,
                    job.get("company", ""),
                    job.get("title", ""),
                    job.get("location", ""),
                    job.get("posted", ""),
                    job.get("ats", ""),
                    normalized_job["description"],
                    source,
                    now,
                    now,
                ),
            )
            new_count += 1
            new_jobs.append(normalized_job)
        else:
            conn.execute(
                "UPDATE jobs SET company=?, title=?, location=?, posted=?, ats=?, description=?, "
                "source=CASE WHEN source='manual' THEN source ELSE ? END, last_seen=? "
                "WHERE url=?",
                (
                    job.get("company", ""),
                    job.get("title", ""),
                    job.get("location", ""),
                    job.get("posted", ""),
                    job.get("ats", ""),
                    normalized_job["description"],
                    source,
                    now,
                    url,
                ),
            )
            updated_count += 1

    conn.commit()
    return new_count, updated_count, new_jobs


_PROCESSING_DEFAULTS = {
    "state": "ready",
    "step": "complete",
    "message": "Job is ready.",
    "last_processed_at": None,
    "last_error": None,
    "retry_count": 0,
}


def _migrate_job_processing_states(conn: Any) -> None:
    """Backfill legacy job_processing_states rows into job_tracking columns, then drop the table."""
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='job_processing_states'"
        ).fetchone()
    except Exception:
        return
    if not exists:
        return
    try:
        conn.execute(
            """
            UPDATE job_tracking
            SET processing_state = COALESCE(
                    (SELECT ps.state FROM job_processing_states ps WHERE ps.job_id = job_tracking.job_id),
                    processing_state
                ),
                processing_step = COALESCE(
                    (SELECT ps.step FROM job_processing_states ps WHERE ps.job_id = job_tracking.job_id),
                    processing_step
                ),
                processing_message = COALESCE(
                    (SELECT ps.message FROM job_processing_states ps WHERE ps.job_id = job_tracking.job_id),
                    processing_message
                ),
                processing_last_at = COALESCE(
                    (SELECT ps.last_processed_at FROM job_processing_states ps WHERE ps.job_id = job_tracking.job_id),
                    processing_last_at
                ),
                processing_last_error = COALESCE(
                    (SELECT ps.last_error FROM job_processing_states ps WHERE ps.job_id = job_tracking.job_id),
                    processing_last_error
                ),
                processing_retry_count = COALESCE(
                    (SELECT ps.retry_count FROM job_processing_states ps WHERE ps.job_id = job_tracking.job_id),
                    processing_retry_count
                )
            WHERE job_id IN (SELECT job_id FROM job_processing_states)
            """
        )
        conn.execute("DROP TABLE job_processing_states")
        conn.commit()
    except Exception:
        # Migration is best-effort; the merged columns are source of truth regardless.
        pass


def get_job_processing_state(conn: Any, job_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT processing_state, processing_step, processing_message,
               processing_last_at, processing_last_error, processing_retry_count
        FROM job_tracking
        WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()
    if not row:
        return dict(_PROCESSING_DEFAULTS)
    return {
        "state": str(row[0] or "ready"),
        "step": str(row[1] or "complete"),
        "message": str(row[2] or "Job is ready."),
        "last_processed_at": str(row[3] or "") or None,
        "last_error": str(row[4] or "") or None,
        "retry_count": int(row[5] or 0),
    }


def upsert_job_processing_state(
    conn: Any,
    job_id: str,
    *,
    state: str,
    step: str,
    message: str,
    last_processed_at: str | None = None,
    last_error: str | None = None,
    increment_retry: bool = False,
) -> dict[str, Any]:
    existing = conn.execute(
        "SELECT url, processing_retry_count FROM job_tracking WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    retry_count = int(existing[1] or 0) if existing else 0
    if increment_retry:
        retry_count += 1
    now = _utc_now_iso()
    if existing:
        conn.execute(
            """
            UPDATE job_tracking
            SET processing_state = ?,
                processing_step = ?,
                processing_message = ?,
                processing_last_at = COALESCE(?, processing_last_at),
                processing_last_error = ?,
                processing_retry_count = ?,
                updated_at = ?
            WHERE job_id = ?
            """,
            (state, step, message, last_processed_at, last_error, retry_count, now, job_id),
        )
    else:
        url_row = conn.execute(
            "SELECT url FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not url_row or not url_row[0]:
            return dict(_PROCESSING_DEFAULTS)
        conn.execute(
            """
            INSERT INTO job_tracking (
                job_id, url, status, priority, pinned,
                processing_state, processing_step, processing_message,
                processing_last_at, processing_last_error, processing_retry_count,
                updated_at
            ) VALUES (?, ?, 'not_applied', 'medium', 0, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                str(url_row[0]),
                state,
                step,
                message,
                last_processed_at,
                last_error,
                retry_count,
                now,
            ),
        )
    conn.commit()
    return get_job_processing_state(conn, job_id)


def clear_job_processing_state(conn: Any, job_id: str) -> None:
    now = _utc_now_iso()
    conn.execute(
        """
        UPDATE job_tracking
        SET processing_state = 'ready',
            processing_step = 'complete',
            processing_message = 'Job is ready.',
            processing_last_at = NULL,
            processing_last_error = NULL,
            processing_retry_count = 0,
            updated_at = ?
        WHERE job_id = ?
        """,
        (now, job_id),
    )
    conn.commit()


def load_active_suppressed_urls(conn: Any) -> set[str]:
    rows = conn.execute("SELECT url FROM job_suppressions WHERE active = 1").fetchall()
    return {str(row[0]) for row in rows if row and row[0]}


def list_overdue_staging_jobs(
    conn: Any, *, reference_at: datetime | None = None
) -> list[dict[str, Any]]:
    reference = reference_at or datetime.now(timezone.utc)
    rows = conn.execute(
        """
        WITH staging_jobs AS (
            SELECT
                j.id,
                j.url,
                j.company,
                j.title,
                j.location,
                j.posted,
                t.staging_entered_at,
                t.staging_due_at,
                COALESCE(t.staging_entered_at, t.updated_at, j.last_seen, j.posted) AS effective_entered_at,
                COALESCE(
                    t.staging_due_at,
                    datetime(COALESCE(t.staging_entered_at, t.updated_at, j.last_seen, j.posted), '+48 hours')
                ) AS effective_due_at
            FROM jobs j
            LEFT JOIN job_tracking t ON t.job_id = j.id
            WHERE COALESCE(t.status, j.application_status) = 'staging'
              AND NOT EXISTS (
                  SELECT 1
                  FROM job_suppressions s
                  WHERE s.active = 1
                    AND (
                        s.job_id = j.id
                        OR ((s.job_id IS NULL OR trim(s.job_id) = '') AND s.url = j.url)
                    )
              )
        )
        SELECT
            id,
            url,
            company,
            title,
            location,
            posted,
            staging_entered_at,
            staging_due_at,
            effective_entered_at,
            effective_due_at
        FROM staging_jobs
        WHERE datetime(effective_due_at) <= datetime(?)
        ORDER BY datetime(effective_due_at) ASC, lower(company) ASC, lower(title) ASC
        """,
        (reference.isoformat(),),
    ).fetchall()
    overdue_jobs: list[dict[str, Any]] = []
    for row in rows:
        entered_at = _parse_timestamp(row[6] or row[8])
        due_at = _parse_timestamp(row[7] or row[9])
        age_hours: int | None = None
        overdue_hours: int | None = None
        if entered_at is not None:
            age_hours = max(0, int((reference - entered_at).total_seconds() // 3600))
        if due_at is not None:
            overdue_hours = max(0, int((reference - due_at).total_seconds() // 3600))
        overdue_jobs.append(
            {
                "job_id": str(row[0] or ""),
                "url": str(row[1] or ""),
                "company": str(row[2] or ""),
                "title": str(row[3] or ""),
                "location": str(row[4] or ""),
                "posted": str(row[5] or ""),
                "staging_entered_at": entered_at.isoformat() if entered_at else None,
                "staging_due_at": due_at.isoformat() if due_at else None,
                "staging_age_hours": age_hours,
                "overdue_hours": overdue_hours,
            }
        )
    return overdue_jobs


def is_job_suppressed(conn: Any, url: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM job_suppressions WHERE url = ? AND active = 1 LIMIT 1",
        (url,),
    ).fetchone()
    return row is not None


def is_job_suppressed_id(conn: Any, job_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM job_suppressions WHERE job_id = ? AND active = 1 LIMIT 1",
        (job_id,),
    ).fetchone()
    return row is not None


def suppress_job_url(
    conn: Any,
    *,
    url: str,
    reason: str | None = None,
    created_by: str = "ui",
) -> None:
    existing_company_row = conn.execute(
        "SELECT company FROM jobs WHERE url = ? LIMIT 1", (url,)
    ).fetchone()
    job_id = _job_id_for_url(conn, url)
    company = existing_company_row[0] if existing_company_row else None
    now = _utc_now_iso()
    conn.execute(
        """
        INSERT INTO job_suppressions (job_id, url, company, reason, scope, created_at, updated_at, created_by, active)
        VALUES (?, ?, ?, ?, 'url', ?, ?, ?, 1)
        ON CONFLICT(url) DO UPDATE SET
            job_id = COALESCE(excluded.job_id, job_suppressions.job_id),
            company = COALESCE(excluded.company, job_suppressions.company),
            reason = excluded.reason,
            updated_at = excluded.updated_at,
            created_by = excluded.created_by,
            active = 1
        """,
        (job_id, url, company, reason, now, now, created_by),
    )
    conn.commit()


def suppress_job_id(
    conn: Any,
    *,
    job_id: str,
    reason: str | None = None,
    created_by: str = "ui",
) -> None:
    row = conn.execute(
        "SELECT url, company FROM jobs WHERE id = ? LIMIT 1",
        (job_id,),
    ).fetchone()
    if not row or not row[0]:
        raise ValueError("job not found")
    suppress_job_url(
        conn,
        url=str(row[0]),
        reason=reason,
        created_by=created_by,
    )


def unsuppress_job_url(conn: Any, url: str) -> int:
    now = _utc_now_iso()
    conn.execute(
        "UPDATE job_suppressions SET active = 0, updated_at = ? WHERE url = ? AND active = 1",
        (now, url),
    )
    changed = conn.execute("SELECT changes()").fetchone()
    conn.commit()
    return int(changed[0]) if changed else 0


def unsuppress_job_id(conn: Any, job_id: str) -> int:
    now = _utc_now_iso()
    conn.execute(
        "UPDATE job_suppressions SET active = 0, updated_at = ? WHERE job_id = ? AND active = 1",
        (now, job_id),
    )
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


def load_jobs_for_jd_reformat(conn: Any, *, missing_only: bool) -> list[dict[str, Any]]:
    """Return enriched jobs eligible for description reformat pass."""
    missing_clause = (
        "AND (e.formatted_description IS NULL OR trim(e.formatted_description) = '')"
        if missing_only
        else ""
    )
    rows = conn.execute(
        f"""
        SELECT j.url, j.company, j.title, j.location, j.description
        FROM jobs j
        INNER JOIN job_enrichments e ON j.url = e.url
        WHERE
            j.description IS NOT NULL
            AND j.description != ''
            AND e.enrichment_status = 'ok'
            {missing_clause}
        """
    ).fetchall()
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


def save_formatted_description(
    conn: Any, url: str, formatted_description: str | None
) -> None:
    """Update formatted_description for an existing enrichment row."""
    job_id = _job_id_for_url(conn, url)
    conn.execute(
        """
        UPDATE job_enrichments
        SET job_id = COALESCE(job_id, ?), formatted_description = ?
        WHERE url = ? AND enrichment_status = 'ok'
        """,
        (job_id, formatted_description, url),
    )
    conn.commit()


def save_enrichment(conn: Any, url: str, enrichment: dict[str, Any]) -> None:
    """Upsert one enrichment row into job_enrichments."""
    job_id = _job_id_for_url(conn, url)
    conn.execute(
        """
        INSERT OR REPLACE INTO job_enrichments (
            job_id, url, work_mode, remote_geo, canada_eligible, seniority, role_family,
            years_exp_min, years_exp_max, minimum_degree,
            required_skills, preferred_skills, formatted_description,
            salary_min, salary_max, salary_currency,
            visa_sponsorship, red_flags,
            enriched_at, enrichment_status, enrichment_model
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            url,
            enrichment.get("work_mode"),
            enrichment.get("remote_geo"),
            enrichment.get("canada_eligible"),
            enrichment.get("seniority"),
            enrichment.get("role_family"),
            enrichment.get("years_exp_min"),
            enrichment.get("years_exp_max"),
            enrichment.get("minimum_degree"),
            enrichment.get("required_skills"),
            enrichment.get("preferred_skills"),
            enrichment.get("formatted_description"),
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


def load_enrichments_for_urls(conn: Any, urls: list[str]) -> dict[str, dict[str, Any]]:
    if not urls:
        return {}
    placeholders = ", ".join("?" for _ in urls)
    rows = conn.execute(
        f"""
        SELECT
            url, work_mode, remote_geo, canada_eligible, seniority, role_family, years_exp_min, years_exp_max,
            minimum_degree, required_skills, preferred_skills, formatted_description, salary_min, salary_max,
            salary_currency, visa_sponsorship, red_flags, enriched_at, enrichment_status, enrichment_model
        FROM job_enrichments
        WHERE url IN ({placeholders})
        """,
        tuple(urls),
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out[row[0]] = {
            "work_mode": row[1],
            "remote_geo": row[2],
            "canada_eligible": row[3],
            "seniority": row[4],
            "role_family": row[5],
            "years_exp_min": row[6],
            "years_exp_max": row[7],
            "minimum_degree": row[8],
            "required_skills": _parse_json_array(row[9]),
            "preferred_skills": _parse_json_array(row[10]),
            "formatted_description": row[11],
            "salary_min": row[12],
            "salary_max": row[13],
            "salary_currency": row[14],
            "visa_sponsorship": row[15],
            "red_flags": _parse_json_array(row[16]),
            "enriched_at": row[17],
            "enrichment_status": row[18],
            "enrichment_model": row[19],
        }
    return out


def _parse_json_array(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    if not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(v).strip() for v in parsed if str(v).strip()]


def get_candidate_profile(conn: Any) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT years_experience, skills, desired_job_titles, target_role_families, requires_visa_sponsorship, education, degree, degree_field, score_version, updated_at,
               full_name, email, phone, linkedin_url, portfolio_url, city, country
        FROM candidate_profile
        WHERE id = 1
        """
    ).fetchone()
    if not row:
        return {
            "years_experience": 0,
            "skills": [],
            "desired_job_titles": [],
            "target_role_families": [],
            "requires_visa_sponsorship": False,
            "education": [],
            "degree": None,
            "degree_field": None,
            "score_version": 1,
            "updated_at": None,
            "full_name": None,
            "email": None,
            "phone": None,
            "linkedin_url": None,
            "portfolio_url": None,
            "city": None,
            "country": None,
        }
    education = _parse_education_array(row[5])
    if not education and (row[6] or row[7]):
        education = [
            {
                "degree": str(row[6] or "").strip(),
                "field": (str(row[7]).strip() or None) if row[7] is not None else None,
            }
        ]
    return {
        "years_experience": int(row[0] or 0),
        "skills": _parse_json_array(row[1]),
        "desired_job_titles": _parse_json_array(row[2]),
        "target_role_families": _parse_json_array(row[3]),
        "requires_visa_sponsorship": bool(row[4]),
        "education": education,
        "degree": row[6],
        "degree_field": row[7],
        "score_version": int(row[8] or 1),
        "updated_at": row[9],
        "full_name": row[10],
        "email": row[11],
        "phone": row[12],
        "linkedin_url": row[13],
        "portfolio_url": row[14],
        "city": row[15],
        "country": row[16],
    }


def upsert_candidate_profile(conn: Any, profile: dict[str, Any]) -> dict[str, Any]:
    years_experience = int(profile.get("years_experience", 0) or 0)
    years_experience = max(0, years_experience)
    skills = _parse_json_array(profile.get("skills"))
    desired_job_titles = _parse_json_array(profile.get("desired_job_titles"))
    role_families = _parse_json_array(profile.get("target_role_families"))
    requires_visa = bool(profile.get("requires_visa_sponsorship", False))
    education = _parse_education_array(profile.get("education"))
    if not education and (profile.get("degree") or profile.get("degree_field")):
        education = [
            {
                "degree": (profile.get("degree") or "").strip(),
                "field": (profile.get("degree_field") or "").strip() or None,
            }
        ]
    education = [item for item in education if item.get("degree")]
    primary_degree = education[0] if education else {"degree": None, "field": None}
    degree = primary_degree.get("degree")
    degree_field = primary_degree.get("field")
    existing = conn.execute(
        "SELECT score_version FROM candidate_profile WHERE id = 1"
    ).fetchone()
    existing_version = int(existing[0]) if existing and existing[0] is not None else 1
    score_version = int(
        profile.get("score_version", existing_version) or existing_version
    )
    score_version = max(1, score_version)
    updated_at = _utc_now_iso()
    full_name = (str(profile.get("full_name") or "").strip()) or None
    email = (str(profile.get("email") or "").strip()) or None
    phone = (str(profile.get("phone") or "").strip()) or None
    linkedin_url = (str(profile.get("linkedin_url") or "").strip()) or None
    portfolio_url = (str(profile.get("portfolio_url") or "").strip()) or None
    city = (str(profile.get("city") or "").strip()) or None
    country = (str(profile.get("country") or "").strip()) or None
    conn.execute(
        """
        INSERT OR REPLACE INTO candidate_profile
        (id, years_experience, skills, desired_job_titles, target_role_families, requires_visa_sponsorship, education, degree, degree_field, score_version, updated_at,
         full_name, email, phone, linkedin_url, portfolio_url, city, country)
        VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            years_experience,
            json.dumps(skills, ensure_ascii=True),
            json.dumps(desired_job_titles, ensure_ascii=True),
            json.dumps(role_families, ensure_ascii=True),
            1 if requires_visa else 0,
            json.dumps(education, ensure_ascii=True),
            degree,
            degree_field,
            score_version,
            updated_at,
            full_name,
            email,
            phone,
            linkedin_url,
            portfolio_url,
            city,
            country,
        ),
    )
    conn.commit()
    return get_candidate_profile(conn)


def bump_candidate_profile_score_version(conn: Any) -> int:
    existing = conn.execute(
        "SELECT score_version FROM candidate_profile WHERE id = 1"
    ).fetchone()
    current = int(existing[0]) if existing and existing[0] is not None else 1
    next_version = max(1, current + 1)
    updated_at = _utc_now_iso()
    if existing:
        conn.execute(
            "UPDATE candidate_profile SET score_version = ?, updated_at = ? WHERE id = 1",
            (next_version, updated_at),
        )
    else:
        conn.execute(
            """
            INSERT INTO candidate_profile
            (id, years_experience, skills, desired_job_titles, target_role_families, requires_visa_sponsorship, education, degree, degree_field, score_version, updated_at)
            VALUES (1, 0, '[]', '[]', '[]', 0, '[]', NULL, NULL, ?, ?)
            """,
            (next_version, updated_at),
        )
    conn.commit()
    return next_version


def create_workspace_operation(conn: Any, operation: dict[str, Any]) -> dict[str, Any]:
    op_id = str(operation.get("id") or "").strip()
    if not op_id:
        raise ValueError("workspace operation id is required")
    started_at = str(operation.get("started_at") or _utc_now_iso())
    conn.execute(
        """
        INSERT INTO workspace_operations
        (id, kind, status, params_json, summary_json, log_tail, started_at, finished_at, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            op_id,
            str(operation.get("kind") or "").strip(),
            str(operation.get("status") or "queued").strip(),
            json.dumps(operation.get("params") or {}, ensure_ascii=True),
            json.dumps(operation.get("summary") or {}, ensure_ascii=True),
            str(operation.get("log_tail") or ""),
            started_at,
            operation.get("finished_at"),
            operation.get("error"),
        ),
    )
    conn.commit()
    return get_workspace_operation(conn, op_id) or {}


def get_workspace_operation(conn: Any, operation_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, kind, status, params_json, summary_json, log_tail, started_at, finished_at, error
        FROM workspace_operations
        WHERE id = ?
        """,
        (operation_id,),
    ).fetchone()
    if not row:
        return None
    try:
        params = json.loads(row[3] or "{}")
    except json.JSONDecodeError:
        params = {}
    try:
        summary = json.loads(row[4] or "{}")
    except json.JSONDecodeError:
        summary = {}
    return {
        "id": row[0],
        "kind": row[1],
        "status": row[2],
        "params": params if isinstance(params, dict) else {},
        "summary": summary if isinstance(summary, dict) else {},
        "log_tail": row[5] or "",
        "started_at": row[6],
        "finished_at": row[7],
        "error": row[8],
    }


def list_workspace_operations(conn: Any, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id
        FROM workspace_operations
        ORDER BY datetime(started_at) DESC, id DESC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()
    operations: list[dict[str, Any]] = []
    for row in rows:
        item = get_workspace_operation(conn, str(row[0]))
        if item:
            operations.append(item)
    return operations


def update_workspace_operation(
    conn: Any, operation_id: str, patch: dict[str, Any]
) -> dict[str, Any] | None:
    existing = get_workspace_operation(conn, operation_id)
    if not existing:
        return None
    next_summary = existing["summary"]
    if "summary" in patch and isinstance(patch.get("summary"), dict):
        next_summary = patch["summary"]
    next_params = existing["params"]
    if "params" in patch and isinstance(patch.get("params"), dict):
        next_params = patch["params"]
    log_tail = (
        existing["log_tail"]
        if "log_tail" not in patch
        else str(patch.get("log_tail") or "")
    )
    conn.execute(
        """
        UPDATE workspace_operations
        SET status = ?, params_json = ?, summary_json = ?, log_tail = ?, finished_at = ?, error = ?
        WHERE id = ?
        """,
        (
            str(patch.get("status") or existing["status"]),
            json.dumps(next_params, ensure_ascii=True),
            json.dumps(next_summary, ensure_ascii=True),
            log_tail,
            patch.get("finished_at", existing["finished_at"]),
            patch.get("error", existing["error"]),
            operation_id,
        ),
    )
    conn.commit()
    return get_workspace_operation(conn, operation_id)


def _parse_education_array(raw: Any) -> list[dict[str, str | None]]:
    parsed: Any = raw
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(parsed, list):
        return []
    result: list[dict[str, str | None]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        degree = str(item.get("degree") or "").strip()
        field_value = item.get("field")
        field = str(field_value).strip() if field_value is not None else ""
        if not degree:
            continue
        result.append({"degree": degree, "field": field or None})
    return result
