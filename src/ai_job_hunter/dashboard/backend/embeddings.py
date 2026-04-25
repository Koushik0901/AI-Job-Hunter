"""
embeddings.py — Vector embedding and semantic job-story matching.

Embeddings are computed via OpenRouter (qwen/qwen3-embedding-8b by default)
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
_DEFAULT_EMBEDDING_MODEL = "qwen/qwen3-embedding-8b"

_SEMANTIC_WEIGHT = 0.65   # semantic is the primary signal; keyword adjusts around it
_KEYWORD_ADJUSTMENT_FACTOR = 0.20  # keyword offsets semantic by ±FACTOR*(keyword-50)
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


def ensure_narrative_intent_embedding(conn: Any) -> bool:
    """
    Compute and cache an embedding for the candidate's narrative_intent.

    Re-embeds only when the stored text has changed (or when no embedding
    exists yet). Requires OPENROUTER_API_KEY + EMBEDDING_MODEL. Silently
    no-ops and returns False when prerequisites are missing so profile
    saves never fail because of a missing embedding service.

    Returns True when a new embedding was written.
    """
    row = conn.execute(
        """
        SELECT narrative_intent, narrative_intent_embedded_text, narrative_intent_embedding
        FROM candidate_profile WHERE id = 1
        """
    ).fetchone()
    if not row:
        return False
    intent_text = (str(row[0] or "").strip()) or None
    last_embedded = (str(row[1] or "").strip()) or None
    existing_blob = row[2]

    if not intent_text:
        # Profile has no intent — clear any stale embedding
        if existing_blob is not None or last_embedded is not None:
            conn.execute(
                "UPDATE candidate_profile SET narrative_intent_embedding = NULL, narrative_intent_embedded_text = NULL WHERE id = 1"
            )
            conn.commit()
        return False

    if existing_blob is not None and last_embedded == intent_text:
        return False   # already up to date

    try:
        vector = get_embedding(intent_text)
    except Exception:
        logger.warning("Failed to embed narrative_intent", exc_info=True)
        return False

    blob = encode_vector(vector)
    conn.execute(
        """
        UPDATE candidate_profile
        SET narrative_intent_embedding = ?, narrative_intent_embedded_text = ?
        WHERE id = 1
        """,
        (blob, intent_text),
    )
    conn.commit()
    return True


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
    intent_embedding: list[float] | None = None,
) -> tuple[float, list[int], list[str]]:
    """
    Compute semantic score for a job against the candidate's stories and
    (optionally) their narrative-intent statement.

    Returns:
        (semantic_score 0-100, top_matched_story_ids, top_matched_story_titles)

    Score blend:
        final = 0.7 * top-K story similarity + 0.3 * intent similarity
        (when intent_embedding is absent, score is 100% story-based)

    Falls back to 0.0 when embeddings are unavailable.
    """
    if not job_embedding_blob:
        return 0.0, [], []

    job_vec = decode_vector(job_embedding_blob)
    if not job_vec:
        return 0.0, [], []

    story_score = 0.0
    top_ids: list[int] = []
    top_titles: list[str] = []

    if story_embeddings:
        sims: list[tuple[float, int, str]] = []
        for s in story_embeddings:
            sim = cosine_similarity(job_vec, s["embedding"])
            sims.append((sim, s["id"], s["title"]))
        sims.sort(key=lambda x: x[0], reverse=True)
        top = [(sim, sid, stitle) for sim, sid, stitle in sims[:_TOP_K_STORIES] if sim >= _MIN_SIMILARITY]
        if top:
            avg_sim = sum(s[0] for s in top) / len(top)
            story_score = min(100.0, max(0.0, avg_sim * 100.0))
            top_ids = [s[1] for s in top]
            top_titles = [s[2] for s in top]

    intent_score = 0.0
    if intent_embedding:
        intent_sim = cosine_similarity(job_vec, intent_embedding)
        intent_score = min(100.0, max(0.0, intent_sim * 100.0))

    if intent_embedding and story_score > 0:
        final = (0.7 * story_score) + (0.3 * intent_score)
    elif intent_embedding:
        # No story matches — intent alone drives the score
        final = intent_score
    else:
        final = story_score

    if final <= 0 and not top_ids:
        return 0.0, [], []

    return final, top_ids, top_titles


def blend_scores(keyword_score: float, semantic_score: float) -> float:
    """
    Semantic-first blend: semantic anchors the score, keyword provides a ±adjustment.

    When stories exist and match the job (semantic_score > 0), semantic is the primary
    signal. Keyword coverage shifts the result by up to ±_KEYWORD_ADJUSTMENT_FACTOR*50
    points (roughly ±10 points for extreme keyword mismatches).

    Falls back to pure keyword when no semantic score is available (no stories yet).
    """
    if semantic_score <= 0:
        return keyword_score
    keyword_delta = (keyword_score - 50.0) * _KEYWORD_ADJUSTMENT_FACTOR
    return max(0.0, min(100.0, semantic_score + keyword_delta))


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
