# System Overview

## Major modules

- `src/scrape.py`: orchestrator and CLI entrypoint
- `src/fetchers.py`: ATS/HN ingestion and description enrichment
- `src/db.py`: SQLite/Turso persistence
- `src/enrich.py`: LLM extraction pipeline
- `src/notify.py`: dotenv load, message formatting, Telegram send
- `src/add_company.py`: ATS discovery and YAML append utility
- `eval/eval.py`: model evaluation framework over curated dataset

## Core runtime responsibilities

1. Discover source jobs from ATS and HN.
2. Normalize records to shared job schema.
3. Filter by title and location rules.
4. Fetch detailed description text.
5. Persist jobs and detect new records.
6. Notify new jobs by Telegram grouping.
7. Enrich new jobs into structured metadata.

## Shared job record shape

Common keys used across modules:

- `company`
- `title`
- `location`
- `url`
- `posted`
- `ats`
- `description` (after description stage)

Fetcher-specific transient keys (prefixed `_`) are injected to help second-stage description fetches.

## Key runtime assumptions

- Execution from repository root for default path behavior.
- Network availability to ATS, HN, Telegram, and OpenRouter.
- Turso URL indicates remote DB mode; otherwise local SQLite.

## Non-goals

- No package installation entrypoint; scripts are run directly.
- No web app/UI surface; CLI and scheduled jobs only.
