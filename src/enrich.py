"""
enrich.py — LLM enrichment pipeline via OpenRouter.

Extracts structured metadata from job descriptions using a cheap LLM.
Uses LangChain (ChatOpenAI) for API calls and Pydantic for output validation.
"""
from __future__ import annotations

import json
import logging
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

# LangChain attaches a `parsed` field to raw response objects for internal bookkeeping;
# Pydantic complains it doesn't match the schema. The warning is cosmetic — data is correct.
warnings.filterwarnings(
    "ignore",
    message=".*PydanticSerializationUnexpectedValue.*",
    category=UserWarning,
)

from db import save_enrichment

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_SYSTEM_PROMPT = (
    "You are a precise structured data extractor. "
    "Return ONLY valid JSON, no explanation. "
    "Use null for fields not mentioned. Never invent information."
)

_SCHEMA_DESCRIPTION = """\
{
  "work_mode":           "remote" | "hybrid" | "onsite" | null,
  "remote_geo":          string | null,
  "canada_eligible":     "yes" | "no" | "unknown",
  "seniority":           "intern" | "junior" | "mid" | "senior" | "staff" | "principal" | null,
  "role_family":         "data scientist" | "ml engineer" | "mlops engineer" | "data engineer" | "research scientist" | "analyst" | "other",
  "years_exp_min":       integer | null,
  "years_exp_max":       integer | null,
  "must_have_skills":    [strings],
  "nice_to_have_skills": [strings],
  "tech_stack":          [strings],
  "salary_min":          integer | null,
  "salary_max":          integer | null,
  "salary_currency":     "CAD" | "USD" | null,
  "visa_sponsorship":    "yes" | "no" | "unknown",
  "red_flags":           [strings]
}

canada_eligible rules:
  "yes"     — role is open to candidates in Canada (e.g. remote North America, worldwide remote, explicitly mentions Canada)
  "no"      — requires US work authorization, US residency/citizenship, or a fixed non-Canadian office location
  "unknown" — description does not mention work location or authorization requirements"""

_SIMPLIFIED_SCHEMA_DESCRIPTION = """\
{
  "work_mode":        "remote" | "hybrid" | "onsite" | null,
  "canada_eligible":  "yes" | "no" | "unknown",
  "seniority":        "intern" | "junior" | "mid" | "senior" | "staff" | "principal" | null,
  "role_family":      "data scientist" | "ml engineer" | "mlops engineer" | "data engineer" | "research scientist" | "analyst" | "other",
  "visa_sponsorship": "yes" | "no" | "unknown",
  "must_have_skills": [strings],
  "tech_stack":       [strings]
}

canada_eligible: "yes" if open to Canada-based candidates, "no" if US work auth required, "unknown" if not mentioned."""


# ---------------------------------------------------------------------------
# Pydantic output schema
# ---------------------------------------------------------------------------

class JobEnrichment(BaseModel):
    """Structured metadata extracted from a job posting."""
    work_mode: Optional[Literal["remote", "hybrid", "onsite"]] = None
    remote_geo: Optional[str] = None
    canada_eligible: Literal["yes", "no", "unknown"] = "unknown"
    seniority: Optional[Literal["intern", "junior", "mid", "senior", "staff", "principal"]] = None
    role_family: Literal[
        "data scientist", "ml engineer", "mlops engineer",
        "data engineer", "research scientist", "analyst", "other"
    ] = "other"
    years_exp_min: Optional[int] = None
    years_exp_max: Optional[int] = None
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: Optional[Literal["CAD", "USD"]] = None
    visa_sponsorship: Literal["yes", "no", "unknown"] = "unknown"
    red_flags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompt builder (also used by eval.py for token estimation)
# ---------------------------------------------------------------------------

def build_enrichment_prompt(job: dict[str, Any], simplified: bool = False) -> str:
    """Build the user message for the enrichment LLM call."""
    description = (job.get("description") or "").strip()
    if len(description) > 3000:
        description = description[:3000] + "...[truncated]"

    schema = _SIMPLIFIED_SCHEMA_DESCRIPTION if simplified else _SCHEMA_DESCRIPTION

    return (
        f"Extract structured data from this job posting. Return ONLY the JSON object.\n\n"
        f"Title: {job.get('title', '')}\n"
        f"Company: {job.get('company', '')}\n"
        f"Location: {job.get('location', '')}\n"
        f"Description:\n{description}\n\n"
        f"Return JSON matching this schema:\n{schema}"
    )


