from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.cover_letter_agents_swarm.parsing import (
    parse_and_validate_draft,
    parse_and_validate_rewrite,
    parse_and_validate_score,
)


def test_parse_and_validate_draft_with_wrapped_text() -> None:
    raw = 'result:\n{"cover_letter_text":"Hello","notes_for_reviewer":["n1"]}\nthanks'
    parsed = parse_and_validate_draft(raw)
    assert parsed.cover_letter_text == "Hello"
    assert parsed.notes_for_reviewer == ["n1"]


def test_parse_and_validate_score() -> None:
    payload = {
        "Total_Score": 74,
        "Breakdown": {
            "Personalization_Intent": 18,
            "Narrative_Fit": 17,
            "Evidence_Credibility": 15,
            "Tone_Clarity_Human": 16,
            "Structure_Skimmability": 8,
        },
        "Cover_Letter_Success_Map": {
            "Top_Role_Outcomes": ["Outcome A"],
            "Fit_Signals_To_Demonstrate": ["Signal A"],
            "Company_Signals_From_JD": ["Signal B"],
            "Potential_Risks_To_Address": ["Risk A"],
        },
        "Evidence": {
            "Why_Company_Evidence": ["snippet"],
            "Why_Role_Evidence": ["snippet"],
            "Proof_Examples_Evidence": ["snippet"],
            "Tone_Voice_Evidence": ["snippet"],
        },
        "Critical_Feedback": ["Fix opening"],
        "Fluff_Detected": [],
        "Generic_Template_Signals": [],
        "Resume_Rehash_Sections": [],
        "Missing_Elements": [],
        "High_Leverage_Sections_To_Edit": [
            {"section_hint": "Opening", "why": "Generic", "goal": "Specific"}
        ],
        "Fix_Plan": [
            {
                "fix_id": "FP1",
                "priority": 1,
                "expected_score_gain": 4,
                "category": "Personalization_Intent",
                "location_hint": "Paragraph 1",
                "problem": "Too generic",
                "required_evidence": "Reference company signal",
                "rewrite_goal": "Make opening specific",
            }
        ],
        "Non_Negotiables": ["State role fit clearly"],
    }
    parsed = parse_and_validate_score(json.dumps(payload))
    assert parsed.Total_Score == 74
    assert parsed.Fix_Plan[0].fix_id == "FP1"


def test_parse_and_validate_rewrite() -> None:
    payload = {
        "applied_fix_ids": ["FP1"],
        "skipped_fix_ids": [],
        "moves": [
            {
                "move_id": "M1",
                "fix_id": "FP1",
                "op": "replace_range",
                "reason": "Improves specificity",
                "targets": ["Personalization_Intent"],
                "supported_by": ["ctx:1"],
                "payload": {
                    "start_line_id": 1,
                    "end_line_id": 1,
                    "new_lines": ["New line"],
                },
            }
        ],
    }
    parsed = parse_and_validate_rewrite(json.dumps(payload))
    assert parsed.applied_fix_ids == ["FP1"]
    assert parsed.moves[0].payload["new_lines"][0] == "New line"


def test_parse_and_validate_rewrite_rejects_invalid_target_enum() -> None:
    payload = {
        "applied_fix_ids": ["FP1"],
        "skipped_fix_ids": [],
        "moves": [
            {
                "move_id": "M1",
                "fix_id": "FP1",
                "op": "replace_range",
                "reason": "Improves specificity",
                "targets": ["InvalidTarget"],
                "supported_by": ["ctx:1"],
                "payload": {
                    "start_line_id": 1,
                    "end_line_id": 1,
                    "new_lines": ["New line"],
                },
            }
        ],
    }
    with pytest.raises(Exception):
        parse_and_validate_rewrite(json.dumps(payload))
