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
from typing import Any

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
# LLM extraction from resume
# ---------------------------------------------------------------------------

def _call_llm_json(prompt: str, system: str) -> str:
    """Call LLM_MODEL (complex task tier) and return raw text."""
    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    model = (os.getenv("LLM_MODEL") or "z-ai/glm-5.1").strip()

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
    )
    response = llm.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])
    return str(getattr(response, "content", "") or "").strip()


def _clean_json_response(raw: str) -> str:
    """Strip markdown fences if the model wrapped the JSON."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop opening fence line and closing fence
        inner = []
        in_block = False
        for line in lines:
            if line.startswith("```") and not in_block:
                in_block = True
                continue
            if line.startswith("```") and in_block:
                break
            if in_block:
                inner.append(line)
        text = "\n".join(inner).strip()
    return text


def extract_from_resume(content_md: str) -> dict:
    """
    Run LLM extraction over a base resume's markdown content.

    Returns a dict with two keys:
      profile_delta: dict matching ExtractedProfileDelta fields
      stories: list of dicts matching UserStoryCreate fields (all with draft=True, source='resume_extracted')
    """
    system = (
        "You are a structured data extraction engine. "
        "Output exactly one JSON object — starting with { and ending with }. "
        "Zero text, markdown fences, or explanation before or after the JSON. "
        "Extract only facts explicitly present in the resume. Never invent, embellish, or infer. "
        "Use null for any missing scalar field. Use [] for any missing list field."
    )

    prompt = f"""Extract structured data from the resume below.

RESUME:
{content_md[:6000]}

===OUTPUT SCHEMA===
Output ONLY this JSON object — exactly these two top-level keys:

{{
  "profile_delta": {{
    "full_name":          string or null,
    "email":              string or null,
    "phone":              string or null,
    "linkedin_url":       string or null,
    "portfolio_url":      string or null,
    "city":               string or null,
    "country":            string or null,
    "years_experience":   integer or null,
    "skills":             ["string", ...],
    "desired_job_titles": ["string", ...],
    "degree":             "high_school"|"associate"|"bachelor"|"master"|"phd" or null,
    "degree_field":       string or null
  }},
  "stories": [
    {{
      "title":        string,
      "narrative":    string,
      "role_context": string or null,
      "skills":       ["string", ...],
      "outcomes":     ["string", ...],
      "tags":         ["string", ...],
      "importance":   integer 1-5,
      "time_period":  string or null,
      "kind":         "role"|"project"|"aspiration"|"strength"
    }}
  ]
}}

===EXTRACTION RULES===

profile_delta:
- full_name: The candidate's full name from the header.
- email/phone/linkedin_url/portfolio_url: Contact details only if present.
- city/country: Location if stated.
- years_experience: Total professional years if explicitly stated; else compute from earliest to latest role end date (or today); round down. null if not determinable.
- skills: Every distinct technical skill, tool, library, language, framework, platform, method, and certification mentioned anywhere in the resume. Be exhaustive.
- desired_job_titles: Any stated career objective titles, or infer 1-3 titles from the most recent roles only if they are clear.
- degree / degree_field: Highest degree level and field of study. Use null if not stated.

stories (create one story per item below):
1. ONE story per distinct ROLE / EMPLOYMENT entry. Use the job title + company as the title. The narrative must faithfully paraphrase what the resume says — do NOT invent. Include every bullet point or responsibility described in that role. kind="role".
2. ONE story per distinct PROJECT if the resume has a projects section. kind="project".
3. If the resume contains an objective or summary section, create ONE aspiration story capturing it. kind="aspiration".

For each story:
- title: "<Job Title> at <Company>" for roles, project name for projects, "Career objective" for aspirations.
- narrative: A faithful, full paraphrase of everything the resume says about this item. Do not truncate. Do not invent.
- role_context: "<Company> (<date range>)" for roles; null for aspirations.
- skills: Skills specifically mentioned or clearly demonstrated in this role/project — a subset of profile_delta.skills.
- outcomes: Quantified or clearly stated results, accomplishments, or impact ("Reduced latency by 30%", "Led team of 5 engineers"). Empty list if none stated.
- tags: 1-4 domain/theme tags (e.g. "fintech", "leadership", "distributed-systems", "nlp").
- importance: 5 = most recent or most senior role; 4 = second most recent; 3 = average; 2 = older/less relevant; 1 = very old or minor.
- time_period: Date range as stated in the resume, e.g. "2022-2024". null if not present.

Minimum 1 story (at least the most recent role). Maximum 10 stories.
===END SCHEMA==="""

    raw = _call_llm_json(prompt, system)
    cleaned = _clean_json_response(raw)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"LLM returned non-JSON response during resume extraction: {exc}\n\nRaw: {raw[:500]}"
        ) from exc

    # Normalise profile_delta
    profile_delta = data.get("profile_delta") or {}
    if not isinstance(profile_delta, dict):
        profile_delta = {}

    # Normalise stories and stamp them as draft resume-extracted
    raw_stories = data.get("stories") or []
    if not isinstance(raw_stories, list):
        raw_stories = []

    stories: list[dict] = []
    for s in raw_stories:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or "").strip()
        if not title:
            continue
        stories.append(
            {
                "title": title,
                "narrative": str(s.get("narrative") or "").strip(),
                "role_context": s.get("role_context") or None,
                "skills": [str(x) for x in (s.get("skills") or []) if x],
                "outcomes": [str(x) for x in (s.get("outcomes") or []) if x],
                "tags": [str(x) for x in (s.get("tags") or []) if x],
                "importance": max(1, min(5, int(s.get("importance") or 3))),
                "time_period": s.get("time_period") or None,
                "kind": str(s.get("kind") or "role"),
                "source": "resume_extracted",
                "draft": True,
            }
        )

    return {"profile_delta": profile_delta, "stories": stories}


def save_extracted_stories(stories: list[dict], conn: Any) -> list[dict]:
    """Persist extracted story dicts (all marked draft=True). Returns saved stories."""
    saved = []
    for s in stories:
        saved.append(create_story({**s, "draft": True, "source": "resume_extracted"}, conn))
    return saved
