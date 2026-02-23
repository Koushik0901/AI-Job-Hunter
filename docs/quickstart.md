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

## First run

```bash
uv run python src/scrape.py
```

Behavior:

1. Loads companies from `companies.yaml`.
2. Scrapes ATS sources and HN comments.
3. Applies title filter and default location filter.
4. Fetches full descriptions (unless `--no-enrich`).
5. Upserts records into DB.
6. Sends Telegram messages only for new jobs.
7. Runs LLM enrichment for new jobs only (if key exists and `--no-enrich-llm` not set).

## Common next commands

```bash
# Show all title matches globally
uv run python src/scrape.py --no-location-filter --limit 200

# Backfill missing/failed enrichment rows
uv run python src/scrape.py --enrich-backfill

# Re-enrich every described job
uv run python src/scrape.py --re-enrich-all

# Add one company interactively
uv run python src/add_company.py "Scale AI"
```

## Troubleshooting quick pointers

- Help text: `uv run python src/scrape.py --help`
- If enrichment pauses due to 429: rerun with `--enrich-backfill`
- If notifications do not send: verify `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`
- More: [`troubleshooting/known-issues.md`](troubleshooting/known-issues.md)
