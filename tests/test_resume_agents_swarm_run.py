from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.resume_agents_swarm import run


def test_compile_guard_rollback_restores_initial_score(monkeypatch) -> None:
    class _FakeGraph:
        def invoke(self, _state):
            return {
                "latex_resume": "\\section{Experience}\n\\item broken rewrite\n",
                "final_score": {"Total_Score": 91},
                "history": [
                    {"stage": "score", "output": {"Total_Score": 64}},
                    {"stage": "final_score", "output": {"Total_Score": 91}},
                ],
            }

    monkeypatch.setattr(run, "load_llm_config", lambda: object())
    monkeypatch.setattr(run, "build_resume_agents_swarm_graph", lambda *_args, **_kwargs: _FakeGraph())

    compile_results = iter([{"ok": True}, {"ok": False}])
    monkeypatch.setattr(run, "compile_resume_tex", lambda **_kwargs: next(compile_results))

    result = run.run_resume_agents_swarm_optimization(
        job_description="Need Python API engineer",
        resume_text="",
        latex_resume="\\section{Experience}\n\\item original\n",
        cycles=2,
    )

    assert result["final_latex_resume"] == "\\section{Experience}\n\\item original\n"
    assert result["final_score"] == {"Total_Score": 64}
    assert any(
        entry.get("stage") == "compile_guard_rollback" and entry.get("restored_score") == {"Total_Score": 64}
        for entry in result["history"]
    )
