"""
apply.py — Loop B orchestrator: tailor resume → verify ATS → refine → cover letter.

Deterministic DAG, NOT a LangChain agent. The steps are:
  1. Load job + resolve resume/cover-letter base documents.
  2. Draft a *structured* resume (JSON with per-bullet provenance).
  3. Verify provenance; render markdown with bullet anchors.
  4. Score against keyword ATS (deterministic, fast).
  5. Screen via LLM recruiter-POV (strong model).
  6. If either gate is below threshold AND we have iterations left, merge the
     gaps into feedback_hints and re-draft (max 3 resume iterations).
  7. Save the final resume artifact with provenance + both scores.
  8. Draft a cover letter (one-shot, no iteration — lower stakes).
  9. Save the cover letter artifact with provenance.

Progress is emitted by updating the `workspace_operations.summary_json` field
with a growing list of steps. The existing `/api/operations/{id}/events` SSE
endpoint polls the row and re-serializes when it changes, so the frontend
receives step-by-step updates without any new plumbing.

This module is called from `task_handlers._run_apply_orchestrate`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ai_job_hunter.db import update_workspace_operation
from ai_job_hunter.dashboard.backend import artifacts as artifact_svc
from ai_job_hunter.dashboard.backend.ats import (
    ScreenerVerdict,
    score_resume_keywords,
    screen_resume,
)
from ai_job_hunter.dashboard.backend.structured_artifacts import (
    generate_cover_letter_structured,
    generate_resume_structured,
)

logger = logging.getLogger(__name__)

# Thresholds (module constants so they show up in review / can be tuned)
KEYWORD_PASS_THRESHOLD = 70      # pass_likelihood >= this is a pass
SCREENER_PASS_VERDICTS = {"pass", "borderline"}  # "fail" forces a rewrite
MAX_RESUME_ITERATIONS = 3


# ---------------------------------------------------------------------------
# Progress emission
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class _Progress:
    """Helper that merges step-update writes into workspace_operations.summary_json."""

    def __init__(self, operation_id: str, conn_factory: Any) -> None:
        self.operation_id = operation_id
        self._conn_factory = conn_factory
        self.summary: dict[str, Any] = {
            "kind": "apply",
            "steps": [],
            "iterations": [],
            "final": None,
        }

    def _flush(self) -> None:
        conn = self._conn_factory()
        try:
            update_workspace_operation(
                conn, self.operation_id, {"summary": self.summary}
            )
        finally:
            conn.close()

    def start_step(self, step_id: str, label: str) -> None:
        self.summary["steps"].append({
            "id": step_id,
            "label": label,
            "status": "running",
            "started_at": _now_iso(),
        })
        self._flush()

    def finish_step(
        self,
        step_id: str,
        *,
        status: str = "completed",
        detail: str | None = None,
        data: dict | None = None,
    ) -> None:
        for step in self.summary["steps"]:
            if step["id"] == step_id and step.get("status") == "running":
                step["status"] = status
                step["finished_at"] = _now_iso()
                if detail is not None:
                    step["detail"] = detail
                if data is not None:
                    step["data"] = data
                break
        self._flush()

    def record_iteration(self, iteration: dict[str, Any]) -> None:
        self.summary["iterations"].append(iteration)
        self._flush()

    def set_final(self, final: dict[str, Any]) -> None:
        self.summary["final"] = final
        self._flush()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_base_doc_id(
    conn: Any, doc_type: str, explicit_id: int | None
) -> int | None:
    if explicit_id:
        return int(explicit_id)
    row = conn.execute(
        "SELECT id FROM base_documents WHERE doc_type = ? AND is_default = 1 ORDER BY created_at DESC LIMIT 1",
        (doc_type,),
    ).fetchone()
    if row:
        return int(row[0])
    row = conn.execute(
        "SELECT id FROM base_documents WHERE doc_type = ? ORDER BY created_at DESC LIMIT 1",
        (doc_type,),
    ).fetchone()
    return int(row[0]) if row else None


def _merge_feedback(
    keyword_hints: str, screener_hints: str, prior: str = ""
) -> str:
    parts = [p for p in (prior, keyword_hints, screener_hints) if p and p.strip()]
    return "\n".join(parts)


def _is_resume_passing(keyword_score: int, verdict: ScreenerVerdict) -> bool:
    return (
        keyword_score >= KEYWORD_PASS_THRESHOLD
        and verdict.verdict in SCREENER_PASS_VERDICTS
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_apply_orchestrator(
    job_id: str,
    operation_id: str,
    conn_factory: Any,
    *,
    resume_base_doc_id: int | None = None,
    cover_letter_base_doc_id: int | None = None,
    max_iterations: int = MAX_RESUME_ITERATIONS,
) -> dict[str, Any]:
    """
    Run the full /apply DAG. Opens short-lived connections (one per step) so
    long LLM calls don't hold a DB row lock. Returns the summary dict that
    also lives on workspace_operations.summary_json.

    `conn_factory` is a callable that returns a fresh DB connection; it's
    provided by the task handler so this module stays DB-binding agnostic.
    """
    progress = _Progress(operation_id, conn_factory)

    # --- Step 1: load job + resolve base documents -------------------------
    progress.start_step("setup", "Loading job and base documents")
    conn = conn_factory()
    try:
        job = artifact_svc._load_job_context(job_id, conn)
        resolved_resume_doc = _resolve_base_doc_id(conn, "resume", resume_base_doc_id)
        resolved_cover_doc = _resolve_base_doc_id(
            conn, "cover_letter", cover_letter_base_doc_id
        ) or resolved_resume_doc  # fall back to resume if no cover-letter base doc
    finally:
        conn.close()

    if not resolved_resume_doc:
        progress.finish_step("setup", status="failed", detail="No base resume document")
        raise ValueError("No base resume document found — upload one in Settings first.")

    progress.finish_step(
        "setup",
        detail=f"Job '{job.get('title') or job_id}' · base_doc_id={resolved_resume_doc}",
    )

    # --- Step 2..6: iterative resume loop ---------------------------------
    feedback_hints = ""
    final_resume_md = ""
    final_provenance: list[dict] = []
    final_story_ids: list[int] = []
    final_keyword_score = 0
    final_screener: ScreenerVerdict | None = None
    iteration_used = 0

    for i in range(1, max_iterations + 1):
        iteration_used = i
        step_draft = f"draft_resume_{i}"
        progress.start_step(
            step_draft,
            f"Drafting resume (iteration {i}/{max_iterations})",
        )
        try:
            conn = conn_factory()
            try:
                content_md, provenance, story_ids = generate_resume_structured(
                    job_id,
                    resolved_resume_doc,
                    conn,
                    feedback_hints=feedback_hints,
                )
            finally:
                conn.close()
        except Exception as e:
            progress.finish_step(step_draft, status="failed", detail=str(e))
            raise

        grounded = sum(
            1 for p in provenance if p.get("source_type") in {"story", "base_resume", "intent"}
        )
        progress.finish_step(
            step_draft,
            detail=f"{len(provenance)} bullets ({grounded} grounded)",
        )

        # Score keyword
        step_kw = f"ats_keyword_{i}"
        progress.start_step(step_kw, "Scoring keyword ATS")
        kw_score = score_resume_keywords(
            content_md,
            list(job.get("required_skills") or []),
            list(job.get("preferred_skills") or []),
        )
        progress.finish_step(
            step_kw,
            detail=f"pass_likelihood={kw_score.pass_likelihood}",
            data={
                "pass_likelihood": kw_score.pass_likelihood,
                "missing_required": kw_score.missing_required,
                "missing_preferred": kw_score.missing_preferred,
                "weak_sections": kw_score.weak_sections,
            },
        )

        # Screen via LLM
        step_sc = f"ats_screener_{i}"
        progress.start_step(step_sc, "Recruiter-POV screener")
        verdict = screen_resume(content_md, job)
        progress.finish_step(
            step_sc,
            detail=f"{verdict.verdict} ({verdict.confidence}%) — {verdict.one_line_summary}",
            data=verdict.to_dict(),
        )

        iteration_record = {
            "iteration": i,
            "keyword_score": kw_score.pass_likelihood,
            "screener_verdict": verdict.verdict,
            "grounded_bullets": grounded,
            "total_bullets": len(provenance),
        }
        progress.record_iteration(iteration_record)

        # Save this iteration's resume (archived, not active) — keeps an audit trail.
        # The LAST iteration will be re-saved as active after the loop.
        conn = conn_factory()
        try:
            artifact_svc.save_artifact(
                job_id,
                "resume",
                content_md,
                resolved_resume_doc,
                "apply_orchestrator",
                conn,
                story_ids_used=story_ids,
                provenance=provenance,
                ats_keyword_score=kw_score.pass_likelihood,
                ats_screener_verdict=verdict.verdict,
                iteration_index=i,
                apply_operation_id=operation_id,
                make_active=False,
            )
        finally:
            conn.close()

        final_resume_md = content_md
        final_provenance = provenance
        final_story_ids = story_ids
        final_keyword_score = kw_score.pass_likelihood
        final_screener = verdict

        if _is_resume_passing(kw_score.pass_likelihood, verdict):
            break

        # Not passing — build feedback for next iteration
        if i < max_iterations:
            feedback_hints = _merge_feedback(
                kw_score.feedback_hints(), verdict.feedback_hints()
            )

    # --- Step 7: save final resume as active -----------------------------
    progress.start_step("save_resume", "Saving final resume")
    conn = conn_factory()
    try:
        final_artifact = artifact_svc.save_artifact(
            job_id,
            "resume",
            final_resume_md,
            resolved_resume_doc,
            "apply_orchestrator",
            conn,
            story_ids_used=final_story_ids,
            provenance=final_provenance,
            ats_keyword_score=final_keyword_score,
            ats_screener_verdict=final_screener.verdict if final_screener else None,
            iteration_index=iteration_used,
            apply_operation_id=operation_id,
            make_active=True,
        )
    finally:
        conn.close()
    progress.finish_step(
        "save_resume",
        detail=f"artifact #{final_artifact.get('id')} v{final_artifact.get('version')}",
    )

    # --- Step 8: cover letter (one-shot) ---------------------------------
    cover_artifact: dict[str, Any] = {}
    progress.start_step("draft_cover_letter", "Drafting cover letter")
    try:
        conn = conn_factory()
        try:
            cl_md, cl_prov, cl_stories = generate_cover_letter_structured(
                job_id,
                resolved_cover_doc or resolved_resume_doc,
                conn,
                feedback_hints="",
            )
        finally:
            conn.close()
        progress.finish_step(
            "draft_cover_letter",
            detail=f"{len(cl_prov)} paragraphs",
        )

        progress.start_step("save_cover_letter", "Saving cover letter")
        conn = conn_factory()
        try:
            cover_artifact = artifact_svc.save_artifact(
                job_id,
                "cover_letter",
                cl_md,
                resolved_cover_doc or resolved_resume_doc,
                "apply_orchestrator",
                conn,
                story_ids_used=cl_stories,
                provenance=cl_prov,
                iteration_index=1,
                apply_operation_id=operation_id,
                make_active=True,
            )
        finally:
            conn.close()
        progress.finish_step(
            "save_cover_letter",
            detail=f"artifact #{cover_artifact.get('id')} v{cover_artifact.get('version')}",
        )
    except Exception as e:
        # Cover letter is best-effort — resume is the primary deliverable.
        logger.exception("Cover letter generation failed; resume still saved")
        for step_id in ("draft_cover_letter", "save_cover_letter"):
            progress.finish_step(step_id, status="failed", detail=str(e))

    final_summary = {
        "resume_artifact_id": int(final_artifact.get("id") or 0),
        "resume_version": int(final_artifact.get("version") or 0),
        "cover_letter_artifact_id": int(cover_artifact.get("id") or 0) if cover_artifact else 0,
        "cover_letter_version": int(cover_artifact.get("version") or 0) if cover_artifact else 0,
        "iterations_used": iteration_used,
        "final_keyword_score": final_keyword_score,
        "final_screener_verdict": final_screener.verdict if final_screener else None,
        "passed": bool(final_screener and _is_resume_passing(final_keyword_score, final_screener)),
    }
    progress.set_final(final_summary)
    return progress.summary
