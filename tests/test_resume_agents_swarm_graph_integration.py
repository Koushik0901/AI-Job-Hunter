from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.resume_agents_swarm.graph import _build_ranked_evidence_payload, build_resume_agents_swarm_graph
from dashboard.backend.resume_agents_swarm.llm import LLMConfig
from dashboard.backend.resume_agents_swarm.models import RankedEvidencePackModel


def _score_payload(total: int, non_negotiables: list[str] | None = None) -> dict:
    return {
        "Total_Score": total,
        "Breakdown": {
            "First_Pass_Clarity": 10,
            "Impact_Specificity": 18,
            "JD_Alignment": 22,
            "Hard_Skills_Keywords": 14,
            "Action_Language": 7,
        },
        "Pass_7s_Summary": {
            "Target_Role_Clear": True,
            "Core_Stack_Clear": True,
            "Top_Impact_Clear": False,
            "What_Recruiter_Notices_First": ["ML engineer profile"],
            "What_Should_Be_Obvious_But_Isnt": ["Quantified business impact"],
        },
        "Job_Requirement_Map": {
            "Must_Have_Skills": ["Python"],
            "Nice_To_Have_Skills": [],
            "Top_Responsibilities": ["Deploy models"],
            "Role_Signals": ["Senior"],
            "Repeated_Keywords": ["production"],
        },
        "Evidence": {"Must_Haves_Coverage": [], "Responsibilities_Coverage": []},
        "Critical_Feedback": ["Add measurable outcomes."],
        "Fluff_Detected": [],
        "Stuffed_Keywords": [],
        "Weak_Evidence_Keywords": [],
        "Missing_Keywords": [],
        "Contradictions_Or_Risks": [],
        "High_Leverage_Sections_To_Edit": [{"section_hint": "Experience", "why": "No metric", "goal": "Add metric"}],
        "Fix_Plan": [
            {
                "fix_id": "FP1",
                "priority": 1,
                "expected_score_gain": 6,
                "category": "Impact_Specificity",
                "location_hint": "Experience bullet 1",
                "problem": "No measurable outcome",
                "required_evidence": "Add observed impact",
                "rewrite_goal": "Add metric and ownership",
            }
        ],
        "Non_Negotiables": non_negotiables or [],
    }


def _jd_payload() -> dict:
    return {
        "role_title_hint": "ML Engineer",
        "must_have_skills": ["Python"],
        "nice_to_have_skills": [],
        "top_outcomes": ["Deploy models"],
        "role_signals": ["Senior"],
        "company_signals": ["Production systems"],
        "risk_signals": [],
    }


def _evidence_payload() -> dict:
    return {
        "selected_chunk_ids": ["ctx:0"],
        "top_story_candidates": [
            {
                "story_id": "story-1",
                "label": "API reliability work",
                "why_relevant": "Supports production ownership",
                "supporting_citations": ["ctx:0"],
            }
        ],
        "keyword_support_map": [
            {
                "keyword": "python",
                "supporting_citations": ["ctx:0"],
                "support_level": "strong",
            }
        ],
        "risk_notes": [],
    }


def _plan_payload() -> dict:
    return {
        "selected_fixes": [
            {
                "fix_id": "FP1",
                "priority": 1,
                "expected_gain": 6,
                "location_hint": "Experience bullet 1",
                "target_kind": "line_range",
                "section_id": "SECTION:EXPERIENCE",
                "block_id": "",
                "start_line_id": 1,
                "end_line_id": 1,
                "allowed_ops": ["replace_range"],
                "required_citations": ["ctx:0"],
                "rationale": "Highest gain bullet",
            }
        ],
        "deferred_fix_ids": [],
        "edit_budget_summary": {
            "max_fixes_this_cycle": 2,
            "max_ops_this_cycle": 4,
            "max_changed_lines": 4,
        },
        "planner_notes": [],
    }


def _rewrite_payload(new_line: str, *, supported_by: list[str] | None = None) -> dict:
    return {
        "applied_fix_ids": ["FP1"],
        "skipped_fix_ids": [],
        "moves": [
            {
                "move_id": "m1",
                "fix_id": "FP1",
                "op": "replace_range",
                "reason": "Improve impact",
                "targets": ["Impact_Specificity"],
                "supported_by": supported_by or ["ctx:0"],
                "payload": {
                    "old_latex": "\\item Built API",
                    "start_line_id": 1,
                    "end_line_id": 1,
                    "new_lines": [new_line],
                },
            }
        ],
    }


