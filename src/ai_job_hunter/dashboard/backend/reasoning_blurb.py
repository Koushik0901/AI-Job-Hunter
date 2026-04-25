"""
reasoning_blurb.py — LLM-generated one-sentence "Kenji's read" blurbs per job.

Produces a short, editorial sentence (≤220 chars) that names a concrete thing in the
JD and ties it to the user's profile (or flags a concrete gap). Stored on
job_match_scores.reasoning_blurb keyed by (job_id, profile_version), so blurbs
invalidate on score_version bump.

Generation is gated to the top-N viable unapplied jobs to control cost. Call
`generate_blurbs(conn, job_ids, force=False)` to populate/refresh.

Voice: second person ("you"/"your"), one sentence, no clichés, no markdown, no
emoji. The output replaces the deterministic `guidance_summary` from advisor.py
on the Discover cards; if the LLM returns something invalid the column stays
NULL and the old deterministic text shows through.
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_SLM_MODEL = "google/gemma-4-31b-it"
_MAX_BLURB_CHARS = 260  # tolerate a little over the 220 target before rejecting
_MIN_BLURB_CHARS = 30
_MAX_CONCURRENCY = 4
_TOP_N_DEFAULT = 150
_ELIGIBLE_BANDS = {"top_band", "strong", "viable"}
_FORBIDDEN_LEAD_INS = (
    "this role",
    "this job",
    "this position",
    "based on your",
    "as an",
    "here's",
    "i think",
    "i recommend",
)
_SYSTEM_PROMPT = """You write one-sentence editorial take-aways for a job-search dashboard called Kenji.

RULES (all mandatory):
- Output exactly ONE sentence. No bullets, no lists, no markdown, no quotes, no emoji.
- Maximum 220 characters including spaces.
- Second person: refer to the reader as "you"/"your".
- Must name at least ONE concrete thing from the JD (a specific tech, tool, domain, scope, or responsibility) AND connect it to something specific in the reader's profile — OR flag a concrete, named gap.
- Never open with "This role", "This job", "This position", "Based on your profile", "As a", "As an", "Here's", "I think", "I recommend". Start with the subject of interest.
- If the match is weak, say exactly why (the named gap) — do not hedge with "mixed signals" or "worth a review".
- No trailing fluff like "could be a great fit" or "worth exploring".

Examples of good output:
- "The stack leans on LangGraph, Pinecone, and eval tooling, which maps directly onto your Elecsys agent work and your Qdrant familiarity."
- "They want 7+ years in risk modelling; you're at 4 and outside financial services, so the seniority and domain gap will fight you."
- "Heavy Snowflake + dbt + Airflow focus matches your analytics pipeline experience, and the remote-Canada posture fits your stated intent."

Output only the sentence. No preamble."""


def _build_slm() -> Any:
    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    model = (os.getenv("SLM_MODEL") or _DEFAULT_SLM_MODEL).strip()
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("langchain-openai is required. Run: uv add langchain-openai") from exc
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=_OPENROUTER_BASE_URL,
        temperature=0.4,
        max_tokens=140,
    )


def _call_slm(llm: Any, user_prompt: str) -> str:
    from langchain_core.messages import HumanMessage, SystemMessage

    response = llm.invoke(
        [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
    )
    return str(getattr(response, "content", "") or "").strip()


def _parse_json_list(val: Any) -> list[Any]:
    if not val:
        return []
    if isinstance(val, list):
        return val
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _load_profile_snippet(conn: Any) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT years_experience, skills, desired_job_titles,
               narrative_intent, preferred_work_mode, education, degree
        FROM candidate_profile WHERE id = 1
        """
    ).fetchone()
    if not row:
        return {}
    education = _parse_json_list(row[5])
    degrees = [
        str(entry.get("degree", "")).strip()
        for entry in education
        if isinstance(entry, dict) and entry.get("degree")
    ]
    if not degrees and row[6]:
        degrees = [str(row[6]).strip()]
    return {
        "years_experience": row[0] or 0,
        "seniority_level": "",
        "skills": _parse_json_list(row[1])[:18],
        "desired_job_titles": _parse_json_list(row[2])[:6],
        "narrative_intent": (row[3] or "").strip()[:500],
        "preferred_work_mode": (row[4] or "").strip(),
        "degrees": degrees[:3],
    }


