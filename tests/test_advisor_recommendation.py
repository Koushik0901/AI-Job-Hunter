from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.advisor import build_recommendation


def _base_profile() -> dict[str, object]:
    return {
        "years_experience": 6,
        "skills": ["python", "sql", "pytorch"],
        "desired_job_titles": ["ML Engineer"],
        "target_role_families": ["ml engineer"],
        "requires_visa_sponsorship": False,
    }


def _enrichment() -> dict[str, object]:
    return {
        "role_family": "ml engineer",
        "required_skills": ["python", "sql"],
        "preferred_skills": ["pytorch"],
        "visa_sponsorship": "yes",
        "enrichment_status": "ok",
    }


def _recent_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def test_recommendation_uses_compact_evaluation_for_early_stage_jobs() -> None:
    rec = build_recommendation(
        profile=_base_profile(),
        job={
            "status": "not_applied",
            "posted": _recent_date(),
            "match_score": 92,
            "desired_title_match": True,
            "enrichment": _enrichment(),
        },
        source_quality_score=72,
        role_quality_score=68,
    )

    assert rec["recommendation"] == "apply_now"
    assert rec["guidance_mode"] == "evaluation"
    assert rec["guidance_title"] == "Strong candidate to apply"
    assert rec["health_label"] == "ready"
    assert rec["next_best_action"] == "Apply now."
    assert rec["guidance_reasons"]
    assert "interview" not in rec["guidance_summary"].lower()


@pytest.mark.parametrize(
    ("status", "title", "health", "action_phrase", "summary_phrase", "reason_token"),
    [
        ("applied", "Application in flight", "in_process", "follow up", "follow-up cadence", "application"),
        ("interviewing", "Interview loop active", "active", "prepare", "prep prompts", "interview"),
        ("offer", "Offer stage", "decision_time", "review the terms", "compare compensation", "decision"),
    ],
)
def test_recommendation_uses_stage_narrative_for_later_stages(
    status: str,
    title: str,
    health: str,
    action_phrase: str,
    summary_phrase: str,
    reason_token: str,
) -> None:
    rec = build_recommendation(
        profile=_base_profile(),
        job={
            "status": status,
            "posted": _recent_date(),
            "match_score": 92,
            "desired_title_match": True,
            "enrichment": _enrichment(),
        },
        source_quality_score=72,
        role_quality_score=68,
    )

    assert rec["recommendation"] == "hold"
    assert rec["guidance_mode"] == "stage_narrative"
    assert rec["guidance_title"] == title
    assert rec["health_label"] == health
    assert action_phrase in rec["next_best_action"].lower()
    assert summary_phrase in rec["guidance_summary"].lower()
    assert any(reason_token in reason.lower() for reason in rec["guidance_reasons"])


def test_interviewing_stage_guidance_does_not_fall_back_to_raw_fit_warning_language() -> None:
    rec = build_recommendation(
        profile=_base_profile(),
        job={
            "status": "interviewing",
            "posted": _recent_date(),
            "match_score": 28,
            "desired_title_match": False,
            "enrichment": _enrichment(),
        },
        source_quality_score=40,
        role_quality_score=42,
    )

    assert rec["guidance_mode"] == "stage_narrative"
    assert all("fit signals are weak" not in reason.lower() for reason in rec["guidance_reasons"])
    assert all("moderate fit worth a closer review" not in reason.lower() for reason in rec["guidance_reasons"])
