# Documentation Changelog

## 2026-02-27

- Noted the new column scrollbar behavior so each pipeline stage becomes scrollable when overflowed, and highlighted it in `docs/dashboard/frontend-ui.md` and `docs/dashboard/overview.md`.

## 2026-02-26

- Documented the refreshed board toolbar controls and scrolling behavior in `docs/dashboard/frontend-ui.md`, including the new Controls capsule, fixed-width action buttons, and two-viewport vertical scroll experience.
- Added a manual job workflow note to `docs/dashboard/frontend-ui.md` explaining how manual creates enqueue backend enrichment/formatting while immediately opening the drawer and silently refreshing the kanban view.
- Expanded `docs/dashboard/overview.md` with a “Board interaction primer” that calls out the new control capsule, consistent action button spacing, vertical scroll behavior, and default collapsed rail with tooltips.

## 2026-02-25

- Performed docs-audit cleanup for stale dashboard/scrape references:
  - added missing `recruitee` coverage in `docs/cli/scrape.md` data-source list
  - added `recruitee` parser support note in `docs/cli/sources.md` import behavior
  - corrected `formatted_description` docs from "plain text" to "Markdown" across backend API, storage, and enrichment integration docs
  - updated dashboard UI docs for current side-rail navigation model (replacing old top-tab wording)
  - expanded profile API body docs to include `education` and legacy degree fields
  - corrected scoring docs for stacked eligibility penalties (`canada_eligible` + visa mismatch)
  - refreshed file-reference docs to include `AnalyticsPage` and markdown description rendering path
  - clarified `lifecycle` docs that `withdrawn` remains a prune-protected legacy status, not a settable status
- Updated scoring docs for seniority targeting:
  - `intern`/`co-op` and `senior`/`lead` now documented as equally penalized in match scoring
  - seniority title heuristics updated to include `co-op` / `coop` under intern detection
- Added analytics documentation coverage:
  - new `GET /api/analytics/funnel` endpoint details in backend API docs
  - frontend route and interaction docs for `/analytics`
  - dashboard overview updates for funnel workflow and nav tab
  - environment docs update for `DASHBOARD_CACHE_TTL_ANALYTICS_FC`
  - documented Phase 1 analytics modules:
    - delta comparisons vs previous window
    - weekly goals and progress bars
    - actionable alerts and goal-target query params
  - documented Phase 2 analytics modules:
    - cohort funnel table (weekly cohorts by posted date)
    - source quality rankings (ATS + companies)
    - analytics-to-board drill-down using URL filters (`ats`, `company`, `posted_after`, `posted_before`)
  - documented Phase 3 analytics modules:
    - forecast simulator with throughput scenario input
    - confidence-band projections for 7-day and 30-day horizons
    - `forecast_apps_per_week` analytics API query parameter
  - documented Recruitee ATS support across:
    - ATS integrations reference
    - company-sources configuration
    - database storage validation notes
    - add-company probe coverage
- Added dashboard cache documentation:
  - Redis-backed read-through cache behavior in backend API docs
  - environment variable references for `REDIS_URL` and `DASHBOARD_CACHE_TTL_*`
  - bounded LRU job-detail cache control via `DASHBOARD_CACHE_MAX_JOB_DETAILS`
- Expanded dashboard scoring documentation:
  - added canonical/fuzzy skill normalization rules in `docs/dashboard/match-scoring.md`
  - documented acronym, compact-form, and parenthetical-equivalence examples
- Added enrichment formatting-only recovery documentation:
  - new CLI modes `--jd-reformat-missing` and `--jd-reformat-all` in scrape CLI docs
  - scheduling and runbook updates for GitHub Actions manual `processing_mode` values:
    `enrich_backfill`, `re_enrich_all`, `jd_reformat_missing`, `jd_reformat_all`
  - integration docs updated with selection behavior (`ok` enrichment + missing formatted text)
- Updated dashboard frontend documentation:
  - board route state persistence and remount cache hydration behavior
  - detail drawer prefetch/cache usage notes
  - skill alignment fuzzy/canonical matching behavior notes
- Updated dashboard overview with performance notes:
  - frontend in-memory board cache reuse on route return
  - backend Redis LRU detail-cache limit behavior
