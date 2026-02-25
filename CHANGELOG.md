# Changelog

All notable project changes are tracked in this file.

This project follows a simple Keep a Changelog style with date-based entries.

## 2026-02-25

### Added

- Description formatting enrichment output:
  - new `job_enrichments.formatted_description` column
  - best-effort LLM formatting pass in `src/enrich.py`
  - dashboard description rendering now prefers formatted text and falls back to raw `jobs.description`
- Dedicated enrichment automation workflow:
  - new `.github/workflows/enrichment.yml`
  - supports scheduled `enrich_backfill` and manual `processing_mode` options
- Tests for new formatting flow:
  - `tests/test_enrich.py`
  - repository round-trip assertion for `formatted_description`
- Dashboard job deletion capability:
  - new backend endpoint `DELETE /api/jobs/{job_url}`
  - transactional delete cascade across `job_events`, `job_tracking`, `job_enrichments`, and `jobs`
- Redis-backed dashboard API caching (optional via `REDIS_URL`):
  - cached reads for jobs list/detail/events, profile, and stats
  - write-time invalidation for tracking/profile/event/job mutations
  - configurable per-endpoint TTL env vars (`DASHBOARD_CACHE_TTL_*`)
- Scoring regression coverage:
  - new test coverage for acronym/expanded and compact skill normalization in `tests/test_match_score.py`
- New enrichment-only CLI mode for formatting gaps:
  - `--jd-reformat-missing` targets rows with `enrichment_status='ok'` and empty `formatted_description`
  - `--jd-reformat-all` refreshes formatted descriptions across all `enrichment_status='ok'` rows
  - useful for running description formatting catch-up/refresh without full re-enrichment

### Changed

- Split automation responsibilities:
  - `.github/workflows/daily_scrape.yml` now runs scrape with `--no-enrich-llm`
  - enrichment and description formatting run in separate workflow
- Enrichment runtime model config now supports two independent env vars:
  - `ENRICHMENT_MODEL`
  - `DESCRIPTION_FORMAT_MODEL`
- Prompt ownership changed to file-based runtime loading:
  - `src/enrich.py` now loads prompts from `prompts.yaml`
  - inline prompt source-of-truth strings removed from code
- Docs updated across environment, scheduling, CLI, architecture, dashboard, storage, and integration references for the new formatting/enrichment split.
- Detail drawer fit UI now uses a compact skill matrix (`matched` vs `gaps`) with one-click add-to-profile for missing skills.
- Detail drawer now includes a `Danger Zone` delete button that removes the job from DB and refreshes board state.
- Added `redis` runtime dependency for dashboard cache support.
- Dashboard Redis job-detail cache now uses bounded LRU eviction to cap memory growth:
  - new env var `DASHBOARD_CACHE_MAX_JOB_DETAILS` (default `24`, clamp `1..500`)
  - least-recently-used detail entries are evicted when capacity is exceeded
- Board page now preserves frontend in-memory state across route remounts:
  - returning `Board -> Profile -> Board` reuses jobs/stats/profile/filter/detail/event cache state
  - avoids immediate full board/detail re-fetch within freshness window
- Skill matching robustness improved across backend scoring and sidebar fit UI:
  - canonical normalization now handles punctuation, compact forms, acronyms, and parenthetical variants
  - examples: `RAG` / `rag` / `Retrieval Augmented Generation (RAG)`, `CI/CD` / `cicd`, `GenAI` / `generative ai`
  - profile add/dedupe and sidebar gap rendering now align with scorer normalization to reduce false skill gaps
- Enrichment GitHub workflow input renamed to `processing_mode` and now supports:
  - `enrich_backfill`
  - `re_enrich_all`
  - `jd_reformat_missing`
  - `jd_reformat_all`

## 2026-02-24

### Added

- Job match scoring system and profile persistence:
  - deterministic scorer in `src/match_score.py`
  - `candidate_profile` table and profile CRUD helpers in `src/db.py`
  - dashboard profile endpoints (`GET/PUT /api/profile`)
  - dashboard list/detail match payloads and `match_desc` sorting
  - CLI scrape `Match` column and `--sort-by {match|posted}`
