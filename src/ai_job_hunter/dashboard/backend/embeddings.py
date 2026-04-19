"""
embeddings.py — Vector embedding and semantic job-story matching.

Embeddings are computed via OpenRouter (openai/text-embedding-3-small by default)
and stored as packed float32 BLOBs. Semantic score blends with the keyword
score in recompute_match_scores to produce the final ranking.

Flow:
  1. embed_pending_stories(conn) — embed accepted stories that lack vectors
  2. embed_pending_jobs(conn)    — embed enriched jobs that lack vectors
  3. compute_semantic_match(job_blob, story_embeddings)
     -> (semantic_score 0-100, top_story_ids, top_story_titles)
"""
from __future__ import annotations

import json
import logging
import os
import struct
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"

_SEMANTIC_WEIGHT = 0.25   # fraction blended into keyword score
_TOP_K_STORIES = 3
_MIN_SIMILARITY = 0.40    # stories below this are excluded from "matched" list


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Vector serialisation
# ---------------------------------------------------------------------------

def encode_vector(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def decode_vector(b: bytes | None) -> list[float] | None:
    if not b:
        return None
    n = len(b) // 4
    if n == 0:
        return None
    return list(struct.unpack(f"{n}f", b))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# Text builders
# ---------------------------------------------------------------------------

def _parse_json_list(raw: Any) -> list:
    if not raw:
        return []
    try:
        result = json.loads(raw) if isinstance(raw, str) else raw
        return result if isinstance(result, list) else []
    except Exception:
        return []


def story_to_text(story: dict) -> str:
    """Flatten a story dict into a single embeddable string."""
    parts: list[str] = []
    if story.get("title"):
        parts.append(str(story["title"]))
    if story.get("role_context"):
        parts.append(str(story["role_context"]))
    if story.get("narrative"):
        parts.append(str(story["narrative"]))
    skills = _parse_json_list(story.get("skills"))
    if skills:
        parts.append("Skills: " + ", ".join(str(s) for s in skills))
    outcomes = _parse_json_list(story.get("outcomes"))
    if outcomes:
        parts.append("Outcomes: " + ". ".join(str(o) for o in outcomes))
    return " | ".join(parts)[:6000]


def job_to_text(enrichment: dict) -> str:
    """Flatten job enrichment into a single embeddable string."""
    parts: list[str] = []
    if enrichment.get("role_family"):
        parts.append(str(enrichment["role_family"]))
    if enrichment.get("seniority"):
        parts.append(str(enrichment["seniority"]))
    desc = str(enrichment.get("formatted_description") or "")
    if desc:
        parts.append(desc[:3500])
    req = _parse_json_list(enrichment.get("required_skills"))
    if req:
        parts.append("Required: " + ", ".join(str(s) for s in req))
    pref = _parse_json_list(enrichment.get("preferred_skills"))
    if pref:
        parts.append("Preferred: " + ", ".join(str(s) for s in pref))
    return " | ".join(parts)[:6000]


# ---------------------------------------------------------------------------
# Embedding API
# ---------------------------------------------------------------------------

def get_embedding(text: str, model: str | None = None) -> list[float]:
    """Call OpenRouter embedding endpoint. Returns float list."""
    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    embedding_model = (model or os.getenv("EMBEDDING_MODEL") or _DEFAULT_EMBEDDING_MODEL).strip()
    payload = json.dumps({"model": embedding_model, "input": text[:8000]}).encode()
    req = urllib.request.Request(
        f"{_OPENROUTER_BASE_URL}/embeddings",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/ai-job-hunter",
            "X-Title": "AI Job Hunter",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Embedding API error {exc.code}: {body}") from exc
    return data["data"][0]["embedding"]


# ---------------------------------------------------------------------------
# Batch embedding
# ---------------------------------------------------------------------------

def embed_pending_stories(conn: Any) -> int:
    """Embed accepted stories that have no embedding yet. Returns count embedded."""
    model = (os.getenv("EMBEDDING_MODEL") or _DEFAULT_EMBEDDING_MODEL).strip()
    rows = conn.execute(
        """
        SELECT id, title, narrative, role_context, skills, outcomes, tags
        FROM user_stories
        WHERE embedding IS NULL AND draft = 0
        """
    ).fetchall()
    count = 0
    for row in rows:
        story = {
            "id": row[0],
            "title": row[1],
            "narrative": row[2],
            "role_context": row[3],
            "skills": row[4],
            "outcomes": row[5],
            "tags": row[6],
        }
        text = story_to_text(story)
        if not text.strip():
            continue
        try:
            vector = get_embedding(text, model)
            blob = encode_vector(vector)
            conn.execute(
                "UPDATE user_stories SET embedding = ?, embedding_model = ? WHERE id = ?",
                (blob, model, row[0]),
            )
            conn.commit()
            count += 1
        except Exception:
            logger.warning("Failed to embed story id=%s", row[0], exc_info=True)
    return count


def embed_pending_jobs(conn: Any, limit: int = 200) -> int:
    """Embed enriched jobs without embeddings. Returns count embedded."""
    model = (os.getenv("EMBEDDING_MODEL") or _DEFAULT_EMBEDDING_MODEL).strip()
    rows = conn.execute(
        """
        SELECT e.job_id, e.role_family, e.seniority, e.formatted_description,
               e.required_skills, e.preferred_skills
        FROM job_enrichments e
        WHERE e.job_embedding IS NULL
          AND e.enrichment_status = 'enriched'
          AND e.job_id IS NOT NULL
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    count = 0
    for row in rows:
        enrichment = {
            "role_family": row[1],
            "seniority": row[2],
            "formatted_description": row[3],
            "required_skills": row[4],
            "preferred_skills": row[5],
        }
        text = job_to_text(enrichment)
        if not text.strip():
            continue
        try:
            vector = get_embedding(text, model)
            blob = encode_vector(vector)
            conn.execute(
                """
                UPDATE job_enrichments
                SET job_embedding = ?, job_embedded_at = ?
                WHERE job_id = ?
                """,
                (blob, _now(), row[0]),
            )
            conn.commit()
            count += 1
        except Exception:
            logger.warning("Failed to embed job id=%s", row[0], exc_info=True)
    return count


# ---------------------------------------------------------------------------
# Semantic match
# ---------------------------------------------------------------------------

def load_story_embeddings(conn: Any) -> list[dict[str, Any]]:
    """Load all accepted story embeddings. Each entry: {id, title, kind, embedding}."""
    rows = conn.execute(
        "SELECT id, title, kind, embedding FROM user_stories WHERE embedding IS NOT NULL AND draft = 0"
    ).fetchall()
    result = []
    for row in rows:
        v = decode_vector(row[3])
        if v:
            result.append({
                "id": int(row[0]),
                "title": str(row[1] or ""),
                "kind": str(row[2] or "role"),
                "embedding": v,
            })
    return result


def compute_semantic_match(
    job_embedding_blob: bytes | None,
    story_embeddings: list[dict[str, Any]],
) -> tuple[float, list[int], list[str]]:
    """
    Compute semantic score for a job given preloaded story embeddings.

    Returns:
        (semantic_score 0-100, top_matched_story_ids, top_matched_story_titles)

    semantic_score uses the average cosine similarity of top-K matched stories,
    scaled to 0-100. Returns (0.0, [], []) when embeddings are unavailable.
    """
    if not job_embedding_blob or not story_embeddings:
        return 0.0, [], []

    job_vec = decode_vector(job_embedding_blob)
    if not job_vec:
        return 0.0, [], []

    sims: list[tuple[float, int, str]] = []
    for s in story_embeddings:
        sim = cosine_similarity(job_vec, s["embedding"])
        sims.append((sim, s["id"], s["title"]))

    sims.sort(key=lambda x: x[0], reverse=True)
    top = [(sim, sid, stitle) for sim, sid, stitle in sims[:_TOP_K_STORIES] if sim >= _MIN_SIMILARITY]

    if not top:
        return 0.0, [], []

    avg_sim = sum(s[0] for s in top) / len(top)
    semantic_score = min(100.0, max(0.0, avg_sim * 100.0))
    return semantic_score, [s[1] for s in top], [s[2] for s in top]


def blend_scores(keyword_score: float, semantic_score: float) -> float:
    """
    Blend keyword score with semantic score.
    Only blends when semantic_score > 0 (i.e. story embeddings exist and matched).
    """
    if semantic_score <= 0:
        return keyword_score
    return (keyword_score * (1.0 - _SEMANTIC_WEIGHT)) + (semantic_score * _SEMANTIC_WEIGHT)


def get_relevant_stories_for_job(
    job_id: str,
    conn: Any,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """
    Return top-K stories most relevant to a job, with similarity scores.
    Used by the /api/jobs/{job_id}/relevant-stories endpoint.
    """
    row = conn.execute(
        "SELECT job_embedding FROM job_enrichments WHERE job_id = ?", (job_id,)
    ).fetchone()
    job_blob = row[0] if row else None
    if not job_blob:
        return []

    story_rows = conn.execute(
        """
        SELECT id, title, kind, narrative, role_context, skills, outcomes,
               importance, embedding
        FROM user_stories
        WHERE embedding IS NOT NULL AND draft = 0
        """
    ).fetchall()
    if not story_rows:
        return []

    job_vec = decode_vector(job_blob)
    if not job_vec:
        return []

    results: list[tuple[float, dict]] = []
    for r in story_rows:
        v = decode_vector(r[8])
        if not v:
            continue
        sim = cosine_similarity(job_vec, v)
        results.append((sim, {
            "id": int(r[0]),
            "title": str(r[1] or ""),
            "kind": str(r[2] or "role"),
            "narrative": str(r[3] or ""),
            "role_context": r[4],
            "skills": _parse_json_list(r[5]),
            "importance": r[7],
            "similarity": round(sim, 4),
        }))

    results.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in results[:top_k] if _ >= _MIN_SIMILARITY]
