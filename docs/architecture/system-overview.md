# System Overview

## Major modules

- `src/cli.py`: top-level CLI entrypoint and command router.
- `src/commands/scrape_jobs.py`: scrape pipeline command implementation.
- `src/commands/company_sources.py`: source registry command implementation.
- `src/commands/job_lifecycle.py`: lifecycle status and retention command implementation.
- `src/services/scrape_service.py`: filtering rules, scrape orchestration helpers, table rendering.
- `src/services/probe_service.py`: ATS slug probing and job-count probes.
- `src/services/company_source_service.py`: source import/list helpers.
- `src/fetchers.py`: ATS/HN ingestion, normalizers, description retrieval.
- `src/db.py`: SQLite/Turso persistence and schema migrations.
- `src/enrich.py`: OpenRouter + LangChain + Pydantic extraction pipeline.
- `src/notify.py`: dotenv loader and Telegram send pipeline.
- `src/add_company.py`: interactive/non-interactive ATS discovery + DB source upsert.
- `eval/eval.py`: model evaluation framework over crawled dataset.

## CLI architecture

Top-level command:

```bash
uv run python src/cli.py <command>
```

Supported commands:

- `scrape`: daily scrape + optional description/enrichment/notify.
- `sources`: source registry (`list`, `enable`, `disable`, `check`, `import`).
- `lifecycle`: status + retention (`set-status`, `prune`).

## Core runtime responsibilities

1. Discover source jobs from ATS and HN.
2. Normalize records to shared job schema.
3. Filter by title and location rules.
4. Fetch detailed description text.
5. Persist jobs and classify new vs updated.
6. Notify Telegram for new jobs.
7. Enrich new or backfilled jobs into structured metadata.
8. Maintain source registry and lifecycle state in DB.

## Shared job record shape

Common keys used across modules:

- `company`
- `title`
- `location`
- `url`
- `posted`
- `ats`
- `description`

Fetcher-specific transient keys (prefixed `_`) are injected to support second-stage description fetches.

## Key runtime assumptions

- Execution from repository root for default path behavior.
- Network availability to ATS, HN, Telegram, and OpenRouter.
- `TURSO_URL` indicates remote DB mode; otherwise local SQLite.
- Source of truth for scrape targets is DB table `company_sources`.

## Non-goals

- No web app/UI surface; CLI and scheduled jobs only.
- No backward compatibility shim for removed `src/scrape.py` legacy entrypoint.
