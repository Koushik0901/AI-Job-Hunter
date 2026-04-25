"""
LangChain tool definitions for the AI Job Hunter agent.

Each tool is created via a factory that closes over the DB connection,
keeping the tool functions pure (no global state).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_agent_tools(conn: Any) -> list:
    """
    Return a list of LangChain Tool objects bound to *conn*.
    Returns [] if langchain-core is not installed.
    """
    try:
        from langchain_core.tools import tool
    except ImportError:
        return []

    @tool
    def search_jobs(query: str) -> str:
        """
        Search for jobs in the database matching a query string.
        Returns a ranked list of not-applied roles with match scores and locations.
        Use this when the user asks about specific kinds of jobs, companies, or titles.
        """
        from ai_job_hunter.dashboard.backend import repository

        items, total = repository.list_jobs(
            conn,
            status="not_applied",
            q=query.strip() or None,
            ats=None,
            company=None,
            posted_after=None,
            posted_before=None,
            sort="match_desc",
            limit=6,
            offset=0,
        )
        if not items:
            return f"No not-applied jobs found matching '{query}'."

        lines = [f"Found {total} result(s) for '{query}':"]
        for item in items:
            score = item.get("match_score")
            lines.append(
                f"- [{item['id']}] {item['company']} — {item['title']} "
                f"({item.get('location') or 'remote/unspecified'}"
                + (f", score {score}" if score is not None else "")
                + ")"
            )
        return "\n".join(lines)

    @tool
    def get_job_detail(job_id: str) -> str:
        """
        Get full details about a specific job by its ID.
        Returns the job description excerpt, required skills, seniority, work mode, and match breakdown.
        Use this when the user wants to know more about a particular role.
        """
        from ai_job_hunter.dashboard.backend import repository

        detail = repository.get_job_detail(conn, job_id.strip())
        if not detail:
            return f"Job {job_id!r} not found."

        enrichment = detail.get("enrichment") or {}
        req_skills = (enrichment.get("required_skills") or [])[:10]
        pref_skills = (enrichment.get("preferred_skills") or [])[:8]
        match = detail.get("match") or {}

        lines = [
            f"{detail['company']} — {detail['title']}",
            f"Location: {detail.get('location', '')} | Mode: {enrichment.get('work_mode') or 'unknown'}",
            f"Seniority: {enrichment.get('seniority') or 'unknown'} | ATS: {detail.get('ats', '')}",
            f"Required skills: {', '.join(req_skills) or 'not specified'}",
            f"Preferred skills: {', '.join(pref_skills) or 'not specified'}",
            f"Match: score {match.get('score') or '-'} | band {match.get('band') or '-'}",
        ]
        if enrichment.get("red_flags"):
            lines.append(f"Red flags: {', '.join(enrichment['red_flags'][:3])}")

        desc = (enrichment.get("formatted_description") or detail.get("description") or "")[:500]
        if desc:
            lines.append(f"\nDescription excerpt:\n{desc}...")

        return "\n".join(lines)

    @tool
    def get_story_match(job_id: str) -> str:
        """
        Find which stories from the user's story bank best match a specific job.
        Returns a ranked list of matching stories with similarity scores and brief excerpts.
        Use this when explaining why a candidate fits a role or what narratives to highlight.
        """
        try:
            from ai_job_hunter.dashboard.backend.embeddings import get_relevant_stories_for_job
            stories = get_relevant_stories_for_job(job_id.strip(), conn, top_k=5)
        except Exception as exc:
            logger.debug("Semantic story match unavailable: %s", exc)
            stories = []

        if not stories:
            rows = conn.execute(
                "SELECT title, kind, narrative, importance FROM user_stories "
                "WHERE draft = 0 ORDER BY importance DESC LIMIT 5"
            ).fetchall()
            if not rows:
                return (
                    "No stories in the story bank yet. "
                    "Add professional stories in Settings > Story Bank to enable matching."
                )
            lines = ["Top stories by importance (embeddings not yet computed):"]
            for r in rows:
                lines.append(
                    f"- [{r[3]}/5] {r[0]} ({r[1]}): {str(r[2] or '')[:100]}..."
                )
            return "\n".join(lines)

        lines = [f"Top matching stories for job {job_id}:"]
        for s in stories:
            sim = s.get("similarity") or 0.0
            lines.append(
                f"- {s['title']} ({s.get('kind', '')}, {sim:.0%} match): "
                f"{str(s.get('narrative') or '')[:100]}..."
            )
        return "\n".join(lines)

    @tool
    def check_ats_pass(job_id: str) -> str:
        """
        Run an ATS (Applicant Tracking System) analysis on the user's resume against a specific job.
        Looks up the most recent active resume artifact for that job automatically.
        Returns pass likelihood (0-100), missing keywords, weak sections, and improvement suggestions.
        Use this when the user asks whether their resume will pass ATS screening for a role.
        """
        from ai_job_hunter.dashboard.backend.artifacts import (
            get_artifacts_for_job,
            critique_resume_for_ats,
        )

        artifacts = get_artifacts_for_job(job_id.strip(), conn)
        resume = next(
            (a for a in artifacts if a.get("artifact_type") == "resume" and a.get("is_active")),
            None,
        )
        if resume is None:
            resume = next((a for a in artifacts if a.get("artifact_type") == "resume"), None)
        if resume is None:
            return (
                f"No resume artifact found for job {job_id}. "
                "Generate a tailored resume first using the /resume skill or the Resume button."
            )

        try:
            result = critique_resume_for_ats(job_id.strip(), resume["content_md"], conn)
        except Exception as exc:
            return f"ATS analysis failed: {exc}"

        lines = [f"ATS Pass Likelihood: {result['pass_likelihood']}%"]
        if result["missing_keywords"]:
            lines.append(f"Missing keywords: {', '.join(result['missing_keywords'][:10])}")
        if result["weak_sections"]:
            lines.append(f"Weak sections: {', '.join(result['weak_sections'])}")
        if result["suggestions"]:
            lines.append("Suggestions:")
            for s in result["suggestions"][:5]:
                lines.append(f"  - {s}")
        return "\n".join(lines)

    @tool
    def draft_resume(job_id: str) -> str:
        """
        Enqueue generation of a tailored resume for a specific job.
        Uses the user's default base resume document and story bank for grounding.
        Returns a confirmation message when the job is queued.
        Use this when the user asks to create or draft a resume for a role.
        """
        from ai_job_hunter.dashboard.backend.artifacts import (
            list_base_documents,
        )
        from ai_job_hunter.dashboard.backend.core_actions import enqueue_artifact_generation

        docs = list_base_documents(conn)
        resume_docs = [d for d in docs if str(d.get("doc_type") or "") == "resume"]
        if not resume_docs:
            return (
                "No base resume found. Upload a base resume in Settings first, "
                "then I can tailor it for this job."
            )

        base_doc = next((d for d in resume_docs if d.get("is_default")), resume_docs[0])
        row = conn.execute("SELECT title, company FROM jobs WHERE id = ?", (job_id.strip(),)).fetchone()
        if not row:
            return f"Job {job_id!r} not found."

        try:
            operation = enqueue_artifact_generation(job_id.strip(), "resume", int(base_doc["id"]))
            op_id = str(operation.get("id") or "")
            return (
                f"Resume generation queued for {row[1]} — {row[0]}. "
                f"Switch to the Application Workflow pane to see it stream in (operation: {op_id})."
            )
        except Exception as exc:
            return f"Failed to queue resume generation: {exc}"

    @tool
    def move_to_stage(job_id: str, stage: str) -> str:
        """
        Move a job to a different pipeline stage.
        Valid stages: not_applied, applied, interviewing, offer, rejected.
        Use this when the user says they applied, got an interview, received an offer, or was rejected.
        """
        valid = {"not_applied", "applied", "interviewing", "offer", "rejected"}
        s = stage.strip().lower()
        if s not in valid:
            return f"Invalid stage '{stage}'. Choose from: {', '.join(sorted(valid))}"
        job_id = job_id.strip()
        row = conn.execute("SELECT title, company FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return f"Job {job_id!r} not found."
        try:
            from ai_job_hunter.dashboard.backend.service import update_tracking
            update_tracking(conn, job_id, {"status": s})
        except Exception as exc:
            return f"Failed to update stage: {exc}"
        return f"Moved '{row[1]} — {row[0]}' to stage '{s}'."

    @tool
    def suppress_job(job_id: str) -> str:
        """
        Suppress (hide) a job so it no longer appears in recommendations or the board.
        Use this when the user says they don't want to see a job anymore or want to skip it.
        """
        job_id = job_id.strip()
        row = conn.execute("SELECT title, company FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return f"Job {job_id!r} not found."
        try:
            now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO job_suppressions (job_id, suppressed_at, reason) VALUES (?, ?, ?)",
                (job_id, now, "agent suppressed"),
            )
            conn.commit()
        except Exception as exc:
            return f"Failed to suppress job: {exc}"
        return f"Suppressed '{row[1]} — {row[0]}'. It won't appear in recommendations."

    @tool
    def update_profile_field(field: str, value: str) -> str:
        """
        Update a single field in the candidate profile.
        Supported fields: narrative_intent, city, country, phone, linkedin_url, portfolio_url.
        Use this when the user tells you something about themselves that should be saved (e.g. "I'm in Vancouver").
        """
        allowed = {"narrative_intent", "city", "country", "phone", "linkedin_url", "portfolio_url"}
        f = field.strip().lower()
        if f not in allowed:
            return f"Field '{field}' is not editable via this tool. Use Settings for skills and titles."
        try:
            from ai_job_hunter.db import get_candidate_profile, upsert_candidate_profile
            profile = get_candidate_profile(conn)
            profile[f] = value.strip()
            upsert_candidate_profile(conn, profile)
        except Exception as exc:
            return f"Failed to update profile: {exc}"
        return f"Profile field '{f}' updated."

    @tool
    def bulk_queue(job_ids_csv: str) -> str:
        """
        Add multiple jobs to the application queue in one shot.
        Takes a comma-separated list of job IDs.
        Use this when the user asks to queue several jobs at once.
        """
        ids = [jid.strip() for jid in job_ids_csv.split(",") if jid.strip()]
        if not ids:
            return "No job IDs provided."
        added, skipped = [], []
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        for jid in ids:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO application_queue (job_id, status, queued_at, sort_order) VALUES (?, 'queued', ?, 0)",
                    (jid, now),
                )
                added.append(jid)
            except Exception:
                skipped.append(jid)
        conn.commit()
        return f"Queued {len(added)} job(s). Skipped {len(skipped)} (already in queue or not found)."

    return [
        search_jobs, get_job_detail, get_story_match, check_ats_pass, draft_resume,
        move_to_stage, suppress_job, update_profile_field, bulk_queue,
    ]
