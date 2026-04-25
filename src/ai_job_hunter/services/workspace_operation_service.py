from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from rich.console import Console

from ai_job_hunter.db import (
    create_workspace_operation,
    get_candidate_profile,
    get_workspace_operation,
    list_workspace_operations,
    load_active_suppressed_urls,
    load_enabled_company_sources,
    load_enrichments_for_urls,
    load_jobs_for_jd_reformat,
    load_unenriched_jobs,
    update_workspace_operation,
    save_jobs,
)
from ai_job_hunter.dashboard.backend.cache import get_dashboard_cache
from ai_job_hunter.dashboard.backend import repository as dashboard_repository
from ai_job_hunter.enrich import run_description_reformat_pipeline, run_enrichment_pipeline
from ai_job_hunter.env_utils import env_or_default, now_iso
from ai_job_hunter.match_score import compute_match_score
from ai_job_hunter.services.scrape_service import scrape_all

logger = logging.getLogger(__name__)


def _operation_log(console: Console) -> str:
    try:
        return console.export_text(clear=False)[-6000:]
    except Exception:
        return ""


def run_workspace_operation(conn: Any, kind: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    operation_id = str(uuid.uuid4())
    operation = create_workspace_operation(
        conn,
        {
            "id": operation_id,
            "kind": kind,
            "status": "running",
            "params": params or {},
        },
    )
    console = Console(record=True, stderr=True)
    try:
        summary = _run_workspace_operation_body(conn, kind, params or {}, console)
        update_workspace_operation(
            conn,
            operation_id,
            {
                "status": "completed",
                "summary": summary,
                "log_tail": _operation_log(console),
                "finished_at": summary.get("finished_at"),
                "error": None,
            },
        )
    except Exception as error:
        update_workspace_operation(
            conn,
            operation_id,
            {
                "status": "failed",
                "summary": {"message": str(error)},
                "log_tail": _operation_log(console),
                "finished_at": now_iso(),
                "error": str(error),
            },
        )
    return get_workspace_operation(conn, operation_id) or operation


def execute_workspace_operation(
    conn: Any,
    kind: str,
    params: dict[str, Any] | None = None,
    *,
    console: Console | None = None,
) -> dict[str, Any]:
    active_console = console or Console(record=True, stderr=True)
    return _run_workspace_operation_body(conn, kind, params or {}, active_console)


def list_operations(conn: Any, limit: int = 20) -> list[dict[str, Any]]:
    return list_workspace_operations(conn, limit=limit)


def get_operation(conn: Any, operation_id: str) -> dict[str, Any] | None:
    return get_workspace_operation(conn, operation_id)


def _invalidate_dashboard_views() -> None:
    if os.getenv("DASHBOARD_CACHE_DISABLED", "").strip().lower() in {"1", "true", "yes"}:
        return
    try:
        cache = get_dashboard_cache()
        cache.startup()
        cache.invalidate_for_workspace_refresh()
    except Exception:
        logger.exception("Dashboard cache invalidation failed; continuing workspace operation.")


def _refresh_daily_briefing(conn: Any, *, trigger_source: str = "scrape") -> None:
    try:
        dashboard_repository.refresh_daily_briefing(conn, trigger_source=trigger_source)
    except Exception:
        # Workspace operations should not fail because briefing refresh failed.
        pass


def _set_processing_state_for_jobs(
    conn: Any,
    jobs: list[dict[str, Any]],
    *,
    state: str,
    step: str,
    message: str,
    last_error: str | None = None,
    increment_retry: bool = False,
) -> None:
    for job in jobs:
        job_id = str(job.get("id") or "")
        if not job_id:
            continue
        try:
            dashboard_repository.set_job_processing(
                conn,
                job_id,
                state=state,
                step=step,
                message=message,
                last_error=last_error,
                increment_retry=increment_retry,
                last_processed_at=now_iso() if state == "ready" else None,
            )
        except Exception:
            pass


def _run_workspace_operation_body(conn: Any, kind: str, params: dict[str, Any], console: Console) -> dict[str, Any]:
    if kind == "scrape":
        return _run_scrape(conn, params, console)
    if kind == "enrich_backfill":
        return _run_enrich(conn, params, console, force=False)
    if kind == "re_enrich_all":
        return _run_enrich(conn, params, console, force=True)
    if kind == "jd_reformat":
        return _run_jd_reformat(conn, params, console)
    if kind == "blurb_backfill":
        return _run_blurb_backfill(conn, params, console)
    raise ValueError(f"Unsupported workspace operation kind: {kind}")


def _run_blurb_backfill(conn: Any, params: dict[str, Any], console: Console) -> dict[str, Any]:
    """Generate LLM 'Kenji's read' blurbs for the top-N viable unapplied jobs.

    Cheap, idempotent, skippable on missing OPENROUTER_API_KEY. Does not touch
    scoring or enrichment — purely narrative post-processing.
    """
    from ai_job_hunter.dashboard.backend import reasoning_blurb
    force = bool(params.get("force", False))
    top_n = int(params.get("top_n") or 150)
    console.print(
        f"[bold]Blurb backfill:[/bold] scanning top {top_n} viable unapplied "
        f"(force={'yes' if force else 'no'})"
    )
    try:
        written = reasoning_blurb.generate_blurbs(
            conn, job_ids=None, force=force, top_n=top_n
        )
    except Exception as error:
        console.print(f"[red]Blurb backfill failed:[/red] {error}")
        raise
    # Snapshots cache the full job item (including llm_blurb) in payload_json.
    # Refresh ALL snapshots for this profile_version so jobs already blurbed in
    # earlier runs (but with stale payloads) also surface the llm_blurb field.
    try:
        from ai_job_hunter.dashboard.backend.repository import refresh_dashboard_snapshots
        # recompute=False: we only wrote reasoning_blurb. Recomputing scores
        # would INSERT OR REPLACE the rows and wipe the blurbs we just wrote.
        refresh_dashboard_snapshots(conn, recompute=False)
        console.print("[dim]Dashboard snapshots refreshed.[/dim]")
    except Exception as snap_error:
        console.print(f"[yellow]Snapshot refresh after blurb backfill failed:[/yellow] {snap_error}")
    _invalidate_dashboard_views()
    return {
        "blurbs_generated": len(written),
        "force": force,
        "top_n": top_n,
        "finished_at": now_iso(),
    }


def _run_scrape(conn: Any, params: dict[str, Any], console: Console) -> dict[str, Any]:
    companies = load_enabled_company_sources(conn)
    if not companies:
        raise RuntimeError("No enabled company sources found. Add or enable company sources first.")

    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_model = env_or_default("ENRICHMENT_MODEL", "openai/gpt-oss-120b")
    description_format_model = env_or_default("DESCRIPTION_FORMAT_MODEL", "openai/gpt-oss-120b")
    sort_by = str(params.get("sort_by") or "match")
    console.print(f"[bold]Scraping {len(companies)} enabled company sources[/bold]")
    jobs = scrape_all(
        companies,
        apply_location_filter=not bool(params.get("no_location_filter", False)),
        enrich=not bool(params.get("no_enrich", False)),
    )
    suppressed_urls = load_active_suppressed_urls(conn)
    if suppressed_urls:
        jobs = [job for job in jobs if str(job.get("url") or "") not in suppressed_urls]

    profile = get_candidate_profile(conn)
    url_to_enrichment = load_enrichments_for_urls(conn, [str(job.get("url") or "") for job in jobs if str(job.get("url") or "")])
    for job in jobs:
        enrichment = url_to_enrichment.get(str(job.get("url") or ""), {})
        # Semantic score is computed later by recompute_match_scores once job
        # embeddings exist; at scrape-time we score without it (neutral 55).
        match = compute_match_score(
            {
                "title": job.get("title", ""),
                "enrichment": enrichment,
                "semantic_score": None,
                "posted": job.get("posted"),
                "first_seen": job.get("first_seen"),
            },
            profile,
        )
        job["match_score"] = match["score"]
        job["match_band"] = match["band"]

    if sort_by == "posted":
        jobs.sort(key=lambda item: item.get("posted") or "", reverse=True)
    else:
        jobs.sort(key=lambda item: int(item.get("match_score", 0) or 0), reverse=True)

    new_count, updated_count, new_jobs = save_jobs(conn, jobs)
    if new_jobs:
        _set_processing_state_for_jobs(
            conn,
            new_jobs,
            state="processing",
            step="scrape",
            message="Queued for enrichment and scoring.",
        )
    try:
        all_urls = [str(job.get("url") or "") for job in jobs if str(job.get("url") or "").strip()]
        if all_urls:
            dashboard_repository.recompute_match_scores(conn, urls=all_urls)
        enriched_new_jobs = 0
        if new_jobs and not bool(params.get("no_enrich_llm", False)) and openrouter_api_key:
            run_enrichment_pipeline(
                new_jobs,
                conn,
                openrouter_api_key,
                openrouter_model,
                description_format_model,
                console,
            )
            enriched_new_jobs = len(new_jobs)
            dashboard_repository.recompute_match_scores(
                conn,
                urls=[str(job.get("url") or "") for job in new_jobs if str(job.get("url") or "").strip()],
            )
        if new_jobs:
            _set_processing_state_for_jobs(
                conn,
                new_jobs,
                state="ready",
                step="complete",
                message="Scrape processing complete.",
            )
    except Exception as error:
        if new_jobs:
            _set_processing_state_for_jobs(
                conn,
                new_jobs,
                state="failed",
                step="failed",
                message="Scrape processing failed.",
                last_error=str(error),
            )
        raise
    summary = {
        "jobs_found": len(jobs),
        "new_count": new_count,
        "updated_count": updated_count,
        "enriched_new_jobs": enriched_new_jobs,
        "message": f"Scrape completed with {new_count} new jobs and {updated_count} updated jobs.",
        "finished_at": now_iso(),
    }
    if bool(params.get("include_jobs", False)):
        summary["jobs"] = jobs
        summary["new_jobs"] = new_jobs
    _invalidate_dashboard_views()
    _refresh_daily_briefing(conn, trigger_source="scrape")
    return summary


def _run_enrich(conn: Any, params: dict[str, Any], console: Console, *, force: bool) -> dict[str, Any]:
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")
    openrouter_model = env_or_default("ENRICHMENT_MODEL", "openai/gpt-oss-120b")
    description_format_model = env_or_default("DESCRIPTION_FORMAT_MODEL", "openai/gpt-oss-120b")
    jobs_to_enrich = load_unenriched_jobs(conn, force=force)
    console.print(f"[bold]Enrichment queue:[/bold] {len(jobs_to_enrich)} job(s)")
    try:
        if jobs_to_enrich:
            _set_processing_state_for_jobs(
                conn,
                jobs_to_enrich,
                state="processing",
                step="enrichment",
                message="Running enrichment pipeline.",
            )
            run_enrichment_pipeline(
                jobs_to_enrich,
                conn,
                openrouter_api_key,
                openrouter_model,
                description_format_model,
                console,
            )
            dashboard_repository.recompute_match_scores(
                conn,
                urls=[str(job.get("url") or "") for job in jobs_to_enrich if str(job.get("url") or "").strip()],
            )
            # Generate per-job editorial blurbs for the top viable unapplied cards.
            # Cheap (SLM) and non-fatal — failures must not break enrichment.
            try:
                from ai_job_hunter.dashboard.backend import reasoning_blurb
                written = reasoning_blurb.generate_blurbs(conn, job_ids=None, force=False)
                if written:
                    console.print(
                        f"[bold]Kenji's read blurbs:[/bold] generated {len(written)}"
                    )
                    # Snapshots cache llm_blurb in payload_json; refresh affected rows
                    # so the dashboard actually shows the new blurbs. recompute=False
                    # so the snapshot refresh doesn't INSERT OR REPLACE the blurbs away.
                    try:
                        dashboard_repository.refresh_dashboard_snapshots(
                            conn, job_ids=list(written.keys()), recompute=False
                        )
                    except Exception as snap_err:
                        logger.warning(
                            "snapshot refresh after blurb generation failed: %s",
                            snap_err,
                            exc_info=True,
                        )
            except Exception as blurb_error:
                logger.warning(
                    "reasoning_blurb generation failed: %s", blurb_error, exc_info=True
                )
            _set_processing_state_for_jobs(
                conn,
                jobs_to_enrich,
                state="ready",
                step="complete",
                message="Enrichment complete.",
            )
    except Exception as error:
        if jobs_to_enrich:
            _set_processing_state_for_jobs(
                conn,
                jobs_to_enrich,
                state="failed",
                step="failed",
                message="Enrichment failed.",
                last_error=str(error),
            )
        raise
    _invalidate_dashboard_views()
    _refresh_daily_briefing(conn, trigger_source="scrape")
    return {
        "jobs_processed": len(jobs_to_enrich),
        "force": force,
        "message": "Re-enrichment completed." if force else "Backfill enrichment completed.",
        "finished_at": now_iso(),
    }


def _run_jd_reformat(conn: Any, params: dict[str, Any], console: Console) -> dict[str, Any]:
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")
    missing_only = bool(params.get("missing_only", True))
    description_format_model = env_or_default("DESCRIPTION_FORMAT_MODEL", "openai/gpt-oss-120b")
    jobs_to_process = load_jobs_for_jd_reformat(conn, missing_only=missing_only)
    console.print(f"[bold]JD reformat queue:[/bold] {len(jobs_to_process)} job(s)")
    try:
        if jobs_to_process:
            _set_processing_state_for_jobs(
                conn,
                jobs_to_process,
                state="processing",
                step="jd_reformat",
                message="Running description reformat pipeline.",
            )
            run_description_reformat_pipeline(
                jobs_to_process,
                conn,
                openrouter_api_key,
                description_format_model,
                console,
            )
            _set_processing_state_for_jobs(
                conn,
                jobs_to_process,
                state="ready",
                step="complete",
                message="Description reformat complete.",
            )
    except Exception as error:
        if jobs_to_process:
            _set_processing_state_for_jobs(
                conn,
                jobs_to_process,
                state="failed",
                step="failed",
                message="Description reformat failed.",
                last_error=str(error),
            )
        raise
    _invalidate_dashboard_views()
    _refresh_daily_briefing(conn, trigger_source="scrape")
    return {
        "jobs_processed": len(jobs_to_process),
        "missing_only": missing_only,
        "message": "JD reformat completed.",
        "finished_at": now_iso(),
    }
