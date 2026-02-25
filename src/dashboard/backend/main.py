from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
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
    CandidateProfile,
    CreateEventRequest,
    JobDetail,
    JobEvent,
    JobsListResponse,
    StatsResponse,
    TrackingPatchRequest,
)
from dashboard.backend.service import decode_job_url, normalize_tracking_patch


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
    sort: str,
    limit: int,
    offset: int,
) -> str:
    payload = {
        "status": status,
        "q": q,
        "ats": ats,
        "company": company,
        "posted_after": posted_after,
        "sort": sort,
        "limit": limit,
        "offset": offset,
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


def _invalidate_job_collections() -> None:
    cache.delete_pattern(f"{_CACHE_NS}:jobs:*")
    cache.delete(_stats_cache_key())


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
    sort: str = Query(default="match_desc", pattern="^(posted_desc|updated_desc|company_asc|match_desc)$"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> JobsListResponse:
    key = _jobs_cache_key(
        status=status,
        q=q,
        ats=ats,
        company=company,
        posted_after=posted_after,
        sort=sort,
        limit=limit,
        offset=offset,
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
            sort=sort,
            limit=limit,
            offset=offset,
        )
        response = JobsListResponse(items=items, total=total)
        cache.set_json(key, response.model_dump(), _TTL_JOBS)
        return response
    finally:
        conn.close()


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "dashboard.backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        app_dir=str(_SRC_DIR),
    )
