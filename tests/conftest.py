from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Load a raw fixture file from tests/fixtures/ as text."""
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def load_fixture_json(name: str) -> Any:
    """Load a JSON fixture file from tests/fixtures/ and parse it."""
    return json.loads(load_fixture(name))
