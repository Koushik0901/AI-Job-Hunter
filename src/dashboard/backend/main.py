from __future__ import annotations

import copy
import os
import queue
import sys
import threading
import time
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware

_THIS_DIR = Path(__file__).resolve().parent
_SRC_DIR = _THIS_DIR.parents[1]
_REPO_DIR = _SRC_DIR.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from db import (
    append_artifact_ai_run_event,
    get_artifact_ai_run,
    init_db,
    list_artifact_ai_run_events,
    upsert_artifact_ai_run,
)
from dashboard.backend.cache import DashboardCache, hash_id
from dashboard.backend.evidence_assets import prepare_candidate_evidence_assets
from dashboard.backend import repository
from dashboard.backend.schemas import (
    AddProfileSkillRequest,
    AppHealthResponse,
    CandidateProfile,
    CandidateEvidenceAssets,
    CandidateEvidenceIndexStatus,
    CompanySource,
    CompanySourceImportResponse,
    CompanySourceProbeRequest,
    CompanySourceProbeResult,
    CompanySourceProbeResponse,
    CreateCompanySourceRequest,
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
    ResumeLatexDocument,
    ArtifactLatexDocument,
    SaveResumeLatexRequest,
    RecompileResumeLatexRequest,
    SaveArtifactLatexRequest,
    RecompileArtifactLatexRequest,
    ResumeSwarmOptimizeRequest,
    ResumeSwarmOptimizeResponse,
    ResumeSwarmRunStartRequest,
    ResumeSwarmRunStartResponse,
    ResumeSwarmRunStatusResponse,
    ResumeSwarmConfirmSaveRequest,
    TemplateSettings,
    TemplateValidationResult,
    ArtifactSummary,
    ArtifactVersion,
    ArtifactsHubResponse,
    ArtifactStarterStatus,
    CreateArtifactVersionRequest,
    GenerateStarterArtifactsRequest,
    SuppressedJob,
    SuppressJobRequest,
    StatsResponse,
    ScoreRecomputeStatus,
    TrackingPatchRequest,
    UpdateCompanySourceRequest,
    WorkspaceJdReformatRequest,
    WorkspaceOperation,
    WorkspaceOverview,
    WorkspacePruneRequest,
    WorkspaceScrapeRequest,
)
from dashboard.backend.evidence_index import build_runtime_evidence_pack, reindex_evidence_assets
from dashboard.backend.service import normalize_tracking_patch
from dashboard.backend.resume_import import import_resume_pdf_bytes_to_baseline, import_resume_pdf_to_baseline
from dashboard.backend.latex_resume import (
    compile_resume_tex,
    compiled_pdf_path,
    list_builtin_templates,
    list_cover_letter_templates,
    get_resume_template_source,
    get_cover_letter_template_source,
    validate_template,
)
from dashboard.backend.resume_agents_swarm.run import run_resume_agents_swarm_optimization
from dashboard.backend.cover_letter_agents_swarm.run import run_cover_letter_agents_swarm_optimization
from dashboard.backend.swarm_runtime import SwarmRunCancelled
from services.company_registry_service import (
    annotate_existing_company_sources,
    apply_company_source_import,
    probe_company_sources,
    preview_company_source_import,
    save_company_source,
)
from services.workspace_operation_service import get_operation as get_workspace_operation_record
from services.workspace_operation_service import list_operations as list_workspace_operation_records
from services.workspace_operation_service import run_workspace_operation

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
_TTL_JOBS_SNAPSHOT = int(os.getenv("DASHBOARD_CACHE_TTL_JOBS_SNAPSHOT", "180"))
_TTL_JOB_DETAIL = int(os.getenv("DASHBOARD_CACHE_TTL_JOB_DETAIL", "300"))
_TTL_EVENTS = int(os.getenv("DASHBOARD_CACHE_TTL_EVENTS", "90"))
_TTL_STATS = int(os.getenv("DASHBOARD_CACHE_TTL_STATS", "30"))
_TTL_PROFILE = int(os.getenv("DASHBOARD_CACHE_TTL_PROFILE", "300"))
_TTL_ANALYTICS_FC = int(os.getenv("DASHBOARD_CACHE_TTL_ANALYTICS_FC", "60"))
_TTL_ARTIFACTS = int(os.getenv("DASHBOARD_CACHE_TTL_ARTIFACTS", "180"))
_ENRICHMENT_MODEL = os.getenv("ENRICHMENT_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
_DESCRIPTION_FORMAT_MODEL = os.getenv("DESCRIPTION_FORMAT_MODEL", "openai/gpt-oss-20b:paid").strip() or "openai/gpt-oss-20b:paid"
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
_SWARM_RUNS_LOCK = threading.Lock()
_SWARM_RUNS: dict[str, dict[str, Any]] = {}
_SWARM_PERSIST_QUEUE: queue.Queue[tuple[str, tuple[Any, ...]]] = queue.Queue()
_SWARM_PERSIST_WORKER_LOCK = threading.Lock()
_SWARM_PERSIST_WORKER_STARTED = False
_EVIDENCE_INDEX_STATUS_LOCK = threading.Lock()
_EVIDENCE_INDEX_STATUS: dict[str, Any] = {
    "enabled": False,
    "backend": "disabled",
    "status": "idle",
    "indexed_count": 0,
    "message": "Not indexed yet.",
    "updated_at": None,
    "collection": None,
}


def _qdrant_health() -> dict[str, Any]:
    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    collection = os.getenv("QDRANT_EVIDENCE_COLLECTION", "candidate_evidence_chunks").strip() or "candidate_evidence_chunks"
    if not qdrant_url:
        return {
            "configured": False,
            "healthy": False,
            "collection": collection,
            "collection_exists": False,
            "message": "QDRANT_URL not configured.",
        }
    try:
        from qdrant_client import QdrantClient
    except Exception as error:
        return {
            "configured": True,
            "healthy": False,
            "collection": collection,
            "collection_exists": False,
            "message": f"qdrant-client unavailable: {error}",
        }

    try:
        client = QdrantClient(
            url=qdrant_url,
            api_key=os.getenv("QDRANT_API_KEY", "").strip() or None,
            timeout=5,
        )
        collections_response = client.get_collections()
        raw_collections = getattr(collections_response, "collections", []) or []
        existing = {
            str(getattr(item, "name", "")).strip()
            for item in raw_collections
            if str(getattr(item, "name", "")).strip()
        }
        return {
            "configured": True,
            "healthy": True,
            "collection": collection,
            "collection_exists": collection in existing,
            "message": "Qdrant reachable.",
        }
    except Exception as error:
        return {
            "configured": True,
            "healthy": False,
            "collection": collection,
            "collection_exists": False,
            "message": str(error),
        }


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


def _jobs_snapshot_cache_key() -> str:
    return f"{_CACHE_NS}:jobs:snapshot"


def _job_cache_key(job_id: str) -> str:
    return f"{_CACHE_NS}:job:{hash_id(job_id)}"


def _parse_snapshot_datetime(raw: Any) -> datetime | None:
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
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _refresh_snapshot_runtime_fields(item: dict[str, Any]) -> dict[str, Any]:
    job = dict(item)
    status = str(job.get("status") or "")
    entered = _parse_snapshot_datetime(job.get("staging_entered_at"))
    due = _parse_snapshot_datetime(job.get("staging_due_at"))
    if status == "staging" and entered is not None and due is None:
        due = entered + timedelta(hours=48)
        job["staging_due_at"] = due.isoformat()
    if status != "staging":
        job["staging_overdue"] = False
        job["staging_age_hours"] = None
        return job
    now = datetime.now(timezone.utc)
    job["staging_overdue"] = bool(due is not None and now >= due)
    if entered is not None:
        job["staging_age_hours"] = max(0, int((now - entered).total_seconds() // 3600))
    else:
        job["staging_age_hours"] = None
    return job


def _load_jobs_snapshot() -> list[dict[str, Any]]:
    cached = cache.get_json(_jobs_snapshot_cache_key())
    if isinstance(cached, list):
        return [
            item
            for item in cached
            if isinstance(item, dict) and isinstance(item.get("url"), str)
        ]

    conn = _conn()
    try:
        items = repository.list_jobs_snapshot(conn)
    finally:
        conn.close()
    cache.set_json(_jobs_snapshot_cache_key(), items, _TTL_JOBS_SNAPSHOT)
    return items


def _matches_jobs_snapshot_filters(
    item: dict[str, Any],
    *,
    status: str | None,
    q: str | None,
    ats: str | None,
    company: str | None,
    posted_after: str | None,
    posted_before: str | None,
    include_suppressed: bool,
) -> bool:
    if not include_suppressed and bool(item.get("_suppressed")):
        return False
    if status and str(item.get("status") or "") != status:
        return False
    if ats and str(item.get("ats") or "") != ats:
        return False
    if company and company.lower() not in str(item.get("company") or "").lower():
        return False
    posted = str(item.get("posted") or "")
    if posted_after and (not posted or posted < posted_after):
        return False
    if posted_before and (not posted or posted > posted_before):
        return False
    if q:
        query = q.strip().lower()
        if query and query not in str(item.get("_search_text") or ""):
            return False
    return True


def _sort_jobs_snapshot(items: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    ranked = list(items)
    if sort == "company_asc":
        ranked.sort(key=lambda item: (str(item.get("_company_sort") or ""), str(item.get("title") or "").casefold()))
        return ranked
    if sort == "posted_desc":
        ranked.sort(key=lambda item: str(item.get("_posted_sort") or ""), reverse=True)
        return ranked
    if sort == "updated_desc":
        ranked.sort(key=lambda item: str(item.get("_updated_sort") or ""), reverse=True)
        return ranked
    ranked.sort(
        key=lambda item: (
            int(item.get("match_score") if item.get("match_score") is not None else -1),
            str(item.get("_posted_sort") or ""),
        ),
        reverse=True,
    )
    return ranked


def _normalize_client_id(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return "anonymous"
    safe = "".join(ch for ch in value if ch.isalnum() or ch in "-_:.")
    if not safe:
        return "anonymous"
    return safe[:128]


def _client_hash(client_id: str) -> str:
    return hash_id(client_id)


def _client_from_request(request: Request) -> str:
    return _normalize_client_id(request.headers.get("X-Client-Id"))


def _job_cache_key_for_client(client_id: str, job_id: str) -> str:
    return f"{_CACHE_NS}:user:{_client_hash(client_id)}:job:{hash_id(job_id)}"


def _events_cache_key(job_id: str) -> str:
    return f"{_CACHE_NS}:events:{hash_id(job_id)}"


def _events_cache_key_for_client(client_id: str, job_id: str) -> str:
    return f"{_CACHE_NS}:user:{_client_hash(client_id)}:events:{hash_id(job_id)}"


def _artifacts_cache_key_for_client(client_id: str, job_id: str) -> str:
    return f"{_CACHE_NS}:user:{_client_hash(client_id)}:artifacts:{hash_id(job_id)}"


def _profile_cache_key() -> str:
    return f"{_CACHE_NS}:profile"


def _resume_profile_cache_key() -> str:
    return f"{_CACHE_NS}:resume_profile"


def _evidence_assets_cache_key() -> str:
    return f"{_CACHE_NS}:evidence_assets"


def _stats_cache_key() -> str:
    return f"{_CACHE_NS}:stats"


def _job_detail_lru_key() -> str:
    return f"{_CACHE_NS}:idx:job_detail_lru"


def _job_detail_lru_key_for_client(client_id: str) -> str:
    return f"{_CACHE_NS}:user:{_client_hash(client_id)}:idx:job_detail_lru"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_artifact_starter_state(job_id: str, job_url: str, stage: str, progress_percent: int, running: bool) -> None:
    bounded = max(0, min(100, int(progress_percent)))
    with _ARTIFACT_STARTER_LOCK:
        _ARTIFACT_STARTER_STATE[job_id] = {
            "job_id": job_id,
            "job_url": job_url,
            "stage": stage,
            "progress_percent": bounded,
            "running": running,
            "updated_at": _now_iso(),
        }


def _get_artifact_starter_state(job_id: str, job_url: str) -> dict[str, Any]:
    with _ARTIFACT_STARTER_LOCK:
        item = _ARTIFACT_STARTER_STATE.get(job_id)
        if item:
            return dict(item)
    return {
        "job_id": job_id,
        "job_url": job_url,
        "stage": "idle",
        "progress_percent": 0,
        "running": False,
        "updated_at": None,
    }


def _set_evidence_index_status(payload: dict[str, Any]) -> None:
    with _EVIDENCE_INDEX_STATUS_LOCK:
        _EVIDENCE_INDEX_STATUS.update(payload)


def _get_evidence_index_status() -> dict[str, Any]:
    with _EVIDENCE_INDEX_STATUS_LOCK:
        return dict(_EVIDENCE_INDEX_STATUS)


def _new_swarm_run(
    *,
    artifact_id: str,
    job_id: str,
    job_url: str,
    cycles: int,
    pipeline: str,
    template_id: str | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    return {
        "run_id": str(uuid.uuid4()),
        "artifact_id": artifact_id,
        "job_id": job_id,
        "job_url": job_url,
        "template_id": template_id,
        "status": "queued",
        "current_stage": "queued",
        "stage_index": 0,
        "started_at": now,
        "updated_at": now,
        "cycles_target": cycles,
        "cycles_done": 0,
        "pipeline": pipeline,
        "events": [],
        "latest_score": None,
        "latest_rewrite": None,
        "latest_apply_report": None,
        "final_score": None,
        "candidate_latex": None,
        "error": None,
        "cancel_requested": False,
    }


def _append_swarm_event(run: dict[str, Any], *, stage: str, message: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {
        "ts": _now_iso(),
        "stage": stage,
        "message": message,
    }
    if data:
        event["data"] = data
    events = list(run.get("events") or [])
    events.append(event)
    event["seq"] = len(events)
    run["events"] = events
    run["updated_at"] = event["ts"]
    return event


def _persist_swarm_run(run: dict[str, Any]) -> None:
    conn = _conn()
    try:
        upsert_artifact_ai_run(conn, run)
    finally:
        conn.close()


def _persist_swarm_event(run_id: str, event: dict[str, Any]) -> None:
    conn = _conn()
    try:
        append_artifact_ai_run_event(conn, run_id, event)
    finally:
        conn.close()


def _ensure_swarm_persist_worker() -> None:
    global _SWARM_PERSIST_WORKER_STARTED
    with _SWARM_PERSIST_WORKER_LOCK:
        if _SWARM_PERSIST_WORKER_STARTED:
            return

        def _worker() -> None:
            while True:
                item, payload = _SWARM_PERSIST_QUEUE.get()
                try:
                    if item == "run":
                        _persist_swarm_run(payload[0])
                    elif item == "event":
                        _persist_swarm_event(str(payload[0]), payload[1])
                finally:
                    _SWARM_PERSIST_QUEUE.task_done()

        threading.Thread(target=_worker, daemon=True, name="swarm-persist-worker").start()
        _SWARM_PERSIST_WORKER_STARTED = True


def _queue_persist_swarm_run(run: dict[str, Any]) -> None:
    _ensure_swarm_persist_worker()
    _SWARM_PERSIST_QUEUE.put(("run", (copy.deepcopy(run),)))


def _queue_persist_swarm_event(run_id: str, event: dict[str, Any]) -> None:
    _ensure_swarm_persist_worker()
    _SWARM_PERSIST_QUEUE.put(("event", (run_id, copy.deepcopy(event))))


def _load_swarm_run_from_store(run_id: str) -> dict[str, Any] | None:
    conn = _conn()
    try:
        run = get_artifact_ai_run(conn, run_id)
        if not run:
            return None
        run["events"] = list_artifact_ai_run_events(conn, run_id)
        run.setdefault("cancel_requested", False)
        return run
    finally:
        conn.close()


def _serialize_swarm_run(run: dict[str, Any]) -> ResumeSwarmRunStatusResponse:
    return ResumeSwarmRunStatusResponse(
        run_id=str(run["run_id"]),
        artifact_id=str(run["artifact_id"]),
        status=str(run["status"]),
        current_stage=str(run["current_stage"]),
        stage_index=int(run["stage_index"]),
        started_at=str(run["started_at"]),
        updated_at=str(run["updated_at"]),
        cycles_target=int(run["cycles_target"]),
        cycles_done=int(run["cycles_done"]),
        events=list(run.get("events") or []),
        latest_score=run.get("latest_score") if isinstance(run.get("latest_score"), dict) else None,
        latest_rewrite=run.get("latest_rewrite") if isinstance(run.get("latest_rewrite"), dict) else None,
        latest_apply_report=run.get("latest_apply_report") if isinstance(run.get("latest_apply_report"), dict) else None,
        final_score=run.get("final_score") if isinstance(run.get("final_score"), dict) else None,
        candidate_latex=str(run["candidate_latex"]) if isinstance(run.get("candidate_latex"), str) else None,
        error=str(run["error"]) if run.get("error") else None,
    )


def _swarm_stage_to_step(event: dict[str, Any], pipeline: str) -> tuple[str, str]:
    stage = str(event.get("stage") or "")
    noun = "resume" if pipeline == "resume" else "cover letter"
    cap_noun = "Resume" if pipeline == "resume" else "Cover letter"
    if stage == "jd_decompose":
        return "jd_decompose", f"Decomposing job description for {noun}"
    if stage == "evidence_mine":
        return "evidence_mine", f"Mining grounded evidence for {noun}"
    if stage == "narrative_plan":
        return "narrative_plan", "Planning cover-letter narrative"
    if stage == "plan":
        cycle = int(event.get("cycle") or 1)
        return f"plan_cycle_{cycle}", f"Planning {noun} edits for cycle {cycle}"
    if stage == "tone_guard":
        return "tone_guard", "Running tone guard checks"
    if stage == "draft":
        return "draft_generation", f"Generating first {noun} draft"
    if stage == "inject":
        return "draft_injected", f"Inserting draft into {noun} template"
    if stage == "score":
        cycle = int(event.get("cycle") or 0)
        if cycle <= 0:
            return "initial_scoring", f"Scoring baseline {noun}"
        return f"rescoring_cycle_{cycle}", f"Re-scoring cycle {cycle}"
    if stage == "rewrite":
        cycle = int(event.get("cycle") or 1)
        return f"rewrite_cycle_{cycle}", f"Rewriting {noun} for cycle {cycle}"
    if stage == "prepare_edit_context":
        return "prepare_edit_context", f"Preparing editable {noun} context"
    if stage == "verify_moves":
        return "verify_moves", f"Verifying {noun} legal moves"
    if stage == "apply":
        cycle = int(event.get("cycle") or 1)
        return f"apply_cycle_{cycle}", f"Applying rewrite moves for cycle {cycle}"
    if stage == "final_score":
        return "final_scoring", f"Running final {noun} scoring pass"
    if stage == "decide_next":
        cycle_done = int(event.get("cycles_done") or 0)
        score_delta_raw = event.get("score_delta")
        score_delta = int(score_delta_raw) if isinstance(score_delta_raw, int) else None
        if bool(event.get("force_continue")):
            return "controller", f"Cycle {cycle_done}: force continue (non-negotiable or tone guard)"
        if bool(event.get("budget_stop")):
            return "controller", f"Cycle {cycle_done + 1} skipped: edit budget reached"
        if bool(event.get("low_delta_stop")):
            return "controller", f"Cycle {cycle_done + 1} skipped: delta predicted low"
        if score_delta is not None:
            sign = "+" if score_delta >= 0 else ""
            return "controller", f"Cycle {cycle_done}: {sign}{score_delta} score delta"
        return "controller", "Deciding next cycle"
    if stage == "preview_ready":
        return "preview_ready", f"{cap_noun} optimization finished. Review and confirm save."
    return stage or "running", "Running"


def _start_swarm_run_background(
    run_id: str,
    *,
    job_description: str,
    latex_source: str,
    resume_text: str,
    evidence_context: dict[str, Any] | None,
    brag_document_markdown: str,
    project_cards: list[dict[str, Any]] | None,
    do_not_claim: list[str] | None,
    evidence_pack: dict[str, Any] | None,
    cycles: int,
    pipeline: str,
) -> None:
    def _runner() -> None:
        runtime_evidence_pack = evidence_pack if isinstance(evidence_pack, dict) and evidence_pack else build_runtime_evidence_pack(
            job_description,
            {
                "evidence_context": evidence_context or {},
                "brag_document_markdown": brag_document_markdown,
                "project_cards": project_cards or [],
                "do_not_claim": do_not_claim or [],
            },
            profile_id="default",
        )

        def _should_cancel() -> bool:
            with _SWARM_RUNS_LOCK:
                run = _SWARM_RUNS.get(run_id)
                return not run or bool(run.get("cancel_requested"))

        def _on_event(event: dict[str, Any]) -> None:
            run_snapshot: dict[str, Any] | None = None
            persisted_event: dict[str, Any] | None = None
            with _SWARM_RUNS_LOCK:
                run = _SWARM_RUNS.get(run_id)
                if not run:
                    return
                if run.get("cancel_requested"):
                    run["status"] = "cancelled"
                    run["current_stage"] = "cancelled"
                    run["updated_at"] = _now_iso()
                    return
                run["status"] = "running"
                run["stage_index"] = int(run.get("stage_index") or 0) + 1
                mapped_stage, message = _swarm_stage_to_step(event, str(run.get("pipeline") or pipeline))
                run["current_stage"] = mapped_stage
                run["cycles_done"] = int(event.get("cycle") or run.get("cycles_done") or 0)
                if isinstance(event.get("score"), dict):
                    run["latest_score"] = event["score"]
                if isinstance(event.get("rewrite"), dict):
                    run["latest_rewrite"] = event["rewrite"]
                if isinstance(event.get("apply"), dict):
                    run["latest_apply_report"] = event["apply"]
                persisted_event = _append_swarm_event(run, stage=mapped_stage, message=message, data=event)
                run_snapshot = dict(run)
            if run_snapshot is not None:
                _queue_persist_swarm_run(run_snapshot)
            if persisted_event is not None:
                _queue_persist_swarm_event(run_id, persisted_event)

        try:
            if pipeline == "resume":
                result = run_resume_agents_swarm_optimization(
                    job_description=job_description,
                    resume_text=resume_text,
                    latex_resume=latex_source,
                    evidence_context=evidence_context or {},
                    brag_document_markdown=brag_document_markdown,
                    project_cards=project_cards or [],
                    do_not_claim=do_not_claim or [],
                    evidence_pack=runtime_evidence_pack,
                    cycles=cycles,
                    progress_callback=_on_event,
                    should_cancel=_should_cancel,
                )
                candidate_latex = str(result.get("final_latex_resume") or latex_source)
            else:
                result = run_cover_letter_agents_swarm_optimization(
                    job_description=job_description,
                    resume_text=resume_text,
                    latex_cover_letter=latex_source,
                    evidence_context=evidence_context or {},
                    brag_document_markdown=brag_document_markdown,
                    project_cards=project_cards or [],
                    do_not_claim=do_not_claim or [],
                    evidence_pack=runtime_evidence_pack,
                    cycles=cycles,
                    progress_callback=_on_event,
                    should_cancel=_should_cancel,
                )
                candidate_latex = str(result.get("final_latex_cover_letter") or latex_source)
            with _SWARM_RUNS_LOCK:
                run = _SWARM_RUNS.get(run_id)
                if not run:
                    return
                if run.get("cancel_requested"):
                    run["status"] = "cancelled"
                    run["current_stage"] = "cancelled"
                    run["updated_at"] = _now_iso()
                    return
                run["candidate_latex"] = candidate_latex
                run["final_score"] = result.get("final_score") if isinstance(result.get("final_score"), dict) else {}
                run["status"] = "awaiting_confirmation"
                run["current_stage"] = "preview_ready"
                run["updated_at"] = _now_iso()
                event = _append_swarm_event(run, stage="preview_ready", message="AI rewrite finished. Review and confirm save.")
                snapshot = dict(run)
            _queue_persist_swarm_run(snapshot)
            _queue_persist_swarm_event(run_id, event)
        except SwarmRunCancelled:
            snapshot: dict[str, Any] | None = None
            event: dict[str, Any] | None = None
            with _SWARM_RUNS_LOCK:
                run = _SWARM_RUNS.get(run_id)
                if not run:
                    return
                run["status"] = "cancelled"
                run["current_stage"] = "cancelled"
                run["updated_at"] = _now_iso()
                events = run.get("events") if isinstance(run.get("events"), list) else []
                if not events or str(events[-1].get("stage") or "") != "cancelled":
                    event = _append_swarm_event(run, stage="cancelled", message="AI rewrite stopped by user.")
                snapshot = dict(run)
            if snapshot is not None:
                _queue_persist_swarm_run(snapshot)
            if event is not None:
                _queue_persist_swarm_event(run_id, event)
        except Exception as error:
            snapshot: dict[str, Any] | None = None
            event: dict[str, Any] | None = None
            with _SWARM_RUNS_LOCK:
                run = _SWARM_RUNS.get(run_id)
                if not run:
                    return
                if run.get("cancel_requested"):
                    run["status"] = "cancelled"
                    run["current_stage"] = "cancelled"
                    run["updated_at"] = _now_iso()
                    snapshot = dict(run)
                else:
                    run["status"] = "failed"
                    run["current_stage"] = "failed"
                    run["error"] = str(error)
                    run["updated_at"] = _now_iso()
                    event = _append_swarm_event(run, stage="failed", message="AI rewrite failed.", data={"error": str(error)})
                    snapshot = dict(run)
            if snapshot is not None:
                _queue_persist_swarm_run(snapshot)
            if event is not None:
                _queue_persist_swarm_event(run_id, event)

    thread = threading.Thread(target=_runner, daemon=True, name=f"{pipeline}-swarm-{run_id}")
    thread.start()


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


def _invalidate_job_detail(job_id: str, client_id: str | None = None) -> None:
    # Prefer precise per-user invalidation when a client id is available.
    if client_id:
        job_key = _job_cache_key_for_client(client_id, job_id)
        events_key = _events_cache_key_for_client(client_id, job_id)
        artifacts_key = _artifacts_cache_key_for_client(client_id, job_id)
        cache.delete(job_key, events_key, artifacts_key)
        cache.zrem(_job_detail_lru_key_for_client(client_id), job_key)
        return
    # Fallback: clear this job's per-user cache entries across users.
    cache.delete(_job_cache_key(job_id), _events_cache_key(job_id))
    job_hash = hash_id(job_id)
    cache.delete_pattern(f"{_CACHE_NS}:user:*:job:{job_hash}")
    cache.delete_pattern(f"{_CACHE_NS}:user:*:events:{job_hash}")
    cache.delete_pattern(f"{_CACHE_NS}:user:*:artifacts:{job_hash}")


def _invalidate_all_job_details() -> None:
    cache.delete_pattern(f"{_CACHE_NS}:job:*")
    cache.delete_pattern(f"{_CACHE_NS}:events:*")
    cache.delete_pattern(f"{_CACHE_NS}:user:*:job:*")
    cache.delete_pattern(f"{_CACHE_NS}:user:*:events:*")
    cache.delete_pattern(f"{_CACHE_NS}:user:*:artifacts:*")
    cache.delete_pattern(f"{_CACHE_NS}:user:*:idx:job_detail_lru")
    cache.delete(_job_detail_lru_key())


def _touch_job_detail_lru(client_id: str, job_key: str) -> None:
    cache.zadd(_job_detail_lru_key_for_client(client_id), {job_key: float(time.time())})
    _trim_job_detail_lru(client_id)


def _trim_job_detail_lru(client_id: str) -> None:
    lru_key = _job_detail_lru_key_for_client(client_id)
    count = cache.zcard(lru_key)
    overflow = count - _MAX_JOB_DETAILS
    if overflow <= 0:
        return
    oldest = cache.zrange(lru_key, 0, overflow - 1)
    if not oldest:
        return
    cache.delete(*oldest)
    cache.zrem(lru_key, *oldest)


def _get_score_recompute_status() -> dict[str, Any]:
    with _SCORE_RECOMPUTE_STATE_LOCK:
        return dict(_SCORE_RECOMPUTE_STATE)


def _set_score_recompute_status(**updates: Any) -> None:
    with _SCORE_RECOMPUTE_STATE_LOCK:
        _SCORE_RECOMPUTE_STATE.update(updates)


def _background_enrich_manual_job(job_id: str) -> None:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return

    conn = _conn()
    try:
        from enrich import RateLimitSignal, enrich_one_job

        item = repository.get_job_detail(conn, job_id)
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
        save_enrichment(conn, str(item["url"]), result)
        repository.recompute_match_scores(conn, urls=[str(item["url"])])
    except RateLimitSignal:
        return
    except Exception:
        return
    finally:
        conn.close()

    _invalidate_job_detail(job_id)
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


@app.get("/api/health", response_model=AppHealthResponse)
def health() -> AppHealthResponse:
    return AppHealthResponse(
        status="ok",
        services={
            "redis": cache.health(),
            "qdrant": _qdrant_health(),
        },
    )


@app.get("/api/workspace/overview", response_model=WorkspaceOverview)
def get_workspace_overview() -> WorkspaceOverview:
    conn = _conn()
    try:
        stats = repository.get_stats(conn)
        profile = repository.get_profile(conn)
        all_sources = repository.list_company_sources_data(conn, enabled_only=False)
        enabled_sources = [item for item in all_sources if bool(item.get("enabled"))]
        recent_operations = [
            WorkspaceOperation(**item)
            for item in repository.list_workspace_operations_data(conn, limit=8)
        ]
        return WorkspaceOverview(
            total_jobs=int(stats.get("total_jobs") or 0),
            enabled_company_sources=len(enabled_sources),
            total_company_sources=len(all_sources),
            desired_job_titles_count=len(profile.get("desired_job_titles") or []),
            has_profile_basics=bool((profile.get("skills") or []) or (profile.get("desired_job_titles") or [])),
            services={
                "redis": cache.health(),
                "qdrant": _qdrant_health(),
            },
            recent_operations=recent_operations,
        )
    finally:
        conn.close()


@app.get("/api/company-sources", response_model=list[CompanySource])
def get_company_sources() -> list[CompanySource]:
    conn = _conn()
    try:
        return [CompanySource(**item) for item in repository.list_company_sources_data(conn, enabled_only=False)]
    finally:
        conn.close()


@app.post("/api/company-sources/probe", response_model=CompanySourceProbeResponse)
def post_company_sources_probe(payload: CompanySourceProbeRequest) -> CompanySourceProbeResponse:
    conn = _conn()
    try:
        probed = probe_company_sources(payload.query, extra_slugs=payload.extra_slugs)
        matches = annotate_existing_company_sources(conn, probed.get("matches") or [])
        zero_job_matches = annotate_existing_company_sources(conn, probed.get("zero_job_matches") or [])
        return CompanySourceProbeResponse(
            query=payload.query,
            company_name=str(probed.get("company_name") or payload.query),
            slugs=[str(item) for item in (probed.get("slugs") or [])],
            inferred=probed.get("inferred"),
            matches=[CompanySourceProbeResult(**item) for item in matches],
            zero_job_matches=[CompanySourceProbeResult(**item) for item in zero_job_matches],
        )
    finally:
        conn.close()


@app.post("/api/company-sources", response_model=CompanySource)
def post_company_sources(payload: CreateCompanySourceRequest) -> CompanySource:
    conn = _conn()
    try:
        saved = save_company_source(conn, payload.model_dump())
        rows = repository.list_company_sources_data(conn, enabled_only=False)
        matched = next(
            (
                item for item in rows
                if str(item.get("slug") or "").lower() == payload.slug.strip().lower()
                and str(item.get("ats_type") or "").lower() == payload.ats_type.strip().lower()
            ),
            None,
        )
        if not matched:
            raise HTTPException(status_code=500, detail="Failed to save company source")
        _invalidate_job_collections()
        return CompanySource(**matched)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        conn.close()


@app.patch("/api/company-sources/{source_id}", response_model=CompanySource)
def patch_company_source(source_id: int, payload: UpdateCompanySourceRequest) -> CompanySource:
    conn = _conn()
    try:
        updated = repository.update_company_source_data(conn, source_id, payload.model_dump(exclude_unset=True))
        if not updated:
            raise HTTPException(status_code=404, detail="Company source not found")
        _invalidate_job_collections()
        return CompanySource(**updated)
    finally:
        conn.close()


@app.post("/api/company-sources/import-preview", response_model=CompanySourceImportResponse)
def post_company_source_import_preview() -> CompanySourceImportResponse:
    conn = _conn()
    try:
        result = preview_company_source_import(conn)
        return CompanySourceImportResponse(
            new_entries=[CompanySourceProbeResult(**item) for item in result["new_entries"]],
            skipped_duplicates=int(result["skipped_duplicates"]),
            imported=None,
        )
    finally:
        conn.close()


@app.post("/api/company-sources/import", response_model=CompanySourceImportResponse)
def post_company_source_import() -> CompanySourceImportResponse:
    conn = _conn()
    try:
        result = apply_company_source_import(conn)
        _invalidate_job_collections()
        return CompanySourceImportResponse(
            new_entries=[CompanySourceProbeResult(**item) for item in result["new_entries"]],
            skipped_duplicates=int(result["skipped_duplicates"]),
            imported=int(result["imported"]),
        )
    finally:
        conn.close()


@app.get("/api/workspace/operations", response_model=list[WorkspaceOperation])
def get_workspace_operations(limit: int = Query(default=20, ge=1, le=100)) -> list[WorkspaceOperation]:
    conn = _conn()
    try:
        return [WorkspaceOperation(**item) for item in list_workspace_operation_records(conn, limit=limit)]
    finally:
        conn.close()


@app.get("/api/workspace/operations/{operation_id}", response_model=WorkspaceOperation)
def get_workspace_operation(operation_id: str) -> WorkspaceOperation:
    conn = _conn()
    try:
        item = get_workspace_operation_record(conn, operation_id)
        if not item:
            raise HTTPException(status_code=404, detail="Workspace operation not found")
        return WorkspaceOperation(**item)
    finally:
        conn.close()


def _run_workspace_operation_endpoint(kind: str, params: dict[str, Any]) -> WorkspaceOperation:
    conn = _conn()
    try:
        item = run_workspace_operation(conn, kind, params)
        if str(item.get("status") or "") == "completed":
            _invalidate_job_collections()
            _invalidate_all_job_details()
        return WorkspaceOperation(**item)
    finally:
        conn.close()


@app.post("/api/workspace/operations/scrape", response_model=WorkspaceOperation)
def post_workspace_scrape(payload: WorkspaceScrapeRequest) -> WorkspaceOperation:
    return _run_workspace_operation_endpoint("scrape", payload.model_dump())


@app.post("/api/workspace/operations/enrich-backfill", response_model=WorkspaceOperation)
def post_workspace_enrich_backfill() -> WorkspaceOperation:
    return _run_workspace_operation_endpoint("enrich_backfill", {})


@app.post("/api/workspace/operations/re-enrich-all", response_model=WorkspaceOperation)
def post_workspace_re_enrich_all() -> WorkspaceOperation:
    return _run_workspace_operation_endpoint("re_enrich_all", {"force": True})


@app.post("/api/workspace/operations/jd-reformat", response_model=WorkspaceOperation)
def post_workspace_jd_reformat(payload: WorkspaceJdReformatRequest) -> WorkspaceOperation:
    return _run_workspace_operation_endpoint("jd_reformat", payload.model_dump())


@app.post("/api/workspace/operations/prune-preview", response_model=WorkspaceOperation)
def post_workspace_prune_preview(payload: WorkspacePruneRequest) -> WorkspaceOperation:
    return _run_workspace_operation_endpoint("prune_preview", payload.model_dump())


@app.post("/api/workspace/operations/prune", response_model=WorkspaceOperation)
def post_workspace_prune(payload: WorkspacePruneRequest) -> WorkspaceOperation:
    return _run_workspace_operation_endpoint("prune", payload.model_dump())


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
    snapshot = _load_jobs_snapshot()
    refreshed = (_refresh_snapshot_runtime_fields(item) for item in snapshot)
    filtered = [
        item
        for item in refreshed
        if _matches_jobs_snapshot_filters(
            item,
            status=status,
            q=q,
            ats=ats,
            company=company,
            posted_after=posted_after,
            posted_before=posted_before,
            include_suppressed=include_suppressed,
        )
    ]
    total = len(filtered)
    ranked = _sort_jobs_snapshot(filtered, sort)
    window = ranked[offset:offset + limit]
    items = [
        {
            key: value
            for key, value in item.items()
            if not str(key).startswith("_")
        }
        for item in window
    ]
    return JobsListResponse(items=items, total=total)


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

    _invalidate_job_detail(response.id)
    _invalidate_job_collections()
    background_tasks.add_task(_background_recompute_scores, [response.url])
    background_tasks.add_task(_background_enrich_manual_job, response.id)
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


@app.get("/api/profile/evidence-assets", response_model=CandidateEvidenceAssets)
def get_profile_evidence_assets() -> CandidateEvidenceAssets:
    cached = cache.get_json(_evidence_assets_cache_key())
    if isinstance(cached, dict):
        return CandidateEvidenceAssets(**cached)

    conn = _conn()
    try:
        response = CandidateEvidenceAssets(**repository.get_candidate_evidence_assets_data(conn))
        cache.set_json(_evidence_assets_cache_key(), response.model_dump(), _TTL_PROFILE)
        return response
    finally:
        conn.close()


@app.put("/api/profile/evidence-assets", response_model=CandidateEvidenceAssets)
def put_profile_evidence_assets(payload: CandidateEvidenceAssets) -> CandidateEvidenceAssets:
    conn = _conn()
    try:
        normalized_cards: list[dict[str, Any]] = []
        for card in payload.project_cards:
            if isinstance(card, dict):
                normalized_cards.append({str(k): v for k, v in card.items()})
        saved = repository.save_candidate_evidence_assets_data(
            conn,
            {
                "evidence_context": {str(k): v for k, v in payload.evidence_context.items()},
                "brag_document_markdown": payload.brag_document_markdown,
                "project_cards": normalized_cards,
                "do_not_claim": [str(item).strip() for item in payload.do_not_claim if str(item).strip()],
            },
        )
        response = CandidateEvidenceAssets(**saved)
        cache.set_json(_evidence_assets_cache_key(), response.model_dump(), _TTL_PROFILE)
        index_result = reindex_evidence_assets("default", saved)
        _set_evidence_index_status(index_result)
        return response
    finally:
        conn.close()


@app.get("/api/profile/evidence/index-status", response_model=CandidateEvidenceIndexStatus)
def get_profile_evidence_index_status() -> CandidateEvidenceIndexStatus:
    return CandidateEvidenceIndexStatus(**_get_evidence_index_status())


@app.post("/api/profile/evidence/reindex", response_model=CandidateEvidenceIndexStatus)
def post_profile_evidence_reindex() -> CandidateEvidenceIndexStatus:
    conn = _conn()
    try:
        assets = repository.get_candidate_evidence_assets_data(conn)
    finally:
        conn.close()
    result = reindex_evidence_assets("default", assets if isinstance(assets, dict) else {})
    _set_evidence_index_status(result)
    return CandidateEvidenceIndexStatus(**_get_evidence_index_status())


@app.get("/api/profile/templates", response_model=TemplateSettings)
def get_template_settings_profile() -> TemplateSettings:
    conn = _conn()
    try:
        response = TemplateSettings(**repository.get_template_settings_data(conn))
        return response
    finally:
        conn.close()


@app.put("/api/profile/templates", response_model=TemplateSettings)
def put_template_settings_profile(payload: TemplateSettings) -> TemplateSettings:
    conn = _conn()
    try:
        saved = repository.save_template_settings_data(conn, payload.model_dump(exclude={"updated_at"}))
        return TemplateSettings(**saved)
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


@app.patch("/api/jobs/{job_id}/tracking", response_model=JobDetail)
def patch_tracking(job_id: str, payload: TrackingPatchRequest, request: Request) -> JobDetail:
    client_id = _client_from_request(request)
    patch = normalize_tracking_patch(payload.model_dump(exclude_unset=True))
    conn = _conn()
    try:
        previous_status = repository.get_tracking_status(conn, job_id)
        repository.upsert_tracking(conn, job_id, patch)
        next_status = str(patch.get("status") or previous_status)
        if previous_status != "staging" and next_status == "staging":
            repository.ensure_starter_artifacts_for_job(conn, job_id)
        item = repository.get_job_detail(conn, job_id)
        if not item:
            raise HTTPException(status_code=404, detail="Job not found after update")
        response = JobDetail(**item)
        _invalidate_job_detail(job_id)
        key = _job_cache_key_for_client(client_id, job_id)
        cache.set_json(key, response.model_dump(), _TTL_JOB_DETAIL)
        _touch_job_detail_lru(client_id, key)
        cache.expire(key, _TTL_JOB_DETAIL)
        _invalidate_job_collections()
        return response
    finally:
        conn.close()


@app.get("/api/jobs/{job_id}/events", response_model=list[JobEvent])
def get_events(job_id: str, request: Request) -> list[JobEvent]:
    client_id = _client_from_request(request)
    conn = _conn()
    try:
        events_key = _events_cache_key_for_client(client_id, job_id)
        cached = cache.get_json(events_key)
        if isinstance(cached, list):
            cache.expire(events_key, _TTL_EVENTS)
            return [JobEvent(**e) for e in cached if isinstance(e, dict)]
        events = repository.list_events(conn, job_id)
        response = [JobEvent(**e) for e in events]
        cache.set_json(events_key, [e.model_dump() for e in response], _TTL_EVENTS)
        return response
    finally:
        conn.close()


@app.get("/api/jobs/{job_id}/artifacts", response_model=list[ArtifactSummary])
def list_job_artifacts(job_id: str, request: Request) -> list[ArtifactSummary]:
    client_id = _client_from_request(request)
    conn = _conn()
    try:
        artifacts_key = _artifacts_cache_key_for_client(client_id, job_id)
        cached = cache.get_json(artifacts_key)
        if isinstance(cached, list):
            cache.expire(artifacts_key, _TTL_ARTIFACTS)
            return [ArtifactSummary(**row) for row in cached if isinstance(row, dict)]
        rows = repository.list_job_artifacts(conn, job_id)
        response = [ArtifactSummary(**row) for row in rows]
        cache.set_json(artifacts_key, [row.model_dump() for row in response], _TTL_ARTIFACTS)
        return response
    finally:
        conn.close()


@app.post("/api/jobs/{job_id}/cache/prewarm")
def prewarm_job_cache(job_id: str, request: Request) -> dict[str, Any]:
    client_id = _client_from_request(request)
    conn = _conn()
    warmed: list[str] = []
    try:
        item = repository.get_job_detail(conn, job_id)
        if not item:
            raise HTTPException(status_code=404, detail="Job not found")

        job_response = JobDetail(**item)
        job_key = _job_cache_key_for_client(client_id, job_id)
        cache.set_json(job_key, job_response.model_dump(), _TTL_JOB_DETAIL)
        _touch_job_detail_lru(client_id, job_key)
        cache.expire(job_key, _TTL_JOB_DETAIL)
        warmed.append("job_detail")

        events = [JobEvent(**e) for e in repository.list_events(conn, job_id)]
        events_key = _events_cache_key_for_client(client_id, job_id)
        cache.set_json(events_key, [e.model_dump() for e in events], _TTL_EVENTS)
        cache.expire(events_key, _TTL_EVENTS)
        warmed.append("events")

        artifacts = [ArtifactSummary(**row) for row in repository.list_job_artifacts(conn, job_id)]
        artifacts_key = _artifacts_cache_key_for_client(client_id, job_id)
        cache.set_json(artifacts_key, [row.model_dump() for row in artifacts], _TTL_ARTIFACTS)
        cache.expire(artifacts_key, _TTL_ARTIFACTS)
        warmed.append("artifacts")
        return {"ok": True, "warmed": warmed}
    finally:
        conn.close()


@app.get("/api/artifacts", response_model=ArtifactsHubResponse)
def list_artifacts_hub(
    q: str | None = None,
    status: str | None = None,
    sort: str = Query(default="updated_desc", pattern="^(updated_desc|company_asc)$"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> ArtifactsHubResponse:
    conn = _conn()
    try:
        items, total = repository.list_artifacts_hub(
            conn,
            q=q,
            status=status,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return ArtifactsHubResponse(items=items, total=total)
    finally:
        conn.close()


@app.post("/api/jobs/{job_id}/artifacts/starter", response_model=list[ArtifactSummary])
def create_starter_artifacts(job_id: str, payload: GenerateStarterArtifactsRequest) -> list[ArtifactSummary]:
    conn = _conn()
    job_url = ""
    try:
        job_url = repository.get_job_url_by_id(conn, job_id) or ""
        if not job_url:
            raise HTTPException(status_code=404, detail="Job not found")
        _set_artifact_starter_state(job_id, job_url, "queued", 5, True)

        def _progress(stage: str, percent: int) -> None:
            _set_artifact_starter_state(job_id, job_url, stage, percent, stage != "done")

        # Always run create-if-missing so partial states (only resume or only cover letter)
        # can be healed from UI actions like "Create".
        repository.ensure_starter_artifacts_for_job_with_progress(conn, job_id, _progress)
        rows = repository.list_job_artifacts(conn, job_id)
        _set_artifact_starter_state(job_id, job_url, "done", 100, False)
        _invalidate_job_detail(job_id)
        _invalidate_job_collections()
        return [ArtifactSummary(**row) for row in rows]
    except Exception:
        if job_url:
            _set_artifact_starter_state(job_id, job_url, "error", 100, False)
        raise
    finally:
        conn.close()


@app.get("/api/jobs/{job_id}/artifacts/starter/status", response_model=ArtifactStarterStatus)
def get_starter_artifact_status(job_id: str) -> ArtifactStarterStatus:
    conn = _conn()
    try:
        job_url = repository.get_job_url_by_id(conn, job_id) or ""
        if not job_url:
            raise HTTPException(status_code=404, detail="Job not found")
        state = _get_artifact_starter_state(job_id, job_url)
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
        job_id = result.get("job_id")
        if isinstance(job_id, str) and job_id.strip():
            _invalidate_job_detail(job_id)
        _invalidate_job_collections()
        return {"deleted": deleted}
    finally:
        conn.close()


@app.delete("/api/jobs/{job_id}/artifacts/{artifact_type}")
def remove_job_artifact(job_id: str, artifact_type: str) -> dict[str, int]:
    kind = artifact_type.strip().lower()
    if kind not in {"resume", "cover_letter"}:
        raise HTTPException(status_code=422, detail="artifact_type must be resume or cover_letter")
    conn = _conn()
    try:
        result = repository.delete_job_artifact_by_type(conn, job_id, kind)
        deleted = int(result.get("deleted") or 0)
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Artifact not found")
        _invalidate_job_detail(job_id)
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
            content_text=None,
            created_by=payload.created_by,
            base_version_id=payload.base_version_id,
        )
        _invalidate_job_detail(str(artifact["job_id"]))
        _invalidate_job_collections()
        return ArtifactVersion(**version)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail=f"Invalid suggestion patch: {error}") from error
    finally:
        conn.close()


def _artifact_latex_document_from_artifact(artifact: dict[str, Any]) -> ArtifactLatexDocument:
    active = artifact.get("active_version") if isinstance(artifact.get("active_version"), dict) else {}
    meta = dict(active.get("meta_json") or {}) if isinstance(active.get("meta_json"), dict) else {}
    source_text = str(active.get("content_text") or "")
    version_raw = active.get("version")
    pdf_available = False
    if isinstance(version_raw, int):
        pdf_available = compiled_pdf_path(str(artifact["id"]), int(version_raw)).exists()
    diagnostics_raw = meta.get("compile_diagnostics")
    diagnostics = diagnostics_raw if isinstance(diagnostics_raw, list) else []
    normalized_diagnostics: list[dict[str, object]] = []
    for entry in diagnostics:
        if isinstance(entry, dict):
            normalized_diagnostics.append({str(k): v for k, v in entry.items()})
    artifact_type = str(artifact.get("artifact_type") or "resume")
    template_id = str(meta.get("templateId") or "classic")
    if artifact_type == "cover_letter" and (not template_id or template_id == "classic"):
        template_id = str(meta.get("templateId") or "classic_cover_letter")
    return ArtifactLatexDocument(
        artifact_id=str(artifact["id"]),
        artifact_type=artifact_type,
        version_id=str(active.get("id")) if active.get("id") else None,
        version=int(version_raw) if version_raw is not None else None,
        source_text=source_text,
        template_id=template_id,
        compile_status=str(meta.get("compile_status") or "never"),
        compile_error=str(meta.get("compile_error")) if meta.get("compile_error") else None,
        pdf_available=pdf_available,
        compiled_at=str(meta.get("compiled_at")) if meta.get("compiled_at") else None,
        log_tail=str(meta.get("compile_log_tail")) if meta.get("compile_log_tail") else None,
        diagnostics=normalized_diagnostics,
    )


def _resume_latex_document_from_artifact(artifact: dict[str, Any]) -> ResumeLatexDocument:
    generic = _artifact_latex_document_from_artifact(artifact)
    return ResumeLatexDocument(
        artifact_id=generic.artifact_id,
        version_id=generic.version_id,
        version=generic.version,
        source_text=generic.source_text,
        template_id=generic.template_id,
        compile_status=generic.compile_status,
        compile_error=generic.compile_error,
        pdf_available=generic.pdf_available,
        compiled_at=generic.compiled_at,
        log_tail=generic.log_tail,
        diagnostics=generic.diagnostics,
    )


@app.get("/api/resume-templates")
def get_resume_templates() -> list[dict[str, str]]:
    return list_builtin_templates()


@app.get("/api/cover-letter-templates")
def get_cover_letter_templates() -> list[dict[str, str]]:
    return list_cover_letter_templates()


@app.get("/api/templates/{artifact_type}")
def get_templates_by_type(artifact_type: str) -> list[dict[str, str]]:
    kind = artifact_type.strip().lower()
    if kind == "resume":
        return list_builtin_templates()
    if kind in {"cover_letter", "cover-letter"}:
        return list_cover_letter_templates()
    raise HTTPException(status_code=422, detail="artifact_type must be resume or cover_letter")


@app.get("/api/templates/{artifact_type}/{template_id}/source")
def get_template_source(artifact_type: str, template_id: str) -> dict[str, str]:
    kind = artifact_type.strip().lower()
    if kind == "resume":
        source = get_resume_template_source(template_id)
    elif kind in {"cover_letter", "cover-letter"}:
        source = get_cover_letter_template_source(template_id)
    else:
        raise HTTPException(status_code=422, detail="artifact_type must be resume or cover_letter")
    return {"template_id": template_id, "artifact_type": kind, "source_text": source}


@app.get("/api/templates/{artifact_type}/{template_id}/validate", response_model=TemplateValidationResult)
def get_template_validation(artifact_type: str, template_id: str) -> TemplateValidationResult:
    kind = artifact_type.strip().lower()
    normalized_kind: str
    if kind == "resume":
        normalized_kind = "resume"
    elif kind in {"cover_letter", "cover-letter"}:
        normalized_kind = "cover_letter"
    else:
        raise HTTPException(status_code=422, detail="artifact_type must be resume or cover_letter")
    result = validate_template(artifact_type=normalized_kind, template_id=template_id)
    return TemplateValidationResult(**result)


def _resolve_latex_artifact(conn: Any, artifact_id: str) -> dict[str, Any]:
    artifact = repository.get_artifact(conn, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact_type = str(artifact.get("artifact_type") or "")
    if artifact_type not in {"resume", "cover_letter"}:
        raise HTTPException(status_code=422, detail="Artifact must be resume or cover_letter")
    return artifact


def _latex_to_plain_text(source: str) -> str:
    import re

    text = source.replace("\r\n", "\n")
    text = re.sub(r"(?m)^\s*%.*$", "", text)
    text = re.sub(r"\\begin\{[^}]+\}", " ", text)
    text = re.sub(r"\\end\{[^}]+\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{([^{}]*)\})?", r" \1 ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _resume_profile_baseline_to_text(baseline: dict[str, Any]) -> str:
    chunks: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                chunks.append(cleaned)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(baseline)
    return "\n".join(chunks)


def _resolve_resume_text_for_cover_letter(conn: Any, job_id: str) -> str:
    artifacts = repository.list_job_artifacts(conn, job_id)
    for artifact in artifacts:
        if str(artifact.get("artifact_type") or "") != "resume":
            continue
        active = artifact.get("active_version") if isinstance(artifact.get("active_version"), dict) else None
        if not active:
            continue
        source = str(active.get("content_text") or "").strip()
        if source:
            parsed = _latex_to_plain_text(source)
            if parsed:
                return parsed
    resume_profile = repository.get_resume_profile(conn)
    baseline = resume_profile.get("baseline_resume_json") if isinstance(resume_profile, dict) else {}
    if isinstance(baseline, dict):
        return _resume_profile_baseline_to_text(baseline)
    return ""


def _load_prepared_evidence_assets(conn: Any) -> dict[str, Any]:
    explicit_assets = repository.get_candidate_evidence_assets_data(conn)
    candidate_profile = repository.get_profile(conn)
    resume_profile = repository.get_resume_profile_data(conn)
    return prepare_candidate_evidence_assets(explicit_assets, candidate_profile, resume_profile)


@app.get("/api/artifacts/{artifact_id}/latex", response_model=ArtifactLatexDocument)
def get_artifact_latex_document(artifact_id: str) -> ArtifactLatexDocument:
    conn = _conn()
    try:
        artifact = _resolve_latex_artifact(conn, artifact_id)
        return _artifact_latex_document_from_artifact(artifact)
    finally:
        conn.close()


@app.post("/api/artifacts/{artifact_id}/latex/save", response_model=ArtifactVersion)
def save_artifact_latex_document(artifact_id: str, payload: SaveArtifactLatexRequest) -> ArtifactVersion:
    conn = _conn()
    try:
        artifact = _resolve_latex_artifact(conn, artifact_id)
        active = artifact.get("active_version") if isinstance(artifact.get("active_version"), dict) else {}
        meta = dict(active.get("meta_json") or {}) if isinstance(active.get("meta_json"), dict) else {}
        meta.update(
            {
                "templateId": payload.template_id,
                "sourceKind": "latex",
                "compile_status": "never",
                "compile_error": None,
                "compiled_at": None,
                "compile_log_tail": None,
                "compile_diagnostics": [],
                "pdf_path": None,
            }
        )
        version = repository.create_artifact_version(
            conn,
            artifact_id=artifact_id,
            label=payload.label,
            content_json={},
            content_text=payload.source_text,
            meta_json=meta,
            created_by=payload.created_by,
            base_version_id=str(active.get("id")) if active.get("id") else None,
        )
        _invalidate_job_detail(str(artifact["job_id"]))
        _invalidate_job_collections()
        return ArtifactVersion(**version)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        conn.close()


@app.post("/api/artifacts/{artifact_id}/latex/recompile", response_model=ArtifactLatexDocument)
def recompile_artifact_latex_document(artifact_id: str, payload: RecompileArtifactLatexRequest) -> ArtifactLatexDocument:
    conn = _conn()
    try:
        artifact = _resolve_latex_artifact(conn, artifact_id)
        active = artifact.get("active_version") if isinstance(artifact.get("active_version"), dict) else {}
        if not active:
            raise HTTPException(status_code=400, detail="Artifact has no active version")

        source_text = payload.source_text if payload.source_text is not None else str(active.get("content_text") or "")
        template_id = payload.template_id or str((active.get("meta_json") or {}).get("templateId") or "classic")
        base_meta = dict(active.get("meta_json") or {}) if isinstance(active.get("meta_json"), dict) else {}
        save_version = repository.create_artifact_version(
            conn,
            artifact_id=artifact_id,
            label="draft",
            content_json={},
            content_text=source_text,
            meta_json={**base_meta, "templateId": template_id, "sourceKind": "latex"},
            created_by=payload.created_by,
            base_version_id=str(active.get("id")) if active.get("id") else None,
        )
        compile_result = compile_resume_tex(
            artifact_id=artifact_id,
            version=int(save_version["version"]),
            source_text=source_text,
        )
        meta = dict(save_version.get("meta_json") or {})
        meta["compiled_at"] = _now_iso()
        meta["compile_log_tail"] = compile_result.get("log_tail")
        meta["compile_diagnostics"] = compile_result.get("diagnostics") if isinstance(compile_result.get("diagnostics"), list) else []
        if compile_result.get("ok"):
            meta["compile_status"] = "ok"
            meta["compile_error"] = None
            meta["pdf_path"] = compile_result.get("pdf_path")
        else:
            meta["compile_status"] = "failed"
            meta["compile_error"] = "Compile failed"
            meta["pdf_path"] = None
        conn.execute(
            "UPDATE artifact_versions SET meta_json = ? WHERE id = ?",
            (json.dumps(meta, separators=(",", ":"), ensure_ascii=True), str(save_version["id"])),
        )
        conn.commit()
        artifact = repository.get_artifact(conn, artifact_id) or artifact
        _invalidate_job_detail(str(artifact["job_id"]))
        _invalidate_job_collections()
        return _artifact_latex_document_from_artifact(artifact)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        conn.close()


@app.get("/api/artifacts/{artifact_id}/latex/pdf")
def get_artifact_latex_pdf(artifact_id: str) -> Response:
    conn = _conn()
    try:
        artifact = _resolve_latex_artifact(conn, artifact_id)
        active = artifact.get("active_version") if isinstance(artifact.get("active_version"), dict) else {}
        version = active.get("version")
        if not isinstance(version, int):
            raise HTTPException(status_code=404, detail="No compiled PDF available")
        path = compiled_pdf_path(str(artifact_id), int(version))
        if not path.exists():
            raise HTTPException(status_code=404, detail="Compiled PDF file not found")
        artifact_type = str(artifact.get("artifact_type") or "artifact")
        filename = f"{artifact_type}-v{active.get('version', 'latest')}.pdf"
        return Response(
            content=path.read_bytes(),
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={filename}"},
        )
    finally:
        conn.close()


@app.get("/api/artifacts/{artifact_id}/resume-latex", response_model=ResumeLatexDocument)
def get_resume_latex_document(artifact_id: str) -> ResumeLatexDocument:
    conn = _conn()
    try:
        artifact = _resolve_latex_artifact(conn, artifact_id)
        if str(artifact.get("artifact_type")) != "resume":
            raise HTTPException(status_code=422, detail="Artifact is not a resume")
        return _resume_latex_document_from_artifact(artifact)
    finally:
        conn.close()


@app.post("/api/artifacts/{artifact_id}/resume-latex/save", response_model=ArtifactVersion)
def save_resume_latex_document(artifact_id: str, payload: SaveResumeLatexRequest) -> ArtifactVersion:
    return save_artifact_latex_document(
        artifact_id,
        SaveArtifactLatexRequest(
            source_text=payload.source_text,
            template_id=payload.template_id,
            label=payload.label,
            created_by=payload.created_by,
        ),
    )


@app.post("/api/artifacts/{artifact_id}/resume-latex/recompile", response_model=ResumeLatexDocument)
def recompile_resume_latex_document(artifact_id: str, payload: RecompileResumeLatexRequest) -> ResumeLatexDocument:
    generic = recompile_artifact_latex_document(
        artifact_id,
        RecompileArtifactLatexRequest(
            source_text=payload.source_text,
            template_id=payload.template_id,
            created_by=payload.created_by,
        ),
    )
    return ResumeLatexDocument(
        artifact_id=generic.artifact_id,
        version_id=generic.version_id,
        version=generic.version,
        source_text=generic.source_text,
        template_id=generic.template_id,
        compile_status=generic.compile_status,
        compile_error=generic.compile_error,
        pdf_available=generic.pdf_available,
        compiled_at=generic.compiled_at,
        log_tail=generic.log_tail,
        diagnostics=generic.diagnostics,
    )


@app.post("/api/artifacts/{artifact_id}/resume-latex/swarm-runs", response_model=ResumeSwarmRunStartResponse)
def start_resume_agents_swarm_run(artifact_id: str, payload: ResumeSwarmRunStartRequest) -> ResumeSwarmRunStartResponse:
    conn = _conn()
    try:
        artifact = _resolve_latex_artifact(conn, artifact_id)
        if str(artifact.get("artifact_type")) != "resume":
            raise HTTPException(status_code=422, detail="Artifact is not a resume")
        active = artifact.get("active_version") if isinstance(artifact.get("active_version"), dict) else {}
        base_meta = dict(active.get("meta_json") or {}) if isinstance(active.get("meta_json"), dict) else {}
        source_text = payload.source_text if payload.source_text is not None else str(active.get("content_text") or "")
        if not source_text.strip():
            raise HTTPException(status_code=400, detail="Resume LaTeX is empty")
        template_id = str(payload.template_id or base_meta.get("templateId") or "classic").strip() or "classic"
        job_id = str(artifact["job_id"])
        job = repository.get_job_detail(conn, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found for artifact")
        enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
        job_description = str(enrichment.get("formatted_description") or job.get("description") or "").strip()
        if not job_description:
            raise HTTPException(status_code=400, detail="Job description is empty")
        evidence_assets = _load_prepared_evidence_assets(conn)
        evidence_context = evidence_assets.get("evidence_context") if isinstance(evidence_assets, dict) else {}
        brag_document_markdown = str((evidence_assets or {}).get("brag_document_markdown") or "")
        project_cards = (evidence_assets or {}).get("project_cards") if isinstance(evidence_assets, dict) else []
        do_not_claim = (evidence_assets or {}).get("do_not_claim") if isinstance(evidence_assets, dict) else []
        run = _new_swarm_run(
            artifact_id=artifact_id,
            job_id=job_id,
            job_url=str(artifact["job_url"]),
            cycles=int(payload.cycles),
            pipeline="resume",
            template_id=template_id,
        )
        run_id = str(run["run_id"])
        with _SWARM_RUNS_LOCK:
            _SWARM_RUNS[run_id] = run
            event = _append_swarm_event(run, stage="queued", message="AI rewrite queued.")
            snapshot = dict(run)
        _queue_persist_swarm_run(snapshot)
        _queue_persist_swarm_event(run_id, event)
        _start_swarm_run_background(
            run_id,
            job_description=job_description,
            latex_source=source_text,
            resume_text="",
            evidence_context=evidence_context if isinstance(evidence_context, dict) else {},
            brag_document_markdown=brag_document_markdown,
            project_cards=project_cards if isinstance(project_cards, list) else [],
            do_not_claim=do_not_claim if isinstance(do_not_claim, list) else [],
            evidence_pack=None,
            cycles=int(payload.cycles),
            pipeline="resume",
        )
        return ResumeSwarmRunStartResponse(run_id=run_id, status="queued")
    finally:
        conn.close()


@app.get("/api/artifacts/{artifact_id}/resume-latex/swarm-runs/{run_id}", response_model=ResumeSwarmRunStatusResponse)
def get_resume_agents_swarm_run_status(artifact_id: str, run_id: str) -> ResumeSwarmRunStatusResponse:
    with _SWARM_RUNS_LOCK:
        run = _SWARM_RUNS.get(run_id)
    if not run:
        run = _load_swarm_run_from_store(run_id)
        if run:
            with _SWARM_RUNS_LOCK:
                _SWARM_RUNS[run_id] = run
    if not run:
        raise HTTPException(status_code=404, detail="AI rewrite run not found")
    if str(run.get("artifact_id")) != artifact_id:
        raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
    if str(run.get("pipeline") or "") != "resume":
        raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
    return _serialize_swarm_run(run)


@app.post("/api/artifacts/{artifact_id}/resume-latex/swarm-runs/{run_id}/cancel", response_model=ResumeSwarmRunStatusResponse)
def cancel_resume_agents_swarm_run(artifact_id: str, run_id: str) -> ResumeSwarmRunStatusResponse:
    with _SWARM_RUNS_LOCK:
        run = _SWARM_RUNS.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="AI rewrite run not found")
        if str(run.get("artifact_id")) != artifact_id:
            raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
        if str(run.get("pipeline") or "") != "resume":
            raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
        if str(run.get("status")) in {"completed", "failed", "cancelled"}:
            return _serialize_swarm_run(run)
        run["cancel_requested"] = True
        run["status"] = "cancelled"
        run["current_stage"] = "cancelled"
        run["updated_at"] = _now_iso()
        event = _append_swarm_event(run, stage="cancelled", message="AI rewrite stopped by user.")
        snapshot = dict(run)
    _queue_persist_swarm_run(snapshot)
    _queue_persist_swarm_event(run_id, event)
    with _SWARM_RUNS_LOCK:
        run = _SWARM_RUNS.get(run_id) or run
        return _serialize_swarm_run(run)


@app.post("/api/artifacts/{artifact_id}/resume-latex/swarm-runs/{run_id}/confirm-save", response_model=ResumeSwarmOptimizeResponse)
def confirm_resume_agents_swarm_run_save(artifact_id: str, run_id: str, payload: ResumeSwarmConfirmSaveRequest) -> ResumeSwarmOptimizeResponse:
    conn = _conn()
    try:
        artifact = _resolve_latex_artifact(conn, artifact_id)
        if str(artifact.get("artifact_type")) != "resume":
            raise HTTPException(status_code=422, detail="Artifact is not a resume")
        active = artifact.get("active_version") if isinstance(artifact.get("active_version"), dict) else {}
        with _SWARM_RUNS_LOCK:
            run = _SWARM_RUNS.get(run_id)
            if not run:
                raise HTTPException(status_code=404, detail="AI rewrite run not found")
            if str(run.get("artifact_id")) != artifact_id:
                raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
            if str(run.get("pipeline") or "") != "resume":
                raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
            if str(run.get("status")) != "awaiting_confirmation":
                raise HTTPException(status_code=409, detail="AI rewrite run is not ready for confirmation")
            candidate_latex = str(run.get("candidate_latex") or "")
            if not candidate_latex.strip():
                raise HTTPException(status_code=409, detail="No candidate resume to save")
            final_score = run.get("final_score") if isinstance(run.get("final_score"), dict) else {}
            history = list(run.get("events") or [])
            run["status"] = "saving"
            run["current_stage"] = "saving"
            run["updated_at"] = _now_iso()
            saving_event = _append_swarm_event(run, stage="saving", message="Saving AI draft.")
            saving_snapshot = dict(run)
        _queue_persist_swarm_run(saving_snapshot)
        _queue_persist_swarm_event(run_id, saving_event)

        base_meta = dict(active.get("meta_json") or {}) if isinstance(active.get("meta_json"), dict) else {}
        template_id = str(run.get("template_id") or base_meta.get("templateId") or "classic").strip() or "classic"
        meta = {
            **base_meta,
            "templateId": template_id,
            "sourceKind": "latex",
            "compile_status": "never",
            "compile_error": None,
            "compiled_at": None,
            "compile_log_tail": None,
            "compile_diagnostics": [],
            "pdf_path": None,
            "swarm_optimize_at": _now_iso(),
            "swarm_cycles": int(run.get("cycles_target") or 2),
            "swarm_run_id": run_id,
        }
        version = repository.create_artifact_version(
            conn,
            artifact_id=artifact_id,
            label=payload.label,
            content_json={},
            content_text=candidate_latex,
            meta_json=meta,
            created_by=payload.created_by,
            base_version_id=str(active.get("id")) if active.get("id") else None,
        )
        _invalidate_job_detail(str(artifact["job_id"]))
        _invalidate_job_collections()
        with _SWARM_RUNS_LOCK:
            run = _SWARM_RUNS.get(run_id)
            if run:
                run["status"] = "completed"
                run["current_stage"] = "done"
                run["updated_at"] = _now_iso()
                done_event = _append_swarm_event(run, stage="done", message=f"Saved AI draft v{int(version['version'])}.")
                done_snapshot = dict(run)
            else:
                done_event = None
                done_snapshot = None
        if done_snapshot is not None and done_event is not None:
            _queue_persist_swarm_run(done_snapshot)
            _queue_persist_swarm_event(run_id, done_event)
        return ResumeSwarmOptimizeResponse(
            artifact_id=artifact_id,
            version_id=str(version["id"]),
            version=int(version["version"]),
            final_score=final_score,
            history=history,
        )
    finally:
        conn.close()


@app.post("/api/artifacts/{artifact_id}/cover-letter-latex/swarm-runs", response_model=ResumeSwarmRunStartResponse)
def start_cover_letter_agents_swarm_run(artifact_id: str, payload: ResumeSwarmRunStartRequest) -> ResumeSwarmRunStartResponse:
    conn = _conn()
    try:
        artifact = _resolve_latex_artifact(conn, artifact_id)
        if str(artifact.get("artifact_type")) != "cover_letter":
            raise HTTPException(status_code=422, detail="Artifact is not a cover letter")
        active = artifact.get("active_version") if isinstance(artifact.get("active_version"), dict) else {}
        base_meta = dict(active.get("meta_json") or {}) if isinstance(active.get("meta_json"), dict) else {}
        source_text = payload.source_text if payload.source_text is not None else str(active.get("content_text") or "")
        if not source_text.strip():
            raise HTTPException(status_code=400, detail="Cover letter LaTeX is empty")
        template_id = str(payload.template_id or base_meta.get("templateId") or "classic").strip() or "classic"
        job_id = str(artifact["job_id"])
        job_url = str(artifact["job_url"])
        job = repository.get_job_detail(conn, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found for artifact")
        enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
        job_description = str(enrichment.get("formatted_description") or job.get("description") or "").strip()
        if not job_description:
            raise HTTPException(status_code=400, detail="Job description is empty")
        resume_text = _resolve_resume_text_for_cover_letter(conn, job_id).strip()
        if not resume_text:
            raise HTTPException(status_code=400, detail="No resume text available for cover letter drafting")
        evidence_assets = _load_prepared_evidence_assets(conn)
        evidence_context = evidence_assets.get("evidence_context") if isinstance(evidence_assets, dict) else {}
        brag_document_markdown = str((evidence_assets or {}).get("brag_document_markdown") or "")
        project_cards = (evidence_assets or {}).get("project_cards") if isinstance(evidence_assets, dict) else []
        do_not_claim = (evidence_assets or {}).get("do_not_claim") if isinstance(evidence_assets, dict) else []
        run = _new_swarm_run(
            artifact_id=artifact_id,
            job_id=job_id,
            job_url=job_url,
            cycles=int(payload.cycles),
            pipeline="cover_letter",
            template_id=template_id,
        )
        run_id = str(run["run_id"])
        with _SWARM_RUNS_LOCK:
            _SWARM_RUNS[run_id] = run
            event = _append_swarm_event(run, stage="queued", message="AI rewrite queued.")
            snapshot = dict(run)
        _queue_persist_swarm_run(snapshot)
        _queue_persist_swarm_event(run_id, event)
        _start_swarm_run_background(
            run_id,
            job_description=job_description,
            latex_source=source_text,
            resume_text=resume_text,
            evidence_context=evidence_context if isinstance(evidence_context, dict) else {},
            brag_document_markdown=brag_document_markdown,
            project_cards=project_cards if isinstance(project_cards, list) else [],
            do_not_claim=do_not_claim if isinstance(do_not_claim, list) else [],
            evidence_pack=None,
            cycles=int(payload.cycles),
            pipeline="cover_letter",
        )
        return ResumeSwarmRunStartResponse(run_id=run_id, status="queued")
    finally:
        conn.close()


@app.get("/api/artifacts/{artifact_id}/cover-letter-latex/swarm-runs/{run_id}", response_model=ResumeSwarmRunStatusResponse)
def get_cover_letter_agents_swarm_run_status(artifact_id: str, run_id: str) -> ResumeSwarmRunStatusResponse:
    with _SWARM_RUNS_LOCK:
        run = _SWARM_RUNS.get(run_id)
    if not run:
        run = _load_swarm_run_from_store(run_id)
        if run:
            with _SWARM_RUNS_LOCK:
                _SWARM_RUNS[run_id] = run
    if not run:
        raise HTTPException(status_code=404, detail="AI rewrite run not found")
    if str(run.get("artifact_id")) != artifact_id:
        raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
    if str(run.get("pipeline") or "") != "cover_letter":
        raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
    return _serialize_swarm_run(run)


@app.post("/api/artifacts/{artifact_id}/cover-letter-latex/swarm-runs/{run_id}/cancel", response_model=ResumeSwarmRunStatusResponse)
def cancel_cover_letter_agents_swarm_run(artifact_id: str, run_id: str) -> ResumeSwarmRunStatusResponse:
    with _SWARM_RUNS_LOCK:
        run = _SWARM_RUNS.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="AI rewrite run not found")
        if str(run.get("artifact_id")) != artifact_id:
            raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
        if str(run.get("pipeline") or "") != "cover_letter":
            raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
        if str(run.get("status")) in {"completed", "failed", "cancelled"}:
            return _serialize_swarm_run(run)
        run["cancel_requested"] = True
        run["status"] = "cancelled"
        run["current_stage"] = "cancelled"
        run["updated_at"] = _now_iso()
        event = _append_swarm_event(run, stage="cancelled", message="AI rewrite stopped by user.")
        snapshot = dict(run)
    _queue_persist_swarm_run(snapshot)
    _queue_persist_swarm_event(run_id, event)
    with _SWARM_RUNS_LOCK:
        run = _SWARM_RUNS.get(run_id) or run
        return _serialize_swarm_run(run)


@app.post("/api/artifacts/{artifact_id}/cover-letter-latex/swarm-runs/{run_id}/confirm-save", response_model=ResumeSwarmOptimizeResponse)
def confirm_cover_letter_agents_swarm_run_save(artifact_id: str, run_id: str, payload: ResumeSwarmConfirmSaveRequest) -> ResumeSwarmOptimizeResponse:
    conn = _conn()
    try:
        artifact = _resolve_latex_artifact(conn, artifact_id)
        if str(artifact.get("artifact_type")) != "cover_letter":
            raise HTTPException(status_code=422, detail="Artifact is not a cover letter")
        active = artifact.get("active_version") if isinstance(artifact.get("active_version"), dict) else {}
        with _SWARM_RUNS_LOCK:
            run = _SWARM_RUNS.get(run_id)
            if not run:
                raise HTTPException(status_code=404, detail="AI rewrite run not found")
            if str(run.get("artifact_id")) != artifact_id:
                raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
            if str(run.get("pipeline") or "") != "cover_letter":
                raise HTTPException(status_code=404, detail="AI rewrite run not found for artifact")
            if str(run.get("status")) != "awaiting_confirmation":
                raise HTTPException(status_code=409, detail="AI rewrite run is not ready for confirmation")
            candidate_latex = str(run.get("candidate_latex") or "")
            if not candidate_latex.strip():
                raise HTTPException(status_code=409, detail="No candidate cover letter to save")
            final_score = run.get("final_score") if isinstance(run.get("final_score"), dict) else {}
            history = list(run.get("events") or [])
            run["status"] = "saving"
            run["current_stage"] = "saving"
            run["updated_at"] = _now_iso()
            saving_event = _append_swarm_event(run, stage="saving", message="Saving AI draft.")
            saving_snapshot = dict(run)
        _queue_persist_swarm_run(saving_snapshot)
        _queue_persist_swarm_event(run_id, saving_event)

        base_meta = dict(active.get("meta_json") or {}) if isinstance(active.get("meta_json"), dict) else {}
        template_id = str(run.get("template_id") or base_meta.get("templateId") or "classic_cover_letter").strip() or "classic_cover_letter"
        meta = {
            **base_meta,
            "templateId": template_id,
            "sourceKind": "latex",
            "compile_status": "never",
            "compile_error": None,
            "compiled_at": None,
            "compile_log_tail": None,
            "compile_diagnostics": [],
            "pdf_path": None,
            "cover_letter_agents_swarm_optimize_at": _now_iso(),
            "cover_letter_agents_swarm_cycles": int(run.get("cycles_target") or 2),
            "cover_letter_agents_swarm_run_id": run_id,
        }
        version = repository.create_artifact_version(
            conn,
            artifact_id=artifact_id,
            label=payload.label,
            content_json={},
            content_text=candidate_latex,
            meta_json=meta,
            created_by=payload.created_by,
            base_version_id=str(active.get("id")) if active.get("id") else None,
        )
        _invalidate_job_detail(str(artifact["job_id"]))
        _invalidate_job_collections()
        with _SWARM_RUNS_LOCK:
            run = _SWARM_RUNS.get(run_id)
            if run:
                run["status"] = "completed"
                run["current_stage"] = "done"
                run["updated_at"] = _now_iso()
                done_event = _append_swarm_event(run, stage="done", message=f"Saved AI draft v{int(version['version'])}.")
                done_snapshot = dict(run)
            else:
                done_event = None
                done_snapshot = None
        if done_snapshot is not None and done_event is not None:
            _queue_persist_swarm_run(done_snapshot)
            _queue_persist_swarm_event(run_id, done_event)
        return ResumeSwarmOptimizeResponse(
            artifact_id=artifact_id,
            version_id=str(version["id"]),
            version=int(version["version"]),
            final_score=final_score,
            history=history,
        )
    finally:
        conn.close()


@app.post("/api/artifacts/{artifact_id}/resume-latex/swarm-optimize", response_model=ResumeSwarmOptimizeResponse)
def optimize_resume_with_swarm(artifact_id: str, payload: ResumeSwarmOptimizeRequest) -> ResumeSwarmOptimizeResponse:
    conn = _conn()
    try:
        artifact = _resolve_latex_artifact(conn, artifact_id)
        if str(artifact.get("artifact_type")) != "resume":
            raise HTTPException(status_code=422, detail="Artifact is not a resume")
        active = artifact.get("active_version") if isinstance(artifact.get("active_version"), dict) else {}
        if not active:
            raise HTTPException(status_code=400, detail="Artifact has no active version")
        source_text = str(active.get("content_text") or "")
        if not source_text.strip():
            raise HTTPException(status_code=400, detail="Active resume LaTeX is empty")

        job = repository.get_job_detail(conn, str(artifact["job_id"]))
        if not job:
            raise HTTPException(status_code=404, detail="Job not found for artifact")
        enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
        job_description = str(enrichment.get("formatted_description") or job.get("description") or "").strip()
        if not job_description:
            raise HTTPException(status_code=400, detail="Job description is empty")
        evidence_assets = _load_prepared_evidence_assets(conn)
        evidence_context = evidence_assets.get("evidence_context") if isinstance(evidence_assets, dict) else {}
        brag_document_markdown = str((evidence_assets or {}).get("brag_document_markdown") or "")
        project_cards = (evidence_assets or {}).get("project_cards") if isinstance(evidence_assets, dict) else []
        do_not_claim = (evidence_assets or {}).get("do_not_claim") if isinstance(evidence_assets, dict) else []
        evidence_pack = build_runtime_evidence_pack(
            job_description,
            evidence_assets if isinstance(evidence_assets, dict) else {},
            profile_id="default",
        )

        result = run_resume_agents_swarm_optimization(
            job_description=job_description,
            resume_text="",
            latex_resume=source_text,
            evidence_context=evidence_context if isinstance(evidence_context, dict) else {},
            brag_document_markdown=brag_document_markdown,
            project_cards=project_cards if isinstance(project_cards, list) else [],
            do_not_claim=do_not_claim if isinstance(do_not_claim, list) else [],
            evidence_pack=evidence_pack,
            cycles=payload.cycles,
        )
        final_latex = str(result.get("final_latex_resume") or source_text)
        final_score = result.get("final_score")
        history = result.get("history")

        base_meta = dict(active.get("meta_json") or {}) if isinstance(active.get("meta_json"), dict) else {}
        template_id = str(base_meta.get("templateId") or "classic")
        meta = {
            **base_meta,
            "templateId": template_id,
            "sourceKind": "latex",
            "compile_status": "never",
            "compile_error": None,
            "compiled_at": None,
            "compile_log_tail": None,
            "compile_diagnostics": [],
            "pdf_path": None,
            "swarm_optimize_at": _now_iso(),
            "swarm_cycles": int(payload.cycles),
        }
        version = repository.create_artifact_version(
            conn,
            artifact_id=artifact_id,
            label="draft",
            content_json={},
            content_text=final_latex,
            meta_json=meta,
            created_by=payload.created_by,
            base_version_id=str(active.get("id")) if active.get("id") else None,
        )
        _invalidate_job_detail(str(artifact["job_id"]))
        _invalidate_job_collections()
        return ResumeSwarmOptimizeResponse(
            artifact_id=artifact_id,
            version_id=str(version["id"]),
            version=int(version["version"]),
            final_score=final_score if isinstance(final_score, dict) else {},
            history=history if isinstance(history, list) else [],
        )
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        conn.close()


@app.post("/api/artifacts/{artifact_id}/cover-letter-latex/swarm-optimize", response_model=ResumeSwarmOptimizeResponse)
def optimize_cover_letter_with_swarm(artifact_id: str, payload: ResumeSwarmOptimizeRequest) -> ResumeSwarmOptimizeResponse:
    conn = _conn()
    try:
        artifact = _resolve_latex_artifact(conn, artifact_id)
        if str(artifact.get("artifact_type")) != "cover_letter":
            raise HTTPException(status_code=422, detail="Artifact is not a cover letter")
        active = artifact.get("active_version") if isinstance(artifact.get("active_version"), dict) else {}
        if not active:
            raise HTTPException(status_code=400, detail="Artifact has no active version")
        source_text = str(active.get("content_text") or "")
        if not source_text.strip():
            raise HTTPException(status_code=400, detail="Active cover letter LaTeX is empty")

        job_id = str(artifact["job_id"])
        job_url = str(artifact["job_url"])
        job = repository.get_job_detail(conn, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found for artifact")
        enrichment = job.get("enrichment") if isinstance(job.get("enrichment"), dict) else {}
        job_description = str(enrichment.get("formatted_description") or job.get("description") or "").strip()
        if not job_description:
            raise HTTPException(status_code=400, detail="Job description is empty")
        resume_text = _resolve_resume_text_for_cover_letter(conn, job_id).strip()
        if not resume_text:
            raise HTTPException(status_code=400, detail="No resume text available for cover letter drafting")
        evidence_assets = _load_prepared_evidence_assets(conn)
        evidence_context = evidence_assets.get("evidence_context") if isinstance(evidence_assets, dict) else {}
        brag_document_markdown = str((evidence_assets or {}).get("brag_document_markdown") or "")
        project_cards = (evidence_assets or {}).get("project_cards") if isinstance(evidence_assets, dict) else []
        do_not_claim = (evidence_assets or {}).get("do_not_claim") if isinstance(evidence_assets, dict) else []
        evidence_pack = build_runtime_evidence_pack(
            job_description,
            evidence_assets if isinstance(evidence_assets, dict) else {},
            profile_id="default",
        )

        result = run_cover_letter_agents_swarm_optimization(
            job_description=job_description,
            resume_text=resume_text,
            latex_cover_letter=source_text,
            evidence_context=evidence_context if isinstance(evidence_context, dict) else {},
            brag_document_markdown=brag_document_markdown,
            project_cards=project_cards if isinstance(project_cards, list) else [],
            do_not_claim=do_not_claim if isinstance(do_not_claim, list) else [],
            evidence_pack=evidence_pack,
            cycles=payload.cycles,
        )
        final_latex = str(result.get("final_latex_cover_letter") or source_text)
        final_score = result.get("final_score")
        history = result.get("history")

        base_meta = dict(active.get("meta_json") or {}) if isinstance(active.get("meta_json"), dict) else {}
        template_id = str(base_meta.get("templateId") or "classic_cover_letter")
        meta = {
            **base_meta,
            "templateId": template_id,
            "sourceKind": "latex",
            "compile_status": "never",
            "compile_error": None,
            "compiled_at": None,
            "compile_log_tail": None,
            "compile_diagnostics": [],
            "pdf_path": None,
            "cover_letter_agents_swarm_optimize_at": _now_iso(),
            "cover_letter_agents_swarm_cycles": int(payload.cycles),
        }
        version = repository.create_artifact_version(
            conn,
            artifact_id=artifact_id,
            label="draft",
            content_json={},
            content_text=final_latex,
            meta_json=meta,
            created_by=payload.created_by,
            base_version_id=str(active.get("id")) if active.get("id") else None,
        )
        _invalidate_job_detail(str(artifact["job_id"]))
        _invalidate_job_collections()
        return ResumeSwarmOptimizeResponse(
            artifact_id=artifact_id,
            version_id=str(version["id"]),
            version=int(version["version"]),
            final_score=final_score if isinstance(final_score, dict) else {},
            history=history if isinstance(history, list) else [],
        )
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        conn.close()


@app.get("/api/artifacts/{artifact_id}/resume-latex/pdf")
def get_resume_latex_pdf(artifact_id: str) -> Response:
    return get_artifact_latex_pdf(artifact_id)


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
        meta = dict(active.get("meta_json") or {}) if isinstance(active.get("meta_json"), dict) else {}
        source_kind = str(meta.get("sourceKind") or "").strip().lower()
        version = active.get("version")
        if source_kind == "latex" and isinstance(version, int):
            path = compiled_pdf_path(str(artifact_id), int(version))
            if path.exists():
                filename = f"{artifact['artifact_type']}-v{active.get('version', 'latest')}.pdf"
                return Response(
                    content=path.read_bytes(),
                    media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={filename}"},
                )
            raise HTTPException(status_code=409, detail="Artifact not compiled yet. Click Recompile first.")
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


@app.get("/api/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: str, request: Request) -> JobDetail:
    client_id = _client_from_request(request)
    conn = _conn()
    try:
        key = _job_cache_key_for_client(client_id, job_id)
        cached = cache.get_json(key)
        if isinstance(cached, dict):
            _touch_job_detail_lru(client_id, key)
            cache.expire(key, _TTL_JOB_DETAIL)
            return JobDetail(**cached)
        item = repository.get_job_detail(conn, job_id)
        if not item:
            raise HTTPException(status_code=404, detail="Job not found")
        response = JobDetail(**item)
        cache.set_json(key, response.model_dump(), _TTL_JOB_DETAIL)
        _touch_job_detail_lru(client_id, key)
        cache.expire(key, _TTL_JOB_DETAIL)
        return response
    finally:
        conn.close()


@app.post("/api/jobs/{job_id}/events", response_model=JobEvent)
def post_event(job_id: str, payload: CreateEventRequest, request: Request) -> JobEvent:
    conn = _conn()
    try:
        event = repository.create_event(conn, job_id, payload.model_dump())
        response = JobEvent(**event)
        _invalidate_job_detail(job_id)
        cache.delete(_stats_cache_key())
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
        cache.delete_pattern(f"{_CACHE_NS}:user:*:events:*")
        cache.delete(_stats_cache_key())
        return {"deleted": changed}
    finally:
        conn.close()


@app.delete("/api/jobs/{job_id}")
def remove_job(job_id: str) -> dict[str, int]:
    conn = _conn()
    try:
        changed = repository.delete_job(conn, job_id)
        if changed == 0:
            raise HTTPException(status_code=404, detail="Job not found")
        _invalidate_job_detail(job_id)
        _invalidate_job_collections()
        return {"deleted": changed}
    finally:
        conn.close()


@app.post("/api/jobs/{job_id}/suppress")
def suppress_job(job_id: str, payload: SuppressJobRequest) -> dict[str, int]:
    conn = _conn()
    try:
        repository.suppress_job(conn, job_id=job_id, reason=payload.reason, created_by="ui")
        changed = 1
    finally:
        conn.close()
    _invalidate_job_detail(job_id)
    _invalidate_job_collections()
    return {"suppressed": changed}


@app.post("/api/jobs/{job_id}/unsuppress")
def unsuppress_job(job_id: str) -> dict[str, int]:
    conn = _conn()
    try:
        changed = repository.unsuppress_job(conn, job_id=job_id)
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
