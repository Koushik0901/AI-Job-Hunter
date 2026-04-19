# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

AI Job Hunter is a daily ML/AI/DS job-search workflow system. It scrapes 100+ companies across multiple ATS providers, filters for Canada/Remote roles, enriches descriptions with an LLM, scores matches against a candidate profile, and surfaces the pipeline in a React dashboard plus a Chrome extension that autofills application forms.

Stack: Python (FastAPI, LangChain, OpenRouter), React/Vite/TypeScript, Redis cache, SQLite or Turso (libsql cloud), Telegram for notifications, Chrome Manifest V3. See Architecture below for the three surfaces that share the DB.

## First-time setup

```bash
uv sync                                  # install Python deps (pyproject.toml + uv.lock)
cp .env.example .env                     # then fill in OPENROUTER_API_KEY, TURSO_*, TELEGRAM_*, etc.
cd src/dashboard/frontend && npm install && cd -
cd src/chrome-extension && npm install && cd -
```

First backend or CLI run creates `jobs.db` and applies `init_db()` auto-migrations. If `REDIS_URL` points at localhost and Docker is available, the backend auto-starts a Redis container on startup.

## Commands

Run everything from the repo root unless noted. Python tooling is managed by `uv`.

**Backend / worker / frontend / extension / CLI:**
```bash
uv run ai-job-hunter-backend              # FastAPI dashboard (default :8000)
uv run ai-job-hunter-worker            # Background task worker
cd src/dashboard/frontend && npm install && npm run dev  # React SPA (Vite, :5173)
cd src/chrome-extension && npm install && npm run build  # MV3 extension → dist/; npm run dev for watch
uv run ai-job-hunter --help
```

**CLI commands** (entry: `src/ai_job_hunter/cli.py`, subcommands in `src/ai_job_hunter/commands/`):
```bash
uv run ai-job-hunter scrape                          # full scrape + enrich + notify
uv run ai-job-hunter scrape --no-enrich-llm          # scrape only (matches daily CI)
uv run ai-job-hunter scrape --enrich-backfill        # enrich rows missing enrichment
uv run ai-job-hunter scrape --re-enrich-all          # re-enrich everything
uv run ai-job-hunter scrape --jd-reformat-missing    # reformat descriptions
uv run ai-job-hunter sources list
uv run ai-job-hunter sources check <company>         # probe one company's ATS
uv run ai-job-hunter daily-briefing [--refresh-only|--send-now]
uv run python -m ai_job_hunter.add_company "<Company Name>"        # discover ATS + append to companies.yaml
```

**Tests & lint:**
```bash
uv run pytest tests/                                     # all
uv run pytest tests/test_foo.py::TestClass::test_method  # single test
uv run pytest -m live_network tests/                     # opt-in: hits real ATS endpoints
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

## Architecture

**Three surfaces over one DB:**

1. **Scraper/CLI** → fetches Greenhouse/Lever/Ashby/Workable/SmartRecruiters/Recruitee/Teamtailor + HN "Who is Hiring?", enriches via OpenRouter, notifies via Telegram. Scheduled by GitHub Actions (`.github/workflows/daily_scrape.yml` at 17:00 UTC, `enrichment.yml` 30 min later).
2. **Dashboard** — FastAPI backend (`src/ai_job_hunter/dashboard/backend/`) + React/Vite SPA (`src/dashboard/frontend/`). Six pages: Today, Board, Insights, Recommend, Agent, Settings.
3. **Chrome extension** (`src/chrome-extension/`) — MV3 autofill + side panel for ATS forms.

**Python layout.** Package lives at `src/ai_job_hunter/` and is installed (editable) by `uv sync` via `pyproject.toml`. Entry points: `ai-job-hunter` (CLI), `ai-job-hunter-backend`, `ai-job-hunter-worker`. Tests add `src/` to `sys.path` via `tests/conftest.py`.

**Data flow.**
`scrape_service` → `fetchers` → `db.save_jobs()` → `enrich.run_enrichment_pipeline()` (structured LLM extraction into `job_enrichments`) → `enrich.run_description_reformat_pipeline()` (Markdown reformat) → `notify.send_telegram()` → scoring in `match_score.py` → `advisor.build_recommendation()`.

**Dashboard read path (fast path).** Request → `main.py` route → `repository.py` reads from `job_dashboard_snapshots` (denormalized projection) preferentially → Redis cache (`cache.py`, namespace `dashboard:v3`) wraps response with ETag + `stale-while-revalidate=30`. Writes go through `service.py` and enqueue snapshot refresh via `task_queue.py` rather than rebuilding inline. Request handlers should **never** run heavy work inline — enqueue through `task_queue` / `workspace_operation_service` and return a `WorkspaceOperation` id; the frontend streams status via `GET /api/operations/{id}/events` (SSE) and dashboard-wide invalidations via `GET /api/events/stream`.

**Scoring.** `match_score.py` separates `raw_fit` (content alignment) from cohort-calibrated `rank_score` (stored as `score`). `SKILL_ALIASES` + `normalize_skill()` in `match_score.py` are the single source of truth. Backend exposes the alias dict via `GET /api/meta/skill-aliases`; frontend fetches once via `DashboardDataContext` and threads `skillAliases` into `skillUtils.ts` helpers (`normalizeSkill`, `fuzzySkillsMatch`, etc.) so all surfaces share the same canonical table.

**Shared env + timezone helpers.** `src/ai_job_hunter/env_utils.py` is the single source for `load_dotenv()`, `local_timezone()`, `local_timezone_name()`, `local_today()`, `now_iso()`. `src/ai_job_hunter/notify.py` and `src/ai_job_hunter/dashboard/backend/utils.py` re-export via thin wrappers. Default timezone fallback is `UTC`; user supplies `JOB_HUNTER_TIMEZONE` in `.env`.

**Frontend type generation.** `src/dashboard/frontend/package.json` exposes `npm run generate:types` which runs `openapi-typescript` against a live backend at `http://localhost:8000/openapi.json` and writes `src/types.generated.ts`. The hand-maintained `src/types.ts` retains UI-only types and re-exports what's needed. Regenerate after backend schema changes; not CI-enforced.

