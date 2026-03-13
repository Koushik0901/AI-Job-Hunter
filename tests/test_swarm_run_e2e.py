from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from db import init_db, save_jobs
from dashboard.backend import main, repository
from dashboard.backend.schemas import (
    RecompileArtifactLatexRequest,
    ResumeSwarmConfirmSaveRequest,
    ResumeSwarmRunStartRequest,
)
from dashboard.backend.swarm_runtime import SwarmRunCancelled


def _seed_job_and_artifacts(tmp_path: Path, monkeypatch: Any) -> tuple[str, str, str, str]:
    db_path = tmp_path / "swarm-e2e.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.delenv("TURSO_URL", raising=False)
    monkeypatch.delenv("TURSO_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(main, "_resolve_db", lambda: (str(db_path), ""))

    conn = init_db(str(db_path))
    try:
        job_url = "https://example.com/jobs/ml-engineer"
        save_jobs(
            conn,
            [
                {
                    "url": job_url,
                    "company": "ExampleAI",
                    "title": "ML Engineer",
                    "location": "Remote",
                    "posted": "2026-03-01",
                    "ats": "greenhouse",
                    "description": "Build production AI systems with retrieval and evaluation.",
                    "source": "manual",
                }
            ],
        )
        job_id = repository.get_job_id_by_url(conn, job_url)
        assert job_id is not None
        repository.ensure_starter_artifacts_for_job(conn, str(job_id))
        artifacts = repository.list_job_artifacts(conn, str(job_id))
        by_type = {str(item["artifact_type"]): str(item["id"]) for item in artifacts}
        return str(job_id), job_url, by_type["resume"], by_type["cover_letter"]
    finally:
        conn.close()


def _install_immediate_swarm_runner(monkeypatch: Any) -> None:
    def _fake_start_swarm_run_background(
        run_id: str,
        *,
        job_description: str,
        latex_source: str,
        resume_text: str,
        evidence_context: dict[str, Any],
        brag_document_markdown: str,
        project_cards: list[dict[str, Any]],
        do_not_claim: list[str],
        evidence_pack: dict[str, Any],
        cycles: int,
        pipeline: str,
    ) -> None:
        with main._SWARM_RUNS_LOCK:
            run = main._SWARM_RUNS.get(run_id)
            if not run:
                return
            run["status"] = "awaiting_confirmation"
            run["current_stage"] = "preview_ready"
            run["stage_index"] = 7
            run["cycles_done"] = int(cycles)
            run["candidate_latex"] = f"{latex_source}\n% ai-rewrite-{pipeline}"
            run["final_score"] = {"Total_Score": 88}
            run["updated_at"] = main._now_iso()
            event = main._append_swarm_event(
                run,
                stage="preview_ready",
                message="AI rewrite finished. Review and confirm save.",
                data={"pipeline": pipeline},
            )
            snapshot = dict(run)
        main._persist_swarm_run(snapshot)
        main._persist_swarm_event(run_id, event)

    monkeypatch.setattr(main, "_start_swarm_run_background", _fake_start_swarm_run_background)
    monkeypatch.setattr(main, "build_runtime_evidence_pack", lambda *_args, **_kwargs: {})


def _install_compile_success(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        main,
        "compile_resume_tex",
        lambda **_kwargs: {
            "ok": True,
            "pdf_path": str((REPO_ROOT / "artifacts_workspace" / "fake.pdf").resolve()),
            "log_tail": "ok",
            "diagnostics": [],
        },
    )


def test_resume_swarm_run_confirm_save_and_recompile(tmp_path: Path, monkeypatch: Any) -> None:
    _, _, resume_artifact_id, _ = _seed_job_and_artifacts(tmp_path, monkeypatch)
    _install_immediate_swarm_runner(monkeypatch)
    _install_compile_success(monkeypatch)
    with main._SWARM_RUNS_LOCK:
        main._SWARM_RUNS.clear()

    started = main.start_resume_agents_swarm_run(resume_artifact_id, ResumeSwarmRunStartRequest(cycles=2))
    assert started.status == "queued"
    status = main.get_resume_agents_swarm_run_status(resume_artifact_id, started.run_id)
    assert status.status == "awaiting_confirmation"
    assert isinstance(status.candidate_latex, str) and "% ai-rewrite-resume" in status.candidate_latex

    saved = main.confirm_resume_agents_swarm_run_save(
        resume_artifact_id,
        started.run_id,
        ResumeSwarmConfirmSaveRequest(created_by="test", label="draft"),
    )
    assert saved.version >= 2
    assert int(saved.final_score.get("Total_Score") or 0) == 88

    compiled = main.recompile_artifact_latex_document(
        resume_artifact_id,
        RecompileArtifactLatexRequest(created_by="test"),
    )
    assert compiled.compile_status == "ok"
    assert compiled.compile_error is None


def test_cover_letter_swarm_run_confirm_save_and_recompile(tmp_path: Path, monkeypatch: Any) -> None:
    _, _, _, cover_letter_artifact_id = _seed_job_and_artifacts(tmp_path, monkeypatch)
    _install_immediate_swarm_runner(monkeypatch)
    _install_compile_success(monkeypatch)
    with main._SWARM_RUNS_LOCK:
        main._SWARM_RUNS.clear()

    started = main.start_cover_letter_agents_swarm_run(cover_letter_artifact_id, ResumeSwarmRunStartRequest(cycles=2))
    assert started.status == "queued"
    status = main.get_cover_letter_agents_swarm_run_status(cover_letter_artifact_id, started.run_id)
    assert status.status == "awaiting_confirmation"
    assert isinstance(status.candidate_latex, str) and "% ai-rewrite-cover_letter" in status.candidate_latex

    saved = main.confirm_cover_letter_agents_swarm_run_save(
        cover_letter_artifact_id,
        started.run_id,
        ResumeSwarmConfirmSaveRequest(created_by="test", label="draft"),
    )
    assert saved.version >= 2
    assert int(saved.final_score.get("Total_Score") or 0) == 88

    compiled = main.recompile_artifact_latex_document(
        cover_letter_artifact_id,
        RecompileArtifactLatexRequest(created_by="test"),
    )
    assert compiled.compile_status == "ok"
    assert compiled.compile_error is None


def test_resume_swarm_run_uses_editor_source_and_template(tmp_path: Path, monkeypatch: Any) -> None:
    _, _, resume_artifact_id, _ = _seed_job_and_artifacts(tmp_path, monkeypatch)
    _install_immediate_swarm_runner(monkeypatch)
    with main._SWARM_RUNS_LOCK:
        main._SWARM_RUNS.clear()

    started = main.start_resume_agents_swarm_run(
        resume_artifact_id,
        ResumeSwarmRunStartRequest(
            cycles=2,
            source_text="\\section{Experience}\nSentinel resume draft\n",
            template_id="user_resume_template",
        ),
    )
    status = main.get_resume_agents_swarm_run_status(resume_artifact_id, started.run_id)
    assert isinstance(status.candidate_latex, str)
    assert "Sentinel resume draft" in status.candidate_latex

    main.confirm_resume_agents_swarm_run_save(
        resume_artifact_id,
        started.run_id,
        ResumeSwarmConfirmSaveRequest(created_by="test", label="draft"),
    )
    saved = main.get_resume_latex_document(resume_artifact_id)
    assert saved.template_id == "user_resume_template"
    assert "Sentinel resume draft" in saved.source_text


def test_cover_letter_swarm_run_uses_editor_source_and_template(tmp_path: Path, monkeypatch: Any) -> None:
    _, _, _, cover_letter_artifact_id = _seed_job_and_artifacts(tmp_path, monkeypatch)
    _install_immediate_swarm_runner(monkeypatch)
    with main._SWARM_RUNS_LOCK:
        main._SWARM_RUNS.clear()

    started = main.start_cover_letter_agents_swarm_run(
        cover_letter_artifact_id,
        ResumeSwarmRunStartRequest(
            cycles=2,
            source_text="\\opening{Dear Hiring Team,}\nSentinel cover letter draft\n",
            template_id="user_cover_letter_template",
        ),
    )
    status = main.get_cover_letter_agents_swarm_run_status(cover_letter_artifact_id, started.run_id)
    assert isinstance(status.candidate_latex, str)
    assert "Sentinel cover letter draft" in status.candidate_latex

    main.confirm_cover_letter_agents_swarm_run_save(
        cover_letter_artifact_id,
        started.run_id,
        ResumeSwarmConfirmSaveRequest(created_by="test", label="draft"),
    )
    saved = main.get_artifact_latex_document(cover_letter_artifact_id)
    assert saved.template_id == "user_cover_letter_template"
    assert "Sentinel cover letter draft" in saved.source_text


def test_swarm_cancel_status_is_stable(tmp_path: Path, monkeypatch: Any) -> None:
    _, _, resume_artifact_id, _ = _seed_job_and_artifacts(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "build_runtime_evidence_pack", lambda *_args, **_kwargs: {})

    def _noop_background(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(main, "_start_swarm_run_background", _noop_background)
    with main._SWARM_RUNS_LOCK:
        main._SWARM_RUNS.clear()

    started = main.start_resume_agents_swarm_run(resume_artifact_id, ResumeSwarmRunStartRequest(cycles=2))
    first = main.cancel_resume_agents_swarm_run(resume_artifact_id, started.run_id)
    second = main.cancel_resume_agents_swarm_run(resume_artifact_id, started.run_id)

    assert first.status == "cancelled"
    assert second.status == "cancelled"
    assert first.current_stage == "cancelled"
    assert second.current_stage == "cancelled"
    assert len(second.events) == len(first.events)


def test_start_resume_swarm_run_defers_expensive_persistence_and_evidence_pack(tmp_path: Path, monkeypatch: Any) -> None:
    _, _, resume_artifact_id, _ = _seed_job_and_artifacts(tmp_path, monkeypatch)
    queued_runs: list[dict[str, Any]] = []
    queued_events: list[dict[str, Any]] = []
    background_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(main, "_queue_persist_swarm_run", lambda snapshot: queued_runs.append(dict(snapshot)))
    monkeypatch.setattr(main, "_queue_persist_swarm_event", lambda _run_id, event: queued_events.append(dict(event)))
    monkeypatch.setattr(
        main,
        "build_runtime_evidence_pack",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("build_runtime_evidence_pack should run in background")),
    )

    def _capture_background_call(*args: Any, **kwargs: Any) -> None:
        background_calls.append({"args": args, "kwargs": kwargs})

    monkeypatch.setattr(main, "_start_swarm_run_background", _capture_background_call)
    with main._SWARM_RUNS_LOCK:
        main._SWARM_RUNS.clear()

    started = main.start_resume_agents_swarm_run(resume_artifact_id, ResumeSwarmRunStartRequest(cycles=2))

    assert started.status == "queued"
    assert len(queued_runs) == 1
    assert len(queued_events) == 1
    assert len(background_calls) == 1
    assert background_calls[0]["kwargs"]["evidence_pack"] is None


def test_background_cancel_stays_cancelled_instead_of_failed(monkeypatch: Any) -> None:
    persisted_runs: list[dict[str, Any]] = []
    persisted_events: list[dict[str, Any]] = []
    monkeypatch.setattr(main, "_persist_swarm_run", lambda snapshot: persisted_runs.append(dict(snapshot)))
    monkeypatch.setattr(main, "_persist_swarm_event", lambda _run_id, event: persisted_events.append(dict(event)))

    def _fake_run_resume_agents_swarm_optimization(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        should_cancel = kwargs.get("should_cancel")
        for _ in range(50):
            if callable(should_cancel) and should_cancel():
                raise SwarmRunCancelled("cancelled in test")
            main.time.sleep(0.01)
        raise AssertionError("Expected cancellation before optimization finished")

    monkeypatch.setattr(main, "run_resume_agents_swarm_optimization", _fake_run_resume_agents_swarm_optimization)
    with main._SWARM_RUNS_LOCK:
        main._SWARM_RUNS.clear()
        run = main._new_swarm_run(
            artifact_id="artifact-1",
            job_id="job-1",
            job_url="https://example.com/jobs/ml-engineer",
            cycles=2,
            pipeline="resume",
        )
        main._SWARM_RUNS[str(run["run_id"])] = run

    run_id = str(run["run_id"])
    main._start_swarm_run_background(
        run_id,
        job_description="Need Python API engineer",
        latex_source="\\section{Experience}\n\\item Built API\n",
        resume_text="Built API",
        evidence_context={},
        brag_document_markdown="",
        project_cards=[],
        do_not_claim=[],
        evidence_pack={},
        cycles=2,
        pipeline="resume",
    )
    main.time.sleep(0.03)
    cancelled = main.cancel_resume_agents_swarm_run("artifact-1", run_id)
    assert cancelled.status == "cancelled"

    for _ in range(40):
        main.time.sleep(0.01)
        with main._SWARM_RUNS_LOCK:
            current = dict(main._SWARM_RUNS.get(run_id) or {})
        if str(current.get("status")) == "cancelled":
            break

    with main._SWARM_RUNS_LOCK:
        final_run = dict(main._SWARM_RUNS.get(run_id) or {})

    assert final_run.get("status") == "cancelled"
    assert final_run.get("current_stage") == "cancelled"
    assert not any(str(event.get("stage")) == "failed" for event in persisted_events)
