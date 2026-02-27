from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from db import (
    get_candidate_profile,
    is_job_suppressed,
    save_jobs,
    suppress_job_url,
    unsuppress_job_url,
    upsert_candidate_profile,
)
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


def _not_suppressed_sql(job_alias: str = "j") -> str:
    return (
        f"NOT EXISTS ("
        f"SELECT 1 FROM job_suppressions js "
        f"WHERE js.url = {job_alias}.url AND js.active = 1)"
    )


def list_jobs(
    conn: Any,
    *,
    status: str | None,
    q: str | None,
    ats: str | None,
    company: str | None,
    posted_after: str | None,
    posted_before: str | None,
    sort: str,
    limit: int,
    offset: int,
    include_suppressed: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: list[Any] = []
    if not include_suppressed:
        where.append(_not_suppressed_sql("j"))

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
    if posted_before:
        where.append("date(j.posted) <= date(?)")
        params.append(posted_before)

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


def create_manual_job(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    if is_job_suppressed(conn, url):
        raise ValueError("This job URL is suppressed. Unsuppress it before adding.")

    today = datetime.now(timezone.utc).date().isoformat()
    job = {
        "url": url,
        "company": str(payload.get("company") or "").strip(),
        "title": str(payload.get("title") or "").strip(),
        "location": str(payload.get("location") or "").strip(),
        "posted": str(payload.get("posted") or today).strip(),
        "ats": str(payload.get("ats") or "manual").strip(),
        "description": str(payload.get("description") or "").strip(),
        "source": "manual",
    }
    save_jobs(conn, [job])
    detail = get_job_detail(conn, url)
    if not detail:
        raise RuntimeError("Failed to save manual job")
    return detail


def suppress_job(conn: Any, *, url: str, reason: str | None, created_by: str = "ui") -> None:
    suppress_job_url(conn, url=url, reason=reason, created_by=created_by)


def unsuppress_job(conn: Any, *, url: str) -> int:
    return unsuppress_job_url(conn, url)


def list_active_suppressions(conn: Any, *, limit: int = 200) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT url, COALESCE(company, ''), reason, created_at, updated_at, created_by
        FROM job_suppressions
        WHERE active = 1
        ORDER BY datetime(updated_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "url": str(row[0]),
            "company": str(row[1] or ""),
            "reason": row[2],
            "created_at": str(row[3]),
            "updated_at": str(row[4]),
            "created_by": str(row[5] or "ui"),
        }
        for row in rows
    ]


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
    total_jobs = int(
        conn.execute(
            f"SELECT COUNT(*) FROM jobs j WHERE {_not_suppressed_sql('j')}"
        ).fetchone()[0]
    )
    tracked_jobs = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM job_tracking t
            INNER JOIN jobs j ON j.url = t.url
            WHERE {_not_suppressed_sql('j')}
            """
        ).fetchone()[0]
    )

    by_status_rows = conn.execute(
        f"""
        SELECT {_normalized_status_sql('t.status', 'j.application_status')} AS s, COUNT(*)
        FROM jobs j
        LEFT JOIN job_tracking t ON t.url = j.url
        WHERE {_not_suppressed_sql('j')}
        GROUP BY s
        """
    ).fetchall()
    by_status = {str(r[0]): int(r[1]) for r in by_status_rows}

    active_pipeline = sum(by_status.get(k, 0) for k in ("applied", "interviewing"))

    recent_activity_7d = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM job_events ev
            INNER JOIN jobs j ON j.url = ev.url
            WHERE datetime(ev.created_at) >= datetime('now', '-7 day')
              AND {_not_suppressed_sql('j')}
            """
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


def get_funnel_analytics(
    conn: Any,
    *,
    from_date: str | None,
    to_date: str | None,
    status_scope: str,
    applications_goal_target: int,
    interviews_goal_target: int,
    forecast_apps_per_week: int | None = None,
) -> dict[str, Any]:
    stage_order_all = ["not_applied", "staging", "applied", "interviewing", "offer", "rejected"]
    stage_order_pipeline = ["not_applied", "staging", "applied", "interviewing", "offer"]
    stage_order = stage_order_all if status_scope == "all" else stage_order_pipeline
    comparison_stage_order = stage_order

    current_counts = _funnel_counts(conn, from_date=from_date, to_date=to_date)
    reference_date = _resolve_reference_date(to_date)
    previous_counts: dict[str, int] = {}
    comparison_window: dict[str, Any] | None = None
    if from_date:
        try:
            previous_window = _previous_window(from_date, to_date or reference_date.isoformat())
        except ValueError:
            previous_window = None
        if previous_window:
            previous_counts = _funnel_counts(
                conn,
                from_date=previous_window["from"],
                to_date=previous_window["to"],
            )
            comparison_window = previous_window

    conversions = _conversion_metrics(current_counts)
    previous_conversions = _conversion_metrics(previous_counts) if previous_counts else {
        "backlog_to_staging": 0.0,
        "staging_to_applied": 0.0,
        "applied_to_interviewing": 0.0,
        "interviewing_to_offer": 0.0,
        "backlog_to_offer": 0.0,
    }
    weekly_goals = _weekly_goals(
        conn,
        reference_date=reference_date,
        applications_goal_target=applications_goal_target,
        interviews_goal_target=interviews_goal_target,
    )
    alerts = _analytics_alerts(conn, reference_date=reference_date)
    cohorts = _cohort_funnel(
        conn,
        from_date=from_date,
        to_date=to_date,
        stage_order=stage_order,
    )
    source_quality = _source_quality(
        conn,
        from_date=from_date,
        to_date=to_date,
    )
    forecast = _forecast_summary(
        current_counts=current_counts,
        conversions=conversions,
        applications_goal_target=applications_goal_target,
        forecast_apps_per_week=forecast_apps_per_week,
    )

    return {
        "stages": [{"status": status, "count": current_counts.get(status, 0)} for status in stage_order],
        "conversions": conversions,
        "totals": {
            "tracked_total": sum(current_counts.get(status, 0) for status in stage_order),
            "active_total": current_counts.get("staging", 0) + current_counts.get("applied", 0) + current_counts.get("interviewing", 0),
            "offer_total": current_counts.get("offer", 0),
        },
        "status_totals": {status: current_counts.get(status, 0) for status in stage_order_all},
        "deltas": {
            "tracked_total": sum(current_counts.get(status, 0) for status in comparison_stage_order)
            - sum(previous_counts.get(status, 0) for status in comparison_stage_order),
            "active_total": (
                current_counts.get("staging", 0) + current_counts.get("applied", 0) + current_counts.get("interviewing", 0)
                - previous_counts.get("staging", 0) - previous_counts.get("applied", 0) - previous_counts.get("interviewing", 0)
            ),
            "offer_total": current_counts.get("offer", 0) - previous_counts.get("offer", 0),
            "conversions": {
                "backlog_to_staging": round(conversions["backlog_to_staging"] - previous_conversions["backlog_to_staging"], 4),
                "staging_to_applied": round(conversions["staging_to_applied"] - previous_conversions["staging_to_applied"], 4),
                "applied_to_interviewing": round(conversions["applied_to_interviewing"] - previous_conversions["applied_to_interviewing"], 4),
                "interviewing_to_offer": round(conversions["interviewing_to_offer"] - previous_conversions["interviewing_to_offer"], 4),
                "backlog_to_offer": round(conversions["backlog_to_offer"] - previous_conversions["backlog_to_offer"], 4),
            },
            "comparison_window": comparison_window,
        },
        "weekly_goals": weekly_goals,
        "alerts": alerts,
        "cohorts": cohorts,
        "source_quality": source_quality,
        "forecast": forecast,
    }


def _funnel_counts(
    conn: Any,
    *,
    from_date: str | None,
    to_date: str | None,
) -> dict[str, int]:
    where: list[str] = []
    params: list[Any] = []
    where.append(_not_suppressed_sql("j"))

    if from_date:
        where.append("date(j.posted) >= date(?)")
        params.append(from_date)
    if to_date:
        where.append("date(j.posted) <= date(?)")
        params.append(to_date)
    if from_date or to_date:
        where.append("j.posted IS NOT NULL AND j.posted != ''")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        f"""
        SELECT {_normalized_status_sql('t.status', 'j.application_status')} AS s, COUNT(*)
        FROM jobs j
        LEFT JOIN job_tracking t ON t.url = j.url
        {where_sql}
        GROUP BY s
        """,
        tuple(params),
    ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def _conversion_metrics(counts: dict[str, int]) -> dict[str, float]:
    def pct(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator, 4)

    backlog = counts.get("not_applied", 0)
    staging = counts.get("staging", 0)
    applied = counts.get("applied", 0)
    interviewing = counts.get("interviewing", 0)
    offer = counts.get("offer", 0)
    return {
        "backlog_to_staging": pct(staging, backlog),
        "staging_to_applied": pct(applied, staging),
        "applied_to_interviewing": pct(interviewing, applied),
        "interviewing_to_offer": pct(offer, interviewing),
        "backlog_to_offer": pct(offer, backlog),
    }


def _resolve_reference_date(to_date: str | None) -> date:
    if not to_date:
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(to_date)
    except ValueError:
        return datetime.now(timezone.utc).date()


def _previous_window(from_date: str, to_date: str) -> dict[str, Any]:
    current_start = date.fromisoformat(from_date)
    current_end = date.fromisoformat(to_date)
    days = max(1, (current_end - current_start).days + 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    return {
        "from": previous_start.isoformat(),
        "to": previous_end.isoformat(),
        "days": days,
    }


def _weekly_goals(
    conn: Any,
    *,
    reference_date: date,
    applications_goal_target: int,
    interviews_goal_target: int,
) -> dict[str, Any]:
    week_start = reference_date - timedelta(days=6)
    start_iso = week_start.isoformat()
    end_iso = reference_date.isoformat()
    applications_actual = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM job_tracking
            WHERE applied_at IS NOT NULL
              AND date(applied_at) >= date(?)
              AND date(applied_at) <= date(?)
            """,
            (start_iso, end_iso),
        ).fetchone()[0]
    )
    interviews_actual = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM job_events
            WHERE event_type IN ('recruiter_screen', 'technical_interview', 'onsite')
              AND date(event_at) >= date(?)
              AND date(event_at) <= date(?)
            """,
            (start_iso, end_iso),
        ).fetchone()[0]
    )

    return {
        "window_start": start_iso,
        "window_end": end_iso,
        "applications": {
            "target": applications_goal_target,
            "actual": applications_actual,
            "progress": round(min(1.0, applications_actual / max(1, applications_goal_target)), 4),
        },
        "interviews": {
            "target": interviews_goal_target,
            "actual": interviews_actual,
            "progress": round(min(1.0, interviews_actual / max(1, interviews_goal_target)), 4),
        },
    }