- Dashboard theme mode system:
  - dark/light toggle in header
  - animated theme transition
  - persisted preference in browser storage
- New frontend component set for rebuilt dashboard UI:
  - `ThemeToggle`
  - ReactBits-style `SpotlightSurface`
  - ReactBits-style `ShimmerTag`
  - route shell and pages:
    - `components/layout/AppShell.tsx`
    - `pages/BoardPage.tsx`
    - `pages/ProfilePage.tsx`
- Backend detail response now includes enrichment payload from `job_enrichments`:
  - exposed under `JobDetail.enrichment`
  - parsed JSON array fields (`required_skills`, `preferred_skills`, `red_flags`)

### Changed

- Documentation now includes a full match scoring rubric and cross-links:
  - new `docs/dashboard/match-scoring.md`
  - updates across README, docs index, dashboard, architecture, CLI, storage, quickstart, glossary, and references
- Full dashboard frontend redesign (`src/dashboard/frontend/*`) with Himalayas-inspired professional visual direction.
- Replaced prior frontend structure with:
  - route-based dashboard navigation (`/` board, `/profile` profile)
  - dedicated profile page with manual save flow and tokenized editors
  - kanban board + drag/drop status transitions
  - right-side job detail drawer
  - inline tracking edits synced to DB via `PATCH /api/jobs/{job_url}/tracking`
  - enrichment rendering in job detail panel
- Updated dashboard documentation set and references to match current behavior and component layout.
- Replaced `withdrawn` board stage with `staging` stage in the dashboard pipeline order (`Backlog -> Staging -> Applied -> Interviewing -> Offer -> Rejected`).
- Updated lifecycle status handling across frontend/backend/CLI to support `staging` and removed `withdrawn` from selectable status transitions.
- Added legacy status normalization in dashboard repository so existing `withdrawn` rows are surfaced as `rejected` in board/detail/stats responses.

## 2026-02-23

### Added

- DB-first source-management docs: `docs/configuration/company-sources.md`.
- New CLI docs:
  - `docs/cli/sources.md`
  - `docs/cli/lifecycle.md`
- Root project changelog (`CHANGELOG.md`).
- Job tracker dashboard stack:
  - FastAPI backend (`src/dashboard/backend/`)
  - React/Vite frontend (`src/dashboard/frontend/`)
  - Dashboard docs under `docs/dashboard/`
- New frontend interaction components:
  - Spotlight hover cards for stats (`SpotlightCard`)
  - Motion-driven column and timeline transitions (`framer-motion`)
  - Drag/drop micro-interactions (drop-target glow, drag state, moved-card pulse)
- New DB tracking tables:
  - `job_tracking`
  - `job_events`

### Changed

- Full documentation refresh aligned to current architecture:
  - `src/cli.py` as single entrypoint
  - split command modules in `src/commands/*`
  - split service modules in `src/services/*`
  - DB-only company source registry (`company_sources`)
- Updated `README.md`, quickstart, docs index, architecture, data flow, storage, operations, and references.
- Updated eval docs to reflect `crawl --source-db` and DB-backed source loading.
- Updated runbook with lifecycle pruning and source-registry operational procedures.
- Added dashboard command/run instructions to `README.md` and docs index.
- Refined dashboard UX from Stitch exports baseline into production-ready UI behaviors and documented the final interaction model.

### Removed

- YAML-based company-source documentation references.
- Legacy `src/scrape.py` references from docs.

## 2026-02-21

### Added

- Structured documentation set under `docs/`.
- CLI, architecture, integrations, operations, evaluation, and reference pages.

### Changed

- `README.md` converted to concise command + docs gateway.

## Changelog Process

For every behavior, interface, or operational change:

1. Add/update docs in `docs/`.
2. Append an entry here in `CHANGELOG.md`.
3. Append docs-only details in `docs/reference/changelog-docs.md`.
4. Include date and clear Added/Changed/Removed notes.
