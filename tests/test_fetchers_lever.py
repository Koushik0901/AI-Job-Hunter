from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import fetch_lever, normalize_lever


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


_LEVER_RAW = {
    "text": "Machine Learning Engineer",
    "hostedUrl": "https://jobs.lever.co/acme/abc-123",
    "createdAt": 1700000000000,
    "categories": {"location": "Remote, Canada"},
    "descriptionPlain": "Build ML systems.",
    "lists": [],
    "additionalPlain": "",
}


def test_fetch_lever_sends_user_agent(monkeypatch) -> None:
    captured: dict = {}

    def fake_get(url: str, headers: dict | None = None, timeout: int = 30) -> _FakeResponse:
        captured["headers"] = dict(headers or {})
        return _FakeResponse([_LEVER_RAW])

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)
    result = fetch_lever("test-co")

    assert "User-Agent" in captured["headers"], "Missing User-Agent header"
    assert len(result) == 1


# --- normalizer tests ---

def test_normalize_lever_extracts_required_fields() -> None:
    raw = {
        "text": "Machine Learning Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/abc-123",
        "createdAt": 1700000000000,
        "categories": {"location": "Remote, Canada"},
    }
    result = normalize_lever(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "Machine Learning Engineer"
    assert result["location"] == "Remote, Canada"
    assert result["url"] == "https://jobs.lever.co/acme/abc-123"
    assert result["ats"] == "lever"
    assert result["posted"] == "2023-11-14"


def test_normalize_lever_handles_missing_categories() -> None:
    raw = {"text": "Data Scientist", "hostedUrl": "https://jobs.lever.co/acme/xyz", "createdAt": None}
    result = normalize_lever(raw, "Acme")

    assert result["location"] == ""
    assert result["posted"] == ""
    assert result["url"].startswith("https://")