def _analytics_alerts(conn: Any, *, reference_date: date) -> dict[str, int]:
    reference_iso = reference_date.isoformat()
    staging_stale_7d = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM jobs j
            LEFT JOIN job_tracking t ON t.url = j.url
            WHERE {_normalized_status_sql('t.status', 'j.application_status')} = 'staging'
              AND date(COALESCE(t.updated_at, j.last_seen, j.posted)) <= date(?, '-7 day')
              AND {_not_suppressed_sql('j')}
            """,
            (reference_iso,),
        ).fetchone()[0]
    )
    interviewing_no_activity_5d = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM jobs j
            LEFT JOIN job_tracking t ON t.url = j.url
            LEFT JOIN (
              SELECT url, MAX(event_at) AS latest_event_at
              FROM job_events
              GROUP BY url
            ) ev ON ev.url = j.url
            WHERE {_normalized_status_sql('t.status', 'j.application_status')} = 'interviewing'
              AND {_not_suppressed_sql('j')}
              AND (
                ev.latest_event_at IS NULL
                OR date(ev.latest_event_at) <= date(?, '-5 day')
              )
            """,
            (reference_iso,),
        ).fetchone()[0]
    )
    backlog_expiring_soon = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM jobs j
            LEFT JOIN job_tracking t ON t.url = j.url
            WHERE {_normalized_status_sql('t.status', 'j.application_status')} = 'not_applied'
              AND j.posted IS NOT NULL
              AND j.posted != ''
              AND date(j.posted) BETWEEN date(?, '-21 day') AND date(?, '-18 day')
              AND {_not_suppressed_sql('j')}
            """,
            (reference_iso, reference_iso),
        ).fetchone()[0]
    )
    return {
        "staging_stale_7d": staging_stale_7d,
        "interviewing_no_activity_5d": interviewing_no_activity_5d,
        "backlog_expiring_soon": backlog_expiring_soon,
    }


def _cohort_funnel(
    conn: Any,
    *,
    from_date: str | None,
    to_date: str | None,
    stage_order: list[str],
) -> list[dict[str, Any]]:
    where: list[str] = ["j.posted IS NOT NULL", "j.posted != ''", _not_suppressed_sql("j")]
    params: list[Any] = []
    if from_date:
        where.append("date(j.posted) >= date(?)")
        params.append(from_date)
    if to_date:
        where.append("date(j.posted) <= date(?)")
        params.append(to_date)
    where_sql = "WHERE " + " AND ".join(where)
    week_start_expr = "date(j.posted, '-' || ((CAST(strftime('%w', j.posted) AS INTEGER) + 6) % 7) || ' days')"
    rows = conn.execute(
        f"""
        SELECT
          {week_start_expr} AS week_start,
          {_normalized_status_sql('t.status', 'j.application_status')} AS s,
          COUNT(*)
        FROM jobs j
        LEFT JOIN job_tracking t ON t.url = j.url
        {where_sql}
        GROUP BY week_start, s
        ORDER BY week_start DESC
        """,
        tuple(params),
    ).fetchall()

    buckets: dict[str, dict[str, int]] = {}
    for week_start, status, count in rows:
        week_key = str(week_start)
        if week_key not in buckets:
            buckets[week_key] = {}
        buckets[week_key][str(status)] = int(count)

    ordered_weeks = sorted(buckets.keys(), reverse=True)[:8]
    result: list[dict[str, Any]] = []
    for week_key in ordered_weeks:
        status_counts = buckets[week_key]
        tracked_total = sum(status_counts.get(status, 0) for status in stage_order)
        offers = status_counts.get("offer", 0)
        offer_rate = round(offers / tracked_total, 4) if tracked_total > 0 else 0.0
        result.append(
            {
                "week_start": week_key,
                "stages": [{"status": status, "count": status_counts.get(status, 0)} for status in stage_order],
                "tracked_total": tracked_total,
                "offer_rate": offer_rate,
            }
        )
    return result


def _source_quality(conn: Any, *, from_date: str | None, to_date: str | None) -> dict[str, list[dict[str, Any]]]:
    return {
        "ats": _source_quality_group(conn, group_expr="COALESCE(NULLIF(j.ats, ''), 'unknown')", from_date=from_date, to_date=to_date),
        "companies": _source_quality_group(conn, group_expr="COALESCE(NULLIF(j.company, ''), 'Unknown company')", from_date=from_date, to_date=to_date),
    }


def _source_quality_group(
    conn: Any,
    *,
    group_expr: str,
    from_date: str | None,
    to_date: str | None,
) -> list[dict[str, Any]]:
    where: list[str] = [_not_suppressed_sql("j")]
    params: list[Any] = []
    if from_date:
        where.append("date(j.posted) >= date(?)")
        params.append(from_date)
    if to_date:
        where.append("date(j.posted) <= date(?)")
        params.append(to_date)
    if from_date or to_date:
        where.append("j.posted IS NOT NULL AND j.posted != ''")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        f"""
        SELECT
          {group_expr} AS source_name,
          {_normalized_status_sql('t.status', 'j.application_status')} AS s,
          COUNT(*)
        FROM jobs j
        LEFT JOIN job_tracking t ON t.url = j.url
        {where_sql}
        GROUP BY source_name, s
        """,
        tuple(params),
    ).fetchall()
    grouped: dict[str, dict[str, int]] = {}
    for source_name, status, count in rows:
        source_key = str(source_name)
        if source_key not in grouped:
            grouped[source_key] = {}
        grouped[source_key][str(status)] = int(count)

    items: list[dict[str, Any]] = []
    for source_key, counts in grouped.items():
        tracked_total = (
            counts.get("not_applied", 0)
            + counts.get("staging", 0)
            + counts.get("applied", 0)
            + counts.get("interviewing", 0)
            + counts.get("offer", 0)
            + counts.get("rejected", 0)
        )
        active_total = counts.get("staging", 0) + counts.get("applied", 0) + counts.get("interviewing", 0)
        offers = counts.get("offer", 0)
        interviewing = counts.get("interviewing", 0)
        offer_rate = round(offers / tracked_total, 4) if tracked_total > 0 else 0.0
        interview_rate = round(interviewing / tracked_total, 4) if tracked_total > 0 else 0.0
        items.append(
            {
                "name": source_key,
                "tracked_total": tracked_total,
                "active_total": active_total,
                "offers": offers,
                "offer_rate": offer_rate,
                "interview_rate": interview_rate,
            }
        )

    items.sort(key=lambda item: (item["offer_rate"], item["tracked_total"]), reverse=True)
    return items[:10]


def _forecast_summary(
    *,
    current_counts: dict[str, int],
    conversions: dict[str, float],
    applications_goal_target: int,
    forecast_apps_per_week: int | None,
) -> dict[str, Any]:
    base_apps = max(1, int(forecast_apps_per_week or applications_goal_target))
    tracked_total = (
        current_counts.get("not_applied", 0)
        + current_counts.get("staging", 0)
        + current_counts.get("applied", 0)
        + current_counts.get("interviewing", 0)
        + current_counts.get("offer", 0)
        + current_counts.get("rejected", 0)
    )
    interviewing_count = current_counts.get("interviewing", 0)
    if tracked_total >= 60 and interviewing_count >= 10:
        confidence_band = "high"
        margin = 0.15
    elif tracked_total >= 25 and interviewing_count >= 4:
        confidence_band = "medium"
        margin = 0.3
    else:
        confidence_band = "low"
        margin = 0.5

    interview_rate = float(conversions.get("applied_to_interviewing", 0.0))
    offer_rate = float(conversions.get("interviewing_to_offer", 0.0))

    def project(days: int) -> dict[str, Any]:
        applications = base_apps * (days / 7.0)
        interviews = applications * interview_rate
        offers = interviews * offer_rate
        low_multiplier = max(0.0, 1.0 - margin)
        high_multiplier = 1.0 + margin
        return {
            "days": days,
            "projected_interviews": round(interviews, 2),
            "projected_offers": round(offers, 2),
            "interviews_low": round(interviews * low_multiplier, 2),
            "interviews_high": round(interviews * high_multiplier, 2),
            "offers_low": round(offers * low_multiplier, 2),
            "offers_high": round(offers * high_multiplier, 2),
        }

    return {
        "applications_per_week": base_apps,
        "interview_rate": round(interview_rate, 4),
        "offer_rate_from_interview": round(offer_rate, 4),
        "confidence_band": confidence_band,
        "confidence_margin": margin,
        "windows": [project(7), project(30)],
    }
