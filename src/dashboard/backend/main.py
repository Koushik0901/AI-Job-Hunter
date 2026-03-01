from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, Response, UploadFile
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
    ResumeProfile,
    ResumeImportRequest,
    ResumeImportResponse,
    CreateEventRequest,
    FunnelAnalyticsResponse,
    JobDetail,
    JobEvent,
    JobsListResponse,
    ManualJobCreateRequest,
    ArtifactExportRequest,
    ArtifactSummary,
    ArtifactSuggestion,
    ArtifactVersion,
    ArtifactStarterStatus,
    CreateArtifactVersionRequest,
    GenerateArtifactSuggestionsRequest,
    GenerateStarterArtifactsRequest,
    SuggestionResolveRequest,
    SuppressedJob,
    SuppressJobRequest,
    StatsResponse,
    ScoreRecomputeStatus,
    TrackingPatchRequest,
)
from dashboard.backend.service import decode_job_url, normalize_tracking_patch
from dashboard.backend.resume_import import import_resume_pdf_bytes_to_baseline, import_resume_pdf_to_baseline

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
_ARTIFACT_AI_MODEL = os.getenv("ARTIFACT_AI_MODEL", "openai/gpt-oss-20b:paid").strip() or "openai/gpt-oss-20b:paid"
_DEFAULT_RESUME_IMPORT_SOURCE = os.getenv(
    "RESUME_IMPORT_SOURCE",
    r"C:\Users\koush\OneDrive\Documents\FULL-TIME\resume_ed_general.pdf",
).strip() or r"C:\Users\koush\OneDrive\Documents\FULL-TIME\resume_ed_general.pdf"
_SCORE_RECOMPUTE_LOCK = threading.Lock()
_SCORE_RECOMPUTE_STATE_LOCK = threading.Lock()
_SCORE_RECOMPUTE_STATE: dict[str, Any] = {
    "running": False,
    "queued_while_running": 0,
    "last_started_at": None,
    "last_finished_at": None,
    "last_duration_ms": None,
    "last_total": None,
    "last_processed": None,
    "last_scope": None,
    "last_error": None,
}
_ARTIFACT_STARTER_LOCK = threading.Lock()
_ARTIFACT_STARTER_STATE: dict[str, dict[str, Any]] = {}


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


def _resume_profile_cache_key() -> str:
    return f"{_CACHE_NS}:resume_profile"


def _stats_cache_key() -> str:
    return f"{_CACHE_NS}:stats"


def _job_detail_lru_key() -> str:
    return f"{_CACHE_NS}:idx:job_detail_lru"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_artifact_starter_state(job_url: str, stage: str, progress_percent: int, running: bool) -> None:
    bounded = max(0, min(100, int(progress_percent)))
    with _ARTIFACT_STARTER_LOCK:
        _ARTIFACT_STARTER_STATE[job_url] = {
            "job_url": job_url,
            "stage": stage,
            "progress_percent": bounded,
            "running": running,
            "updated_at": _now_iso(),
        }


def _get_artifact_starter_state(job_url: str) -> dict[str, Any]:
    with _ARTIFACT_STARTER_LOCK:
        item = _ARTIFACT_STARTER_STATE.get(job_url)
        if item:
            return dict(item)
    return {
        "job_url": job_url,
        "stage": "idle",
        "progress_percent": 0,
        "running": False,
        "updated_at": None,
    }


