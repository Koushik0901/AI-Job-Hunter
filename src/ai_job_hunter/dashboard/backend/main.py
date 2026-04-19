from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi.encoders import jsonable_encoder
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from ai_job_hunter.db import get_workspace_operation, init_db, list_workspace_operations
from ai_job_hunter.match_score import SKILL_ALIASES
from ai_job_hunter.dashboard.backend.cache import DashboardCache, get_dashboard_cache
from ai_job_hunter.dashboard.backend import repository
from ai_job_hunter.dashboard.backend.job_description_pdf import (
    build_job_description_filename,
    export_job_description_pdf,
)
from ai_job_hunter.enrich import run_enrichment_pipeline
from ai_job_hunter.notify import notify_daily_briefing, telegram_message_hash
from ai_job_hunter.dashboard.backend.schemas import (
    AddProfileSkillRequest,
    ActionQueueResponse,
    AgentChatRequest,
    AgentChatResponse,
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
    AddToQueueRequest,
    ArtifactsByUrlResponse,
    BaseDocument,
    BootstrapResponse,
    GenerateArtifactRequest,
    JobArtifact,
    QueueItem,
    ReorderQueueRequest,
    UpdateArtifactRequest,
    UpdateQueueItemRequest,
    WorkspaceOperation,
)
from ai_job_hunter.dashboard.backend.agent_gateway import handle_agent_chat
from ai_job_hunter.dashboard.backend import artifacts as artifact_svc
from ai_job_hunter.dashboard.backend.task_queue import get_dashboard_task_queue
from ai_job_hunter.dashboard.backend.core_actions import enqueue_artifact_generation, enqueue_operation
from ai_job_hunter.dashboard.backend.utils import (
    load_dotenv,
    local_timezone,
    local_today,
    now_iso,
    resolve_db_config,
)
from ai_job_hunter.env_utils import env_or_default as _env_or_default

load_dotenv()


def _resolve_db() -> tuple[str, str]:
    return resolve_db_config()


def _conn() -> Any:
    db_url, db_token = _resolve_db()
    return init_db(db_url, db_token)


def _with_conn(fn: Callable[[Any], Any]) -> Any:
    conn = _conn()
    try:
        return fn(conn)
    finally:
        conn.close()


_now_iso = now_iso
_local_today = local_today
_local_timezone = local_timezone

logger = logging.getLogger(__name__)

_CACHE_CONTROL_REVALIDATE = "private, max-age=60, stale-while-revalidate=30"
_CACHE_CONTROL_NO_STORE = "no-store"
_TTL_SHORT = int((os.getenv("DASHBOARD_CACHE_TTL_SHORT") or "60").strip() or "60")
_TTL_LONG = int((os.getenv("DASHBOARD_CACHE_TTL_LONG") or "3600").strip() or "3600")
_TTL_JOBS_LIST = _TTL_SHORT
_TTL_JOB_DETAIL = _TTL_SHORT
_TTL_EVENTS = _TTL_SHORT
_TTL_STATS = _TTL_SHORT
_TTL_ASSISTANT = _TTL_SHORT
_TTL_PROFILE = _TTL_SHORT
_TTL_META = _TTL_LONG


@asynccontextmanager
async def _lifespan(app: FastAPI):
    cache = get_dashboard_cache()
    task_queue = get_dashboard_task_queue()
    cache.startup()
    task_queue.startup()
    app.state.dashboard_cache = cache
    app.state.dashboard_task_queue = task_queue
    warm_thread: threading.Thread | None = None
    if cache.enabled and not os.getenv("PYTEST_CURRENT_TEST"):
        warm_thread = threading.Thread(
            target=_warm_dashboard_cache, name="dashboard-cache-warm", daemon=True
        )
        warm_thread.start()
    try:
        yield
    finally:
        task_queue.close()
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
    allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1|host\.docker\.internal)(:\d+)?|chrome-extension://.*)$",
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


def _set_score_recompute_state(**patch: Any) -> None:

    with _SCORE_RECOMPUTE_STATE_LOCK:
        _SCORE_RECOMPUTE_STATE.update(patch)


