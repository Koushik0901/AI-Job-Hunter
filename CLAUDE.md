# CLAUDE.md — AI Job Hunter

Project context and conventions for Claude Code.

## What this project does

Daily ML/AI/Data Science job scraper. Runs on GitHub Actions at 10 AM MT, scrapes 38+
company career pages (Greenhouse, Lever, Ashby, Workable), filters to Canada/Remote roles,
stores results in SQLite Cloud, sends Telegram notifications, and enriches new jobs with
LLM-extracted metadata (seniority, salary, skills, etc.) via OpenRouter.

## How to run

```bash
uv run python src/scrape.py                        # standard daily run
uv run python src/scrape.py --no-enrich-llm        # skip LLM enrichment
uv run python src/scrape.py --no-notify            # skip Telegram
uv run python src/scrape.py --enrich-backfill      # enrich all existing jobs, then exit
uv run python src/scrape.py --check openai         # probe ATS platforms for a slug
uv sync                                            # install / sync dependencies
```

## File layout

```
src/
├── scrape.py     # CLI entry point — filters, orchestration, main()
├── fetchers.py   # ATS fetchers (Greenhouse/Lever/Ashby/Workable), normalizers, description helpers
├── db.py         # SQLite persistence — init_db(), save_jobs(), enrichment table
├── notify.py     # _load_dotenv(), Telegram formatting and sending
└── enrich.py     # OpenRouter LLM enrichment pipeline

companies.yaml    # list of companies to scrape (name, ats_type, ats_url, enabled)
pyproject.toml    # dependencies only — no build system, no entry point
```

## Key conventions

- **Imports**: absolute (`from db import ...`, `from fetchers import ...`).
  Python adds `src/` to `sys.path` automatically when running `src/scrape.py`.
- **File lookup**: use `Path.cwd()` for `.env`, `companies.yaml`, `jobs.db` — always run from project root.
- **No new dependencies** for stdlib-solvable tasks (e.g. `_load_dotenv` instead of python-dotenv).
- **Single-file philosophy for each concern** — don't split a module further unless it exceeds ~400 lines.
- **enrich.py never raises** from `enrich_one_job()` — always returns a dict with `enrichment_status`.

## Environment variables

| Variable | Required | Notes |
|----------|----------|-------|
| `TELEGRAM_TOKEN` | Yes | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Your chat ID |
| `SQLITECLOUD_URL` | Recommended | Falls back to local `jobs.db` |
| `OPENROUTER_API_KEY` | Optional | LLM enrichment silently skipped if unset |
| `ENRICHMENT_MODEL` | Optional | Default: `google/gemma-3-12b-it` |

Local: set in `.env` (git-ignored). GitHub Actions: set as repository secrets.

## Database

Two tables in SQLite (local or SQLite Cloud):
- `jobs` — scraped postings (url PK, company, title, location, posted, ats, description, first_seen, last_seen)
- `job_enrichments` — LLM output (url FK, work_mode, seniority, role_family, salary_*, skills, visa_sponsorship, enrichment_status)

## Adding companies

Edit `companies.yaml`. Use `--check <slug>` to find the right ATS and slug for a company.

## GitHub Actions

Workflow: `.github/workflows/daily_scrape.yml`
- Runs daily at 10:00 AM MST (cron: `0 17 * * *`)
- Required secrets: `SQLITECLOUD_URL`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `OPENROUTER_API_KEY`
- Manual trigger available via `workflow_dispatch`
