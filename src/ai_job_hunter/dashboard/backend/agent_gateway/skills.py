from __future__ import annotations

import re
from typing import Any

_BUILTIN_SKILLS = {
    "discover": {"output_kind": "discovery", "requires_selected_job": False},
    "resume": {"output_kind": "resume", "requires_selected_job": True},
    "cover-letter": {"output_kind": "cover_letter", "requires_selected_job": True},
    "cover_letter": {"output_kind": "cover_letter", "requires_selected_job": True},
    "critique": {"output_kind": "critique", "requires_selected_job": False},
    # /apply is dispatched client-side; registered here so the gateway
    # recognises the invocation and can route it to the tool_agent if needed.
    "apply": {"output_kind": "apply", "requires_selected_job": True},
}

_SLASH_RE = re.compile(r"^/(?P<name>[a-zA-Z][\w-]*)(?:\s+(?P<arguments>.*))?$")


def normalize_skill_name(value: str | None) -> str | None:
    cleaned = str(value or "").strip().casefold()
    if not cleaned:
        return None
    if cleaned == "cover-letter":
        return "cover_letter"
    return cleaned if cleaned in _BUILTIN_SKILLS else None


def parse_slash_command(text: str | None) -> dict[str, Any] | None:
    match = _SLASH_RE.match(str(text or "").strip())
    if not match:
        return None
    normalized = normalize_skill_name(match.group("name"))
    if normalized is None:
        return None
    return {
        "name": normalized,
        "arguments": (match.group("arguments") or "").strip(),
    }


def resolve_skill_invocation(
    messages: list[dict[str, str]],
    skill_invocation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if skill_invocation:
        normalized = normalize_skill_name(skill_invocation.get("name"))
        if normalized is None:
            return None
        return {
            "name": normalized,
            "arguments": str(skill_invocation.get("arguments") or "").strip(),
            "selected_job_id": str(skill_invocation.get("selected_job_id") or "").strip() or None,
            "active_artifact_id": int(skill_invocation["active_artifact_id"])
            if skill_invocation.get("active_artifact_id") is not None
            else None,
            "active_output_kind": str(skill_invocation.get("active_output_kind") or "").strip() or None,
        }

    latest_user = ""
    for message in reversed(messages):
        if str(message.get("role") or "") == "user":
            latest_user = str(message.get("content") or "").strip()
            break
    parsed = parse_slash_command(latest_user)
    if parsed is None:
        return None
    return {
        "name": parsed["name"],
        "arguments": parsed["arguments"],
        "selected_job_id": None,
        "active_artifact_id": None,
        "active_output_kind": None,
    }