def _get_score_recompute_status() -> dict[str, Any]:
    with _SCORE_RECOMPUTE_STATE_LOCK:
        return dict(_SCORE_RECOMPUTE_STATE)


def _set_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = _CACHE_CONTROL_NO_STORE


def _cache_headers(
    etag: str,
    cache_status: str,
    *,
    cache_layer: str | None = None,
    duration_ms: float | None = None,
) -> dict[str, str]:
    headers = {
        "Cache-Control": _CACHE_CONTROL_REVALIDATE,
        "ETag": etag,
        "X-Cache": cache_status,
    }
    if cache_layer:
        headers["X-Cache-Layer"] = cache_layer
    if duration_ms is not None:
        headers["Server-Timing"] = f'app;dur={duration_ms:.1f}'
    return headers


def _request_etag_matches(request: Request, etag: str) -> bool:
    raw = request.headers.get("if-none-match", "")
    values = [item.strip() for item in raw.split(",") if item.strip()]
    return "*" in values or etag in values


def _invalidate_job_collections() -> None:
    cache = _cache()
    cache.invalidate_jobs_lists()
    cache.invalidate_stats()
    cache.invalidate_for_assistant_change()
    cache.publish_dashboard_event("refresh", "jobs")


def _invalidate_job_detail(job_id: str) -> None:
    _cache().invalidate_job_detail(job_id)


def _invalidate_job_events(job_id: str) -> None:
    _cache().invalidate_job_events(job_id)


def _invalidate_profile_views() -> None:
    cache = _cache()
    cache.invalidate_for_profile_change()
    cache.publish_dashboard_event("refresh", "profile")
    _schedule_snapshot_refresh()


def _invalidate_score_views() -> None:
    cache = _cache()
    cache.invalidate_for_score_recompute()
    cache.publish_dashboard_event("refresh", "scores")
    _schedule_snapshot_refresh()


def _invalidate_workspace_views() -> None:
    cache = _cache()
    cache.invalidate_for_workspace_refresh()
    cache.publish_dashboard_event("refresh", "workspace")
    _schedule_snapshot_refresh()


def _invalidate_assistant_views() -> None:
    cache = _cache()
    cache.invalidate_for_assistant_change()
    cache.publish_dashboard_event("refresh", "assistant")


def _schedule_snapshot_refresh(job_ids: list[str] | None = None) -> None:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    normalized_ids = [
        str(job_id).strip() for job_id in (job_ids or []) if str(job_id).strip()
    ]
    enqueue_operation("dashboard_snapshot_refresh", {"job_ids": normalized_ids})


def _refresh_daily_briefing_best_effort(
    conn: Any, *, trigger_source: str = "interactive"
) -> None:
    try:
        repository.refresh_daily_briefing(conn, trigger_source=trigger_source)
    except Exception:
        logger.warning("Failed to refresh daily briefing.", exc_info=True)


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
            logger.debug(
                "Unable to mark job processing before background finalize.",
                exc_info=True,
            )

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
                    _env_or_default(
                        "DESCRIPTION_FORMAT_MODEL", "openai/gpt-oss-20b:paid"
                    ),
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
            last_processed_at=now_iso(),
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


def _envelope_response(
    request: Request,
    *,
    body: Any,
    etag: str,
    hit_label: str,
    cache_layer: str,
    started: float,
) -> Response:
    duration_ms = (time.perf_counter() - started) * 1000
    if _request_etag_matches(request, etag):
        return Response(
            status_code=304,
            headers=_cache_headers(etag, "REVALIDATED", cache_layer=cache_layer, duration_ms=duration_ms),
        )
    return JSONResponse(
        content=body,
        headers=_cache_headers(etag, hit_label, cache_layer=cache_layer, duration_ms=duration_ms),
    )


