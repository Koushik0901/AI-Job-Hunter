from __future__ import annotations

import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi.encoders import jsonable_encoder
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

_THIS_DIR = Path(__file__).resolve().parent
_SRC_DIR = _THIS_DIR.parents[1]
_REPO_DIR = _SRC_DIR.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from db import init_db
from dashboard.backend.cache import DashboardCache, get_dashboard_cache
from dashboard.backend import repository
from dashboard.backend.job_description_pdf import build_job_description_filename, export_job_description_pdf
from enrich import run_enrichment_pipeline
from notify import notify_daily_briefing, telegram_message_hash
from dashboard.backend.schemas import (
    AddProfileSkillRequest,
    ActionQueueResponse,
    AppHealthResponse,
    CandidateProfile,
    CreateEventRequest,
    DeferActionRequest,
    ConversionResponse,
    DailyBriefing,
    JobDetail,
    JobDecisionRequest,
    JobEvent,
    JobAction,
    JobsListResponse,
    ManualJobCreateRequest,
    ManualJobCreateResponse,
    ProfileGapsResponse,
    ProfileInsightsResponse,
    ScoreRecomputeStatus,
    SourceQualityResponse,
    StatsResponse,
    SuppressedJob,
    SuppressJobRequest,
    TrackingPatchRequest,
)
from dashboard.backend.service import normalize_tracking_patch


def _load_dotenv(path: Path) -> None:
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

logger = logging.getLogger(__name__)

_CACHE_CONTROL_REVALIDATE = "private, no-cache"
_CACHE_CONTROL_NO_STORE = "no-store"
_TTL_JOBS_LIST = int((os.getenv("DASHBOARD_CACHE_TTL_JOBS_LIST") or "60").strip() or "60")
_TTL_JOB_DETAIL = int((os.getenv("DASHBOARD_CACHE_TTL_JOB_DETAIL") or "300").strip() or "300")
_TTL_EVENTS = int((os.getenv("DASHBOARD_CACHE_TTL_EVENTS") or "90").strip() or "90")
_TTL_STATS = int((os.getenv("DASHBOARD_CACHE_TTL_STATS") or "30").strip() or "30")
_TTL_ASSISTANT = int((os.getenv("DASHBOARD_CACHE_TTL_ASSISTANT") or "60").strip() or "60")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    cache = get_dashboard_cache()
    cache.startup()
    app.state.dashboard_cache = cache
    warm_thread: threading.Thread | None = None
    if cache.enabled:
        warm_thread = threading.Thread(target=_warm_dashboard_cache, name="dashboard-cache-warm", daemon=True)
        warm_thread.start()
    try:
        yield
    finally:
        cache.close()


app = FastAPI(title="AI Job Hunter Board API", version="4.0.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
        "http://localhost:4174",
        "http://127.0.0.1:4174",
        "http://host.docker.internal:4173",
        "http://host.docker.internal:4174",
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|host\.docker\.internal)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


def _cache() -> DashboardCache:
    return get_dashboard_cache()


def _resolve_db() -> tuple[str, str]:
    turso_url = (os.getenv("TURSO_URL") or "").strip()
    turso_token = (os.getenv("TURSO_AUTH_TOKEN") or "").strip()
    if turso_url:
        if not turso_token:
            raise RuntimeError("TURSO_AUTH_TOKEN is required when TURSO_URL is configured.")
        return turso_url, turso_token
    db_path = (os.getenv("DB_PATH") or str(_REPO_DIR / "jobs.db")).strip()
    return db_path, ""


def _conn() -> Any:
    db_url, db_token = _resolve_db()
    return init_db(db_url, db_token)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_timezone_name() -> str:
    return (
        str(
            os.getenv("JOB_HUNTER_TIMEZONE")
            or os.getenv("TIMEZONE")
            or os.getenv("TZ")
            or "America/Edmonton"
        )
        .strip()
        or "America/Edmonton"
    )


def _local_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(_local_timezone_name())
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _local_today() -> str:
    return datetime.now(_local_timezone()).date().isoformat()


def _set_score_recompute_state(**patch: Any) -> None:
    with _SCORE_RECOMPUTE_STATE_LOCK:
        _SCORE_RECOMPUTE_STATE.update(patch)


def _get_score_recompute_status() -> dict[str, Any]:
    with _SCORE_RECOMPUTE_STATE_LOCK:
        return dict(_SCORE_RECOMPUTE_STATE)


