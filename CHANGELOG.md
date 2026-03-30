# Changelog

## 2026-03-30

### Changed
- Simplified the manual-add modal so it now behaves like a compact form instead of a feature explainer.
- Required fields are now marked directly in the form, with lightweight validation and invalid highlighting on save attempt.
- Duplicate-aware manual add now uses concise messaging and reopens the existing record without extra explanatory banners or footer copy.

### Fixed
- Hardened assistant-surface cache invalidation so `Today` and `Insights` stay fresh after tracking changes, events, suppress/unsuppress, decisions, deletes, and action updates.
- Cleaned up later-stage recommendation wording so `applied`, `interviewing`, and `offer` jobs no longer fall back to early-stage “fit is weak” style reasoning.
- Verified the retry-processing drawer flow end to end with a real failed-processing state and retry transition.

### Docs
- Refreshed `README.md`, `CHANGELOG.md`, and `TODO.md` to match the current dashboard structure, processing model, caching behavior, and backlog status.

## 2026-03-29

### Added
- Durable job processing state with `processing`, `ready`, and `failed` states visible in the dashboard.
- Retry-processing API and drawer retry action for failed background enrichment / formatting / recommendation work.
- Redis + `ETag` cache parity for `Today`, daily briefing, action queue, conversion, source quality, profile gaps, and profile insights.
- Stage-aware recommendation presentation fields for narrative later-stage guidance.

### Changed
- `Today` was reworked into an operational landing page organized around `Must do today`, `Follow up today`, `Review later`, and `Top notes`.
- Manual add now opens instantly while background processing runs asynchronously.
- Manual add now prevents duplicates by exact URL and by normalized title + company + location + posted-month matching.
- Job descriptions are normalized before persistence and before enrichment sees the text.
- Clicking outside the drawer now closes it consistently on desktop and mobile.

### Removed
- Application-brief UI and API surface from the active dashboard product flow.

## 2026-03-28

### Added
- Interview-focused advisor layer with interview-likelihood scoring, recommendation reasons, manual decision overrides, action queue persistence, outcome analytics, and profile-gap insights.
- Daily briefing system with:
  - persisted one-row-per-day briefing state
  - dashboard Daily Briefing panel
  - Telegram daily briefing formatter and send path
  - same-day Telegram send dedupe
  - CLI entrypoint: `uv run python src/cli.py daily-briefing`

### Changed
- Workspace scrape, enrich, and JD reformat flows now refresh the stored daily briefing after successful runs.
- Dashboard is now split into `Today`, `Board`, and `Insights`, with assistant and analytics surfaces moved off the Kanban page.
- Board drawer keeps the core evaluation workflow but is reordered for easier scanning, with timeline and cleanup actions pushed to the bottom.
- `.env.example` now documents `JOB_HUNTER_TIMEZONE` for local-day briefing generation and Telegram dedupe.

### Notes
- The daily briefing is sourced from the same recommendation, action, and profile analytics already shown in the dashboard, so Telegram and the board use the same canonical payload.
- Scheduling remains external to the backend process; the repo provides the CLI command and a scheduler-friendly interface rather than an in-process scheduler.
