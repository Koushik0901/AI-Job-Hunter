from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from dashboard.backend.latex_resume import compile_resume_tex
from dashboard.backend.cover_letter_agents_swarm.graph import build_cover_letter_agents_swarm_graph
from dashboard.backend.cover_letter_agents_swarm.llm import load_llm_config
from dashboard.backend.cover_letter_agents_swarm.latex_insert import extract_cover_letter_text_from_latex
from dashboard.backend.swarm_runtime import score_from_history


def _read_path_or_text(value: str) -> str:
    candidate = Path(value)
    if candidate.exists() and candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return value


def _compile_ok(tag: str, latex: str) -> bool | None:
    digest = hashlib.sha1(latex.encode("utf-8")).hexdigest()[:10]
    try:
        result = compile_resume_tex(
            artifact_id=f"swarm-guard-{tag}-{digest}",
            version=1,
            source_text=latex,
        )
        return bool(result.get("ok"))
    except RuntimeError:
        return None
    except Exception:
        return False


def run_cover_letter_agents_swarm_optimization(
    job_description: str,
    resume_text: str,
    latex_cover_letter: str,
    evidence_context: dict[str, Any] | None = None,
    brag_document_markdown: str = "",
    project_cards: list[dict[str, Any]] | None = None,
    do_not_claim: list[str] | None = None,
    evidence_pack: dict[str, Any] | None = None,
    cycles: int = 2,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    config = load_llm_config()
    graph = build_cover_letter_agents_swarm_graph(config, on_event=progress_callback, should_cancel=should_cancel)
    initial_text = ""
    try:
        initial_text = extract_cover_letter_text_from_latex(latex_cover_letter)
    except Exception:
        initial_text = ""
    min_score_delta = max(0, int(os.getenv("SWARM_MIN_SCORE_DELTA", "3")))
    max_ops_per_cycle = max(1, int(os.getenv("SWARM_MAX_OPS_PER_CYCLE", "12")))
    max_changed_line_ratio = max(0.01, float(os.getenv("SWARM_MAX_CHANGED_LINE_RATIO", "0.25")))
    force_cycle_on_non_negotiables = (os.getenv("SWARM_FORCE_ON_NON_NEGOTIABLES", "1").strip() or "1") in {"1", "true", "TRUE", "yes", "YES"}
    initial_state = {
        "job_description": job_description,
        "resume_text": resume_text.strip(),
        "latex_cover_letter": latex_cover_letter,
        "cover_letter_text": initial_text,
        "evidence_context": evidence_context or {},
        "brag_document_markdown": brag_document_markdown,
        "project_cards": project_cards or [],
        "do_not_claim": do_not_claim or [],
        "evidence_pack": evidence_pack or {},
        "cycles_done": 0,
        "target_cycles": max(0, int(cycles)),
        "initial_line_count": max(1, len(latex_cover_letter.splitlines())),
        "min_score_delta": min_score_delta,
        "max_ops_per_cycle": max_ops_per_cycle,
        "max_changed_line_ratio": max_changed_line_ratio,
        "force_cycle_on_non_negotiables": force_cycle_on_non_negotiables,
        "history": [],
    }
    final_state = graph.invoke(initial_state)
    final_latex = str(final_state.get("latex_cover_letter", latex_cover_letter))
    history = list(final_state.get("history", []))
    final_score = final_state.get("final_score", final_state.get("last_score", {}))
    compile_guard_enabled = (os.getenv("SWARM_COMPILE_ROLLBACK", "1").strip() or "1") in {"1", "true", "TRUE", "yes", "YES"}
    if compile_guard_enabled:
        before_ok = _compile_ok("cl-before", latex_cover_letter)
        after_ok = _compile_ok("cl-final", final_latex)
        if before_ok is True and after_ok is False:
            restored_score = score_from_history(history, stage="score", prefer="first")
            history.append(
                {
                    "stage": "compile_guard_rollback",
                    "artifact_kind": "cover_letter",
                    "before_ok": before_ok,
                    "after_ok": after_ok,
                    "action": "reverted_to_input",
                    "restored_score": restored_score,
                }
            )
            final_latex = latex_cover_letter
            final_score = restored_score
    return {
        "final_latex_cover_letter": final_latex,
        "final_score": final_score,
        "history": history,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cover letter swarm-like optimization loop")
    parser.add_argument("--jd", required=True, help="Job description text or path")
    parser.add_argument("--latex", required=True, help="LaTeX cover letter path or raw text")
    parser.add_argument("--resume-text", default="", help="Plain resume text path or raw text")
    parser.add_argument("--cycles", type=int, default=2, help="Number of rewrite/apply cycles")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    job_description = _read_path_or_text(args.jd)
    latex_cover_letter = _read_path_or_text(args.latex)
    resume_text = _read_path_or_text(args.resume_text) if args.resume_text else ""
    result = run_cover_letter_agents_swarm_optimization(
        job_description=job_description,
        resume_text=resume_text,
        latex_cover_letter=latex_cover_letter,
        cycles=args.cycles,
    )
    print(json.dumps({"final_score": result["final_score"], "history_steps": len(result["history"])}, indent=2))


if __name__ == "__main__":
    main()
