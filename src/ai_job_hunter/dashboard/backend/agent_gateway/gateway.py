from __future__ import annotations

import re
from typing import Any

from .core_access import CoreActionClient, CoreReadClient
from .legacy_chat import build_agent_context, handle_freeform_chat
from .skills import resolve_skill_invocation


def _compact_job_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "job_id": str(item.get("id") or ""),
        "url": str(item.get("url") or ""),
        "company": str(item.get("company") or ""),
        "title": str(item.get("title") or ""),
        "location": str(item.get("location") or ""),
        "posted": str(item.get("posted") or ""),
        "ats": str(item.get("ats") or ""),
        "status": str(item.get("status") or ""),
        "priority": str(item.get("priority") or ""),
        "pinned": bool(item.get("pinned") or False),
        "match_score": item.get("match_score"),
        "raw_score": item.get("raw_score"),
        "fit_score": item.get("fit_score"),
        "guidance_summary": item.get("guidance_summary"),
        "health_label": item.get("health_label"),
    }


def _build_no_output(reply: str, *, context_snapshot: str, response_mode: str = "skill") -> dict[str, Any]:
    return {
        "reply": reply,
        "context_snapshot": context_snapshot,
        "response_mode": response_mode,
        "output_kind": "none",
        "output_payload": None,
        "operation_id": None,
    }


def _detect_resume_strengths(text: str) -> list[str]:
    strengths: list[str] = []
    if re.search(r"(^|\n)##\s+", text):
        strengths.append("The document already uses clear section headings.")
    if re.search(r"\b\d+[%xkK+]?\b", text):
        strengths.append("There are quantified signals in the document.")
    if re.search(r"(^|\n)-\s", text):
        strengths.append("The writing already uses bullet structure for scanability.")
    return strengths[:3]


def _detect_resume_improvements(text: str, instructions: str) -> list[str]:
    improvements: list[str] = []
    if len(text.split()) < 220:
        improvements.append("The document looks short. Add more evidence for impact, ownership, and scope.")
    if not re.search(r"\b\d+[%xkK+]?\b", text):
        improvements.append("Add quantified outcomes wherever they are truthful.")
    if not re.search(r"\b(machine learning|ml|ai|data science|experimentation|model)\b", text.casefold()):
        improvements.append("Bring the most relevant technical keywords closer to the top of the document.")
    if instructions:
        improvements.append(f"Apply the requested focus explicitly: {instructions}.")
    return improvements[:4]


def _build_critique_payload(
    artifact: dict[str, Any],
    *,
    instructions: str,
) -> dict[str, Any]:
    content = str(artifact.get("content_md") or "")
    strengths = _detect_resume_strengths(content)
    improvements = _detect_resume_improvements(content, instructions)
    summary = (
        "Strong structural base, but the draft still needs sharper evidence and tighter positioning."
        if improvements
        else "The draft is structurally sound and does not show major weaknesses."
    )
    return {
        "artifact_id": int(artifact.get("id") or 0),
        "artifact_type": str(artifact.get("artifact_type") or ""),
        "job_id": str(artifact.get("job_id") or ""),
        "summary": summary,
        "strengths": strengths,
        "improvements": improvements,
        "instructions": instructions,
    }


def _handle_discover(
    reads: CoreReadClient,
    *,
    arguments: str,
    context_snapshot: str,
) -> dict[str, Any]:
    items = reads.search_jobs(arguments, limit=8)
    if not items:
        return _build_no_output(
            "I did not find matching not-applied roles in the current database. Refresh sources or broaden the search.",
            context_snapshot=context_snapshot,
        )
    jobs = [_compact_job_payload(item) for item in items]
    query_text = arguments or "top matches"
    reply = f"I found {len(jobs)} candidate role(s) for `{query_text}` in the current database."
    return {
        "reply": reply,
        "context_snapshot": context_snapshot,
        "response_mode": "skill",
        "output_kind": "discovery",
        "output_payload": {
            "query": arguments,
            "items": jobs,
        },
        "operation_id": None,
    }


