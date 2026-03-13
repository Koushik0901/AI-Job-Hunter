from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dashboard.backend.cover_letter_agents_swarm.graph import _build_ranked_evidence_payload, build_cover_letter_agents_swarm_graph
from dashboard.backend.cover_letter_agents_swarm.llm import LLMConfig


def _jd_payload() -> dict:
    return {
        "role_title_hint": "ML Engineer",
        "top_outcomes": ["Ship production AI systems"],
        "fit_signals": ["Ownership", "Communication"],
        "company_signals": ["Evaluation minded"],
        "tone_signals": ["Direct"],
        "risk_signals": [],
    }


def _evidence_payload() -> dict:
    return {
        "selected_chunk_ids": ["ctx:0"],
        "story_candidates": [
            {
                "story_id": "story-1",
                "label": "Reliability project",
                "why_relevant": "Matches production systems work",
                "supporting_citations": ["ctx:0"],
            }
        ],
        "why_company_evidence": ["Evaluation minded"],
        "risk_notes": [],
    }


def _narrative_payload() -> dict:
    return {
        "opening_angle": "Production AI work with tight feedback loops",
        "proof_story_1": {
            "label": "Reliability work",
            "goal": "Show shipping quality",
            "supporting_citations": ["ctx:0"],
        },
        "proof_story_2": {
            "label": "Cross-functional work",
            "goal": "Show collaboration",
            "supporting_citations": ["ctx:0"],
        },
        "why_company_angle": "The role values evaluation and iteration",
        "closing_intent": "Discuss how to help the team ship",
        "tone_guardrails": ["No buzzwords"],
    }


def _draft_payload() -> dict:
    return {
        "cover_letter_text": "I like production AI work.\n\nI improved reliability on shipped systems.\n\nI'd value a chance to discuss the role.",
        "notes_for_reviewer": [],
    }


def _score_payload(total: int) -> dict:
    return {
        "Total_Score": total,
        "Breakdown": {
            "Personalization_Intent": 18,
            "Narrative_Fit": 18,
            "Evidence_Credibility": 16,
            "Tone_Clarity_Human": 15,
            "Structure_Skimmability": 8,
        },
        "Cover_Letter_Success_Map": {
            "Top_Role_Outcomes": ["Ship production AI systems"],
            "Fit_Signals_To_Demonstrate": ["Ownership"],
            "Company_Signals_From_JD": ["Evaluation minded"],
            "Potential_Risks_To_Address": [],
        },
        "Evidence": {
            "Why_Company_Evidence": [],
            "Why_Role_Evidence": [],
            "Proof_Examples_Evidence": [],
            "Tone_Voice_Evidence": [],
        },
        "Critical_Feedback": ["Be more specific."],
        "Fluff_Detected": [],
        "Generic_Template_Signals": [],
        "Resume_Rehash_Sections": [],
        "Missing_Elements": [],
        "High_Leverage_Sections_To_Edit": [{"section_hint": "Body", "why": "Needs specificity", "goal": "Add concrete example"}],
        "Fix_Plan": [
            {
                "fix_id": "FP1",
                "priority": 1,
                "expected_score_gain": 5,
                "category": "Narrative_Fit",
                "location_hint": "Body paragraph",
                "problem": "Too generic",
                "required_evidence": "Mention shipped reliability work",
                "rewrite_goal": "Make proof specific",
            }
        ],
        "Non_Negotiables": [],
    }


def _plan_payload() -> dict:
    return {
        "selected_fixes": [
            {
                "fix_id": "FP1",
                "priority": 1,
                "expected_gain": 5,
                "location_hint": "Body paragraph",
                "target_kind": "line_range",
                "section_id": "CL_BODY",
                "block_id": "",
                "start_line_id": 2,
                "end_line_id": 2,
                "allowed_ops": ["replace_range"],
                "required_citations": ["ctx:0"],
                "rationale": "Highest leverage line",
            }
        ],
        "deferred_fix_ids": [],
        "edit_budget_summary": {
            "max_fixes_this_cycle": 2,
            "max_ops_this_cycle": 3,
            "max_changed_lines": 3,
        },
        "planner_notes": [],
    }


def _rewrite_payload() -> dict:
    return {
        "applied_fix_ids": ["FP1"],
        "skipped_fix_ids": [],
        "moves": [
            {
                "move_id": "m1",
                "fix_id": "FP1",
                "op": "replace_range",
                "reason": "Add concrete proof",
                "targets": ["Narrative_Fit"],
                "supported_by": ["ctx:0"],
                "payload": {
                    "start_line_id": 2,
                    "end_line_id": 2,
                    "new_lines": ["I improved reliability on production AI systems and tightened feedback loops."],
                },
            }
        ],
    }


