# `scrape.py` CLI Reference

Command:

```bash
uv run python src/scrape.py [options]
```

## Options

- `--config PATH`, `-c PATH`: path to `companies.yaml` (default: `<cwd>/companies.yaml`)
- `--no-location-filter`: disable Canada/remote-focused location filtering
- `--limit N`: max rows displayed in Rich table (default: `50`)
- `--check SLUG`: probe all ATS endpoints for one slug and exit
- `--db PATH`: local SQLite path. Ignored if `TURSO_URL` is set
- `--no-enrich`: skip description fetching stage
- `--no-notify`: skip Telegram notifications
- `--no-enrich-llm`: skip OpenRouter enrichment stage
- `--enrich-backfill`: enrich jobs missing successful enrichment and exit
- `--re-enrich-all`: force enrich all jobs with descriptions and exit
- `--import-companies`: fetch GitHub lists and append new entries to `companies.yaml`
- `--dry-run`: with `--import-companies`, preview without writing

## Mode behavior

### Normal scrape mode

Runs full pipeline and writes jobs to DB.

### `--check` mode

- Performs ATS health checks only.
- Prints per-ATS result and estimated job counts.
- Does not mutate DB or config.

### `--import-companies` mode

- Pulls data from three upstream repositories.
- Parses Greenhouse/Lever/SmartRecruiters slugs.
- De-duplicates against existing slugs/URLs.
- Appends YAML entries unless `--dry-run` is used.

### Enrichment-only modes

- `--enrich-backfill`: picks rows where enrichment missing or non-`ok`.
- `--re-enrich-all`: picks all jobs with non-empty descriptions.

## Filtering behavior

### Title filter

Include list (`TITLE_INCLUDE`) and exclusion list (`TITLE_EXCLUDE`) are case-insensitive substring checks.

### Location filter

Accepts:

- Empty location (unknown)
- Canada signals (country/province/city/tokenized abbreviations)
- Remote unless explicitly blocked country keywords
- Anywhere

Rejects:

- Explicit non-remote US-only style locations
- Remote with blocked country qualifiers (for example UK, Europe, India)

## Data source coverage

- Greenhouse
- Lever
- Ashby
- Workable
- SmartRecruiters
- HN "Who is Hiring" comments (Algolia)

## Side effects

- DB writes to `jobs` and `job_enrichments`
- Optional Telegram sends for new jobs
- Optional company list append in `companies.yaml`

## Important assumptions

- Working directory should be project root (for default `.env`, `companies.yaml`, `jobs.db` resolution).
- If both `TURSO_URL` and `--db` are provided, Turso wins.
- LLM enrichment requires `OPENROUTER_API_KEY`; otherwise enrichment is skipped with console message.

## Recovery examples

```bash
# Resume paused enrichment after rate limit
uv run python src/scrape.py --enrich-backfill

# Rebuild from local DB with no messaging
uv run python src/scrape.py --no-notify --no-enrich-llm
```
