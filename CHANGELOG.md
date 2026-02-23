# Changelog

All notable project changes are tracked in this file.

This project follows a simple Keep a Changelog style with date-based entries.

## 2026-02-23

### Added

- DB-first source-management docs: `docs/configuration/company-sources.md`.
- New CLI docs:
  - `docs/cli/sources.md`
  - `docs/cli/lifecycle.md`
- Root project changelog (`CHANGELOG.md`).

### Changed

- Full documentation refresh aligned to current architecture:
  - `src/cli.py` as single entrypoint
  - split command modules in `src/commands/*`
  - split service modules in `src/services/*`
  - DB-only company source registry (`company_sources`)
- Updated `README.md`, quickstart, docs index, architecture, data flow, storage, operations, and references.
- Updated eval docs to reflect `crawl --source-db` and DB-backed source loading.
- Updated runbook with lifecycle pruning and source-registry operational procedures.

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