- Updated dashboard backend API docs with `DELETE /api/jobs/{job_url}` and transactional linked-record deletion behavior.
- Updated dashboard frontend UI docs to include:
  - compact skill-alignment matrix in the detail drawer
  - one-click add missing skill to profile from the drawer
  - destructive job deletion (`Danger Zone`) flow
- Documented split automation model:
  - scrape-only workflow (`daily_scrape.yml`)
  - enrichment/formatting workflow (`enrichment.yml`)
- Updated prompt documentation to reflect `prompts.yaml` as runtime source of truth (not reference-only).
- Updated environment docs with `DESCRIPTION_FORMAT_MODEL` and workflow-specific secrets.
- Updated enrichment integration docs to include two-pass extraction + formatting behavior and non-fatal formatting failures.
- Updated storage docs with `job_enrichments.formatted_description` column and `minimum_degree` coverage.
- Updated dashboard backend/frontend docs to include `formatted_description` consumption and fallback behavior.
- Updated CLI and architecture flow docs to reflect split scrape vs enrichment execution paths.

## 2026-02-25

- Added dedicated scoring rubric doc: `docs/dashboard/match-scoring.md` with exact inputs, weights, penalties, bands, and confidence rules.
- Updated dashboard docs to include profile-based match scoring:
  - overview
  - backend API
  - frontend UI
- Updated architecture/data-flow docs to include score computation and profile save/re-rank flow.
- Updated CLI scrape docs with match-rubric linkage and sort behavior context.
- Updated storage and reference docs to include `candidate_profile` and `src/match_score.py`.
- Updated README/docs index/quickstart links for scoring discoverability.
- Updated dashboard docs to match rebuilt frontend architecture and interaction model:
  - kanban + right detail drawer layout
  - inline tracking patch flow
  - enrichment display in detail pane
  - ReactBits-style spotlight/shimmer components
- Added dark/light theme system docs:
  - header toggle
  - persisted theme preference
  - reduced-motion-safe theme transition behavior
- Updated backend API docs to document enrichment payload in `GET /api/jobs/{job_url}`.
- Updated architecture and file reference pages to remove old frontend component references and reflect current component set.
- Updated README dashboard highlights to match current shipped behavior.
- Updated dashboard docs for route-based frontend architecture:
  - top nav tabs (`Board`, `Profile`)
  - dedicated `/profile` page replacing inline profile section
  - page/component map updates for `AppShell`, `BoardPage`, and `ProfilePage`
- Updated quickstart and overview notes for Turso-only dashboard backend requirement.
- Updated dashboard/lifecycle/storage/architecture docs for new `staging` status and board order replacing `withdrawn` as an active selectable stage.

## 2026-02-23

- Fully aligned docs to DB-only source registry architecture (`company_sources`).
- Removed YAML source documentation and replaced with DB source-management docs.
- Added CLI references for:
  - `cli.py sources`
  - `cli.py lifecycle`
- Updated `README.md`, docs index, quickstart, architecture, data flow, storage, runbook, and reference pages for split command/service architecture.
- Corrected eval docs to use `crawl --source-db` (removed stale `--config` references).
- Added lifecycle retention semantics (`application_status`, prune behavior, protected statuses).
- Expanded file-by-file reference for `src/commands/*` and `src/services/*` modules.
- Added changelog governance notes in operations runbook and project changelog.
- Added dashboard documentation set:
  - `docs/dashboard/overview.md`
  - `docs/dashboard/backend-api.md`
  - `docs/dashboard/frontend-ui.md`
- Updated README and docs index to include dashboard workflows.
- Expanded dashboard docs with final UI architecture and interaction details:
  - Spotlight cards and visual token system
  - `framer-motion`-based entrance/layout/exit transitions
  - drag-and-drop micro-interactions for kanban columns and cards
- Updated architecture and file reference pages to include dashboard frontend component roles and dependency notes.

## 2026-02-21

- Replaced root README with concise gateway + docs map.
- Added structured `docs/` reference architecture.
- Added dedicated CLI docs for `cli.py scrape`, `add_company.py`, and `eval.py`.
- Added environment, architecture, data flow, storage, integrations, operations, troubleshooting, and evaluation references.
- Added file-by-file tracked file reference and glossary.
- Aligned docs to code-observed defaults and operational quirks.
