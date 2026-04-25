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
