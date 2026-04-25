from __future__ import annotations

import json
from pathlib import Path
from typing import Any


from ai_job_hunter.fetchers import fetch_workable
from ai_job_hunter.fetchers import fetch_workable_description


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.content = b"ok"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def test_fetch_workable_follows_next_page_token(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_post(url: str, json: dict[str, Any], headers: dict | None = None, timeout: int = 30) -> _FakeResponse:
        calls.append({"url": url, "json": json, "timeout": timeout})
        token = json.get("token")
        if not token:
            return _FakeResponse(
                {
                    "total": 3,
                    "results": [
                        {
                            "shortcode": "AAA111",
                            "title": "AI Engineer",
                            "location": {"city": "Toronto", "country": "Canada"},
                        },
                        {
                            "shortcode": "BBB222",
                            "title": "ML Engineer",
                            "location": {"city": "Montreal", "country": "Canada"},
                        },
                    ],
                    "nextPage": "token-2",
                }
            )
        assert token == "token-2"
        return _FakeResponse(
            {
                "total": 3,
                "results": [
                    {
                        "shortcode": "CCC333",
                        "title": "AI Product Engineer",
                        "location": {"city": "Winnipeg", "country": "Canada"},
                    }
                ],
                "nextPage": "",
            }
        )

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.post", fake_post)

    jobs = fetch_workable("example-company")

    assert len(jobs) == 3
    assert [job["shortcode"] for job in jobs] == ["AAA111", "BBB222", "CCC333"]
    assert calls[0]["json"] == {}
    assert calls[1]["json"] == {"token": "token-2"}
    assert jobs[0]["absolute_url"] == "https://apply.workable.com/example-company/j/AAA111"
    assert jobs[0]["_location_str"] == "Toronto, Canada"


def test_fetch_workable_description_uses_v2_job_endpoint(monkeypatch) -> None:
    seen: dict[str, Any] = {}

    def fake_get(url: str, timeout: int) -> _FakeResponse:
        seen["url"] = url
        seen["timeout"] = timeout
        return _FakeResponse({"description": "<p>AI team role</p>"})

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.get", fake_get)

    description = fetch_workable_description("example-company", "ABC123")

    assert description == "AI team role"
    assert seen["url"] == "https://apply.workable.com/api/v2/accounts/example-company/jobs/ABC123"
    assert seen["timeout"] == 30


def test_fetch_workable_sends_required_headers(monkeypatch) -> None:
    """fetch_workable must include Origin, Referer, and User-Agent headers."""
    captured: dict = {}

    def fake_post(url: str, json: Any, headers: dict | None = None,
                  timeout: int = 30) -> _FakeResponse:
        captured["headers"] = dict(headers or {})
        return _FakeResponse(
            {"total": 1, "results": [{"shortcode": "X1", "title": "AI Eng"}], "nextPage": ""}
        )

    monkeypatch.setattr("ai_job_hunter.fetchers.requests.post", fake_post)
    fetch_workable("example-co")

    assert "Origin" in captured["headers"], "Missing Origin header"
    assert captured["headers"]["Origin"] == "https://apply.workable.com"
    assert "Referer" in captured["headers"], "Missing Referer header"
    assert captured["headers"]["Referer"] == "https://apply.workable.com/example-co/"
    assert "User-Agent" in captured["headers"], "Missing User-Agent header"
