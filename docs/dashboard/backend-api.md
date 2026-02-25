# Dashboard Backend API

Base URL: `http://127.0.0.1:8000`

Default CORS allowlist:

- `http://localhost:5173`
- `http://127.0.0.1:5173`

## Endpoints

### `GET /api/health`

Health check.

### `GET /api/jobs`

List jobs with tracking join.

Query params:

- `status`
- `q`
- `ats`
- `company`
- `posted_after`
- `sort` (`posted_desc|updated_desc|company_asc|match_desc`)
- `limit`
- `offset`

### `GET /api/jobs/{job_url}`

Get full job + tracking detail.

`job_url` should be URL-encoded on the client.

Response also includes `enrichment` (nullable) loaded from `job_enrichments`, including:

- work mode / remote geo / eligibility
- seniority / role family / years experience
- minimum degree requirement
- salary fields
- required and preferred skills arrays
- `formatted_description` (LLM-cleaned plain text, nullable)
- visa sponsorship and red flags
- enrichment metadata (`enriched_at`, `enrichment_status`, `enrichment_model`)

Response includes `match`:

- `score` (`0-100`)
- `band` (`excellent|good|fair|low`)
- `breakdown`
- `reasons`
- `confidence`

Scoring rubric details: [`match-scoring.md`](match-scoring.md).

### `GET /api/profile`

Get candidate profile used for job-match scoring.

### `PUT /api/profile`

Upsert candidate profile.

Body fields:

- `years_experience`
- `skills` (array)
- `target_role_families` (array)
- `requires_visa_sponsorship` (boolean)

### `PATCH /api/jobs/{job_url}/tracking`

Update tracking fields.

Body supports:

- `status`
- `priority`
- `applied_at`
- `next_step`
- `target_compensation`

### `DELETE /api/jobs/{job_url}`

Permanently delete one job and linked dashboard records in a single backend transaction.

Delete cascade performed by repository:

- `job_events`
- `job_tracking`
- `job_enrichments`
- `jobs`

Returns:

- `{ "deleted": 1 }` on success
- `404` when the job URL does not exist

### `GET /api/jobs/{job_url}/events`

List timeline events for a job.

### `POST /api/jobs/{job_url}/events`

Create timeline event.

Body fields:

- `event_type`
- `title`
- `body` (optional)
- `event_at` (ISO)

### `DELETE /api/events/{event_id}`

Delete one event.

### `GET /api/meta/stats`

Return dashboard summary metrics.

## Data consistency rule

Tracking updates also sync `jobs.application_status` so CLI lifecycle and dashboard stay aligned.

## Caching

When `REDIS_URL` is configured, dashboard backend uses Redis read-through caching for:

- `GET /api/jobs`
- `GET /api/jobs/{job_url}`
- `GET /api/jobs/{job_url}/events`
- `GET /api/profile`
- `GET /api/meta/stats`

Write endpoints invalidate affected cache keys (tracking updates, profile updates, event create/delete, and job delete).

Job-detail cache (`GET /api/jobs/{job_url}`) is also bounded by an LRU index:

- max entries controlled by `DASHBOARD_CACHE_MAX_JOB_DETAILS` (default `24`)
- oldest least-recently-used detail entries are evicted when limit is exceeded
- per-entry TTL still applies via `DASHBOARD_CACHE_TTL_JOB_DETAIL`