def _cached_json_response(
    *,
    request: Request,
    key: str,
    ttl_seconds: int,
    loader: Callable[[], Any],
) -> Response:
    started = time.perf_counter()
    cache = _cache()
    envelope = cache.get_cached_envelope(key)
    if envelope is not None:
        return _envelope_response(
            request,
            body=envelope["body"],
            etag=str(envelope["etag"]),
            hit_label="HIT",
            cache_layer=str(envelope.get("_cache_source") or "CACHE"),
            started=started,
        )

    payload = jsonable_encoder(loader())
    if cache.enabled:
        envelope = cache.set_cached_envelope(key, payload, ttl_seconds)
        return _envelope_response(
            request,
            body=payload,
            etag=str(envelope["etag"]),
            hit_label="MISS",
            cache_layer="WRITE",
            started=started,
        )

    return _envelope_response(
        request,
        body=payload,
        etag=cache.build_etag(payload),
        hit_label="BYPASS",
        cache_layer="BYPASS",
        started=started,
    )


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
    def load(conn: Any) -> JobsListResponse:
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

    return _with_conn(load)


def _load_job_detail_payload(job_id: str) -> JobDetail:
    def load(conn: Any) -> JobDetail:
        item = repository.get_job_detail(conn, job_id)
        if not item:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobDetail(**item)

    return _with_conn(load)


def _load_job_events_payload(job_id: str) -> list[JobEvent]:
    return _with_conn(
        lambda conn: [JobEvent(**event) for event in repository.list_events(conn, job_id)]
    )


def _load_stats_payload() -> StatsResponse:
    return _with_conn(lambda conn: StatsResponse(**repository.get_stats(conn)))


def _load_daily_briefing_payload() -> DailyBriefing:
    return _with_conn(
        lambda conn: DailyBriefing(**repository.get_or_create_daily_briefing(conn))
    )


def _load_action_queue_payload() -> ActionQueueResponse:
    return _with_conn(
        lambda conn: ActionQueueResponse(
            items=[JobAction(**item) for item in repository.refresh_action_queue(conn)]
        )
    )


def _load_actions_today_payload() -> ActionQueueResponse:
    return _with_conn(
        lambda conn: ActionQueueResponse(
            items=[JobAction(**item) for item in repository.list_actions_today(conn)]
        )
    )


def _load_conversion_payload() -> ConversionResponse:
    return _with_conn(
        lambda conn: ConversionResponse(**repository.get_conversion_metrics(conn))
    )


def _load_source_quality_payload() -> SourceQualityResponse:
    return _with_conn(
        lambda conn: SourceQualityResponse(**repository.get_source_quality(conn))
    )


def _load_profile_gaps_payload() -> ProfileGapsResponse:
    return _with_conn(
        lambda conn: ProfileGapsResponse(**repository.get_profile_gaps(conn))
    )


def _load_profile_insights_payload() -> ProfileInsightsResponse:
    return _with_conn(
        lambda conn: ProfileInsightsResponse(**repository.get_profile_insights(conn))
    )


def _load_profile_payload() -> CandidateProfile:
    return _with_conn(
        lambda conn: CandidateProfile(**repository.get_profile(conn))
    )


def _load_skill_aliases_payload() -> dict[str, str]:
    return SKILL_ALIASES


def _load_bootstrap_payload() -> BootstrapResponse:
    conn = _conn()
    try:
        profile = repository.get_profile(conn)
        stats = repository.get_stats(conn)
        action_queue = repository.refresh_action_queue(conn)[:8]
        profile_version = int(profile.get("score_version") or 1)
        snapshot_rows = conn.execute(
            """
            SELECT payload_json
            FROM job_dashboard_snapshots
            WHERE profile_version = ?
              AND status = 'not_applied'
            ORDER BY COALESCE(match_score, -1) DESC, posted DESC
            LIMIT 12
            """,
            (profile_version,),
        ).fetchall()
        snapshot_ready = bool(snapshot_rows)
        if not snapshot_ready:
            _schedule_snapshot_refresh()
        recommended_jobs: list[dict[str, Any]] = []
        for row in snapshot_rows:
            try:
                payload = json.loads(row[0] or "{}")
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict):
                recommended_jobs.append(payload)
        return BootstrapResponse(
            profile=CandidateProfile(**profile),
            stats=StatsResponse(**stats),
            recommended_jobs=[repository_item for repository_item in recommended_jobs],
            action_queue=[JobAction(**item) for item in action_queue],
            cache={
                "profile_version": profile_version,
                "snapshot_ready": snapshot_ready,
                "generated_at": now_iso(),
            },
        )
    finally:
        conn.close()