def test_resume_graph_end_to_end_with_mock_llm(monkeypatch) -> None:
    outputs = [
        json.dumps(_jd_payload()),
        json.dumps(_evidence_payload()),
        json.dumps(_score_payload(60, ["Quantify top bullet"])),
        json.dumps(_plan_payload()),
        json.dumps(_rewrite_payload("\\item Built API and improved reliability by 20\\%")),
        json.dumps(_score_payload(72, [])),
        json.dumps(_plan_payload()),
        json.dumps(_rewrite_payload("\\item Built API and improved reliability by 24\\%")),
        json.dumps(_score_payload(78, [])),
    ]

    def _fake_build_chat_model(**_kwargs):
        return object()

    def _fake_invoke_model(_model, _messages):
        if not outputs:
            raise AssertionError("No more mocked outputs available")
        return outputs.pop(0)

    monkeypatch.setattr("dashboard.backend.resume_agents_swarm.graph.build_chat_model", _fake_build_chat_model)
    monkeypatch.setattr("dashboard.backend.resume_agents_swarm.graph.invoke_model", _fake_invoke_model)

    events: list[dict] = []
    graph = build_resume_agents_swarm_graph(
        LLMConfig(
            api_key="test",
            scoring_model="mock",
            rewrite_model="mock",
            scoring_temperature=0.0,
            rewrite_temperature=0.0,
            scoring_max_tokens=None,
            rewrite_max_tokens=None,
        ),
        on_event=events.append,
    )
    latex = "\\section{Experience}\n\\item Built API\n"
    final_state = graph.invoke(
        {
            "job_description": "Need Python API engineer",
            "resume_text": "",
            "latex_resume": latex,
            "evidence_context": {"skills": ["python", "api"]},
            "brag_document_markdown": "",
            "project_cards": [],
            "do_not_claim": [],
            "evidence_pack": {"selected_chunks": [{"chunk_id": "ctx:0", "text": "Python API reliability work"}]},
            "cycles_done": 0,
            "target_cycles": 2,
            "initial_line_count": 2,
            "min_score_delta": 3,
            "max_ops_per_cycle": 12,
            "max_changed_line_ratio": 0.9,
            "force_cycle_on_non_negotiables": True,
            "history": [],
        }
    )
    assert "24\\%" in str(final_state.get("latex_resume", ""))
    assert int((final_state.get("final_score") or {}).get("Total_Score", 0)) == 78
    assert any(event.get("stage") == "decide_next" for event in events)


def test_resume_ranked_evidence_payload_auto_backfills_when_llm_returns_empty() -> None:
    raw_pack = {
        "algorithm": "hybrid_v1",
        "selected_chunks": [
            {"chunk_id": "ctx:0", "text": "Built Python APIs"},
            {"chunk_id": "ctx:1", "text": "Shipped ML evaluation tooling"},
        ],
    }
    ranked = RankedEvidencePackModel(
        selected_chunk_ids=[],
        top_story_candidates=[],
        keyword_support_map=[],
        risk_notes=["LLM failed to choose chunks"],
    )
    payload = _build_ranked_evidence_payload(raw_pack, ranked)
    assert payload["auto_backfill"] is True
    assert payload["selected_chunk_ids"] == ["ctx:0", "ctx:1"]
    assert len(payload["selected_chunks"]) == 2


def test_resume_graph_policy_violation_path(monkeypatch) -> None:
    outputs = [
        json.dumps(_jd_payload()),
        json.dumps(_evidence_payload()),
        json.dumps(_score_payload(60, [])),
        json.dumps(_plan_payload()),
        json.dumps(_rewrite_payload("\\item Built API and operated Spark clusters", supported_by=[])),
        json.dumps(_score_payload(61, [])),
    ]

    def _fake_build_chat_model(**_kwargs):
        return object()

    def _fake_invoke_model(_model, _messages):
        if not outputs:
            raise AssertionError("No more mocked outputs available")
        return outputs.pop(0)

    monkeypatch.setattr("dashboard.backend.resume_agents_swarm.graph.build_chat_model", _fake_build_chat_model)
    monkeypatch.setattr("dashboard.backend.resume_agents_swarm.graph.invoke_model", _fake_invoke_model)

    graph = build_resume_agents_swarm_graph(
        LLMConfig(
            api_key="test",
            scoring_model="mock",
            rewrite_model="mock",
            scoring_temperature=0.0,
            rewrite_temperature=0.0,
            scoring_max_tokens=None,
            rewrite_max_tokens=None,
        ),
        on_event=None,
    )
    latex = "\\section{Experience}\n\\item Built API\n"
    final_state = graph.invoke(
        {
            "job_description": "Need Python API engineer",
            "resume_text": "",
            "latex_resume": latex,
            "evidence_context": {"skills": ["python", "api", "kubernetes"]},
            "brag_document_markdown": "",
            "project_cards": [],
            "do_not_claim": [],
            "evidence_pack": {"selected_chunks": [{"chunk_id": "ctx:0", "text": "Python API reliability work"}]},
            "cycles_done": 0,
            "target_cycles": 2,
            "initial_line_count": 2,
            "min_score_delta": 3,
            "max_ops_per_cycle": 12,
            "max_changed_line_ratio": 0.9,
            "force_cycle_on_non_negotiables": True,
            "history": [],
        }
    )
    apply_entries = [entry for entry in list(final_state.get("history") or []) if entry.get("stage") == "apply"]
    assert apply_entries
    failed_moves = ((apply_entries[-1].get("output") or {}).get("failed_moves") or [])
    assert failed_moves
    assert any(
        str(item.get("reason")) == "claim_policy_blocked"
        and any(
            flag in str(item.get("policy_reason"))
            for flag in (
                "missing_supported_by",
                "citation_not_supporting_keyword",
                "unsupported_keyword",
                "low_precedence_keyword",
            )
        )
        for item in failed_moves
        if isinstance(item, dict)
    )


