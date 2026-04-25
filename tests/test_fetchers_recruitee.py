from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import fetch_recruitee, normalize_recruitee


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

def test_normalize_recruitee_builds_url_from_slug() -> None:
    raw = {
        "id": 123,
        "title": "NLP Engineer",
        "slug": "nlp-engineer-123",
        "company_slug": "acme",
        "location": {"city": "Remote", "country": "Canada"},
        "created_at": "2026-01-15T10:00:00Z",
    }
    result = normalize_recruitee(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "NLP Engineer"
    assert "Remote" in result["location"]
    assert result["url"] == "https://acme.recruitee.com/o/nlp-engineer-123"
    assert result["ats"] == "recruitee"
    assert result["posted"] == "2026-01-15"


def test_normalize_recruitee_string_location() -> None:
    raw = {
        "title": "Data Engineer",
        "slug": "data-eng-1",
        "company_slug": "acme",
        "location": "Vancouver, BC, Canada",
        "created_at": "2026-01-15T10:00:00Z",
    }
    result = normalize_recruitee(raw, "Acme")

    assert result["location"] == "Vancouver, BC, Canada"


# --- fixture integration test ---

def test_fetch_recruitee_fixture(monkeypatch) -> None:
    fixture_files = list((Path(__file__).parent / "fixtures").glob("recruitee_*.json"))
    if not fixture_files:
        pytest.skip("No recruitee fixture -- run scripts/record_fixtures.py first")
    data = json.loads(fixture_files[0].read_text(encoding="utf-8"))
    slug = fixture_files[0].stem.split("_", 1)[1]

    def fake_get(url: str, timeout: int = 30) -> _FakeResponse:
        return _FakeResponse(data)

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    results = fetch_recruitee(slug)

    assert len(results) > 0, "Expected at least one job from fixture"
    normalized = [normalize_recruitee(r, "FixtureTest") for r in results]
    for n in normalized:
        assert all(k in n for k in ("company", "title", "location", "url", "posted", "ats"))
        assert n["ats"] == "recruitee"
