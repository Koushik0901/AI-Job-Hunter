from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.resume_agents_swarm.parsing import JsonExtractionError, extract_first_json_object


def test_extract_first_json_object_with_wrapper_text() -> None:
    raw = "hello before\n```json\n{\"a\": 1, \"b\": {\"c\": true}}\n```\nafter"
    assert extract_first_json_object(raw) == '{"a": 1, "b": {"c": true}}'


def test_extract_first_json_object_handles_braces_inside_string() -> None:
    raw = 'text {"note":"value with } brace", "ok": true} trailing'
    assert extract_first_json_object(raw) == '{"note":"value with } brace", "ok": true}'


def test_extract_first_json_object_raises_when_missing() -> None:
    with pytest.raises(JsonExtractionError):
        extract_first_json_object("no json here")