def test_resume_graph_reuses_last_score_on_noop_final(monkeypatch) -> None:
    outputs = [
        json.dumps(_jd_payload()),
        json.dumps(_evidence_payload()),
        json.dumps(_score_payload(64, [])),
        json.dumps({"selected_fixes": [], "deferred_fix_ids": ["FP1"], "edit_budget_summary": {"max_fixes_this_cycle": 0, "max_ops_this_cycle": 0, "max_changed_lines": 0}, "planner_notes": ["No grounded fix"]}),
        json.dumps({"applied_fix_ids": [], "skipped_fix_ids": [{"fix_id": "FP1", "why": "No grounded evidence"}], "moves": []}),
    ]

    def _fake_build_chat_model(**_kwargs):
        return object()

    def _fake_invoke_model(_model, _messages):
        if not outputs:
            raise AssertionError("No more mocked outputs available")
        return outputs.pop(0)

    monkeypatch.setattr("dashboard.backend.resume_agents_swarm.graph.build_chat_model", _fake_build_chat_model)
    monkeypatch.setattr("dashboard.backend.resume_agents_swarm.graph.invoke_model", _fake_invoke_model)

    graph = build_resume_agents_swarm_graph(
        LLMConfig(
            api_key="test",
            scoring_model="mock",
            rewrite_model="mock",
            scoring_temperature=0.0,
            rewrite_temperature=0.0,
            scoring_max_tokens=None,
            rewrite_max_tokens=None,
        ),
        on_event=None,
    )
    final_state = graph.invoke(
        {
            "job_description": "Need Python API engineer",
            "resume_text": "",
            "latex_resume": "\\section{Experience}\n\\item Built API\n",
            "evidence_context": {"skills": ["python", "api"]},
            "brag_document_markdown": "",
            "project_cards": [],
            "do_not_claim": [],
            "evidence_pack": {"selected_chunks": [{"chunk_id": "ctx:0", "text": "Python API reliability work"}]},
            "cycles_done": 0,
            "target_cycles": 2,
            "initial_line_count": 2,
            "min_score_delta": 3,
            "max_ops_per_cycle": 12,
            "max_changed_line_ratio": 0.9,
            "force_cycle_on_non_negotiables": True,
            "history": [],
        }
    )
    assert int((final_state.get("final_score") or {}).get("Total_Score", 0)) == 64
    final_entries = [entry for entry in list(final_state.get("history") or []) if entry.get("stage") == "final_score"]
    assert final_entries
    assert bool(final_entries[-1].get("reused_last_score")) is True


