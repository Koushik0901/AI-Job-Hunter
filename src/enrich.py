"""
enrich.py — LLM enrichment pipeline via OpenRouter.

Extracts structured metadata from job descriptions using a cheap LLM.
Uses LangChain (ChatOpenAI) for API calls and Pydantic for output validation.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import warnings
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, field_validator

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
    "You are a structured data extraction engine for job postings. "
    "Output exactly one JSON object — starting with { and ending with }. "
    "Zero text, markdown fences, or explanation before or after the JSON. "
    "Extract only facts explicitly stated. Never invent information. "
    "Use null for any missing scalar field. Use [] for any missing list field."
)

_SCHEMA_DESCRIPTION = """\
===OUTPUT SCHEMA===
Output ONLY the following JSON object — exactly these 13 keys, no extra keys, no markdown fences, no text before or after:
{
  "work_mode":        "remote" | "hybrid" | "onsite" | null,
  "remote_geo":       string or null,
  "canada_eligible":  "yes" | "no" | "unknown",
  "seniority":        "intern" | "junior" | "mid" | "senior" | "staff" | "principal" | null,
  "role_family":      "data scientist" | "ml engineer" | "mlops engineer" | "data engineer" | "research scientist" | "analyst" | "other",
  "years_exp_min":    integer or null,
  "years_exp_max":    integer or null,
  "required_skills":  ["string", ...],
  "preferred_skills": ["string", ...],
  "salary_min":       integer or null,
  "salary_max":       integer or null,
  "salary_currency":  "CAD" | "USD" | null,
  "visa_sponsorship": "yes" | "no" | "unknown",
  "red_flags":        ["string", ...]
}
===END SCHEMA===

FIELD RULES

canada_eligible — can the candidate work from Canada?
  "yes"     → remote (worldwide / North America / Canada mentioned), or Canadian office
              e.g. "Remote — North America" → "yes" | "Toronto, ON" → "yes" | "Remote, Canada OK" → "yes"
  "no"      → US work authorization required, US citizenship/residency required, or US-only office
              e.g. "must be authorized to work in the US" → "no" | "Remote — United States only" → "no"
  "unknown" → work location / authorization requirements not mentioned

years_exp — integers only, examples:
  "3+ years experience"   → min=3, max=null
  "3 to 5 years"          → min=3, max=5
  "up to 2 years"         → min=null, max=2

salary — always FULL DOLLAR AMOUNTS (not abbreviated):
  "$150k–$200k"           → min=150000, max=200000, currency="USD"
  "$120,000 CAD annually" → min=120000, max=null,   currency="CAD"
  Not mentioned           → min=null, max=null, currency=null

required_skills — ALL skills/tools/languages/certifications listed as required.
  Sections: "Requirements", "Qualifications", "Must Have", "Basic Qualifications", "You Will Need"
  Include: languages, frameworks, tools, degrees, certifications, methodologies.

preferred_skills — skills listed as optional/desirable.
  Sections: "Nice to Have", "Preferred", "Bonus", "Plus", "Preferred Qualifications"
  If no such section exists → []

red_flags — copy word-for-word (do NOT paraphrase) phrases signalling Canada-ineligibility:
  e.g. "must be authorized to work in the US", "US citizenship required",
       "does not offer visa sponsorship", "security clearance required"
  If none → []

visa_sponsorship:
  "yes"     → sponsorship explicitly offered
  "no"      → explicitly declined ("does not sponsor", "cannot sponsor", "no sponsorship")
  "unknown" → not mentioned

role_family — pick the single closest match:
  "data scientist"      → statistical modelling, ML experiments, predictions
  "ml engineer"         → building / deploying ML models and ML systems
  "mlops engineer"      → ML infrastructure, pipelines, model serving
  "data engineer"       → ETL, data pipelines, data warehousing
  "research scientist"  → academic-style research, novel algorithms, publications
  "analyst"             → BI dashboards, SQL analysis, business reporting
  "other"               → none of the above applies

===ONE-SHOT EXAMPLE (reference only — do NOT extract this posting)===

Posting:
  ML Engineer II — Remote (United States Only) | Acme AI
  Requirements: Bachelor's in CS or equivalent; 3-5 years Python; PyTorch or TensorFlow; REST APIs.
  Nice to Have: Kubernetes, MLflow.
  Compensation: $140,000-$180,000 USD/year.
  Candidates must be authorized to work in the United States. We do not offer visa sponsorship.

