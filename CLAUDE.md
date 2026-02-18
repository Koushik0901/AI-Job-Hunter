# CLAUDE.md — AI Job Hunter

Project context and conventions for Claude Code.

## What this project does

Daily ML/AI/Data Science job scraper. Runs on GitHub Actions at 10 AM MT, scrapes 38+
company career pages (Greenhouse, Lever, Ashby, Workable), filters to Canada/Remote roles,
stores results in SQLite Cloud, sends Telegram notifications, and enriches new jobs with
LLM-extracted metadata (seniority, salary, skills, canada_eligible, etc.) via OpenRouter.

LLM calls use **LangChain** (`ChatOpenAI` pointed at OpenRouter) and **Pydantic** (`JobEnrichment`
model) for structured output validation.

## How to run

```bash
uv run python src/scrape.py                        # standard daily run
uv run python src/scrape.py --no-enrich-llm        # skip LLM enrichment
uv run python src/scrape.py --no-notify            # skip Telegram
uv run python src/scrape.py --enrich-backfill      # enrich all existing jobs, then exit
uv run python src/scrape.py --check openai         # probe ATS platforms for a slug
uv sync                                            # install / sync dependencies

# Eval framework
uv run python eval/eval.py crawl                   # crawl jobs into eval/eval_jobs.db (no location filter)
uv run python eval/eval.py build                   # tag segments, write eval/dataset.yaml
uv run python eval/eval.py cost                    # estimate API cost for all models
uv run python eval/eval.py run                     # run full eval (7 student models vs teacher)
uv run python eval/eval.py run --subset 5          # sanity-check on 5 jobs
uv run python eval/eval.py report                  # print latest results
```

## File layout

```
src/
├── scrape.py     # CLI entry point — filters, orchestration, main()
├── fetchers.py   # ATS fetchers (Greenhouse/Lever/Ashby/Workable), normalizers, description helpers
├── db.py         # SQLite persistence — init_db(), save_jobs(), enrichment table
├── notify.py     # _load_dotenv(), Telegram formatting and sending
└── enrich.py     # LLM enrichment — LangChain + Pydantic (JobEnrichment model)

eval/
├── eval.py       # Eval framework: crawl / build / cost / run / report subcommands
├── eval_jobs.db  # Local crawl DB (git-ignored)
├── dataset.yaml  # Curated dataset (db_jobs auto-generated + manual_jobs)
└── results/      # JSON results files (git-ignored)

companies.yaml    # list of companies to scrape (name, ats_type, ats_url, enabled)
pyproject.toml    # dependencies — no build system, no entry point
```

## Key conventions

- **Imports**: absolute (`from db import ...`, `from fetchers import ...`).
  Python adds `src/` to `sys.path` automatically when running `src/scrape.py`.
- **File lookup**: use `Path.cwd()` for `.env`, `companies.yaml`, `jobs.db` — always run from project root.
- **Single-file philosophy for each concern** — don't split a module further unless it exceeds ~400 lines.
- **enrich.py never raises** from `enrich_one_job()` — always returns a dict with `enrichment_status`.
- **DB migrations**: new columns are added via `ALTER TABLE ... ADD COLUMN` in `init_db()`, wrapped in
  try/except so existing DBs are upgraded automatically on next run.

## LLM enrichment (`src/enrich.py`)

Uses **LangChain** (`langchain-openai`) and **Pydantic** instead of raw `requests`:

- `JobEnrichment(BaseModel)` — Pydantic model with typed, constrained fields (`Literal` enums,
  `Optional`, `list[str]`). Validation is automatic; invalid LLM output raises `ValidationError`.
- `_make_chain(api_key, model)` — creates `ChatOpenAI` pointed at OpenRouter's base URL, returns
  `llm.with_structured_output(JobEnrichment)`.
- `enrich_one_job()` — two attempts (full schema → simplified prompt); never raises; always returns
  a dict with `enrichment_status`.
- List fields (`must_have_skills`, etc.) are serialized to JSON strings for SQLite TEXT columns.

## Location filter (`scrape.py: passes_location_filter`)

Two-stage filter — runs before LLM enrichment, on the raw ATS location string:

**Accept if:**
- Location is empty (unknown → let through)
- Contains "canada"
- Matches a Canadian province full name (`_CA_PROVINCES`) or abbreviation as a whole token (`_CA_ABBREVS`)
- Matches a major Canadian city (`_CA_CITIES`)
- Contains "remote" with no blocked-country keyword (UK, Europe, Germany, France, Australia, India, etc.)
- "Remote US / Remote USA" — **accepted** (work-auth eligibility is checked by LLM via `canada_eligible`)
- Contains "anywhere"

**Reject if:**
- Non-remote location with no Canadian signal (e.g. "New York, NY", "United States", "US")
- Remote + explicitly non-CA/non-NA country (e.g. "Remote - UK", "Remote, Europe")

The `canada_eligible` enrichment field provides the second check for ambiguous "Remote US" jobs.

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
- `job_enrichments` — LLM output (url FK, work_mode, remote_geo, **canada_eligible**, seniority,
  role_family, years_exp_min/max, must_have_skills, nice_to_have_skills, tech_stack,
  salary_min/max/currency, visa_sponsorship, red_flags, enrichment_status, enrichment_model)

`canada_eligible` values: `"yes"` | `"no"` | `"unknown"` — LLM determines whether the job allows
working from Canada based on the full description text.

## Eval framework (`eval/eval.py`)

Measures general LLM extraction quality for AI/ML roles. Compares student models against a teacher
(GPT-5.2) on a curated dataset built from a no-location-filter crawl.

**Subcommands:**
- `crawl` — scrapes all companies (no location filter, broader title filter) into `eval/eval_jobs.db`
- `build [--db PATH]` — reads `eval_jobs.db`, tags segments, writes `eval/dataset.yaml`
- `cost` — token + cost estimate per model, no API calls
- `run [--models ...] [--teacher MODEL] [--subset N]` — runs teacher then students, saves results JSON
- `report [file]` — field-by-field table + list diagnostics + confusion matrix + per-segment breakdown

**Scoring:**
- Categorical fields (partial credit): `work_mode`, `canada_eligible`, `seniority`, `role_family`, `visa_sponsorship`
- List fields (F1 + Precision/Recall): `must_have_skills`, `nice_to_have_skills`, `tech_stack`, `red_flags`
- Overall = simple mean of all 9 fields (equal weight — measures general extraction quality)
- Skill normalization: aliases (`js→javascript`, `k8s→kubernetes`, etc.) + parenthetical stripping

**Segments** (6): `core`, `remote_geo_edge`, `red_flag`, `seniority_extreme`, `salary_disclosed`, `sparse`

Default student models (7): gemma-3-12b-it, gemma-3-27b-it, gpt-oss-120b, nemotron-3-nano-30b,
mistral-small-3.2-24b, qwen3-30b-a3b-thinking, llama-4-scout

## Adding companies

Edit `companies.yaml`. Use `--check <slug>` to find the right ATS and slug for a company.

## GitHub Actions

Workflow: `.github/workflows/daily_scrape.yml`
- Runs daily at 10:00 AM MST (cron: `0 17 * * *`)
- Required secrets: `SQLITECLOUD_URL`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `OPENROUTER_API_KEY`
- Manual trigger available via `workflow_dispatch`
