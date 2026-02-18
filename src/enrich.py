"""
enrich.py — LLM enrichment pipeline via OpenRouter.

Extracts structured metadata from job descriptions using a cheap LLM.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import requests

from db import save_enrichment

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a precise structured data extractor. "
    "Return ONLY valid JSON, no explanation. "
    "Use null for fields not mentioned. Never invent information."
)

_SCHEMA_DESCRIPTION = """\
{
  "work_mode":           "remote" | "hybrid" | "onsite" | null,
  "remote_geo":          string | null,
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
}"""

_SIMPLIFIED_SCHEMA_DESCRIPTION = """\
{
  "work_mode":        "remote" | "hybrid" | "onsite" | null,
  "seniority":        "intern" | "junior" | "mid" | "senior" | "staff" | "principal" | null,
  "role_family":      "data scientist" | "ml engineer" | "mlops engineer" | "data engineer" | "research scientist" | "analyst" | "other",
  "visa_sponsorship": "yes" | "no" | "unknown",
  "must_have_skills": [strings],
  "tech_stack":       [strings]
}"""


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


def call_openrouter(prompt: str, api_key: str, model: str) -> dict[str, Any]:
    """POST to OpenRouter chat completions. Returns parsed JSON dict or raises ValueError."""
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        lines = content.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)

    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse failed: {e}\nRaw content: {content[:200]}") from e

    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object, got {type(result).__name__}")

    return result


def enrich_one_job(job: dict[str, Any], api_key: str, model: str) -> dict[str, Any]:
    """
    Enrich a single job with LLM-extracted metadata.
    Always returns a complete dict with enrichment_status set.
    Never raises.
    """
    url = job.get("url", "")
    now = datetime.now(timezone.utc).isoformat()

    # Skip jobs with no description
    if not (job.get("description") or "").strip():
        return {
            "url": url,
            "enriched_at": now,
            "enrichment_status": "skipped",
            "enrichment_model": model,
        }

    # First attempt: full schema
    try:
        prompt = build_enrichment_prompt(job, simplified=False)
        result = call_openrouter(prompt, api_key, model)
        result["url"] = url
        result["enriched_at"] = now
        result["enrichment_status"] = "ok"
        result["enrichment_model"] = model
        # Serialize list fields to JSON strings for storage
        for field in ("must_have_skills", "nice_to_have_skills", "tech_stack", "red_flags"):
            if isinstance(result.get(field), list):
                result[field] = json.dumps(result[field])
        return result
    except Exception as e:
        logger.warning("First enrichment attempt failed for %s: %s", url, e)

    # Second attempt: simplified schema
    try:
        prompt = build_enrichment_prompt(job, simplified=True)
        result = call_openrouter(prompt, api_key, model)
        result["url"] = url
        result["enriched_at"] = now
        result["enrichment_status"] = "ok"
        result["enrichment_model"] = model
        for field in ("must_have_skills", "nice_to_have_skills", "tech_stack", "red_flags"):
            if isinstance(result.get(field), list):
                result[field] = json.dumps(result[field])
        return result
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
