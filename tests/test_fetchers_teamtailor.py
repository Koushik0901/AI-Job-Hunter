from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import normalize_teamtailor


class _FakeResponse:
    def __init__(self, body: Any, status_code: int = 200) -> None:
        if isinstance(body, (dict, list)):
            self._text = json.dumps(body)
            self._json: Any = body
        else:
            self._text = str(body)
            self._json = None
        self.status_code = status_code
        self.content = self._text.encode("utf-8")
        self.url = ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._json if self._json is not None else json.loads(self._text)

    @property
    def text(self) -> str:
        return self._text


# --- normalizer tests ---

def test_normalize_teamtailor_extracts_required_fields() -> None:
    raw = {
        "@type": "JobPosting",
        "title": "AI Research Scientist",
        "url": "https://careers.acme.com/jobs/123-ai-research-scientist",
        "datePosted": "2026-01-15",
        "location": "Remote, Canada",
    }
    result = normalize_teamtailor(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "AI Research Scientist"
    assert result["location"] == "Remote, Canada"
    assert result["url"] == "https://careers.acme.com/jobs/123-ai-research-scientist"
    assert result["ats"] == "teamtailor"
    assert result["posted"] == "2026-01-15"


def test_normalize_teamtailor_handles_empty_location() -> None:
    raw = {
        "title": "ML Eng",
        "url": "https://careers.acme.com/jobs/1",
        "datePosted": "2026-01-15",
    }
    result = normalize_teamtailor(raw, "Acme")
    assert result["location"] == ""


# --- fixture integration test ---

def test_fetch_teamtailor_fixture(monkeypatch) -> None:
    from ai_job_hunter.fetchers import fetch_teamtailor, _extract_teamtailor_job_urls
    fixture_files = list((Path(__file__).parent / "fixtures").glob("teamtailor_*.html"))
    if not fixture_files:
        pytest.skip("No teamtailor fixture -- run scripts/record_fixtures.py first")
    list_html = fixture_files[0].read_text(encoding="utf-8")
    slug = fixture_files[0].stem.split("_", 1)[1]
    base_url = f"https://{slug}.teamtailor.com/jobs"
    job_urls = _extract_teamtailor_job_urls(base_url, list_html)
    if not job_urls:
        pytest.skip("No job URLs in teamtailor fixture -- re-record with a company that has active listings")

    # Minimal LD+JSON detail page to satisfy _extract_teamtailor_job_posting
    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        if url == base_url:
            return _FakeResponse(list_html)
        detail_html = (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","title":"Software Engineer",'
            f'"url":"{url}","datePosted":"2026-01-15",'
            '"jobLocation":[{"@type":"Place","address":{"addressLocality":"Remote"}}]}'
            "</script>"
        )
        return _FakeResponse(detail_html)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    results = fetch_teamtailor(slug)

    assert len(results) > 0, "Expected at least one job"
    normalized = [normalize_teamtailor(r, "FixtureTest") for r in results]
    for n in normalized:
        assert all(k in n for k in ("company", "title", "location", "url", "posted", "ats"))
        assert n["ats"] == "teamtailor"
