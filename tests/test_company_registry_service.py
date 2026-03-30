from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from db import init_db
from services import company_registry_service


def test_probe_company_sources_splits_zero_job_hits_with_explicit_reason(monkeypatch) -> None:
    monkeypatch.setattr(
        company_registry_service,
        "probe_all",
        lambda slugs, url_templates: [
            {
                "slug": "example-company",
                "ats": "greenhouse",
                "ats_url": "https://boards-api.greenhouse.io/v1/boards/example-company/jobs",
                "jobs": 4,
            },
            {
                "slug": "example-company",
                "ats": "workable",
                "ats_url": "https://apply.workable.com/api/v3/accounts/example-company/jobs",
                "jobs": 0,
            },
            {
                "slug": "example-company",
                "ats": "smartrecruiters",
                "ats_url": "https://api.smartrecruiters.com/v1/companies/example-company/postings",
                "jobs": 0,
            },
        ],
    )

    result = company_registry_service.probe_company_sources("Example Company")

    assert [item["ats_type"] for item in result["matches"]] == ["greenhouse"]
    assert [item["ats_type"] for item in result["zero_job_matches"]] == ["smartrecruiters", "workable"]
    assert all(item["low_signal"] is True for item in result["zero_job_matches"])
    assert all(item["suppressed_reason"] == "low_signal_zero_jobs" for item in result["zero_job_matches"])


def test_probe_company_sources_blocks_hiring_cafe_query() -> None:
    result = company_registry_service.probe_company_sources("https://hiring.cafe")

    assert result["matches"] == []
    assert result["zero_job_matches"] == [
        {
            "name": "Hiring Cafe",
            "slug": "hiring-cafe",
            "ats_type": "blocked",
            "ats_url": "https://hiring.cafe",
            "jobs": 0,
            "low_signal": True,
            "suppressed_reason": "blocked_source",
        }
    ]


def test_save_company_source_rejects_hiring_cafe(tmp_path) -> None:
    conn = init_db(str(tmp_path / "jobs.db"))
    try:
        with pytest.raises(ValueError, match="Hiring Cafe is blocked"):
            company_registry_service.save_company_source(
                conn,
                {
                    "name": "Hiring Cafe",
                    "ats_type": "greenhouse",
                    "slug": "hiring-cafe",
                    "ats_url": "https://hiring.cafe",
                },
            )
    finally:
        conn.close()


def test_probe_company_sources_limits_probes_when_careers_url_is_inferred(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_probe_all(slugs, url_templates):
        calls.append((list(slugs), dict(url_templates)))
        return [
            {
                "slug": "acme",
                "ats": "teamtailor",
                "ats_url": "https://acme.teamtailor.com/jobs",
                "jobs": 5,
            }
        ]

    monkeypatch.setattr(company_registry_service, "probe_all", fake_probe_all)

    result = company_registry_service.probe_company_sources("https://acme.teamtailor.com/jobs")

    assert result["inferred"] == {"ats_type": "teamtailor", "slug": "acme"}
    assert [item["ats_type"] for item in result["matches"]] == ["teamtailor"]
    assert calls == [(["acme"], {"teamtailor": "https://{slug}.teamtailor.com/jobs"})]


def test_probe_company_sources_preserves_mixed_case_explicit_slug(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_probe_all(slugs, url_templates):
        calls.append((list(slugs), dict(url_templates)))
        return []

    monkeypatch.setattr(company_registry_service, "probe_all", fake_probe_all)

    company_registry_service.probe_company_sources("Energy Vault", extra_slugs=["EnergyVault"])

    assert len(calls) == 1
    slugs, url_templates = calls[0]
    assert "EnergyVault" in slugs
    assert url_templates["lever"] == "https://api.lever.co/v0/postings/{slug}"


def test_extract_slug_from_careers_url_preserves_case_for_lever() -> None:
    assert company_registry_service.extract_slug_from_careers_url("https://jobs.lever.co/EnergyVault/123-role") == (
        "lever",
        "EnergyVault",
    )


def test_save_company_source_preserves_case_sensitive_slug(tmp_path) -> None:
    conn = init_db(str(tmp_path / "jobs.db"))
    try:
        saved = company_registry_service.save_company_source(
            conn,
            {
                "name": "Energy Vault",
                "ats_type": "lever",
                "slug": "EnergyVault",
            },
        )
        assert saved["slug"] == "EnergyVault"
        assert saved["ats_url"] == "https://api.lever.co/v0/postings/EnergyVault"
    finally:
        conn.close()
