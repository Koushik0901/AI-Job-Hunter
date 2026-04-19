from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ai_job_hunter.dashboard.backend.advisor import (
    build_recommendation,
    clamp,
    overlap_skills,
)
from ai_job_hunter.db import (
    bump_candidate_profile_score_version,
    clear_job_processing_state,
    get_candidate_profile,
    get_job_processing_state,
    save_jobs,
    suppress_job_id,
    unsuppress_job_id,
    upsert_job_processing_state,
    upsert_candidate_profile,
)
from ai_job_hunter.dashboard.backend.utils import now_iso as _now_iso, local_today as _local_today
from ai_job_hunter.match_score import calibrate_match_scores, compute_match_score


def _parse_iso_datetime(raw: Any) -> datetime | None:
    if raw is None:
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
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _plus_hours_iso(raw_iso: str, hours: int) -> str:
    parsed = _parse_iso_datetime(raw_iso) or datetime.now(timezone.utc)
    return (parsed + timedelta(hours=hours)).isoformat()


def _parse_json_array(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


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


_POSITIVE_OUTCOME_TYPES = {
    "recruiter_reply",
    "hiring_manager_screen",
    "technical_interview",
    "onsite",
    "offer",
}
_INTERVIEW_OUTCOME_TYPES = {
    "hiring_manager_screen",
    "technical_interview",
    "onsite",
    "offer",
}
_NEGATIVE_OUTCOME_TYPES = {
    "resume_rejected",
    "rejection",
    "closed_no_response",
    "withdrawn",
}
_ACTIONABLE_RECOMMENDATIONS = {"apply_now", "review_manually"}
_PROCESSING_STATES = {"ready", "processing", "failed"}


def _parse_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _processing_state_payload(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = raw or {}
    state = str(payload.get("state") or "ready").strip().lower()
    if state not in _PROCESSING_STATES:
        state = "ready"
    step = str(payload.get("step") or "complete").strip() or "complete"
    message = str(payload.get("message") or "Job is ready.").strip() or "Job is ready."
    return {
        "state": state,
        "step": step,
        "message": message,
        "last_processed_at": str(payload.get("last_processed_at") or "") or None,
        "last_error": str(payload.get("last_error") or "") or None,
        "retry_count": int(payload.get("retry_count") or 0),
    }


def _role_family_label(title: str, enrichment: dict[str, Any] | None = None) -> str:
    if enrichment:
        family = str(enrichment.get("role_family") or "").strip().lower()
        if family:
            return family
    lowered = title.strip().lower()
    if not lowered:
        return "unknown"
    tokens = lowered.split()
    return " ".join(tokens[:2]) if len(tokens) >= 2 else tokens[0]


def _load_manual_decisions(conn: Any) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT job_id, recommendation_override, note, updated_at
        FROM job_decisions
        """
    ).fetchall()
    return {
        str(row[0] or ""): {
            "recommendation": str(row[1] or ""),
            "note": row[2],
            "updated_at": str(row[3] or ""),
        }
        for row in rows
        if row and row[0]
    }


def _load_source_quality_maps(conn: Any) -> tuple[dict[str, int], dict[str, int]]:
    rows = conn.execute(
        """
        SELECT
            j.id,
            COALESCE(j.ats, ''),
            COALESCE(e.role_family, COALESCE(j.title, '')),
            EXISTS(SELECT 1 FROM job_events ev WHERE ev.job_id = j.id AND ev.event_type = 'application_submitted'),
            COALESCE(o.outcome_type, '')
        FROM jobs j
        LEFT JOIN job_enrichments e ON e.job_id = j.id
        LEFT JOIN job_outcomes o ON o.job_id = j.id
        WHERE j.id IS NOT NULL AND trim(j.id) != ''
        """
    ).fetchall()
    ats_accumulator: dict[str, dict[str, int]] = {}
    role_accumulator: dict[str, dict[str, int]] = {}
    for row in rows:
        ats = str(row[1] or "").strip().lower() or "unknown"
        role_family = _role_family_label(str(row[2] or ""))
        applied = 1 if int(row[3] or 0) else 0
        outcome_type = str(row[4] or "").strip().lower()
        positive = 1 if outcome_type in _POSITIVE_OUTCOME_TYPES else 0
        negative = 1 if outcome_type in _NEGATIVE_OUTCOME_TYPES else 0
        for target, key in ((ats_accumulator, ats), (role_accumulator, role_family)):
            bucket = target.setdefault(
                key, {"applied": 0, "positive": 0, "negative": 0}
            )
            bucket["applied"] += applied
            bucket["positive"] += positive
            bucket["negative"] += negative

    def _quality_map(source: dict[str, dict[str, int]]) -> dict[str, int]:
        result: dict[str, int] = {}
        for key, bucket in source.items():
            applied = bucket["applied"]
            if applied <= 0:
                result[key] = 50
                continue
            positive_rate = bucket["positive"] / applied
            negative_rate = bucket["negative"] / applied
            result[key] = clamp(50 + (positive_rate * 35) - (negative_rate * 25))
        return result

    return _quality_map(ats_accumulator), _quality_map(role_accumulator)


def _latest_application_state(conn: Any, job_id: str) -> tuple[str, str | None]:
    follow_up_row = conn.execute(
        """
        SELECT due_at
        FROM job_actions
        WHERE job_id = ? AND action_type = 'follow_up' AND status IN ('pending', 'deferred')
        ORDER BY datetime(due_at) ASC, id ASC
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    event_row = conn.execute(
        """
        SELECT event_type
        FROM job_events
        WHERE job_id = ?
        ORDER BY datetime(event_at) DESC, id DESC
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    event_type = str(event_row[0] or "").strip().lower() if event_row else ""
    if event_type == "offer":
        return "offer", str(follow_up_row[0]) if follow_up_row else None
    if event_type in {
        "technical_interview",
        "onsite",
        "hiring_manager_screen",
        "recruiter_reply",
        "recruiter_screen",
    }:
        return "in_process", str(follow_up_row[0]) if follow_up_row else None
    if event_type in _NEGATIVE_OUTCOME_TYPES:
        return "closed", str(follow_up_row[0]) if follow_up_row else None
    if event_type == "application_submitted":
        return "submitted", str(follow_up_row[0]) if follow_up_row else None
    return "not_started", str(follow_up_row[0]) if follow_up_row else None


def _attach_recommendation(
    conn: Any,
    *,
    profile: dict[str, Any],
    item: dict[str, Any],
    decisions: dict[str, dict[str, Any]],
    source_quality_map: dict[str, int],
    role_quality_map: dict[str, int],
) -> dict[str, Any]:
    job_id = str(item.get("id") or "")
    enrichment = (
        item.get("enrichment") if isinstance(item.get("enrichment"), dict) else {}
    )
    decision = decisions.get(job_id, {})
    metrics = build_recommendation(
        profile=profile,
        job=item,
        source_quality_score=source_quality_map.get(
            str(item.get("ats") or "").strip().lower() or "unknown", 50
        ),
        role_quality_score=role_quality_map.get(
            _role_family_label(str(item.get("title") or ""), enrichment), 50
        ),
        override=str(decision.get("recommendation") or "").strip() or None,
        override_note=str(decision.get("note") or "").strip() or None,
    )
    item.update(metrics)
    return item


def _json_text(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)


def _hash_score_source(
    *, title: str, enrichment: dict[str, Any], profile_version: int
) -> str:
    payload = {
        "title": title,
        "enrichment": enrichment,
        "profile_version": profile_version,
    }
    return hashlib.sha1(_json_text(payload).encode("utf-8")).hexdigest()


def _parse_match_row(row: tuple[Any, ...]) -> dict[str, Any]:
    breakdown: dict[str, int] = {}
    reasons: list[str] = []
    try:
        parsed_breakdown = json.loads(str(row[4] or "{}"))
        if isinstance(parsed_breakdown, dict):
            breakdown = {
                str(key): int(value) for key, value in parsed_breakdown.items()
            }
    except Exception:
        breakdown = {}
    try:
        parsed_reasons = json.loads(str(row[5] or "[]"))
        if isinstance(parsed_reasons, list):
            reasons = [str(value) for value in parsed_reasons]
    except Exception:
        reasons = []
    return {
        "profile_version": int(row[0]),
        "score": int(row[1]),
        "raw_score": int(row[2] or 0),
        "band": str(row[3]),
        "breakdown": breakdown,
        "reasons": reasons,
        "confidence": str(row[6] or "low"),
        "computed_at": row[7],
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
        "NOT EXISTS ("
        "SELECT 1 FROM job_suppressions js "
        f"WHERE js.active = 1 AND (js.job_id = {job_alias}.id OR ((js.job_id IS NULL OR trim(js.job_id) = '') AND js.url = {job_alias}.url))"
        ")"
    )


def _staging_sla_fields(
    status: str, staging_entered_at: Any, staging_due_at: Any
) -> dict[str, Any]:
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


def _upsert_match_row(
    conn: Any,
    *,
    job_id: str,
    url: str,
    profile_version: int,
    match: dict[str, Any],
    source_hash: str,
    semantic_score: float | None = None,
    matched_story_ids: list[int] | None = None,
    matched_story_titles: list[str] | None = None,
) -> str:
    computed_at = _now_iso()
    conn.execute(
        """
        INSERT OR REPLACE INTO job_match_scores
        (job_id, url, profile_version, score, raw_score, band, breakdown_json, reasons_json,
         confidence, computed_at, source_hash, semantic_score, matched_story_ids, matched_story_titles)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            url,
            profile_version,
            int(match.get("score", 0) or 0),
            int(match.get("raw_score", match.get("score", 0)) or 0),
            str(match.get("band") or "low"),
            _json_text(match.get("breakdown") or {}),
            _json_text(match.get("reasons") or []),
            str(match.get("confidence") or "low"),
            computed_at,
            source_hash,
            semantic_score,
            json.dumps(matched_story_ids or []),
            json.dumps(matched_story_titles or []),
        ),
    )
    return computed_at


def get_job_id_by_url(conn: Any, url: str) -> str | None:
    row = conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
    if not row or not row[0]:
        return None
    return str(row[0])


def get_job_url_by_id(conn: Any, job_id: str) -> str | None:
    row = conn.execute("SELECT url FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row or not row[0]:
        return None
    return str(row[0])


def _is_job_suppressed(conn: Any, job_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM job_suppressions WHERE job_id = ? AND active = 1 LIMIT 1",
        (job_id,),
    ).fetchone()
    return row is not None


def _normalize_duplicate_text(raw: Any) -> str:
    text = unicodedata.normalize("NFKC", str(raw or "")).strip().casefold()
    text = re.sub(r"[\u200B-\u200D\uFEFF]", "", text)
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return " ".join(text.split())


def _duplicate_posted_month(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if re.match(r"^\d{4}-\d{2}", text):
        return text[:7]
    parsed = _parse_iso_datetime(text)
    if parsed is not None:
        return parsed.strftime("%Y-%m")
    try:
        parsed_date = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=timezone.utc)
    return parsed_date.astimezone(timezone.utc).strftime("%Y-%m")


def _find_manual_job_duplicate(
    conn: Any,
    *,
    title: str,
    company: str,
    location: str,
    posted: str,
) -> dict[str, Any] | None:
    title_key = _normalize_duplicate_text(title)
    company_key = _normalize_duplicate_text(company)
    location_key = _normalize_duplicate_text(location)
    posted_month = _duplicate_posted_month(posted)
    if not title_key or not company_key or not location_key or not posted_month:
        return None

    rows = conn.execute(
        """
        SELECT id, url, title, company, location, posted
        FROM jobs
        WHERE COALESCE(title, '') != '' AND COALESCE(company, '') != '' AND COALESCE(posted, '') != ''
        """
    ).fetchall()
    for row in rows:
        candidate_title = _normalize_duplicate_text(row[2])
        candidate_company = _normalize_duplicate_text(row[3])
        candidate_location = _normalize_duplicate_text(row[4])
        candidate_month = _duplicate_posted_month(row[5])
        if candidate_title != title_key:
            continue
        if candidate_company != company_key:
            continue
        if candidate_location != location_key:
            continue
        if candidate_month != posted_month:
            continue
        return {
            "id": str(row[0] or ""),
            "url": str(row[1] or ""),
            "match_kind": "content",
        }
    return None


def _list_jobs_live(
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
    _allow_recompute: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = [_not_suppressed_sql("j")]
    params: list[Any] = []

    if status:
        where.append(
            f"{_normalized_status_sql('t.status', 'j.application_status')} = ?"
        )
        params.append(status)
    if q:
        qv = f"%{q}%"
        where.append("(j.title LIKE ? OR j.company LIKE ? OR j.location LIKE ?)")
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

    where_sql = "WHERE " + " AND ".join(where)
    profile = get_candidate_profile(conn)
    decisions = _load_manual_decisions(conn)
    source_quality_map, role_quality_map = _load_source_quality_maps(conn)
    profile_version = int(profile.get("score_version") or 1)

    order_sql = "ORDER BY date(j.posted) DESC"
    if sort == "updated_desc":
        order_sql = "ORDER BY COALESCE(t.updated_at, j.last_seen) DESC"
    elif sort == "company_asc":
        order_sql = "ORDER BY j.company ASC, j.title ASC"
    elif sort == "match_desc":
        order_sql = "ORDER BY COALESCE(ms.score, -1) DESC, date(j.posted) DESC"

    total_row = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
        {where_sql}
        """,
        tuple(params),
    ).fetchone()
    total = int(total_row[0]) if total_row else 0

    query = f"""
        SELECT
            j.url,
            COALESCE(j.company, ''),
            COALESCE(j.title, ''),
            COALESCE(j.location, ''),
            COALESCE(j.posted, ''),
            COALESCE(j.ats, ''),
            {_normalized_status_sql("t.status", "j.application_status")},
            COALESCE(t.priority, 'medium'),
            COALESCE(t.pinned, 0),
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
            ms.raw_score,
            ms.band,
            ms.breakdown_json,
            j.id,
            t.processing_state,
            t.processing_step,
            t.processing_message,
            t.processing_last_at,
            t.processing_last_error,
            t.processing_retry_count,
            ms.semantic_score,
            ms.matched_story_ids,
            ms.matched_story_titles
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
        LEFT JOIN job_enrichments e ON e.job_id = j.id
        LEFT JOIN job_match_scores ms ON ms.job_id = j.id AND ms.profile_version = ?
        {where_sql}
        {order_sql}
    """
    query_params: list[Any] = [profile_version, *params]
    if sort != "match_desc":
        query += "\nLIMIT ? OFFSET ?"
        query_params.extend([limit, offset])

    rows = conn.execute(query, tuple(query_params)).fetchall()
    items: list[dict[str, Any]] = []
    missing_job_ids: list[str] = []
    for row in rows:
        score = row[31]
        raw_score = row[32]
        band = row[33]
        desired_title_match = (
            _match_breakdown_value(row[34], "desired_title_alignment") > 0
        )
        enrichment = _build_enrichment_payload(
            {
                "work_mode": row[12],
                "remote_geo": row[13],
                "canada_eligible": row[14],
                "seniority": row[15],
                "role_family": row[16],
                "years_exp_min": row[17],
                "years_exp_max": row[18],
                "minimum_degree": row[19],
                "required_skills": row[20],
                "preferred_skills": row[21],
                "formatted_description": row[22],
                "salary_min": row[23],
                "salary_max": row[24],
                "salary_currency": row[25],
                "visa_sponsorship": row[26],
                "red_flags": row[27],
                "enriched_at": row[28],
                "enrichment_status": row[29],
                "enrichment_model": row[30],
            }
        )
        if score is None:
            missing_job_ids.append(str(row[35] or ""))
        staging = _staging_sla_fields(str(row[6] or ""), row[10], row[11])

        # Parse semantic fields (rows 42-44)
        semantic_score_val = row[42] if len(row) > 42 else None
        matched_ids_raw = row[43] if len(row) > 43 else None
        matched_titles_raw = row[44] if len(row) > 44 else None
        try:
            matched_story_ids = json.loads(matched_ids_raw) if matched_ids_raw else []
        except Exception:
            matched_story_ids = []
        try:
            matched_story_titles = json.loads(matched_titles_raw) if matched_titles_raw else []
        except Exception:
            matched_story_titles = []

        items.append(
            {
                "id": str(row[35] or ""),
                "url": str(row[0] or ""),
                "company": str(row[1] or ""),
                "title": str(row[2] or ""),
                "location": str(row[3] or ""),
                "posted": str(row[4] or ""),
                "ats": str(row[5] or ""),
                "status": str(row[6] or "not_applied"),
                "priority": str(row[7] or "medium"),
                "pinned": bool(row[8]),
                "updated_at": row[9],
                "match_score": int(score) if isinstance(score, int) else None,
                "raw_score": int(raw_score) if isinstance(raw_score, int) else None,
                "match_band": str(band) if band is not None else None,
                "desired_title_match": desired_title_match,
                "processing": _processing_state_payload(
                    {
                        "state": row[36],
                        "step": row[37],
                        "message": row[38],
                        "last_processed_at": row[39],
                        "last_error": row[40],
                        "retry_count": row[41],
                    }
                ),
                "staging_entered_at": staging["staging_entered_at"],
                "staging_due_at": staging["staging_due_at"],
                "staging_overdue": bool(staging["staging_overdue"]),
                "staging_age_hours": staging["staging_age_hours"],
                "semantic_score": float(semantic_score_val) if semantic_score_val is not None else None,
                "matched_story_ids": matched_story_ids,
                "matched_story_titles": matched_story_titles,
                "enrichment": enrichment,
            }
        )

    if missing_job_ids and _allow_recompute:
        recompute_match_scores(conn)
        return _list_jobs_live(
            conn,
            status=status,
            q=q,
            ats=ats,
            company=company,
            posted_after=posted_after,
            posted_before=posted_before,
            sort=sort,
            limit=limit,
            offset=offset,
            _allow_recompute=False,
        )

    if sort == "match_desc":
        items.sort(
            key=lambda item: (
                int(item.get("match_score") or -1),
                str(item.get("posted") or ""),
            ),
            reverse=True,
        )
        items = items[offset : offset + limit]

    for item in items:
        _attach_recommendation(
            conn,
            profile=profile,
            item=item,
            decisions=decisions,
            source_quality_map=source_quality_map,
            role_quality_map=role_quality_map,
        )
        item["required_skills"] = (item.get("enrichment") or {}).get(
            "required_skills", []
        )[:5]
        item.pop("enrichment", None)

    return items, total


def _snapshot_row_to_item(row: tuple[Any, ...]) -> dict[str, Any]:
    payload = {}
    try:
        payload = json.loads(row[16] or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return payload


def _snapshot_matches_filters(
    item: dict[str, Any],
    *,
    status: str | None,
    q: str | None,
    ats: str | None,
    company: str | None,
    posted_after: str | None,
    posted_before: str | None,
) -> bool:
    if status and str(item.get("status") or "not_applied") != status:
        return False
    if ats and str(item.get("ats") or "") != ats:
        return False
    if company:
        if company.casefold() not in str(item.get("company") or "").casefold():
            return False
    if q:
        haystack = " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("company") or ""),
                str(item.get("location") or ""),
            ]
        ).casefold()
        if q.casefold() not in haystack:
            return False
    posted = str(item.get("posted") or "")
    if posted_after and (not posted or posted < posted_after):
        return False
    if posted_before and (not posted or posted > posted_before):
        return False
    return True


def _snapshot_sort_key(item: dict[str, Any], sort: str) -> tuple[Any, ...]:
    if sort == "updated_desc":
        return (str(item.get("updated_at") or ""), str(item.get("posted") or ""))
    if sort == "company_asc":
        return (
            str(item.get("company") or "").casefold(),
            str(item.get("title") or "").casefold(),
        )
    if sort == "posted_desc":
        return (str(item.get("posted") or ""), str(item.get("updated_at") or ""))
    return (
        int(item.get("match_score") or -1),
        str(item.get("posted") or ""),
        str(item.get("updated_at") or ""),
    )


def refresh_dashboard_snapshots(
    conn: Any, *, job_ids: list[str] | None = None, profile_version: int | None = None
) -> int:
    profile = get_candidate_profile(conn)
    version = int(profile_version or profile.get("score_version") or 1)
    recompute_match_scores(
        conn,
        urls=None if not job_ids else [get_job_url_by_id(conn, job_id) for job_id in job_ids if get_job_url_by_id(conn, job_id)],
    )
    live_items, _ = _list_jobs_live(
        conn,
        status=None,
        q=None,
        ats=None,
        company=None,
        posted_after=None,
        posted_before=None,
        sort="match_desc",
        limit=100000,
        offset=0,
        _allow_recompute=False,
    )
    selected_ids = {str(job_id) for job_id in job_ids or [] if str(job_id).strip()}
    now = _now_iso()
    refreshed = 0
    if selected_ids:
        conn.execute(
            """
            DELETE FROM job_dashboard_snapshots
            WHERE profile_version = ?
              AND job_id IN ({placeholders})
            """.format(placeholders=",".join("?" for _ in selected_ids)),
            (version, *selected_ids),
        )
    else:
        conn.execute(
            "DELETE FROM job_dashboard_snapshots WHERE profile_version = ?", (version,)
        )
    for item in live_items:
        job_id = str(item.get("id") or "")
        if not job_id:
            continue
        if selected_ids and job_id not in selected_ids:
            continue
        conn.execute(
            """
            INSERT OR REPLACE INTO job_dashboard_snapshots (
                job_id,
                profile_version,
                url,
                company,
                title,
                location,
                posted,
                ats,
                status,
                priority,
                pinned,
                updated_at,
                match_score,
                raw_score,
                match_band,
                desired_title_match,
                snapshot_updated_at,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                version,
                str(item.get("url") or ""),
                str(item.get("company") or ""),
                str(item.get("title") or ""),
                str(item.get("location") or ""),
                str(item.get("posted") or ""),
                str(item.get("ats") or ""),
                str(item.get("status") or "not_applied"),
                str(item.get("priority") or "medium"),
                1 if bool(item.get("pinned")) else 0,
                item.get("updated_at"),
                item.get("match_score"),
                item.get("raw_score"),
                item.get("match_band"),
                1 if bool(item.get("desired_title_match")) else 0,
                now,
                json.dumps(item, ensure_ascii=True, separators=(",", ":")),
            ),
        )
        refreshed += 1
    conn.commit()
    return refreshed


def _load_snapshot_items(
    conn: Any, *, profile_version: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            job_id,
            url,
            company,
            title,
            location,
            posted,
            ats,
            status,
            priority,
            pinned,
            updated_at,
            match_score,
            raw_score,
            match_band,
            desired_title_match,
            snapshot_updated_at,
            payload_json
        FROM job_dashboard_snapshots
        WHERE profile_version = ?
        """,
        (profile_version,),
    ).fetchall()
    return [_snapshot_row_to_item(row) for row in rows]


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
    _allow_recompute: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    profile = get_candidate_profile(conn)
    profile_version = int(profile.get("score_version") or 1)
    snapshot_items = _load_snapshot_items(conn, profile_version=profile_version)
    if not snapshot_items:
        refresh_dashboard_snapshots(conn, profile_version=profile_version)
        snapshot_items = _load_snapshot_items(conn, profile_version=profile_version)
    if not snapshot_items:
        return _list_jobs_live(
            conn,
            status=status,
            q=q,
            ats=ats,
            company=company,
            posted_after=posted_after,
            posted_before=posted_before,
            sort=sort,
            limit=limit,
            offset=offset,
            _allow_recompute=_allow_recompute,
        )

    filtered = [
        item
        for item in snapshot_items
        if _snapshot_matches_filters(
            item,
            status=status,
            q=q.strip() if q else None,
            ats=ats.strip() if ats else None,
            company=company.strip() if company else None,
            posted_after=posted_after,
            posted_before=posted_before,
        )
    ]
    reverse = sort != "company_asc"
    filtered.sort(key=lambda item: _snapshot_sort_key(item, sort), reverse=reverse)
    total = len(filtered)
    return filtered[offset : offset + limit], total


def _get_job_detail_where(
    conn: Any, where_sql: str, value: str, *, _allow_recompute: bool = True
) -> dict[str, Any] | None:
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
            {_normalized_status_sql("t.status", "j.application_status")},
            COALESCE(t.priority, 'medium'),
            COALESCE(t.pinned, 0),
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
            j.id,
            t.processing_state,
            t.processing_step,
            t.processing_message,
            t.processing_last_at,
            t.processing_last_error,
            t.processing_retry_count
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
    if any(column is not None for column in row[19:38]):
        enrichment = _build_enrichment_payload(
            {
                "work_mode": row[19],
                "remote_geo": row[20],
                "canada_eligible": row[21],
                "seniority": row[22],
                "role_family": row[23],
                "years_exp_min": row[24],
                "years_exp_max": row[25],
                "minimum_degree": row[26],
                "required_skills": row[27],
                "preferred_skills": row[28],
                "formatted_description": row[29],
                "salary_min": row[30],
                "salary_max": row[31],
                "salary_currency": row[32],
                "visa_sponsorship": row[33],
                "red_flags": row[34],
                "enriched_at": row[35],
                "enrichment_status": row[36],
                "enrichment_model": row[37],
            }
        )

    profile = get_candidate_profile(conn)
    profile_version = int(profile.get("score_version") or 1)
    score_row = conn.execute(
        """
        SELECT profile_version, score, raw_score, band, breakdown_json, reasons_json, confidence, computed_at
        FROM job_match_scores
        WHERE job_id = ?
        ORDER BY (profile_version = ?) DESC, profile_version DESC
        LIMIT 1
        """,
        (str(row[38] or ""), profile_version),
    ).fetchone()

    match = None
    stale = True
    computed_at = None
    if score_row:
        parsed = _parse_match_row(score_row)
        match = {
            "score": parsed["score"],
            "raw_score": parsed["raw_score"],
            "band": parsed["band"],
            "breakdown": parsed["breakdown"],
            "reasons": parsed["reasons"],
            "confidence": parsed["confidence"],
        }
        stale = int(parsed["profile_version"]) != profile_version
        computed_at = parsed["computed_at"]
    staging = _staging_sla_fields(str(row[10] or ""), row[17], row[18])
    desired_title_match = (
        _match_breakdown_value(
            match.get("breakdown") if isinstance(match, dict) else {},
            "desired_title_alignment",
        )
        > 0
    )
    item = {
        "id": str(row[38] or ""),
        "url": str(row[0] or ""),
        "company": str(row[1] or ""),
        "title": str(row[2] or ""),
        "location": str(row[3] or ""),
        "posted": str(row[4] or ""),
        "ats": str(row[5] or ""),
        "description": str(row[6] or ""),
        "first_seen": str(row[7] or ""),
        "last_seen": str(row[8] or ""),
        "application_status": row[9],
        "tracking_status": str(row[10] or "not_applied"),
        "priority": str(row[11] or "medium"),
        "pinned": bool(row[12]),
        "applied_at": row[13],
        "next_step": row[14],
        "target_compensation": row[15],
        "tracking_updated_at": row[16],
        "staging_entered_at": staging["staging_entered_at"],
        "staging_due_at": staging["staging_due_at"],
        "staging_overdue": bool(staging["staging_overdue"]),
        "staging_age_hours": staging["staging_age_hours"],
        "enrichment": enrichment,
        "match": match,
        "match_score": match.get("score") if isinstance(match, dict) else None,
        "raw_score": match.get("raw_score") if isinstance(match, dict) else None,
        "match_band": match.get("band") if isinstance(match, dict) else None,
        "desired_title_match": desired_title_match,
        "match_meta": {
            "profile_version": profile_version,
            "computed_at": computed_at,
            "stale": stale,
        },
        "processing": _processing_state_payload(
            {
                "state": row[39],
                "step": row[40],
                "message": row[41],
                "last_processed_at": row[42],
                "last_error": row[43],
                "retry_count": row[44],
            }
        ),
    }
    decisions = _load_manual_decisions(conn)
    source_quality_map, role_quality_map = _load_source_quality_maps(conn)
    return _attach_recommendation(
        conn,
        profile=profile,
        item=item,
        decisions=decisions,
        source_quality_map=source_quality_map,
        role_quality_map=role_quality_map,
    )


def get_job_detail(conn: Any, job_id: str) -> dict[str, Any] | None:
    return _get_job_detail_where(conn, "j.id = ?", job_id)


def upsert_tracking(conn: Any, job_id: str, patch: dict[str, Any]) -> None:
    job_url = get_job_url_by_id(conn, job_id)
    if not job_url:
        raise ValueError("job not found")

    existing = conn.execute(
        """
        SELECT status, priority, pinned, applied_at, next_step, target_compensation, staging_entered_at, staging_due_at
        FROM job_tracking
        WHERE job_id = ?
        """,
        (job_id,),
    ).fetchone()

    now = _now_iso()
    if existing:
        previous_status = str(existing[0] or "not_applied")
        status = str(patch.get("status", previous_status) or previous_status)
        priority = patch.get("priority", existing[1])
        pinned = int(bool(patch.get("pinned", bool(existing[2]))))
        applied_at = patch.get("applied_at", existing[3])
        next_step = patch.get("next_step", existing[4])
        target_compensation = patch.get("target_compensation", existing[5])
        staging_entered_at = existing[6]
        staging_due_at = existing[7]
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
            SET url = ?, status = ?, priority = ?, pinned = ?, applied_at = ?, next_step = ?, target_compensation = ?, staging_entered_at = ?, staging_due_at = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (
                job_url,
                status,
                priority,
                pinned,
                applied_at,
                next_step,
                target_compensation,
                staging_entered_at,
                staging_due_at,
                now,
                job_id,
            ),
        )
    else:
        status = str(patch.get("status", "not_applied") or "not_applied")
        priority = patch.get("priority", "medium")
        pinned = int(bool(patch.get("pinned", False)))
        applied_at = patch.get("applied_at")
        next_step = patch.get("next_step")
        target_compensation = patch.get("target_compensation")
        staging_entered_at = now if status == "staging" else None
        staging_due_at = _plus_hours_iso(now, 48) if status == "staging" else None
        conn.execute(
            """
            INSERT INTO job_tracking (job_id, url, status, priority, pinned, applied_at, next_step, target_compensation, staging_entered_at, staging_due_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                job_url,
                status,
                priority,
                pinned,
                applied_at,
                next_step,
                target_compensation,
                staging_entered_at,
                staging_due_at,
                now,
            ),
        )

    conn.execute(
        "UPDATE jobs SET application_status = ? WHERE id = ?", (status, job_id)
    )
    conn.commit()


def create_manual_job(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    if not url:
        raise ValueError("url is required")
    existing_job_id = get_job_id_by_url(conn, url)
    if existing_job_id:
        if _is_job_suppressed(conn, existing_job_id):
            raise ValueError("This job URL is suppressed. Unsuppress it before adding.")
        detail = get_job_detail(conn, existing_job_id)
        if not detail:
            raise RuntimeError("Failed to load existing job duplicate")
        detail["duplicate_detected"] = True
        detail["duplicate_of_job_id"] = existing_job_id
        detail["duplicate_match_kind"] = "url"
        return detail

    title = str(payload.get("title") or "").strip()
    company = str(payload.get("company") or "").strip()
    location = str(payload.get("location") or "").strip()
    posted = str(
        payload.get("posted") or datetime.now(timezone.utc).date().isoformat()
    ).strip()
    duplicate = _find_manual_job_duplicate(
        conn,
        title=title,
        company=company,
        location=location,
        posted=posted,
    )
    if duplicate:
        if _is_job_suppressed(conn, duplicate["id"]):
            raise ValueError(
                "A matching job is suppressed. Unsuppress it before adding."
            )
        detail = get_job_detail(conn, duplicate["id"])
        if not detail:
            raise RuntimeError("Failed to load existing job duplicate")
        detail["duplicate_detected"] = True
        detail["duplicate_of_job_id"] = duplicate["id"]
        detail["duplicate_match_kind"] = duplicate["match_kind"]
        return detail

    job = {
        "url": url,
        "company": company,
        "title": title,
        "location": location,
        "posted": posted,
        "ats": str(payload.get("ats") or "manual").strip(),
        "description": str(payload.get("description") or "").strip(),
        "source": "manual",
    }
    save_jobs(conn, [job])
    job_id = get_job_id_by_url(conn, url)
    if not job_id:
        raise RuntimeError("Failed to resolve manual job id")

    status = str(payload.get("status") or "not_applied").strip().lower()
    allowed_statuses = {
        "not_applied",
        "staging",
        "applied",
        "interviewing",
        "offer",
        "rejected",
    }
    if status not in allowed_statuses:
        raise ValueError(
            "status must be one of: not_applied, staging, applied, interviewing, offer, rejected"
        )
    upsert_tracking(conn, job_id, {"status": status})
    upsert_job_processing_state(
        conn,
        job_id,
        state="processing",
        step="queued",
        message="Queued for background processing.",
    )

    detail = get_manual_job_stub(conn, job_id)
    if not detail:
        raise RuntimeError("Failed to save manual job")
    return detail


def get_manual_job_stub(conn: Any, job_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            j.id,
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
            COALESCE(t.status, COALESCE(j.application_status, 'not_applied')),
            COALESCE(t.priority, 'medium'),
            t.applied_at,
            t.next_step,
            t.target_compensation,
            t.updated_at,
            t.staging_entered_at,
            t.staging_due_at,
            t.processing_state,
            t.processing_step,
            t.processing_message,
            t.processing_last_at,
            t.processing_last_error,
            t.processing_retry_count
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
        WHERE j.id = ?
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    if not row:
        return None

    staging = _staging_sla_fields(str(row[11] or "not_applied"), row[17], row[18])

    return {
        "id": str(row[0] or ""),
        "url": str(row[1] or ""),
        "company": str(row[2] or ""),
        "title": str(row[3] or ""),
        "location": str(row[4] or ""),
        "posted": str(row[5] or ""),
        "ats": str(row[6] or ""),
        "description": str(row[7] or ""),
        "first_seen": str(row[8] or ""),
        "last_seen": str(row[9] or ""),
        "application_status": str(row[10] or "") or None,
        "tracking_status": str(row[11] or "not_applied"),
        "priority": str(row[12] or "medium"),
        "applied_at": str(row[13] or "") or None,
        "next_step": str(row[14] or "") or None,
        "target_compensation": str(row[15] or "") or None,
        "tracking_updated_at": str(row[16] or "") or None,
        "staging_entered_at": staging["staging_entered_at"],
        "staging_due_at": staging["staging_due_at"],
        "staging_overdue": staging["staging_overdue"],
        "staging_age_hours": staging["staging_age_hours"],
        "processing": _processing_state_payload(
            {
                "state": row[19],
                "step": row[20],
                "message": row[21],
                "last_processed_at": row[22],
                "last_error": row[23],
                "retry_count": row[24],
            }
        ),
        "enrichment": None,
        "match": None,
        "match_meta": None,
        "desired_title_match": False,
        "fit_score": None,
        "interview_likelihood_score": None,
        "urgency_score": None,
        "friction_score": None,
        "confidence_score": None,
        "recommendation": None,
        "recommendation_reasons": [],
        "duplicate_detected": False,
        "duplicate_of_job_id": None,
        "duplicate_match_kind": None,
    }


def get_job_processing(conn: Any, job_id: str) -> dict[str, Any]:
    return _processing_state_payload(get_job_processing_state(conn, job_id))


def set_job_processing(
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
    return _processing_state_payload(
        upsert_job_processing_state(
            conn,
            job_id,
            state=state,
            step=step,
            message=message,
            last_processed_at=last_processed_at,
            last_error=last_error,
            increment_retry=increment_retry,
        )
    )


def suppress_job(
    conn: Any, *, job_id: str, reason: str | None, created_by: str = "ui"
) -> None:
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
            "id": int(row[0]),
            "job_id": str(row[1] or ""),
            "url": str(row[2] or ""),
            "event_type": str(row[3] or ""),
            "title": str(row[4] or ""),
            "body": row[5],
            "event_at": str(row[6] or ""),
            "created_at": str(row[7] or ""),
        }
        for row in rows
    ]


def create_event(conn: Any, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    job_url = get_job_url_by_id(conn, job_id)
    if not job_url:
        raise ValueError("job not found")
    created_at = _now_iso()
    conn.execute(
        """
        INSERT INTO job_events (job_id, url, event_type, title, body, event_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            job_url,
            payload["event_type"],
            payload["title"],
            payload.get("body"),
            payload["event_at"],
            created_at,
        ),
    )
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    _sync_outcome_for_event(
        conn,
        job_id=job_id,
        event_type=str(payload["event_type"]),
        body=payload.get("body"),
    )
    if str(payload["event_type"] or "").strip().lower() == "application_submitted":
        _ensure_follow_up_action(
            conn, job_id=job_id, submitted_at=str(payload["event_at"] or created_at)
        )
    if str(payload["event_type"] or "").strip().lower() in (
        _POSITIVE_OUTCOME_TYPES | _NEGATIVE_OUTCOME_TYPES
    ):
        _complete_pending_actions(conn, job_id=job_id, action_types={"follow_up"})
    conn.commit()
    return {
        "id": int(row[0]) if row else 0,
        "job_id": job_id,
        "url": job_url,
        "event_type": payload["event_type"],
        "title": payload["title"],
        "body": payload.get("body"),
        "event_at": payload["event_at"],
        "created_at": created_at,
    }


def get_event(conn: Any, event_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, job_id, url, event_type, title, body, event_at, created_at
        FROM job_events
        WHERE id = ?
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": int(row[0]),
        "job_id": str(row[1] or ""),
        "url": str(row[2] or ""),
        "event_type": str(row[3] or ""),
        "title": str(row[4] or ""),
        "body": row[5],
        "event_at": str(row[6] or ""),
        "created_at": str(row[7] or ""),
    }


def delete_event(conn: Any, event_id: int) -> int:
    existing = get_event(conn, event_id)
    conn.execute("DELETE FROM job_events WHERE id = ?", (event_id,))
    changed = conn.execute("SELECT changes()").fetchone()
    if existing:
        _refresh_outcome_for_job(conn, str(existing.get("job_id") or ""))
    conn.commit()
    return int(changed[0]) if changed else 0


def delete_job(conn: Any, job_id: str) -> int:
    clear_job_processing_state(conn, job_id)
    conn.execute("DELETE FROM job_events WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_tracking WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_enrichments WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_match_scores WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_decisions WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_actions WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_outcomes WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM job_suppressions WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    changed = conn.execute("SELECT changes()").fetchone()
    conn.commit()
    return int(changed[0]) if changed else 0


def save_job_decision(
    conn: Any, *, job_id: str, recommendation: str, note: str | None = None
) -> dict[str, Any]:
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO job_decisions (job_id, recommendation_override, note, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            recommendation_override = excluded.recommendation_override,
            note = excluded.note,
            updated_at = excluded.updated_at
        """,
        (job_id, recommendation, note, now),
    )
    conn.commit()
    return {
        "job_id": job_id,
        "recommendation": recommendation,
        "note": note,
        "updated_at": now,
    }


def _insert_action(
    conn: Any,
    *,
    job_id: str,
    action_type: str,
    priority: str,
    due_at: str,
    reason: str,
    source: str = "system",
    status: str = "pending",
    payload: dict[str, Any] | None = None,
) -> int:
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO job_actions (job_id, action_type, priority, due_at, reason, status, source, payload_json, created_at, updated_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            job_id,
            action_type,
            priority,
            due_at,
            reason,
            status,
            source,
            _json_text(payload or {}),
            now,
            now,
        ),
    )
    row = conn.execute("SELECT last_insert_rowid()").fetchone()
    return int(row[0]) if row else 0


def _find_existing_action(
    conn: Any, *, job_id: str, action_type: str, reason: str
) -> tuple[Any, ...] | None:
    return conn.execute(
        """
        SELECT id, status, due_at
        FROM job_actions
        WHERE job_id = ? AND action_type = ? AND reason = ? AND source = 'system'
        ORDER BY id DESC
        LIMIT 1
        """,
        (job_id, action_type, reason),
    ).fetchone()


def _upsert_system_action(
    conn: Any,
    *,
    job_id: str,
    action_type: str,
    priority: str,
    due_at: str,
    reason: str,
    payload: dict[str, Any] | None = None,
) -> None:
    existing = _find_existing_action(
        conn, job_id=job_id, action_type=action_type, reason=reason
    )
    now = _now_iso()
    if existing:
        current_status = str(existing[1] or "pending")
        current_due = str(existing[2] or due_at)
        next_due = (
            current_due
            if current_status == "deferred" and current_due > due_at
            else due_at
        )
        if current_status in {"completed", "dismissed"}:
            return
        conn.execute(
            """
            UPDATE job_actions
            SET priority = ?, due_at = ?, payload_json = ?, updated_at = ?, status = CASE WHEN status = 'deferred' THEN status ELSE 'pending' END
            WHERE id = ?
            """,
            (priority, next_due, _json_text(payload or {}), now, int(existing[0])),
        )
        return
    _insert_action(
        conn,
        job_id=job_id,
        action_type=action_type,
        priority=priority,
        due_at=due_at,
        reason=reason,
        payload=payload,
    )


def _complete_pending_actions(
    conn: Any, *, job_id: str, action_types: set[str]
) -> None:
    if not action_types:
        return
    placeholders = ", ".join("?" for _ in action_types)
    now = _now_iso()
    conn.execute(
        f"""
        UPDATE job_actions
        SET status = 'completed', completed_at = ?, updated_at = ?
        WHERE job_id = ? AND action_type IN ({placeholders}) AND status IN ('pending', 'deferred')
        """,
        (now, now, job_id, *sorted(action_types)),
    )


def _sync_outcome_for_event(
    conn: Any, *, job_id: str, event_type: str, body: Any
) -> None:
    normalized = event_type.strip().lower()
    if normalized not in (_POSITIVE_OUTCOME_TYPES | _NEGATIVE_OUTCOME_TYPES):
        return
    conn.execute(
        """
        INSERT INTO job_outcomes (job_id, outcome_type, reason_code, details_json, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            outcome_type = excluded.outcome_type,
            reason_code = excluded.reason_code,
            details_json = excluded.details_json,
            recorded_at = excluded.recorded_at
        """,
        (job_id, normalized, normalized, _json_text({"body": body}), _now_iso()),
    )


def _refresh_outcome_for_job(conn: Any, job_id: str) -> None:
    if not job_id:
        return
    outcome_types = sorted(_POSITIVE_OUTCOME_TYPES | _NEGATIVE_OUTCOME_TYPES)
    placeholders = ", ".join("?" for _ in outcome_types)
    row = conn.execute(
        f"""
        SELECT event_type, body, event_at
        FROM job_events
        WHERE job_id = ? AND event_type IN ({placeholders})
        ORDER BY datetime(event_at) DESC, id DESC
        LIMIT 1
        """,
        (job_id, *outcome_types),
    ).fetchone()
    if not row:
        conn.execute("DELETE FROM job_outcomes WHERE job_id = ?", (job_id,))
        return
    normalized = str(row[0] or "").strip().lower()
    conn.execute(
        """
        INSERT INTO job_outcomes (job_id, outcome_type, reason_code, details_json, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            outcome_type = excluded.outcome_type,
            reason_code = excluded.reason_code,
            details_json = excluded.details_json,
            recorded_at = excluded.recorded_at
        """,
        (
            job_id,
            normalized,
            normalized,
            _json_text({"body": row[1]}),
            str(row[2] or _now_iso()),
        ),
    )


def _plus_days_iso(raw_iso: str, days: int) -> str:
    parsed = _parse_iso_datetime(raw_iso) or datetime.now(timezone.utc)
    return (parsed + timedelta(days=days)).isoformat()


def _ensure_follow_up_action(conn: Any, *, job_id: str, submitted_at: str) -> None:
    _upsert_system_action(
        conn,
        job_id=job_id,
        action_type="follow_up",
        priority="high",
        due_at=_plus_days_iso(submitted_at, 7),
        reason="Follow up on submitted application.",
        payload={"submitted_at": submitted_at},
    )


def _action_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "job_id": str(row[1] or ""),
        "job_url": str(row[2] or "") if row[2] is not None else None,
        "company": str(row[3] or "") if row[3] is not None else None,
        "title": str(row[4] or "") if row[4] is not None else None,
        "action_type": str(row[5] or ""),
        "priority": str(row[6] or "medium"),
        "due_at": str(row[7] or ""),
        "reason": str(row[8] or ""),
        "status": str(row[9] or "pending"),
        "recommendation": str(row[10] or "") or None,
    }


def _pending_actions(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            a.id,
            a.job_id,
            j.url,
            j.company,
            j.title,
            a.action_type,
            a.priority,
            a.due_at,
            a.reason,
            a.status,
            d.recommendation_override
        FROM job_actions a
        INNER JOIN jobs j ON j.id = a.job_id
        LEFT JOIN job_decisions d ON d.job_id = a.job_id
        WHERE a.status IN ('pending', 'deferred') AND NOT EXISTS (
            SELECT 1 FROM job_suppressions s
            WHERE s.active = 1 AND (s.job_id = j.id OR ((s.job_id IS NULL OR trim(s.job_id) = '') AND s.url = j.url))
        )
        ORDER BY
            CASE a.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
            datetime(a.due_at) ASC,
            a.id ASC
        """
    ).fetchall()
    return [_action_row_to_dict(row) for row in rows]


def _assistant_snapshot_jobs(conn: Any, limit: int = 500) -> list[dict[str, Any]]:
    profile = get_candidate_profile(conn)
    profile_version = int(profile.get("score_version") or 1)
    rows = conn.execute(
        """
        SELECT payload_json
        FROM job_dashboard_snapshots
        WHERE profile_version = ?
        ORDER BY COALESCE(match_score, -1) DESC, posted DESC
        LIMIT ?
        """,
        (profile_version, max(1, int(limit))),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row[0] or "{}")
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            items.append(payload)
    if not items:
        items, _ = list_jobs(
            conn,
            status=None,
            q=None,
            ats=None,
            company=None,
            posted_after=None,
            posted_before=None,
            sort="match_desc",
            limit=limit,
            offset=0,
        )
        return items

    # Overlay fresh manual decisions and tracking state on top of the cached
    # snapshot payload. Snapshot refresh is async, so the recommendation baked
    # into the snapshot can lag behind the latest decision/tracking mutation.
    decisions = _load_manual_decisions(conn)
    if not decisions:
        return items
    source_quality_map, role_quality_map = _load_source_quality_maps(conn)
    for item in items:
        job_id = str(item.get("id") or "")
        if not job_id or job_id not in decisions:
            continue
        _attach_recommendation(
            conn,
            profile=profile,
            item=item,
            decisions=decisions,
            source_quality_map=source_quality_map,
            role_quality_map=role_quality_map,
        )
    return items


def refresh_action_queue(conn: Any) -> list[dict[str, Any]]:
    items = _assistant_snapshot_jobs(conn, limit=500)
    desired_keys: set[tuple[str, str, str]] = set()

    actionable = [
        item
        for item in items
        if str(item.get("recommendation") or "") in _ACTIONABLE_RECOMMENDATIONS
    ]
    for index, item in enumerate(actionable[:8]):
        recommendation = str(item.get("recommendation") or "")
        action_type = "apply" if recommendation == "apply_now" else "review"
        reason = str((item.get("recommendation_reasons") or ["Review this role."])[0])
        due_at = _now_iso()
        priority = "high" if recommendation == "apply_now" and index < 6 else "medium"
        _upsert_system_action(
            conn,
            job_id=str(item["id"]),
            action_type=action_type,
            priority=priority,
            due_at=due_at,
            reason=reason,
            payload={"recommendation": recommendation},
        )
        desired_keys.add((str(item["id"]), action_type, reason))

    for item in items:
        if bool(item.get("staging_overdue")):
            reason = "Staging SLA is overdue; decide whether to apply or reject."
            _upsert_system_action(
                conn,
                job_id=str(item["id"]),
                action_type="review",
                priority="high",
                due_at=_now_iso(),
                reason=reason,
                payload={
                    "recommendation": str(
                        item.get("recommendation") or "review_manually"
                    )
                },
            )
            desired_keys.add((str(item["id"]), "review", reason))

    gaps = get_profile_gaps(conn).get("items", [])
    for gap in gaps[:2]:
        example_job_id = str((gap.get("example_job_ids") or [""])[0] or "")
        if not example_job_id:
            continue
        reason = f"Close profile gap: {gap['label']}"
        _upsert_system_action(
            conn,
            job_id=example_job_id,
            action_type="update_profile_gap",
            priority="medium",
            due_at=_now_iso(),
            reason=reason,
            payload={"kind": gap.get("kind"), "count": gap.get("count")},
        )
        desired_keys.add((example_job_id, "update_profile_gap", reason))

    follow_up_rows = conn.execute(
        """
        SELECT job_id, reason
        FROM job_actions
        WHERE source = 'system' AND action_type = 'follow_up' AND status IN ('pending', 'deferred')
        """
    ).fetchall()
    for row in follow_up_rows:
        desired_keys.add((str(row[0] or ""), "follow_up", str(row[1] or "")))

    rows = conn.execute(
        """
        SELECT id, job_id, action_type, reason, status
        FROM job_actions
        WHERE source = 'system' AND status IN ('pending', 'deferred')
        """
    ).fetchall()
    now = _now_iso()
    for row in rows:
        key = (str(row[1] or ""), str(row[2] or ""), str(row[3] or ""))
        if key not in desired_keys:
            conn.execute(
                "UPDATE job_actions SET status = 'dismissed', updated_at = ?, completed_at = COALESCE(completed_at, ?) WHERE id = ?",
                (now, now, int(row[0])),
            )
    conn.commit()
    return _pending_actions(conn)


def list_actions_today(conn: Any, *, refresh: bool = True) -> list[dict[str, Any]]:
    if refresh:
        refresh_action_queue(conn)
    now = _now_iso()
    rows = conn.execute(
        """
        SELECT
            a.id,
            a.job_id,
            j.url,
            j.company,
            j.title,
            a.action_type,
            a.priority,
            a.due_at,
            a.reason,
            a.status,
            d.recommendation_override
        FROM job_actions a
        INNER JOIN jobs j ON j.id = a.job_id
        LEFT JOIN job_decisions d ON d.job_id = a.job_id
        WHERE a.status IN ('pending', 'deferred') AND datetime(a.due_at) <= datetime(?)
        ORDER BY
            CASE a.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
            datetime(a.due_at) ASC,
            a.id ASC
        LIMIT 24
        """,
        (now,),
    ).fetchall()
    return [_action_row_to_dict(row) for row in rows]


def complete_action(conn: Any, action_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, job_id, action_type, priority, due_at, reason, status
        FROM job_actions
        WHERE id = ?
        """,
        (action_id,),
    ).fetchone()
    if not row:
        return None
    now = _now_iso()
    conn.execute(
        "UPDATE job_actions SET status = 'completed', completed_at = ?, updated_at = ? WHERE id = ?",
        (now, now, action_id),
    )
    job_id = str(row[1] or "")
    action_type = str(row[2] or "")
    if action_type == "apply":
        today = datetime.now(timezone.utc).date().isoformat()
        upsert_tracking(conn, job_id, {"status": "applied", "applied_at": today})
        create_event(
            conn,
            job_id,
            {
                "event_type": "application_submitted",
                "title": "Application submitted",
                "body": "Marked complete from the action queue.",
                "event_at": today,
            },
        )
    conn.commit()
    refreshed = conn.execute(
        """
        SELECT a.id, a.job_id, j.url, j.company, j.title, a.action_type, a.priority, a.due_at, a.reason, a.status, d.recommendation_override
        FROM job_actions a
        INNER JOIN jobs j ON j.id = a.job_id
        LEFT JOIN job_decisions d ON d.job_id = a.job_id
        WHERE a.id = ?
        """,
        (action_id,),
    ).fetchone()
    return _action_row_to_dict(refreshed) if refreshed else None


def defer_action(conn: Any, action_id: int, days: int = 2) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, job_id, action_type, priority, due_at, reason, status
        FROM job_actions
        WHERE id = ?
        """,
        (action_id,),
    ).fetchone()
    if not row:
        return None
    due_at = _plus_days_iso(_now_iso(), days)
    now = _now_iso()
    conn.execute(
        "UPDATE job_actions SET status = 'deferred', due_at = ?, updated_at = ? WHERE id = ?",
        (due_at, now, action_id),
    )
    conn.commit()
    refreshed = conn.execute(
        """
        SELECT a.id, a.job_id, j.url, j.company, j.title, a.action_type, a.priority, a.due_at, a.reason, a.status, d.recommendation_override
        FROM job_actions a
        INNER JOIN jobs j ON j.id = a.job_id
        LEFT JOIN job_decisions d ON d.job_id = a.job_id
        WHERE a.id = ?
        """,
        (action_id,),
    ).fetchone()
    return _action_row_to_dict(refreshed) if refreshed else None


def get_conversion_metrics(conn: Any) -> dict[str, Any]:
    rows = conn.execute(
        f"""
        SELECT
            j.id,
            COALESCE(j.ats, ''),
            COALESCE(e.role_family, COALESCE(j.title, '')),
            (
                EXISTS(SELECT 1 FROM job_events ev WHERE ev.job_id = j.id AND ev.event_type = 'application_submitted')
                OR COALESCE(t.status, j.application_status) IN ('applied', 'interviewing', 'offer', 'rejected')
            ) AS applied,
            (
                EXISTS(SELECT 1 FROM job_events ev WHERE ev.job_id = j.id AND ev.event_type IN ('recruiter_reply', 'recruiter_screen', 'hiring_manager_screen', 'technical_interview', 'onsite', 'offer'))
                OR COALESCE(t.status, j.application_status) IN ('interviewing', 'offer')
            ) AS responses,
            (
                EXISTS(SELECT 1 FROM job_events ev WHERE ev.job_id = j.id AND ev.event_type IN ('hiring_manager_screen', 'technical_interview', 'onsite', 'offer'))
                OR COALESCE(t.status, j.application_status) IN ('interviewing', 'offer')
            ) AS interviews,
            (
                EXISTS(SELECT 1 FROM job_events ev WHERE ev.job_id = j.id AND ev.event_type = 'offer')
                OR COALESCE(t.status, j.application_status) = 'offer'
            ) AS offers,
            (
                EXISTS(SELECT 1 FROM job_events ev WHERE ev.job_id = j.id AND ev.event_type IN ('resume_rejected', 'rejection', 'closed_no_response'))
                OR COALESCE(t.status, j.application_status) = 'rejected'
            ) AS rejections
        FROM jobs j
        LEFT JOIN job_tracking t ON t.job_id = j.id
        LEFT JOIN job_enrichments e ON e.job_id = j.id
        WHERE {_not_suppressed_sql("j")}
        """
    ).fetchall()
    overall = {
        "key": "overall",
        "applied": 0,
        "responses": 0,
        "interviews": 0,
        "offers": 0,
        "rejections": 0,
    }
    by_ats: dict[str, dict[str, Any]] = {}
    by_role: dict[str, dict[str, Any]] = {}
    for row in rows:
        ats = str(row[1] or "").strip().lower() or "unknown"
        role_family = _role_family_label(str(row[2] or ""))
        applied = int(row[3] or 0)
        responses = int(row[4] or 0)
        interviews = int(row[5] or 0)
        offers = int(row[6] or 0)
        rejections = int(row[7] or 0)
        for bucket in (
            overall,
            by_ats.setdefault(
                ats,
                {
                    "key": ats,
                    "applied": 0,
                    "responses": 0,
                    "interviews": 0,
                    "offers": 0,
                    "rejections": 0,
                },
            ),
            by_role.setdefault(
                role_family,
                {
                    "key": role_family,
                    "applied": 0,
                    "responses": 0,
                    "interviews": 0,
                    "offers": 0,
                    "rejections": 0,
                },
            ),
        ):
            bucket["applied"] += applied
            bucket["responses"] += responses
            bucket["interviews"] += interviews
            bucket["offers"] += offers
            bucket["rejections"] += rejections
    return {
        "overall": overall,
        "by_ats": sorted(
            by_ats.values(),
            key=lambda item: (-item["responses"], -item["applied"], item["key"]),
        )[:8],
        "by_role_family": sorted(
            by_role.values(),
            key=lambda item: (-item["responses"], -item["applied"], item["key"]),
        )[:8],
    }


def get_source_quality(conn: Any) -> dict[str, Any]:
    conversion = get_conversion_metrics(conn)
    items: list[dict[str, Any]] = []
    for bucket in conversion["by_ats"]:
        applied = int(bucket["applied"] or 0)
        positive = int(bucket["responses"] or 0)
        negative = int(bucket["rejections"] or 0)
        quality_score = (
            50
            if applied <= 0
            else clamp(50 + (positive / applied * 35) - (negative / applied * 25))
        )
        items.append(
            {
                "ats": bucket["key"],
                "applied": applied,
                "positive_outcomes": positive,
                "negative_outcomes": negative,
                "quality_score": quality_score,
            }
        )
    return {"items": items}


def get_profile_gaps(conn: Any) -> dict[str, Any]:
    profile = get_profile(conn)
    jobs, _ = list_jobs(
        conn,
        status=None,
        q=None,
        ats=None,
        company=None,
        posted_after=None,
        posted_before=None,
        sort="match_desc",
        limit=200,
        offset=0,
    )
    actionable_jobs = [
        item
        for item in jobs[:80]
        if str(item.get("recommendation") or "") in _ACTIONABLE_RECOMMENDATIONS
    ]
    job_ids = [str(item.get("id") or "") for item in actionable_jobs if str(item.get("id") or "")]
    enrichments_by_job_id: dict[str, dict[str, Any]] = {}
    if job_ids:
        rows = conn.execute(
            """
            SELECT job_id, required_skills, years_exp_min, visa_sponsorship
            FROM job_enrichments
            WHERE job_id IN ({placeholders})
            """.format(placeholders=",".join("?" for _ in job_ids)),
            tuple(job_ids),
        ).fetchall()
        for row in rows:
            enrichments_by_job_id[str(row[0] or "")] = {
                "required_skills": _parse_json_array(row[1]),
                "years_exp_min": row[2],
                "visa_sponsorship": row[3],
            }
    skill_counts: dict[str, dict[str, Any]] = {}
    kind_counts: dict[str, dict[str, Any]] = {}
    skills = [
        str(item).strip() for item in profile.get("skills", []) if str(item).strip()
    ]
    for item in actionable_jobs:
        job_id = str(item.get("id") or "")
        enrichment = enrichments_by_job_id.get(job_id, {})
        required = [
            str(item).strip()
            for item in enrichment.get("required_skills", [])
            if str(item).strip()
        ]
        _, missing_required = overlap_skills(required, skills)
        for skill in missing_required[:5]:
            bucket = skill_counts.setdefault(
                skill,
                {
                    "label": skill,
                    "kind": "skill_gap",
                    "count": 0,
                    "example_job_ids": [],
                },
            )
            bucket["count"] += 1
            if job_id not in bucket["example_job_ids"]:
                bucket["example_job_ids"].append(job_id)
        years_min = enrichment.get("years_exp_min")
        try:
            if (
                years_min is not None
                and int(years_min) > int(profile.get("years_experience") or 0) + 2
            ):
                bucket = kind_counts.setdefault(
                    "Seniority mismatch",
                    {
                        "label": "Seniority mismatch",
                        "kind": "seniority_mismatch",
                        "count": 0,
                        "example_job_ids": [],
                    },
                )
                bucket["count"] += 1
                bucket["example_job_ids"].append(job_id)
        except Exception:
            pass
        if bool(profile.get("requires_visa_sponsorship")) and str(
            enrichment.get("visa_sponsorship") or ""
        ).strip().lower() in {"no", "not available"}:
            bucket = kind_counts.setdefault(
                "Work authorization mismatch",
                {
                    "label": "Work authorization mismatch",
                    "kind": "work_authorization_mismatch",
                    "count": 0,
                    "example_job_ids": [],
                },
            )
            bucket["count"] += 1
            bucket["example_job_ids"].append(job_id)
        if not item.get("desired_title_match"):
            bucket = kind_counts.setdefault(
                "Title positioning gap",
                {
                    "label": "Title positioning gap",
                    "kind": "title_positioning_gap",
                    "count": 0,
                    "example_job_ids": [],
                },
            )
            bucket["count"] += 1
            bucket["example_job_ids"].append(job_id)
    items = list(skill_counts.values()) + list(kind_counts.values())
    items.sort(key=lambda item: (-int(item["count"]), item["label"]))
    for item in items:
        item["example_job_ids"] = item["example_job_ids"][:3]
    return {"items": items[:8]}


def get_profile_insights(conn: Any) -> dict[str, Any]:
    gaps = get_profile_gaps(conn)["items"]
    conversion = get_conversion_metrics(conn)
    roles_more = [
        str(item["key"])
        for item in conversion["by_role_family"]
        if int(item["responses"]) > 0
    ][:3]
    roles_less = [
        str(item["key"])
        for item in conversion["by_role_family"]
        if int(item["applied"]) >= 2 and int(item["responses"]) == 0
    ][:3]
    suggestions: list[str] = []
    for gap in gaps[:3]:
        if gap["kind"] == "skill_gap":
            suggestions.append(
                f"Add stronger evidence for {gap['label']} in your resume and project stories."
            )
        elif gap["kind"] == "title_positioning_gap":
            suggestions.append(
                "Adjust desired titles so your profile matches the roles that are surfacing as strong opportunities."
            )
        elif gap["kind"] == "seniority_mismatch":
            suggestions.append(
                "Tighten target seniority or emphasize scope/ownership to reduce seniority mismatch."
            )
        elif gap["kind"] == "work_authorization_mismatch":
            suggestions.append(
                "De-prioritize roles that explicitly conflict with your work authorization needs."
            )
    return {
        "top_missing_signals": gaps[:5],
        "roles_you_should_target_more": roles_more,
        "roles_you_should_target_less": roles_less,
        "suggested_profile_updates": suggestions[:4],
    }


def _daily_briefing_item(
    *,
    job_id: str,
    job_url: str | None,
    company: str | None,
    title: str | None,
    reason: str,
    due_at: str | None = None,
    recommendation: str | None = None,
    score: int | None = None,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "job_url": job_url,
        "company": company,
        "title": title,
        "reason": reason,
        "due_at": due_at,
        "recommendation": recommendation,
        "score": score,
    }


def _briefing_payload_from_state(conn: Any) -> dict[str, Any]:
    queue_items = refresh_action_queue(conn)
    today_actions = list_actions_today(conn, refresh=False)
    jobs = _assistant_snapshot_jobs(conn, limit=200)
    jobs_by_id = {str(item["id"]): item for item in jobs}
    apply_now: list[dict[str, Any]] = []
    seen_apply_ids: set[str] = set()
    for item in queue_items:
        if str(item.get("action_type") or "") != "apply":
            continue
        job_id = str(item.get("job_id") or "")
        if not job_id or job_id in seen_apply_ids:
            continue
        seen_apply_ids.add(job_id)
        job = jobs_by_id.get(job_id, {})
        apply_now.append(
            _daily_briefing_item(
                job_id=job_id,
                job_url=item.get("job_url"),
                company=item.get("company"),
                title=item.get("title"),
                reason=str(item.get("reason") or "Apply to this role."),
                due_at=str(item.get("due_at") or "") or None,
                recommendation=str(item.get("recommendation") or "")
                or str(job.get("recommendation") or "")
                or None,
                score=int(job.get("interview_likelihood_score") or 0)
                if job.get("interview_likelihood_score") is not None
                else None,
            )
        )
        if len(apply_now) >= 5:
            break

    follow_ups_due: list[dict[str, Any]] = []
    seen_follow_ids: set[str] = set()
    for item in today_actions:
        if str(item.get("action_type") or "") != "follow_up":
            continue
        job_id = str(item.get("job_id") or "")
        if not job_id or job_id in seen_follow_ids:
            continue
        seen_follow_ids.add(job_id)
        job = jobs_by_id.get(job_id, {})
        follow_ups_due.append(
            _daily_briefing_item(
                job_id=job_id,
                job_url=item.get("job_url"),
                company=item.get("company"),
                title=item.get("title"),
                reason=str(item.get("reason") or "Follow up."),
                due_at=str(item.get("due_at") or "") or None,
                recommendation=str(item.get("recommendation") or "")
                or str(job.get("recommendation") or "")
                or None,
                score=int(job.get("interview_likelihood_score") or 0)
                if job.get("interview_likelihood_score") is not None
                else None,
            )
        )
        if len(follow_ups_due) >= 5:
            break

    watchlist: list[dict[str, Any]] = []
    blocked_ids = {item["job_id"] for item in apply_now} | {
        item["job_id"] for item in follow_ups_due
    }
    for job in jobs:
        job_id = str(job.get("id") or "")
        if not job_id or job_id in blocked_ids:
            continue
        if str(job.get("recommendation") or "") != "review_manually":
            continue
        if str(job.get("status") or "") in {"rejected", "offer"}:
            continue
        reasons = [
            str(item).strip()
            for item in job.get("recommendation_reasons", [])
            if str(item).strip()
        ]
        watchlist.append(
            _daily_briefing_item(
                job_id=job_id,
                job_url=str(job.get("url") or "") or None,
                company=str(job.get("company") or "") or None,
                title=str(job.get("title") or "") or None,
                reason=reasons[0]
                if reasons
                else "Worth a closer look before applying.",
                recommendation=str(job.get("recommendation") or "") or None,
                score=int(job.get("interview_likelihood_score") or 0)
                if job.get("interview_likelihood_score") is not None
                else None,
            )
        )
        if len(watchlist) >= 4:
            break

    profile_insights = get_profile_insights(conn)
    profile_gaps = [
        str(item.get("label") or "").strip()
        for item in profile_insights.get("top_missing_signals", [])
        if str(item.get("label") or "").strip()
    ][:3]
    conversion = get_conversion_metrics(conn)
    source_quality = get_source_quality(conn).get("items", [])
    signals: list[str] = []
    overall = conversion.get("overall", {})
    applied = int(overall.get("applied") or 0)
    responses = int(overall.get("responses") or 0)
    interviews = int(overall.get("interviews") or 0)
    if applied > 0:
        response_rate = round((responses / applied) * 100)
        interview_rate = round((interviews / applied) * 100)
        signals.append(
            f"{responses} responses from {applied} applications ({response_rate}% response rate, {interview_rate}% interview rate)."
        )
    else:
        signals.append(
            "No application outcomes yet; use today to build the first clean signal set."
        )
    if source_quality:
        best_source = max(
            source_quality,
            key=lambda item: (
                int(item.get("quality_score") or 0),
                int(item.get("applied") or 0),
            ),
        )
        signals.append(
            f"Best recent source: {best_source['ats']} at {int(best_source.get('quality_score') or 0)}/100 quality."
        )
    if profile_insights.get("roles_you_should_target_more"):
        signals.append(
            f"Lean harder into {', '.join(str(item) for item in profile_insights['roles_you_should_target_more'][:2])}."
        )

    quiet_day = not apply_now and not follow_ups_due and not watchlist
    if quiet_day:
        summary_line = "Quiet day: no urgent applications or follow-ups, so focus on profile improvements and keeping sources fresh."
    else:
        parts: list[str] = []
        if apply_now:
            parts.append(
                f"{len(apply_now)} apply-now role{'s' if len(apply_now) != 1 else ''}"
            )
        if follow_ups_due:
            parts.append(
                f"{len(follow_ups_due)} follow-up{'s' if len(follow_ups_due) != 1 else ''} due"
            )
        if watchlist:
            parts.append(
                f"{len(watchlist)} watchlist review{'s' if len(watchlist) != 1 else ''}"
            )
        summary_line = "Today: " + ", ".join(parts) + "."
    return {
        "summary_line": summary_line,
        "quiet_day": quiet_day,
        "apply_now": apply_now,
        "follow_ups_due": follow_ups_due,
        "watchlist": watchlist,
        "profile_gaps": profile_gaps,
        "signals": signals[:3],
    }


def _daily_briefing_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    payload_raw = row[2]
    payload: dict[str, Any] = {}
    if isinstance(payload_raw, str):
        try:
            parsed = json.loads(payload_raw)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
    return {
        "brief_date": str(row[0] or ""),
        "generated_at": str(row[1] or ""),
        "telegram_sent_at": str(row[3] or "") or None,
        "trigger_source": str(row[5] or "scheduled"),
        "summary_line": str(payload.get("summary_line") or ""),
        "quiet_day": bool(payload.get("quiet_day")),
        "apply_now": list(payload.get("apply_now") or []),
        "follow_ups_due": list(payload.get("follow_ups_due") or []),
        "watchlist": list(payload.get("watchlist") or []),
        "profile_gaps": [
            str(item)
            for item in list(payload.get("profile_gaps") or [])
            if str(item).strip()
        ],
        "signals": [
            str(item)
            for item in list(payload.get("signals") or [])
            if str(item).strip()
        ],
    }


def get_daily_briefing(
    conn: Any, brief_date: str | None = None
) -> dict[str, Any] | None:
    target_date = (brief_date or _local_today()).strip()
    row = conn.execute(
        """
        SELECT brief_date, generated_at, payload_json, telegram_sent_at, telegram_message_hash, trigger_source
        FROM daily_briefings
        WHERE brief_date = ?
        """,
        (target_date,),
    ).fetchone()
    return _daily_briefing_from_row(row) if row else None


def refresh_daily_briefing(
    conn: Any, *, trigger_source: str = "scheduled"
) -> dict[str, Any]:
    brief_date = _local_today()
    generated_at = _now_iso()
    payload = _briefing_payload_from_state(conn)
    conn.execute(
        """
        INSERT INTO daily_briefings (brief_date, generated_at, payload_json, trigger_source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(brief_date) DO UPDATE SET
            generated_at = excluded.generated_at,
            payload_json = excluded.payload_json,
            trigger_source = excluded.trigger_source
        """,
        (brief_date, generated_at, _json_text(payload), trigger_source),
    )
    conn.commit()
    return get_daily_briefing(conn, brief_date) or {
        "brief_date": brief_date,
        "generated_at": generated_at,
        "telegram_sent_at": None,
        "trigger_source": trigger_source,
        **payload,
    }


def get_or_create_daily_briefing(conn: Any) -> dict[str, Any]:
    existing = get_daily_briefing(conn)
    if existing:
        return existing
    return refresh_daily_briefing(conn, trigger_source="scheduled")


def mark_daily_briefing_sent(
    conn: Any, *, brief_date: str, message_hash: str
) -> dict[str, Any] | None:
    sent_at = _now_iso()
    conn.execute(
        """
        UPDATE daily_briefings
        SET telegram_sent_at = ?, telegram_message_hash = ?
        WHERE brief_date = ?
        """,
        (sent_at, message_hash, brief_date),
    )
    conn.commit()
    return get_daily_briefing(conn, brief_date)


def get_stats(conn: Any) -> dict[str, Any]:
    profile = get_candidate_profile(conn)
    profile_version = int(profile.get("score_version") or 1)
    snapshot_items = _load_snapshot_items(conn, profile_version=profile_version)
    if snapshot_items:
        total_jobs = len(snapshot_items)
        by_status: dict[str, int] = {}
        tracked_jobs = 0
        for item in snapshot_items:
            status = str(item.get("status") or "not_applied")
            by_status[status] = by_status.get(status, 0) + 1
            if status != "not_applied":
                tracked_jobs += 1
    else:
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
                WHERE {_not_suppressed_sql("j")}
                """
            ).fetchone()[0]
        )

        by_status_rows = conn.execute(
            f"""
            SELECT {_normalized_status_sql("t.status", "j.application_status")} AS s, COUNT(*)
            FROM jobs j
            LEFT JOIN job_tracking t ON t.job_id = j.id
            WHERE {_not_suppressed_sql("j")}
            GROUP BY s
            """
        ).fetchall()
        by_status = {str(row[0]): int(row[1]) for row in by_status_rows}
    active_pipeline = sum(by_status.get(key, 0) for key in ("applied", "interviewing"))
    recent_activity_7d = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM job_events ev
            INNER JOIN jobs j ON j.id = ev.job_id
            WHERE datetime(ev.created_at) >= datetime('now', '-7 day')
              AND {_not_suppressed_sql("j")}
            """
        ).fetchone()[0]
    )
    overdue_staging_count = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM job_tracking t
            INNER JOIN jobs j ON j.id = t.job_id
            WHERE t.status = 'staging'
              AND t.staging_due_at IS NOT NULL
              AND datetime(t.staging_due_at) <= datetime('now')
              AND {_not_suppressed_sql("j")}
            """
        ).fetchone()[0]
    )
    return {
        "total_jobs": total_jobs,
        "tracked_jobs": tracked_jobs,
        "active_pipeline": active_pipeline,
        "recent_activity_7d": recent_activity_7d,
        "overdue_staging_count": overdue_staging_count,
        "by_status": by_status,
    }