def _validate_resume_baseline_json(payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("baseline_resume_json must be an object")
    basics = payload.get("basics")
    if basics is not None and not isinstance(basics, dict):
        raise ValueError("baseline_resume_json.basics must be an object when provided")
    skills = payload.get("skills")
    if skills is not None:
        if not isinstance(skills, list):
            raise ValueError("baseline_resume_json.skills must be an array when provided")
        for index, item in enumerate(skills):
            if isinstance(item, str):
                continue
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                continue
            raise ValueError(f"baseline_resume_json.skills[{index}] must be a string or object with name")
    work = payload.get("work")
    if work is not None and not isinstance(work, list):
        raise ValueError("baseline_resume_json.work must be an array when provided")
    education = payload.get("education")
    if education is not None and not isinstance(education, list):
        raise ValueError("baseline_resume_json.education must be an array when provided")


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


def _get_score_recompute_status() -> dict[str, Any]:
    with _SCORE_RECOMPUTE_STATE_LOCK:
        return dict(_SCORE_RECOMPUTE_STATE)


def _set_score_recompute_status(**updates: Any) -> None:
    with _SCORE_RECOMPUTE_STATE_LOCK:
        _SCORE_RECOMPUTE_STATE.update(updates)


def _background_enrich_manual_job(job_url: str) -> None:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return

    conn = _conn()
    try:
        from enrich import RateLimitSignal, enrich_one_job

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
        repository.recompute_match_scores(conn, urls=[job_url])
    except RateLimitSignal:
        return
    except Exception:
        return
    finally:
        conn.close()

    _invalidate_job_detail(job_url)
    _invalidate_job_collections()


def _background_recompute_scores(urls: list[str] | None = None) -> None:
    acquired = _SCORE_RECOMPUTE_LOCK.acquire(blocking=False)
    if not acquired:
        with _SCORE_RECOMPUTE_STATE_LOCK:
            _SCORE_RECOMPUTE_STATE["queued_while_running"] = int(_SCORE_RECOMPUTE_STATE.get("queued_while_running") or 0) + 1
        return
    started_at = datetime.now(timezone.utc)
    scope = "all" if not urls else f"urls:{len(urls)}"
    _set_score_recompute_status(
        running=True,
        queued_while_running=0,
        last_started_at=started_at.isoformat(),
        last_finished_at=None,
        last_duration_ms=None,
        last_total=(len(urls) if urls else None),
        last_processed=0,
        last_scope=scope,
        last_error=None,
    )
    conn = _conn()
    try:
        def _progress(processed: int, total: int) -> None:
            _set_score_recompute_status(last_processed=processed, last_total=total)

        repository.recompute_match_scores(conn, urls=urls, progress_callback=_progress)
    except Exception as error:
        _set_score_recompute_status(last_error=str(error))
        return
    finally:
        finished_at = datetime.now(timezone.utc)
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        _set_score_recompute_status(
            running=False,
            last_finished_at=finished_at.isoformat(),
            last_duration_ms=duration_ms,
        )
        conn.close()
        _SCORE_RECOMPUTE_LOCK.release()
    _invalidate_all_job_details()
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
    background_tasks.add_task(_background_recompute_scores, [response.url])
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
def put_profile(payload: CandidateProfile, background_tasks: BackgroundTasks) -> CandidateProfile:
    conn = _conn()
    try:
        saved = repository.save_profile(conn, payload.model_dump(exclude={"updated_at"}))
        repository.bump_profile_score_version(conn)
        saved = repository.get_profile(conn)
        response = CandidateProfile(**saved)
        cache.set_json(_profile_cache_key(), response.model_dump(), _TTL_PROFILE)
        _invalidate_job_collections()
        _invalidate_all_job_details()
        background_tasks.add_task(_background_recompute_scores, None)
        return response
    finally:
        conn.close()


@app.get("/api/profile/resume", response_model=ResumeProfile)
def get_resume_profile() -> ResumeProfile:
    cached = cache.get_json(_resume_profile_cache_key())
    if isinstance(cached, dict):
        return ResumeProfile(**cached)

    conn = _conn()
    try:
        response = ResumeProfile(**repository.get_resume_profile_data(conn))
        cache.set_json(_resume_profile_cache_key(), response.model_dump(), _TTL_PROFILE)
        return response
    finally:
        conn.close()


@app.put("/api/profile/resume", response_model=ResumeProfile)
def put_resume_profile(payload: ResumeProfile) -> ResumeProfile:
    conn = _conn()
    try:
        try:
            _validate_resume_baseline_json(payload.baseline_resume_json)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        saved = repository.save_resume_profile_data(conn, payload.model_dump(exclude={"updated_at"}))
        response = ResumeProfile(**saved)
        cache.set_json(_resume_profile_cache_key(), response.model_dump(), _TTL_PROFILE)
        return response
    finally:
        conn.close()


@app.post("/api/profile/resume/import", response_model=ResumeImportResponse)
def import_resume_profile(payload: ResumeImportRequest) -> ResumeImportResponse:
    source = (payload.source_path or _DEFAULT_RESUME_IMPORT_SOURCE).strip()
    if not source:
        raise HTTPException(status_code=422, detail="source_path is required")
    try:
        baseline = import_resume_pdf_to_baseline(source)
        _validate_resume_baseline_json(baseline)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return ResumeImportResponse(source_path=source, baseline_resume_json=baseline)


@app.post("/api/profile/resume/import/upload", response_model=ResumeImportResponse)
async def import_resume_profile_upload(file: UploadFile = File(...)) -> ResumeImportResponse:
    filename = (file.filename or "uploaded-resume.pdf").strip()
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Only PDF uploads are supported")
    try:
        payload = await file.read()
        baseline = import_resume_pdf_bytes_to_baseline(payload, filename=filename)
        _validate_resume_baseline_json(baseline)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return ResumeImportResponse(source_path=filename, baseline_resume_json=baseline)


@app.post("/api/profile/skills", response_model=CandidateProfile)
def add_profile_skill(payload: AddProfileSkillRequest, background_tasks: BackgroundTasks) -> CandidateProfile:
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

        repository.bump_profile_score_version(conn)
        saved = repository.get_profile(conn)
        response = CandidateProfile(**saved)
        cache.set_json(_profile_cache_key(), response.model_dump(), _TTL_PROFILE)
        _invalidate_job_collections()
        _invalidate_all_job_details()
        background_tasks.add_task(_background_recompute_scores, None)
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
        previous_status = repository.get_tracking_status(conn, decoded)
        repository.upsert_tracking(conn, decoded, patch)
        next_status = str(patch.get("status") or previous_status)
        if previous_status != "staging" and next_status == "staging":
            repository.ensure_starter_artifacts_for_job(conn, decoded)
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


@app.get("/api/jobs/{job_url:path}/artifacts", response_model=list[ArtifactSummary])
def list_job_artifacts(job_url: str) -> list[ArtifactSummary]:
    decoded = decode_job_url(job_url)
    conn = _conn()
    try:
        if not repository.get_job_detail(conn, decoded):
            raise HTTPException(status_code=404, detail="Job not found")
        rows = repository.list_job_artifacts(conn, decoded)
        return [ArtifactSummary(**row) for row in rows]
    finally:
        conn.close()


@app.post("/api/jobs/{job_url:path}/artifacts/starter", response_model=list[ArtifactSummary])
def create_starter_artifacts(job_url: str, payload: GenerateStarterArtifactsRequest) -> list[ArtifactSummary]:
    decoded = decode_job_url(job_url)
    conn = _conn()
    try:
        if not repository.get_job_detail(conn, decoded):
            raise HTTPException(status_code=404, detail="Job not found")
        _set_artifact_starter_state(decoded, "queued", 5, True)
        def _progress(stage: str, percent: int) -> None:
            _set_artifact_starter_state(decoded, stage, percent, stage != "done")
        existing = repository.list_job_artifacts(conn, decoded)
        if payload.force:
            # Force re-generation only creates starter artifacts if identity rows are missing.
            repository.ensure_starter_artifacts_for_job_with_progress(conn, decoded, _progress)
        elif not existing:
            repository.ensure_starter_artifacts_for_job_with_progress(conn, decoded, _progress)
        rows = repository.list_job_artifacts(conn, decoded)
        _set_artifact_starter_state(decoded, "done", 100, False)
        _invalidate_job_detail(decoded)
        _invalidate_job_collections()
        return [ArtifactSummary(**row) for row in rows]
    except Exception:
        _set_artifact_starter_state(decoded, "error", 100, False)
        raise
    finally:
        conn.close()


@app.get("/api/jobs/{job_url:path}/artifacts/starter/status", response_model=ArtifactStarterStatus)
def get_starter_artifact_status(job_url: str) -> ArtifactStarterStatus:
    decoded = decode_job_url(job_url)
    conn = _conn()
    try:
        if not repository.get_job_detail(conn, decoded):
            raise HTTPException(status_code=404, detail="Job not found")
        state = _get_artifact_starter_state(decoded)
        return ArtifactStarterStatus(**state)
    finally:
        conn.close()


@app.get("/api/artifacts/{artifact_id}", response_model=ArtifactSummary)
def get_artifact(artifact_id: str) -> ArtifactSummary:
    conn = _conn()
    try:
        row = repository.get_artifact(conn, artifact_id)
        if not row:
            raise HTTPException(status_code=404, detail="Artifact not found")
        return ArtifactSummary(**row)
    finally:
        conn.close()


@app.delete("/api/artifacts/{artifact_id}")
def remove_artifact(artifact_id: str) -> dict[str, int]:
    conn = _conn()
    try:
        result = repository.delete_artifact(conn, artifact_id)
        deleted = int(result.get("deleted") or 0)
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Artifact not found")
        job_url = result.get("job_url")
        if isinstance(job_url, str) and job_url.strip():
            _invalidate_job_detail(job_url)
        _invalidate_job_collections()
        return {"deleted": deleted}
    finally:
        conn.close()


@app.delete("/api/jobs/{job_url:path}/artifacts/{artifact_type}")
def remove_job_artifact(job_url: str, artifact_type: str) -> dict[str, int]:
    decoded = decode_job_url(job_url)
    kind = artifact_type.strip().lower()
    if kind not in {"resume", "cover_letter"}:
        raise HTTPException(status_code=422, detail="artifact_type must be resume or cover_letter")
    conn = _conn()
    try:
        if not repository.get_job_detail(conn, decoded):
            raise HTTPException(status_code=404, detail="Job not found")
        result = repository.delete_job_artifact_by_type(conn, decoded, kind)
        deleted = int(result.get("deleted") or 0)
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Artifact not found")
        _invalidate_job_detail(decoded)
        _invalidate_job_collections()
        return {"deleted": deleted}
    finally:
        conn.close()


@app.get("/api/artifacts/{artifact_id}/versions", response_model=list[ArtifactVersion])
def get_artifact_versions(artifact_id: str, limit: int = Query(default=200, ge=1, le=1000)) -> list[ArtifactVersion]:
    conn = _conn()
    try:
        artifact = repository.get_artifact(conn, artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        rows = repository.list_artifact_versions(conn, artifact_id, limit=limit)
        return [ArtifactVersion(**row) for row in rows]
    finally:
        conn.close()


@app.post("/api/artifacts/{artifact_id}/versions", response_model=ArtifactVersion)
def post_artifact_version(artifact_id: str, payload: CreateArtifactVersionRequest) -> ArtifactVersion:
    conn = _conn()
    try:
        artifact = repository.get_artifact(conn, artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        version = repository.create_artifact_version(
            conn,
            artifact_id=artifact_id,
            label=payload.label,
            content_json={str(k): v for k, v in payload.content_json.items()},
            meta_json={str(k): v for k, v in payload.meta_json.items()},
            created_by=payload.created_by,
            base_version_id=payload.base_version_id,
        )
        _invalidate_job_detail(str(artifact["job_url"]))
        _invalidate_job_collections()
        return ArtifactVersion(**version)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail=f"Invalid suggestion patch: {error}") from error
    finally:
        conn.close()


@app.get("/api/artifacts/{artifact_id}/suggestions", response_model=list[ArtifactSuggestion])
def get_artifact_suggestions(artifact_id: str, pending_only: bool = Query(default=False)) -> list[ArtifactSuggestion]:
    conn = _conn()
    try:
        artifact = repository.get_artifact(conn, artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        rows = repository.list_artifact_suggestions(conn, artifact_id, pending_only=pending_only)
        return [ArtifactSuggestion(**row) for row in rows]
    finally:
        conn.close()


@app.post("/api/artifacts/{artifact_id}/suggestions/generate", response_model=list[ArtifactSuggestion])
def generate_artifact_suggestions(artifact_id: str, payload: GenerateArtifactSuggestionsRequest) -> list[ArtifactSuggestion]:
    conn = _conn()
    try:
        artifact = repository.get_artifact(conn, artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        active = artifact.get("active_version")
        if not isinstance(active, dict):
            raise HTTPException(status_code=400, detail="Artifact has no active version")
        job = repository.get_job_detail(conn, str(artifact["job_url"]))
        if not job:
            raise HTTPException(status_code=404, detail="Job not found for artifact")
        from dashboard.backend.artifact_ai import generate_patch_suggestions

        suggestions = generate_patch_suggestions(
            artifact_type=str(artifact["artifact_type"]),
            artifact_content={str(k): v for k, v in dict(active.get("content_json") or {}).items()},
            job_context=job,
            prompt=payload.prompt,
            target_path=payload.target_path,
            max_suggestions=payload.max_suggestions,
            api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
            model=_ARTIFACT_AI_MODEL,
        )
        rows = repository.create_artifact_suggestions(
            conn,
            artifact_id=artifact_id,
            base_version_id=str(active["id"]),
            suggestions=suggestions,
        )
        return [ArtifactSuggestion(**row) for row in rows]
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        conn.close()


@app.post("/api/suggestions/{suggestion_id}/accept", response_model=ArtifactVersion)
def accept_artifact_suggestion(suggestion_id: str, payload: SuggestionResolveRequest) -> ArtifactVersion:
    conn = _conn()
    try:
        result = repository.accept_artifact_suggestion(
            conn,
            suggestion_id=suggestion_id,
            edited_patch_json=payload.edited_patch_json,
            allow_outdated=payload.allow_outdated,
            created_by=payload.created_by,
        )
        new_version = result.get("new_version")
        if not isinstance(new_version, dict):
            raise HTTPException(status_code=500, detail="Failed to create artifact version from suggestion")
        artifact = repository.get_artifact(conn, str(new_version["artifact_id"]))
        if artifact:
            _invalidate_job_detail(str(artifact["job_url"]))
            _invalidate_job_collections()
        return ArtifactVersion(**new_version)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        conn.close()


@app.post("/api/suggestions/{suggestion_id}/reject")
def reject_artifact_suggestion(suggestion_id: str) -> dict[str, str]:
    conn = _conn()
    try:
        result = repository.reject_artifact_suggestion(conn, suggestion_id)
        return {"state": str(result["state"])}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        conn.close()


@app.post("/api/artifacts/{artifact_id}/export/pdf")
def export_artifact_pdf(artifact_id: str, payload: ArtifactExportRequest) -> Response:
    conn = _conn()
    try:
        artifact = repository.get_artifact(conn, artifact_id)
        if not artifact:
            raise HTTPException(status_code=404, detail="Artifact not found")
        active = artifact.get("active_version")
        if not isinstance(active, dict):
            raise HTTPException(status_code=400, detail="Artifact has no active version")
        from dashboard.backend.artifact_export import export_artifact_pdf as export_pdf

        pdf_bytes = export_pdf(
            artifact_type=str(artifact["artifact_type"]),
            content={str(k): v for k, v in dict(active.get("content_json") or {}).items()},
            meta={str(k): v for k, v in dict(active.get("meta_json") or {}).items()},
        )
        filename = f"{artifact['artifact_type']}-{active.get('version', 'latest')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
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


@app.get("/api/meta/scores/recompute-status", response_model=ScoreRecomputeStatus)
def score_recompute_status() -> ScoreRecomputeStatus:
    return ScoreRecomputeStatus(**_get_score_recompute_status())


@app.post("/api/meta/scores/recompute")
def trigger_score_recompute(background_tasks: BackgroundTasks) -> dict[str, int]:
    running = bool(_get_score_recompute_status().get("running"))
    if running:
        with _SCORE_RECOMPUTE_STATE_LOCK:
            _SCORE_RECOMPUTE_STATE["queued_while_running"] = int(_SCORE_RECOMPUTE_STATE.get("queued_while_running") or 0) + 1
        return {"scheduled": 0}
    background_tasks.add_task(_background_recompute_scores, None)
    return {"scheduled": 1}


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