# ---------------------------------------------------------------------------
# LangChain / LLM helpers
# ---------------------------------------------------------------------------

def _is_rate_limit(e: Exception) -> bool:
    """Return True if the exception signals a rate limit (HTTP 429)."""
    msg = str(e).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg


def _invoke_with_retry(chain, messages, max_retries: int = 4, base_delay: float = 5.0):
    """Invoke a LangChain chain with exponential backoff on rate limit errors.

    Delays: 5s, 10s, 20s, 40s (base_delay * 2^attempt).
    Non-rate-limit errors are re-raised immediately on the first occurrence.
    """
    for attempt in range(max_retries):
        try:
            return chain.invoke(messages)
        except Exception as e:
            if _is_rate_limit(e) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Rate limit (attempt %d/%d), retrying in %.0fs: %s",
                    attempt + 1, max_retries, delay, e,
                )
                time.sleep(delay)
            else:
                raise


def _make_chain(api_key: str, model: str):
    """Create a LangChain structured-output chain for JobEnrichment."""
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=_OPENROUTER_BASE_URL,
        temperature=0,
    )
    return llm.with_structured_output(JobEnrichment)


def _enrichment_to_dict(enrichment: JobEnrichment, url: str, model: str, now: str) -> dict[str, Any]:
    """Convert a validated JobEnrichment to a flat dict ready for DB storage."""
    result = enrichment.model_dump()
    # Serialize list fields to JSON strings for SQLite TEXT columns
    for field in ("must_have_skills", "nice_to_have_skills", "tech_stack", "red_flags"):
        if isinstance(result.get(field), list):
            result[field] = json.dumps(result[field])
    result["url"] = url
    result["enriched_at"] = now
    result["enrichment_status"] = "ok"
    result["enrichment_model"] = model
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enrich_one_job(job: dict[str, Any], api_key: str, model: str) -> dict[str, Any]:
    """
    Enrich a single job with LLM-extracted metadata.
    Always returns a complete dict with enrichment_status set.
    Never raises.
    """
    url = job.get("url", "")
    now = datetime.now(timezone.utc).isoformat()

    if not (job.get("description") or "").strip():
        return {
            "url": url,
            "enriched_at": now,
            "enrichment_status": "skipped",
            "enrichment_model": model,
        }

    chain = _make_chain(api_key, model)

    # First attempt: full schema
    try:
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=build_enrichment_prompt(job, simplified=False)),
        ]
        enrichment: JobEnrichment = _invoke_with_retry(chain, messages)
        return _enrichment_to_dict(enrichment, url, model, now)
    except Exception as e:
        logger.warning("First enrichment attempt failed for %s: %s", url, e)

    # Second attempt: simplified schema (shorter prompt, fewer fields)
    try:
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=build_enrichment_prompt(job, simplified=True)),
        ]
        enrichment = _invoke_with_retry(chain, messages)
        return _enrichment_to_dict(enrichment, url, model, now)
    except Exception as e:
        logger.error("Second enrichment attempt failed for %s: %s", url, e)

    return {
        "url": url,
        "enriched_at": now,
        "enrichment_status": "failed",
        "enrichment_model": model,
    }


def run_enrichment_pipeline(
    jobs: list[dict[str, Any]],
    conn: Any,
    api_key: str,
    model: str,
    console: Any,
) -> None:
    """Enrich jobs concurrently via OpenRouter, saving each result to DB."""
    if not jobs:
        return

    ok_count = 0
    failed_count = 0
    skipped_count = 0

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(enrich_one_job, job, api_key, model): job
            for job in jobs
        }
        for future in as_completed(futures):
            result = future.result()
            url = result.get("url", "")
            status = result.get("enrichment_status", "failed")
            if status == "ok":
                ok_count += 1
            elif status == "skipped":
                skipped_count += 1
            else:
                failed_count += 1
            if url:
                save_enrichment(conn, url, result)

    if console:
        console.print(
            f"  [bold]Enrichment:[/bold] "
            f"[green]{ok_count} ok[/green], "
            f"[red]{failed_count} failed[/red], "
            f"[dim]{skipped_count} skipped[/dim]"
        )