def _handle_artifact_generation(
    reads: CoreReadClient,
    actions: CoreActionClient,
    *,
    skill_name: str,
    arguments: str,
    selected_job_id: str | None,
    context_snapshot: str,
) -> dict[str, Any]:
    if not selected_job_id:
        return _build_no_output(
            "Select a queued role first so I know which job to use for this document.",
            context_snapshot=context_snapshot,
        )

    detail = reads.get_job_detail(selected_job_id)
    if detail is None:
        return _build_no_output(
            "I could not find that job anymore. Refresh the queue and try again.",
            context_snapshot=context_snapshot,
        )

    artifact_type = "resume" if skill_name == "resume" else "cover_letter"
    base_doc = reads.pick_default_base_document(artifact_type)
    if base_doc is None:
        label = "resume" if artifact_type == "resume" else "cover letter"
        return _build_no_output(
            f"Upload a base {label} in Settings first so I have something to tailor.",
            context_snapshot=context_snapshot,
        )

    operation = (
        actions.enqueue_resume_generation(selected_job_id, int(base_doc["id"]))
        if artifact_type == "resume"
        else actions.enqueue_cover_letter_generation(selected_job_id, int(base_doc["id"]))
    )
    label = "resume" if artifact_type == "resume" else "cover letter"
    reply = f"Starting a tailored {label} for {detail['company']} — {detail['title']}."
    if arguments:
        reply += f" Focus: {arguments}."
    return {
        "reply": reply,
        "context_snapshot": context_snapshot,
        "response_mode": "skill",
        "output_kind": artifact_type,
        "output_payload": {
            "job_id": selected_job_id,
            "artifact_type": artifact_type,
            "base_doc_id": int(base_doc["id"]),
            "job": {
                "id": str(detail.get("id") or ""),
                "company": str(detail.get("company") or ""),
                "title": str(detail.get("title") or ""),
                "location": str(detail.get("location") or ""),
            },
            "instructions": arguments,
        },
        "operation_id": str(operation.get("id") or ""),
    }


def _handle_critique(
    reads: CoreReadClient,
    *,
    arguments: str,
    selected_job_id: str | None,
    active_artifact_id: int | None,
    context_snapshot: str,
) -> dict[str, Any]:
    artifact = reads.get_artifact(active_artifact_id) if active_artifact_id else None
    if artifact is None and selected_job_id:
        artifacts = reads.get_job_artifacts(selected_job_id)
        artifact = next((item for item in artifacts if str(item.get("artifact_type")) == "resume"), None)
        if artifact is None:
            artifact = next(iter(artifacts), None)
    if artifact is None:
        return _build_no_output(
            "I do not have a generated draft to critique yet. Generate or open a draft first.",
            context_snapshot=context_snapshot,
        )

    payload = _build_critique_payload(artifact, instructions=arguments)
    return {
        "reply": "I reviewed the current draft and summarized the strongest improvements to make next.",
        "context_snapshot": context_snapshot,
        "response_mode": "skill",
        "output_kind": "critique",
        "output_payload": payload,
        "operation_id": None,
    }


def handle_agent_chat(
    messages: list[dict[str, str]],
    conn: Any,
    skill_invocation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reads = CoreReadClient(conn)
    actions = CoreActionClient()
    context_snapshot = build_agent_context(conn)

    invocation = resolve_skill_invocation(messages, skill_invocation)
    if invocation is None:
        legacy = handle_freeform_chat(messages, conn)
        legacy.setdefault("output_kind", "none")
        legacy.setdefault("output_payload", None)
        legacy.setdefault("operation_id", None)
        return legacy

    name = str(invocation.get("name") or "")
    arguments = str(invocation.get("arguments") or "")
    selected_job_id = invocation.get("selected_job_id")
    active_artifact_id = invocation.get("active_artifact_id")

    if name == "discover":
        return _handle_discover(
            reads,
            arguments=arguments,
            context_snapshot=context_snapshot,
        )
    if name in {"resume", "cover_letter"}:
        return _handle_artifact_generation(
            reads,
            actions,
            skill_name=name,
            arguments=arguments,
            selected_job_id=selected_job_id,
            context_snapshot=context_snapshot,
        )
    if name == "critique":
        return _handle_critique(
            reads,
            arguments=arguments,
            selected_job_id=selected_job_id,
            active_artifact_id=active_artifact_id,
            context_snapshot=context_snapshot,
        )

    return _build_no_output(
        "That skill is not available yet.",
        context_snapshot=context_snapshot,
    )
