# Documentation Changelog

## 2026-02-25

- Added dashboard cache documentation:
  - Redis-backed read-through cache behavior in backend API docs
  - environment variable references for `REDIS_URL` and `DASHBOARD_CACHE_TTL_*`
  - bounded LRU job-detail cache control via `DASHBOARD_CACHE_MAX_JOB_DETAILS`
- Expanded dashboard scoring documentation:
  - added canonical/fuzzy skill normalization rules in `docs/dashboard/match-scoring.md`
  - documented acronym, compact-form, and parenthetical-equivalence examples
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

## 2026-02-24

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