def _load_job_score_row(conn: Any, job_id: str, profile_version: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT j.id, j.title, j.company, j.location,
               e.work_mode, e.seniority, e.role_family,
               e.years_exp_min, e.years_exp_max,
               e.required_skills, e.preferred_skills,
               e.formatted_description, j.description,
               e.salary_min, e.salary_max, e.salary_currency,
               ms.score, ms.band, ms.reasons_json, ms.breakdown_json,
               ms.reasoning_blurb
        FROM jobs j
        LEFT JOIN job_enrichments e ON e.job_id = j.id
        LEFT JOIN job_match_scores ms ON ms.job_id = j.id AND ms.profile_version = ?
        WHERE j.id = ?
        """,
        (profile_version, job_id),
    ).fetchone()
    if not row:
        return None
    description = row[11] or row[12] or ""
    try:
        reasons = json.loads(row[18]) if row[18] else []
    except Exception:
        reasons = []
    try:
        breakdown = json.loads(row[19]) if row[19] else {}
    except Exception:
        breakdown = {}
    return {
        "id": str(row[0] or ""),
        "title": (row[1] or "").strip(),
        "company": (row[2] or "").strip(),
        "location": (row[3] or "").strip(),
        "work_mode": (row[4] or "").strip(),
        "seniority": (row[5] or "").strip(),
        "role_family": (row[6] or "").strip(),
        "years_exp_min": row[7],
        "years_exp_max": row[8],
        "required_skills": _parse_json_list(row[9])[:8],
        "preferred_skills": _parse_json_list(row[10])[:6],
        "description": str(description)[:1600],
        "salary_min": row[13],
        "salary_max": row[14],
        "salary_currency": (row[15] or "").strip(),
        "match_score": int(row[16]) if isinstance(row[16], (int, float)) else None,
        "band": (row[17] or "").strip(),
        "reasons": list(reasons)[:4] if isinstance(reasons, list) else [],
        "breakdown": breakdown if isinstance(breakdown, dict) else {},
        "existing_blurb": (row[20] or "").strip() or None,
    }


def _compose_user_prompt(job: dict[str, Any], profile: dict[str, Any]) -> str:
    sal = ""
    if job.get("salary_min") or job.get("salary_max"):
        cur = job.get("salary_currency") or ""
        lo = job.get("salary_min") or "?"
        hi = job.get("salary_max") or "?"
        sal = f"\nSalary: {cur} {lo}–{hi}".strip()

    yrs = ""
    if job.get("years_exp_min") is not None or job.get("years_exp_max") is not None:
        lo = job.get("years_exp_min")
        hi = job.get("years_exp_max")
        yrs = f"\nExperience asked: {lo if lo is not None else '?'}–{hi if hi is not None else '?'} yrs"

    reasons_str = "\n".join(f"- {r}" for r in job.get("reasons", []) if r) or "- (none)"
    profile_skills = ", ".join(profile.get("skills", [])[:14]) or "(unspecified)"
    profile_titles = ", ".join(profile.get("desired_job_titles", [])) or "(unspecified)"
    narrative = profile.get("narrative_intent") or "(not set)"

    return (
        f"JOB\n"
        f"Title: {job.get('title','')}\n"
        f"Company: {job.get('company','')}\n"
        f"Location: {job.get('location','')}  work_mode: {job.get('work_mode','')}\n"
        f"Role family: {job.get('role_family','')}  seniority: {job.get('seniority','')}{yrs}{sal}\n"
        f"Required skills: {', '.join(job.get('required_skills', [])) or '(none listed)'}\n"
        f"Preferred skills: {', '.join(job.get('preferred_skills', [])) or '(none listed)'}\n"
        f"Description (truncated):\n{job.get('description','').strip()}\n"
        f"\nCANDIDATE\n"
        f"Years experience: {profile.get('years_experience', 0)}  seniority: {profile.get('seniority_level','')}\n"
        f"Desired titles: {profile_titles}\n"
        f"Skills: {profile_skills}\n"
        f"Work-mode pref: {profile.get('preferred_work_mode','')}\n"
        f"Degrees: {', '.join(profile.get('degrees', [])) or '(unspecified)'}\n"
        f"Narrative intent: {narrative}\n"
        f"\nSCORE CONTEXT\n"
        f"Match score: {job.get('match_score')}  band: {job.get('band')}\n"
        f"Top reasons:\n{reasons_str}\n"
        f"\nWrite the one-sentence take-away now."
    )


def _validate_blurb(raw: str) -> str | None:
    text = (raw or "").strip().strip('"').strip("'")
    # Drop surrounding code fences / markdown if any slipped through.
    if text.startswith("```"):
        text = text.strip("`").strip()
    # Collapse multi-line outputs to first non-empty sentence.
    text = " ".join(text.split())
    if not text:
        return None
    if len(text) < _MIN_BLURB_CHARS:
        return None
    if len(text) > _MAX_BLURB_CHARS:
        return None
    lowered = text.lower()
    for bad in _FORBIDDEN_LEAD_INS:
        if lowered.startswith(bad):
            return None
    # Reject if output looks like multiple sentences of generic fluff (heuristic:
    # too many periods implies paragraph, not one tight sentence).
    if text.count(".") > 3:
        return None
    return text


def _current_profile_version(conn: Any) -> int:
    row = conn.execute(
        "SELECT score_version FROM candidate_profile WHERE id = 1"
    ).fetchone()
    if not row:
        return 1
    try:
        return int(row[0] or 1)
    except Exception:
        return 1


def _eligible_top_job_ids(conn: Any, profile_version: int, limit: int) -> list[str]:
    """Return top-N unapplied, non-suppressed job ids by score, in viable bands."""
    placeholders = ",".join("?" for _ in _ELIGIBLE_BANDS)
    rows = conn.execute(
        f"""
        SELECT ms.job_id
        FROM job_match_scores ms
        JOIN jobs j ON j.id = ms.job_id
        LEFT JOIN job_tracking t ON t.job_id = j.id
        LEFT JOIN job_suppressions s ON s.job_id = j.id
        WHERE ms.profile_version = ?
          AND ms.band IN ({placeholders})
          AND COALESCE(t.status, j.application_status, 'not_applied') = 'not_applied'
          AND s.job_id IS NULL
        ORDER BY ms.score DESC
        LIMIT ?
        """,
        (profile_version, *_ELIGIBLE_BANDS, limit),
    ).fetchall()
    return [str(r[0]) for r in rows if r and r[0]]


def _write_blurb(conn: Any, job_id: str, profile_version: int, blurb: str | None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE job_match_scores
        SET reasoning_blurb = ?, reasoning_blurb_at = ?
        WHERE job_id = ? AND profile_version = ?
        """,
        (blurb, now if blurb else None, job_id, profile_version),
    )


