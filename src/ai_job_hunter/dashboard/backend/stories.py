"""
stories.py — User story bank: CRUD and LLM-driven resume extraction.

A "story" is a rich narrative unit about the jobseeker — a role, project,
aspiration, or strength — that goes beyond a flat skill list. Stories feed
semantic ranking (item 2) and grounded artifact generation (item 3).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import pydantic
import yaml

from ai_job_hunter import settings_service

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json_list(raw: Any) -> list:
    if not raw:
        return []
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _row_to_dict(row: tuple) -> dict:
    return {
        "id": row[0],
        "title": row[1],
        "narrative": row[2] or "",
        "role_context": row[3],
        "skills": _parse_json_list(row[4]),
        "outcomes": _parse_json_list(row[5]),
        "tags": _parse_json_list(row[6]),
        "importance": row[7] if row[7] is not None else 3,
        "time_period": row[8],
        "kind": row[9] or "role",
        "source": row[10] or "user",
        "draft": bool(row[11]),
        "created_at": row[12],
        "updated_at": row[13],
    }


_SELECT = """
    SELECT id, title, narrative, role_context, skills, outcomes, tags,
           importance, time_period, kind, source, draft, created_at, updated_at
    FROM user_stories
"""


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def list_stories(conn: Any, *, include_drafts: bool = True) -> list[dict]:
    where = "" if include_drafts else "WHERE draft = 0"
    rows = conn.execute(
        f"{_SELECT} {where} ORDER BY draft ASC, importance DESC, created_at DESC"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_story(story_id: int, conn: Any) -> dict | None:
    row = conn.execute(f"{_SELECT} WHERE id = ?", (story_id,)).fetchone()
    return _row_to_dict(row) if row else None


def create_story(data: dict, conn: Any) -> dict:
    now = _now()
    conn.execute(
        """
        INSERT INTO user_stories
            (title, narrative, role_context, skills, outcomes, tags,
             importance, time_period, kind, source, draft, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(data.get("title") or ""),
            str(data.get("narrative") or ""),
            data.get("role_context"),
            json.dumps(list(data.get("skills") or [])),
            json.dumps(list(data.get("outcomes") or [])),
            json.dumps(list(data.get("tags") or [])),
            int(data.get("importance") or 3),
            data.get("time_period"),
            str(data.get("kind") or "role"),
            str(data.get("source") or "user"),
            1 if data.get("draft") else 0,
            now,
            now,
        ),
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return get_story(int(row_id), conn)  # type: ignore[return-value]


def update_story(story_id: int, data: dict, conn: Any) -> dict | None:
    existing = get_story(story_id, conn)
    if not existing:
        return None

    fields: list[str] = []
    values: list[Any] = []

    for key in ("title", "narrative", "role_context", "time_period", "kind"):
        if key in data and data[key] is not None:
            fields.append(f"{key} = ?")
            values.append(str(data[key]))

    for key in ("importance",):
        if key in data and data[key] is not None:
            fields.append(f"{key} = ?")
            values.append(int(data[key]))

    if "draft" in data and data["draft"] is not None:
        fields.append("draft = ?")
        values.append(1 if data["draft"] else 0)

    for key in ("skills", "outcomes", "tags"):
        if key in data and data[key] is not None:
            fields.append(f"{key} = ?")
            values.append(json.dumps(list(data[key])))

    if not fields:
        return existing

    fields.append("updated_at = ?")
    values.append(_now())
    values.append(story_id)

    conn.execute(
        f"UPDATE user_stories SET {', '.join(fields)} WHERE id = ?", values
    )
    conn.commit()
    return get_story(story_id, conn)


def delete_story(story_id: int, conn: Any) -> bool:
    result = conn.execute(
        "DELETE FROM user_stories WHERE id = ?", (story_id,)
    )
    conn.commit()
    return (result.rowcount if hasattr(result, "rowcount") else 1) > 0


def bulk_accept_stories(story_ids: list[int], conn: Any) -> int:
    """Flip draft=0 for the given story IDs. Returns count updated."""
    if not story_ids:
        return 0
    placeholders = ",".join("?" * len(story_ids))
    conn.execute(
        f"UPDATE user_stories SET draft = 0, updated_at = ? WHERE id IN ({placeholders})",
        [_now(), *story_ids],
    )
    conn.commit()
    return len(story_ids)


def count_stories(conn: Any) -> dict[str, int]:
    row = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN draft=0 THEN 1 ELSE 0 END) FROM user_stories"
    ).fetchone()
    total = int(row[0]) if row else 0
    accepted = int(row[1]) if row and row[1] is not None else 0
    return {"total": total, "accepted": accepted, "drafts": total - accepted}


# ---------------------------------------------------------------------------
# LLM extraction from resume — Pydantic output models
# ---------------------------------------------------------------------------

_RESUME_EXTRACTION_PLUGINS = [{"id": "response-healing"}]
_PROMPTS_DIR = Path(__file__).resolve().parents[3].parent / "prompts"


@lru_cache(maxsize=1)
def _load_extraction_prompt() -> dict:
    path = _PROMPTS_DIR / "resume_extraction.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    node = next((v for v in data.values() if isinstance(v, dict)), None) or data
    return node


