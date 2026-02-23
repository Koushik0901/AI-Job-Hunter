# End-to-End Data Flow

## Scrape pipeline (`src/scrape.py`)

1. Parse CLI args.
2. Load `.env` from `<cwd>/.env`.
3. Branch by mode:
   - `--check`
   - `--import-companies`
   - enrichment-only modes
   - full daily scrape mode
4. Load enabled companies from config.
5. For each company:
   - detect ATS and slug
   - fetch raw listings
   - normalize row fields
   - attach private IDs for description fetch
   - dedupe by URL
   - apply title filter
   - apply location filter (unless disabled)
6. Pull HN jobs and apply same filters.
7. Sort by posted date descending.
8. Fetch descriptions concurrently unless `--no-enrich`.
9. Upsert to DB and classify new vs updated.
10. Notify Telegram for new jobs unless disabled.
11. Enrich new jobs via OpenRouter unless disabled/unconfigured.

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
6. Persist results row by row.

## Pause/resume semantics

- Scrape enrichment pipeline sets stop flag on first hard rate-limit signal.
- Remaining queued/cancelled jobs are left unenriched and recoverable through:

```bash
uv run python src/scrape.py --enrich-backfill
```

- Eval run persists checkpoint after each completed job and can resume with:

```bash
uv run python eval/eval.py run --resume
```
