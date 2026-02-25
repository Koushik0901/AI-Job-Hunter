from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from db import get_candidate_profile, upsert_candidate_profile
from match_score import compute_match_score


def _parse_json_array(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(v) for v in raw]
    if not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(v) for v in parsed]
    return []


def _build_enrichment_payload(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "work_mode": raw.get("work_mode"),
        "remote_geo": raw.get("remote_geo"),
        "canada_eligible": raw.get("canada_eligible"),
        "seniority": raw.get("seniority"),
        "role_family": raw.get("role_family"),
        "years_exp_min": raw.get("years_exp_min"),
        "years_exp_max": raw.get("years_exp_max"),
        "minimum_degree": raw.get("minimum_degree"),
        "required_skills": _parse_json_array(raw.get("required_skills")),
        "preferred_skills": _parse_json_array(raw.get("preferred_skills")),
        "formatted_description": raw.get("formatted_description"),
        "salary_min": raw.get("salary_min"),
        "salary_max": raw.get("salary_max"),
        "salary_currency": raw.get("salary_currency"),
        "visa_sponsorship": raw.get("visa_sponsorship"),
        "red_flags": _parse_json_array(raw.get("red_flags")),
        "enriched_at": raw.get("enriched_at"),
        "enrichment_status": raw.get("enrichment_status"),
        "enrichment_model": raw.get("enrichment_model"),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_status_sql(tracking_column: str, application_column: str) -> str:
    source = f"COALESCE({tracking_column}, {application_column})"
    return f"CASE WHEN {source} = 'withdrawn' THEN 'rejected' ELSE COALESCE({source}, 'not_applied') END"


def list_jobs(
    conn: Any,
    *,
    status: str | None,
    q: str | None,
    ats: str | None,
    company: str | None,
    posted_after: str | None,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: list[Any] = []

    if status:
        where.append(f"{_normalized_status_sql('t.status', 'j.application_status')} = ?")
        params.append(status)
    if q:
        where.append("(j.title LIKE ? OR j.company LIKE ? OR j.location LIKE ?)")
        qv = f"%{q}%"
        params.extend([qv, qv, qv])
    if ats:
        where.append("j.ats = ?")
        params.append(ats)
    if company:
        where.append("j.company LIKE ?")
        params.append(f"%{company}%")
    if posted_after:
        where.append("date(j.posted) >= date(?)")
        params.append(posted_after)

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    order_sql = "ORDER BY date(j.posted) DESC"
    if sort == "updated_desc":
        order_sql = "ORDER BY COALESCE(t.updated_at, j.last_seen) DESC"
    elif sort == "company_asc":
        order_sql = "ORDER BY j.company ASC, j.title ASC"
    elif sort == "match_desc":
        order_sql = "ORDER BY date(j.posted) DESC"

    count_sql = f"""
        SELECT COUNT(*)
        FROM jobs j
        LEFT JOIN job_tracking t ON t.url = j.url
        {where_sql}
    """
    total_row = conn.execute(count_sql, tuple(params)).fetchone()
    total = int(total_row[0]) if total_row else 0

    data_sql = f"""
        SELECT
            j.url,
            COALESCE(j.company, ''),
            COALESCE(j.title, ''),
            COALESCE(j.location, ''),
            COALESCE(j.posted, ''),
            COALESCE(j.ats, ''),
            {_normalized_status_sql('t.status', 'j.application_status')},
            COALESCE(t.priority, 'medium'),
            t.updated_at,
            e.work_mode,
            e.remote_geo,
            e.canada_eligible,
            e.seniority,
            e.role_family,
            e.years_exp_min,
            e.years_exp_max,
            e.minimum_degree,
            e.required_skills,
            e.preferred_skills,
            e.formatted_description,
            e.salary_min,
            e.salary_max,
            e.salary_currency,
            e.visa_sponsorship,
            e.red_flags,
            e.enriched_at,
            e.enrichment_status,
            e.enrichment_model
        FROM jobs j
        LEFT JOIN job_tracking t ON t.url = j.url
        LEFT JOIN job_enrichments e ON e.url = j.url
        {where_sql}
        {order_sql}
    """
    data_params: list[Any] = list(params)
    if sort != "match_desc":
        data_sql += "\nLIMIT ? OFFSET ?"
        data_params.extend([limit, offset])
    rows = conn.execute(data_sql, tuple(data_params)).fetchall()
    profile = get_candidate_profile(conn)
    items = [
        {
            "url": r[0],
            "company": r[1],
            "title": r[2],
            "location": r[3],
            "posted": r[4],
            "ats": r[5],
            "status": r[6],
            "priority": r[7],
            "updated_at": r[8],
            "match_score": compute_match_score(
                {
                    "title": r[2],
                    "enrichment": _build_enrichment_payload(
                        {
                            "work_mode": r[9],
                            "remote_geo": r[10],
                            "canada_eligible": r[11],
                            "seniority": r[12],
                            "role_family": r[13],
                            "years_exp_min": r[14],
                            "years_exp_max": r[15],
                            "minimum_degree": r[16],
                            "required_skills": r[17],
                            "preferred_skills": r[18],
                            "formatted_description": r[19],
                            "salary_min": r[20],
                            "salary_max": r[21],
                            "salary_currency": r[22],
                            "visa_sponsorship": r[23],
                            "red_flags": r[24],
                            "enriched_at": r[25],
                            "enrichment_status": r[26],
                            "enrichment_model": r[27],
                        }
                    ),
                },
                profile,
            )["score"],
        }
        for r in rows
    ]
    for item in items:
        score = item.get("match_score")
        if isinstance(score, int):
            item["match_band"] = "excellent" if score >= 80 else ("good" if score >= 65 else ("fair" if score >= 45 else "low"))
        else:
            item["match_band"] = None
    if sort == "match_desc":
        items.sort(key=lambda x: int(x.get("match_score") or 0), reverse=True)
        items = items[offset:offset + limit]
    return items, total


def get_job_detail(conn: Any, url: str) -> dict[str, Any] | None:
    row = conn.execute(
        f"""
        SELECT
            j.url,
            COALESCE(j.company, ''),
            COALESCE(j.title, ''),
            COALESCE(j.location, ''),
            COALESCE(j.posted, ''),
            COALESCE(j.ats, ''),
            COALESCE(j.description, ''),
            COALESCE(j.first_seen, ''),
            COALESCE(j.last_seen, ''),
            j.application_status,
            {_normalized_status_sql('t.status', 'j.application_status')},
            COALESCE(t.priority, 'medium'),
            t.applied_at,
            t.next_step,
            t.target_compensation,
            t.updated_at,
            e.work_mode,
            e.remote_geo,
            e.canada_eligible,
            e.seniority,
            e.role_family,
            e.years_exp_min,
            e.years_exp_max,
            e.minimum_degree,
            e.required_skills,
            e.preferred_skills,
            e.formatted_description,
            e.salary_min,
            e.salary_max,
            e.salary_currency,
            e.visa_sponsorship,
            e.red_flags,
            e.enriched_at,
            e.enrichment_status,
            e.enrichment_model
        FROM jobs j
        LEFT JOIN job_tracking t ON t.url = j.url
        LEFT JOIN job_enrichments e ON e.url = j.url
        WHERE j.url = ?
        """,
        (url,),
    ).fetchone()
    if not row:
        return None
    enrichment = None
    if any(value is not None for value in row[16:35]):
        enrichment = _build_enrichment_payload(
            {
                "work_mode": row[16],
                "remote_geo": row[17],
                "canada_eligible": row[18],
                "seniority": row[19],
                "role_family": row[20],
                "years_exp_min": row[21],
                "years_exp_max": row[22],
                "minimum_degree": row[23],
                "required_skills": row[24],
                "preferred_skills": row[25],
                "formatted_description": row[26],
                "salary_min": row[27],
                "salary_max": row[28],
                "salary_currency": row[29],
                "visa_sponsorship": row[30],
                "red_flags": row[31],
                "enriched_at": row[32],
                "enrichment_status": row[33],
                "enrichment_model": row[34],
            }
        )

    profile = get_candidate_profile(conn)
    match = compute_match_score({"title": row[2], "enrichment": enrichment or {}}, profile)

    return {
        "url": row[0],
        "company": row[1],
        "title": row[2],
        "location": row[3],
        "posted": row[4],
        "ats": row[5],
        "description": row[6],
        "first_seen": row[7],
        "last_seen": row[8],
        "application_status": row[9],
        "tracking_status": row[10],
        "priority": row[11],
        "applied_at": row[12],
        "next_step": row[13],
        "target_compensation": row[14],
        "tracking_updated_at": row[15],
        "enrichment": enrichment,
        "match": match,
    }


def upsert_tracking(conn: Any, url: str, patch: dict[str, Any]) -> None:
    existing = conn.execute(
        "SELECT status, priority, applied_at, next_step, target_compensation FROM job_tracking WHERE url = ?",
        (url,),
    ).fetchone()

    now = _now_iso()
    if existing:
        status = patch.get("status", existing[0])
        priority = patch.get("priority", existing[1])
        applied_at = patch.get("applied_at", existing[2])
        next_step = patch.get("next_step", existing[3])
        target_compensation = patch.get("target_compensation", existing[4])
        conn.execute(
            """
            UPDATE job_tracking
            SET status = ?, priority = ?, applied_at = ?, next_step = ?, target_compensation = ?, updated_at = ?
            WHERE url = ?
            """,
            (status, priority, applied_at, next_step, target_compensation, now, url),
        )
    else:
        status = patch.get("status", "not_applied")
        priority = patch.get("priority", "medium")
        applied_at = patch.get("applied_at")
        next_step = patch.get("next_step")
        target_compensation = patch.get("target_compensation")
        conn.execute(
            """
            INSERT INTO job_tracking (url, status, priority, applied_at, next_step, target_compensation, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (url, status, priority, applied_at, next_step, target_compensation, now),
        )

    conn.execute("UPDATE jobs SET application_status = ? WHERE url = ?", (status, url))
    conn.commit()


def list_events(conn: Any, url: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, url, event_type, title, body, event_at, created_at
        FROM job_events
        WHERE url = ?
        ORDER BY datetime(event_at) DESC, id DESC
        """,
        (url,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "url": r[1],
            "event_type": r[2],
            "title": r[3],
            "body": r[4],
            "event_at": r[5],
            "created_at": r[6],
        }
        for r in rows
    ]


def create_event(conn: Any, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    created = _now_iso()
    conn.execute(
        """
        INSERT INTO job_events (url, event_type, title, body, event_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (url, payload["event_type"], payload["title"], payload.get("body"), payload["event_at"], created),
    )
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    event_id = int(row[0]) if row else 0
    conn.commit()
    return {
        "id": event_id,
        "url": url,
        "event_type": payload["event_type"],
        "title": payload["title"],
        "body": payload.get("body"),
        "event_at": payload["event_at"],
        "created_at": created,
    }


def delete_event(conn: Any, event_id: int) -> int:
    conn.execute("DELETE FROM job_events WHERE id = ?", (event_id,))
    changed = conn.execute("SELECT changes()").fetchone()
    conn.commit()
    return int(changed[0]) if changed else 0


def delete_job(conn: Any, url: str) -> int:
    conn.execute("DELETE FROM job_events WHERE url = ?", (url,))
    conn.execute("DELETE FROM job_tracking WHERE url = ?", (url,))
    conn.execute("DELETE FROM job_enrichments WHERE url = ?", (url,))
    conn.execute("DELETE FROM jobs WHERE url = ?", (url,))
    changed = conn.execute("SELECT changes()").fetchone()
    conn.commit()
    return int(changed[0]) if changed else 0


def get_stats(conn: Any) -> dict[str, Any]:
    total_jobs = int(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
    tracked_jobs = int(conn.execute("SELECT COUNT(*) FROM job_tracking").fetchone()[0])

    by_status_rows = conn.execute(
        f"""
        SELECT {_normalized_status_sql('t.status', 'j.application_status')} AS s, COUNT(*)
        FROM jobs j
        LEFT JOIN job_tracking t ON t.url = j.url
        GROUP BY s
        """
    ).fetchall()
    by_status = {str(r[0]): int(r[1]) for r in by_status_rows}

    active_pipeline = sum(by_status.get(k, 0) for k in ("applied", "interviewing"))

    recent_activity_7d = int(
        conn.execute(
            "SELECT COUNT(*) FROM job_events WHERE datetime(created_at) >= datetime('now', '-7 day')"
        ).fetchone()[0]
    )

    return {
        "total_jobs": total_jobs,
        "tracked_jobs": tracked_jobs,
        "active_pipeline": active_pipeline,
        "recent_activity_7d": recent_activity_7d,
        "by_status": by_status,
    }


def get_profile(conn: Any) -> dict[str, Any]:
    return get_candidate_profile(conn)


def save_profile(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return upsert_candidate_profile(conn, payload)