def _warm_dashboard_cache() -> None:
    cache = _cache()
    if not cache.enabled:
        return
    try:
        bootstrap_key = cache.bootstrap_key()
        if cache.get_cached_envelope(bootstrap_key) is None:
            cache.set_cached_envelope(
                bootstrap_key,
                jsonable_encoder(_load_bootstrap_payload()),
                _TTL_ASSISTANT,
            )
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
        warm_conn = _conn()
        try:
            snapshot_ready = bool(
                warm_conn.execute(
                    "SELECT 1 FROM job_dashboard_snapshots LIMIT 1"
                ).fetchone()
            )
        finally:
            warm_conn.close()
        if snapshot_ready and cache.get_cached_envelope(jobs_key) is None:
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
            cache.set_cached_envelope(
                stats_key, jsonable_encoder(_load_stats_payload()), _TTL_STATS
            )
    except Exception:
        logger.debug(
            "Dashboard cache warmup skipped after startup failure.", exc_info=True
        )


def _background_recompute_scores(urls: list[str] | None = None) -> None:
    if not _SCORE_RECOMPUTE_LOCK.acquire(blocking=False):
        _set_score_recompute_state(
            queued_while_running=int(
                _get_score_recompute_status().get("queued_while_running") or 0
            )
            + 1,
        )
        return
    started_at = now_iso()
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

            processed = repository.recompute_match_scores(
                conn, urls=urls, progress_callback=_progress
            )
        finally:
            conn.close()
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        _set_score_recompute_state(
            running=False,
            queued_while_running=0,
            last_finished_at=now_iso(),
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
            last_finished_at=now_iso(),
            last_duration_ms=duration_ms,
            last_error=str(error),
        )
    finally:
        _SCORE_RECOMPUTE_LOCK.release()


@app.get("/api/health", response_model=AppHealthResponse)
def health(response: Response) -> AppHealthResponse:
    _set_no_store(response)
    redis_health = _cache().health()
    task_queue_health = {
        "configured": bool(os.getenv("REDIS_URL", "").strip()),
        "healthy": bool(get_dashboard_task_queue().enabled),
        "message": "Task queue ready."
        if get_dashboard_task_queue().enabled
        else "Task queue unavailable; local fallback only.",
    }
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
        status="ok"
        if healthy
        and (not redis_health.get("configured") or redis_health.get("healthy"))
        else "degraded",
        services={
            "database": {
                "configured": True,
                "healthy": healthy,
                "message": message,
            },
            "redis": redis_health,
            "task_queue": task_queue_health,
        },
    )


