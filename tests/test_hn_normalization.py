from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fetchers import normalize_hn


def test_normalize_hn_pipe_delimited_header_keeps_clean_title_and_location() -> None:
    raw = {
        "objectID": "1",
        "created_at": "2026-03-11T00:00:00Z",
        "comment_text": (
            "Hightouch | Multiple Roles | Remote | Full-time | $180,000 - $320,000 USD + equity"
            "<p>Hightouch is building an AI platform for marketing and growth teams.</p>"
        ),
    }

    normalized = normalize_hn(raw)

    assert normalized["company"] == "Hightouch"
    assert normalized["title"] == "Multiple Roles"
    assert normalized["location"] == "Remote"


def test_normalize_hn_dash_delimited_header_extracts_company_role_and_context() -> None:
    raw = {
        "objectID": "2",
        "created_at": "2026-03-11T00:00:00Z",
        "comment_text": (
            "Hearo (Remote) — Founding Engineer — AI Product Intelligence Platform Apply: https://example.com"
            "<p>Hearo is building an AI platform that turns public internet conversations into structured product intelligence.</p>"
        ),
    }

    normalized = normalize_hn(raw)

    assert normalized["company"] == "Hearo"
    assert normalized["title"] == "Founding Engineer - AI Product Intelligence Platform"
    assert normalized["location"] == "Remote"


def test_hn_generic_titles_preserve_context_in_description() -> None:
    raw = {
        "objectID": "3",
        "created_at": "2026-03-11T00:00:00Z",
        "comment_text": (
            "Atomic Tessellator | Various | REMOTE (UTC+12) | https://example.com"
            "<p>We are hiring for Lead Engineer, LLMs and other AI roles.</p>"
        ),
    }

    normalized = normalize_hn(raw)

    assert normalized["company"] == "Atomic Tessellator"
    assert normalized["title"].startswith("Various")
    assert normalized["location"] == "REMOTE (UTC+12)"
    assert "Lead Engineer, LLMs and other AI roles." in normalized["description"]
