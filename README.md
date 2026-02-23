# AI Job Hunter

Daily ML/AI/Data Science job discovery pipeline.

It scrapes ATS job boards (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) plus Hacker News "Who is Hiring", filters by role/location, stores jobs in SQLite or Turso (libsql), optionally enriches jobs with structured LLM extraction via OpenRouter, and sends Telegram notifications for new roles.

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

### 3) Run

```bash
uv run python src/scrape.py
```

## Most Used Commands

```bash
# Daily run
uv run python src/scrape.py

# Skip Telegram and enrichment
uv run python src/scrape.py --no-notify --no-enrich-llm

# Backfill failed/unenriched records
uv run python src/scrape.py --enrich-backfill

# Probe ATS support for known slug
uv run python src/scrape.py --check openai

# Discover and add a company interactively
uv run python src/add_company.py "Hugging Face"

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
  - [`docs/cli/add-company.md`](docs/cli/add-company.md)
  - [`docs/cli/eval.md`](docs/cli/eval.md)
- Configuration:
  - [`docs/configuration/environment.md`](docs/configuration/environment.md)
  - [`docs/configuration/companies-yaml.md`](docs/configuration/companies-yaml.md)
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
- Full file reference:
  - [`docs/reference/file-by-file-reference.md`](docs/reference/file-by-file-reference.md)
  - [`docs/reference/glossary.md`](docs/reference/glossary.md)
  - [`docs/reference/changelog-docs.md`](docs/reference/changelog-docs.md)

## Design Notes

- Code is the source of truth. Documentation tracks current behavior from tracked code under `src/`, `eval/`, and workflow/config files.
- `prompts.yaml` is a reference copy; runtime prompt strings are defined in `src/enrich.py`.
- Default enrichment model used by runtime code is `openai/gpt-oss-120b` unless overridden by `ENRICHMENT_MODEL`.