def test_cover_letter_graph_end_to_end_with_mock_llm(monkeypatch) -> None:
    outputs = [
        json.dumps(_jd_payload()),
        json.dumps(_evidence_payload()),
        json.dumps(_narrative_payload()),
        json.dumps(_draft_payload()),
        json.dumps(_score_payload(66)),
        json.dumps(_plan_payload()),
        json.dumps(_rewrite_payload()),
        json.dumps(_score_payload(74)),
    ]

    def _fake_build_chat_model(**_kwargs):
        return object()

    def _fake_invoke_model(_model, _messages):
        if not outputs:
            raise AssertionError("No more mocked outputs available")
        return outputs.pop(0)

    monkeypatch.setattr("dashboard.backend.cover_letter_agents_swarm.graph.build_chat_model", _fake_build_chat_model)
    monkeypatch.setattr("dashboard.backend.cover_letter_agents_swarm.graph.invoke_model", _fake_invoke_model)

    events: list[dict] = []
    graph = build_cover_letter_agents_swarm_graph(
        LLMConfig(
            api_key="test",
            draft_model="mock",
            scoring_model="mock",
            rewrite_model="mock",
            draft_temperature=0.0,
            scoring_temperature=0.0,
            rewrite_temperature=0.0,
            draft_max_tokens=None,
            scoring_max_tokens=None,
            rewrite_max_tokens=None,
        ),
        on_event=events.append,
    )
    latex = "%<CL_START>\nOpening line\nBody line\nClosing line\n%<CL_END>\n"
    final_state = graph.invoke(
        {
            "job_description": "Need production AI engineer",
            "resume_text": "Built production AI systems",
            "latex_cover_letter": latex,
            "cover_letter_text": "",
            "evidence_context": {"skills": ["python", "reliability"]},
            "brag_document_markdown": "",
            "project_cards": [],
            "do_not_claim": [],
            "evidence_pack": {"selected_chunks": [{"chunk_id": "ctx:0", "text": "Production AI reliability work"}]},
            "cycles_done": 0,
            "target_cycles": 1,
            "initial_line_count": 5,
            "min_score_delta": 3,
            "max_ops_per_cycle": 8,
            "max_changed_line_ratio": 0.9,
            "force_cycle_on_non_negotiables": True,
            "history": [],
        }
    )
    assert "tightened feedback loops" in str(final_state.get("latex_cover_letter", ""))
    assert int((final_state.get("final_score") or {}).get("Total_Score", 0)) == 74
    assert any(event.get("stage") == "narrative_plan" for event in events)


def test_cover_letter_graph_reuses_last_score_on_noop_final(monkeypatch) -> None:
    outputs = [
        json.dumps(_jd_payload()),
        json.dumps(_evidence_payload()),
        json.dumps(_narrative_payload()),
        json.dumps(_draft_payload()),
        json.dumps(_score_payload(68)),
        json.dumps({"selected_fixes": [], "deferred_fix_ids": ["FP1"], "edit_budget_summary": {"max_fixes_this_cycle": 0, "max_ops_this_cycle": 0, "max_changed_lines": 0}, "planner_notes": ["No grounded fix"]}),
        json.dumps({"applied_fix_ids": [], "skipped_fix_ids": [{"fix_id": "FP1", "why": "No grounded evidence"}], "moves": []}),
    ]

    def _fake_build_chat_model(**_kwargs):
        return object()

    def _fake_invoke_model(_model, _messages):
        if not outputs:
            raise AssertionError("No more mocked outputs available")
        return outputs.pop(0)

    monkeypatch.setattr("dashboard.backend.cover_letter_agents_swarm.graph.build_chat_model", _fake_build_chat_model)
    monkeypatch.setattr("dashboard.backend.cover_letter_agents_swarm.graph.invoke_model", _fake_invoke_model)

    graph = build_cover_letter_agents_swarm_graph(
        LLMConfig(
            api_key="test",
            draft_model="mock",
            scoring_model="mock",
            rewrite_model="mock",
            draft_temperature=0.0,
            scoring_temperature=0.0,
            rewrite_temperature=0.0,
            draft_max_tokens=None,
            scoring_max_tokens=None,
            rewrite_max_tokens=None,
        ),
        on_event=None,
    )
    final_state = graph.invoke(
        {
            "job_description": "Need production AI engineer",
            "resume_text": "Built production AI systems",
            "latex_cover_letter": "%<CL_START>\nOpening line\nBody line\nClosing line\n%<CL_END>\n",
            "cover_letter_text": "",
            "evidence_context": {"skills": ["python", "reliability"]},
            "brag_document_markdown": "",
            "project_cards": [],
            "do_not_claim": [],
            "evidence_pack": {"selected_chunks": [{"chunk_id": "ctx:0", "text": "Production AI reliability work"}]},
            "cycles_done": 0,
            "target_cycles": 2,
            "initial_line_count": 5,
            "min_score_delta": 3,
            "max_ops_per_cycle": 8,
            "max_changed_line_ratio": 0.9,
            "force_cycle_on_non_negotiables": True,
            "history": [],
        }
    )
    assert int((final_state.get("final_score") or {}).get("Total_Score", 0)) == 68
    final_entries = [entry for entry in list(final_state.get("history") or []) if entry.get("stage") == "final_score"]
    assert final_entries
    assert bool(final_entries[-1].get("reused_last_score")) is True


def test_cover_letter_ranked_evidence_payload_auto_backfills_when_llm_returns_empty() -> None:
    raw_pack = {
        "algorithm": "hybrid_v1",
        "selected_chunks": [
            {"chunk_id": "ctx:0", "text": "Production AI reliability work"},
            {"chunk_id": "ctx:1", "text": "Cross-functional delivery with PMs"},
        ],
    }
    payload = _build_ranked_evidence_payload(
        raw_pack,
        {
            "selected_chunk_ids": [],
            "story_candidates": [],
            "why_company_evidence": [],
            "risk_notes": ["LLM failed to choose chunks"],
        },
    )
    assert payload["auto_backfill"] is True
    assert payload["selected_chunk_ids"] == ["ctx:0", "ctx:1"]
    assert len(payload["selected_chunks"]) == 2