def _set_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = _CACHE_CONTROL_NO_STORE


def _cache_headers(etag: str, cache_status: str) -> dict[str, str]:
    return {
        "Cache-Control": _CACHE_CONTROL_REVALIDATE,
        "ETag": etag,
        "X-Cache": cache_status,
    }


def _request_etag_matches(request: Request, etag: str) -> bool:
    raw = request.headers.get("if-none-match", "")
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return "*" in values or etag in values


def _invalidate_job_collections() -> None:
    cache = _cache()
    cache.invalidate_jobs_lists()
    cache.invalidate_stats()
    cache.invalidate_for_assistant_change()


def _invalidate_job_detail(job_id: str) -> None:
    _cache().invalidate_job_detail(job_id)


def _invalidate_job_events(job_id: str) -> None:
    _cache().invalidate_job_events(job_id)


def _invalidate_profile_views() -> None:
    _cache().invalidate_for_profile_change()


def _invalidate_score_views() -> None:
    _cache().invalidate_for_score_recompute()


def _invalidate_workspace_views() -> None:
    _cache().invalidate_for_workspace_refresh()


def _invalidate_assistant_views() -> None:
    _cache().invalidate_for_assistant_change()


def _refresh_daily_briefing_best_effort(conn: Any, *, trigger_source: str = "interactive") -> None:
    try:
        repository.refresh_daily_briefing(conn, trigger_source=trigger_source)
    except Exception:
        logger.warning("Failed to refresh daily briefing.", exc_info=True)


