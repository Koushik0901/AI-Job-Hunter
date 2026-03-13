from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.swarm_benchmark import _aggregate


def test_aggregate_computes_acceptance_gates() -> None:
    rows = [
        {
            "resume": {
                "skipped": False,
                "applied": 7,
                "failed": 2,
                "out_of_region_failures": 0,
                "score_delta": 8,
                "compile_regression": False,
            },
            "cover_letter": {
                "skipped": False,
                "applied": 4,
                "failed": 1,
                "out_of_region_failures": 0,
                "score_delta": 5,
                "compile_regression": False,
            },
        }
    ]
    metrics = _aggregate(rows)
    assert metrics["apply"]["success_rate"] > 0.70
    assert metrics["out_of_region"]["violations"] == 0
    assert metrics["compile"]["regressions"] == 0
    assert metrics["acceptance"]["apply_success_gt_70"] is True
    assert metrics["acceptance"]["zero_out_of_region"] is True
    assert metrics["acceptance"]["zero_compile_regression"] is True

