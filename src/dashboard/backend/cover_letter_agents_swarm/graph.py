from __future__ import annotations

import json
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from dashboard.backend.claim_validator import build_claim_policy
from dashboard.backend.cover_letter_agents_swarm.latex_apply import apply_rewrite_operations, parse_cover_letter_latex
from dashboard.backend.cover_letter_agents_swarm.latex_insert import extract_cover_letter_text_from_latex, inject_cover_letter_body
from dashboard.backend.cover_letter_agents_swarm.llm import (
    LLMConfig,
    build_chat_model,
    build_draft_messages,
    build_evidence_miner_messages,
    build_jd_decomposer_messages,
    build_narrative_planner_messages,
    build_planner_messages,
    build_repair_message,
    build_rewriter_messages,
    build_scorer_messages,
    invoke_model,
)
from dashboard.backend.cover_letter_agents_swarm.models import (
    ApplyReport,
    CoverLetterEditPlanModel,
    CoverLetterNarrativePlanModel,
    CoverLetterRewriteModel,
    DraftOutputModel,
    LegalMove,
    PlannedFixItem,
    SkippedFixItem,
)
from dashboard.backend.cover_letter_agents_swarm.parsing import (
    call_with_json_retries,
    parse_and_validate_draft,
    parse_and_validate_edit_plan,
    parse_and_validate_jd_target_spec,
    parse_and_validate_narrative_plan,
    parse_and_validate_ranked_evidence_pack,
    parse_and_validate_rewrite,
    parse_and_validate_score,
)
from dashboard.backend.cover_letter_agents_swarm.tone_guard import evaluate_cover_letter_tone
from dashboard.backend.swarm_runtime import ensure_not_cancelled, estimate_changed_lines


class CoverLetterGanState(TypedDict, total=False):
    job_description: str
    resume_text: str
    latex_cover_letter: str
    cover_letter_text: str
    evidence_context: dict[str, Any]
    brag_document_markdown: str
    project_cards: list[dict[str, Any]]
    do_not_claim: list[str]
    evidence_pack: dict[str, Any]
    jd_target_spec: dict[str, Any]
    ranked_evidence_pack: dict[str, Any]
    narrative_plan: dict[str, Any]
    draft_output: dict[str, Any]
    last_score: dict[str, Any]
    last_plan: dict[str, Any]
    last_rewrite: dict[str, Any]
    final_score: dict[str, Any]
    last_apply_report: dict[str, Any]
    last_tone_guard: dict[str, Any]
    cycles_done: int
    target_cycles: int
    initial_line_count: int
    min_score_delta: int
    max_ops_per_cycle: int
    max_changed_line_ratio: float
    force_cycle_on_non_negotiables: bool
    history: list[dict[str, Any]]


def _append_history(state: CoverLetterGanState, entry: dict[str, Any]) -> list[dict[str, Any]]:
    history = list(state.get("history", []))
    history.append(entry)
    return history


def _extract_fix_priorities(score_payload: dict[str, Any]) -> dict[str, int]:
    priorities: dict[str, int] = {}
    fix_plan = score_payload.get("Fix_Plan")
    if not isinstance(fix_plan, list):
        return priorities
    for item in fix_plan:
        if not isinstance(item, dict):
            continue
        fix_id = str(item.get("fix_id") or "").strip()
        if not fix_id:
            continue
        priority_raw = item.get("priority")
        priority = int(priority_raw) if isinstance(priority_raw, int) or str(priority_raw).isdigit() else 999
        priorities[fix_id] = max(1, priority)
    return priorities


def _sort_moves_with_priority(moves: list[LegalMove], fix_priorities: dict[str, int]) -> list[LegalMove]:
    return sorted(
        moves,
        key=lambda move: (
            int(fix_priorities.get(move.fix_id, 999)),
            move.fix_id,
            move.move_id,
        ),
    )


def _normalize_move_for_verify(move: LegalMove) -> tuple[str, dict[str, Any]]:
    return str(move.op), dict(move.payload or {})


def _move_targets(move: LegalMove, line_count: int, block_line_ids: dict[str, set[int]]) -> tuple[set[int], set[str]]:
    op, payload = _normalize_move_for_verify(move)
    line_targets: set[int] = set()
    if op in {"replace_range", "delete_range"}:
        start_line_id = payload.get("start_line_id")
        end_line_id = payload.get("end_line_id")
        if isinstance(start_line_id, int) and isinstance(end_line_id, int) and 0 <= start_line_id <= end_line_id < line_count:
            line_targets.update(range(start_line_id, end_line_id + 1))
    if op == "insert_after":
        line_id = payload.get("after_line_id")
        if isinstance(line_id, int) and 0 <= line_id < line_count:
            line_targets.add(line_id)
    return line_targets, set()