**Chrome extension autofill.** Two flows — popup (`AUTOFILL_PAGE`) and side panel (`SIDEPANEL_AUTOFILL` with artifact IDs) — both relay through `background.ts` as `DO_AUTOFILL` to a content script that dispatches to a per-ATS module (`greenhouse/lever/ashby/workable/smartrecruiters/generic`). Side panel additionally uploads resume/cover-letter PDFs via `DataTransfer` into `<input type="file">` elements. Profile cached 5 min in `chrome.storage.session`. Artifact lookup by current tab URL: `GET /api/artifacts/by-url?url=...`.

**CORS.** Backend allows `localhost`/`127.0.0.1`/`host.docker.internal` any port plus `chrome-extension://*` via `allow_origin_regex`.

## Key files

- `src/ai_job_hunter/cli.py`, `src/ai_job_hunter/commands/` — CLI entry + subcommand registry
- `src/ai_job_hunter/env_utils.py` — shared `.env` loader + timezone helpers
- `src/ai_job_hunter/db.py` — schema, `_TursoConnection` (sqlite3-compatible wrapper over Turso hrana HTTP), auto-migration via `ALTER TABLE ... ADD COLUMN` in `init_db()`
- `src/ai_job_hunter/fetchers.py`, `src/ai_job_hunter/services/scrape_service.py` — ATS fetchers + filtering
- `src/ai_job_hunter/enrich.py`, `prompts/*.yaml` — LLM enrichment + reformatter prompts
- `src/ai_job_hunter/match_score.py` — scoring + `SKILL_ALIASES`
- `src/ai_job_hunter/dashboard/backend/{main,repository,service,advisor,agent,artifacts,cache,task_queue,worker}.py`
- `src/dashboard/frontend/src/{App.tsx, api.ts, contexts/DashboardDataContext.tsx, pages/*, components/{JobCard,RecommendJobCard,DetailDrawer,ArtifactEditor}.tsx}`
- `src/chrome-extension/src/{background,content/index,content/utils,content/<ats>,popup/Popup,sidepanel/SidePanel}.ts(x)`
- `companies.yaml` — ATS configs (source of truth)
- `.impeccable.md` — formal design system reference ("The Navigator")

## Key DB tables

`jobs`, `job_enrichments`, `job_tracking`, `job_match_scores` (raw + rank semantics, bands, reasons JSON), `candidate_profile` (includes autofill fields + `score_version` bumped on profile change to invalidate scores), `job_dashboard_snapshots` (read model), `job_processing_state`, `workspace_operations`, `base_documents`, `application_queue` (unique on `job_id`), `job_artifacts` (versioned; `is_active=0` archives old), `job_suppressions`, `job_events`, `company_sources`.

## Environment

Copy `.env.example` → `.env`. Critical vars:

| Var | Purpose |
|---|---|
| `TURSO_URL` / `TURSO_AUTH_TOKEN` | Cloud DB; overrides `DB_PATH` |
| `DB_PATH` | Local SQLite fallback (default `jobs.db` in cwd) |
| `REDIS_URL` | Dashboard cache; auto-starts a Docker Redis when pointing to localhost |
| `OPENROUTER_API_KEY` | LLM enrichment + agent + artifacts |
| `ENRICHMENT_MODEL` (`openai/gpt-oss-120b`), `DESCRIPTION_FORMAT_MODEL`, `AGENT_MODEL` (`openai/gpt-4o-mini`), `ARTIFACT_MODEL` (`openai/gpt-4o`) | Per-pipeline model overrides |
| `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` | Notifications |
| `JOB_HUNTER_TIMEZONE` | Default `America/Edmonton` |
| `DASHBOARD_CACHE_TTL_*` | Per-endpoint Redis TTLs (seconds) |
| `DASHBOARD_CACHE_DISABLED=1` | Bypass cache for local debugging / CI |

