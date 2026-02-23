# End-to-End Data Flow

## Scrape pipeline (`src/cli.py scrape`)

1. Parse CLI args.
2. Load `.env` from `<cwd>/.env`.
3. Resolve DB (Turso if `TURSO_URL`, else local SQLite path).
4. If `--enrich-backfill` or `--re-enrich-all`:
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
8. Sort by `posted` descending.
9. Fetch descriptions concurrently unless `--no-enrich`.
10. Upsert to DB and classify `new` vs `updated`.
11. Notify Telegram for new jobs unless disabled.
12. Enrich new jobs unless disabled/unconfigured.

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
  - status is not in protected set (`applied`, `interviewing`, `offer`, `rejected`, `withdrawn`)

## Enrichment flow (`src/enrich.py`)

1. Skip jobs with empty descriptions (`skipped`).
2. Build structured extraction prompt.
3. Invoke LangChain `with_structured_output(JobEnrichment)`.
4. On non-rate-limit errors: mark `failed`.
5. On rate limit:
   - parse provider name from error if possible
   - add provider to `ignore` list and retry
   - fallback to `sort_by=throughput` when provider unknown
   - after max retries, raise `RateLimitSignal`
6. Persist enrichment results row by row.

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
