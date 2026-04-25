from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import fetch_ashby, normalize_ashby


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


_API_RESPONSE = {
    "jobPostings": [
        {
            "id": "abc123",
            "title": "ML Engineer",
            "locationName": "Remote, Canada",
            "publishedDate": "2026-01-15",
        }
    ]
}


def test_fetch_ashby_prefers_json_api(monkeypatch) -> None:
    """fetch_ashby should hit api.ashbyhq.com first, not the HTML page."""
    api_urls: list[str] = []
    html_urls: list[str] = []

    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        if "api.ashbyhq.com" in url:
            api_urls.append(url)
            return _FakeResponse(_API_RESPONSE)
        html_urls.append(url)
        raise AssertionError(f"HTML fallback should not be called when API succeeds: {url}")

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    result = fetch_ashby("test-org")

    assert api_urls == ["https://api.ashbyhq.com/posting-api/job-board/test-org"]
    assert not html_urls, "HTML endpoint should not be called when API succeeds"
    assert len(result) == 1
    assert result[0]["jobPostingUrl"] == "https://jobs.ashbyhq.com/test-org/abc123"


def test_fetch_ashby_falls_back_to_html_when_api_fails(monkeypatch) -> None:
    """If the JSON API returns non-200, fetch_ashby falls back to HTML scraping."""
    html_content = (
        'window.__data = {"jobPostings": ['
        '{"id": "xyz", "title": "Data Scientist", "locationName": "Vancouver"}'
        ']}'
    )

    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        if "api.ashbyhq.com" in url:
            return _FakeResponse({}, status_code=404)
        return _FakeResponse(html_content)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    result = fetch_ashby("test-org")

    assert any(r.get("title") == "Data Scientist" for r in result)


# --- normalizer tests ---

def test_normalize_ashby_extracts_required_fields() -> None:
    raw = {
        "id": "abc123",
        "title": "Data Scientist",
        "locationName": "Vancouver, BC",
        "publishedDate": "2026-01-15",
        "jobPostingUrl": "https://jobs.ashbyhq.com/acme/abc123",
    }
    result = normalize_ashby(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "Data Scientist"
    assert result["location"] == "Vancouver, BC"
    assert result["url"] == "https://jobs.ashbyhq.com/acme/abc123"
    assert result["ats"] == "ashby"
    assert result["posted"] == "2026-01-15"


def test_normalize_ashby_falls_back_to_location_field() -> None:
    raw = {"title": "ML Eng", "location": "Remote", "publishedDate": "2026-01-15",
           "jobPostingUrl": "https://jobs.ashbyhq.com/acme/1"}
    result = normalize_ashby(raw, "Acme")
    assert result["location"] == "Remote"


# --- fixture integration test ---

def test_fetch_ashby_fixture(monkeypatch) -> None:
    fixture_files = list((Path(__file__).parent / "fixtures").glob("ashby_*.html"))
    if not fixture_files:
        pytest.skip("No ashby fixture -- run scripts/record_fixtures.py first")
    fixture_text = fixture_files[0].read_text(encoding="utf-8")
    slug = fixture_files[0].stem.split("_", 1)[1]

    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        if "api.ashbyhq.com" in url:
            # Return non-200 to force HTML fallback (fixture is HTML)
            return _FakeResponse({}, status_code=404)
        return _FakeResponse(fixture_text)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    results = fetch_ashby(slug)

    assert len(results) > 0, "Expected at least one job from fixture"
    normalized = [normalize_ashby(r, "FixtureTest") for r in results]
    for n in normalized:
        assert all(k in n for k in ("company", "title", "location", "url", "posted", "ats"))
        assert n["url"].startswith("https://")
        assert n["ats"] == "ashby"
