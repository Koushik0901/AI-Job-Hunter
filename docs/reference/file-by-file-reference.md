# File-by-File Technical Reference

This page covers every tracked project file except local tooling config intentionally excluded from end-user docs.

## Root files

### `.env.example`

- Purpose: template for required runtime env vars.
- Consumers: `src/scrape.py`, `src/notify.py`, `eval/eval.py`.

### `.github/workflows/daily_scrape.yml`

- Purpose: scheduled and manual CI execution of daily scraper.
- Risk if changed: run frequency/secrets wiring may break.

### `.gitignore`

- Purpose: avoid committing secrets, local dbs, eval outputs, virtual env artifacts.

### `.python-version`

- Purpose: pin Python runtime expectation (`3.12`).

### `CLAUDE.md`

- Purpose: agent/operator context and conventions.
- Runtime impact: none; contributor guidance only.

### `README.md`

- Purpose: user entrypoint linking to full docs.

### `companies.yaml`

- Purpose: source registry for ATS scrape targets.
- Runtime impact: primary input to scrape.

### `prompts.yaml`

- Purpose: reference copy of enrichment prompts.
- Runtime impact: none directly (runtime prompts live in `src/enrich.py`).

### `pyproject.toml`

- Purpose: dependency and project metadata for uv.

### `setup_scheduler.ps1`

- Purpose: register Windows Task Scheduler automation.

### `uv.lock`

- Purpose: locked dependency resolution for reproducible installs.

## Source code (`src/`)

### `src/scrape.py`

- CLI entrypoint and orchestration.
- Includes filters, ATS checks, company import flow.

### `src/add_company.py`

- Interactive/non-interactive ATS discovery + YAML append utility.

### `src/fetchers.py`

- ATS/HN source fetchers, normalizers, description retrieval, retries.

### `src/db.py`

- Local SQLite and Turso-backed persistence abstractions.

### `src/notify.py`

- Env load helper, telegram message composition/sending.

### `src/enrich.py`

- Pydantic schema and OpenRouter-based enrichment pipeline.

## Eval (`eval/`)

### `eval/README.md`

- Eval user guide and command overview.

### `eval/eval.py`

- CLI for crawl/build/cost/run/report.
- Includes checkpointing and scoring logic.

### `eval/dataset.yaml`

- Dataset file with `db_jobs` (generated) and `manual_jobs` (editable).

### `eval/eval_analysis.ipynb`

- Notebook for deep result analysis and plotting.

## Intentional omission

- `.claude/settings.local.json` is excluded from end-user docs by documentation policy.
