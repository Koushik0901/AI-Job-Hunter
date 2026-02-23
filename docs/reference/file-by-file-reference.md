# File-by-File Technical Reference

This page summarizes tracked project files and their runtime roles.

## Root files

### `.env.example`

- Template for required runtime env vars.
- Used by local setup guidance and runtime docs.

### `.github/workflows/daily_scrape.yml`

- Scheduled/manual CI execution of daily scraper.
- Runs `uv run python src/cli.py scrape`.

### `.gitignore`

- Excludes secrets, local DBs, eval outputs, and virtual env artifacts.

### `.python-version`

- Pins expected Python runtime (`3.12`).

### `CLAUDE.md`

- Agent/operator context and conventions.
- No runtime effect.

### `CHANGELOG.md`

- Project-level changelog (code + behavior + docs highlights).

### `README.md`

- Main entrypoint and command/docs map.

### `prompts.yaml`

- Reference copy of enrichment prompt text.
- Runtime prompt source remains `src/enrich.py`.

### `pyproject.toml`

- Dependency and project metadata for `uv`.

### `setup_scheduler.ps1`

- Registers Windows Task Scheduler automation.

### `uv.lock`

- Locked dependency resolution for reproducible installs.

## Source code (`src/`)

### `src/cli.py`

- CLI entrypoint and command router (`scrape`, `sources`, `lifecycle`).

### `src/add_company.py`

- Interactive/non-interactive ATS discovery + DB source upsert helper.

### `src/commands/scrape_jobs.py`

- `scrape` command registration + execution path.

### `src/commands/company_sources.py`

- `sources` command registration + execution path.

### `src/commands/job_lifecycle.py`

- `lifecycle` command registration + execution path.

### `src/services/scrape_service.py`

- Title/location filters, slug extraction, scrape orchestration helpers, Rich table rendering.

### `src/services/probe_service.py`

- ATS probe definitions + concurrent slug probing helpers.

### `src/services/company_source_service.py`

- Source import parsers and DB upsert/list helpers.

### `src/fetchers.py`

- ATS/HN source fetchers, normalizers, description retrieval, retries.

### `src/db.py`

- Local SQLite and Turso-backed persistence abstractions.
- Schema creation/migration and CRUD helpers.

### `src/notify.py`

- `.env` loader and Telegram message composition/sending.

### `src/enrich.py`

- Pydantic schema + OpenRouter/LangChain enrichment pipeline.
- Rate-limit stop/resume semantics.

## Eval (`eval/`)

### `eval/README.md`

- Eval workflow and command overview.

### `eval/eval.py`

- Eval CLI (`crawl/build/cost/run/report`).
- Checkpointing, scoring, and reporting logic.

### `eval/dataset.yaml`

- Dataset with generated `db_jobs` + curated `manual_jobs`.

### `eval/eval_analysis.ipynb`

- Notebook for deeper result analysis and plotting.

## Documentation (`docs/`)

- CLI, architecture, storage, integrations, operations, troubleshooting, eval, and references.
- `docs/reference/changelog-docs.md` tracks documentation-specific updates.

## Intentional omission

- `.claude/settings.local.json` is excluded from end-user docs by policy.
