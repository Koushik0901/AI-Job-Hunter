from __future__ import annotations

from typing import Any
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fetchers import fetch_workable
from fetchers import fetch_workable_description


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

    def fake_post(url: str, json: dict[str, Any], timeout: int) -> _FakeResponse:
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

    monkeypatch.setattr("fetchers.requests.post", fake_post)

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

    monkeypatch.setattr("fetchers.requests.get", fake_get)

    description = fetch_workable_description("example-company", "ABC123")

    assert description == "AI team role"
    assert seen["url"] == "https://apply.workable.com/api/v2/accounts/example-company/jobs/ABC123"
    assert seen["timeout"] == 30
