# 🚀 Environment Configuration

Environment values are loaded from process env and optional `.env`.

---

## ✨ Required (core app)

- None if you are using the default local SQLite database.
- `TURSO_URL`
- `TURSO_AUTH_TOKEN`

## ✨ Required (AI)

- `OPENROUTER_API_KEY`

## ✨ Optional (dashboard performance)

- `REDIS_URL`
- `DASHBOARD_CACHE_TTL_*`
- `DASHBOARD_CACHE_TTL_JOBS_SNAPSHOT`
- `DASHBOARD_CACHE_MAX_JOB_DETAILS`

## ✨ Optional (evidence retrieval)

- `EVIDENCE_RETRIEVAL_MODE`
- `EVIDENCE_MAX_TOP_K`
- `EVIDENCE_MIN_LEXICAL_OVERLAP`
- `EVIDENCE_MIN_VECTOR_SCORE`
- `QDRANT_URL`
- `QDRANT_API_KEY`
- `QDRANT_EVIDENCE_COLLECTION`

Local dev example:
- `EVIDENCE_RETRIEVAL_MODE=auto`
- `QDRANT_URL=http://127.0.0.1:6333`
- `QDRANT_API_KEY=` (empty unless you secure local Qdrant)
- `QDRANT_EVIDENCE_COLLECTION=candidate_evidence_chunks`

## ✨ Optional (swarm controls)

- `RESUME_SWARM_SCORING_MODEL`
- `RESUME_SWARM_REWRITE_MODEL`
- `COVER_LETTER_SWARM_DRAFT_MODEL`
- `COVER_LETTER_SWARM_SCORING_MODEL`
- `COVER_LETTER_SWARM_REWRITE_MODEL`
- `SWARM_MIN_SCORE_DELTA`
- `SWARM_MAX_OPS_PER_CYCLE`
- `SWARM_MAX_CHANGED_LINE_RATIO`
- `SWARM_FORCE_ON_NON_NEGOTIABLES`
- `SWARM_COMPILE_ROLLBACK`

---

## ✨ Precedence

- If `TURSO_URL` is set, Turso is used.
- Otherwise local SQLite path logic applies.

---

## ✨ Security

- Keep `.env` out of git.
- Use CI secrets in workflows.
- Keep local databases, artifact workspaces, logs, and exported files out of git as well.
