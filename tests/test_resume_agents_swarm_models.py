from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.resume_agents_swarm.models import ResumeRewriteModel, ResumeScoreModel


def test_score_model_validates_minimal_payload() -> None:
    payload = {
        "Total_Score": 71,
        "Breakdown": {
            "First_Pass_Clarity": 10,
            "Impact_Specificity": 18,
            "JD_Alignment": 22,
            "Hard_Skills_Keywords": 14,
            "Action_Language": 7,
        },
        "Pass_7s_Summary": {
            "Target_Role_Clear": True,
            "Core_Stack_Clear": True,
            "Top_Impact_Clear": False,
            "What_Recruiter_Notices_First": ["ML engineer profile", "Python + cloud stack"],
            "What_Should_Be_Obvious_But_Isnt": ["Quantified business impact"],
        },
        "Job_Requirement_Map": {
            "Must_Have_Skills": ["Python"],
            "Nice_To_Have_Skills": ["Kubernetes"],
            "Top_Responsibilities": ["Deploy models"],
            "Role_Signals": ["Senior"],
            "Repeated_Keywords": ["production"],
        },
        "Evidence": {
            "Must_Haves_Coverage": [
                {
                    "skill": "Python",
                    "covered": True,
                    "evidence_spans": ["Built Python APIs"],
                    "evidence_quality": "Strong",
                }
            ],
            "Responsibilities_Coverage": [
                {
                    "responsibility": "Deploy models",
                    "covered": True,
                    "evidence_spans": ["Deployed model service"],
                    "evidence_quality": "Weak",
                }
            ],
        },
        "Critical_Feedback": ["Add measurable outcomes."],
        "Fluff_Detected": [],
        "Stuffed_Keywords": [],
        "Weak_Evidence_Keywords": ["Kubernetes"],
        "Missing_Keywords": ["Airflow"],
        "Contradictions_Or_Risks": [],
        "High_Leverage_Sections_To_Edit": [
            {
                "section_hint": "Experience bullet 2",
                "why": "No metrics",
                "goal": "Add impact",
            }
        ],
        "Fix_Plan": [
            {
                "fix_id": "FP1",
                "priority": 1,
                "expected_score_gain": 6,
                "category": "Impact_Specificity",
                "location_hint": "Experience bullet 2",
                "problem": "No measurable outcome",
                "required_evidence": "Include latency improvement metric",
                "rewrite_goal": "Add metric and ownership",
            }
        ],
        "Non_Negotiables": ["Quantify top bullets"],
    }

    model = ResumeScoreModel.model_validate(payload)
    assert model.Total_Score == 71
    assert model.Fix_Plan[0].fix_id == "FP1"


def test_rewrite_model_validates_payload() -> None:
    payload = {
        "applied_fix_ids": ["FP1"],
        "skipped_fix_ids": [{"fix_id": "FP2", "why": "Missing evidence"}],
        "moves": [
            {
                "move_id": "M1",
                "fix_id": "FP1",
                "op": "replace_range",
                "reason": "Improves impact specificity",
                "targets": ["Impact_Specificity", "JD_Alignment"],
                "supported_by": ["ctx:1"],
                "payload": {
                    "start_line_id": 3,
                    "end_line_id": 3,
                    "new_lines": ["\\item Built API and reduced latency by [X]\\%"],
                },
            }
        ],
    }
    model = ResumeRewriteModel.model_validate(payload)
    assert model.applied_fix_ids == ["FP1"]
    assert model.moves[0].targets[0] == "Impact_Specificity"
