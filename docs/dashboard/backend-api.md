# 🚀 Dashboard Backend API

Base URL: `http://127.0.0.1:8000`

This API powers Board, Profile, Artifacts, Analytics, and Swarm optimization.

---

## ✨ Health

### `GET /api/health`
Basic health check.

---

## ✨ Jobs and Tracking

### `GET /api/jobs`
List jobs with tracking join.

Query params:
- `status`
- `q`
- `ats`
- `company`
- `posted_after`
- `posted_before`
- `sort` (`posted_desc|updated_desc|company_asc|match_desc`)
- `limit`
- `offset`

### `GET /api/jobs/{job_url}`
Full job detail including enrichment and match panel.

### `PATCH /api/jobs/{job_url}/tracking`
Update tracking fields:
- `status`
- `priority`
- `applied_at`
- `next_step`
- `target_compensation`

### `DELETE /api/jobs/{job_url}`
Delete job and linked dashboard records.

---

## ✨ Job Events

### `GET /api/jobs/{job_url}/events`
List timeline events.

### `POST /api/jobs/{job_url}/events`
Create timeline event.

### `DELETE /api/events/{event_id}`
Delete one event.

---

## ✨ Profile

### `GET /api/profile`
Candidate scoring profile.

### `PUT /api/profile`
Upsert scoring profile.

### `GET /api/profile/evidence-assets`
Load evidence vault assets used by swarm grounding.

### `PUT /api/profile/evidence-assets`
Upsert evidence assets (size-limited + sanitized).

### `GET /api/profile/evidence/index-status`
Current evidence indexing status.

### `POST /api/profile/evidence/reindex`
Force evidence reindex.

---

## ✨ Analytics

### `GET /api/meta/stats`
Board summary metrics.

### `GET /api/analytics/funnel`
Funnel, deltas, goals, alerts, cohorts, source quality, forecast.

Key query params:
- `preset` (`30d|90d|all`)
- `from` / `to`
- `status_scope` (`pipeline|all`)

---

## ✨ Artifact LaTeX + Compile

### `POST /api/artifacts/{artifact_id}/latex/recompile`
Compile active LaTeX version and return compile status/diagnostics.

### `GET /api/artifacts/{artifact_id}/latex/pdf?version=<n>`
Download compiled PDF for a version.

---

## ✨ Resume Swarm Endpoints

- `POST /api/artifacts/{artifact_id}/resume-latex/swarm-runs`
- `GET /api/artifacts/{artifact_id}/resume-latex/swarm-runs/{run_id}`
- `POST /api/artifacts/{artifact_id}/resume-latex/swarm-runs/{run_id}/cancel`
- `POST /api/artifacts/{artifact_id}/resume-latex/swarm-runs/{run_id}/confirm-save`

Run lifecycle:
- Start run -> stream stage events in DB -> inspect status -> confirm save.

Stage telemetry includes:
- evidence retrieval snippets/citation IDs
- score payloads
- rewrite payloads
- verify/apply reports
- gate decisions
- rollback events (if compile guard reverts)

---

## ✨ Cover-Letter Swarm Endpoints

- `POST /api/artifacts/{artifact_id}/cover-letter-latex/swarm-runs`
- `GET /api/artifacts/{artifact_id}/cover-letter-latex/swarm-runs/{run_id}`
- `POST /api/artifacts/{artifact_id}/cover-letter-latex/swarm-runs/{run_id}/cancel`
- `POST /api/artifacts/{artifact_id}/cover-letter-latex/swarm-runs/{run_id}/confirm-save`

Same lifecycle model as resume swarm.

---

## ✨ Safety and Integrity Guarantees

1. Legal-move verification
- Invalid targets are skipped.
- Conflicts are dropped deterministically.

2. Claim policy
- Unsupported claim-introducing edits are blocked.
- `supported_by` citations can be enforced.

3. LaTeX safety
- Brace/environment/special-char guards prevent fragile edits.

4. Compile guard rollback
- If pre-run compiles and post-run fails, final output reverts to input.

---

## ✨ Caching

With `REDIS_URL` configured, read-through caching is enabled for:
- jobs list/detail
- events
- profile
- stats
- funnel analytics

Jobs list requests are served from a single Redis-backed board snapshot and filtered/sorted in memory, so filter changes avoid duplicating per-query job caches behind the scenes.

Writes invalidate affected keys.

---

## ✨ Related Docs

- [overview.md](overview.md)
- [frontend-ui.md](frontend-ui.md)
- [../evaluation/eval-framework.md](../evaluation/eval-framework.md)
