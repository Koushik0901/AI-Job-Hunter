from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

_THIS_DIR = Path(__file__).resolve().parent
_SRC_DIR = _THIS_DIR.parents[1]
_REPO_DIR = _SRC_DIR.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from db import init_db
from dashboard.backend.cache import DashboardCache, hash_id
from dashboard.backend import repository
from dashboard.backend.schemas import (
    AddProfileSkillRequest,
    CandidateProfile,
    CreateEventRequest,
    FunnelAnalyticsResponse,
    JobDetail,
    JobEvent,
    JobsListResponse,
    ManualJobCreateRequest,
    SuppressedJob,
    SuppressJobRequest,
    StatsResponse,
    TrackingPatchRequest,
)
from dashboard.backend.service import decode_job_url, normalize_tracking_patch
from enrich import RateLimitSignal, enrich_one_job


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE pairs into env without overriding existing variables."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(_REPO_DIR / ".env")


app = FastAPI(title="AI Job Hunter Dashboard API", version="1.0.0")
cache = DashboardCache(os.getenv("REDIS_URL"))

_CACHE_NS = "dashboard:v1"
_TTL_JOBS = int(os.getenv("DASHBOARD_CACHE_TTL_JOBS", "45"))
_TTL_JOB_DETAIL = int(os.getenv("DASHBOARD_CACHE_TTL_JOB_DETAIL", "300"))
_TTL_EVENTS = int(os.getenv("DASHBOARD_CACHE_TTL_EVENTS", "90"))
_TTL_STATS = int(os.getenv("DASHBOARD_CACHE_TTL_STATS", "30"))
_TTL_PROFILE = int(os.getenv("DASHBOARD_CACHE_TTL_PROFILE", "300"))
_TTL_ANALYTICS_FC = int(os.getenv("DASHBOARD_CACHE_TTL_ANALYTICS_FC", "60"))
_ENRICHMENT_MODEL = os.getenv("ENRICHMENT_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
_DESCRIPTION_FORMAT_MODEL = os.getenv("DESCRIPTION_FORMAT_MODEL", "openai/gpt-oss-20b:paid").strip() or "openai/gpt-oss-20b:paid"


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(value, maximum))


