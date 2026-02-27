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
- `posted_before`
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
- `formatted_description` (LLM-formatted Markdown, nullable)
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
- `education` (array of `{ degree, field }`)
- `degree` (legacy scalar degree field)
- `degree_field` (legacy scalar degree-field value)

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

### `GET /api/analytics/funnel`

Return funnel analytics for pipeline stages and conversion rates.

Query params:

- `preset` (`30d|90d|all`, default `90d`)
- `from` (ISO date, optional; alias of `from_date`)
- `to` (ISO date, optional; defaults to today UTC)
- `status_scope` (`pipeline|all`, default `pipeline`)
- `applications_goal_target` (int, optional, default `10`)
- `interviews_goal_target` (int, optional, default `3`)
- `forecast_apps_per_week` (int, optional, default falls back to `applications_goal_target`)

Behavior:

- Stage counts are always returned for pipeline statuses:
  - `not_applied`
  - `staging`
  - `applied`
  - `interviewing`
  - `offer`
  - `rejected`
- Conversion metrics include:
  - `backlog_to_staging`
  - `staging_to_applied`
  - `applied_to_interviewing`
  - `interviewing_to_offer`
  - `backlog_to_offer`
- Also returns:
  - `deltas` (current window minus previous equal window counts/conversions)
  - `weekly_goals` (7-day applications/interviews target vs actual and progress)
  - `alerts` (stale staging, stale interviewing, backlog expiring soon)
  - `cohorts` (weekly posted cohorts with per-stage counts and offer rate)
  - `source_quality`:
    - `ats` top source performance table
    - `companies` top company performance table
  - `forecast`:
    - forecast input throughput (`applications_per_week`)
    - rates (`interview_rate`, `offer_rate_from_interview`)
    - confidence band + margin
    - horizon windows (`7d`, `30d`) with projected values and low/high ranges
- `status_scope=pipeline` excludes non-pipeline/legacy statuses from totals.
- `status_scope=all` includes all normalized statuses in `status_totals`.

## Data consistency rule

Tracking updates also sync `jobs.application_status` so CLI lifecycle and dashboard stay aligned.

## Caching

When `REDIS_URL` is configured, dashboard backend uses Redis read-through caching for:

- `GET /api/jobs`
- `GET /api/jobs/{job_url}`
- `GET /api/jobs/{job_url}/events`
- `GET /api/profile`
- `GET /api/meta/stats`
- `GET /api/analytics/funnel`

Write endpoints invalidate affected cache keys (tracking updates, profile updates, event create/delete, and job delete).

Job-detail cache (`GET /api/jobs/{job_url}`) is also bounded by an LRU index:

- max entries controlled by `DASHBOARD_CACHE_MAX_JOB_DETAILS` (default `24`)
- oldest least-recently-used detail entries are evicted when limit is exceeded
- per-entry TTL still applies via `DASHBOARD_CACHE_TTL_JOB_DETAIL`
- funnel analytics TTL is controlled by `DASHBOARD_CACHE_TTL_ANALYTICS_FC`
