# Documentation Changelog

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

## 2026-02-21

- Replaced root README with concise gateway + docs map.
- Added structured `docs/` reference architecture.
- Added dedicated CLI docs for `cli.py scrape`, `add_company.py`, and `eval.py`.
- Added environment, architecture, data flow, storage, integrations, operations, troubleshooting, and evaluation references.
- Added file-by-file tracked file reference and glossary.
- Aligned docs to code-observed defaults and operational quirks.