_MAX_JOB_DETAILS = _int_env("DASHBOARD_CACHE_MAX_JOB_DETAILS", default=24, minimum=1, maximum=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_db() -> tuple[str, str]:
    turso_url = os.getenv("TURSO_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")
    if not turso_url:
        raise RuntimeError("TURSO_URL is required. Local SQLite fallback is disabled for dashboard backend.")
    if not turso_token:
        raise RuntimeError("TURSO_AUTH_TOKEN is required when TURSO_URL is set.")
    return turso_url, turso_token


def _conn() -> Any:
    db_url, db_token = _resolve_db()
    return init_db(db_url, db_token)


def _jobs_cache_key(
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
    include_suppressed: bool,
) -> str:
    payload = {
        "status": status,
        "q": q,
        "ats": ats,
        "company": company,
        "posted_after": posted_after,
        "posted_before": posted_before,
        "sort": sort,
        "limit": limit,
        "offset": offset,
        "include_suppressed": include_suppressed,
    }
    return f"{_CACHE_NS}:jobs:{hash_id(str(payload))}"


def _job_cache_key(job_url: str) -> str:
    return f"{_CACHE_NS}:job:{hash_id(job_url)}"


def _events_cache_key(job_url: str) -> str:
    return f"{_CACHE_NS}:events:{hash_id(job_url)}"


def _profile_cache_key() -> str:
    return f"{_CACHE_NS}:profile"


def _stats_cache_key() -> str:
    return f"{_CACHE_NS}:stats"


def _job_detail_lru_key() -> str:
    return f"{_CACHE_NS}:idx:job_detail_lru"


def _analytics_funnel_cache_key(
    *,
    from_date: str | None,
    to_date: str | None,
    preset: str,
    status_scope: str,
    applications_goal_target: int,
    interviews_goal_target: int,
    forecast_apps_per_week: int | None,
) -> str:
    payload = {
        "from": from_date,
        "to": to_date,
        "preset": preset,
        "status_scope": status_scope,
        "applications_goal_target": applications_goal_target,
        "interviews_goal_target": interviews_goal_target,
        "forecast_apps_per_week": forecast_apps_per_week,
    }
    return f"{_CACHE_NS}:analytics:funnel:{hash_id(str(payload))}"


def _invalidate_job_collections() -> None:
    cache.delete_pattern(f"{_CACHE_NS}:jobs:*")
    cache.delete(_stats_cache_key())
    cache.delete_pattern(f"{_CACHE_NS}:analytics:funnel:*")


def _invalidate_job_detail(job_url: str) -> None:
    job_key = _job_cache_key(job_url)
    cache.delete(job_key, _events_cache_key(job_url))
    cache.zrem(_job_detail_lru_key(), job_key)


def _invalidate_all_job_details() -> None:
    cache.delete_pattern(f"{_CACHE_NS}:job:*")
    cache.delete_pattern(f"{_CACHE_NS}:events:*")
    cache.delete(_job_detail_lru_key())


def _touch_job_detail_lru(job_key: str) -> None:
    cache.zadd(_job_detail_lru_key(), {job_key: float(time.time())})
    _trim_job_detail_lru()


def _trim_job_detail_lru() -> None:
    count = cache.zcard(_job_detail_lru_key())
    overflow = count - _MAX_JOB_DETAILS
    if overflow <= 0:
        return
    oldest = cache.zrange(_job_detail_lru_key(), 0, overflow - 1)
    if not oldest:
        return
    cache.delete(*oldest)
    cache.zrem(_job_detail_lru_key(), *oldest)


def _background_enrich_manual_job(job_url: str) -> None:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return

    conn = _conn()
    try:
        item = repository.get_job_detail(conn, job_url)
        if not item:
            return
        description = str(item.get("description") or "").strip()
        if not description:
            return
        payload = {
            "url": item["url"],
            "company": item["company"],
            "title": item["title"],
            "location": item["location"],
            "description": description,
        }
        result = enrich_one_job(
            payload,
            api_key,
            _ENRICHMENT_MODEL,
            _DESCRIPTION_FORMAT_MODEL,
        )
        from db import save_enrichment
        save_enrichment(conn, job_url, result)
    except RateLimitSignal:
        return
    except Exception:
        return
    finally:
        conn.close()

    _invalidate_job_detail(job_url)
    _invalidate_job_collections()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/jobs", response_model=JobsListResponse)
def list_jobs(
    status: str | None = None,
    q: str | None = None,
    ats: str | None = None,
    company: str | None = None,
    posted_after: str | None = None,
    posted_before: str | None = None,
    sort: str = Query(default="match_desc", pattern="^(posted_desc|updated_desc|company_asc|match_desc)$"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    include_suppressed: bool = Query(default=False),
) -> JobsListResponse:
    key = _jobs_cache_key(
        status=status,
        q=q,
        ats=ats,
        company=company,
        posted_after=posted_after,
        posted_before=posted_before,
        sort=sort,
        limit=limit,
        offset=offset,
        include_suppressed=include_suppressed,
    )
    cached = cache.get_json(key)
    if isinstance(cached, dict) and isinstance(cached.get("items"), list) and isinstance(cached.get("total"), int):
        return JobsListResponse(**cached)

    conn = _conn()
    try:
        items, total = repository.list_jobs(
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
            include_suppressed=include_suppressed,
        )
        response = JobsListResponse(items=items, total=total)
        cache.set_json(key, response.model_dump(), _TTL_JOBS)
        return response
    finally:
        conn.close()


@app.post("/api/jobs/manual", response_model=JobDetail)
def create_manual_job(payload: ManualJobCreateRequest, background_tasks: BackgroundTasks) -> JobDetail:
    conn = _conn()
    try:
        try:
            item = repository.create_manual_job(conn, payload.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        response = JobDetail(**item)
    finally:
        conn.close()

    _invalidate_job_detail(response.url)
    _invalidate_job_collections()
    background_tasks.add_task(_background_enrich_manual_job, response.url)
    return response


@app.get("/api/profile", response_model=CandidateProfile)
def get_profile() -> CandidateProfile:
    cached = cache.get_json(_profile_cache_key())
    if isinstance(cached, dict):
        return CandidateProfile(**cached)

    conn = _conn()
    try:
        response = CandidateProfile(**repository.get_profile(conn))
        cache.set_json(_profile_cache_key(), response.model_dump(), _TTL_PROFILE)
        return response
    finally:
        conn.close()


@app.put("/api/profile", response_model=CandidateProfile)
def put_profile(payload: CandidateProfile) -> CandidateProfile:
    conn = _conn()
    try:
        saved = repository.save_profile(conn, payload.model_dump(exclude={"updated_at"}))
        response = CandidateProfile(**saved)
        cache.set_json(_profile_cache_key(), response.model_dump(), _TTL_PROFILE)
        _invalidate_job_collections()
        _invalidate_all_job_details()
        return response
    finally:
        conn.close()


@app.post("/api/profile/skills", response_model=CandidateProfile)
def add_profile_skill(payload: AddProfileSkillRequest) -> CandidateProfile:
    incoming = payload.skill.strip()
    if not incoming:
        raise HTTPException(status_code=400, detail="Skill cannot be empty")

    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in values:
            item = str(raw).strip()
            if not item:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    conn = _conn()
    try:
        saved: dict[str, Any] | None = None
        # Retry merge to avoid dropped updates under concurrent skill-add requests.
        for _ in range(3):
            profile = repository.get_profile(conn)
            current = _dedupe([str(item) for item in profile.get("skills", [])])
            if incoming.lower() not in {item.lower() for item in current}:
                current.append(incoming)
            profile["skills"] = _dedupe(current)
            saved = repository.save_profile(conn, profile)
            persisted = {str(item).strip().lower() for item in saved.get("skills", []) if str(item).strip()}
            if incoming.lower() in persisted:
                break

        if saved is None:
            raise HTTPException(status_code=500, detail="Failed to update profile skills")

        response = CandidateProfile(**saved)
        cache.set_json(_profile_cache_key(), response.model_dump(), _TTL_PROFILE)
        _invalidate_job_collections()
        _invalidate_all_job_details()
        return response
    finally:
        conn.close()


@app.patch("/api/jobs/{job_url:path}/tracking", response_model=JobDetail)
def patch_tracking(job_url: str, payload: TrackingPatchRequest) -> JobDetail:
    decoded = decode_job_url(job_url)
    patch = normalize_tracking_patch(payload.model_dump(exclude_unset=True))
    conn = _conn()
    try:
        if not repository.get_job_detail(conn, decoded):
            raise HTTPException(status_code=404, detail="Job not found")
        repository.upsert_tracking(conn, decoded, patch)
        item = repository.get_job_detail(conn, decoded)
        if not item:
            raise HTTPException(status_code=404, detail="Job not found after update")
        response = JobDetail(**item)
        key = _job_cache_key(decoded)
        cache.set_json(key, response.model_dump(), _TTL_JOB_DETAIL)
        _touch_job_detail_lru(key)
        cache.delete(_events_cache_key(decoded))
        _invalidate_job_collections()
        return response
    finally:
        conn.close()


@app.get("/api/jobs/{job_url:path}/events", response_model=list[JobEvent])
def get_events(job_url: str) -> list[JobEvent]:
    decoded = decode_job_url(job_url)
    cached = cache.get_json(_events_cache_key(decoded))
    if isinstance(cached, list):
        return [JobEvent(**e) for e in cached if isinstance(e, dict)]

    conn = _conn()
    try:
        if not repository.get_job_detail(conn, decoded):
            raise HTTPException(status_code=404, detail="Job not found")
        events = repository.list_events(conn, decoded)
        response = [JobEvent(**e) for e in events]
        cache.set_json(_events_cache_key(decoded), [e.model_dump() for e in response], _TTL_EVENTS)
        return response
    finally:
        conn.close()


@app.get("/api/jobs/{job_url:path}", response_model=JobDetail)
def get_job(job_url: str) -> JobDetail:
    decoded = decode_job_url(job_url)
    key = _job_cache_key(decoded)
    cached = cache.get_json(key)
    if isinstance(cached, dict):
        _touch_job_detail_lru(key)
        return JobDetail(**cached)

    conn = _conn()
    try:
        item = repository.get_job_detail(conn, decoded)
        if not item:
            raise HTTPException(status_code=404, detail="Job not found")
        response = JobDetail(**item)
        cache.set_json(key, response.model_dump(), _TTL_JOB_DETAIL)
        _touch_job_detail_lru(key)
        return response
    finally:
        conn.close()


@app.post("/api/jobs/{job_url:path}/events", response_model=JobEvent)
def post_event(job_url: str, payload: CreateEventRequest) -> JobEvent:
    decoded = decode_job_url(job_url)
    conn = _conn()
    try:
        if not repository.get_job_detail(conn, decoded):
            raise HTTPException(status_code=404, detail="Job not found")
        event = repository.create_event(conn, decoded, payload.model_dump())
        response = JobEvent(**event)
        _invalidate_job_detail(decoded)
        cache.delete(_events_cache_key(decoded), _stats_cache_key())
        return response
    finally:
        conn.close()


@app.delete("/api/events/{event_id}")
def remove_event(event_id: int) -> dict[str, int]:
    conn = _conn()
    try:
        changed = repository.delete_event(conn, event_id)
        if changed == 0:
            raise HTTPException(status_code=404, detail="Event not found")
        cache.delete_pattern(f"{_CACHE_NS}:events:*")
        cache.delete(_stats_cache_key())
        return {"deleted": changed}
    finally:
        conn.close()


@app.delete("/api/jobs/{job_url:path}")
def remove_job(job_url: str) -> dict[str, int]:
    decoded = decode_job_url(job_url)
    conn = _conn()
    try:
        changed = repository.delete_job(conn, decoded)
        if changed == 0:
            raise HTTPException(status_code=404, detail="Job not found")
        _invalidate_job_detail(decoded)
        _invalidate_job_collections()
        return {"deleted": changed}
    finally:
        conn.close()


@app.post("/api/jobs/{job_url:path}/suppress")
def suppress_job(job_url: str, payload: SuppressJobRequest) -> dict[str, int]:
    decoded = decode_job_url(job_url)
    conn = _conn()
    try:
        repository.suppress_job(conn, url=decoded, reason=payload.reason, created_by="ui")
        changed = 1
    finally:
        conn.close()
    _invalidate_job_detail(decoded)
    _invalidate_job_collections()
    return {"suppressed": changed}


@app.post("/api/jobs/{job_url:path}/unsuppress")
def unsuppress_job(job_url: str) -> dict[str, int]:
    decoded = decode_job_url(job_url)
    conn = _conn()
    try:
        changed = repository.unsuppress_job(conn, url=decoded)
    finally:
        conn.close()
    _invalidate_job_collections()
    return {"unsuppressed": changed}


@app.get("/api/suppressions", response_model=list[SuppressedJob])
def list_suppressions(limit: int = Query(default=200, ge=1, le=1000)) -> list[SuppressedJob]:
    conn = _conn()
    try:
        items = repository.list_active_suppressions(conn, limit=limit)
        return [SuppressedJob(**item) for item in items]
    finally:
        conn.close()


@app.get("/api/meta/stats", response_model=StatsResponse)
def meta_stats() -> StatsResponse:
    cached = cache.get_json(_stats_cache_key())
    if isinstance(cached, dict):
        return StatsResponse(**cached)

    conn = _conn()
    try:
        data = repository.get_stats(conn)
        response = StatsResponse(**data)
        cache.set_json(_stats_cache_key(), response.model_dump(), _TTL_STATS)
        return response
    finally:
        conn.close()


@app.get("/api/analytics/funnel", response_model=FunnelAnalyticsResponse)
def analytics_funnel(
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    preset: str = Query(default="90d", pattern="^(30d|90d|all)$"),
    status_scope: str = Query(default="pipeline", pattern="^(pipeline|all)$"),
    applications_goal_target: int = Query(default=10, ge=1, le=100),
    interviews_goal_target: int = Query(default=3, ge=1, le=50),
    forecast_apps_per_week: int | None = Query(default=None, ge=1, le=150),
) -> FunnelAnalyticsResponse:
    resolved_from = from_date
    resolved_to = to_date
    if not from_date and not to_date:
        if preset == "30d":
            resolved_from = _days_ago_date(30)
            resolved_to = _days_ago_date(0)
        elif preset == "90d":
            resolved_from = _days_ago_date(90)
            resolved_to = _days_ago_date(0)

    key = _analytics_funnel_cache_key(
        from_date=resolved_from,
        to_date=resolved_to,
        preset=preset,
        status_scope=status_scope,
        applications_goal_target=applications_goal_target,
        interviews_goal_target=interviews_goal_target,
        forecast_apps_per_week=forecast_apps_per_week,
    )
    cached = cache.get_json(key)
    if isinstance(cached, dict):
        return FunnelAnalyticsResponse(**cached)

    conn = _conn()
    try:
        data = repository.get_funnel_analytics(
            conn,
            from_date=resolved_from,
            to_date=resolved_to,
            status_scope=status_scope,
            applications_goal_target=applications_goal_target,
            interviews_goal_target=interviews_goal_target,
            forecast_apps_per_week=forecast_apps_per_week,
        )
        response = FunnelAnalyticsResponse(
            window={"from": resolved_from, "to": resolved_to, "preset": preset},
            stages=data["stages"],
            conversions=data["conversions"],
            totals=data["totals"],
            deltas=data["deltas"],
            weekly_goals=data["weekly_goals"],
            alerts=data["alerts"],
            cohorts=data["cohorts"],
            source_quality=data["source_quality"],
            forecast=data["forecast"],
        )
        cache.set_json(key, response.model_dump(by_alias=True), _TTL_ANALYTICS_FC)
        return response
    finally:
        conn.close()


def _days_ago_date(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "dashboard.backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        app_dir=str(_SRC_DIR),
    )
