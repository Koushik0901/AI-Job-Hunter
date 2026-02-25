# Quickstart

## Prerequisites

- Python `3.12+` (`.python-version` is `3.12`)
- `uv`

## Install

```bash
uv sync
```

## Configure

```bash
cp .env.example .env
```

Set at minimum:

- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

Optional but recommended:

- `TURSO_URL`
- `TURSO_AUTH_TOKEN`
- `OPENROUTER_API_KEY`
- `ENRICHMENT_MODEL`

If `TURSO_URL` is absent, local SQLite `jobs.db` is used.

## Add company sources

Sources are stored in DB table `company_sources`.

```bash
# interactive single-company add
uv run python src/add_company.py "Scale AI"

# or bulk import from curated lists
uv run python src/cli.py sources import --dry-run
uv run python src/cli.py sources import
```

Verify source registry:

```bash
uv run python src/cli.py sources list
```

## First run

```bash
uv run python src/cli.py scrape
```

Behavior:

1. Loads enabled companies from DB table `company_sources`.
2. Scrapes ATS sources and HN comments.
3. Applies title filter and default location filter.
4. Fetches full descriptions (unless `--no-enrich`).
5. Upserts records into `jobs`.
6. Sends Telegram messages only for new jobs.
7. Runs LLM enrichment for new jobs only (if key exists and `--no-enrich-llm` not set).

## Common next commands

```bash
# Show broader location output
uv run python src/cli.py scrape --no-location-filter --limit 200

# Backfill missing/failed enrichment rows
uv run python src/cli.py scrape --enrich-backfill

# Re-enrich every described job
uv run python src/cli.py scrape --re-enrich-all

# Reformat descriptions for already-enriched rows missing formatted text
uv run python src/cli.py scrape --jd-reformat-missing

# Reformat descriptions for all already-enriched rows
uv run python src/cli.py scrape --jd-reformat-all

# Track your process for one URL
uv run python src/cli.py lifecycle set-status --url <job_url> --status applied

# Preview retention cleanup
uv run python src/cli.py lifecycle prune --days 28
```

## Run dashboard (optional)

```bash
# API
uv run python src/dashboard/backend/main.py

# UI
cd src/dashboard/frontend
npm install
npm run dev
```

Open:

- API: `http://127.0.0.1:8000/api/health`
- UI: `http://localhost:5173`

Note: dashboard backend requires `TURSO_URL` and `TURSO_AUTH_TOKEN`.

## Configure match profile (dashboard)

In the dashboard `Profile` page (`/profile`), set:

- years of experience
- skills
- target role families
- visa sponsorship need

Then save profile to enable/rerank match scoring.

Scoring rubric: [`dashboard/match-scoring.md`](dashboard/match-scoring.md)

## Troubleshooting quick pointers

- CLI help: `uv run python src/cli.py --help`
- Scrape help: `uv run python src/cli.py scrape --help`
- If enrichment pauses due to 429: rerun with `--enrich-backfill`
- If notifications do not send: verify `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`
- More: [`troubleshooting/known-issues.md`](troubleshooting/known-issues.md)