## Gotchas

- **Windows CP1252 console.** Avoid non-ASCII in `console.print()` / stdout — use `->` not `→`, no emoji. Telegram receives Unicode fine.
- **Path resolution** uses `Path.cwd()` for `.env`, `companies.yaml`, `jobs.db`. Always run from repo root.
- **React-controlled inputs.** In the Chrome extension, `fillField()` in `src/chrome-extension/src/content/utils.ts` uses the native React property setter (`Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set`) + dispatches `input`/`change`/`blur`. Plain `.value =` does **not** work on React-controlled inputs.
- **Enqueue, don't block.** Dashboard request handlers must not run scraping, enrichment, PDF export, or artifact LLM calls inline — use `task_queue` / `workspace_operation_service` and return an operation id.
- **Profile version invalidates scores.** Bump `candidate_profile.score_version` on any profile mutation that should change ranking; `repository.recompute_match_scores()` gates on it.
- **Snapshots, not joins.** Prefer `job_dashboard_snapshots` for list/detail reads. Inline re-joins are slow and fight the cache.
- **Recommend page** only shows `not_applied` jobs (`RecommendPage.tsx`). Don't accidentally broaden.
- **Artifact versioning.** `save_artifact()` auto-archives the previous active row of the same `(job_id, artifact_type)` — don't manually flip `is_active`.
- **Daily scrape job** in CI uses `scrape --no-enrich-llm`; enrichment runs in a separate workflow 30 min later. Keep them decoupled.
- **`init_db()` auto-migration** runs on every backend/CLI start. Adds new columns via `ALTER TABLE ... ADD COLUMN` wrapped in try/except — safe to add columns, but do not rename or drop columns this way; write a dedicated migration.
- **Snapshot fallback.** `repository.list_jobs()` and related reads fall back to live joins when `job_dashboard_snapshots` is stale or absent. After bulk writes (scrape, re-enrich, profile mutation), enqueue a `dashboard_snapshot_refresh` task so the fast path stays fast.
- **Tests use editable install.** `uv sync` installs the `ai_job_hunter` package in editable mode. `tests/conftest.py` also adds `src/` to `sys.path` as a fallback. Import via `from ai_job_hunter.foo import ...`.

## Known gaps

- Insights conversion metrics query a `job_outcomes` table rather than `job_tracking.status` and render as zeros.
- Role-family trends section on Insights is a heading-only stub.
- Artifact generation endpoints are async via task queue, but the underlying LLM call itself is synchronous (10–25 s) — no streaming to the frontend yet.

## Design system ("The Navigator")

The dashboard follows a formal, calm aesthetic. Rules below are load-bearing for any UI change.

- **Fonts**: "Plus Jakarta Sans" (headings), "Inter" (body).
- **Palette**: background `#f6fafe`; tonal surface layers (`surface_container_lowest` `#ffffff`, `_low` `#f0f4f8`, `_highest` `#dfe3e7`); violet primary `#630ed4`, secondary `#0058be`; 45° primary→secondary gradient reserved for AI highlights and primary actions.
- **No-line rule**: avoid 1px solid borders for sectioning — use tonal shifts + spacing. Ghost borders use `outline_variant` at 20% opacity.
- **Glass**: modals/nav use `surface_container_lowest` at 70% opacity + `20px` backdrop-blur.
- **Shadows**: ambient only, e.g. `0 8px 32px rgba(23,28,31,0.04)`.
- **Buttons**: primary = gradient, 12px radius, no border; secondary = `surface_container_highest` pebble; hover = 10% white overlay.
- **Match cards**: no internal dividers; 1.5rem between title and metadata; match score = circular glass chip with inner-shadow glow.
- **Motion**: respect `prefers-reduced-motion` globally; global `:focus-visible` rings for a11y.
- **Dark + light**: both supported via tonal layering, not color inversion.

Design principles: systems over surfaces, information density with clarity, calm authority, performance as a feature. `Board` and dedicated job-detail pages are the visual benchmark.

## Additional context files

- `README.md` — user-facing product pitch and workflow narrative.
- `.impeccable.md` — formal design-system source of truth (extended Navigator spec).
- `companies.yaml` — ATS configs, source of truth for sources.
- `prompts/*.yaml` — LLM enrichment and reformatter prompts.
- `.env.example` — full env var list with example values.
