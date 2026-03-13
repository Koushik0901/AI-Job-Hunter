from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.evidence_assets import derive_fallback_evidence_assets, prepare_candidate_evidence_assets


def _candidate_profile() -> dict:
    return {
        "years_experience": 4,
        "skills": ["Python", "FastAPI", "LangGraph"],
        "target_role_families": ["ml_platform", "software_engineering"],
        "requires_visa_sponsorship": False,
        "education": [{"degree": "MSc", "field": "Computer Science"}],
    }


def _resume_profile() -> dict:
    return {
        "baseline_resume_json": {
            "basics": {
                "name": "Test User",
                "headline": "ML Engineer",
                "summary": "Built retrieval and evaluation systems for production AI products.",
                "location": "Edmonton, AB",
            },
            "skills": [{"name": "Qdrant"}, {"name": "OpenAI"}, "Redis"],
            "work": [
                {
                    "name": "Acme",
                    "position": "ML Engineer",
                    "summary": "Owned RAG platform reliability.",
                    "highlights": [
                        "Built evaluation harnesses for resume tailoring.",
                        "Reduced latency with Redis-backed caching.",
                    ],
                    "startDate": "2024-01",
                    "endDate": "2025-12",
                }
            ],
            "projects": [
                {
                    "name": "Evidence Vault",
                    "summary": "Hybrid retrieval over brag docs and project cards.",
                    "highlights": ["Implemented lexical + vector retrieval."],
                    "keywords": ["Qdrant", "LangChain"],
                }
            ],
        }
    }


def test_derive_fallback_evidence_assets_builds_grounded_payload() -> None:
    assets = derive_fallback_evidence_assets(_candidate_profile(), _resume_profile())
    evidence = assets["evidence_context"]
    assert evidence["candidate_profile"]["years_experience"] == 4
    assert "FastAPI" in evidence["candidate_profile"]["skills"]
    assert evidence["resume_basics"]["headline"] == "ML Engineer"
    assert len(evidence["work_experience"]) == 1
    assert len(assets["project_cards"]) == 1
    assert "RAG platform reliability" in assets["brag_document_markdown"]


def test_prepare_candidate_evidence_assets_preserves_explicit_fields_and_fills_missing() -> None:
    explicit = {
        "evidence_context": {},
        "brag_document_markdown": "",
        "project_cards": [],
        "do_not_claim": ["kubernetes"],
    }
    prepared = prepare_candidate_evidence_assets(explicit, _candidate_profile(), _resume_profile())
    assert prepared["do_not_claim"] == ["kubernetes"]
    assert prepared["project_cards"]
    assert prepared["brag_document_markdown"]
    assert prepared["evidence_context"]["candidate_profile"]["skills"]


def test_prepare_candidate_evidence_assets_prefers_explicit_evidence() -> None:
    explicit = {
        "evidence_context": {"custom": {"fact": "Use this"}},
        "brag_document_markdown": "Explicit brag doc",
        "project_cards": [{"title": "Explicit Project"}],
        "do_not_claim": [],
    }
    prepared = prepare_candidate_evidence_assets(explicit, _candidate_profile(), _resume_profile())
    assert prepared["evidence_context"] == explicit["evidence_context"]
    assert prepared["brag_document_markdown"] == "Explicit brag doc"
    assert prepared["project_cards"] == [{"title": "Explicit Project"}]
