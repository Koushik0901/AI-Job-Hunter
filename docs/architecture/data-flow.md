# End-to-End Data Flow

## Scrape pipeline (`src/cli.py scrape`)

1. Parse CLI args.
2. Load `.env` from `<cwd>/.env`.
3. Resolve DB (Turso if `TURSO_URL`, else local SQLite path).
4. If `--enrich-backfill`, `--re-enrich-all`, `--jd-reformat-missing`, or `--jd-reformat-all`:
   - load enrichment candidates from DB
   - run enrichment-only pipeline
   - exit
5. Load enabled companies from DB table `company_sources`.
6. For each company source:
   - select fetcher by `ats_type`
   - extract slug from `ats_url`
   - fetch raw listings
   - normalize row fields
   - attach private IDs for description fetch
   - dedupe by URL
   - apply title filter
   - apply location filter (unless disabled)
7. Pull HN jobs and apply same filters.
8. Compute match score from profile + enrichment/title signals.
9. Sort by `match` (or `posted` when selected).
10. Fetch descriptions concurrently unless `--no-enrich`.
11. Upsert to DB and classify `new` vs `updated`.
12. Notify Telegram for new jobs unless disabled.
13. Enrich new jobs unless disabled/unconfigured.

In production automation, this is split:

- scrape workflow: `scrape --no-enrich-llm`
- enrichment workflow: `scrape --enrich-backfill` (or manual `--re-enrich-all` / `--jd-reformat-missing` / `--jd-reformat-all`)

## Source registry flow (`src/cli.py sources`)

- `list`: reads all rows from `company_sources`.
- `enable`/`disable`: updates row state by `id` or `slug`.
- `check`: probes ATS endpoints for a slug; no DB mutation.
- `import`: fetches curated GitHub lists, parses candidates, dedupes, upserts DB rows.

## Lifecycle flow (`src/cli.py lifecycle`)

- `set-status`: writes `jobs.application_status` for one URL.
- `prune` (dry-run default): counts/deletes old rows where:
  - status is unset or `not_applied`
  - `posted` exists and is older than threshold
  - status is not in protected set (`staging`, `applied`, `interviewing`, `offer`, `rejected`, `withdrawn`)

## Dashboard flow (`src/dashboard/backend` + `src/dashboard/frontend`)

1. User lands on `Board` route (`/`) and frontend loads jobs list (`GET /api/jobs`) + summary stats (`GET /api/meta/stats`).
2. Frontend groups jobs by `tracking_status` for kanban columns.
3. Backend computes match score per job from profile + enrichment/title and returns list/detail score payloads.
4. User selects a card -> frontend requests detail (`GET /api/jobs/{job_url}`) and timeline (`GET /api/jobs/{job_url}/events`).
5. User drags card across columns:
   - frontend applies optimistic state update
   - backend patch persists tracking (`PATCH /api/jobs/{job_url}/tracking`)
   - repository syncs `job_tracking.status` and `jobs.application_status`
6. User edits tracking fields from detail drawer:
   - frontend sends patch (`PATCH /api/jobs/{job_url}/tracking`)
   - backend updates `job_tracking` and mirrored `jobs.application_status`
7. User navigates to `Profile` route (`/profile`) to load and edit profile (`GET/PUT /api/profile`).
8. Saved profile updates are used for subsequent match computation/ranking in board responses.
9. Frontend refreshes stats/list/detail so kanban, metrics, and drawer data remain consistent.
10. Detail response includes optional enrichment payload joined from `job_enrichments` and `match` payload from scorer.

## Enrichment flow (`src/enrich.py`)

1. Skip jobs with empty descriptions (`skipped`).
2. Build structured extraction prompt.
3. Invoke LangChain `with_structured_output(JobEnrichment)`.
4. Run a second low-cost model pass to produce `formatted_description` (best-effort).
5. On non-rate-limit extraction errors: mark `failed`.
6. On rate limit:
   - parse provider name from error if possible
   - add provider to `ignore` list and retry
   - fallback to `sort_by=throughput` when provider unknown
   - after max retries, raise `RateLimitSignal`
7. Persist enrichment results row by row.

## Pause/resume semantics

- Scrape enrichment pipeline sets stop flag on first hard rate-limit signal.
- Remaining queued/cancelled jobs are left unenriched and recoverable through:

```bash
uv run python src/cli.py scrape --enrich-backfill
```

- Eval run persists checkpoint after each completed job and can resume with:

```bash
uv run python eval/eval.py run --resume
```
