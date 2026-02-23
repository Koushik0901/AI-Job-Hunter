# AI Job Hunter

Daily ML/AI/Data Science job discovery pipeline.

The system scrapes ATS job boards (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) plus Hacker News "Who is Hiring", filters by title/location, stores jobs in SQLite or Turso (libsql), optionally enriches jobs with structured LLM extraction via OpenRouter, and sends Telegram notifications for new roles.

## Quick Start

### 1) Install

Requires Python `3.12+` and [`uv`](https://github.com/astral-sh/uv).

```bash
uv sync
```

### 2) Configure

```bash
cp .env.example .env
```

Populate `.env` values (details: [`docs/configuration/environment.md`](docs/configuration/environment.md)).

### 3) Add company sources (DB-backed)

```bash
# add one company interactively
uv run python src/add_company.py "Hugging Face"

# or bulk import community lists
uv run python src/cli.py sources import --dry-run
uv run python src/cli.py sources import
```

### 4) Run

```bash
uv run python src/cli.py scrape
```

## Most Used Commands

```bash
# Daily run
uv run python src/cli.py scrape

# Skip Telegram + LLM enrichment
uv run python src/cli.py scrape --no-notify --no-enrich-llm

# Backfill failed/unenriched records
uv run python src/cli.py scrape --enrich-backfill

# Probe ATS support for a slug
uv run python src/cli.py sources check openai

# Manage source registry
uv run python src/cli.py sources list
uv run python src/cli.py sources enable openai
uv run python src/cli.py sources disable openai

# Manage job lifecycle retention
uv run python src/cli.py lifecycle set-status --url <job_url> --status applied
uv run python src/cli.py lifecycle prune --days 28
uv run python src/cli.py lifecycle prune --days 28 --apply

# Eval framework
uv run python eval/eval.py crawl
uv run python eval/eval.py build
uv run python eval/eval.py cost
uv run python eval/eval.py run
uv run python eval/eval.py report
```

## Documentation Map

- Start here: [`docs/INDEX.md`](docs/INDEX.md)
- CLI reference:
  - [`docs/cli/scrape.md`](docs/cli/scrape.md)
  - [`docs/cli/sources.md`](docs/cli/sources.md)
  - [`docs/cli/lifecycle.md`](docs/cli/lifecycle.md)
  - [`docs/cli/add-company.md`](docs/cli/add-company.md)
  - [`docs/cli/eval.md`](docs/cli/eval.md)
- Configuration:
  - [`docs/configuration/environment.md`](docs/configuration/environment.md)
  - [`docs/configuration/company-sources.md`](docs/configuration/company-sources.md)
- Architecture and flow:
  - [`docs/architecture/system-overview.md`](docs/architecture/system-overview.md)
  - [`docs/architecture/data-flow.md`](docs/architecture/data-flow.md)
- Storage and integrations:
  - [`docs/storage/database.md`](docs/storage/database.md)
  - [`docs/integrations/ats-sources.md`](docs/integrations/ats-sources.md)
  - [`docs/integrations/openrouter-enrichment.md`](docs/integrations/openrouter-enrichment.md)
  - [`docs/integrations/telegram.md`](docs/integrations/telegram.md)
- Operations:
  - [`docs/operations/scheduling.md`](docs/operations/scheduling.md)
  - [`docs/operations/runbook.md`](docs/operations/runbook.md)
  - [`docs/troubleshooting/known-issues.md`](docs/troubleshooting/known-issues.md)
- Evaluation:
  - [`docs/evaluation/eval-framework.md`](docs/evaluation/eval-framework.md)
- Reference:
  - [`docs/reference/file-by-file-reference.md`](docs/reference/file-by-file-reference.md)
  - [`docs/reference/glossary.md`](docs/reference/glossary.md)
  - [`docs/reference/changelog-docs.md`](docs/reference/changelog-docs.md)
  - [`CHANGELOG.md`](CHANGELOG.md)

## Design Notes

- Code is the source of truth. Docs are aligned to tracked behavior in `src/`, `eval/`, and automation files.
- Company sources are DB-only (`company_sources` table).
- `prompts.yaml` is a reference copy; runtime prompt strings are defined in `src/enrich.py`.
- Default enrichment model is `openai/gpt-oss-120b` unless overridden by `ENRICHMENT_MODEL`.
