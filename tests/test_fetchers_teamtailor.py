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