def _render(template: str, variables: dict[str, str]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


class _ProfileDeltaOutput(pydantic.BaseModel):
    """Structured profile information extracted from a resume."""
    full_name: str | None = pydantic.Field(None, description="Candidate's full name from the resume header.")
    email: str | None = pydantic.Field(None, description="Email address if present.")
    phone: str | None = pydantic.Field(None, description="Phone number if present.")
    linkedin_url: str | None = pydantic.Field(None, description="LinkedIn profile URL if present.")
    portfolio_url: str | None = pydantic.Field(None, description="Portfolio or personal website URL if present.")
    city: str | None = pydantic.Field(None, description="City from the resume location field.")
    country: str | None = pydantic.Field(None, description="Country from the resume location field.")
    years_experience: int | None = pydantic.Field(None, description="Total professional years — explicitly stated or computed from earliest to latest role date, rounded down. null if not determinable.")
    skills: list[str] = pydantic.Field(default_factory=list, description="Every distinct technical skill, tool, library, language, framework, platform, method, and certification mentioned anywhere in the resume.")
    desired_job_titles: list[str] = pydantic.Field(default_factory=list, description="Stated career objective titles, or 1-3 inferred from the most recent roles only if unambiguous.")
    degree: Literal["high_school", "associate", "bachelor", "master", "phd"] | None = pydantic.Field(None, description="Highest degree level. null if not stated.")
    degree_field: str | None = pydantic.Field(None, description="Field of study for the highest degree. null if not stated.")


class _StoryOutput(pydantic.BaseModel):
    """A single career story extracted from a resume."""
    title: str = pydantic.Field(description="'Job Title at Company' for roles, project name for projects, 'Career objective' for aspirations.")
    narrative: str = pydantic.Field(description="Faithful, full paraphrase of everything the resume says about this item. Do not truncate. Do not invent.")
    role_context: str | None = pydantic.Field(None, description="'Company (date range)' for roles; null for projects and aspirations.")
    skills: list[str] = pydantic.Field(default_factory=list, description="Skills specifically mentioned or clearly demonstrated in this role/project — a subset of profile_delta skills.")
    outcomes: list[str] = pydantic.Field(default_factory=list, description="Quantified or clearly stated results, accomplishments, or impact. Empty if none stated.")
    tags: list[str] = pydantic.Field(default_factory=list, description="1-4 domain/theme tags such as 'fintech', 'leadership', 'distributed-systems', 'nlp'.")
    importance: int = pydantic.Field(description="1-5 score: 5=most recent or senior role, 4=second most recent, 3=average, 2=older/less relevant, 1=very old or minor.")
    time_period: str | None = pydantic.Field(None, description="Date range as stated in the resume, e.g. '2022-2024'. null if not present.")
    kind: Literal["role", "project", "aspiration", "strength"] = pydantic.Field(description="role=work experience entry, project=specific project, aspiration=career objective/summary, strength=personal trait.")


class _ExtractFromResumeOutput(pydantic.BaseModel):
    """Complete structured extraction from a resume document."""
    profile_delta: _ProfileDeltaOutput = pydantic.Field(description="Profile information extracted from the resume header, summary, and contact section.")
    stories: list[_StoryOutput] = pydantic.Field(description="One story per distinct role, project, or aspiration. Minimum 1, maximum 10.")


def _call_llm_structured(prompt: str, system: str) -> _ExtractFromResumeOutput:
    """Call LLM_MODEL with structured output, returning a typed _ExtractFromResumeOutput."""
    api_key = settings_service.get("OPENROUTER_API_KEY").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    model = settings_service.get("LLM_MODEL").strip()
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise RuntimeError("langchain-openai is required. Run: uv add langchain-openai")
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=_OPENROUTER_BASE_URL,
        temperature=0.1,
        max_tokens=4000,
        extra_body={"plugins": _RESUME_EXTRACTION_PLUGINS},
    )
    structured = llm.with_structured_output(_ExtractFromResumeOutput, method="json_schema", strict=True)
    return structured.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])


def extract_from_resume(content_md: str) -> dict:
    """
    Run LLM extraction over a base resume's markdown content.

    Returns a dict with two keys:
      profile_delta: dict matching ExtractedProfileDelta fields
      stories: list of dicts matching UserStoryCreate fields (all with draft=True, source='resume_extracted')
    """
    tpl = _load_extraction_prompt()
    system = tpl["system"].strip()
    prompt = _render(tpl["user"], {"resume_content": content_md[:6000]})
    result = _call_llm_structured(prompt, system)

    # Convert Pydantic object → dicts, stamping stories as draft resume-extracted
    pd = result.profile_delta
    profile_delta = {
        "full_name": pd.full_name,
        "email": pd.email,
        "phone": pd.phone,
        "linkedin_url": pd.linkedin_url,
        "portfolio_url": pd.portfolio_url,
        "city": pd.city,
        "country": pd.country,
        "years_experience": pd.years_experience,
        "skills": [str(x) for x in (pd.skills or []) if x],
        "desired_job_titles": [str(x) for x in (pd.desired_job_titles or []) if x],
        "degree": pd.degree,
        "degree_field": pd.degree_field,
    }

    stories: list[dict] = []
    for s in result.stories:
        title = (s.title or "").strip()
        if not title:
            continue
        kind = s.kind or "role"
        if kind not in ("role", "project", "aspiration", "strength"):
            kind = "role"
        stories.append({
            "title": title,
            "narrative": (s.narrative or "").strip(),
            "role_context": s.role_context or None,
            "skills": [str(x) for x in (s.skills or []) if x],
            "outcomes": [str(x) for x in (s.outcomes or []) if x],
            "tags": [str(x) for x in (s.tags or []) if x],
            "importance": max(1, min(5, int(s.importance or 3))),
            "time_period": s.time_period or None,
            "kind": kind,
            "source": "resume_extracted",
            "draft": True,
        })

    return {"profile_delta": profile_delta, "stories": stories}


def save_extracted_stories(stories: list[dict], conn: Any) -> list[dict]:
    """Persist extracted story dicts (all marked draft=True). Returns saved stories."""
    saved = []
    for s in stories:
        saved.append(create_story({**s, "draft": True, "source": "resume_extracted"}, conn))
    return saved
