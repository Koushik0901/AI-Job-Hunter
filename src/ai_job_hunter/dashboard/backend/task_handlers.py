from __future__ import annotations

import logging
import os
from typing import Any

from ai_job_hunter.db import update_workspace_operation
from ai_job_hunter.dashboard.backend import artifacts as artifact_svc
from ai_job_hunter.dashboard.backend import repository
from ai_job_hunter.dashboard.backend import stories as story_svc
from ai_job_hunter.dashboard.backend.cache import get_dashboard_cache
from ai_job_hunter.dashboard.backend.utils import now_iso, resolve_db_config
from ai_job_hunter.db import get_workspace_operation, init_db

logger = logging.getLogger(__name__)


def _conn() -> Any:
    db_url, db_token = resolve_db_config()
    return init_db(db_url, db_token)


def _mark_operation(
    operation_id: str,
    *,
    status: str,
    summary: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    conn = _conn()
    try:
        patch: dict[str, Any] = {"status": status}
        if summary is not None:
            patch["summary"] = summary
        if error is not None:
            patch["error"] = error
        if status in {"completed", "failed"}:
            patch["finished_at"] = now_iso()
        update_workspace_operation(conn, operation_id, patch)
    finally:
        conn.close()


def _invalidate_after_task(
    kind: str, params: dict[str, Any], operation_id: str | None = None
) -> None:
    try:
        cache = get_dashboard_cache()
        cache.startup()
        if kind == "dashboard_snapshot_refresh":
            cache.invalidate_jobs_lists()
            cache.invalidate_stats()
            cache.invalidate_for_assistant_change()
            cache.publish_dashboard_event(
                "refresh",
                "jobs",
                operation_id=operation_id,
            )
            return
        if kind == "artifact_generate":
            job_id = str(params.get("job_id") or "")
            if job_id:
                cache.invalidate_job_detail(job_id)
            cache.invalidate_for_assistant_change()
            cache.publish_dashboard_event(
                "refresh",
                "artifacts",
                job_id=job_id or None,
                operation_id=operation_id,
            )
        if kind == "resume_extract":
            cache.publish_dashboard_event(
                "refresh",
                "stories",
                operation_id=operation_id,
            )
    except Exception:
        logger.debug("Cache invalidation after task failed.", exc_info=True)


def _run_artifact_generate(params: dict[str, Any]) -> dict[str, Any]:
    job_id = str(params.get("job_id") or "")
    artifact_type = str(params.get("artifact_type") or "")
    base_doc_id = int(params.get("base_doc_id") or 0)
    conn = _conn()
    try:
        row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Job not found")
        model = (os.getenv("ARTIFACT_MODEL") or "openai/gpt-4o").strip()

        # Load story context once for both generation and save
        story_context, story_ids = artifact_svc.load_story_context_for_generation(job_id, conn)

        if artifact_type == "resume":
            content_md, story_ids = artifact_svc.generate_tailored_resume(
                job_id, base_doc_id, conn, story_context=story_context, story_ids_used=story_ids
            )
        elif artifact_type == "cover_letter":
            content_md, story_ids = artifact_svc.generate_cover_letter(
                job_id, base_doc_id, conn, story_context=story_context, story_ids_used=story_ids
            )
        else:
            raise ValueError("Unsupported artifact type")
        artifact = artifact_svc.save_artifact(
            job_id,
            artifact_type,
            content_md,
            base_doc_id,
            model,
            conn,
            story_ids_used=story_ids,
        )
        return {
            "job_id": job_id,
            "artifact_type": artifact_type,
            "artifact_id": int(artifact.get("id") or 0),
            "version": int(artifact.get("version") or 0),
            "stories_grounded": len(story_ids),
        }
    finally:
        conn.close()


def _run_snapshot_refresh(params: dict[str, Any]) -> dict[str, Any]:
    job_ids = [
        str(job_id).strip()
        for job_id in (params.get("job_ids") or [])
        if str(job_id).strip()
    ]
    conn = _conn()
    try:
        refreshed = repository.refresh_dashboard_snapshots(
            conn, job_ids=job_ids or None
        )
        return {"refreshed": refreshed, "job_ids": job_ids}
    finally:
        conn.close()


def _run_resume_extract(params: dict[str, Any]) -> dict[str, Any]:
    base_doc_id = int(params.get("base_doc_id") or 0)
    conn = _conn()
    try:
        doc = artifact_svc.get_base_document(base_doc_id, conn)
        if not doc:
            raise ValueError(f"Base document {base_doc_id} not found")
        result = story_svc.extract_from_resume(doc["content_md"])
        saved = story_svc.save_extracted_stories(result.get("stories") or [], conn)
        return {
            "base_doc_id": base_doc_id,
            "stories_drafted": len(saved),
            "story_ids": [s["id"] for s in saved],
            "profile_delta": result.get("profile_delta") or {},
        }
    finally:
        conn.close()


def _run_embed_stories(params: dict[str, Any]) -> dict[str, Any]:
    from ai_job_hunter.dashboard.backend.embeddings import embed_pending_jobs, embed_pending_stories
    conn = _conn()
    try:
        stories_embedded = embed_pending_stories(conn)
        jobs_embedded = embed_pending_jobs(conn, limit=int(params.get("limit") or 200))
        return {"stories_embedded": stories_embedded, "jobs_embedded": jobs_embedded}
    finally:
        conn.close()


def execute_task(kind: str, params: dict[str, Any]) -> dict[str, Any]:
    if kind == "artifact_generate":
        return _run_artifact_generate(params)
    if kind == "dashboard_snapshot_refresh":
        return _run_snapshot_refresh(params)
    if kind == "resume_extract":
        return _run_resume_extract(params)
    if kind == "embed_stories":
        return _run_embed_stories(params)
    raise ValueError(f"Unsupported task kind: {kind}")


def run_operation(operation_id: str, kind: str, params: dict[str, Any]) -> dict[str, Any]:
    _mark_operation(operation_id, status="running")
    try:
        summary = execute_task(kind, params)
        _mark_operation(operation_id, status="completed", summary=summary)
        _invalidate_after_task(kind, params, operation_id)
        return summary
    except Exception as error:
        logger.exception("Queued operation %s failed", kind)
        _mark_operation(
            operation_id,
            status="failed",
            summary={"kind": kind},
            error=str(error),
        )
        raise


def get_operation_status(operation_id: str) -> dict[str, Any] | None:
    conn = _conn()
    try:
        return get_workspace_operation(conn, operation_id)
    finally:
        conn.close()