def generate_blurbs(
    conn: Any,
    job_ids: list[str] | None = None,
    *,
    force: bool = False,
    top_n: int = _TOP_N_DEFAULT,
) -> dict[str, str]:
    """Generate LLM blurbs for the given job_ids (or the top-N viable unapplied if None).

    Returns a map of job_id -> blurb for successful generations. Failures are
    silently skipped (column stays at its previous value, or NULL).

    Safe to call without OPENROUTER_API_KEY — returns {} and logs a warning.
    """
    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        logger.warning("reasoning_blurb: OPENROUTER_API_KEY not set, skipping")
        return {}

    profile_version = _current_profile_version(conn)
    profile = _load_profile_snippet(conn)
    if not profile:
        logger.warning("reasoning_blurb: no candidate_profile row, skipping")
        return {}

    if job_ids is None:
        job_ids = _eligible_top_job_ids(conn, profile_version, top_n)
    job_ids = [jid for jid in (job_ids or []) if str(jid).strip()]
    if not job_ids:
        return {}

    # Load rows, drop ones already blurbed (unless force).
    work: list[dict[str, Any]] = []
    for jid in job_ids:
        row = _load_job_score_row(conn, jid, profile_version)
        if not row:
            continue
        if row.get("match_score") is None:
            continue
        if not force and row.get("existing_blurb"):
            continue
        work.append(row)

    if not work:
        return {}

    try:
        llm = _build_slm()
    except Exception as exc:
        logger.warning("reasoning_blurb: could not build SLM client: %s", exc)
        return {}

    results: dict[str, str] = {}

    def _one(job: dict[str, Any]) -> tuple[str, str | None]:
        try:
            prompt = _compose_user_prompt(job, profile)
            raw = _call_slm(llm, prompt)
            return job["id"], _validate_blurb(raw)
        except Exception as exc:
            logger.info("reasoning_blurb: generation failed for %s: %s", job.get("id"), exc)
            return job["id"], None

    with ThreadPoolExecutor(max_workers=_MAX_CONCURRENCY) as pool:
        futures = [pool.submit(_one, job) for job in work]
        for fut in as_completed(futures):
            try:
                job_id, blurb = fut.result()
            except Exception as exc:
                logger.info("reasoning_blurb: future failed: %s", exc)
                continue
            if not blurb:
                continue
            try:
                _write_blurb(conn, job_id, profile_version, blurb)
                conn.commit()
            except Exception as exc:
                logger.warning(
                    "reasoning_blurb: failed to persist blurb for %s: %s", job_id, exc
                )
                continue
            # Only count as "written" after the write + commit succeed.
            results[job_id] = blurb

    logger.info(
        "reasoning_blurb: generated %d blurbs (of %d candidates)",
        len(results),
        len(work),
    )
    return results
