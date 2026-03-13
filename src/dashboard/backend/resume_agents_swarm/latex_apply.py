from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from dashboard.backend.claim_validator import validate_claim_text
from dashboard.backend.resume_agents_swarm.models import (
    ApplyApplied,
    ApplyFailure,
    ApplyNoOp,
    ApplyReport,
    LegalMove,
    ResumeRewriteModel,
)

_ENV_PATTERN = re.compile(r"\\(begin|end)\{([^}]+)\}")
_UNESCAPED_UNDERSCORE_PATTERN = re.compile(r"(?<!\\)_")
_UNESCAPED_SPECIAL_PATTERN = re.compile(r"(?<!\\)[#$&%]")


@dataclass(frozen=True)
class ParsedLine:
    line_id: int
    text: str
    region_id: str
    block_id: str | None
    line_kind: str
    editable: bool


@dataclass(frozen=True)
class ParsedBlock:
    block_id: str
    region_id: str
    line_ids: list[int]
    block_kind: str
    editable: bool


def _line_warnings(old_line: str, new_line: str) -> list[str]:
    warnings: list[str] = []
    if new_line.count("{") != new_line.count("}"):
        warnings.append("brace-count changed on replacement line")
    old_env = _ENV_PATTERN.findall(old_line)
    new_env = _ENV_PATTERN.findall(new_line)
    if old_env != new_env:
        warnings.append("environment token changed on replacement line")
    return warnings


def _has_balanced_braces(line: str) -> bool:
    return line.count("{") == line.count("}")


def _has_unescaped_underscore(line: str) -> bool:
    # Allow URLs/hrefs where underscores are expected.
    if r"\url{" in line or r"\href{" in line:
        return False
    return bool(_UNESCAPED_UNDERSCORE_PATTERN.search(line))


def _has_unescaped_special(line: str) -> bool:
    if line.strip().startswith("%"):
        return False
    if r"\url{" in line or r"\href{" in line:
        return False
    return bool(_UNESCAPED_SPECIAL_PATTERN.search(line))


def _escape_unescaped_latex_chars(line: str) -> str:
    if line.strip().startswith("%"):
        return line
    if r"\url{" in line or r"\href{" in line:
        return line
    value = re.sub(r"\\(begin|end)\{", r"\1{", line)
    value = re.sub(r"(?<!\\)_", r"\\_", value)
    value = re.sub(r"(?<!\\)([#$&%])", r"\\\1", value)
    return value


def _env_counter(lines: list[str]) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for line in lines:
        for kind, name in _ENV_PATTERN.findall(line):
            key = (kind, name)
            counts[key] = counts.get(key, 0) + 1
    return counts


def _document_has_balanced_braces(lines: list[str]) -> bool:
    balance = 0
    for line in lines:
        balance += line.count("{")
        balance -= line.count("}")
        if balance < 0:
            return False
    return balance == 0


