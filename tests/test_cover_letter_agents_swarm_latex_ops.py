from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.cover_letter_agents_swarm.latex_apply import apply_rewrite_operations
from dashboard.backend.cover_letter_agents_swarm.latex_insert import (
    extract_cover_letter_text_from_latex,
    inject_cover_letter_body,
)
from dashboard.backend.cover_letter_agents_swarm.models import CoverLetterRewriteModel, LegalMove


def test_apply_rewrite_operations_replace_range_exact_match() -> None:
    latex = "%<CL_START>\nOld line\n%<CL_END>\n"
    rewrite = CoverLetterRewriteModel(
        applied_fix_ids=["FP1"],
        skipped_fix_ids=[],
        moves=[
            LegalMove(
                move_id="M1",
                fix_id="FP1",
                op="replace_range",
                reason="clearer",
                targets=["Tone_Clarity_Human"],
                supported_by=["ctx:1"],
                payload={
                    "start_line_id": 1,
                    "end_line_id": 1,
                    "old_latex": "Old line",
                    "new_lines": ["New line"],
                },
            )
        ],
    )
    report = apply_rewrite_operations(latex, rewrite)
    assert len(report.applied) == 1
    assert "New line" in report.updated_latex
    assert report.doc_version_hash_before
    assert report.doc_version_hash_after


def test_apply_rewrite_operations_missing_line_fails() -> None:
    latex = "%<CL_START>\nOnly line\n%<CL_END>\n"
    rewrite = CoverLetterRewriteModel(
        applied_fix_ids=["FP9"],
        skipped_fix_ids=[],
        moves=[
            LegalMove(
                move_id="M1",
                fix_id="FP9",
                op="replace_range",
                reason="n/a",
                targets=["Narrative_Fit"],
                supported_by=["ctx:1"],
                payload={
                    "start_line_id": 9,
                    "end_line_id": 9,
                    "old_latex": "Not present",
                    "new_lines": ["Replacement"],
                },
            )
        ],
    )
    report = apply_rewrite_operations(latex, rewrite)
    assert len(report.failed) == 1
    assert report.failed[0].fix_id == "FP9"
    assert report.failed_moves[0]["policy_reason"] == "target_not_found"


def test_apply_rewrite_operations_insert_and_delete() -> None:
    latex = "%<CL_START>\nLine one\nLine two\n%<CL_END>\n"
    rewrite = CoverLetterRewriteModel(
        applied_fix_ids=["FP1", "FP2"],
        skipped_fix_ids=[],
        moves=[
            LegalMove(
                move_id="M1",
                fix_id="FP1",
                op="insert_after",
                reason="add sentence",
                targets=["Narrative_Fit"],
                supported_by=["ctx:1"],
                payload={"after_line_id": 1, "new_lines": ["Inserted line"]},
            ),
            LegalMove(
                move_id="M2",
                fix_id="FP2",
                op="delete_range",
                reason="remove weak line",
                targets=["Structure_Skimmability"],
                supported_by=["ctx:2"],
                payload={"start_line_id": 3, "end_line_id": 3},
            ),
        ],
    )
    report = apply_rewrite_operations(latex, rewrite)
    assert "Inserted line" in report.updated_latex
    assert len(report.applied_moves) == 2


def test_inject_and_extract_cover_letter_body_markers() -> None:
    source = "\\begin{document}\n%<CL_START>\nOld body\n%<CL_END>\n\\end{document}\n"
    updated = inject_cover_letter_body(source, "First paragraph.\n\nSecond paragraph.")
    extracted = extract_cover_letter_text_from_latex(updated)
    assert "First paragraph." in extracted
    assert "Second paragraph." in extracted


def test_inject_and_extract_cover_letter_body_legacy_section_markers() -> None:
    source = "\\begin{document}\n% <section:body>\nOld body\n% </section:body>\n\\end{document}\n"
    updated = inject_cover_letter_body(source, "Legacy paragraph one.\n\nLegacy paragraph two.")
    extracted = extract_cover_letter_text_from_latex(updated)
    assert "Legacy paragraph one." in extracted
    assert "Legacy paragraph two." in extracted