def _env_or_default(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    cleaned = value.strip()
    return cleaned or default


def _background_finalize_manual_job(job_id: str, url: str) -> None:
    conn = _conn()
    try:
        try:
            repository.set_job_processing(
                conn,
                job_id,
                state="processing",
                step="processing",
                message="Running background processing.",
            )
        except Exception:
            logger.debug("Unable to mark job processing before background finalize.", exc_info=True)

        openrouter_api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
        job_url = url
        if not job_url:
            detail = repository.get_job_detail(conn, job_id)
            job_url = str(detail.get("url") or "") if detail else ""
        if openrouter_api_key:
            stub = repository.get_manual_job_stub(conn, job_id)
            if stub:
                run_enrichment_pipeline(
                    [
                        {
                            "url": str(stub.get("url") or url),
                            "company": str(stub.get("company") or ""),
                            "title": str(stub.get("title") or ""),
                            "location": str(stub.get("location") or ""),
                            "description": str(stub.get("description") or ""),
                        }
                    ],
                    conn,
                    openrouter_api_key,
                    _env_or_default("ENRICHMENT_MODEL", "openai/gpt-oss-120b"),
                    _env_or_default("DESCRIPTION_FORMAT_MODEL", "openai/gpt-oss-20b:paid"),
                    None,
                )
        if job_url:
            repository.recompute_match_scores(conn, urls=[job_url])
        repository.set_job_processing(
            conn,
            job_id,
            state="ready",
            step="complete",
            message="Background processing complete.",
            last_processed_at=_now_iso(),
            last_error=None,
        )
        _invalidate_job_collections()
        _invalidate_job_detail(job_id)
        _invalidate_assistant_views()
        _refresh_daily_briefing_best_effort(conn, trigger_source="interactive")
    except Exception as error:
        try:
            repository.set_job_processing(
                conn,
                job_id,
                state="failed",
                step="failed",
                message="Background processing failed.",
                last_error=str(error),
            )
        except Exception:
            logger.debug("Unable to mark job processing as failed.", exc_info=True)
        _invalidate_job_collections()
        _invalidate_job_detail(job_id)
        _invalidate_assistant_views()
        logger.warning("Failed to finalize manual job in background.", exc_info=True)
    finally:
        conn.close()


def _cached_json_response(
    *,
    request: Request,
    key: str,
    ttl_seconds: int,
    loader: Callable[[], Any],
) -> Response:
    cache = _cache()
    envelope = cache.get_cached_envelope(key)
    if envelope is not None:
        etag = str(envelope["etag"])
        if _request_etag_matches(request, etag):
            return Response(status_code=304, headers=_cache_headers(etag, "REVALIDATED"))
        return JSONResponse(content=envelope["body"], headers=_cache_headers(etag, "HIT"))

    with cache.singleflight(key):
        envelope = cache.get_cached_envelope(key)
        if envelope is not None:
            etag = str(envelope["etag"])
            if _request_etag_matches(request, etag):
                return Response(status_code=304, headers=_cache_headers(etag, "REVALIDATED"))
            return JSONResponse(content=envelope["body"], headers=_cache_headers(etag, "HIT"))

        payload = jsonable_encoder(loader())
        if cache.enabled:
            envelope = cache.set_cached_envelope(key, payload, ttl_seconds)
            etag = str(envelope["etag"])
            if _request_etag_matches(request, etag):
                return Response(status_code=304, headers=_cache_headers(etag, "REVALIDATED"))
            return JSONResponse(content=payload, headers=_cache_headers(etag, "MISS"))

        etag = cache.build_etag(payload)
        if _request_etag_matches(request, etag):
            return Response(status_code=304, headers=_cache_headers(etag, "REVALIDATED"))
        return JSONResponse(content=payload, headers=_cache_headers(etag, "BYPASS"))


def _load_jobs_payload(
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
) -> JobsListResponse:
    conn = _conn()
    try:
        items, total = repository.list_jobs(
            conn,
            status=status,
            q=q.strip() if q else None,
            ats=ats.strip() if ats else None,
            company=company.strip() if company else None,
            posted_after=posted_after,
            posted_before=posted_before,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return JobsListResponse(items=items, total=total)
    finally:
        conn.close()


def _load_job_detail_payload(job_id: str) -> JobDetail:
    conn = _conn()
    try:
        item = repository.get_job_detail(conn, job_id)
        if not item:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobDetail(**item)
    finally:
        conn.close()


def _load_job_events_payload(job_id: str) -> list[JobEvent]:
    conn = _conn()
    try:
        return [JobEvent(**event) for event in repository.list_events(conn, job_id)]
    finally:
        conn.close()


def _load_stats_payload() -> StatsResponse:
    conn = _conn()
    try:
        return StatsResponse(**repository.get_stats(conn))
    finally:
        conn.close()


def _load_daily_briefing_payload() -> DailyBriefing:
    conn = _conn()
    try:
        return DailyBriefing(**repository.get_or_create_daily_briefing(conn))
    finally:
        conn.close()


def _load_action_queue_payload() -> ActionQueueResponse:
    conn = _conn()
    try:
        return ActionQueueResponse(items=[JobAction(**item) for item in repository.refresh_action_queue(conn)])
    finally:
        conn.close()


def _load_actions_today_payload() -> ActionQueueResponse:
    conn = _conn()
    try:
        return ActionQueueResponse(items=[JobAction(**item) for item in repository.list_actions_today(conn)])
    finally:
        conn.close()


def _load_conversion_payload() -> ConversionResponse:
    conn = _conn()
    try:
        return ConversionResponse(**repository.get_conversion_metrics(conn))
    finally:
        conn.close()


def _load_source_quality_payload() -> SourceQualityResponse:
    conn = _conn()
    try:
        return SourceQualityResponse(**repository.get_source_quality(conn))
    finally:
        conn.close()


def _load_profile_gaps_payload() -> ProfileGapsResponse:
    conn = _conn()
    try:
        return ProfileGapsResponse(**repository.get_profile_gaps(conn))
    finally:
        conn.close()


def _load_profile_insights_payload() -> ProfileInsightsResponse:
    conn = _conn()
    try:
        return ProfileInsightsResponse(**repository.get_profile_insights(conn))
    finally:
        conn.close()


def _warm_dashboard_cache() -> None:
    cache = _cache()
    if not cache.enabled:
        return
    try:
        jobs_key = cache.jobs_list_key(
            {
                "status": None,
                "q": None,
                "ats": None,
                "company": None,
                "posted_after": None,
                "posted_before": None,
                "sort": "match_desc",
                "limit": 200,
                "offset": 0,
            }
        )
        if cache.get_cached_envelope(jobs_key) is None:
            cache.set_cached_envelope(
                jobs_key,
                jsonable_encoder(
                    _load_jobs_payload(
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
                ),
                _TTL_JOBS_LIST,
            )
        stats_key = cache.stats_key()
        if cache.get_cached_envelope(stats_key) is None:
            cache.set_cached_envelope(stats_key, jsonable_encoder(_load_stats_payload()), _TTL_STATS)
    except Exception:
        logger.debug("Dashboard cache warmup skipped after startup failure.", exc_info=True)


def _background_recompute_scores(urls: list[str] | None = None) -> None:
    if not _SCORE_RECOMPUTE_LOCK.acquire(blocking=False):
        _set_score_recompute_state(
            queued_while_running=int(_get_score_recompute_status().get("queued_while_running") or 0) + 1,
        )
        return
    started_at = _now_iso()
    started_perf = time.perf_counter()
    scope = "urls" if urls else "all"
    _set_score_recompute_state(
        running=True,
        last_started_at=started_at,
        last_finished_at=None,
        last_duration_ms=None,
        last_total=None,
        last_processed=0,
        last_scope=scope,
        last_error=None,
    )
    try:
        conn = _conn()
        try:
            progress_total = 0

            def _progress(processed: int, total: int) -> None:
                nonlocal progress_total
                progress_total = total
                _set_score_recompute_state(last_processed=processed, last_total=total)

            processed = repository.recompute_match_scores(conn, urls=urls, progress_callback=_progress)
        finally:
            conn.close()
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        _set_score_recompute_state(
            running=False,
            queued_while_running=0,
            last_finished_at=_now_iso(),
            last_duration_ms=duration_ms,
            last_total=progress_total or processed,
            last_processed=processed,
            last_error=None,
        )
        _invalidate_score_views()
    except Exception as error:
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        _set_score_recompute_state(
            running=False,
            queued_while_running=0,
            last_finished_at=_now_iso(),
            last_duration_ms=duration_ms,
            last_error=str(error),
        )
    finally:
        _SCORE_RECOMPUTE_LOCK.release()


@app.get("/api/health", response_model=AppHealthResponse)
def health(response: Response) -> AppHealthResponse:
    _set_no_store(response)
    redis_health = _cache().health()
    try:
        conn = _conn()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        message = "Database reachable."
        healthy = True
    except Exception as error:
        message = str(error)
        healthy = False
    return AppHealthResponse(
        status="ok" if healthy and (not redis_health.get("configured") or redis_health.get("healthy")) else "degraded",
        services={
            "database": {
                "configured": True,
                "healthy": healthy,
                "message": message,
            },
            "redis": redis_health,
        },
    )


@app.get("/api/jobs", response_model=JobsListResponse)
def list_jobs(
    request: Request,
    status: str | None = Query(default=None, pattern="^(not_applied|staging|applied|interviewing|offer|rejected)$"),
    q: str | None = Query(default=None),
    ats: str | None = Query(default=None),
    company: str | None = Query(default=None),
    posted_after: str | None = Query(default=None),
    posted_before: str | None = Query(default=None),
    sort: str = Query(default="match_desc", pattern="^(match_desc|posted_desc|updated_desc|company_asc)$"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Response:
    key = _cache().jobs_list_key(
        {
            "status": status,
            "q": q,
            "ats": ats,
            "company": company,
            "posted_after": posted_after,
            "posted_before": posted_before,
            "sort": sort,
            "limit": limit,
            "offset": offset,
        }
    )
    return _cached_json_response(
        request=request,
        key=key,
        ttl_seconds=_TTL_JOBS_LIST,
        loader=lambda: _load_jobs_payload(
            status=status,
            q=q,
            ats=ats,
            company=company,
            posted_after=posted_after,
            posted_before=posted_before,
            sort=sort,
            limit=limit,
            offset=offset,
        ),
    )


@app.post("/api/jobs/manual", response_model=ManualJobCreateResponse)
def create_manual_job(
    payload: ManualJobCreateRequest,
    response: Response,
    background_tasks: BackgroundTasks,
) -> ManualJobCreateResponse:
    _set_no_store(response)
    conn = _conn()
    try:
        try:
            item = repository.create_manual_job(conn, payload.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        duplicate_detected = bool(item.get("duplicate_detected"))
        if not duplicate_detected:
            _invalidate_job_collections()
            _invalidate_job_detail(str(item.get("id") or ""))
            _invalidate_assistant_views()
            background_tasks.add_task(
                _background_finalize_manual_job,
                str(item.get("id") or ""),
                str(item.get("url") or ""),
            )
        return ManualJobCreateResponse(**item)
    finally:
        conn.close()


@app.get("/api/profile", response_model=CandidateProfile)
def get_profile(response: Response) -> CandidateProfile:
    _set_no_store(response)
    conn = _conn()
    try:
        return CandidateProfile(**repository.get_profile(conn))
    finally:
        conn.close()


@app.put("/api/profile", response_model=CandidateProfile)
def put_profile(payload: CandidateProfile, response: Response) -> CandidateProfile:
    _set_no_store(response)
    conn = _conn()
    try:
        repository.save_profile(conn, payload.model_dump(exclude={"updated_at", "score_version"}))
        repository.bump_profile_score_version(conn)
        _invalidate_profile_views()
        _refresh_daily_briefing_best_effort(conn)
        return CandidateProfile(**repository.get_profile(conn))
    finally:
        conn.close()


@app.post("/api/profile/skills", response_model=CandidateProfile)
def add_profile_skill(payload: AddProfileSkillRequest, response: Response) -> CandidateProfile:
    _set_no_store(response)
    conn = _conn()
    try:
        profile = repository.get_profile(conn)
        skills = [str(item).strip() for item in profile.get("skills", []) if str(item).strip()]
        normalized = {item.casefold() for item in skills}
        incoming = payload.skill.strip()
        if incoming.casefold() not in normalized:
            skills.append(incoming)
            profile["skills"] = skills
            repository.save_profile(conn, profile)
            repository.bump_profile_score_version(conn)
            _invalidate_profile_views()
            _refresh_daily_briefing_best_effort(conn)
        return CandidateProfile(**repository.get_profile(conn))
    finally:
        conn.close()


@app.patch("/api/jobs/{job_id}/tracking", response_model=JobDetail)
def patch_tracking(job_id: str, payload: TrackingPatchRequest, response: Response) -> JobDetail:
    _set_no_store(response)
    patch = normalize_tracking_patch(payload.model_dump(exclude_unset=True))
    conn = _conn()
    try:
        try:
            repository.upsert_tracking(conn, job_id, patch)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        item = repository.get_job_detail(conn, job_id)
        if not item:
            raise HTTPException(status_code=404, detail="Job not found")
        _invalidate_job_collections()
        _invalidate_job_detail(job_id)
        _invalidate_assistant_views()
        _refresh_daily_briefing_best_effort(conn)
        return JobDetail(**item)
    finally:
        conn.close()


@app.get("/api/jobs/{job_id}/events", response_model=list[JobEvent])
def get_job_events(job_id: str, request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().job_events_key(job_id),
        ttl_seconds=_TTL_EVENTS,
        loader=lambda: _load_job_events_payload(job_id),
    )


@app.post("/api/jobs/{job_id}/events", response_model=JobEvent)
def post_event(job_id: str, payload: CreateEventRequest, response: Response) -> JobEvent:
    _set_no_store(response)
    conn = _conn()
    try:
        try:
            event = repository.create_event(conn, job_id, payload.model_dump())
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        _invalidate_job_events(job_id)
        _invalidate_job_collections()
        _invalidate_job_detail(job_id)
        _invalidate_assistant_views()
        _refresh_daily_briefing_best_effort(conn)
        return JobEvent(**event)
    finally:
        conn.close()


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int, response: Response) -> dict[str, int]:
    _set_no_store(response)
    conn = _conn()
    try:
        existing = repository.get_event(conn, event_id)
        changed = repository.delete_event(conn, event_id)
        if changed == 0:
            raise HTTPException(status_code=404, detail="Event not found")
        if existing:
            _invalidate_job_events(str(existing["job_id"]))
            _invalidate_job_collections()
            _invalidate_job_detail(str(existing["job_id"]))
            _invalidate_assistant_views()
            _refresh_daily_briefing_best_effort(conn)
        return {"deleted": changed}
    finally:
        conn.close()


@app.get("/api/jobs/{job_id}/description/pdf")
def export_job_description_pdf_route(job_id: str) -> Response:
    conn = _conn()
    try:
        job = repository.get_job_detail(conn, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
        formatted_description = str(enrichment.get("formatted_description") or "").strip()
        if not formatted_description:
            raise HTTPException(status_code=409, detail="Formatted job description is not available yet")
        try:
            pdf_bytes = export_job_description_pdf(job)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        filename = build_job_description_filename(job)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        conn.close()


@app.get("/api/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: str, request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().job_detail_key(job_id),
        ttl_seconds=_TTL_JOB_DETAIL,
        loader=lambda: _load_job_detail_payload(job_id),
    )


@app.post("/api/jobs/{job_id}/retry-processing", response_model=JobDetail)
def retry_job_processing(job_id: str, background_tasks: BackgroundTasks, response: Response) -> JobDetail:
    _set_no_store(response)
    conn = _conn()
    try:
        item = repository.get_job_detail(conn, job_id)
        if not item:
            raise HTTPException(status_code=404, detail="Job not found")
        processing = item.get("processing") if isinstance(item.get("processing"), dict) else {}
        if str(processing.get("state") or "ready") != "failed":
            return JobDetail(**item)
        repository.set_job_processing(
            conn,
            job_id,
            state="processing",
            step="retry",
            message="Retrying background processing.",
            increment_retry=True,
        )
        item = repository.get_job_detail(conn, job_id) or item
        background_tasks.add_task(
            _background_finalize_manual_job,
            job_id,
            str(item.get("url") or ""),
        )
        _invalidate_job_collections()
        _invalidate_job_detail(job_id)
        _invalidate_assistant_views()
        return JobDetail(**item)
    finally:
        conn.close()


@app.post("/api/jobs/{job_id}/decision")
def save_job_decision(job_id: str, payload: JobDecisionRequest, response: Response) -> dict[str, Any]:
    _set_no_store(response)
    conn = _conn()
    try:
        item = repository.get_job_detail(conn, job_id)
        if not item:
            raise HTTPException(status_code=404, detail="Job not found")
        decision = repository.save_job_decision(
            conn,
            job_id=job_id,
            recommendation=payload.recommendation,
            note=payload.note,
        )
        _invalidate_job_collections()
        _invalidate_job_detail(job_id)
        _invalidate_assistant_views()
        _refresh_daily_briefing_best_effort(conn)
        return decision
    finally:
        conn.close()


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str, response: Response) -> dict[str, int]:
    _set_no_store(response)
    conn = _conn()
    try:
        changed = repository.delete_job(conn, job_id)
        if changed == 0:
            raise HTTPException(status_code=404, detail="Job not found")
        _invalidate_job_collections()
        _invalidate_job_detail(job_id)
        _invalidate_job_events(job_id)
        _invalidate_assistant_views()
        _refresh_daily_briefing_best_effort(conn)
        return {"deleted": changed}
    finally:
        conn.close()


@app.post("/api/jobs/{job_id}/suppress")
def suppress_job(job_id: str, payload: SuppressJobRequest, response: Response) -> dict[str, int]:
    _set_no_store(response)
    conn = _conn()
    try:
        try:
            repository.suppress_job(conn, job_id=job_id, reason=payload.reason, created_by="ui")
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        _invalidate_job_collections()
        _invalidate_job_detail(job_id)
        _invalidate_assistant_views()
        _refresh_daily_briefing_best_effort(conn)
        return {"suppressed": 1}
    finally:
        conn.close()


@app.post("/api/jobs/{job_id}/unsuppress")
def unsuppress_job(job_id: str, response: Response) -> dict[str, int]:
    _set_no_store(response)
    conn = _conn()
    try:
        changed = repository.unsuppress_job(conn, job_id=job_id)
        _invalidate_job_collections()
        _invalidate_job_detail(job_id)
        _invalidate_assistant_views()
        _refresh_daily_briefing_best_effort(conn)
        return {"unsuppressed": changed}
    finally:
        conn.close()


@app.get("/api/suppressions", response_model=list[SuppressedJob])
def list_suppressions(response: Response, limit: int = Query(default=200, ge=1, le=1000)) -> list[SuppressedJob]:
    _set_no_store(response)
    conn = _conn()
    try:
        return [SuppressedJob(**item) for item in repository.list_active_suppressions(conn, limit=limit)]
    finally:
        conn.close()


@app.get("/api/meta/stats", response_model=StatsResponse)
def meta_stats(request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().stats_key(),
        ttl_seconds=_TTL_STATS,
        loader=_load_stats_payload,
    )


@app.get("/api/meta/daily-briefing/latest", response_model=DailyBriefing)
def get_daily_briefing_latest(request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().daily_briefing_key(_local_today()),
        ttl_seconds=_TTL_ASSISTANT,
        loader=_load_daily_briefing_payload,
    )


@app.post("/api/meta/daily-briefing/refresh", response_model=DailyBriefing)
def refresh_daily_briefing(response: Response) -> DailyBriefing:
    _set_no_store(response)
    conn = _conn()
    try:
        briefing = DailyBriefing(**repository.refresh_daily_briefing(conn, trigger_source="scheduled"))
        _invalidate_assistant_views()
        return briefing
    finally:
        conn.close()


@app.post("/api/meta/daily-briefing/send", response_model=DailyBriefing)
def send_daily_briefing(response: Response) -> DailyBriefing:
    _set_no_store(response)
    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        raise HTTPException(status_code=503, detail="Telegram not configured")
    conn = _conn()
    try:
        briefing = repository.get_or_create_daily_briefing(conn)
        if briefing.get("telegram_sent_at"):
            return DailyBriefing(**briefing)
        chunks = notify_daily_briefing(briefing, token, chat_id, console=None)
        message_hash = telegram_message_hash(chunks)
        updated = repository.mark_daily_briefing_sent(
            conn,
            brief_date=str(briefing.get("brief_date") or ""),
            message_hash=message_hash,
        )
        _invalidate_assistant_views()
        return DailyBriefing(**(updated or briefing))
    finally:
        conn.close()


@app.get("/api/meta/action-queue", response_model=ActionQueueResponse)
def get_action_queue(request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().action_queue_key(),
        ttl_seconds=_TTL_ASSISTANT,
        loader=_load_action_queue_payload,
    )


@app.get("/api/actions/today", response_model=ActionQueueResponse)
def get_actions_today(request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().actions_today_key(),
        ttl_seconds=_TTL_ASSISTANT,
        loader=_load_actions_today_payload,
    )


@app.post("/api/actions/{action_id}/complete", response_model=JobAction)
def complete_action(action_id: int, response: Response) -> JobAction:
    _set_no_store(response)
    conn = _conn()
    try:
        item = repository.complete_action(conn, action_id)
        if not item:
            raise HTTPException(status_code=404, detail="Action not found")
        job_id = str(item.get("job_id") or "")
        if job_id:
            _invalidate_job_collections()
            _invalidate_job_detail(job_id)
            _invalidate_job_events(job_id)
        _invalidate_assistant_views()
        _refresh_daily_briefing_best_effort(conn)
        return JobAction(**item)
    finally:
        conn.close()


@app.post("/api/actions/{action_id}/defer", response_model=JobAction)
def defer_action(action_id: int, payload: DeferActionRequest, response: Response) -> JobAction:
    _set_no_store(response)
    conn = _conn()
    try:
        item = repository.defer_action(conn, action_id, payload.days)
        if not item:
            raise HTTPException(status_code=404, detail="Action not found")
        job_id = str(item.get("job_id") or "")
        if job_id:
            _invalidate_job_collections()
            _invalidate_job_detail(job_id)
        _invalidate_assistant_views()
        _refresh_daily_briefing_best_effort(conn)
        return JobAction(**item)
    finally:
        conn.close()


@app.get("/api/meta/conversion", response_model=ConversionResponse)
def get_conversion(request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().conversion_key(),
        ttl_seconds=_TTL_ASSISTANT,
        loader=_load_conversion_payload,
    )


@app.get("/api/meta/source-quality", response_model=SourceQualityResponse)
def get_source_quality(request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().source_quality_key(),
        ttl_seconds=_TTL_ASSISTANT,
        loader=_load_source_quality_payload,
    )


@app.get("/api/meta/profile-gaps", response_model=ProfileGapsResponse)
def get_profile_gaps(request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().profile_gaps_key(),
        ttl_seconds=_TTL_ASSISTANT,
        loader=_load_profile_gaps_payload,
    )


@app.get("/api/profile/insights", response_model=ProfileInsightsResponse)
def get_profile_insights(request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().profile_insights_key(),
        ttl_seconds=_TTL_ASSISTANT,
        loader=_load_profile_insights_payload,
    )


@app.get("/api/meta/scores/recompute-status", response_model=ScoreRecomputeStatus)
def score_recompute_status(response: Response) -> ScoreRecomputeStatus:
    _set_no_store(response)
    return ScoreRecomputeStatus(**_get_score_recompute_status())


@app.post("/api/meta/scores/recompute")
def trigger_score_recompute(background_tasks: BackgroundTasks, response: Response) -> dict[str, int]:
    _set_no_store(response)
    if bool(_get_score_recompute_status().get("running")):
        _set_score_recompute_state(
            queued_while_running=int(_get_score_recompute_status().get("queued_while_running") or 0) + 1,
        )
        return {"scheduled": 0}
    background_tasks.add_task(_background_recompute_scores, None)
    return {"scheduled": 1}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "dashboard.backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        app_dir=str(_SRC_DIR),
    )