def test_resume_graph_low_delta_with_high_remaining_gain_keeps_looping(monkeypatch) -> None:
    score_two = _score_payload(61, [])
    score_two["Fix_Plan"].append(
        {
            "fix_id": "FP2",
            "priority": 2,
            "expected_score_gain": 6,
            "category": "JD_Alignment",
            "location_hint": "Summary",
            "problem": "Missing deployment signal",
            "required_evidence": "Add deployment evidence",
            "rewrite_goal": "Show production deployment work",
        }
    )
    outputs = [
        json.dumps(_jd_payload()),
        json.dumps(_evidence_payload()),
        json.dumps(_score_payload(60, [])),
        json.dumps(_plan_payload()),
        json.dumps(_rewrite_payload("\\item Built API and improved reliability by 20\\%")),
        json.dumps(score_two),
        json.dumps(_plan_payload()),
        json.dumps(_rewrite_payload("\\item Built API and improved reliability by 28\\%")),
        json.dumps(_score_payload(72, [])),
        json.dumps(_plan_payload()),
        json.dumps(_rewrite_payload("\\item Built API and improved reliability by 34\\%")),
        json.dumps(_score_payload(78, [])),
    ]

    def _fake_build_chat_model(**_kwargs):
        return object()

    def _fake_invoke_model(_model, _messages):
        if not outputs:
            raise AssertionError("No more mocked outputs available")
        return outputs.pop(0)

    monkeypatch.setattr("dashboard.backend.resume_agents_swarm.graph.build_chat_model", _fake_build_chat_model)
    monkeypatch.setattr("dashboard.backend.resume_agents_swarm.graph.invoke_model", _fake_invoke_model)

    graph = build_resume_agents_swarm_graph(
        LLMConfig(
            api_key="test",
            scoring_model="mock",
            rewrite_model="mock",
            scoring_temperature=0.0,
            rewrite_temperature=0.0,
            scoring_max_tokens=None,
            rewrite_max_tokens=None,
        ),
        on_event=None,
    )
    final_state = graph.invoke(
        {
            "job_description": "Need Python API engineer",
            "resume_text": "",
            "latex_resume": "\\section{Experience}\n\\item Built API\n",
            "evidence_context": {"skills": ["python", "api"]},
            "brag_document_markdown": "",
            "project_cards": [],
            "do_not_claim": [],
            "evidence_pack": {"selected_chunks": [{"chunk_id": "ctx:0", "text": "Python API reliability work"}]},
            "cycles_done": 0,
            "target_cycles": 3,
            "initial_line_count": 2,
            "min_score_delta": 3,
            "max_ops_per_cycle": 12,
            "max_changed_line_ratio": 0.95,
            "force_cycle_on_non_negotiables": True,
            "history": [],
        }
    )
    rewrite_entries = [entry for entry in list(final_state.get("history") or []) if entry.get("stage") == "rewrite"]
    assert len(rewrite_entries) == 3
    assert int((final_state.get("final_score") or {}).get("Total_Score", 0)) == 78


def test_resume_graph_changed_line_budget_does_not_double_count_replace_range(monkeypatch) -> None:
    plan_payload = _plan_payload()
    plan_payload["selected_fixes"][0]["start_line_id"] = 3
    plan_payload["selected_fixes"][0]["end_line_id"] = 3
    rewrite_one = _rewrite_payload("\\item Built API and improved reliability by 20\\%")
    rewrite_one["moves"][0]["payload"]["start_line_id"] = 3
    rewrite_one["moves"][0]["payload"]["end_line_id"] = 3
    rewrite_two = _rewrite_payload("\\item Built API and improved reliability by 24\\%")
    rewrite_two["moves"][0]["payload"]["start_line_id"] = 3
    rewrite_two["moves"][0]["payload"]["end_line_id"] = 3
    outputs = [
        json.dumps(_jd_payload()),
        json.dumps(_evidence_payload()),
        json.dumps(_score_payload(60, [])),
        json.dumps(plan_payload),
        json.dumps(rewrite_one),
        json.dumps(_score_payload(67, [])),
        json.dumps(plan_payload),
        json.dumps(rewrite_two),
        json.dumps(_score_payload(74, [])),
    ]

    def _fake_build_chat_model(**_kwargs):
        return object()

    def _fake_invoke_model(_model, _messages):
        if not outputs:
            raise AssertionError("No more mocked outputs available")
        return outputs.pop(0)

    monkeypatch.setattr("dashboard.backend.resume_agents_swarm.graph.build_chat_model", _fake_build_chat_model)
    monkeypatch.setattr("dashboard.backend.resume_agents_swarm.graph.invoke_model", _fake_invoke_model)

    graph = build_resume_agents_swarm_graph(
        LLMConfig(
            api_key="test",
            scoring_model="mock",
            rewrite_model="mock",
            scoring_temperature=0.0,
            rewrite_temperature=0.0,
            scoring_max_tokens=None,
            rewrite_max_tokens=None,
        ),
        on_event=None,
    )
    latex = "\\documentclass{article}\n\\begin{document}\n\\section{Experience}\n\\item Built API\n\\end{document}\n"
    final_state = graph.invoke(
        {
            "job_description": "Need Python API engineer",
            "resume_text": "",
            "latex_resume": latex,
            "evidence_context": {"skills": ["python", "api"]},
            "brag_document_markdown": "",
            "project_cards": [],
            "do_not_claim": [],
            "evidence_pack": {"selected_chunks": [{"chunk_id": "ctx:0", "text": "Python API reliability work"}]},
            "cycles_done": 0,
            "target_cycles": 2,
            "initial_line_count": 5,
            "min_score_delta": 3,
            "max_ops_per_cycle": 12,
            "max_changed_line_ratio": 0.3,
            "force_cycle_on_non_negotiables": True,
            "history": [],
        }
    )
    rewrite_entries = [entry for entry in list(final_state.get("history") or []) if entry.get("stage") == "rewrite"]
    assert len(rewrite_entries) == 2