def _build_ranked_evidence_payload(raw_pack: dict[str, Any], ranked_pack: dict[str, Any]) -> dict[str, Any]:
    selected_chunks_raw = raw_pack.get("selected_chunks")
    chunks_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(selected_chunks_raw, list):
        for item in selected_chunks_raw:
            if not isinstance(item, dict):
                continue
            chunk_id = str(item.get("chunk_id") or "").strip()
            if chunk_id:
                chunks_by_id[chunk_id] = dict(item)
    selected_ids = ranked_pack.get("selected_chunk_ids")
    if not isinstance(selected_ids, list):
        selected_ids = []
    selected_ids = [cid for cid in selected_ids if cid in chunks_by_id]
    auto_backfill = False
    if not selected_ids and chunks_by_id:
        selected_ids = list(chunks_by_id.keys())[: min(4, len(chunks_by_id))]
        auto_backfill = True
    selected_chunks = [chunks_by_id[cid] for cid in selected_ids if cid in chunks_by_id]
    return {
        **ranked_pack,
        "selected_chunk_ids": selected_ids,
        "selected_chunks": selected_chunks,
        "algorithm": str(raw_pack.get("algorithm") or "hybrid_v1"),
        "sources": dict(raw_pack.get("sources") or {}) if isinstance(raw_pack.get("sources"), dict) else {},
        "thresholds": dict(raw_pack.get("thresholds") or {}) if isinstance(raw_pack.get("thresholds"), dict) else {},
        "auto_backfill": auto_backfill,
    }


def _build_editable_context(latex_cover_letter: str) -> dict[str, Any]:
    parsed_lines, parsed_blocks = parse_cover_letter_latex(latex_cover_letter)
    sections: dict[str, dict[str, Any]] = {}
    for entry in parsed_lines:
        section = sections.setdefault(
            entry.region_id,
            {
                "section_id": entry.region_id,
                "editable_line_ids": [],
                "line_ids": [],
            },
        )
        section["line_ids"].append(entry.line_id)
        if entry.editable:
            section["editable_line_ids"].append(entry.line_id)
    blocks = [
        {
            "block_id": block.block_id,
            "section_id": block.region_id,
            "line_ids": list(block.line_ids),
            "editable": block.editable,
        }
        for block in parsed_blocks.values()
    ]
    lines = [
        {
            "line_id": entry.line_id,
            "section_id": entry.region_id,
            "editable": entry.editable,
            "text": entry.text,
        }
        for entry in parsed_lines
    ]
    return {
        "sections": list(sections.values()),
        "blocks": blocks,
        "lines": lines,
        "allowed_ops": ["replace_range", "insert_after", "delete_range"],
    }


def _filter_plan_to_editable_targets(plan: CoverLetterEditPlanModel, editable_context: dict[str, Any]) -> dict[str, Any]:
    editable_lines: set[int] = set()
    sections: dict[str, dict[str, Any]] = {}
    blocks: dict[str, dict[str, Any]] = {}

    for section in editable_context.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_id") or "").strip()
        if section_id:
            sections[section_id] = section
            editable_lines.update(
                int(line_id)
                for line_id in (section.get("editable_line_ids") or [])
                if isinstance(line_id, int)
            )
    for block in editable_context.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        block_id = str(block.get("block_id") or "").strip()
        if block_id:
            blocks[block_id] = block

    selected: list[dict[str, Any]] = []
    deferred = list(plan.deferred_fix_ids)
    notes = list(plan.planner_notes)
    for fix in plan.selected_fixes:
        keep = True
        if fix.target_kind == "line_range":
            if fix.start_line_id is None or fix.end_line_id is None:
                keep = False
            else:
                line_ids = range(int(fix.start_line_id), int(fix.end_line_id) + 1)
                keep = all(line_id in editable_lines for line_id in line_ids)
        elif fix.target_kind == "section":
            section = sections.get(fix.section_id)
            keep = bool(section and section.get("editable_line_ids"))
        elif fix.target_kind == "block":
            block = blocks.get(fix.block_id)
            keep = bool(block and bool(block.get("editable")))
        if keep:
            selected.append(fix.model_dump())
            continue
        deferred.append(fix.fix_id)
        notes.append(f"{fix.fix_id} deferred: target is not editable in parsed LaTeX context.")

    return {
        "selected_fixes": selected,
        "deferred_fix_ids": deferred,
        "edit_budget_summary": plan.edit_budget_summary.model_dump(),
        "planner_notes": notes,
    }


def _line_range_contains(target: PlannedFixItem, start_line_id: int, end_line_id: int) -> bool:
    if target.target_kind != "line_range":
        return True
    if target.start_line_id is None or target.end_line_id is None:
        return False
    return target.start_line_id <= start_line_id <= end_line_id <= target.end_line_id