@app.get("/api/jobs", response_model=JobsListResponse)
def list_jobs(
    request: Request,
    status: str | None = Query(
        default=None,
        pattern="^(not_applied|staging|applied|interviewing|offer|rejected)$",
    ),
    q: str | None = Query(default=None),
    ats: str | None = Query(default=None),
    company: str | None = Query(default=None),
    posted_after: str | None = Query(default=None),
    posted_before: str | None = Query(default=None),
    sort: str = Query(
        default="match_desc",
        pattern="^(match_desc|posted_desc|updated_desc|company_asc)$",
    ),
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


@app.get("/api/bootstrap", response_model=BootstrapResponse)
def get_bootstrap(request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().bootstrap_key(),
        ttl_seconds=_TTL_ASSISTANT,
        loader=_load_bootstrap_payload,
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
def get_profile(request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().profile_key(),
        ttl_seconds=_TTL_PROFILE,
        loader=_load_profile_payload,
    )


@app.put("/api/profile", response_model=CandidateProfile)
def put_profile(payload: CandidateProfile, response: Response) -> CandidateProfile:
    _set_no_store(response)
    conn = _conn()
    try:
        repository.save_profile(
            conn, payload.model_dump(exclude={"updated_at", "score_version"})
        )
        repository.bump_profile_score_version(conn)
        _invalidate_profile_views()
        _refresh_daily_briefing_best_effort(conn)
        return CandidateProfile(**repository.get_profile(conn))
    finally:
        conn.close()


@app.post("/api/profile/skills", response_model=CandidateProfile)
def add_profile_skill(
    payload: AddProfileSkillRequest, response: Response
) -> CandidateProfile:
    _set_no_store(response)
    conn = _conn()
    try:
        profile = repository.get_profile(conn)
        skills = [
            str(item).strip() for item in profile.get("skills", []) if str(item).strip()
        ]
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


@app.get("/api/profile/autofill-export")
def get_autofill_export(response: Response) -> dict:
    _set_no_store(response)
    conn = _conn()
    try:
        profile = repository.get_profile(conn)
        full_name = str(profile.get("full_name") or "")
        name_parts = full_name.strip().split(None, 1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else ""
        education = profile.get("education") or []
        degree = ""
        degree_field = ""
        if education:
            degree = str(education[0].get("degree") or "")
            degree_field = str(education[0].get("field") or "")
        return {
            "first_name": first_name or None,
            "last_name": last_name or None,
            "full_name": full_name or None,
            "email": profile.get("email"),
            "phone": profile.get("phone"),
            "linkedin_url": profile.get("linkedin_url"),
            "portfolio_url": profile.get("portfolio_url"),
            "city": profile.get("city"),
            "country": profile.get("country"),
            "years_experience": profile.get("years_experience"),
            "degree": degree or None,
            "degree_field": degree_field or None,
            "requires_visa_sponsorship": profile.get(
                "requires_visa_sponsorship", False
            ),
        }
    finally:
        conn.close()


@app.post("/api/agent/chat", response_model=AgentChatResponse)
def agent_chat_endpoint(
    payload: AgentChatRequest, response: Response
) -> AgentChatResponse:
    _set_no_store(response)
    conn = _conn()
    try:
        messages = [
            {"role": msg.role, "content": msg.content} for msg in payload.messages
        ]
        result = handle_agent_chat(
            messages,
            conn,
            skill_invocation=payload.skill_invocation.model_dump()
            if payload.skill_invocation
            else None,
        )
        return AgentChatResponse(
            reply=result["reply"],
            context_snapshot=result.get("context_snapshot", ""),
            response_mode=str(result.get("response_mode") or "llm"),
            output_kind=str(result.get("output_kind") or "none"),
            output_payload=result.get("output_payload"),
            operation_id=str(result.get("operation_id") or "") or None,
        )
    finally:
        conn.close()


@app.patch("/api/jobs/{job_id}/tracking", response_model=JobDetail)
def patch_tracking(
    job_id: str, payload: TrackingPatchRequest, response: Response
) -> JobDetail:
    _set_no_store(response)
    patch = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if patch.get("status") == "applied" and not patch.get("applied_at"):
        patch["applied_at"] = datetime.now(timezone.utc).date().isoformat()
    if "pinned" in patch:
        patch["pinned"] = bool(patch["pinned"])
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
def post_event(
    job_id: str, payload: CreateEventRequest, response: Response
) -> JobEvent:
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
        enrichment = (
            job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
        )
        formatted_description = str(
            enrichment.get("formatted_description") or ""
        ).strip()
        if not formatted_description:
            raise HTTPException(
                status_code=409, detail="Formatted job description is not available yet"
            )
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
def retry_job_processing(
    job_id: str, background_tasks: BackgroundTasks, response: Response
) -> JobDetail:
    _set_no_store(response)
    conn = _conn()
    try:
        item = repository.get_job_detail(conn, job_id)
        if not item:
            raise HTTPException(status_code=404, detail="Job not found")
        processing = (
            item.get("processing") if isinstance(item.get("processing"), dict) else {}
        )
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
def save_job_decision(
    job_id: str, payload: JobDecisionRequest, response: Response
) -> dict[str, Any]:
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
def suppress_job(
    job_id: str, payload: SuppressJobRequest, response: Response
) -> dict[str, int]:
    _set_no_store(response)
    conn = _conn()
    try:
        try:
            repository.suppress_job(
                conn, job_id=job_id, reason=payload.reason, created_by="ui"
            )
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
def list_suppressions(
    response: Response, limit: int = Query(default=200, ge=1, le=1000)
) -> list[SuppressedJob]:
    _set_no_store(response)
    conn = _conn()
    try:
        return [
            SuppressedJob(**item)
            for item in repository.list_active_suppressions(conn, limit=limit)
        ]
    finally:
        conn.close()


@app.get("/api/meta/skill-aliases")
def get_skill_aliases(request: Request) -> Response:
    return _cached_json_response(
        request=request,
        key=_cache().skill_aliases_key(),
        ttl_seconds=_TTL_META,
        loader=_load_skill_aliases_payload,
    )


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
        key=_cache().daily_briefing_key(local_today()),
        ttl_seconds=_TTL_ASSISTANT,
        loader=_load_daily_briefing_payload,
    )


@app.post("/api/meta/daily-briefing/refresh", response_model=DailyBriefing)
def refresh_daily_briefing(response: Response) -> DailyBriefing:
    _set_no_store(response)
    conn = _conn()
    try:
        briefing = DailyBriefing(
            **repository.refresh_daily_briefing(conn, trigger_source="scheduled")
        )
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
def defer_action(
    action_id: int, payload: DeferActionRequest, response: Response
) -> JobAction:
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
def trigger_score_recompute(
    background_tasks: BackgroundTasks, response: Response
) -> dict[str, int]:
    _set_no_store(response)
    if bool(_get_score_recompute_status().get("running")):
        _set_score_recompute_state(
            queued_while_running=int(
                _get_score_recompute_status().get("queued_while_running") or 0
            )
            + 1,
        )
        return {"scheduled": 0}
    background_tasks.add_task(_background_recompute_scores, None)
    return {"scheduled": 1}


@app.get("/api/operations", response_model=list[WorkspaceOperation])
def get_operations(
    response: Response, limit: int = Query(default=20, ge=1, le=100)
) -> list[WorkspaceOperation]:
    _set_no_store(response)
    conn = _conn()
    try:
        items = list_workspace_operations(conn, limit=limit)
        return [WorkspaceOperation(**item) for item in items]
    finally:
        conn.close()


@app.get("/api/operations/{operation_id}", response_model=WorkspaceOperation)
def get_operation(operation_id: str, response: Response) -> WorkspaceOperation:
    _set_no_store(response)
    conn = _conn()
    try:
        item = get_workspace_operation(conn, operation_id)
        if not item:
            raise HTTPException(status_code=404, detail="Operation not found")
        return WorkspaceOperation(**item)
    finally:
        conn.close()


_SSE_HEADERS = {
    "Cache-Control": "no-store",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse_response(generator: Any) -> StreamingResponse:
    return StreamingResponse(generator, media_type="text/event-stream", headers=_SSE_HEADERS)


@app.get("/api/events/stream")
async def stream_dashboard_events(
    request: Request, once: bool = Query(default=False)
) -> StreamingResponse:
    async def event_stream():
        cache = _cache()
        initial = cache.get_dashboard_event() or {
            "id": "ready",
            "event": "ready",
            "scope": "system",
            "at": now_iso(),
        }
        last_event_id = str(initial.get("id") or "")
        yield f"data: {json.dumps(initial, ensure_ascii=True)}\n\n"
        if once:
            return
        while True:
            if await request.is_disconnected():
                return
            event = cache.get_dashboard_event()
            event_id = str(event.get("id") or "") if isinstance(event, dict) else ""
            if event and event_id and event_id != last_event_id:
                last_event_id = event_id
                yield f"data: {json.dumps(event, ensure_ascii=True)}\n\n"
            await asyncio.sleep(1)

    return _sse_response(event_stream())


@app.get("/api/operations/{operation_id}/events")
async def stream_operation(operation_id: str, request: Request) -> StreamingResponse:
    async def event_stream():
        last_payload = ""
        while True:
            conn = _conn()
            try:
                item = get_workspace_operation(conn, operation_id)
            finally:
                conn.close()
            if item is None:
                yield "event: error\ndata: {}\n\n"
                return
            payload = json.dumps(item, ensure_ascii=True)
            if payload != last_payload:
                last_payload = payload
                yield f"data: {payload}\n\n"
            if str(item.get("status") or "") in {"completed", "failed"}:
                return
            if await request.is_disconnected():
                return
            await asyncio.sleep(1)

    return _sse_response(event_stream())


# ---------------------------------------------------------------------------
# Base document endpoints
# ---------------------------------------------------------------------------


@app.post("/api/profile/documents", response_model=BaseDocument)
async def upload_base_document(
    file: UploadFile = File(...),
    doc_type: str = Form(...),
) -> BaseDocument:
    if doc_type not in ("resume", "cover_letter"):
        raise HTTPException(
            status_code=400, detail="doc_type must be 'resume' or 'cover_letter'"
        )
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    try:
        content_md = artifact_svc.parse_uploaded_file(
            file.filename or "upload", content_bytes, file.content_type or ""
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    with _conn() as conn:
        doc_id = artifact_svc.save_base_document(
            doc_type,
            file.filename or "upload",
            content_md,
            content_bytes,
            file.content_type,
            conn,
        )
        doc = artifact_svc.get_base_document(doc_id, conn)
    return BaseDocument(**doc)


@app.get("/api/profile/documents", response_model=list[BaseDocument])
def list_base_documents(response: Response) -> list[BaseDocument]:
    _set_no_store(response)
    with _conn() as conn:
        docs = artifact_svc.list_base_documents(conn)
    return [BaseDocument(**d) for d in docs]


@app.delete("/api/profile/documents/{doc_id}", status_code=204)
def delete_base_document(doc_id: int) -> None:
    with _conn() as conn:
        artifact_svc.delete_base_document(doc_id, conn)


@app.patch("/api/profile/documents/{doc_id}/default", response_model=BaseDocument)
def set_default_base_document(doc_id: int) -> BaseDocument:
    with _conn() as conn:
        doc = artifact_svc.get_base_document(doc_id, conn)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        artifact_svc.set_default_base_document(doc_id, doc["doc_type"], conn)
        doc = artifact_svc.get_base_document(doc_id, conn)
    return BaseDocument(**doc)


# ---------------------------------------------------------------------------
# Application queue endpoints
# ---------------------------------------------------------------------------


@app.get("/api/queue", response_model=list[QueueItem])
def get_queue(response: Response) -> list[QueueItem]:
    _set_no_store(response)
    with _conn() as conn:
        items = artifact_svc.list_queue(conn)
    return [QueueItem(**i) for i in items]


@app.post("/api/queue", response_model=QueueItem)
def add_to_queue(body: AddToQueueRequest, response: Response) -> QueueItem:
    _set_no_store(response)
    with _conn() as conn:
        # Verify job exists
        row = conn.execute(
            "SELECT id FROM jobs WHERE id = ?", (body.job_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        item = artifact_svc.add_to_queue(body.job_id, conn)
    _cache().publish_dashboard_event(
        "refresh",
        "queue",
        job_id=body.job_id,
    )
    return QueueItem(**item)


@app.delete("/api/queue/{queue_id}", status_code=204)
def remove_from_queue(queue_id: int) -> None:
    job_id = ""
    with _conn() as conn:
        existing = conn.execute(
            "SELECT job_id FROM application_queue WHERE id = ?", (queue_id,)
        ).fetchone()
        if existing:
            job_id = str(existing[0] or "")
        artifact_svc.remove_from_queue(queue_id, conn)
    _cache().publish_dashboard_event("refresh", "queue", job_id=job_id or None)


@app.patch("/api/queue/{queue_id}", response_model=QueueItem)
def update_queue_item(queue_id: int, body: UpdateQueueItemRequest) -> QueueItem:
    with _conn() as conn:
        item = artifact_svc.update_queue_item(queue_id, body.status, conn)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    _cache().publish_dashboard_event(
        "refresh",
        "queue",
        job_id=str(item.get("job_id") or ""),
        status=body.status,
    )
    return QueueItem(**item)


@app.post("/api/queue/reorder", status_code=204)
def reorder_queue(body: ReorderQueueRequest) -> None:
    with _conn() as conn:
        artifact_svc.reorder_queue(body.ids, conn)
    _cache().publish_dashboard_event("refresh", "queue")


# ---------------------------------------------------------------------------
# Job artifact endpoints
# ---------------------------------------------------------------------------


@app.get("/api/jobs/{job_id}/artifacts", response_model=list[JobArtifact])
def get_job_artifacts(job_id: str, response: Response) -> list[JobArtifact]:
    _set_no_store(response)
    with _conn() as conn:
        arts = artifact_svc.get_artifacts_for_job(job_id, conn)
    return [JobArtifact(**a) for a in arts]


@app.post("/api/jobs/{job_id}/artifacts/resume", response_model=WorkspaceOperation)
def generate_resume_artifact(
    job_id: str, body: GenerateArtifactRequest, response: Response
) -> WorkspaceOperation:
    _set_no_store(response)
    with _conn() as conn:
        row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
    operation = enqueue_artifact_generation(
        job_id,
        "resume",
        body.base_doc_id,
    )
    return WorkspaceOperation(**operation)


@app.post("/api/jobs/{job_id}/artifacts/cover-letter", response_model=WorkspaceOperation)
def generate_cover_letter_artifact(
    job_id: str, body: GenerateArtifactRequest, response: Response
) -> WorkspaceOperation:
    _set_no_store(response)
    with _conn() as conn:
        row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
    operation = enqueue_artifact_generation(
        job_id,
        "cover_letter",
        body.base_doc_id,
    )
    return WorkspaceOperation(**operation)


@app.put("/api/artifacts/{artifact_id}", response_model=JobArtifact)
def update_artifact(artifact_id: int, body: UpdateArtifactRequest) -> JobArtifact:
    with _conn() as conn:
        existing = artifact_svc.get_artifact(artifact_id, conn)
        if not existing:
            raise HTTPException(status_code=404, detail="Artifact not found")
        art = artifact_svc.update_artifact(artifact_id, body.content_md, conn)
    _cache().publish_dashboard_event(
        "refresh",
        "artifacts",
        job_id=str(art.get("job_id") or ""),
    )
    return JobArtifact(**art)


@app.get("/api/artifacts/{artifact_id}/pdf")
def get_artifact_pdf(artifact_id: int) -> StreamingResponse:
    with _conn() as conn:
        art = artifact_svc.get_artifact(artifact_id, conn)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        pdf_bytes = artifact_svc.render_artifact_pdf(art["content_md"])
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    artifact_type = art.get("artifact_type", "artifact")
    filename = "resume.pdf" if artifact_type == "resume" else "cover_letter.pdf"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/artifacts/by-url", response_model=ArtifactsByUrlResponse)
def get_artifacts_by_url(
    url: str = Query(..., description="Job application page URL"),
    response: Response = None,
) -> ArtifactsByUrlResponse:
    _set_no_store(response)
    with _conn() as conn:
        result = artifact_svc.get_artifacts_by_url(url, conn)
    resume = JobArtifact(**result["resume"]) if result.get("resume") else None
    cover_letter = (
        JobArtifact(**result["cover_letter"]) if result.get("cover_letter") else None
    )
    return ArtifactsByUrlResponse(
        job_info=result.get("job_info"),
        resume=resume,
        cover_letter=cover_letter,
    )


def run() -> None:
    import uvicorn

    src_dir = Path(__file__).resolve().parents[3]
    uvicorn.run(
        "ai_job_hunter.dashboard.backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        app_dir=str(src_dir),
    )


if __name__ == "__main__":
    run()
