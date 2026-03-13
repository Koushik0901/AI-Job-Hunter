from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

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
