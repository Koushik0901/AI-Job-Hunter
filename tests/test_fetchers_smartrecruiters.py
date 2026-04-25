from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from ai_job_hunter.fetchers import fetch_smartrecruiters, normalize_smartrecruiters


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

def test_normalize_smartrecruiters_non_remote() -> None:
    raw = {
        "id": "sr-123",
        "name": "ML Platform Engineer",
        "location": {"city": "Toronto", "region": "Ontario", "country": "Canada", "remote": False},
        "releasedDate": "2026-01-15",
        "ref": "https://careers.smartrecruiters.com/Acme/sr-123",
    }
    result = normalize_smartrecruiters(raw, "Acme")

    assert result["company"] == "Acme"
    assert result["title"] == "ML Platform Engineer"
    assert result["location"] == "Toronto, Ontario, Canada"
    assert result["url"] == "https://careers.smartrecruiters.com/Acme/sr-123"
    assert result["ats"] == "smartrecruiters"
    assert result["posted"] == "2026-01-15"


def test_normalize_smartrecruiters_remote_prepended() -> None:
    raw = {
        "id": "sr-456",
        "name": "Data Scientist",
        "location": {"city": "Toronto", "country": "Canada", "remote": True},
        "releasedDate": "2026-01-15",
        "ref": "https://careers.smartrecruiters.com/Acme/sr-456",
    }
    result = normalize_smartrecruiters(raw, "Acme")

    assert result["location"].startswith("Remote")
    assert "Toronto" in result["location"]