def get_profile(conn: Any) -> dict[str, Any]:
    return get_candidate_profile(conn)


def save_profile(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return upsert_candidate_profile(conn, payload)


def bump_profile_score_version(conn: Any) -> int:
    return bump_candidate_profile_score_version(conn)


def recompute_match_scores(
    conn: Any,
    *,
    urls: list[str] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> int:
    profile = get_candidate_profile(conn)
    profile_version = int(profile.get("score_version") or 1)
    rows = conn.execute(
        """
        SELECT
            j.id,
            j.url,
            COALESCE(j.title, ''),
            COALESCE(t.status, COALESCE(j.application_status, 'not_applied')),
            CASE
                WHEN EXISTS(
                    SELECT 1
                    FROM job_suppressions js
                    WHERE js.active = 1
                      AND (js.job_id = j.id OR ((js.job_id IS NULL OR trim(js.job_id) = '') AND js.url = j.url))
                ) THEN 1
                ELSE 0
            END,
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
        LEFT JOIN job_tracking t ON t.job_id = j.id
        """,
    ).fetchall()

    total = len(rows)
    if total == 0:
        if progress_callback is not None:
            progress_callback(0, 0)
        return 0

    requested_urls = {str(url) for url in (urls or []) if str(url).strip()}
    computed_rows: list[dict[str, Any]] = []
    for row in rows:
        enrichment = _build_enrichment_payload(
            {
                "work_mode": row[5],
                "remote_geo": row[6],
                "canada_eligible": row[7],
                "seniority": row[8],
                "role_family": row[9],
                "years_exp_min": row[10],
                "years_exp_max": row[11],
                "minimum_degree": row[12],
                "required_skills": row[13],
                "preferred_skills": row[14],
                "formatted_description": row[15],
                "salary_min": row[16],
                "salary_max": row[17],
                "salary_currency": row[18],
                "visa_sponsorship": row[19],
                "red_flags": row[20],
                "enriched_at": row[21],
                "enrichment_status": row[22],
                "enrichment_model": row[23],
            }
        )
        match = compute_match_score({"title": row[2], "enrichment": enrichment}, profile)
        computed_rows.append(
            {
                "job_id": str(row[0] or ""),
                "url": str(row[1] or ""),
                "title": str(row[2] or ""),
                "status": str(row[3] or "not_applied"),
                "suppressed": bool(row[4]),
                "match": match,
                "enrichment": enrichment,
            }
        )
    # Load story and job embeddings for semantic blending
    try:
        from ai_job_hunter.dashboard.backend.embeddings import (
            blend_scores,
            compute_semantic_match,
            load_story_embeddings,
        )
        story_embeddings = load_story_embeddings(conn)
        # Fetch job embeddings keyed by job_id
        emb_rows = conn.execute(
            "SELECT job_id, job_embedding FROM job_enrichments WHERE job_embedding IS NOT NULL"
        ).fetchall()
        job_blob_by_id: dict[str, bytes] = {str(r[0]): r[1] for r in emb_rows if r[1]}
    except Exception:
        story_embeddings = []
        job_blob_by_id = {}

    cohort_inputs = [
        {
            **entry["match"],
            "suppressed": bool(entry["suppressed"]) or bool(entry["match"].get("suppressed")),
            "status": entry["status"],
            "key": entry["url"],
        }
        for entry in computed_rows
    ]
    calibrated_inputs = calibrate_match_scores(cohort_inputs)
    calibrated_by_url: dict[str, dict[str, Any]] = {}
    for calibrated in calibrated_inputs:
        calibrated_by_url[str(calibrated.get("key") or "")] = calibrated

    processed = 0
    for entry in computed_rows:
        calibrated = calibrated_by_url.get(entry["url"], entry["match"])

        # Blend semantic score when embeddings are available
        semantic_score: float | None = None
        matched_ids: list[int] = []
        matched_titles: list[str] = []
        if story_embeddings and entry["job_id"] in job_blob_by_id:
            sem, matched_ids, matched_titles = compute_semantic_match(
                job_blob_by_id[entry["job_id"]], story_embeddings
            )
            if sem > 0:
                semantic_score = round(sem, 2)
                blended = blend_scores(float(calibrated.get("score", 0) or 0), sem)
                calibrated = {**calibrated, "score": int(round(blended))}

        source_hash = _hash_score_source(
            title=entry["title"],
            enrichment=entry["enrichment"],
            profile_version=profile_version,
        )
        _upsert_match_row(
            conn,
            job_id=entry["job_id"],
            url=entry["url"],
            profile_version=profile_version,
            match=calibrated,
            source_hash=source_hash,
            semantic_score=semantic_score,
            matched_story_ids=matched_ids,
            matched_story_titles=matched_titles,
        )
        if not requested_urls or entry["url"] in requested_urls:
            processed += 1
        if progress_callback is not None and (
            processed == (len(requested_urls) or total) or processed % 50 == 0
        ):
            progress_callback(processed, len(requested_urls) or total)

    conn.commit()
    return processed
