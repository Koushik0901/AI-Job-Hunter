from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.resume_agents_swarm.latex_apply import apply_rewrite_operations
from dashboard.backend.resume_agents_swarm.models import LegalMove, ResumeRewriteModel


def test_apply_rewrite_operations_replace_range_exact_match() -> None:
    latex = "\\begin{itemize}\n\\item Built API\n\\end{itemize}\n"
    rewrite = ResumeRewriteModel(
        applied_fix_ids=["FP1"],
        skipped_fix_ids=[],
        moves=[
            LegalMove(
                move_id="M1",
                fix_id="FP1",
                op="replace_range",
                reason="impact",
                targets=["Impact_Specificity"],
                supported_by=["ctx:1"],
                payload={
                    "start_line_id": 1,
                    "end_line_id": 1,
                    "old_latex": "\\item Built API",
                    "new_lines": ["\\item Built API and reduced latency by [X]\\%"],
                },
            )
        ],
    )
    report = apply_rewrite_operations(latex, rewrite)
    assert len(report.applied) == 1
    assert "reduced latency" in report.updated_latex
    assert report.doc_version_hash_before
    assert report.doc_version_hash_after


def test_apply_rewrite_operations_missing_line_fails() -> None:
    latex = "\\item One\n"
    rewrite = ResumeRewriteModel(
        applied_fix_ids=["FP9"],
        skipped_fix_ids=[],
        moves=[
            LegalMove(
                move_id="M1",
                fix_id="FP9",
                op="replace_range",
                reason="n/a",
                targets=["JD_Alignment"],
                supported_by=["ctx:1"],
                payload={
                    "start_line_id": 7,
                    "end_line_id": 7,
                    "old_latex": "\\item Missing",
                    "new_lines": ["\\item New"],
                },
            )
        ],
    )
    report = apply_rewrite_operations(latex, rewrite)
    assert len(report.failed) == 1
    assert report.failed[0].fix_id == "FP9"
    assert report.failed_moves[0]["policy_reason"] == "target_not_found"


def test_apply_rewrite_operations_noop_is_logged() -> None:
    latex = "\\item Same\n"
    rewrite = ResumeRewriteModel(
        applied_fix_ids=["FP0"],
        skipped_fix_ids=[],
        moves=[
            LegalMove(
                move_id="M1",
                fix_id="FP0",
                op="replace_range",
                reason="no-op",
                targets=["Action_Language"],
                supported_by=["ctx:1"],
                payload={
                    "start_line_id": 0,
                    "end_line_id": 0,
                    "old_latex": "\\item Same",
                    "new_lines": ["\\item Same"],
                },
            )
        ],
    )
    report = apply_rewrite_operations(latex, rewrite)
    assert len(report.no_op) == 1
    assert report.updated_latex == latex


def test_apply_rewrite_operations_insert_and_delete() -> None:
    latex = "\\section{Experience}\n\\begin{itemize}\n\\item One\n\\item Two\n\\end{itemize}\n"
    rewrite = ResumeRewriteModel(
        applied_fix_ids=["FP1", "FP2"],
        skipped_fix_ids=[],
        moves=[
            LegalMove(
                move_id="M1",
                fix_id="FP1",
                op="insert_after",
                reason="add bullet",
                targets=["Impact_Specificity"],
                supported_by=["ctx:1"],
                payload={"after_line_id": 2, "new_lines": ["\\item Inserted"]},
            ),
            LegalMove(
                move_id="M2",
                fix_id="FP2",
                op="delete_range",
                reason="remove weak bullet",
                targets=["First_Pass_Clarity"],
                supported_by=["ctx:2"],
                payload={"start_line_id": 2, "end_line_id": 2},
            ),
        ],
    )
    report = apply_rewrite_operations(latex, rewrite)
    assert any("Inserted" in line for line in report.updated_latex.splitlines())
    assert len(report.applied_moves) == 2
