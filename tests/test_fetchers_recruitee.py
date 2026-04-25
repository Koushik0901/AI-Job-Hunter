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
