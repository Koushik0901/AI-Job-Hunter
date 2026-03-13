from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend import main


class _DummyConn:
    def close(self) -> None:
        return None


def test_load_swarm_run_from_store_restores_events(monkeypatch) -> None:
    run_payload = {
        "run_id": "r1",
        "artifact_id": "a1",
        "pipeline": "resume",
        "status": "running",
    }
    event_payload = [{"seq": 1, "stage": "queued", "message": "Run queued."}]

    monkeypatch.setattr(main, "_conn", lambda: _DummyConn())
    monkeypatch.setattr(main, "get_artifact_ai_run", lambda _conn, _run_id: dict(run_payload))
    monkeypatch.setattr(main, "list_artifact_ai_run_events", lambda _conn, _run_id: list(event_payload))

    recovered = main._load_swarm_run_from_store("r1")
    assert recovered is not None
    assert recovered.get("run_id") == "r1"
    assert recovered.get("events") == event_payload
    assert recovered.get("cancel_requested") is False
