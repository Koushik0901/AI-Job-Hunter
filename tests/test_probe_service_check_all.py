from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from ai_job_hunter.services.probe_service import probe_company_sources_all

_ROWS = [
    {"id": 1, "name": "Acme", "ats_type": "greenhouse", "slug": "acme",
     "ats_url": "https://boards-api.greenhouse.io/v1/boards/acme/jobs", "enabled": 1},
    {"id": 2, "name": "Beta", "ats_type": "lever", "slug": "beta",
     "ats_url": "https://api.lever.co/v0/postings/beta", "enabled": 1},
    {"id": 3, "name": "Gamma", "ats_type": "greenhouse", "slug": "gamma",
     "ats_url": "https://boards-api.greenhouse.io/v1/boards/gamma/jobs", "enabled": 0},
]


def _make_ok_response(jobs: int = 3) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"jobs": [{"id": i} for i in range(jobs)]}
    r.text = '{"jobs": []}'
    r.url = ""
    return r


def test_probe_company_sources_all_returns_one_result_per_enabled_row() -> None:
    with patch("ai_job_hunter.services.probe_service._send_probe_request") as mock_send:
        mock_send.return_value = _make_ok_response(3)
        results = probe_company_sources_all(_ROWS)

    assert len(results) == 2  # disabled row excluded by default
    assert all("probe_status" in r for r in results)
    assert all("probe_jobs" in r for r in results)


def test_probe_company_sources_all_include_disabled() -> None:
    with patch("ai_job_hunter.services.probe_service._send_probe_request") as mock_send:
        mock_send.return_value = _make_ok_response(1)
        results = probe_company_sources_all(_ROWS, include_disabled=True)

    assert len(results) == 3


def test_probe_company_sources_all_ats_filter() -> None:
    with patch("ai_job_hunter.services.probe_service._send_probe_request") as mock_send:
        mock_send.return_value = _make_ok_response(2)
        results = probe_company_sources_all(_ROWS, ats_filter="greenhouse")

    assert len(results) == 1  # only enabled greenhouse row
    assert results[0]["name"] == "Acme"


def test_probe_company_sources_all_marks_errors() -> None:
    import requests

    def raise_error(method: str, url: str, ats_name: str):
        raise requests.ConnectionError("timeout")

    with patch("ai_job_hunter.services.probe_service._send_probe_request", side_effect=raise_error):
        results = probe_company_sources_all(_ROWS)

    assert all(r["probe_status"] == "ERROR" for r in results)
    assert all("ConnectionError" in r["probe_note"] for r in results)
