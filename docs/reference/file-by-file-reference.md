# File-by-File Technical Reference

This page summarizes tracked project files and their runtime roles.

## Root files

### `.env.example`

- Template for required runtime env vars.
- Used by local setup guidance and runtime docs.

### `.github/workflows/daily_scrape.yml`

- Scheduled/manual CI execution of daily scraper.
- Runs `uv run python src/cli.py scrape --no-enrich-llm`.

### `.github/workflows/enrichment.yml`

- Scheduled/manual CI execution of enrichment pipeline.
- Runs `uv run python src/cli.py scrape --enrich-backfill` (or manual `--re-enrich-all` / `--jd-reformat-missing` / `--jd-reformat-all`).

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

- Runtime source of truth for enrichment and description-format prompts.
- Loaded directly by `src/enrich.py`.

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

### `src/match_score.py`

- Deterministic profile-based job fit scoring rubric.
- Shared by dashboard API and CLI scrape rendering.

### `src/dashboard/backend/main.py`

- FastAPI app and dashboard REST endpoints.

### `src/dashboard/backend/repository.py`

- Dashboard data-access layer for jobs/tracking/events/stats/profile.
- Joins and maps `job_enrichments` into detail response payload.
- Computes `match` payload from `candidate_profile` + job data.

### `src/dashboard/backend/schemas.py`

- Pydantic request/response contracts for dashboard API.
- Includes nested job enrichment model under `JobDetail.enrichment`.
- Includes `CandidateProfile` and `JobMatchScore` contracts.

### `src/dashboard/backend/service.py`

- URL decoding and patch normalization helpers.

### `src/dashboard/frontend/*`

- React/Vite dashboard app (route-based Board + Profile pages, dual-theme UI).
- Includes `framer-motion` animations for board and drawer transitions.
- Key component responsibilities:
  - `App.tsx`: route registration and theme persistence.
  - `components/layout/AppShell.tsx`: shared app shell and top navigation tabs (`Board`, `Profile`).
  - `pages/BoardPage.tsx`: board orchestration, data fetches, status patching, drawer interaction.
  - `pages/ProfilePage.tsx`: profile load/edit/save workflow with manual save and dirty-state UX.
  - `components/KanbanColumn.tsx`: status column drop zone + card list frame.
  - `components/JobCard.tsx`: draggable job summary card.
  - `components/DetailDrawer.tsx`: detail panel with tracking edits, enrichment, timeline.
  - `components/ThemeToggle.tsx`: dark/light switch.
  - `components/reactbits/SpotlightSurface.tsx`: pointer-reactive spotlight wrapper.
  - `components/reactbits/ShimmerTag.tsx`: animated metadata/skill chip.

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
