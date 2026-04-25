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
