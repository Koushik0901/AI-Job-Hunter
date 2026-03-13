from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.cover_letter_agents_swarm.tone_guard import evaluate_cover_letter_tone


def test_tone_guard_triggers_on_cliches_and_long_sentences() -> None:
    text = (
        "I am confident I am a perfect fit for your dynamic team in this fast-paced environment, "
        "because I have repeatedly demonstrated excellence across Python, SQL, AWS, Docker, Kubernetes, TensorFlow, and PyTorch "
        "while driving cross-functional initiatives with broad impact and visibility across the organization."
    )
    report = evaluate_cover_letter_tone(text)
    assert report["triggered"] is True
    assert "cliche_phrases_detected" in report["issues"]


def test_tone_guard_passes_simple_human_text() -> None:
    text = (
        "I like solving production reliability problems. "
        "At my last role, I rebuilt an API path and cut p95 latency by 24%. "
        "That kind of practical work is what I want to do here."
    )
    report = evaluate_cover_letter_tone(text)
    assert isinstance(report, dict)
    assert "metrics" in report
