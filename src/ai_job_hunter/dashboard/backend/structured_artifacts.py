"""
structured_artifacts.py — Structured JSON generation path for Loop B.

The legacy path (artifacts.generate_tailored_resume / generate_cover_letter) asks the
LLM for free-form markdown. That leaves us no way to know which bullets are grounded in
real user stories vs. invented by the model.

This module instead prompts the LLM for a JSON object where every bullet carries an
explicit source claim (story id, base_resume, or ungrounded) plus a source excerpt.
We then:
  1. Verify each claim by fuzzy-matching the excerpt against the cited source. If the
     excerpt doesn't show up in the source, we downgrade the bullet to "ungrounded"
     before persisting — the model cannot forge provenance.
  2. Render deterministic markdown from the JSON with inline `<!-- b-N -->` anchors
     that let the frontend map rendered bullets back to provenance entries.

Public entry points:
  - generate_resume_structured(job_id, base_doc_id, conn, feedback_hints="")
  - generate_cover_letter_structured(job_id, base_doc_id, conn, feedback_hints="")

Both return (content_md, provenance_list, story_ids_used).
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pydantic
import yaml

from ai_job_hunter.dashboard.backend import artifacts as artifact_svc
from ai_job_hunter import settings_service

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[3].parent / "prompts"

_VALID_RESUME_SOURCES = {"story", "base_resume", "ungrounded"}
_VALID_COVER_LETTER_SOURCES = {"story", "base_resume", "intent", "ungrounded"}
_STRUCTURED_PLUGINS = [{"id": "response-healing"}]
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_LLM_MODEL = "z-ai/glm-5.1"


# ---------------------------------------------------------------------------
# Pydantic output models — structured resume and cover letter
# ---------------------------------------------------------------------------

class _BulletOutput(pydantic.BaseModel):
    """A single content unit (bullet point or paragraph) inside a resume/cover-letter section."""
    text: str = pydantic.Field(description="The text of the bullet point or paragraph.")
    style: str = pydantic.Field(description="'bullet' for a list item, 'paragraph' for a prose block.")
    source_type: str = pydantic.Field(
        description="Provenance claim: 'story' (grounded in a user story), 'base_resume' (from the base resume), 'intent' (cover letter intent only), or 'ungrounded' (model-generated)."
    )
    source_id: int | None = pydantic.Field(
        None,
        description="Story id (integer) when source_type is 'story'; null for all other source types.",
    )
    source_excerpt: str | None = pydantic.Field(
        None,
        description="Verbatim short excerpt (10-30 words) copied from the cited source to prove the claim. null when source_type is 'ungrounded'.",
    )


class _SectionOutput(pydantic.BaseModel):
    """A resume section such as Experience, Skills, Education."""
    heading: str = pydantic.Field(description="Section heading, e.g. 'Experience', 'Skills', 'Education'.")
    subtitle: str | None = pydantic.Field(
        None,
        description="Optional subtitle, e.g. 'Senior Software Engineer at Acme Corp (2021-2024)'. null if not applicable.",
    )
    bullets: list[_BulletOutput] = pydantic.Field(
        default_factory=list,
        description="Ordered list of bullets or paragraphs in this section.",
    )


class _HeaderOutput(pydantic.BaseModel):
    """Resume header with contact information."""
    name: str = pydantic.Field(description="Candidate's full name.")
    email: str | None = pydantic.Field(None, description="Email address.")
    phone: str | None = pydantic.Field(None, description="Phone number.")
    location: str | None = pydantic.Field(None, description="City, Province/State or remote.")
    links: list[str] = pydantic.Field(
        default_factory=list,
        description="LinkedIn URL, portfolio URL, GitHub URL, or other relevant links.",
    )


class _ResumeStructuredOutput(pydantic.BaseModel):
    """Complete structured resume ready for provenance verification and markdown rendering."""
    header: _HeaderOutput = pydantic.Field(description="Contact and identity header.")
    sections: list[_SectionOutput] = pydantic.Field(
        description="Ordered list of resume sections. Must include Experience and Skills at minimum."
    )


class _CoverLetterStructuredOutput(pydantic.BaseModel):
    """Complete structured cover letter ready for provenance verification and markdown rendering."""
    header: _HeaderOutput = pydantic.Field(description="Contact and identity header (same as resume header).")
    sections: list[_SectionOutput] = pydantic.Field(
        description="Cover letter body as sections. Each section has paragraph-style bullets forming the letter."
    )


def _call_llm_structured(prompt: str, system: str, output_model: type, max_tokens: int = 4000) -> Any:
    """Call LLM_MODEL with structured output, returning a typed Pydantic object."""
    api_key = settings_service.get("OPENROUTER_API_KEY").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    model = settings_service.get("LLM_MODEL").strip()
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise RuntimeError("langchain-openai is required. Run: uv add langchain-openai") from e
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=_OPENROUTER_BASE_URL,
        temperature=0.3,
        max_tokens=max_tokens,
        extra_body={"plugins": _STRUCTURED_PLUGINS},
    )
    structured = llm.with_structured_output(output_model, method="json_schema", strict=True)
    return structured.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _load_structured_prompt(filename: str) -> dict[str, str]:
    path = _PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Structured prompt not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{filename} must contain a top-level mapping")
    node = next((v for v in data.values() if isinstance(v, dict)), None) or data
    system = node.get("system")
    user = node.get("user")
    if not isinstance(system, str) or not isinstance(user, str):
        raise ValueError(f"{filename} must define 'system' and 'user' strings")
    return {"system": system, "user": user}


def _render(template: str, variables: dict[str, str]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


# ---------------------------------------------------------------------------
# JSON parsing (robust against stray fences)
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def parse_llm_json(raw: str) -> dict:
    """
    Strip optional markdown fences and parse the first {...} JSON object.
    Raises ValueError on unparseable output.
    """
    s = raw.strip()
    s = _FENCE_RE.sub("", s).strip()
    # Find first { and last } to tolerate trailing commentary
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM output contains no JSON object")
    try:
        return json.loads(s[start : end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from LLM: {e}") from e


# ---------------------------------------------------------------------------
# Provenance verification (fuzzy excerpt matching)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str, min_len: int = 4) -> list[str]:
    if not text:
        return []
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= min_len]


def _excerpt_supports(excerpt: str, source: str, min_overlap: float = 0.5) -> bool:
    """
    Return True if >=min_overlap of meaningful tokens from excerpt appear in source.

    Forgiving enough to survive paraphrase; strict enough to catch fabricated facts
    (made-up company names, metrics, skills won't appear in the source).
    """
    ex_tokens = _tokens(excerpt)
    if not ex_tokens:
        return False
    src_tokens = set(_tokens(source, min_len=3))
    if not src_tokens:
        return False
    hits = sum(1 for t in ex_tokens if t in src_tokens)
    return (hits / len(ex_tokens)) >= min_overlap


def verify_provenance(
    structured: dict,
    stories: list[dict],
    base_resume: str,
    *,
    intent: str = "",
    artifact_type: str = "resume",
) -> dict:
    """
    Walk every bullet in the structured object and downgrade to "ungrounded" any
    source claim we can't verify.

    Mutates and returns the input (caller's copy is fine).
    """
    valid_sources = _VALID_COVER_LETTER_SOURCES if artifact_type == "cover_letter" else _VALID_RESUME_SOURCES
    stories_by_id = {int(s["id"]): s for s in stories if s.get("id") is not None}

    for section in structured.get("sections") or []:
        for bullet in section.get("bullets") or []:
            src_type = bullet.get("source_type") or "ungrounded"
            src_id = bullet.get("source_id")
            excerpt = bullet.get("source_excerpt") or ""

            if src_type not in valid_sources:
                src_type = "ungrounded"

            verified = False
            if src_type == "story" and src_id is not None:
                try:
                    sid = int(src_id)
                except (TypeError, ValueError):
                    sid = None
                if sid is not None and sid in stories_by_id:
                    story = stories_by_id[sid]
                    source_text = " ".join(
                        str(story.get(k) or "") for k in ("title", "narrative", "role_context")
                    )
                    if _excerpt_supports(excerpt, source_text):
                        verified = True
                        bullet["source_id"] = sid
            elif src_type == "base_resume":
                if _excerpt_supports(excerpt, base_resume):
                    verified = True
                bullet["source_id"] = None
            elif src_type == "intent":
                if _excerpt_supports(excerpt, intent):
                    verified = True
                bullet["source_id"] = None
            elif src_type == "ungrounded":
                verified = True
                bullet["source_id"] = None
                bullet["source_excerpt"] = None

            if not verified:
                bullet["source_type"] = "ungrounded"
                bullet["source_id"] = None
                bullet["source_excerpt"] = None
            else:
                bullet["source_type"] = src_type

    return structured


# ---------------------------------------------------------------------------
# Deterministic markdown rendering
# ---------------------------------------------------------------------------

def render_markdown_from_structured(
    structured: dict, artifact_type: str = "resume"
) -> tuple[str, list[dict]]:
    """
    Render (content_md, provenance) from a verified structured object.

    Each bullet gets a running id b1, b2, ... and an inline `<!-- b-N -->` anchor
    in the markdown. The provenance list is keyed by those ids.
    """
    lines: list[str] = []
    provenance: list[dict] = []
    counter = 0

    header = structured.get("header") or {}
    name = (header.get("name") or "").strip()
    if name:
        lines.append(f"# {name}")
        contact_bits = [
            header.get("email"),
            header.get("phone"),
            header.get("location"),
        ]
        contact_bits = [b for b in contact_bits if b]
        links = header.get("links") or []
        contact_bits.extend([str(link) for link in links if link])
        if contact_bits:
            lines.append(" · ".join(contact_bits))
        lines.append("")

    for section in structured.get("sections") or []:
        heading = (section.get("heading") or "").strip()
        subtitle = (section.get("subtitle") or "").strip() if section.get("subtitle") else ""

        if heading and artifact_type != "cover_letter":
            lines.append(f"## {heading}")
        if subtitle:
            lines.append(f"**{subtitle}**")

        for bullet in section.get("bullets") or []:
            text = (bullet.get("text") or "").strip()
            if not text:
                continue
            counter += 1
            bullet_id = f"b{counter}"
            style = bullet.get("style") or "bullet"
            anchor = f" <!-- {bullet_id} -->"

            if style == "paragraph" or artifact_type == "cover_letter":
                lines.append(f"{text}{anchor}")
                lines.append("")
            else:
                lines.append(f"- {text}{anchor}")

            provenance.append({
                "bullet_id": bullet_id,
                "text": text,
                "style": "paragraph" if style == "paragraph" else "bullet",
                "source_type": bullet.get("source_type") or "ungrounded",
                "source_id": bullet.get("source_id"),
                "source_excerpt": bullet.get("source_excerpt"),
            })

        if heading and artifact_type != "cover_letter":
            lines.append("")

    content_md = "\n".join(lines).rstrip() + "\n"
    return content_md, provenance


# ---------------------------------------------------------------------------
# Story retrieval (raw list — separate from artifacts.load_story_context_for_generation
# which returns pre-formatted text)
# ---------------------------------------------------------------------------

def _load_stories_for_grounding(job_id: str, conn: Any, top_k: int = 5) -> list[dict]:
    stories: list[dict] = []
    try:
        from ai_job_hunter.dashboard.backend.embeddings import get_relevant_stories_for_job
        stories = get_relevant_stories_for_job(job_id, conn, top_k=top_k)
    except Exception:
        stories = []

    if not stories:
        rows = conn.execute(
            """
            SELECT id, title, kind, narrative, role_context, skills, outcomes, importance
            FROM user_stories
            WHERE draft = 0
            ORDER BY importance DESC, created_at DESC
            LIMIT ?
            """,
            (top_k,),
        ).fetchall()
        for r in rows:
            try:
                skills_list = json.loads(r[5] or "[]") or []
            except Exception:
                skills_list = []
            try:
                outcomes_list = json.loads(r[6] or "[]") or []
            except Exception:
                outcomes_list = []
            stories.append({
                "id": r[0],
                "title": r[1],
                "kind": r[2],
                "narrative": r[3],
                "role_context": r[4],
                "skills": skills_list,
                "outcomes": outcomes_list,
                "importance": r[7],
            })
    return stories


def _format_story_bank(stories: list[dict]) -> str:
    if not stories:
        return "(No stories available — candidate has not added any stories yet.)"
    lines: list[str] = []
    for s in stories:
        sid = s.get("id")
        title = s.get("title") or ""
        kind = s.get("kind") or ""
        lines.append(f"[id={sid}] {title} ({kind})")
        if s.get("role_context"):
            lines.append(f"  role_context: {s['role_context']}")
        if s.get("narrative"):
            lines.append(f"  narrative: {s['narrative']}")
        outcomes = s.get("outcomes") or []
        if outcomes:
            lines.append(f"  outcomes: {'; '.join(str(o) for o in outcomes)}")
        skills = s.get("skills") or []
        if skills:
            lines.append(f"  skills: {', '.join(str(k) for k in skills)}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Structured generation entry points
# ---------------------------------------------------------------------------

def _format_years_range(job: dict) -> str:
    lo = job.get("years_exp_min")
    hi = job.get("years_exp_max")
    if lo is None and hi is None:
        return "Not specified"
    if lo is not None and hi is not None:
        return f"{lo}-{hi} years"
    return f"{lo or hi} years"


def generate_resume_structured(
    job_id: str,
    base_doc_id: int,
    conn: Any,
    *,
    feedback_hints: str = "",
) -> tuple[str, list[dict], list[int]]:
    """
    Generate a structured, provenance-verified tailored resume.
    Returns (content_md, provenance, story_ids_used).
    """
    job = artifact_svc._load_job_context(job_id, conn)
    profile = artifact_svc._load_profile_context(conn)
    base_doc = artifact_svc.get_base_document(base_doc_id, conn)
    if not base_doc:
        raise ValueError(f"Base document {base_doc_id} not found")
    base_resume = base_doc.get("content_md") or ""

    stories = _load_stories_for_grounding(job_id, conn)
    story_ids_used = [int(s["id"]) for s in stories if s.get("id") is not None]
    story_bank_text = _format_story_bank(stories)

    prompt_tpl = _load_structured_prompt("resume_tailoring_structured.yaml")
    vars_ = {
        "job_title": str(job.get("title") or ""),
        "job_company": str(job.get("company") or ""),
        "job_location": str(job.get("location") or ""),
        "job_seniority": str(job.get("seniority") or "Not specified"),
        "job_work_mode": str(job.get("work_mode") or "Not specified"),
        "job_years_range": _format_years_range(job),
        "job_required_skills": ", ".join((job.get("required_skills") or [])[:12]) or "Not specified",
        "job_preferred_skills": ", ".join((job.get("preferred_skills") or [])[:12]) or "Not specified",
        "job_description_excerpt": str(job.get("description") or "")[:2500],
        "profile_full_name": str(profile.get("full_name") or ""),
        "profile_email": str(profile.get("email") or ""),
        "profile_phone": str(profile.get("phone") or ""),
        "profile_linkedin": str(profile.get("linkedin_url") or ""),
        "profile_portfolio": str(profile.get("portfolio_url") or ""),
        "profile_city": str(profile.get("city") or ""),
        "profile_country": str(profile.get("country") or ""),
        "story_bank": story_bank_text,
        "base_resume_text": base_resume[:6000],
        "feedback_hints": feedback_hints or "(none — this is the first iteration)",
    }
    user_prompt = _render(prompt_tpl["user"], vars_)

    result = _call_llm_structured(
        user_prompt, prompt_tpl["system"], _ResumeStructuredOutput, max_tokens=5000
    )
    structured = result.model_dump()
    structured = verify_provenance(
        structured, stories=stories, base_resume=base_resume, artifact_type="resume"
    )
    content_md, provenance = render_markdown_from_structured(structured, artifact_type="resume")
    return content_md, provenance, story_ids_used


def generate_cover_letter_structured(
    job_id: str,
    base_doc_id: int,
    conn: Any,
    *,
    feedback_hints: str = "",
) -> tuple[str, list[dict], list[int]]:
    """
    Generate a structured, provenance-verified tailored cover letter.
    Returns (content_md, provenance, story_ids_used).
    """
    job = artifact_svc._load_job_context(job_id, conn)
    profile = artifact_svc._load_profile_context(conn)
    base_doc = artifact_svc.get_base_document(base_doc_id, conn)
    if not base_doc:
        raise ValueError(f"Base document {base_doc_id} not found")
    base_resume = base_doc.get("content_md") or ""
    intent = str(profile.get("narrative_intent") or "")

    stories = _load_stories_for_grounding(job_id, conn)
    story_ids_used = [int(s["id"]) for s in stories if s.get("id") is not None]
    story_bank_text = _format_story_bank(stories)

    prompt_tpl = _load_structured_prompt("cover_letter_structured.yaml")
    vars_ = {
        "job_title": str(job.get("title") or ""),
        "job_company": str(job.get("company") or ""),
        "job_location": str(job.get("location") or ""),
        "job_description_excerpt": str(job.get("description") or "")[:2500],
        "profile_full_name": str(profile.get("full_name") or ""),
        "profile_narrative_intent": intent or "(not provided)",
        "story_bank": story_bank_text,
        "base_resume_text": base_resume[:4000],
        "feedback_hints": feedback_hints or "(none — this is the first iteration)",
    }
    user_prompt = _render(prompt_tpl["user"], vars_)

    result = _call_llm_structured(
        user_prompt, prompt_tpl["system"], _CoverLetterStructuredOutput, max_tokens=3000
    )
    structured = result.model_dump()
    structured = verify_provenance(
        structured,
        stories=stories,
        base_resume=base_resume,
        intent=intent,
        artifact_type="cover_letter",
    )
    content_md, provenance = render_markdown_from_structured(
        structured, artifact_type="cover_letter"
    )
    return content_md, provenance, story_ids_used
