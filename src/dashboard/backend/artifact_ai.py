from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class _PatchOperation(BaseModel):
    op: str = Field(pattern="^(add|replace|remove)$")
    path: str = Field(min_length=1)
    value: object | None = None


class _Suggestion(BaseModel):
    target_path: str | None = None
    summary: str | None = None
    group_key: str | None = None
    patch_json: list[_PatchOperation] = Field(default_factory=list)


class _SuggestionEnvelope(BaseModel):
    suggestions: list[_Suggestion] = Field(default_factory=list)


def _build_fallback_suggestion(*, artifact_type: str, prompt: str, target_path: str | None) -> list[dict[str, Any]]:
    if artifact_type == "resume":
        return [
            {
                "target_path": target_path or "/basics/summary",
                "summary": "Rewrite summary to align with the job posting",
                "group_key": "summary",
                "patch_json": [
                    {
                        "op": "replace",
                        "path": target_path or "/basics/summary",
                        "value": f"Tailored draft: {prompt[:220]}",
                    }
                ],
            }
        ]
    return [
        {
            "target_path": target_path or "/blocks/1/text",
            "summary": "Rewrite a core cover-letter paragraph for role fit",
            "group_key": "body",
            "patch_json": [
                {
                    "op": "replace",
                    "path": target_path or "/blocks/1/text",
                    "value": f"Tailored draft: {prompt[:220]}",
                }
            ],
        }
    ]


def generate_patch_suggestions(
    *,
    artifact_type: str,
    artifact_content: dict[str, Any],
    job_context: dict[str, Any],
    prompt: str,
    target_path: str | None,
    max_suggestions: int,
    api_key: str,
    model: str,
) -> list[dict[str, Any]]:
    if not api_key.strip():
        raise ValueError("OPENROUTER_API_KEY is required for AI suggestions")

    system = (
        "You are an assistant that proposes safe JSON patch operations for job-application artifacts. "
        "Return suggestions only; do not return full documents. "
        "Each suggestion must include target_path, summary, group_key, and patch_json."
    )
    human_payload = {
        "artifact_type": artifact_type,
        "prompt": prompt,
        "target_path": target_path,
        "max_suggestions": max_suggestions,
        "job": {
            "company": job_context.get("company"),
            "title": job_context.get("title"),
            "description": str(job_context.get("description") or "")[:6000],
            "required_skills": ((job_context.get("enrichment") or {}).get("required_skills") or []),
            "preferred_skills": ((job_context.get("enrichment") or {}).get("preferred_skills") or []),
        },
        "artifact_content": artifact_content,
    }

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=_OPENROUTER_BASE_URL,
        temperature=0.2,
        timeout=90,
    ).with_structured_output(_SuggestionEnvelope)

    try:
        response: _SuggestionEnvelope = llm.invoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=json.dumps(human_payload, ensure_ascii=True)),
            ]
        )
        output: list[dict[str, Any]] = []
        for suggestion in response.suggestions[:max_suggestions]:
            output.append(
                {
                    "target_path": suggestion.target_path,
                    "summary": suggestion.summary,
                    "group_key": suggestion.group_key,
                    "patch_json": [op.model_dump() for op in suggestion.patch_json],
                }
            )
        if output:
            return output
    except Exception:
        # Fail soft in v1: return deterministic local fallback suggestion.
        pass

    return _build_fallback_suggestion(artifact_type=artifact_type, prompt=prompt, target_path=target_path)
