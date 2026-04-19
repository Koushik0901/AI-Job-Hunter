from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_AGENT_MODEL = "openai/gpt-4o-mini"

_SYSTEM_TEMPLATE = """\
You are an AI job search assistant embedded in a personal job search dashboard called "AI Job Hunter".
You help the user manage their job pipeline, understand their match scores, and decide on next actions.

Current pipeline snapshot:
{context}

Guidelines:
- Be concise and actionable. Bullet points preferred for lists.
- Reference specific companies or job titles from the snapshot when relevant.
- Treat `rank score` as a cohort-relative ranking signal, not a literal probability or percent match.
- Treat `fit score` as the content-fit signal against the current profile and job constraints.
- If you don't have enough information to answer precisely, say so clearly.
- Do not make up job listings or scores not mentioned in the context.
- Tone: professional, direct, encouraging.
"""


def build_agent_context(conn: Any) -> str:
    lines: list[str] = []

    try:
        rows = conn.execute(
            """
            SELECT
                COALESCE(t.status, 'not_applied') AS status,
                COUNT(*) AS cnt
            FROM jobs j
            LEFT JOIN job_tracking t ON t.job_id = j.id
            WHERE j.id IS NOT NULL
            GROUP BY status
            ORDER BY cnt DESC
            """
        ).fetchall()
        status_parts = [f"{row[0]}: {row[1]}" for row in rows if row]
        if status_parts:
            lines.append("Pipeline status counts: " + ", ".join(status_parts))
    except Exception:
        pass

    try:
        rows = conn.execute(
            """
            SELECT j.company, j.title, ms.score, ms.raw_score
            FROM jobs j
            JOIN job_match_scores ms ON ms.job_id = j.id
            LEFT JOIN job_tracking t ON t.job_id = j.id
            JOIN candidate_profile cp ON cp.id = 1
            WHERE COALESCE(t.status, 'not_applied') = 'not_applied'
              AND ms.profile_version = COALESCE(cp.score_version, 1)
            ORDER BY ms.score DESC
            LIMIT 5
            """
        ).fetchall()
        if rows:
            top = [
                f"{row[0]} — {row[1]} (rank {row[2]}, fit {row[3]})"
                for row in rows
                if row
            ]
            lines.append("Top ranked not-applied roles: " + "; ".join(top))
    except Exception:
        pass

    try:
        rows = conn.execute(
            """
            SELECT j.company, j.title
            FROM jobs j
            JOIN job_tracking t ON t.job_id = j.id
            WHERE t.status = 'staging'
              AND t.staging_due_at IS NOT NULL
              AND datetime(t.staging_due_at) < datetime('now')
            LIMIT 5
            """
        ).fetchall()
        if rows:
            overdue = [f"{row[0]} — {row[1]}" for row in rows if row]
            lines.append("Overdue staging (need action): " + "; ".join(overdue))
    except Exception:
        pass

    try:
        row = conn.execute(
            "SELECT years_experience, skills, desired_job_titles FROM candidate_profile WHERE id = 1"
        ).fetchone()
        if row:
            skills = []
            titles = []
            try:
                skills = json.loads(row[1] or "[]")
            except Exception:
                pass
            try:
                titles = json.loads(row[2] or "[]")
            except Exception:
                pass
            lines.append(f"Candidate: {row[0]} years experience, {len(skills)} skills in profile")
            if titles:
                lines.append("Desired titles: " + ", ".join(titles[:5]))
    except Exception:
        pass

    return "\n".join(lines) if lines else "No pipeline data available yet."


