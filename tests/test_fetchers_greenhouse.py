from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import fetch_greenhouse, normalize_greenhouse


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

def test_normalize_greenhouse_extracts_required_fields() -> None:
    raw = {
        "id": 12345,
        "title": "Machine Learning Engineer",
        "location": {"name": "Remote, Canada"},
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/12345",
        "updated_at": "2026-01-15T10:00:00Z",
    }
    result = normalize_greenhouse(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "Machine Learning Engineer"
    assert result["location"] == "Remote, Canada"
    assert result["url"] == "https://boards.greenhouse.io/acme/jobs/12345"
    assert result["ats"] == "greenhouse"
    assert result["posted"] == "2026-01-15"


def test_normalize_greenhouse_handles_missing_location() -> None:
    raw = {
        "title": "Data Scientist",
        "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
        "updated_at": None,
    }
    result = normalize_greenhouse(raw, "Acme")

    assert result["location"] == ""
    assert result["posted"] == ""


# --- fixture integration test ---

def test_fetch_greenhouse_fixture(monkeypatch) -> None:
    fixture_files = list((Path(__file__).parent / "fixtures").glob("greenhouse_*.json"))
    if not fixture_files:
        pytest.skip("No greenhouse fixture -- run scripts/record_fixtures.py first")
    data = json.loads(fixture_files[0].read_text(encoding="utf-8"))
    slug = fixture_files[0].stem.split("_", 1)[1]

    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        return _FakeResponse(data)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    results = fetch_greenhouse(slug)

    assert len(results) > 0, "Expected at least one job from fixture"
    normalized = [normalize_greenhouse(r, "FixtureTest") for r in results]
    for n in normalized:
        assert all(k in n for k in ("company", "title", "location", "url", "posted", "ats"))
        assert n["url"].startswith("https://")
        assert n["ats"] == "greenhouse"