Expected output:
  {
    "work_mode": "remote",
    "remote_geo": "United States only",
    "canada_eligible": "no",
    "seniority": "mid",
    "role_family": "ml engineer",
    "years_exp_min": 3,
    "years_exp_max": 5,
    "required_skills": ["Bachelor's in CS or equivalent", "Python", "PyTorch", "TensorFlow", "REST APIs"],
    "preferred_skills": ["Kubernetes", "MLflow"],
    "salary_min": 140000,
    "salary_max": 180000,
    "salary_currency": "USD",
    "visa_sponsorship": "no",
    "red_flags": ["must be authorized to work in the United States", "We do not offer visa sponsorship"]
  }

===END EXAMPLE==="""




# ---------------------------------------------------------------------------
# Pydantic output schema
# ---------------------------------------------------------------------------

class JobEnrichment(BaseModel):
    """Structured metadata extracted from a job posting."""
    work_mode: Optional[Literal["remote", "hybrid", "onsite"]] = Field(
        default=None, description="How the role is delivered: remote, hybrid, or onsite"
    )
    remote_geo: Optional[str] = Field(
        default=None,
        description="Geographic scope of remote work (e.g. 'North America', 'US only', 'Worldwide'). Null if not remote or not specified.",
    )
    canada_eligible: Literal["yes", "no", "unknown"] = Field(
        default="unknown",
        description=(
            "Can the candidate work from Canada? "
            "yes=remote-friendly (worldwide/North America/Canada) or Canadian office; "
            "no=US work authorization required, US citizenship/residency required, or US-only office; "
            "unknown=work location or authorization requirements not mentioned"
        ),
    )
    seniority: Optional[Literal["intern", "junior", "mid", "senior", "staff", "principal"]] = Field(
        default=None, description="Career level inferred from title and requirements"
    )
    role_family: Literal[
        "data scientist", "ml engineer", "mlops engineer",
        "data engineer", "research scientist", "analyst", "other"
    ] = Field(
        default="other",
        description=(
            "Primary job category. "
            "data scientist=modelling/experiments; ml engineer=building/deploying ML systems; "
            "mlops engineer=ML infra/pipelines; data engineer=ETL/warehousing; "
            "research scientist=academic research/novel algorithms; analyst=BI/SQL/dashboards"
        ),
    )
    years_exp_min: Optional[int] = Field(
        default=None, description="Minimum years of experience required (integer). '3+ years' → 3. Null if not stated."
    )
    years_exp_max: Optional[int] = Field(
        default=None, description="Maximum years of experience mentioned (integer). '3-5 years' → 5. Null if open-ended or not stated."
    )
    required_skills: list[str] = Field(
        default_factory=list,
        description=(
            "ALL skills, tools, languages, frameworks, degrees, and certifications listed as required or mandatory. "
            "Look in sections labelled: Requirements, Qualifications, Must Have, Basic Qualifications, You Will Need."
        ),
    )
    preferred_skills: list[str] = Field(
        default_factory=list,
        description=(
            "Skills listed as optional or desirable. "
            "Look in sections labelled: Nice to Have, Preferred, Bonus, Plus, Preferred Qualifications. "
            "Return empty list [] if no such section exists."
        ),
    )
    salary_min: Optional[int] = Field(
        default=None, description="Minimum annual salary in FULL DOLLARS (e.g. 150000, NOT 150 or 150k). Null if not stated."
    )
    salary_max: Optional[int] = Field(
        default=None, description="Maximum annual salary in FULL DOLLARS (e.g. 200000, NOT 200 or 200k). Null if not stated."
    )
    salary_currency: Optional[Literal["CAD", "USD"]] = Field(
        default=None, description="Currency of the stated salary. Null if salary not mentioned."
    )
    visa_sponsorship: Literal["yes", "no", "unknown"] = Field(
        default="unknown",
        description=(
            "Visa sponsorship availability. "
            "yes=explicitly offered; "
            "no=explicitly declined ('does not sponsor', 'cannot sponsor', 'no sponsorship'); "
            "unknown=not mentioned"
        ),
    )
    red_flags: list[str] = Field(
        default_factory=list,
        description=(
            "Exact phrases from the posting signalling Canada-ineligibility. "
            "Examples: 'must be authorized to work in the US', 'US citizenship required', "
            "'does not offer visa sponsorship', 'security clearance required', 'must be based in [US city]'. "
            "Return empty list [] if none found."
        ),
    )

    @field_validator("required_skills", "preferred_skills", "red_flags", mode="before")
    @classmethod
    def _coerce_none_to_list(cls, v):
        """Some models return null instead of [] for list fields — treat as empty."""
        return v if v is not None else []

    @field_validator("work_mode", mode="before")
    @classmethod
    def _coerce_work_mode(cls, v):
        return v if v in ("remote", "hybrid", "onsite") else None

    @field_validator("canada_eligible", mode="before")
    @classmethod
    def _coerce_canada_eligible(cls, v):
        return v if v in ("yes", "no", "unknown") else "unknown"

    @field_validator("seniority", mode="before")
    @classmethod
    def _coerce_seniority(cls, v):
        return v if v in ("intern", "junior", "mid", "senior", "staff", "principal") else None

    @field_validator("visa_sponsorship", mode="before")
    @classmethod
    def _coerce_visa_sponsorship(cls, v):
        return v if v in ("yes", "no", "unknown") else "unknown"

    @field_validator("salary_currency", mode="before")
    @classmethod
    def _coerce_salary_currency(cls, v):
        return v if v in ("CAD", "USD") else None


# ---------------------------------------------------------------------------
# Prompt builder (also used by eval.py for token estimation)
# ---------------------------------------------------------------------------

def build_enrichment_prompt(job: dict[str, Any]) -> str:
    """Build the user message for the enrichment LLM call."""
    description = (job.get("description") or "").strip()
    title = job.get("title", "")
    company = job.get("company", "")
    return (
        f"Extract structured metadata from the job posting below.\n\n"
        f"TITLE:    {title}\n"
        f"COMPANY:  {company}\n"
        f"LOCATION: {job.get('location', '')}\n\n"
        f"DESCRIPTION:\n{description}\n\n"
        f"{_SCHEMA_DESCRIPTION}\n\n"
        f"Now extract the JSON for the posting above (TITLE: {title} / COMPANY: {company}).\n"
        f"Your response must start with {{ and end with }}. No markdown fences. No explanation."
    )


# ---------------------------------------------------------------------------
# LangChain / LLM helpers
# ---------------------------------------------------------------------------

_MAX_PROVIDER_RETRIES = 3   # retries with successively more providers ignored

# Patterns to extract the rate-limiting provider name from OpenRouter error messages.
# OpenRouter typically surfaces the provider name as: "Provider Crusoe returned error: 429"
# or in JSON as: "provider_name": "Crusoe"
_PROVIDER_EXTRACT_RE = [
    re.compile(r'Provider\s+([A-Za-z][A-Za-z0-9_\-]+)\s+returned', re.IGNORECASE),
    re.compile(r'"provider_name":\s*"([^"]+)"', re.IGNORECASE),
]
_PROVIDER_NAME_SKIP = frozenset((
    "provider", "error", "openrouter", "upstream",
    "the", "a", "an", "code", "status", "http", "api", "model",
))


class RateLimitSignal(Exception):
    """Raised when all provider retries are exhausted, to pause the pipeline."""


def _is_rate_limit(e: Exception) -> bool:
    """Return True if the exception signals a rate limit (HTTP 429)."""
    msg = str(e).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg


def _extract_rate_limited_provider(e: Exception) -> str | None:
    """Try to extract the provider name from an OpenRouter rate-limit error message."""
    msg = str(e)
    for pat in _PROVIDER_EXTRACT_RE:
        m = pat.search(msg)
        if m:
            name = m.group(1).strip()
            if name.lower() not in _PROVIDER_NAME_SKIP and len(name) > 1:
                return name
    return None


def _invoke_once(chain, messages):
    """Invoke a LangChain chain once, returning the result or raising the original exception."""
    return chain.invoke(messages)


def _make_chain(
    api_key: str,
    model: str,
    provider_order: list[str] | None = None,
    ignore_providers: list[str] | None = None,
    sort_by: str | None = None,
):
    """Create a LangChain structured-output chain for JobEnrichment.

    provider_order: OpenRouter provider preference order (e.g. ["DeepInfra"]).
    ignore_providers: providers to exclude for this request (e.g. ["Crusoe"] after a 429).
    sort_by: OpenRouter sort strategy ("throughput" | "latency" | "price") used when the
             offending provider is unknown, to encourage routing to a different one.
    All map to OpenRouter's `provider` request field. extra_body is passed as a direct
    kwarg (not inside model_kwargs) to avoid LangChain's UserWarning.
    """
    provider_cfg: dict = {}
    if provider_order:
        provider_cfg["order"] = provider_order
    if ignore_providers:
        provider_cfg["ignore"] = ignore_providers
    if sort_by:
        provider_cfg["sort"] = sort_by
    if provider_cfg:
        provider_cfg["allow_fallbacks"] = True

    extra: dict = {}
    if provider_cfg:
        extra["extra_body"] = {"provider": provider_cfg}

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=_OPENROUTER_BASE_URL,
        temperature=0,
        **extra,
    )
    return llm.with_structured_output(JobEnrichment)


def _enrichment_to_dict(enrichment: JobEnrichment, url: str, model: str, now: str) -> dict[str, Any]:
    """Convert a validated JobEnrichment to a flat dict ready for DB storage."""
    result = enrichment.model_dump()
    # Serialize list fields to JSON strings for SQLite TEXT columns
    for field in ("required_skills", "preferred_skills", "red_flags"):
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

def enrich_one_job(
    job: dict[str, Any],
    api_key: str,
    model: str,
    stop_event: threading.Event | None = None,
    provider_order: list[str] | None = None,
) -> dict[str, Any]:
    """
    Enrich a single job with LLM-extracted metadata.

    On HTTP 429, automatically retries up to _MAX_PROVIDER_RETRIES times using
    OpenRouter's `provider.ignore` field to exclude the rate-limiting provider and
    let OpenRouter route to any other available provider for this model.

    Only raises RateLimitSignal when all retries are exhausted — the caller then
    stops the pipeline and saves a checkpoint so --enrich-backfill can resume.
    All other errors are caught and returned as enrichment_status="failed".
    """
    url = job.get("url", "")
    now = datetime.now(timezone.utc).isoformat()

    if stop_event is not None and stop_event.is_set():
        raise RateLimitSignal("pipeline paused")

    if not (job.get("description") or "").strip():
        return {
            "url": url,
            "enriched_at": now,
            "enrichment_status": "skipped",
            "enrichment_model": model,
        }

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=build_enrichment_prompt(job)),
    ]
    ignored_providers: list[str] = []
    sort_by: str | None = None

    for attempt in range(_MAX_PROVIDER_RETRIES + 1):
        if stop_event is not None and stop_event.is_set():
            raise RateLimitSignal("pipeline paused")

        chain = _make_chain(
            api_key, model,
            provider_order=provider_order,
            ignore_providers=ignored_providers or None,
            sort_by=sort_by,
        )
        try:
            enrichment: JobEnrichment = _invoke_once(chain, messages)
            return _enrichment_to_dict(enrichment, url, model, now)
        except Exception as e:
            if not _is_rate_limit(e):
                logger.error("Enrichment failed for %s: %s", url, e)
                return {
                    "url": url,
                    "enriched_at": now,
                    "enrichment_status": "failed",
                    "enrichment_model": model,
                }
            # Rate limit — try to identify and exclude the offending provider
            if attempt < _MAX_PROVIDER_RETRIES:
                provider = _extract_rate_limited_provider(e)
                if provider and provider not in ignored_providers:
                    logger.warning(
                        "Rate limited by provider '%s' for %s — retrying with it excluded "
                        "(attempt %d/%d)", provider, url, attempt + 1, _MAX_PROVIDER_RETRIES,
                    )
                    ignored_providers.append(provider)
                else:
                    # Provider unknown — ask OpenRouter to sort by throughput so it
                    # prefers a less-loaded provider instead of the same rate-limited one
                    sort_by = "throughput"
                    logger.warning(
                        "Rate limited (provider unknown) for %s — retry %d/%d with throughput sort",
                        url, attempt + 1, _MAX_PROVIDER_RETRIES,
                    )
                continue

            # All retries exhausted — raise to stop the pipeline
            raise RateLimitSignal(str(e)) from e


def run_enrichment_pipeline(
    jobs: list[dict[str, Any]],
    conn: Any,
    api_key: str,
    model: str,
    console: Any,
) -> None:
    """Enrich jobs concurrently via OpenRouter, saving each result to DB.

    On HTTP 429, stops immediately and leaves remaining jobs as unenriched (NULL)
    so --enrich-backfill can resume from the exact checkpoint.
    """
    if not jobs:
        return

    ok_count = 0
    failed_count = 0
    skipped_count = 0
    paused_count = 0
    stop_event = threading.Event()

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(enrich_one_job, job, api_key, model, stop_event): job
            for job in jobs
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except RateLimitSignal:
                paused_count += 1
                if not stop_event.is_set():
                    stop_event.set()
                    # Cancel futures that haven't started yet
                    for f in futures:
                        f.cancel()
                continue  # do NOT save — job stays NULL, picked up by --enrich-backfill
            except CancelledError:
                paused_count += 1
                continue  # cancelled by stop_event — stays NULL
            except Exception as e:
                logger.error("Unexpected error from future: %s", e)
                continue

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
        if stop_event.is_set():
            console.print(
                f"\n[bold yellow]Enrichment paused — rate limit hit.[/bold yellow]\n"
                f"  [green]{ok_count} enriched[/green] before pause, "
                f"[dim]{paused_count} job(s) left unenriched[/dim].\n"
                f"  Resume anytime with: "
                f"[bold]uv run python src/scrape.py --enrich-backfill[/bold]"
            )
        else:
            console.print(
                f"  [bold]Enrichment:[/bold] "
                f"[green]{ok_count} ok[/green], "
                f"[red]{failed_count} failed[/red], "
                f"[dim]{skipped_count} skipped[/dim]"
            )