def _latest_user_message(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if str(message.get("role") or "") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _top_ranked_roles(conn: Any, limit: int = 5) -> list[tuple[str, str, int | None, int | None]]:
    rows = conn.execute(
        """
        SELECT j.company, j.title, ms.score, ms.raw_score
        FROM jobs j
        JOIN job_match_scores ms ON ms.job_id = j.id
        LEFT JOIN job_tracking t ON t.job_id = j.id
        LEFT JOIN job_suppressions s ON s.job_id = j.id AND s.active = 1
        JOIN candidate_profile cp ON cp.id = 1
        WHERE COALESCE(t.status, 'not_applied') = 'not_applied'
          AND s.job_id IS NULL
          AND ms.profile_version = COALESCE(cp.score_version, 1)
        ORDER BY ms.score DESC, date(j.posted) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        (str(row[0] or ""), str(row[1] or ""), row[2], row[3])
        for row in rows
    ]


def _skill_gap_summary(conn: Any, limit: int = 6) -> list[tuple[str, int]]:
    rows = conn.execute(
        """
        SELECT label, count
        FROM (
            SELECT json_extract(value, '$.label') AS label,
                   CAST(json_extract(value, '$.count') AS INTEGER) AS count
            FROM (
                SELECT json_each.value AS value
                FROM daily_briefings db, json_each(json_extract(db.payload_json, '$.profile_gaps'))
                ORDER BY datetime(db.generated_at) DESC
                LIMIT 1
            )
        )
        WHERE label IS NOT NULL
        ORDER BY count DESC, label ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    if rows:
        return [(str(row[0]), int(row[1] or 0)) for row in rows]

    profile_row = conn.execute(
        "SELECT skills FROM candidate_profile WHERE id = 1"
    ).fetchone()
    profile_skills: set[str] = set()
    if profile_row and profile_row[0]:
        try:
            profile_skills = {
                str(item).strip().casefold()
                for item in json.loads(profile_row[0] or "[]")
                if str(item).strip()
            }
        except Exception:
            profile_skills = set()
    rows = conn.execute(
        """
        SELECT required_skills
        FROM job_enrichments e
        JOIN jobs j ON j.id = e.job_id
        LEFT JOIN job_tracking t ON t.job_id = j.id
        LEFT JOIN job_suppressions s ON s.job_id = j.id AND s.active = 1
        WHERE COALESCE(t.status, 'not_applied') = 'not_applied'
          AND s.job_id IS NULL
          AND required_skills IS NOT NULL
        """
    ).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        try:
            skills = json.loads(row[0] or "[]")
        except Exception:
            skills = []
        for skill in skills:
            label = str(skill).strip()
            if not label or label.casefold() in profile_skills:
                continue
            counts[label] = counts.get(label, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    return ranked[:limit]


def _pipeline_triage(conn: Any, limit: int = 5) -> list[str]:
    rows = conn.execute(
        """
        SELECT j.company, j.title, t.staging_due_at
        FROM job_tracking t
        JOIN jobs j ON j.id = t.job_id
        LEFT JOIN job_suppressions s ON s.job_id = j.id AND s.active = 1
        WHERE t.status = 'staging'
          AND s.job_id IS NULL
        ORDER BY
            CASE
                WHEN t.staging_due_at IS NOT NULL AND datetime(t.staging_due_at) <= datetime('now') THEN 0
                ELSE 1
            END,
            datetime(t.staging_due_at) ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        f"{str(row[0] or '')} - {str(row[1] or '')}"
        + (f" (due {row[2]})" if row[2] else "")
        for row in rows
    ]


def _try_fast_agent(messages: list[dict[str, str]], conn: Any) -> dict[str, str] | None:
    prompt = _latest_user_message(messages).casefold()
    if not prompt:
        return None

    context = build_agent_context(conn)

    if any(token in prompt for token in ("apply", "top opportunities", "match my skills", "best jobs", "today")):
        roles = _top_ranked_roles(conn, limit=5)
        if not roles:
            return {
                "reply": "No ranked not-applied roles are available yet. Refresh scoring or add jobs first.",
                "context_snapshot": context,
                "response_mode": "fast",
            }
        lines = ["Top ranked roles right now:"]
        for company, title, rank, fit in roles:
            lines.append(f"- {company} - {title} (rank {rank or '-'}, fit {fit or '-'})")
        lines.append("Prioritize the top 2-3 roles with the strongest fit and the least friction.")
        return {"reply": "\n".join(lines), "context_snapshot": context, "response_mode": "fast"}

    if any(token in prompt for token in ("skill", "gap", "profile")):
        gaps = _skill_gap_summary(conn)
        if not gaps:
            return {
                "reply": "I do not see a dominant skill gap right now. The current recommendations look reasonably aligned with your profile.",
                "context_snapshot": context,
                "response_mode": "fast",
            }
        lines = ["Most common missing signals across current opportunities:"]
        for label, count in gaps:
            lines.append(f"- {label}: appears in {count} role(s)")
        lines.append("Add the strongest truthful skills to your profile first, then regenerate ranking.")
        return {"reply": "\n".join(lines), "context_snapshot": context, "response_mode": "fast"}

    if any(token in prompt for token in ("pipeline", "momentum", "triage", "stage", "staging")):
        triage = _pipeline_triage(conn)
        if not triage:
            return {
                "reply": "There are no urgent staging items right now. Focus on the highest-ranked not-applied roles.",
                "context_snapshot": context,
                "response_mode": "fast",
            }
        lines = ["Pipeline triage:"]
        for item in triage:
            lines.append(f"- {item}")
        lines.append("Clear overdue staging items before adding more queue work.")
        return {"reply": "\n".join(lines), "context_snapshot": context, "response_mode": "fast"}

    return None


def handle_freeform_chat(messages: list[dict[str, str]], conn: Any) -> dict[str, str]:
    fast = _try_fast_agent(messages, conn)
    if fast is not None:
        return fast

    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        return {
            "reply": "The agent is not configured — set OPENROUTER_API_KEY in your environment to enable it.",
            "context_snapshot": "",
            "response_mode": "fallback",
        }

    model = (os.getenv("AGENT_MODEL") or _DEFAULT_AGENT_MODEL).strip()

    try:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_openai import ChatOpenAI
    except ImportError:
        return {
            "reply": "LangChain is not installed. Run: uv add langchain-openai",
            "context_snapshot": "",
            "response_mode": "fallback",
        }

    context = build_agent_context(conn)
    system_content = _SYSTEM_TEMPLATE.format(context=context)

    lc_messages: list[Any] = [SystemMessage(content=system_content)]
    for msg in messages:
        role = str(msg.get("role") or "user")
        content = str(msg.get("content") or "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        else:
            lc_messages.append(AIMessage(content=content))

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=_OPENROUTER_BASE_URL,
        temperature=0.4,
        max_tokens=1200,
    )

    try:
        response = llm.invoke(lc_messages)
        reply = str(getattr(response, "content", "") or "")
    except Exception as exc:
        logger.exception("Agent LLM call failed")
        reply = f"The agent encountered an error: {exc}"

    return {"reply": reply, "context_snapshot": context, "response_mode": "llm"}
