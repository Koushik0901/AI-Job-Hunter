from __future__ import annotations

import re
from typing import Any, Callable


class SwarmRunCancelled(RuntimeError):
    pass


def ensure_not_cancelled(should_cancel: Callable[[], bool] | None, *, stage: str = "") -> None:
    if should_cancel is None:
        return
    if should_cancel():
        suffix = f" during {stage}" if stage else ""
        raise SwarmRunCancelled(f"Swarm run cancelled{suffix}")


def latex_to_text(source: str) -> str:
    text = source.replace("\r\n", "\n")
    text = re.sub(r"(?m)^\s*%.*$", "", text)
    text = re.sub(r"\\begin\{[^}]+\}", " ", text)
    text = re.sub(r"\\end\{[^}]+\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{([^{}]*)\})?", r" \1 ", text)
    text = text.replace("{", " ").replace("}", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def score_from_history(history: list[dict[str, Any]], *, stage: str = "score", prefer: str = "first") -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for item in history:
        if not isinstance(item, dict) or item.get("stage") != stage:
            continue
        output = item.get("output")
        if isinstance(output, dict):
            matches.append(output)
    if not matches:
        return {}
    return dict(matches[-1] if prefer == "last" else matches[0])


def estimate_changed_lines(apply_report: dict[str, Any]) -> int:
    applied_moves = apply_report.get("applied_moves")
    if isinstance(applied_moves, list) and applied_moves:
        changed_lines = 0
        for move in applied_moves:
            if not isinstance(move, dict):
                continue
            op = str(move.get("op") or "")
            if op in {"replace_range", "delete_range"}:
                start = move.get("start_line_id")
                end = move.get("end_line_id")
                if isinstance(start, int) and isinstance(end, int) and end >= start:
                    changed_lines += (end - start + 1)
                else:
                    changed_lines += 1
            elif op == "insert_after":
                inserted = move.get("inserted")
                if isinstance(inserted, int) and inserted > 0:
                    changed_lines += inserted
                else:
                    new_lines = move.get("new_lines")
                    if isinstance(new_lines, list) and new_lines:
                        changed_lines += len(new_lines)
                    else:
                        changed_lines += 1
            else:
                changed_lines += 1
        return changed_lines

    applied = apply_report.get("applied")
    if isinstance(applied, list):
        return len(applied)
    return 0
