# `cli.py scrape` CLI Reference

Command:

```bash
uv run python src/cli.py scrape [options]
```

## Options

- `--no-location-filter`: disable Canada/remote-focused location filtering
- `--limit N`: max rows displayed in Rich table (default: `50`)
- `--db PATH`: local SQLite path. Ignored if `TURSO_URL` is set
- `--no-enrich`: skip description fetching stage
- `--no-notify`: skip Telegram notifications
- `--no-enrich-llm`: skip OpenRouter enrichment stage
- `--enrich-backfill`: enrich jobs missing successful enrichment and exit
- `--re-enrich-all`: force enrich all jobs with descriptions and exit
- `--sort-by {match|posted}`: display ordering (default: `match`)

## Mode behavior

### Normal scrape mode

Runs scraping pipeline and writes jobs to DB.

In automation, scrape workflow runs with `--no-enrich-llm` and enrichment is handled by a separate workflow.

### Enrichment-only modes

- `--enrich-backfill`: picks rows where enrichment missing or non-`ok`.
- `--re-enrich-all`: picks all jobs with non-empty descriptions.
- Enrichment includes:
  - structured extraction (`ENRICHMENT_MODEL`)
  - best-effort description formatting (`DESCRIPTION_FORMAT_MODEL`)

### Source registry precondition

- `scrape` reads companies from DB table `company_sources` (enabled rows only).
- If no enabled sources exist, run one of:
  - `uv run python src/add_company.py "Company Name"`
  - `uv run python src/cli.py sources import`

## Filtering behavior

### Title filter

Include list (`TITLE_INCLUDE`) and exclusion list (`TITLE_EXCLUDE`) are case-insensitive checks.
Additionally, senior-level markers are excluded by default (`senior`, `sr`, `staff`, `principal`, `lead`).

### Match scoring

- Table includes a `Match` column (`0-100`).
- Scores are computed from your profile (`candidate_profile`) and enrichment/title signals.
- `--sort-by match` ranks highest-fit jobs first.
- Rubric details: [`../dashboard/match-scoring.md`](../dashboard/match-scoring.md).

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

## Important assumptions

- Working directory should be project root (for default `.env` and `jobs.db` resolution).
- If both `TURSO_URL` and `--db` are provided, Turso wins.
- LLM enrichment requires `OPENROUTER_API_KEY`; otherwise enrichment is skipped with console message.

## Recovery examples

```bash
# Resume paused enrichment after rate limit
uv run python src/cli.py scrape --enrich-backfill

# Rebuild from local DB with no messaging
uv run python src/cli.py scrape --no-notify --no-enrich-llm
```
