from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fetchers import _find_hn_hiring_thread


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_find_hn_hiring_thread_prefers_latest_monthly_thread(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _fake_get(url, params=None, timeout=None):
        seen["url"] = url
        seen["params"] = params
        seen["timeout"] = timeout
        return _FakeResponse(
            {
                "hits": [
                    {
                        "author": "whoishiring",
                        "title": "Ask HN: Who wants to be hired? (March 2026)",
                        "objectID": "47219667",
                    },
                    {
                        "author": "whoishiring",
                        "title": "Ask HN: Who is hiring? (March 2026)",
                        "objectID": "47219668",
                    },
                    {
                        "author": "whoishiring",
                        "title": "Ask HN: Who is hiring? (February 2026)",
                        "objectID": "46857488",
                    },
                ]
            }
        )

    monkeypatch.setattr("fetchers.requests.get", _fake_get)

    thread_id = _find_hn_hiring_thread()

    assert thread_id == 47219668
    assert seen["url"] == "https://hn.algolia.com/api/v1/search_by_date"
    assert seen["params"] == {
        "query": "Ask HN: Who is hiring?",
        "tags": "story,author_whoishiring",
        "hitsPerPage": 20,
    }
