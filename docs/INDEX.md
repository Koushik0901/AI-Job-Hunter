# Documentation Index

This documentation is organized by task and maps to the current DB-backed CLI architecture.

## Start

- Quick setup and first run: [`quickstart.md`](quickstart.md)
- Root project overview: [`../README.md`](../README.md)
- Project changelog: [`../CHANGELOG.md`](../CHANGELOG.md)

## CLI Reference

- Scrape pipeline: [`cli/scrape.md`](cli/scrape.md)
- Source registry management: [`cli/sources.md`](cli/sources.md)
- Job lifecycle and retention: [`cli/lifecycle.md`](cli/lifecycle.md)
- Company discovery helper: [`cli/add-company.md`](cli/add-company.md)
- Eval framework CLI: [`cli/eval.md`](cli/eval.md)

## Configuration

- Environment variables and precedence: [`configuration/environment.md`](configuration/environment.md)
- Company source registry in DB: [`configuration/company-sources.md`](configuration/company-sources.md)

## Architecture

- System components and module boundaries: [`architecture/system-overview.md`](architecture/system-overview.md)
- End-to-end runtime data flow: [`architecture/data-flow.md`](architecture/data-flow.md)

## Storage and Integrations

- Database schema and persistence semantics: [`storage/database.md`](storage/database.md)
- ATS connector behavior and quirks: [`integrations/ats-sources.md`](integrations/ats-sources.md)
- LLM enrichment pipeline details: [`integrations/openrouter-enrichment.md`](integrations/openrouter-enrichment.md)
- Telegram delivery and message formatting: [`integrations/telegram.md`](integrations/telegram.md)

## Operations

- Scheduling (GitHub Actions + Windows Task Scheduler): [`operations/scheduling.md`](operations/scheduling.md)
- Operational runbook (daily checks, recovery): [`operations/runbook.md`](operations/runbook.md)
- Known issues and fixes: [`troubleshooting/known-issues.md`](troubleshooting/known-issues.md)

## Evaluation

- Eval framework model comparison details: [`evaluation/eval-framework.md`](evaluation/eval-framework.md)

## Dashboard

- Dashboard overview and run guide: [`dashboard/overview.md`](dashboard/overview.md)
- Backend API reference: [`dashboard/backend-api.md`](dashboard/backend-api.md)
- Frontend UI behavior and interaction model: [`dashboard/frontend-ui.md`](dashboard/frontend-ui.md)
- Match scoring rubric: [`dashboard/match-scoring.md`](dashboard/match-scoring.md)

## Reference

- File-by-file technical reference: [`reference/file-by-file-reference.md`](reference/file-by-file-reference.md)
- Glossary: [`reference/glossary.md`](reference/glossary.md)
- Documentation changelog: [`reference/changelog-docs.md`](reference/changelog-docs.md)