def _line_kind(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return "blank"
    if stripped.startswith("%"):
        return "comment"
    if stripped.startswith(r"\item"):
        return "bullet"
    if stripped.startswith("\\"):
        return "command"
    return "paragraph"


def parse_resume_latex(source: str) -> tuple[list[ParsedLine], dict[str, ParsedBlock]]:
    lines = source.splitlines()
    parsed: list[ParsedLine] = []
    blocks: dict[str, ParsedBlock] = {}
    region_id = "GLOBAL"
    in_itemize = False
    current_itemize_line_ids: list[int] = []
    itemize_count = 0

    protected_commands = (
        r"\documentclass",
        r"\usepackage",
        r"\begin{document}",
        r"\end{document}",
        r"\name",
        r"\moderncvstyle",
        r"\moderncvcolor",
        r"\nopagenumbers",
    )

    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        section_match = re.match(r"\\section\*?\{([^}]*)\}", stripped)
        if section_match:
            title = section_match.group(1).strip().upper().replace(" ", "_")
            region_id = f"SECTION:{title or 'UNTITLED'}"

        if stripped == r"\begin{itemize}":
            in_itemize = True
            current_itemize_line_ids = [idx]
            itemize_count += 1
        elif in_itemize:
            current_itemize_line_ids.append(idx)
            if stripped == r"\end{itemize}":
                block_id = f"{region_id}:ITEMIZE:{itemize_count}"
                blocks[block_id] = ParsedBlock(
                    block_id=block_id,
                    region_id=region_id,
                    line_ids=list(current_itemize_line_ids),
                    block_kind="bullet_list",
                    editable=True,
                )
                in_itemize = False
                current_itemize_line_ids = []

        kind = _line_kind(raw)
        editable = True
        if kind == "comment":
            editable = False
        if any(stripped.startswith(cmd) for cmd in protected_commands):
            editable = False
        if stripped in {r"\begin{itemize}", r"\end{itemize}"}:
            editable = False
        block_id = None
        if in_itemize and blocks:
            # Only needed for in-progress visibility; finalized mapping handled by blocks.
            block_id = f"{region_id}:ITEMIZE:{itemize_count}"
        parsed.append(
            ParsedLine(
                line_id=idx,
                text=raw,
                region_id=region_id,
                block_id=block_id,
                line_kind=kind,
                editable=editable,
            )
        )
    return parsed, blocks


def _env_tokens(lines: list[str]) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for line in lines:
        tokens.extend(_ENV_PATTERN.findall(line))
    return tokens


def _resolve_line_index(lines: list[str], payload: dict[str, Any]) -> tuple[int | None, str | None]:
    old_latex = payload.get("old_latex")
    if isinstance(old_latex, str) and old_latex in lines:
        return lines.index(old_latex), "exact"
    if isinstance(old_latex, str):
        normalized = " ".join(old_latex.split())
        candidates = [idx for idx, line in enumerate(lines) if " ".join(line.split()) == normalized]
        if len(candidates) == 1:
            return candidates[0], "normalized"
    hint = payload.get("line_id")
    if isinstance(hint, int) and 0 <= hint < len(lines):
        if isinstance(old_latex, str):
            normalized = " ".join(old_latex.split())
            if " ".join(lines[hint].split()) == normalized and lines[hint] != old_latex:
                return hint, "normalized"
        return hint, "hint"
    return None, None


def apply_rewrite_operations(latex: str, rewrite: ResumeRewriteModel, *, claim_policy: dict[str, Any] | None = None) -> ApplyReport:
    hash_before = hashlib.sha256(latex.encode("utf-8")).hexdigest()
    lines = latex.splitlines()
    base_env_counts = _env_counter(lines)
    applied: list[ApplyApplied] = []
    failed: list[ApplyFailure] = []
    no_op: list[ApplyNoOp] = []
    applied_moves: list[dict[str, Any]] = []
    failed_moves: list[dict[str, Any]] = []
    warnings: list[str] = []

    moves = list(rewrite.moves)

    for raw_move in moves:
        move = raw_move
        parsed_lines, blocks = parse_resume_latex("\n".join(lines))
        line_map = {entry.line_id: entry for entry in parsed_lines}
        payload = dict(move.payload or {})
        if move.op == "replace_range":
            start_line_id = payload.get("start_line_id")
            end_line_id = payload.get("end_line_id")
            if (
                not isinstance(start_line_id, int)
                or not isinstance(end_line_id, int)
                or start_line_id < 0
                or end_line_id < start_line_id
                or end_line_id >= len(lines)
            ):
                resolved_line_id, match_mode = _resolve_line_index(lines, payload)
                if resolved_line_id is None:
                    failed.append(
                        ApplyFailure(
                            fix_id=move.fix_id,
                            reason="replace_range target invalid",
                            old_latex=str(payload.get("old_latex") or ""),
                        )
                    )
                    failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "target_not_found", "policy_reason": "target_not_found"})
                    continue
                start_line_id = resolved_line_id
                end_line_id = resolved_line_id
            else:
                match_mode = None
            region_entries = [line_map.get(idx) for idx in range(start_line_id, end_line_id + 1)]
            if not all(entry and entry.editable for entry in region_entries):
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="range contains non-editable lines", old_latex="\n".join(lines[start_line_id : end_line_id + 1])))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "line_not_editable", "policy_reason": "line_not_editable"})
                continue
            new_lines_raw = payload.get("new_lines")
            if not isinstance(new_lines_raw, list) or not all(isinstance(item, str) for item in new_lines_raw):
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="replace_range requires new_lines[]", old_latex="\n".join(lines[start_line_id : end_line_id + 1])))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "invalid_new_lines", "policy_reason": "invalid_new_lines"})
                continue
            new_lines = [_escape_unescaped_latex_chars(str(item)) for item in new_lines_raw]
            old_segment = lines[start_line_id : end_line_id + 1]
            if new_lines == old_segment:
                no_op.append(ApplyNoOp(fix_id=move.fix_id, reason="new_text equals current line"))
                continue
            for new_text in new_lines:
                if not _has_balanced_braces(new_text):
                    failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:unbalanced_braces", old_latex="\n".join(old_segment)))
                    failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "unbalanced_braces"})
                    break
                if _has_unescaped_underscore(new_text):
                    failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:unescaped_underscore", old_latex="\n".join(old_segment)))
                    failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "unescaped_underscore"})
                    break
                if _has_unescaped_special(new_text):
                    failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:unescaped_special", old_latex="\n".join(old_segment)))
                    failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "unescaped_special"})
                    break
            if failed_moves and failed_moves[-1]["move_id"] == move.move_id:
                continue
            if _env_tokens(old_segment) != _env_tokens(new_lines):
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:command_parity_violation", old_latex="\n".join(old_segment)))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "command_parity_violation"})
                continue
            supported_by = [str(item) for item in (move.supported_by or []) if str(item).strip()]
            old_text = "\n".join(old_segment)
            blocked = False
            for new_text in new_lines:
                allowed, reason = validate_claim_text(new_text, claim_policy, old_text=old_text, supported_by=supported_by)
                if not allowed:
                    failed.append(ApplyFailure(fix_id=move.fix_id, reason=f"claim_policy_blocked:{reason}", old_latex=old_text))
                    failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "claim_policy_blocked", "policy_reason": reason or "claim_policy_blocked"})
                    blocked = True
                    break
            if blocked:
                continue
            line_warn: list[str] = []
            if match_mode == "normalized":
                line_warn.append("normalized line match")
            else:
                old_latex = payload.get("old_latex")
                if isinstance(old_latex, str) and len(old_segment) == 1:
                    normalized_old = " ".join(old_latex.split())
                    normalized_current = " ".join(old_segment[0].split())
                    if normalized_old == normalized_current and old_latex != old_segment[0]:
                        line_warn.append("normalized line match")
            candidate_lines = list(lines)
            candidate_lines[start_line_id : end_line_id + 1] = new_lines
            if not _document_has_balanced_braces(candidate_lines):
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:document_unbalanced_braces", old_latex="\n".join(old_segment)))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "document_unbalanced_braces"})
                continue
            if _env_counter(candidate_lines) != base_env_counts:
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:environment_structure_changed", old_latex="\n".join(old_segment)))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "environment_structure_changed"})
                continue
            lines = candidate_lines
            applied.append(
                ApplyApplied(
                    fix_id=move.fix_id,
                    line_index=start_line_id,
                    old_latex="\n".join(old_segment),
                    new_latex="\n".join(new_lines),
                    warnings=line_warn,
                )
            )
            applied_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "op": move.op, "start_line_id": start_line_id, "end_line_id": end_line_id})
            if line_warn:
                warnings.extend(line_warn)
            continue

        if move.op == "insert_after":
            line_id = payload.get("line_id")
            if line_id is None:
                line_id = payload.get("after_line_id")
            new_lines_raw = payload.get("new_lines")
            if not isinstance(line_id, int) or line_id < 0 or line_id >= len(lines):
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="invalid line_id", old_latex=""))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "invalid_line_id", "policy_reason": "invalid_line_id"})
                continue
            if not isinstance(new_lines_raw, list) or not all(isinstance(item, str) for item in new_lines_raw):
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="insert_after requires new_lines[]", old_latex=""))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "invalid_new_lines", "policy_reason": "invalid_new_lines"})
                continue
            new_lines = [_escape_unescaped_latex_chars(str(item)) for item in new_lines_raw]
            entry = line_map.get(line_id)
            if not entry or not entry.editable:
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="anchor line is not editable", old_latex=lines[line_id]))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "anchor_not_editable", "policy_reason": "anchor_not_editable"})
                continue
            supported_by = [str(item) for item in (move.supported_by or []) if str(item).strip()]
            blocked = False
            for new_text in new_lines:
                allowed, reason = validate_claim_text(new_text, claim_policy, old_text="", supported_by=supported_by)
                if not allowed:
                    failed.append(ApplyFailure(fix_id=move.fix_id, reason=f"claim_policy_blocked:{reason}", old_latex=""))
                    failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "claim_policy_blocked", "policy_reason": reason or "claim_policy_blocked"})
                    blocked = True
                    break
                if not _has_balanced_braces(new_text):
                    failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:unbalanced_braces", old_latex=""))
                    failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "unbalanced_braces"})
                    blocked = True
                    break
                if _has_unescaped_underscore(new_text):
                    failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:unescaped_underscore", old_latex=""))
                    failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "unescaped_underscore"})
                    blocked = True
                    break
                if _has_unescaped_special(new_text):
                    failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:unescaped_special", old_latex=""))
                    failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "unescaped_special"})
                    blocked = True
                    break
            if blocked:
                continue
            candidate_lines = list(lines)
            candidate_lines[line_id + 1 : line_id + 1] = new_lines
            if not _document_has_balanced_braces(candidate_lines):
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:document_unbalanced_braces", old_latex=""))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "document_unbalanced_braces"})
                continue
            if _env_counter(candidate_lines) != base_env_counts:
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:environment_structure_changed", old_latex=""))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "environment_structure_changed"})
                continue
            lines = candidate_lines
            applied_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "op": move.op, "line_id": line_id, "inserted": len(new_lines)})
            continue

        if move.op == "delete_range":
            start_line_id = payload.get("start_line_id")
            end_line_id = payload.get("end_line_id")
            if (
                not isinstance(start_line_id, int)
                or not isinstance(end_line_id, int)
                or start_line_id < 0
                or end_line_id < start_line_id
                or end_line_id >= len(lines)
            ):
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="invalid range", old_latex=""))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "invalid_range", "policy_reason": "invalid_range"})
                continue
            entries = [line_map.get(idx) for idx in range(start_line_id, end_line_id + 1)]
            if not all(entry and entry.editable and entry.line_kind in {"bullet", "blank", "paragraph"} for entry in entries):
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="delete_range only allowed for editable non-structural lines", old_latex="\n".join(lines[start_line_id : end_line_id + 1])))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "delete_policy_blocked", "policy_reason": "delete_policy_blocked"})
                continue
            candidate_lines = list(lines)
            removed = candidate_lines[start_line_id : end_line_id + 1]
            del candidate_lines[start_line_id : end_line_id + 1]
            if not _document_has_balanced_braces(candidate_lines):
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:document_unbalanced_braces", old_latex="\n".join(removed)))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "document_unbalanced_braces"})
                continue
            if _env_counter(candidate_lines) != base_env_counts:
                failed.append(ApplyFailure(fix_id=move.fix_id, reason="latex_safety_blocked:environment_structure_changed", old_latex="\n".join(removed)))
                failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "latex_safety_blocked", "policy_reason": "environment_structure_changed"})
                continue
            lines = candidate_lines
            applied_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "op": move.op, "start_line_id": start_line_id, "end_line_id": end_line_id, "removed": len(removed)})
            continue

        failed.append(ApplyFailure(fix_id=move.fix_id, reason=f"unsupported op {move.op}", old_latex=""))
        failed_moves.append({"move_id": move.move_id, "fix_id": move.fix_id, "reason": "unsupported_op", "policy_reason": "unsupported_op"})

    updated = "\n".join(lines)
    if latex.endswith("\n"):
        updated = f"{updated}\n"
    hash_after = hashlib.sha256(updated.encode("utf-8")).hexdigest()

    return ApplyReport(
        applied=applied,
        failed=failed,
        no_op=no_op,
        applied_moves=applied_moves,
        failed_moves=failed_moves,
        warnings=warnings,
        doc_version_hash_before=hash_before,
        doc_version_hash_after=hash_after,
        updated_latex=updated,
    )
