from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from db import (
    bump_candidate_profile_score_version,
    create_workspace_operation,
    get_candidate_evidence_assets,
    get_candidate_profile,
    get_company_source_by_id,
    get_resume_profile,
    get_template_settings,
    get_workspace_operation,
    is_job_suppressed_id,
    list_company_sources,
    list_workspace_operations,
    save_jobs,
    suppress_job_id,
    unsuppress_job_id,
    update_company_source,
    update_workspace_operation,
    upsert_candidate_evidence_assets,
    upsert_candidate_profile,
    upsert_resume_profile,
    upsert_template_settings,
)
from dashboard.backend.artifact_typography import resolve_document_typography
from dashboard.backend.latex_resume import bootstrap_cover_letter_tex, bootstrap_resume_tex
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


def _plus_hours_iso(raw_iso: str, hours: int) -> str:
    parsed = _parse_iso_datetime(raw_iso)
    if parsed is None:
        parsed = datetime.now(timezone.utc)
    return (parsed + timedelta(hours=hours)).isoformat()


def _parse_iso_datetime(raw: Any) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _staging_sla_fields(status: str, staging_entered_at: Any, staging_due_at: Any) -> dict[str, Any]:
    in_staging = str(status or "") == "staging"
    entered = _parse_iso_datetime(staging_entered_at)
    due = _parse_iso_datetime(staging_due_at)
    if in_staging and entered is not None and due is None:
        due = entered + timedelta(hours=48)

    if not in_staging:
        return {
            "staging_entered_at": entered.isoformat() if entered else None,
            "staging_due_at": due.isoformat() if due else None,
            "staging_overdue": False,
            "staging_age_hours": None,
        }

    now = datetime.now(timezone.utc)
    age_hours: int | None = None
    if entered is not None:
        age_hours = max(0, int((now - entered).total_seconds() // 3600))
    overdue = bool(due is not None and now >= due)
    return {
        "staging_entered_at": entered.isoformat() if entered else None,
        "staging_due_at": due.isoformat() if due else None,
        "staging_overdue": overdue,
        "staging_age_hours": age_hours,
    }


def _json_text(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def _hash_score_source(*, title: str, enrichment: dict[str, Any], profile_version: int) -> str:
    payload = {"title": title, "enrichment": enrichment, "profile_version": profile_version}
    return hashlib.sha1(_json_text(payload).encode("utf-8")).hexdigest()


def _upsert_match_row(
    conn: Any,
    *,
    job_id: str,
    url: str,
    profile_version: int,
    match: dict[str, Any],
    source_hash: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO job_match_scores
        (job_id, url, profile_version, score, band, breakdown_json, reasons_json, confidence, computed_at, source_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            url,
            profile_version,
            int(match.get("score", 0) or 0),
            str(match.get("band") or "low"),
            _json_text(match.get("breakdown") or {}),
            _json_text(match.get("reasons") or []),
            str(match.get("confidence") or "low"),
            _now_iso(),
            source_hash,
        ),
    )


def _parse_match_row(row: tuple[Any, ...]) -> dict[str, Any]:
    breakdown: dict[str, int] = {}
    reasons: list[str] = []
    try:
        parsed_breakdown = json.loads(str(row[3] or "{}"))
        if isinstance(parsed_breakdown, dict):
            breakdown = {str(k): int(v) for k, v in parsed_breakdown.items()}
    except Exception:
        breakdown = {}
    try:
        parsed_reasons = json.loads(str(row[4] or "[]"))
        if isinstance(parsed_reasons, list):
            reasons = [str(v) for v in parsed_reasons]
    except Exception:
        reasons = []
    return {
        "profile_version": int(row[0]),
        "score": int(row[1]),
        "band": str(row[2]),
        "breakdown": breakdown,
        "reasons": reasons,
        "confidence": str(row[5] or "low"),
        "computed_at": row[6],
    }


def _match_breakdown_value(value: Any, key: str) -> int:
    if isinstance(value, dict):
        raw = value.get(key)
        try:
            return int(raw or 0)
        except Exception:
            return 0
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return 0
        return _match_breakdown_value(parsed, key)
    return 0


def _normalized_status_sql(tracking_column: str, application_column: str) -> str:
    source = f"COALESCE({tracking_column}, {application_column})"
    return f"CASE WHEN {source} = 'withdrawn' THEN 'rejected' ELSE COALESCE({source}, 'not_applied') END"


def _not_suppressed_sql(job_alias: str = "j") -> str:
    return (
        f"NOT EXISTS ("
        f"SELECT 1 FROM job_suppressions js "
        f"WHERE js.job_id = {job_alias}.id AND js.active = 1)"
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

    profile = get_candidate_profile(conn)
    profile_version = int(profile.get("score_version") or 1)

    order_sql = "ORDER BY date(j.posted) DESC"
    if sort == "updated_desc":
        order_sql = "ORDER BY COALESCE(t.updated_at, j.last_seen) DESC"
    elif sort == "company_asc":
        order_sql = "ORDER BY j.company ASC, j.title ASC"
    elif sort == "match_desc":
        order_sql = "ORDER BY COALESCE(ms.score, -1) DESC, date(j.posted) DESC"

    count_sql = f"""
        SELECT COUNT(*)
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
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
            t.staging_entered_at,
            t.staging_due_at,
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
            e.enrichment_model,
            ms.score,
            ms.band,
            ms.breakdown_json,
            j.id
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
        LEFT JOIN job_enrichments e ON e.job_id = j.id
        LEFT JOIN job_match_scores ms ON ms.job_id = j.id AND ms.profile_version = ?
        {where_sql}
        {order_sql}
    """
    data_params: list[Any] = [profile_version, *params]
    if sort != "match_desc":
        data_sql += "\nLIMIT ? OFFSET ?"
        data_params.extend([limit, offset])
    rows = conn.execute(data_sql, tuple(data_params)).fetchall()
    missing: list[tuple[str, str, str, dict[str, Any]]] = []
    items: list[dict[str, Any]] = []
    for r in rows:
        score = r[30]
        band = r[31]
        desired_title_match = _match_breakdown_value(r[32], "desired_title_alignment") > 0
        enrichment = _build_enrichment_payload(
            {
                "work_mode": r[11],
                "remote_geo": r[12],
                "canada_eligible": r[13],
                "seniority": r[14],
                "role_family": r[15],
                "years_exp_min": r[16],
                "years_exp_max": r[17],
                "minimum_degree": r[18],
                "required_skills": r[19],
                "preferred_skills": r[20],
                "formatted_description": r[21],
                "salary_min": r[22],
                "salary_max": r[23],
                "salary_currency": r[24],
                "visa_sponsorship": r[25],
                "red_flags": r[26],
                "enriched_at": r[27],
                "enrichment_status": r[28],
                "enrichment_model": r[29],
            }
        )
        if score is None:
            missing.append((str(r[33] or ""), str(r[0] or ""), str(r[2] or ""), enrichment))
        staging = _staging_sla_fields(r[6], r[9], r[10])
        items.append(
            {
                "id": str(r[33] or ""),
                "url": r[0],
                "company": r[1],
                "title": r[2],
                "location": r[3],
                "posted": r[4],
                "ats": r[5],
                "status": r[6],
                "priority": r[7],
                "updated_at": r[8],
                "match_score": int(score) if isinstance(score, int) else None,
                "match_band": str(band) if band is not None else None,
                "desired_title_match": desired_title_match,
                "staging_entered_at": staging["staging_entered_at"],
                "staging_due_at": staging["staging_due_at"],
                "staging_overdue": bool(staging["staging_overdue"]),
                "staging_age_hours": staging["staging_age_hours"],
            }
        )

    if missing:
        computed: dict[str, dict[str, Any]] = {}
        for job_id, url, title, enrichment in missing:
            match = compute_match_score({"title": title, "enrichment": enrichment}, profile)
            source_hash = _hash_score_source(title=title, enrichment=enrichment, profile_version=profile_version)
            _upsert_match_row(
                conn,
                job_id=job_id,
                url=url,
                profile_version=profile_version,
                match=match,
                source_hash=source_hash,
            )
            computed[job_id] = match
        conn.commit()
        for item in items:
            match = computed.get(str(item.get("id") or ""))
            if match:
                item["match_score"] = int(match["score"])
                item["match_band"] = str(match["band"])
                item["desired_title_match"] = _match_breakdown_value(match.get("breakdown"), "desired_title_alignment") > 0
        if sort == "match_desc":
            items.sort(
                key=lambda x: (int(x.get("match_score") or -1), str(x.get("posted") or "")),
                reverse=True,
            )
    if sort == "match_desc":
        items.sort(
            key=lambda x: (int(x.get("match_score") or -1), str(x.get("posted") or "")),
            reverse=True,
        )
        items = items[offset:offset + limit]
    return items, total


def list_jobs_snapshot(conn: Any) -> list[dict[str, Any]]:
    profile = get_candidate_profile(conn)
    profile_version = int(profile.get("score_version") or 1)
    rows = conn.execute(
        f"""
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
            t.staging_entered_at,
            t.staging_due_at,
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
            e.enrichment_model,
            ms.score,
            ms.band,
            ms.breakdown_json,
            j.id,
            CASE
                WHEN EXISTS (
                    SELECT 1 FROM job_suppressions js
                    WHERE js.job_id = j.id AND js.active = 1
                ) THEN 1
                ELSE 0
            END AS suppressed
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
        LEFT JOIN job_enrichments e ON e.job_id = j.id
        LEFT JOIN job_match_scores ms ON ms.job_id = j.id AND ms.profile_version = ?
        """,
        (profile_version,),
    ).fetchall()

    missing: list[tuple[str, str, str, dict[str, Any]]] = []
    items: list[dict[str, Any]] = []
    for r in rows:
        score = r[30]
        band = r[31]
        desired_title_match = _match_breakdown_value(r[32], "desired_title_alignment") > 0
        enrichment = _build_enrichment_payload(
            {
                "work_mode": r[11],
                "remote_geo": r[12],
                "canada_eligible": r[13],
                "seniority": r[14],
                "role_family": r[15],
                "years_exp_min": r[16],
                "years_exp_max": r[17],
                "minimum_degree": r[18],
                "required_skills": r[19],
                "preferred_skills": r[20],
                "formatted_description": r[21],
                "salary_min": r[22],
                "salary_max": r[23],
                "salary_currency": r[24],
                "visa_sponsorship": r[25],
                "red_flags": r[26],
                "enriched_at": r[27],
                "enrichment_status": r[28],
                "enrichment_model": r[29],
            }
        )
        if score is None:
            missing.append((str(r[33] or ""), str(r[0] or ""), str(r[2] or ""), enrichment))
        staging = _staging_sla_fields(r[6], r[9], r[10])
        company = r[1]
        title = r[2]
        location = r[3]
        ats = r[5]
        posted = r[4]
        updated_at = r[8]
        items.append(
            {
                "id": str(r[33] or ""),
                "url": r[0],
                "company": company,
                "title": title,
                "location": location,
                "posted": posted,
                "ats": ats,
                "status": r[6],
                "priority": r[7],
                "updated_at": updated_at,
                "match_score": int(score) if isinstance(score, int) else None,
                "match_band": str(band) if band is not None else None,
                "desired_title_match": desired_title_match,
                "staging_entered_at": staging["staging_entered_at"],
                "staging_due_at": staging["staging_due_at"],
                "staging_overdue": bool(staging["staging_overdue"]),
                "staging_age_hours": staging["staging_age_hours"],
                "_suppressed": bool(r[34]),
                "_search_text": f"{title} {company} {location} {ats}".strip().lower(),
                "_company_sort": str(company).casefold(),
                "_posted_sort": str(posted or ""),
                "_updated_sort": str(updated_at or posted or ""),
            }
        )

    if missing:
        computed: dict[str, dict[str, Any]] = {}
        for job_id, url, title, enrichment in missing:
            match = compute_match_score({"title": title, "enrichment": enrichment}, profile)
            source_hash = _hash_score_source(title=title, enrichment=enrichment, profile_version=profile_version)
            _upsert_match_row(
                conn,
                job_id=job_id,
                url=url,
                profile_version=profile_version,
                match=match,
                source_hash=source_hash,
            )
            computed[job_id] = match
        conn.commit()
        for item in items:
            match = computed.get(str(item.get("id") or ""))
            if match:
                item["match_score"] = int(match["score"])
                item["match_band"] = str(match["band"])
                item["desired_title_match"] = _match_breakdown_value(match.get("breakdown"), "desired_title_alignment") > 0
    return items


def _get_job_detail_where(conn: Any, where_sql: str, value: str) -> dict[str, Any] | None:
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
            t.staging_entered_at,
            t.staging_due_at,
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
            e.enrichment_model,
            j.id
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
        LEFT JOIN job_enrichments e ON e.job_id = j.id
        WHERE {where_sql}
        """,
        (value,),
    ).fetchone()
    if not row:
        return None
    enrichment = None
    if any(value is not None for value in row[18:37]):
        enrichment = _build_enrichment_payload(
            {
                "work_mode": row[18],
                "remote_geo": row[19],
                "canada_eligible": row[20],
                "seniority": row[21],
                "role_family": row[22],
                "years_exp_min": row[23],
                "years_exp_max": row[24],
                "minimum_degree": row[25],
                "required_skills": row[26],
                "preferred_skills": row[27],
                "formatted_description": row[28],
                "salary_min": row[29],
                "salary_max": row[30],
                "salary_currency": row[31],
                "visa_sponsorship": row[32],
                "red_flags": row[33],
                "enriched_at": row[34],
                "enrichment_status": row[35],
                "enrichment_model": row[36],
            }
        )

    profile = get_candidate_profile(conn)
    profile_version = int(profile.get("score_version") or 1)
    score_row = conn.execute(
        """
        SELECT profile_version, score, band, breakdown_json, reasons_json, confidence, computed_at
        FROM job_match_scores
        WHERE job_id = ?
        ORDER BY profile_version DESC
        LIMIT 1
        """,
        (str(row[37] or ""),),
    ).fetchone()
    match = None
    stale = True
    computed_at = None
    if score_row:
        parsed = _parse_match_row(score_row)
        match = {
            "score": parsed["score"],
            "band": parsed["band"],
            "breakdown": parsed["breakdown"],
            "reasons": parsed["reasons"],
            "confidence": parsed["confidence"],
        }
        stale = int(parsed["profile_version"]) != profile_version
        computed_at = parsed["computed_at"]
    else:
        # Prime detail score when missing to avoid showing empty score indefinitely.
        match = compute_match_score({"title": row[2], "enrichment": enrichment or {}}, profile)
        source_hash = _hash_score_source(title=row[2], enrichment=enrichment or {}, profile_version=profile_version)
        _upsert_match_row(
            conn,
            job_id=str(row[37] or ""),
            url=str(row[0]),
            profile_version=profile_version,
            match=match,
            source_hash=source_hash,
        )
        conn.commit()
        stale = False

    staging = _staging_sla_fields(row[10], row[16], row[17])
    desired_title_match = _match_breakdown_value(match.get("breakdown") if isinstance(match, dict) else {}, "desired_title_alignment") > 0
    return {
        "id": str(row[37] or ""),
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
        "staging_entered_at": staging["staging_entered_at"],
        "staging_due_at": staging["staging_due_at"],
        "staging_overdue": bool(staging["staging_overdue"]),
        "staging_age_hours": staging["staging_age_hours"],
        "enrichment": enrichment,
        "match": match,
        "desired_title_match": desired_title_match,
        "match_meta": {
            "profile_version": profile_version,
            "computed_at": computed_at,
            "stale": stale,
        },
    }


def get_job_detail(conn: Any, job_id: str) -> dict[str, Any] | None:
    return _get_job_detail_where(conn, "j.id = ?", job_id)


def get_job_url_by_id(conn: Any, job_id: str) -> str | None:
    row = conn.execute("SELECT url FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row or not row[0]:
        return None
    return str(row[0])


def get_job_id_by_url(conn: Any, url: str) -> str | None:
    row = conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
    if not row or not row[0]:
        return None
    return str(row[0])


def upsert_tracking(conn: Any, job_id: str, patch: dict[str, Any]) -> None:
    job_url = get_job_url_by_id(conn, job_id)
    if not job_url:
        raise ValueError("job not found")
    existing = conn.execute(
        "SELECT status, priority, applied_at, next_step, target_compensation, staging_entered_at, staging_due_at FROM job_tracking WHERE job_id = ?",
        (job_id,),
    ).fetchone()

    now = _now_iso()
    if existing:
        previous_status = str(existing[0] or "not_applied")
        status = str(patch.get("status", previous_status) or previous_status)
        priority = patch.get("priority", existing[1])
        applied_at = patch.get("applied_at", existing[2])
        next_step = patch.get("next_step", existing[3])
        target_compensation = patch.get("target_compensation", existing[4])
        staging_entered_at = existing[5]
        staging_due_at = existing[6]
        if previous_status != "staging" and status == "staging":
            staging_entered_at = now
            staging_due_at = _plus_hours_iso(now, 48)
        elif previous_status == "staging" and status == "staging":
            if not staging_entered_at:
                staging_entered_at = now
            if not staging_due_at:
                staging_due_at = _plus_hours_iso(str(staging_entered_at), 48)
        else:
            staging_entered_at = None
            staging_due_at = None
        conn.execute(
            """
            UPDATE job_tracking
            SET url = ?, status = ?, priority = ?, applied_at = ?, next_step = ?, target_compensation = ?, staging_entered_at = ?, staging_due_at = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (job_url, status, priority, applied_at, next_step, target_compensation, staging_entered_at, staging_due_at, now, job_id),
        )
    else:
        status = str(patch.get("status", "not_applied") or "not_applied")
        priority = patch.get("priority", "medium")
        applied_at = patch.get("applied_at")
        next_step = patch.get("next_step")
        target_compensation = patch.get("target_compensation")
        staging_entered_at = now if status == "staging" else None
        staging_due_at = _plus_hours_iso(now, 48) if status == "staging" else None
        conn.execute(
            """
            INSERT INTO job_tracking (job_id, url, status, priority, applied_at, next_step, target_compensation, staging_entered_at, staging_due_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, job_url, status, priority, applied_at, next_step, target_compensation, staging_entered_at, staging_due_at, now),
        )

    conn.execute("UPDATE jobs SET application_status = ? WHERE id = ?", (status, job_id))
    conn.commit()


def get_tracking_status(conn: Any, job_id: str) -> str:
    row = conn.execute(
        f"""
        SELECT {_normalized_status_sql('t.status', 'j.application_status')}
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
        WHERE j.id = ?
        """,
        (job_id,),
    ).fetchone()
    if not row:
        raise ValueError("job not found")
    return str(row[0] or "not_applied")


def _parse_json_object(raw: Any, *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    fallback_value = fallback if fallback is not None else {}
    if raw is None:
        return dict(fallback_value)
    if isinstance(raw, dict):
        return dict(raw)
    if not isinstance(raw, str):
        return dict(fallback_value)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return dict(fallback_value)
    if isinstance(parsed, dict):
        return parsed
    return dict(fallback_value)


def _resolve_pointer_parent(doc: Any, pointer: str) -> tuple[Any, str]:
    if not pointer or pointer == "/":
        raise ValueError("pointer must target a property path")
    if not pointer.startswith("/"):
        raise ValueError("pointer must start with '/'")
    parts = pointer.lstrip("/").split("/")
    decoded = [part.replace("~1", "/").replace("~0", "~") for part in parts]
    target = doc
    for part in decoded[:-1]:
        if isinstance(target, list):
            index = int(part)
            target = target[index]
        elif isinstance(target, dict):
            if part not in target:
                raise KeyError(f"Path segment '{part}' not found")
            target = target[part]
        else:
            raise TypeError("Unsupported path target")
    return target, decoded[-1]


def _apply_json_patch(doc: dict[str, Any], patch_ops: list[dict[str, Any]]) -> dict[str, Any]:
    updated = copy.deepcopy(doc)
    for op in patch_ops:
        op_name = str(op.get("op") or "").strip().lower()
        path = str(op.get("path") or "")
        parent, key = _resolve_pointer_parent(updated, path)
        if isinstance(parent, list):
            if key == "-":
                if op_name == "add":
                    parent.append(op.get("value"))
                    continue
                raise ValueError("'-' index is only valid for add operations")
            index = int(key)
            if op_name == "remove":
                parent.pop(index)
                continue
            if op_name == "add":
                parent.insert(index, op.get("value"))
                continue
            if op_name == "replace":
                parent[index] = op.get("value")
                continue
            raise ValueError(f"Unsupported patch op: {op_name}")
        if isinstance(parent, dict):
            if op_name == "remove":
                parent.pop(key, None)
                continue
            if op_name in {"add", "replace"}:
                parent[key] = op.get("value")
                continue
            raise ValueError(f"Unsupported patch op: {op_name}")
        raise TypeError("Unsupported patch parent")
    return updated


def _sha256_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _default_resume_content(profile: dict[str, Any], job: dict[str, Any], resume_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    skills = [str(skill).strip() for skill in profile.get("skills", []) if str(skill).strip()]
    summary = f"Targeting {job.get('title', 'this role')} opportunities with strengths in ML and data systems."
    if skills:
        summary = f"Targeting {job.get('title', 'this role')} roles with strengths in {', '.join(skills[:4])}."
    base = {
        "basics": {
            "name": "",
            "label": job.get("title") or "",
            "summary": summary,
        },
        "work": [],
        "education": profile.get("education", []),
        "skills": [{"name": skill} for skill in skills],
        "meta": {
            "job_company": job.get("company", ""),
            "job_title": job.get("title", ""),
        },
    }
    baseline = (resume_profile or {}).get("baseline_resume_json")
    if isinstance(baseline, dict) and baseline:
        merged = copy.deepcopy(baseline)
        meta = merged.get("meta") if isinstance(merged.get("meta"), dict) else {}
        meta["job_company"] = job.get("company", "")
        meta["job_title"] = job.get("title", "")
        merged["meta"] = meta
        basics = merged.get("basics") if isinstance(merged.get("basics"), dict) else {}
        if not str(basics.get("label") or "").strip():
            basics["label"] = job.get("title") or ""
        merged["basics"] = basics
        return merged
    return base


def _default_cover_letter_content(job: dict[str, Any]) -> dict[str, Any]:
    company = str(job.get("company") or "Hiring Team")
    role = str(job.get("title") or "the role")
    return {
        "frontmatter": {
            "tone": "neutral",
            "recipient": company,
            "subject": f"Application for {role}",
        },
        "blocks": [
            {"id": str(uuid.uuid4()), "type": "paragraph", "text": f"Dear {company},"},
            {
                "id": str(uuid.uuid4()),
                "type": "paragraph",
                "text": f"I am excited to apply for {role}. My background aligns strongly with the responsibilities and requirements outlined in the posting.",
            },
            {
                "id": str(uuid.uuid4()),
                "type": "paragraph",
                "text": "I would welcome the opportunity to discuss how I can contribute to your team.",
            },
            {"id": str(uuid.uuid4()), "type": "paragraph", "text": "Sincerely,\n[Your Name]"},
        ],
    }


def _artifact_row_to_summary(row: tuple[Any, ...]) -> dict[str, Any]:
    active_version = None
    if row[5] is not None:
        active_version = {
            "id": str(row[5]),
            "artifact_id": str(row[0]),
            "version": int(row[6]),
            "label": str(row[7] or "draft"),
            "content_json": _parse_json_object(row[8]),
            "content_text": str(row[9]) if row[9] is not None else None,
            "meta_json": _parse_json_object(row[10]),
            "created_at": str(row[11]),
            "created_by": str(row[12] or "system"),
            "supersedes_version_id": str(row[13]) if row[13] else None,
            "base_version_id": str(row[14]) if row[14] else None,
        }
    return {
        "id": str(row[0]),
        "job_url": str(row[1]),
        "job_id": str(row[15] or ""),
        "artifact_type": str(row[2]),
        "active_version_id": str(row[3]) if row[3] else None,
        "created_at": str(row[4]),
        "active_version": active_version,
    }


def _artifact_summary_from_offsets(
    row: tuple[Any, ...],
    offset: int,
    *,
    job_id: str | None = None,
) -> dict[str, Any] | None:
    artifact_id = row[offset]
    if artifact_id is None:
        return None
    active_version = None
    if row[offset + 5] is not None:
        active_version = {
            "id": str(row[offset + 5]),
            "artifact_id": str(artifact_id),
            "version": int(row[offset + 6]),
            "label": str(row[offset + 7] or "draft"),
            "content_json": _parse_json_object(row[offset + 8]),
            "content_text": str(row[offset + 9]) if row[offset + 9] is not None else None,
            "meta_json": _parse_json_object(row[offset + 10]),
            "created_at": str(row[offset + 11]),
            "created_by": str(row[offset + 12] or "system"),
            "supersedes_version_id": str(row[offset + 13]) if row[offset + 13] else None,
            "base_version_id": str(row[offset + 14]) if row[offset + 14] else None,
        }
    return {
        "id": str(artifact_id),
        "job_id": str(job_id or ""),
        "job_url": str(row[offset + 1]),
        "artifact_type": str(row[offset + 2]),
        "active_version_id": str(row[offset + 3]) if row[offset + 3] else None,
        "created_at": str(row[offset + 4]),
        "active_version": active_version,
    }


def _artifact_summary_from_offsets_compact(
    row: tuple[Any, ...],
    offset: int,
    *,
    job_id: str | None = None,
) -> dict[str, Any] | None:
    artifact_id = row[offset]
    if artifact_id is None:
        return None
    active_version = None
    if row[offset + 5] is not None:
        active_version = {
            "id": str(row[offset + 5]),
            "artifact_id": str(artifact_id),
            "version": int(row[offset + 6]),
            "label": str(row[offset + 7] or "draft"),
            "content_json": None,
            "content_text": None,
            "meta_json": {},
            "created_at": str(row[offset + 8]),
            "created_by": str(row[offset + 9] or "system"),
            "supersedes_version_id": str(row[offset + 10]) if row[offset + 10] else None,
            "base_version_id": str(row[offset + 11]) if row[offset + 11] else None,
        }
    return {
        "id": str(artifact_id),
        "job_id": str(job_id or ""),
        "job_url": str(row[offset + 1]),
        "artifact_type": str(row[offset + 2]),
        "active_version_id": str(row[offset + 3]) if row[offset + 3] else None,
        "created_at": str(row[offset + 4]),
        "active_version": active_version,
    }


def list_artifacts_hub(
    conn: Any,
    *,
    q: str | None,
    status: str | None,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = [_not_suppressed_sql("j"), "(ra.id IS NOT NULL OR ca.id IS NOT NULL)"]
    params: list[Any] = []
    if status:
        where.append(f"{_normalized_status_sql('t.status', 'j.application_status')} = ?")
        params.append(status)
    if q:
        qv = f"%{q}%"
        where.append("(j.company LIKE ? OR j.title LIKE ? OR j.url LIKE ?)")
        params.extend([qv, qv, qv])
    where_sql = "WHERE " + " AND ".join(where)

    latest_updated_sql = (
        "COALESCE("
        "CASE "
        "WHEN rv.created_at IS NOT NULL AND (cv.created_at IS NULL OR datetime(rv.created_at) >= datetime(cv.created_at)) "
        "THEN rv.created_at ELSE cv.created_at END, "
        "t.updated_at, j.last_seen, j.posted)"
    )

    count_sql = f"""
        SELECT COUNT(*)
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
        LEFT JOIN job_artifacts ra ON ra.job_id = j.id AND ra.artifact_type = 'resume'
        LEFT JOIN job_artifacts ca ON ca.job_id = j.id AND ca.artifact_type = 'cover_letter'
        {where_sql}
    """
    total_row = conn.execute(count_sql, tuple(params)).fetchone()
    total = int(total_row[0]) if total_row else 0

    order_sql = (
        f"ORDER BY datetime({latest_updated_sql}) DESC, j.company ASC, j.title ASC"
        if sort == "updated_desc"
        else "ORDER BY j.company ASC, j.title ASC"
    )

    data_sql = f"""
        SELECT
            j.url,
            COALESCE(j.company, ''),
            COALESCE(j.title, ''),
            {_normalized_status_sql('t.status', 'j.application_status')},
            t.updated_at,
            {latest_updated_sql},
            j.id,

            ra.id, ra.job_url, ra.artifact_type, ra.active_version_id, ra.created_at,
            rv.id, rv.version, rv.label, rv.created_at, rv.created_by, rv.supersedes_version_id, rv.base_version_id,

            ca.id, ca.job_url, ca.artifact_type, ca.active_version_id, ca.created_at,
            cv.id, cv.version, cv.label, cv.created_at, cv.created_by, cv.supersedes_version_id, cv.base_version_id
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
        LEFT JOIN job_artifacts ra ON ra.job_id = j.id AND ra.artifact_type = 'resume'
        LEFT JOIN artifact_versions rv ON rv.id = ra.active_version_id
        LEFT JOIN job_artifacts ca ON ca.job_id = j.id AND ca.artifact_type = 'cover_letter'
        LEFT JOIN artifact_versions cv ON cv.id = ca.active_version_id
        {where_sql}
        {order_sql}
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(data_sql, tuple([*params, limit, offset])).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        job_id = str(row[6] or "")
        resume = _artifact_summary_from_offsets_compact(row, 7, job_id=job_id)
        cover_letter = _artifact_summary_from_offsets_compact(row, 19, job_id=job_id)
        items.append(
            {
                "job_url": str(row[0]),
                "job_id": job_id,
                "company": str(row[1]),
                "title": str(row[2]),
                "tracking_status": str(row[3]),
                "tracking_updated_at": str(row[4]) if row[4] else None,
                "latest_artifact_updated_at": str(row[5]) if row[5] else None,
                "resume": resume,
                "cover_letter": cover_letter,
            }
        )
    return items, total


def ensure_starter_artifacts_for_job(conn: Any, job_id: str) -> list[dict[str, Any]]:
    return ensure_starter_artifacts_for_job_with_progress(conn, job_id)


def ensure_starter_artifacts_for_job_with_progress(
    conn: Any,
    job_id: str,
    progress_cb: Callable[[str, int], None] | None = None,
) -> list[dict[str, Any]]:
    job = get_job_detail(conn, job_id)
    if not job:
        raise ValueError("job not found")
    profile = get_candidate_profile(conn)
    resume_profile = get_resume_profile(conn)
    template_settings = get_template_settings(conn)
    resume_template_id = str((template_settings or {}).get("resume_template_id") or "classic").strip() or "classic"
    cover_letter_template_id = str((template_settings or {}).get("cover_letter_template_id") or "classic").strip() or "classic"
    use_template_typography = bool((resume_profile or {}).get("use_template_typography", True))
    document_typography_override = (
        (resume_profile or {}).get("document_typography_override")
        if isinstance((resume_profile or {}).get("document_typography_override"), dict)
        else {}
    )
    typography, typography_source = resolve_document_typography(
        template_id=resume_template_id,
        use_template_typography=use_template_typography,
        document_typography_override=document_typography_override,
    )
    created_at = _now_iso()
    created: list[dict[str, Any]] = []
    total_steps = 4
    if progress_cb:
        progress_cb("queued", 5)
    for step_index, artifact_type in enumerate(("resume", "cover_letter"), start=1):
        existing = conn.execute(
            "SELECT id FROM job_artifacts WHERE job_id = ? AND artifact_type = ?",
            (job_id, artifact_type),
        ).fetchone()
        stage_name = "creating_resume" if artifact_type == "resume" else "creating_cover_letter"
        if progress_cb:
            pct = 5 + int((step_index - 1) / total_steps * 80)
            progress_cb(stage_name, pct)
        if existing:
            continue
        artifact_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO job_artifacts (id, job_id, job_url, artifact_type, active_version_id, created_at)
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (artifact_id, job_id, str(job.get("url") or ""), artifact_type, created_at),
        )
        initial_content = (
            _default_resume_content(profile, job, resume_profile)
            if artifact_type == "resume"
            else _default_cover_letter_content(job)
        )
        initial_text = (
            bootstrap_resume_tex(
                profile=profile,
                resume_profile=resume_profile,
                job=job,
                template_id=resume_template_id,
            )
            if artifact_type == "resume"
            else bootstrap_cover_letter_tex(
                job=job,
                template_id=cover_letter_template_id,
            )
        )
        version = create_artifact_version(
            conn,
            artifact_id=artifact_id,
            label="draft",
            content_json=initial_content,
            meta_json={
                "templateId": resume_template_id if artifact_type == "resume" else cover_letter_template_id,
                "layout": {"fontSize": typography.get("fontSize", 11), "lineHeight": typography.get("lineHeight", 1.35)},
                "typography": typography,
                "typographySource": typography_source,
                "sourceKind": "latex",
            },
            content_text=initial_text,
            created_by="system",
            base_version_id=None,
        )
        created.append({"artifact_id": artifact_id, "version_id": version["id"], "artifact_type": artifact_type})
    if progress_cb:
        progress_cb("finalizing", 95)
    conn.commit()
    if progress_cb:
        progress_cb("done", 100)
    return created


def list_job_artifacts(conn: Any, job_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            a.id,
            a.job_url,
            a.artifact_type,
            a.active_version_id,
            a.created_at,
            v.id,
            v.version,
            v.label,
            v.content_json,
            v.content_text,
            v.meta_json,
            v.created_at,
            v.created_by,
            v.supersedes_version_id,
            v.base_version_id,
            a.job_id
        FROM job_artifacts a
        LEFT JOIN artifact_versions v ON v.id = a.active_version_id
        WHERE a.job_id = ?
        ORDER BY a.artifact_type ASC
        """,
        (job_id,),
    ).fetchall()
    return [_artifact_row_to_summary(row) for row in rows]


def get_artifact(conn: Any, artifact_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            a.id,
            a.job_url,
            a.artifact_type,
            a.active_version_id,
            a.created_at,
            v.id,
            v.version,
            v.label,
            v.content_json,
            v.content_text,
            v.meta_json,
            v.created_at,
            v.created_by,
            v.supersedes_version_id,
            v.base_version_id,
            a.job_id
        FROM job_artifacts a
        LEFT JOIN artifact_versions v ON v.id = a.active_version_id
        WHERE a.id = ?
        """,
        (artifact_id,),
    ).fetchone()
    if not row:
        return None
    return _artifact_row_to_summary(row)


def delete_artifact(conn: Any, artifact_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT job_id, job_url, artifact_type FROM job_artifacts WHERE id = ?",
        (artifact_id,),
    ).fetchone()
    if not row:
        return {"deleted": 0, "job_id": None, "job_url": None, "artifact_type": None}
    job_id = str(row[0]) if row[0] else None
    job_url = str(row[1]) if row[1] else None
    artifact_type = str(row[2]) if row[2] else None
    conn.execute("DELETE FROM artifact_suggestions WHERE artifact_id = ?", (artifact_id,))
    conn.execute("DELETE FROM artifact_versions WHERE artifact_id = ?", (artifact_id,))
    conn.execute("DELETE FROM job_artifacts WHERE id = ?", (artifact_id,))
    changed = conn.execute("SELECT changes()").fetchone()
    conn.commit()
    return {
        "deleted": int(changed[0]) if changed else 0,
        "job_id": job_id,
        "job_url": job_url,
        "artifact_type": artifact_type,
    }


def delete_job_artifact_by_type(conn: Any, job_id: str, artifact_type: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id FROM job_artifacts WHERE job_id = ? AND artifact_type = ?",
        (job_id, artifact_type),
    ).fetchone()
    if not row or not row[0]:
        return {"deleted": 0, "job_id": job_id, "job_url": get_job_url_by_id(conn, job_id), "artifact_type": artifact_type}
    return delete_artifact(conn, str(row[0]))


def list_artifact_versions(conn: Any, artifact_id: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            id, artifact_id, version, label, content_json, content_text, meta_json, created_at, created_by, supersedes_version_id, base_version_id
        FROM artifact_versions
        WHERE artifact_id = ?
        ORDER BY version DESC
        LIMIT ?
        """,
        (artifact_id, limit),
    ).fetchall()
    return [
        {
            "id": str(row[0]),
            "artifact_id": str(row[1]),
            "version": int(row[2]),
            "label": str(row[3] or "draft"),
            "content_json": _parse_json_object(row[4]),
            "content_text": str(row[5]) if row[5] is not None else None,
            "meta_json": _parse_json_object(row[6]),
            "created_at": str(row[7]),
            "created_by": str(row[8] or "system"),
            "supersedes_version_id": str(row[9]) if row[9] else None,
            "base_version_id": str(row[10]) if row[10] else None,
        }
        for row in rows
    ]


def create_artifact_version(
    conn: Any,
    *,
    artifact_id: str,
    label: str,
    content_json: dict[str, Any],
    meta_json: dict[str, Any],
    content_text: str | None = None,
    created_by: str,
    base_version_id: str | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    normalized_meta = dict(meta_json) if isinstance(meta_json, dict) else {}
    template_id = str(normalized_meta.get("templateId") or "classic").strip().lower() or "classic"
    typography_raw = normalized_meta.get("typography")
    if isinstance(typography_raw, dict) and typography_raw:
        typography = dict(typography_raw)
        typography_source = str(normalized_meta.get("typographySource") or "version")
    else:
        typography, typography_source = resolve_document_typography(
            template_id=template_id,
            use_template_typography=True,
            document_typography_override={},
        )
    normalized_meta["templateId"] = template_id
    normalized_meta["typography"] = typography
    normalized_meta["typographySource"] = typography_source
    layout = normalized_meta.get("layout")
    layout_obj = dict(layout) if isinstance(layout, dict) else {}
    layout_obj["fontSize"] = float(typography.get("fontSize") or layout_obj.get("fontSize") or 11)
    layout_obj["lineHeight"] = float(typography.get("lineHeight") or layout_obj.get("lineHeight") or 1.35)
    normalized_meta["layout"] = layout_obj
    document_layout = normalized_meta.get("documentLayout")
    document_layout_obj = dict(document_layout) if isinstance(document_layout, dict) else {}
    page_obj = dict(document_layout_obj.get("page")) if isinstance(document_layout_obj.get("page"), dict) else {}
    global_obj = dict(document_layout_obj.get("global")) if isinstance(document_layout_obj.get("global"), dict) else {}
    page_obj["size"] = "A4"
    page_obj["marginTopMm"] = float(page_obj.get("marginTopMm") or 18)
    page_obj["marginRightMm"] = float(page_obj.get("marginRightMm") or 14)
    page_obj["marginBottomMm"] = float(page_obj.get("marginBottomMm") or 18)
    page_obj["marginLeftMm"] = float(page_obj.get("marginLeftMm") or 14)
    global_obj["fontFamily"] = str(global_obj.get("fontFamily") or typography.get("fontFamily") or "Georgia, 'Times New Roman', serif")
    global_obj["fontSizePx"] = float(global_obj.get("fontSizePx") or typography.get("fontSize") or 11)
    global_obj["lineHeight"] = float(global_obj.get("lineHeight") or typography.get("lineHeight") or 1.35)
    align = str(global_obj.get("textAlign") or "left").strip().lower()
    global_obj["textAlign"] = align if align in {"left", "justify", "center"} else "left"
    document_layout_obj["page"] = page_obj
    document_layout_obj["global"] = global_obj
    normalized_meta["documentLayout"] = document_layout_obj
    if not isinstance(normalized_meta.get("sectionLayout"), dict):
        normalized_meta["sectionLayout"] = {}
    if not isinstance(normalized_meta.get("paginationRules"), dict):
        normalized_meta["paginationRules"] = {"sectionSplitMode": "never_split_section"}
    retries = 2
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            current_row = conn.execute(
                "SELECT active_version_id FROM job_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
            if not current_row:
                raise ValueError("artifact not found")
            current_active = str(current_row[0]) if current_row and current_row[0] else None
            max_row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM artifact_versions WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            next_version = int(max_row[0] or 0) + 1
            version_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO artifact_versions
                (id, artifact_id, version, label, content_json, content_text, meta_json, created_at, created_by, supersedes_version_id, base_version_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    artifact_id,
                    next_version,
                    label,
                    _json_text(content_json),
                    content_text,
                    _json_text(normalized_meta),
                    now,
                    created_by,
                    current_active,
                    base_version_id,
                ),
            )
            conn.execute(
                "UPDATE job_artifacts SET active_version_id = ? WHERE id = ?",
                (version_id, artifact_id),
            )
            conn.commit()
            return {
                "id": version_id,
                "artifact_id": artifact_id,
                "version": next_version,
                "label": label,
                "content_json": content_json,
                "content_text": content_text,
                "meta_json": normalized_meta,
                "created_at": now,
                "created_by": created_by,
                "supersedes_version_id": current_active,
                "base_version_id": base_version_id,
            }
        except Exception as error:
            last_error = error
            message = str(error).lower()
            if "unique" not in message:
                raise
    if last_error:
        raise last_error
    raise RuntimeError("failed to create artifact version")


def list_artifact_suggestions(conn: Any, artifact_id: str, pending_only: bool = False) -> list[dict[str, Any]]:
    where = "WHERE artifact_id = ?"
    params: list[Any] = [artifact_id]
    if pending_only:
        where += " AND state = 'pending'"
    rows = conn.execute(
        f"""
        SELECT
            id,
            artifact_id,
            base_version_id,
            base_hash,
            target_path,
            patch_json,
            group_key,
            summary,
            state,
            created_at,
            resolved_at,
            supersedes_suggestion_id
        FROM artifact_suggestions
        {where}
        ORDER BY datetime(created_at) DESC
        """,
        tuple(params),
    ).fetchall()
    suggestions: list[dict[str, Any]] = []
    for row in rows:
        patch_list = []
        try:
            parsed = json.loads(str(row[5] or "[]"))
            if isinstance(parsed, list):
                patch_list = [dict(item) for item in parsed if isinstance(item, dict)]
        except Exception:
            patch_list = []
        suggestions.append(
            {
                "id": str(row[0]),
                "artifact_id": str(row[1]),
                "base_version_id": str(row[2]),
                "base_hash": str(row[3]) if row[3] else None,
                "target_path": str(row[4]) if row[4] else None,
                "patch_json": patch_list,
                "group_key": str(row[6]) if row[6] else None,
                "summary": str(row[7]) if row[7] else None,
                "state": str(row[8]),
                "created_at": str(row[9]),
                "resolved_at": str(row[10]) if row[10] else None,
                "supersedes_suggestion_id": str(row[11]) if row[11] else None,
            }
        )
    return suggestions


def create_artifact_suggestions(
    conn: Any,
    *,
    artifact_id: str,
    base_version_id: str,
    suggestions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    base_row = conn.execute(
        "SELECT content_json FROM artifact_versions WHERE id = ? AND artifact_id = ?",
        (base_version_id, artifact_id),
    ).fetchone()
    if not base_row:
        raise ValueError("base version not found")
    base_content = _parse_json_object(base_row[0])
    base_hash = _sha256_json(base_content)
    created_at = _now_iso()
    created: list[dict[str, Any]] = []
    for entry in suggestions:
        suggestion_id = str(uuid.uuid4())
        patch_json = entry.get("patch_json") if isinstance(entry.get("patch_json"), list) else []
        conn.execute(
            """
            INSERT INTO artifact_suggestions
            (id, artifact_id, base_version_id, base_hash, target_path, patch_json, group_key, summary, state, created_at, resolved_at, supersedes_suggestion_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL, ?)
            """,
            (
                suggestion_id,
                artifact_id,
                base_version_id,
                base_hash,
                entry.get("target_path"),
                _json_text(patch_json),
                entry.get("group_key"),
                entry.get("summary"),
                created_at,
                entry.get("supersedes_suggestion_id"),
            ),
        )
        created.append(
            {
                "id": suggestion_id,
                "artifact_id": artifact_id,
                "base_version_id": base_version_id,
                "base_hash": base_hash,
                "target_path": entry.get("target_path"),
                "patch_json": patch_json,
                "group_key": entry.get("group_key"),
                "summary": entry.get("summary"),
                "state": "pending",
                "created_at": created_at,
                "resolved_at": None,
                "supersedes_suggestion_id": entry.get("supersedes_suggestion_id"),
            }
        )
    conn.commit()
    return created


def accept_artifact_suggestion(
    conn: Any,
    *,
    suggestion_id: str,
    edited_patch_json: list[dict[str, Any]] | None,
    allow_outdated: bool,
    created_by: str,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, artifact_id, base_version_id, base_hash, patch_json, state
        FROM artifact_suggestions
        WHERE id = ?
        """,
        (suggestion_id,),
    ).fetchone()
    if not row:
        raise ValueError("suggestion not found")
    if str(row[5]) != "pending":
        raise ValueError("suggestion already resolved")
    artifact_id = str(row[1])
    base_version_id = str(row[2])
    patch_json_raw = edited_patch_json if edited_patch_json is not None else json.loads(str(row[4] or "[]"))

    artifact = get_artifact(conn, artifact_id)
    if not artifact or not artifact.get("active_version_id"):
        raise ValueError("artifact not found")
    active_version_id = str(artifact["active_version_id"])
    if active_version_id != base_version_id and not allow_outdated:
        raise ValueError("outdated suggestion")

    base_version_row = conn.execute(
        "SELECT content_json, content_text, meta_json FROM artifact_versions WHERE id = ? AND artifact_id = ?",
        (base_version_id, artifact_id),
    ).fetchone()
    if not base_version_row:
        raise ValueError("base version missing")
    base_content = _parse_json_object(base_version_row[0])
    base_hash = _sha256_json(base_content)
    stored_hash = str(row[3]) if row[3] else None
    if stored_hash and stored_hash != base_hash and not allow_outdated:
        raise ValueError("outdated suggestion")
    next_content = _apply_json_patch(base_content, [dict(op) for op in patch_json_raw if isinstance(op, dict)])
    base_content_text = str(base_version_row[1]) if base_version_row[1] is not None else None
    meta_json = _parse_json_object(base_version_row[2])
    new_version = create_artifact_version(
        conn,
        artifact_id=artifact_id,
        label="draft",
        content_json=next_content,
        content_text=base_content_text,
        meta_json=meta_json,
        created_by=created_by,
        base_version_id=base_version_id,
    )
    resolved_at = _now_iso()
    conn.execute(
        "UPDATE artifact_suggestions SET state = 'accepted', resolved_at = ? WHERE id = ?",
        (resolved_at, suggestion_id),
    )
    conn.commit()
    return {
        "suggestion_id": suggestion_id,
        "state": "accepted",
        "resolved_at": resolved_at,
        "new_version": new_version,
    }


def reject_artifact_suggestion(conn: Any, suggestion_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT state FROM artifact_suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if not row:
        raise ValueError("suggestion not found")
    if str(row[0]) != "pending":
        raise ValueError("suggestion already resolved")
    resolved_at = _now_iso()
    conn.execute(
        "UPDATE artifact_suggestions SET state = 'rejected', resolved_at = ? WHERE id = ?",
        (resolved_at, suggestion_id),
    )
    conn.commit()
    return {
        "suggestion_id": suggestion_id,
        "state": "rejected",
        "resolved_at": resolved_at,
    }


def create_manual_job(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    existing_job_id = get_job_id_by_url(conn, url)
    if existing_job_id and is_job_suppressed_id(conn, existing_job_id):
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
    job_id = get_job_id_by_url(conn, url)
    if not job_id:
        raise RuntimeError("Failed to resolve manual job id")
    status = str(payload.get("status") or "not_applied").strip().lower()
    allowed_statuses = {"not_applied", "staging", "applied", "interviewing", "offer", "rejected"}
    if status not in allowed_statuses:
        raise ValueError("status must be one of: not_applied, staging, applied, interviewing, offer, rejected")
    upsert_tracking(conn, job_id, {"status": status})
    if status == "staging":
        ensure_starter_artifacts_for_job(conn, job_id)
    detail = get_job_detail(conn, job_id)
    if not detail:
        raise RuntimeError("Failed to save manual job")
    return detail


def suppress_job(conn: Any, *, job_id: str, reason: str | None, created_by: str = "ui") -> None:
    suppress_job_id(conn, job_id=job_id, reason=reason, created_by=created_by)


def unsuppress_job(conn: Any, *, job_id: str) -> int:
    return unsuppress_job_id(conn, job_id)


def list_active_suppressions(conn: Any, *, limit: int = 200) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT job_id, url, COALESCE(company, ''), reason, created_at, updated_at, created_by
        FROM job_suppressions
        WHERE active = 1
        ORDER BY datetime(updated_at) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "job_id": str(row[0] or ""),
            "url": str(row[1] or ""),
            "company": str(row[2] or ""),
            "reason": row[3],
            "created_at": str(row[4]),
            "updated_at": str(row[5]),
            "created_by": str(row[6] or "ui"),
        }
        for row in rows
    ]


def list_events(conn: Any, job_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, job_id, url, event_type, title, body, event_at, created_at
        FROM job_events
        WHERE job_id = ?
        ORDER BY datetime(event_at) DESC, id DESC
        """,
        (job_id,),
    ).fetchall()
    return [
        {
            "id": r[0],
            "job_id": r[1],
            "url": r[2],
            "event_type": r[3],
            "title": r[4],
            "body": r[5],
            "event_at": r[6],
            "created_at": r[7],
        }
        for r in rows
    ]


def create_event(conn: Any, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    job_url = get_job_url_by_id(conn, job_id)
    if not job_url:
        raise ValueError("job not found")
    created = _now_iso()
    conn.execute(
        """
        INSERT INTO job_events (job_id, url, event_type, title, body, event_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (job_id, job_url, payload["event_type"], payload["title"], payload.get("body"), payload["event_at"], created),
    )
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    event_id = int(row[0]) if row else 0
    conn.commit()
    return {
        "id": event_id,
        "job_id": job_id,
        "url": job_url,
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


def delete_job(conn: Any, job_id: str) -> int:
    artifact_rows = conn.execute(
        "SELECT id FROM job_artifacts WHERE job_id = ?",
        (job_id,),
    ).fetchall()
    artifact_ids = [str(row[0]) for row in artifact_rows if row and row[0] is not None]
    if artifact_ids:
        placeholders = ", ".join("?" for _ in artifact_ids)
        conn.execute(
            f"DELETE FROM artifact_suggestions WHERE artifact_id IN ({placeholders})",
            tuple(artifact_ids),
        )
        conn.execute(
            f"DELETE FROM artifact_versions WHERE artifact_id IN ({placeholders})",
            tuple(artifact_ids),
        )
        conn.execute(
            f"DELETE FROM job_artifacts WHERE id IN ({placeholders})",
            tuple(artifact_ids),
        )
    conn.execute("DELETE FROM job_events WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_tracking WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_enrichments WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_match_scores WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
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
            INNER JOIN jobs j ON j.id = t.job_id
            WHERE {_not_suppressed_sql('j')}
            """
        ).fetchone()[0]
    )

    by_status_rows = conn.execute(
        f"""
        SELECT {_normalized_status_sql('t.status', 'j.application_status')} AS s, COUNT(*)
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
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
            INNER JOIN jobs j ON j.id = ev.job_id
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


def bump_profile_score_version(conn: Any) -> int:
    return bump_candidate_profile_score_version(conn)


def get_resume_profile_data(conn: Any) -> dict[str, Any]:
    return get_resume_profile(conn)


def save_resume_profile_data(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return upsert_resume_profile(conn, payload)


def get_template_settings_data(conn: Any) -> dict[str, Any]:
    return get_template_settings(conn)


def save_template_settings_data(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return upsert_template_settings(conn, payload)


def get_candidate_evidence_assets_data(conn: Any) -> dict[str, Any]:
    return get_candidate_evidence_assets(conn)


def save_candidate_evidence_assets_data(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return upsert_candidate_evidence_assets(conn, payload)


def list_company_sources_data(conn: Any, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    return list_company_sources(conn, enabled_only=enabled_only)


def get_company_source_data(conn: Any, row_id: int) -> dict[str, Any] | None:
    return get_company_source_by_id(conn, row_id)


def update_company_source_data(conn: Any, row_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
    return update_company_source(
        conn,
        row_id,
        enabled=payload.get("enabled"),
        name=payload.get("name"),
        source=payload.get("source"),
    )


def create_workspace_operation_data(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return create_workspace_operation(conn, payload)


def list_workspace_operations_data(conn: Any, limit: int = 20) -> list[dict[str, Any]]:
    return list_workspace_operations(conn, limit=limit)


def get_workspace_operation_data(conn: Any, operation_id: str) -> dict[str, Any] | None:
    return get_workspace_operation(conn, operation_id)


def update_workspace_operation_data(conn: Any, operation_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    return update_workspace_operation(conn, operation_id, payload)


def recompute_match_scores(
    conn: Any,
    *,
    urls: list[str] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> int:
    profile = get_candidate_profile(conn)
    profile_version = int(profile.get("score_version") or 1)
    where = ""
    params: list[Any] = []
    if urls:
        placeholders = ", ".join("?" for _ in urls)
        where = f"WHERE j.url IN ({placeholders})"
        params.extend(urls)
    rows = conn.execute(
        f"""
        SELECT
            j.id,
            j.url,
            COALESCE(j.title, ''),
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
        LEFT JOIN job_enrichments e ON e.job_id = j.id
        {where}
        """,
        tuple(params),
    ).fetchall()
    if not rows:
        if progress_callback is not None:
            progress_callback(0, 0)
        return 0
    count = 0
    total = len(rows)
    for row in rows:
        enrichment = _build_enrichment_payload(
            {
                "work_mode": row[3],
                "remote_geo": row[4],
                "canada_eligible": row[5],
                "seniority": row[6],
                "role_family": row[7],
                "years_exp_min": row[8],
                "years_exp_max": row[9],
                "minimum_degree": row[10],
                "required_skills": row[11],
                "preferred_skills": row[12],
                "formatted_description": row[13],
                "salary_min": row[14],
                "salary_max": row[15],
                "salary_currency": row[16],
                "visa_sponsorship": row[17],
                "red_flags": row[18],
                "enriched_at": row[19],
                "enrichment_status": row[20],
                "enrichment_model": row[21],
            }
        )
        match = compute_match_score({"title": row[2], "enrichment": enrichment}, profile)
        source_hash = _hash_score_source(title=row[2], enrichment=enrichment, profile_version=profile_version)
        _upsert_match_row(
            conn,
            job_id=str(row[0] or ""),
            url=row[1],
            profile_version=profile_version,
            match=match,
            source_hash=source_hash,
        )
        count += 1
        if progress_callback is not None and (count == total or count % 50 == 0):
            progress_callback(count, total)
    conn.commit()
    return count


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
    alerts = _analytics_alerts(conn, reference_at=datetime.now(timezone.utc))
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
        LEFT JOIN job_tracking t ON t.job_id = j.id
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


def _analytics_alerts(conn: Any, *, reference_at: datetime) -> dict[str, int]:
    reference_iso = reference_at.isoformat()
    staging_overdue_48h = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM jobs j
            LEFT JOIN job_tracking t ON t.job_id = j.id
            WHERE {_normalized_status_sql('t.status', 'j.application_status')} = 'staging'
              AND datetime(COALESCE(t.staging_entered_at, t.updated_at, j.last_seen, j.posted)) <= datetime(?, '-48 hour')
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
            LEFT JOIN job_tracking t ON t.job_id = j.id
            LEFT JOIN (
              SELECT job_id, MAX(event_at) AS latest_event_at
              FROM job_events
              GROUP BY job_id
            ) ev ON ev.job_id = j.id
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
            LEFT JOIN job_tracking t ON t.job_id = j.id
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
        "staging_overdue_48h": staging_overdue_48h,
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
        LEFT JOIN job_tracking t ON t.job_id = j.id
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
        LEFT JOIN job_tracking t ON t.job_id = j.id
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