def _should_reuse_last_score(apply_report: dict[str, Any]) -> bool:
    before_hash = str(apply_report.get("doc_version_hash_before") or "").strip()
    after_hash = str(apply_report.get("doc_version_hash_after") or "").strip()
    if before_hash and after_hash and before_hash == after_hash:
        return True
    applied = apply_report.get("applied")
    applied_moves = apply_report.get("applied_moves")
    return len(applied or []) == 0 and len(applied_moves or []) == 0


def build_cover_letter_agents_swarm_graph(
    config: LLMConfig,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
):
    def _emit(event: dict[str, Any]) -> None:
        if on_event is None:
            return
        on_event(event)

    def _check_cancelled(stage: str) -> None:
        ensure_not_cancelled(should_cancel, stage=stage)

    analytical_model = build_chat_model(
        model=config.scoring_model,
        api_key=config.api_key,
        temperature=config.scoring_temperature,
        max_tokens=config.scoring_max_tokens,
    )
    draft_model = build_chat_model(
        model=config.draft_model,
        api_key=config.api_key,
        temperature=config.draft_temperature,
        max_tokens=config.draft_max_tokens,
    )
    generative_model = build_chat_model(
        model=config.rewrite_model,
        api_key=config.api_key,
        temperature=config.rewrite_temperature,
        max_tokens=config.rewrite_max_tokens,
    )

    def jd_decompose_node(state: CoverLetterGanState) -> CoverLetterGanState:
        messages = build_jd_decomposer_messages(job_description=state["job_description"])
        parsed, parse_errors = call_with_json_retries(
            invoke=lambda msgs: invoke_model(analytical_model, msgs),
            base_messages=messages,
            parser=parse_and_validate_jd_target_spec,
            build_repair_message=build_repair_message,
            max_retries=2,
            before_attempt=lambda: _check_cancelled("jd_decompose"),
        )
        payload = parsed.model_dump()
        _emit({"stage": "jd_decompose", "jd_target_spec": payload, "parse_errors": parse_errors})
        return {
            "jd_target_spec": payload,
            "history": _append_history(state, {"stage": "jd_decompose", "output": payload, "parse_errors": parse_errors}),
        }

    def evidence_mine_node(state: CoverLetterGanState) -> CoverLetterGanState:
        raw_pack = dict(state.get("evidence_pack") or {})
        messages = build_evidence_miner_messages(
            jd_target_spec_json=json.dumps(dict(state.get("jd_target_spec") or {}), ensure_ascii=False),
            evidence_pack_json=json.dumps(raw_pack, ensure_ascii=False),
            evidence_context_json=json.dumps(dict(state.get("evidence_context") or {}), ensure_ascii=False),
        )
        parsed, parse_errors = call_with_json_retries(
            invoke=lambda msgs: invoke_model(analytical_model, msgs),
            base_messages=messages,
            parser=parse_and_validate_ranked_evidence_pack,
            build_repair_message=build_repair_message,
            max_retries=2,
            before_attempt=lambda: _check_cancelled("evidence_mine"),
        )
        payload = _build_ranked_evidence_payload(raw_pack, parsed.model_dump())
        _emit({"stage": "evidence_mine", "evidence_pack": payload, "parse_errors": parse_errors})
        return {
            "ranked_evidence_pack": payload,
            "history": _append_history(state, {"stage": "evidence_mine", "output": payload, "parse_errors": parse_errors}),
        }

    def narrative_plan_node(state: CoverLetterGanState) -> CoverLetterGanState:
        messages = build_narrative_planner_messages(
            jd_target_spec_json=json.dumps(dict(state.get("jd_target_spec") or {}), ensure_ascii=False),
            ranked_evidence_pack_json=json.dumps(dict(state.get("ranked_evidence_pack") or {}), ensure_ascii=False),
        )
        parsed, parse_errors = call_with_json_retries(
            invoke=lambda msgs: invoke_model(analytical_model, msgs),
            base_messages=messages,
            parser=parse_and_validate_narrative_plan,
            build_repair_message=build_repair_message,
            max_retries=2,
            before_attempt=lambda: _check_cancelled("narrative_plan"),
        )
        payload = parsed.model_dump()
        _emit({"stage": "narrative_plan", "narrative_plan": payload, "parse_errors": parse_errors})
        return {
            "narrative_plan": payload,
            "history": _append_history(state, {"stage": "narrative_plan", "output": payload, "parse_errors": parse_errors}),
        }

    def draft_node(state: CoverLetterGanState) -> CoverLetterGanState:
        if str(state.get("cover_letter_text") or "").strip():
            return state
        messages = build_draft_messages(
            job_description=state["job_description"],
            resume_text=state.get("resume_text", ""),
            company_context="",
            narrative_plan_json=json.dumps(dict(state.get("narrative_plan") or {}), ensure_ascii=False),
            evidence_context=state.get("evidence_context"),
            brag_document_markdown=str(state.get("brag_document_markdown") or ""),
            project_cards=list(state.get("project_cards") or []),
            do_not_claim=list(state.get("do_not_claim") or []),
            evidence_pack=dict(state.get("ranked_evidence_pack") or state.get("evidence_pack") or {}),
        )
        parsed, parse_errors = call_with_json_retries(
            invoke=lambda msgs: invoke_model(draft_model, msgs),
            base_messages=messages,
            parser=parse_and_validate_draft,
            build_repair_message=build_repair_message,
            max_retries=2,
            before_attempt=lambda: _check_cancelled("draft"),
        )
        payload = parsed.model_dump()
        _emit({"stage": "draft", "draft": payload, "parse_errors": parse_errors})
        return {
            "draft_output": payload,
            "cover_letter_text": str(payload.get("cover_letter_text") or ""),
            "history": _append_history(state, {"stage": "draft", "output": payload, "parse_errors": parse_errors}),
        }

    def inject_draft_node(state: CoverLetterGanState) -> CoverLetterGanState:
        draft_payload = state.get("draft_output")
        if not isinstance(draft_payload, dict):
            return state
        draft = DraftOutputModel.model_validate(draft_payload)
        updated_latex = inject_cover_letter_body(state["latex_cover_letter"], draft.cover_letter_text)
        _emit({"stage": "inject", "message": "Inserted draft into template markers."})
        return {
            "latex_cover_letter": updated_latex,
            "cover_letter_text": draft.cover_letter_text,
            "history": _append_history(state, {"stage": "inject", "output": {"ok": True}}),
        }

    def score_node(state: CoverLetterGanState) -> CoverLetterGanState:
        score_index = sum(1 for item in state.get("history", []) if item.get("stage") == "score") + 1
        cover_letter_text = str(state.get("cover_letter_text") or "")
        if not cover_letter_text.strip():
            cover_letter_text = extract_cover_letter_text_from_latex(state["latex_cover_letter"])
        messages = build_scorer_messages(
            job_description=state["job_description"],
            cover_letter_text=cover_letter_text,
            evidence_context=state.get("evidence_context"),
            brag_document_markdown=str(state.get("brag_document_markdown") or ""),
            project_cards=list(state.get("project_cards") or []),
            do_not_claim=list(state.get("do_not_claim") or []),
            evidence_pack=dict(state.get("ranked_evidence_pack") or state.get("evidence_pack") or {}),
        )
        parsed, parse_errors = call_with_json_retries(
            invoke=lambda msgs: invoke_model(analytical_model, msgs),
            base_messages=messages,
            parser=parse_and_validate_score,
            build_repair_message=build_repair_message,
            max_retries=2,
            before_attempt=lambda: _check_cancelled("score"),
        )
        payload = parsed.model_dump()
        cycle = max(0, score_index - 1)
        _emit({"stage": "score", "index": score_index, "cycle": cycle, "score": payload, "parse_errors": parse_errors})
        return {
            "last_score": payload,
            "cover_letter_text": cover_letter_text,
            "history": _append_history(state, {"stage": "score", "index": score_index, "output": payload, "parse_errors": parse_errors}),
        }

    def plan_node(state: CoverLetterGanState) -> CoverLetterGanState:
        score_payload = state.get("last_score")
        if not isinstance(score_payload, dict):
            raise RuntimeError("plan_node requires last_score")
        editable_context = _build_editable_context(state["latex_cover_letter"])
        messages = build_planner_messages(
            jd_target_spec_json=json.dumps(dict(state.get("jd_target_spec") or {}), ensure_ascii=False),
            narrative_plan_json=json.dumps(dict(state.get("narrative_plan") or {}), ensure_ascii=False),
            ranked_evidence_pack_json=json.dumps(dict(state.get("ranked_evidence_pack") or {}), ensure_ascii=False),
            recruiter_feedback_json=json.dumps(score_payload, ensure_ascii=False),
            editable_context_json=json.dumps(editable_context, ensure_ascii=False),
        )
        parsed, parse_errors = call_with_json_retries(
            invoke=lambda msgs: invoke_model(analytical_model, msgs),
            base_messages=messages,
            parser=parse_and_validate_edit_plan,
            build_repair_message=build_repair_message,
            max_retries=2,
            before_attempt=lambda: _check_cancelled("plan"),
        )
        payload = _filter_plan_to_editable_targets(parsed, editable_context)
        _emit({"stage": "plan", "edit_plan": payload, "parse_errors": parse_errors})
        return {
            "last_plan": payload,
            "history": _append_history(state, {"stage": "plan", "output": payload, "parse_errors": parse_errors}),
        }

    def rewrite_node(state: CoverLetterGanState) -> CoverLetterGanState:
        rewrite_index = sum(1 for item in state.get("history", []) if item.get("stage") == "rewrite") + 1
        score_payload = state.get("last_score")
        plan_payload = state.get("last_plan")
        if not isinstance(score_payload, dict):
            raise RuntimeError("rewrite_node requires last_score")
        if not isinstance(plan_payload, dict):
            raise RuntimeError("rewrite_node requires last_plan")
        messages = build_rewriter_messages(
            job_description=state["job_description"],
            jd_target_spec_json=json.dumps(dict(state.get("jd_target_spec") or {}), ensure_ascii=False),
            narrative_plan_json=json.dumps(dict(state.get("narrative_plan") or {}), ensure_ascii=False),
            ranked_evidence_pack_json=json.dumps(dict(state.get("ranked_evidence_pack") or {}), ensure_ascii=False),
            edit_plan_json=json.dumps(plan_payload, ensure_ascii=False),
            recruiter_feedback_json=json.dumps(score_payload, ensure_ascii=False),
            current_latex_cover_letter=state["latex_cover_letter"],
            evidence_context=state.get("evidence_context"),
            brag_document_markdown=str(state.get("brag_document_markdown") or ""),
            project_cards=list(state.get("project_cards") or []),
            do_not_claim=list(state.get("do_not_claim") or []),
            evidence_pack=dict(state.get("ranked_evidence_pack") or state.get("evidence_pack") or {}),
        )
        parsed, parse_errors = call_with_json_retries(
            invoke=lambda msgs: invoke_model(generative_model, msgs),
            base_messages=messages,
            parser=parse_and_validate_rewrite,
            build_repair_message=build_repair_message,
            max_retries=2,
            before_attempt=lambda: _check_cancelled("rewrite"),
        )
        payload = parsed.model_dump()
        cycle = int(state.get("cycles_done", 0)) + 1
        _emit({"stage": "rewrite", "index": rewrite_index, "cycle": cycle, "rewrite": payload, "parse_errors": parse_errors})
        return {
            "last_rewrite": payload,
            "history": _append_history(state, {"stage": "rewrite", "index": rewrite_index, "output": payload, "parse_errors": parse_errors}),
        }

    def tone_guard_node(state: CoverLetterGanState) -> CoverLetterGanState:
        tone_guard = evaluate_cover_letter_tone(str(state.get("cover_letter_text") or ""))
        _emit({"stage": "tone_guard", "tone_guard": tone_guard})
        return {
            "last_tone_guard": tone_guard,
            "history": _append_history(state, {"stage": "tone_guard", "output": tone_guard}),
        }

    def verify_moves_node(state: CoverLetterGanState) -> CoverLetterGanState:
        rewrite_payload = state.get("last_rewrite")
        plan_payload = state.get("last_plan")
        if not isinstance(rewrite_payload, dict):
            raise RuntimeError("verify_moves_node requires last_rewrite")
        if not isinstance(plan_payload, dict):
            raise RuntimeError("verify_moves_node requires last_plan")
        rewrite_model_payload = CoverLetterRewriteModel.model_validate(rewrite_payload)
        plan_model = CoverLetterEditPlanModel.model_validate(plan_payload)
        moves = list(rewrite_model_payload.moves)
        warnings: list[str] = []
        skipped: list[dict[str, str]] = []
        plan_by_fix = {item.fix_id: item for item in plan_model.selected_fixes}
        fix_priorities = _extract_fix_priorities(dict(state.get("last_score") or {}))
        sorted_moves = _sort_moves_with_priority(moves, fix_priorities)
        line_count = len(state.get("latex_cover_letter", "").splitlines())
        parsed_lines, parsed_blocks = parse_cover_letter_latex(state.get("latex_cover_letter", ""))
        line_by_id = {entry.line_id: entry for entry in parsed_lines}
        block_line_ids = {block_id: set(block.line_ids) for block_id, block in parsed_blocks.items()}
        accepted: list[LegalMove] = []
        touched_lines: set[int] = set()
        touched_blocks: set[str] = set()
        for move in sorted_moves:
            target = plan_by_fix.get(move.fix_id)
            if not target:
                skipped.append({"fix_id": move.fix_id, "why": "skipped_not_in_plan"})
                continue
            op, payload = _normalize_move_for_verify(move)
            if op not in set(target.allowed_ops):
                skipped.append({"fix_id": move.fix_id, "why": "skipped_op_not_allowed"})
                continue
            if target.required_citations:
                supported = {str(item).strip() for item in (move.supported_by or []) if str(item).strip()}
                if not supported.intersection(set(target.required_citations)):
                    skipped.append({"fix_id": move.fix_id, "why": "skipped_missing_required_citation"})
                    continue
            if op == "replace_range":
                start_line_id = payload.get("start_line_id")
                end_line_id = payload.get("end_line_id")
                if not isinstance(start_line_id, int) or not isinstance(end_line_id, int) or start_line_id < 0 or end_line_id < start_line_id or end_line_id >= line_count:
                    skipped.append({"fix_id": move.fix_id, "why": "skipped_invalid_target"})
                    continue
                if not _line_range_contains(target, start_line_id, end_line_id):
                    skipped.append({"fix_id": move.fix_id, "why": "skipped_outside_planned_range"})
                    continue
                segment = [line_by_id.get(line_id) for line_id in range(start_line_id, end_line_id + 1)]
                if any((entry is None or not entry.editable) for entry in segment):
                    skipped.append({"fix_id": move.fix_id, "why": "skipped_invalid_target"})
                    continue
            elif op == "insert_after":
                after_line_id = payload.get("after_line_id")
                if not isinstance(after_line_id, int) or after_line_id < 0 or after_line_id >= line_count:
                    skipped.append({"fix_id": move.fix_id, "why": "skipped_invalid_target"})
                    continue
                if target.target_kind == "line_range" and not _line_range_contains(target, after_line_id, after_line_id):
                    skipped.append({"fix_id": move.fix_id, "why": "skipped_outside_planned_range"})
                    continue
                anchor = line_by_id.get(after_line_id)
                if not anchor or not anchor.editable:
                    skipped.append({"fix_id": move.fix_id, "why": "skipped_invalid_target"})
                    continue
            elif op == "delete_range":
                start_line_id = payload.get("start_line_id")
                end_line_id = payload.get("end_line_id")
                if not isinstance(start_line_id, int) or not isinstance(end_line_id, int) or start_line_id < 0 or end_line_id < start_line_id or end_line_id >= line_count:
                    skipped.append({"fix_id": move.fix_id, "why": "skipped_invalid_target"})
                    continue
                if not _line_range_contains(target, start_line_id, end_line_id):
                    skipped.append({"fix_id": move.fix_id, "why": "skipped_outside_planned_range"})
                    continue
                segment = [line_by_id.get(line_id) for line_id in range(start_line_id, end_line_id + 1)]
                if any((entry is None or not entry.editable) for entry in segment):
                    skipped.append({"fix_id": move.fix_id, "why": "skipped_invalid_target"})
                    continue
            move_lines, move_blocks = _move_targets(move, line_count, block_line_ids)
            if move_lines.intersection(touched_lines) or move_blocks.intersection(touched_blocks):
                skipped.append({"fix_id": move.fix_id, "why": "skipped_conflict"})
                continue
            accepted.append(move)
            touched_lines.update(move_lines)
            touched_blocks.update(move_blocks)
        insert_moves = [item for item in accepted if _normalize_move_for_verify(item)[0] == "insert_after"]
        if len(insert_moves) > 1:
            warnings.append("cover_letter_insert_cap_exceeded")
            kept_insert = 0
            filtered_moves: list[LegalMove] = []
            for item in accepted:
                if _normalize_move_for_verify(item)[0] != "insert_after":
                    filtered_moves.append(item)
                    continue
                if kept_insert == 0:
                    filtered_moves.append(item)
                    kept_insert += 1
            accepted = filtered_moves
        max_ops = min(
            max(1, int(state.get("max_ops_per_cycle", 12))),
            max(1, int(plan_model.edit_budget_summary.max_ops_this_cycle or state.get("max_ops_per_cycle", 12))),
        )
        if len(accepted) > max_ops:
            warnings.append("move_count_exceeds_policy_limit")
            accepted = accepted[:max_ops]
        rewrite_model_payload = rewrite_model_payload.model_copy(update={"moves": accepted})
        move_count = len(accepted)
        existing_skips = list(rewrite_model_payload.skipped_fix_ids or [])
        for item in skipped:
            existing_skips.append(SkippedFixItem(fix_id=item["fix_id"], why=item["why"]))
        rewrite_model_payload = rewrite_model_payload.model_copy(update={"skipped_fix_ids": existing_skips})
        _emit({"stage": "verify_moves", "move_count": move_count, "warnings": warnings, "skipped_conflicts": skipped})
        return {
            "last_rewrite": rewrite_model_payload.model_dump(),
            "history": _append_history(state, {"stage": "verify_moves", "move_count": move_count, "warnings": warnings, "skipped_conflicts": skipped}),
        }

    def apply_node(state: CoverLetterGanState) -> CoverLetterGanState:
        cycle_no = int(state.get("cycles_done", 0)) + 1
        rewrite_payload = state.get("last_rewrite")
        if not isinstance(rewrite_payload, dict):
            raise RuntimeError("apply_node requires last_rewrite")
        rewrite_model_payload = CoverLetterRewriteModel.model_validate(rewrite_payload)
        claim_policy = build_claim_policy(
            current_latex=state["latex_cover_letter"],
            evidence_context=dict(state.get("evidence_context") or {}),
            evidence_pack=dict(state.get("ranked_evidence_pack") or state.get("evidence_pack") or {}),
            brag_document_markdown=str(state.get("brag_document_markdown") or ""),
            project_cards=list(state.get("project_cards") or []),
            do_not_claim=list(state.get("do_not_claim") or []),
        )
        report: ApplyReport = apply_rewrite_operations(
            state["latex_cover_letter"],
            rewrite_model_payload,
            claim_policy=claim_policy,
        )
        report_payload = report.model_dump()
        try:
            next_text = extract_cover_letter_text_from_latex(report.updated_latex)
        except Exception:
            next_text = str(state.get("cover_letter_text") or "")
        _emit({"stage": "apply", "cycle": cycle_no, "apply": report_payload})
        return {
            "latex_cover_letter": report.updated_latex,
            "cover_letter_text": next_text,
            "cycles_done": cycle_no,
            "last_apply_report": report_payload,
            "history": _append_history(state, {"stage": "apply", "cycle": cycle_no, "output": report_payload}),
        }

    def decide_next(state: CoverLetterGanState) -> CoverLetterGanState:
        cycles_done = int(state.get("cycles_done", 0))
        target_cycles = int(state.get("target_cycles", 2))
        min_score_delta = max(0, int(state.get("min_score_delta", 3)))
        force_non_negotiable = bool(state.get("force_cycle_on_non_negotiables", True))
        max_changed_ratio = max(0.0, float(state.get("max_changed_line_ratio", 0.2)))
        initial_line_count = max(1, int(state.get("initial_line_count", 1)))
        history = list(state.get("history", []))
        score_values: list[int] = []
        for item in history:
            if item.get("stage") != "score":
                continue
            output = item.get("output")
            if isinstance(output, dict) and isinstance(output.get("Total_Score"), int):
                score_values.append(int(output["Total_Score"]))
        score_delta = score_values[-1] - score_values[-2] if len(score_values) >= 2 else None
        last_score = dict(state.get("last_score") or {})
        current_total_score = int(last_score.get("Total_Score") or 0) if isinstance(last_score.get("Total_Score"), int) else 0
        remaining_non_negotiables = len(last_score.get("Non_Negotiables") or []) if isinstance(last_score.get("Non_Negotiables"), list) else 0
        remaining_expected_gain = 0
        fix_plan = last_score.get("Fix_Plan")
        if isinstance(fix_plan, list):
            for item in fix_plan:
                if isinstance(item, dict):
                    gain = item.get("expected_score_gain")
                    if isinstance(gain, int):
                        remaining_expected_gain += gain
        apply_report = dict(state.get("last_apply_report") or {})
        changed_lines = estimate_changed_lines(apply_report)
        changed_ratio = changed_lines / float(initial_line_count)
        tone_guard = evaluate_cover_letter_tone(str(state.get("cover_letter_text") or ""))
        tone_triggered = bool(tone_guard.get("triggered"))
        no_change_stop = _should_reuse_last_score(apply_report)
        low_delta_stop = score_delta is not None and score_delta < min_score_delta and remaining_expected_gain <= 10
        budget_stop = changed_ratio > max_changed_ratio
        high_score_stop = current_total_score >= 88 and remaining_expected_gain <= 10
        tone_force_continue = tone_triggered and current_total_score < 80 and remaining_expected_gain > 0 and cycles_done < target_cycles
        force_continue = (force_non_negotiable and remaining_non_negotiables > 0 and cycles_done < target_cycles) or tone_force_continue
        _emit(
            {
                "stage": "decide_next",
                "cycles_done": cycles_done,
                "target_cycles": target_cycles,
                "score_delta": score_delta,
                "current_total_score": current_total_score,
                "remaining_non_negotiables": remaining_non_negotiables,
                "remaining_expected_gain": remaining_expected_gain,
                "changed_ratio": changed_ratio,
                "no_change_stop": no_change_stop,
                "tone_guard": tone_guard,
                "low_delta_stop": low_delta_stop,
                "budget_stop": budget_stop,
                "high_score_stop": high_score_stop,
                "tone_force_continue": tone_force_continue,
                "force_continue": force_continue,
            }
        )
        return {
            "last_tone_guard": tone_guard,
            "history": _append_history(
                state,
                {
                    "stage": "decide_next",
                    "cycles_done": cycles_done,
                    "target_cycles": target_cycles,
                    "score_delta": score_delta,
                    "current_total_score": current_total_score,
                    "remaining_non_negotiables": remaining_non_negotiables,
                    "remaining_expected_gain": remaining_expected_gain,
                    "changed_ratio": changed_ratio,
                    "no_change_stop": no_change_stop,
                    "tone_guard": tone_guard,
                    "low_delta_stop": low_delta_stop,
                    "budget_stop": budget_stop,
                    "high_score_stop": high_score_stop,
                    "tone_force_continue": tone_force_continue,
                    "force_continue": force_continue,
                },
            ),
        }

    def final_score_node(state: CoverLetterGanState) -> CoverLetterGanState:
        apply_report = dict(state.get("last_apply_report") or {})
        last_score = dict(state.get("last_score") or {})
        if last_score and _should_reuse_last_score(apply_report):
            _emit({"stage": "final_score", "score": last_score, "parse_errors": [], "reused_last_score": True})
            return {
                "final_score": last_score,
                "history": _append_history(
                    state,
                    {"stage": "final_score", "output": last_score, "parse_errors": [], "reused_last_score": True},
                ),
            }
        cover_letter_text = str(state.get("cover_letter_text") or "")
        if not cover_letter_text.strip():
            cover_letter_text = extract_cover_letter_text_from_latex(state["latex_cover_letter"])
        messages = build_scorer_messages(
            job_description=state["job_description"],
            cover_letter_text=cover_letter_text,
            evidence_context=state.get("evidence_context"),
            brag_document_markdown=str(state.get("brag_document_markdown") or ""),
            project_cards=list(state.get("project_cards") or []),
            do_not_claim=list(state.get("do_not_claim") or []),
            evidence_pack=dict(state.get("ranked_evidence_pack") or state.get("evidence_pack") or {}),
        )
        parsed, parse_errors = call_with_json_retries(
            invoke=lambda msgs: invoke_model(analytical_model, msgs),
            base_messages=messages,
            parser=parse_and_validate_score,
            build_repair_message=build_repair_message,
            max_retries=2,
            before_attempt=lambda: _check_cancelled("final_score"),
        )
        payload = parsed.model_dump()
        _emit({"stage": "final_score", "score": payload, "parse_errors": parse_errors})
        return {
            "final_score": payload,
            "history": _append_history(state, {"stage": "final_score", "output": payload, "parse_errors": parse_errors}),
        }

    def route_after_decide(state: CoverLetterGanState) -> str:
        cycles_done = int(state.get("cycles_done", 0))
        target_cycles = int(state.get("target_cycles", 2))
        history = list(state.get("history", []))
        last_decide = next((entry for entry in reversed(history) if entry.get("stage") == "decide_next"), {})
        if not isinstance(last_decide, dict):
            last_decide = {}
        no_change_stop = bool(last_decide.get("no_change_stop"))
        low_delta_stop = bool(last_decide.get("low_delta_stop"))
        budget_stop = bool(last_decide.get("budget_stop"))
        high_score_stop = bool(last_decide.get("high_score_stop"))
        force_continue = bool(last_decide.get("force_continue"))
        if cycles_done >= target_cycles:
            return "final"
        if no_change_stop:
            return "final"
        if high_score_stop:
            return "final"
        if force_continue:
            return "loop"
        if low_delta_stop or budget_stop:
            return "final"
        return "loop"

    def _wrap_node(stage: str, node: Callable[[CoverLetterGanState], CoverLetterGanState]) -> Callable[[CoverLetterGanState], CoverLetterGanState]:
        def _wrapped(state: CoverLetterGanState) -> CoverLetterGanState:
            _check_cancelled(stage)
            result = node(state)
            _check_cancelled(stage)
            return result

        return _wrapped

    graph = StateGraph(CoverLetterGanState)
    graph.add_node("jd_decompose_node", _wrap_node("jd_decompose", jd_decompose_node))
    graph.add_node("evidence_mine_node", _wrap_node("evidence_mine", evidence_mine_node))
    graph.add_node("narrative_plan_node", _wrap_node("narrative_plan", narrative_plan_node))
    graph.add_node("draft_node", _wrap_node("draft", draft_node))
    graph.add_node("inject_draft_node", _wrap_node("inject_draft", inject_draft_node))
    graph.add_node("score_node", _wrap_node("score", score_node))
    graph.add_node("plan_node", _wrap_node("plan", plan_node))
    graph.add_node("rewrite_node", _wrap_node("rewrite", rewrite_node))
    graph.add_node("tone_guard_node", _wrap_node("tone_guard", tone_guard_node))
    graph.add_node("verify_moves_node", _wrap_node("verify_moves", verify_moves_node))
    graph.add_node("apply_node", _wrap_node("apply", apply_node))
    graph.add_node("decide_next", _wrap_node("decide_next", decide_next))
    graph.add_node("final_score_node", _wrap_node("final_score", final_score_node))

    graph.add_edge(START, "jd_decompose_node")
    graph.add_edge("jd_decompose_node", "evidence_mine_node")
    graph.add_edge("evidence_mine_node", "narrative_plan_node")
    graph.add_edge("narrative_plan_node", "draft_node")
    graph.add_edge("draft_node", "inject_draft_node")
    graph.add_edge("inject_draft_node", "score_node")
    graph.add_edge("score_node", "plan_node")
    graph.add_edge("plan_node", "rewrite_node")
    graph.add_edge("rewrite_node", "tone_guard_node")
    graph.add_edge("tone_guard_node", "verify_moves_node")
    graph.add_edge("verify_moves_node", "apply_node")
    graph.add_edge("apply_node", "decide_next")
    graph.add_conditional_edges("decide_next", route_after_decide, {"loop": "score_node", "final": "final_score_node"})
    graph.add_edge("final_score_node", END)
    return graph.compile()
