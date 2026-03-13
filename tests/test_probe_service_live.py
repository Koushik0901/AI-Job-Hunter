from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from services.probe_service import probe_all


LIVE_CASES: list[tuple[str, str, int]] = [
    ("greenhouse", "stripe", 1),
    ("lever", "source", 1),
    ("ashby", "openai", 1),
    ("workable", "valsoft-corp", 1),
    ("smartrecruiters", "Visa", 1),
    ("recruitee", "source", 1),
]


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_ATS_PROBE_TESTS", "").strip() != "1",
    reason="Set RUN_LIVE_ATS_PROBE_TESTS=1 to run live ATS probe checks.",
)


@pytest.mark.live_network
@pytest.mark.parametrize(("ats_name", "slug", "minimum_jobs"), LIVE_CASES)
def test_probe_all_live_public_boards(ats_name: str, slug: str, minimum_jobs: int) -> None:
    rows = probe_all([slug], {})
    matches = [row for row in rows if row.get("ats") == ats_name and row.get("slug") == slug]
    assert matches, f"Expected a live {ats_name} match for slug {slug!r}, got {rows!r}"
    assert int(matches[0].get("jobs", 0) or 0) >= minimum_jobs
