"""
llm_screener.py — Recruiter-POV LLM screener for Loop B.

Runs AFTER the deterministic keyword gate. The screener reads the tailored resume
like a 30-second recruiter screen and returns pass / borderline / fail plus
strengths, gaps, and red flags. The orchestrator feeds `gaps + red_flags` back
into the next iteration's prompt as feedback hints.

Uses LLM_MODEL (default z-ai/glm-5.1) — this is the quality-critical step,
not the cheap one.
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import pydantic
import yaml

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_LLM_MODEL = "z-ai/glm-5.1"
_SCREENER_PLUGINS = [{"id": "response-healing"}]


class _ScreenerOutput(pydantic.BaseModel):
    """Structured output for the LLM recruiter screen."""
    verdict: str = pydantic.Field(
        description="Recruiter verdict: 'pass' if the resume clearly meets requirements, 'fail' if it clearly does not, 'borderline' if it is close or uncertain."
    )
    confidence: int = pydantic.Field(
        description="Confidence in the verdict, 0-100."
    )
    strengths: list[str] = pydantic.Field(
        default_factory=list,
        description="Resume strengths that directly support the job requirements.",
    )
    gaps: list[str] = pydantic.Field(
        default_factory=list,
        description="Missing qualifications, experience gaps, or weak areas relative to the job.",
    )
    red_flags: list[str] = pydantic.Field(
        default_factory=list,
        description="Serious concerns — unexplained gaps, role mismatch, missing hard requirements.",
    )
    one_line_summary: str = pydantic.Field(
        description="One-sentence recruiter summary of why this resume passes, fails, or is borderline."
    )

_PROMPTS_DIR = Path(__file__).resolve().parents[4].parent / "prompts"
_PROMPT_FILE = "llm_screener.yaml"

_VALID_VERDICTS = {"pass", "borderline", "fail"}


@dataclass
class ScreenerVerdict:
    verdict: str  # "pass" | "borderline" | "fail"
    confidence: int  # 0-100
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    one_line_summary: str = ""
    error: str | None = None  # populated if screener failed to produce a verdict

    def to_dict(self) -> dict:
        return asdict(self)

    def feedback_hints(self) -> str:
        """Human-readable feedback for the next iteration's prompt."""
        parts: list[str] = []
        if self.gaps:
            parts.append("Recruiter-flagged gaps: " + "; ".join(self.gaps))
        if self.red_flags:
            parts.append("Recruiter red flags: " + "; ".join(self.red_flags))
        if not parts:
            return "Screener passed — no recruiter-flagged issues."
        return "\n".join(parts)


@lru_cache(maxsize=1)
def _load_prompt() -> dict[str, str]:
    path = _PROMPTS_DIR / _PROMPT_FILE
    if not path.exists():
        raise FileNotFoundError(f"Screener prompt not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    node = next((v for v in data.values() if isinstance(v, dict)), None) or data
    system = node.get("system")
    user = node.get("user")
    if not isinstance(system, str) or not isinstance(user, str):
        raise ValueError(f"{_PROMPT_FILE} must define 'system' and 'user' strings")
    return {"system": system, "user": user}


def _render(template: str, variables: dict[str, str]) -> str:
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered


def _call_screener_structured(prompt: str, system: str) -> _ScreenerOutput:
    """Call LLM_MODEL and return a typed _ScreenerOutput via structured output."""
    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    model = (os.getenv("LLM_MODEL") or _DEFAULT_LLM_MODEL).strip()
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise RuntimeError("langchain-openai is required. Run: uv add langchain-openai") from e
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=_OPENROUTER_BASE_URL,
        temperature=0.1,
        max_tokens=1200,
        extra_body={"plugins": _SCREENER_PLUGINS},
    )
    structured = llm.with_structured_output(_ScreenerOutput, method="json_schema", strict=True)
    return structured.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])


def _coerce_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def screen_resume(
    resume_md: str,
    job: dict,
) -> ScreenerVerdict:
    """
    Run the LLM recruiter screen against `resume_md` for `job`.

    `job` is the dict returned by artifacts._load_job_context — we read
    title, company, seniority, required_skills, preferred_skills, description.

    On any error (missing API key, LLM failure, malformed JSON) returns a
    ScreenerVerdict with verdict="borderline" + populated `error` so the
    orchestrator can proceed without crashing.
    """
    if not resume_md or not resume_md.strip():
        return ScreenerVerdict(
            verdict="fail",
            confidence=0,
            red_flags=["Resume is empty."],
            one_line_summary="Empty resume cannot be screened.",
        )

    try:
        tpl = _load_prompt()
    except Exception as e:
        logger.exception("Failed to load screener prompt")
        return ScreenerVerdict(
            verdict="borderline",
            confidence=0,
            one_line_summary="Screener unavailable (prompt load failed).",
            error=str(e),
        )

    vars_ = {
        "job_title": str(job.get("title") or ""),
        "job_company": str(job.get("company") or ""),
        "job_seniority": str(job.get("seniority") or "Not specified"),
        "job_required_skills": ", ".join((job.get("required_skills") or [])[:12]) or "Not specified",
        "job_preferred_skills": ", ".join((job.get("preferred_skills") or [])[:12]) or "Not specified",
        "job_description_excerpt": str(job.get("description") or "")[:2500],
        "resume_md": resume_md[:8000],
    }
    user_prompt = _render(tpl["user"], vars_)

    try:
        result = _call_screener_structured(user_prompt, tpl["system"])
    except Exception as e:
        logger.exception("LLM screener call failed")
        return ScreenerVerdict(
            verdict="borderline",
            confidence=0,
            one_line_summary="Screener LLM call failed.",
            error=str(e),
        )

    verdict = str(result.verdict or "").strip().lower()
    if verdict not in _VALID_VERDICTS:
        verdict = "borderline"

    return ScreenerVerdict(
        verdict=verdict,
        confidence=max(0, min(100, _coerce_int(result.confidence, 50))),
        strengths=_coerce_str_list(result.strengths),
        gaps=_coerce_str_list(result.gaps),
        red_flags=_coerce_str_list(result.red_flags),
        one_line_summary=str(result.one_line_summary or "")[:240],
    )
