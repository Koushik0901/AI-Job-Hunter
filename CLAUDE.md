# CLAUDE.md — AI Job Hunter

Project context and conventions for Claude Code.

## What this project does

Daily ML/AI/Data Science job scraper. Runs on GitHub Actions at 10 AM MT, scrapes 100+
company career pages (Greenhouse, Lever, Ashby, Workable, SmartRecruiters) plus HN "Who is
Hiring?" (monthly community thread), filters to Canada/Remote roles,
stores results in Turso (libsql cloud), sends Telegram notifications, and enriches new jobs with
LLM-extracted metadata (seniority, salary, skills, canada_eligible, etc.) via OpenRouter.

LLM calls use **LangChain** (`ChatOpenAI` pointed at OpenRouter) and **Pydantic** (`JobEnrichment`
model) for structured output validation.

## How to run

```bash
uv run python src/scrape.py                        # standard daily run
uv run python src/scrape.py --no-enrich-llm        # skip LLM enrichment
uv run python src/scrape.py --no-notify            # skip Telegram
uv run python src/scrape.py --no-enrich            # skip description fetching (faster)
uv run python src/scrape.py --enrich-backfill      # enrich all unenriched/failed jobs, then exit
uv run python src/scrape.py --check openai         # probe all 5 ATS platforms for a slug
uv run python src/scrape.py --import-companies --dry-run  # preview companies to import
uv run python src/scrape.py --import-companies     # fetch & append new companies to companies.yaml

# Company discovery (new standalone script)
uv run python src/add_company.py "Hugging Face"               # auto-generate slug candidates
uv run python src/add_company.py "Scale AI" --slug scaleai   # provide explicit slug
uv run python src/add_company.py "OpenAI" --slug openai --add # non-interactive auto-add

uv sync                                            # install / sync dependencies

# Eval framework
uv run python eval/eval.py crawl                   # crawl jobs into eval/eval_jobs.db (no location filter)
uv run python eval/eval.py build                   # tag segments, write eval/dataset.yaml
uv run python eval/eval.py cost                    # estimate API cost for all models
uv run python eval/eval.py run                     # run full eval (7 student models vs teacher)
uv run python eval/eval.py run --subset 5          # sanity-check on 5 jobs
uv run python eval/eval.py run --resume            # resume from checkpoint after rate limit / interruption
uv run python eval/eval.py report                  # print latest results
```

## File layout

```
src/
├── scrape.py       # CLI entry point — filters, orchestration, main()
├── add_company.py  # Standalone company discovery tool (slug gen + ATS probing + yaml append)
├── fetchers.py     # ATS fetchers (Greenhouse/Lever/Ashby/Workable/SmartRecruiters/HN),
│                   #   normalizers, description helpers, retry_with_backoff
├── db.py           # SQLite persistence — init_db(), save_jobs(), load_unenriched_jobs(),
│                   #   save_enrichment(), migrations
├── notify.py       # _load_dotenv(), bucket_country(), Telegram formatting + sending
└── enrich.py       # LLM enrichment — LangChain + Pydantic (JobEnrichment model),
                    #   RateLimitSignal, provider-rotation retry logic

eval/
├── eval.py         # Eval framework: crawl / build / cost / run / report subcommands
├── eval_jobs.db    # Local crawl DB (git-ignored)
├── dataset.yaml    # Curated dataset (db_jobs auto-generated + manual_jobs)
└── results/        # JSON results files + checkpoint.json (git-ignored)

companies.yaml      # List of companies to scrape (name, ats_type, ats_url, enabled)
prompts.yaml        # LLM prompt templates (reference copy — actual strings live in enrich.py)
pyproject.toml      # Dependencies — no build system, no entry point
```

## Key conventions

- **Imports**: absolute (`from db import ...`, `from fetchers import ...`).
  Python adds `src/` to `sys.path` automatically when running any script inside `src/`.
- **File lookup**: use `Path.cwd()` for `.env`, `companies.yaml`, `jobs.db` — always run from project root.
- **Single-file philosophy for each concern** — don't split a module further unless it exceeds ~400 lines.
- **`enrich_one_job()` raises `RateLimitSignal`** only after `_MAX_PROVIDER_RETRIES` (3) rate-limit
  retries are exhausted; non-rate-limit errors are caught and returned as `enrichment_status="failed"`.
  Callers must NOT save rate-limited results to DB.
- **DB migrations**: new columns are added via `ALTER TABLE ... ADD COLUMN` in `init_db()`, wrapped in
  try/except so existing DBs are upgraded automatically on next run.
- **Windows CP1252 terminal**: avoid non-ASCII characters (arrows `→`, emoji) in `console.print()` output
  that goes to stdout/stderr — they crash the Windows legacy terminal renderer. Use `->` etc. instead.

## `src/add_company.py` — Company Discovery Tool

Standalone script for discovering which ATS platform a company uses and adding it to `companies.yaml`.
Does NOT require knowing the slug in advance — generates candidates automatically.

**Workflow:**
1. `_candidate_slugs(name)` — generates up to ~6 slug variants from the company name:
   - Three forms from the full name: `joined` (no separators), `hyphenated`, `first word`
   - Three forms from the suffix-stripped name (removes: Inc, LLC, Ltd, Corp, Corporation,
     Technologies, Technology, Systems, Solutions, Group, Labs, Software)
   - `--slug` arguments are appended after auto-generated candidates
2. `_probe_all(slugs)` — fires all 5 ATS platforms × N slugs concurrently via
   `ThreadPoolExecutor(max_workers=20)`; reuses `_ATS_PROBES` and `_probe_job_count` from `scrape.py`
3. Splits results into `real_hits` (jobs > 0) and `zero_hits` (jobs == 0). Only `real_hits` are
   shown in the table and offered for adding. Zero-job hits are listed in a dim suppressed note.
4. Deduplicates by `ats_url`, displays a Rich table (Slug | ATS | Jobs | URL)
5. `_find_in_yaml(slug, ats_url, config_path)` — two-level duplicate check:
   - **Exact URL match**: same `ats_url` already in yaml
   - **Slug path match**: slug appears as a URL path segment in *any* existing entry (catches
     the same company under a different ATS, e.g. slug `openfarminc` blocked because "Open Farm Pet"
     already has `boards-api.greenhouse.io/.../openfarminc/...`)
   - Prints `Already in companies.yaml as '<name>'` with the existing entry's name
6. Interactive prompt for single new match, numbered list for multiple, `--add` skips prompts

**SmartRecruiters/Workable false positives**: their APIs return HTTP 200 for any slug (0 jobs).
Zero-job hits are now suppressed from the table and never offered for adding — they appear only as
a dim note: `N zero-job hit(s) hidden (false positives): smartrecruiters:slug, workable:slug`.

**Imports from siblings**: `_ATS_PROBES`, `_probe_job_count` from `scrape`; `_load_dotenv` from `notify`.
`sys.path.insert(0, str(Path(__file__).parent))` makes the `src/` siblings importable.

## LLM enrichment (`src/enrich.py`)

Uses **LangChain** (`langchain-openai`) and **Pydantic** instead of raw `requests`:

- `JobEnrichment(BaseModel)` — Pydantic model with typed, constrained fields (`Literal` enums,
  `Optional`, `list[str]`). Field validators coerce invalid LLM output to safe defaults instead of
  raising (e.g. unknown `work_mode` value → `None`).
- `_make_chain(api_key, model, provider_order, ignore_providers, sort_by)` — creates `ChatOpenAI`
  pointed at OpenRouter's base URL, returns `llm.with_structured_output(JobEnrichment)`.
  `ignore_providers` and `sort_by` map to OpenRouter's `provider` request field via `extra_body`.
- `_invoke_once(chain, messages)` — single LLM call; thin wrapper.
- `build_enrichment_prompt(job)` — builds the user message; also used by `eval/eval.py` for token
  estimation (exported symbol).
- `enrich_one_job(job, api_key, model, stop_event, provider_order)` — enriches one job with up to
  `_MAX_PROVIDER_RETRIES` (3) retries on HTTP 429:
  - Each retry adds the rate-limiting provider to an `ignored_providers` list passed to OpenRouter
  - If the provider cannot be identified from the error message, switches to `sort_by="throughput"`
  - Only raises `RateLimitSignal` when all retries are exhausted
  - Checks `stop_event` at entry (and between retries) so already-queued threads bail out fast
  - All non-rate-limit errors return `enrichment_status="failed"` (never raise)
- `run_enrichment_pipeline()` — on first `RateLimitSignal`: sets stop flag, cancels pending futures,
  leaves unprocessed jobs as `NULL` in DB (picked up by `--enrich-backfill`), prints resume command.
- List fields (`required_skills`, `preferred_skills`, `red_flags`) are serialized to JSON strings
  for SQLite TEXT columns before storage.

## Rate limit behaviour

On HTTP 429 from OpenRouter/upstream provider:

| Context | Behaviour |
|---------|-----------|
| `enrich_one_job()` | Retries up to 3x, excluding the rate-limiting provider each time; only raises `RateLimitSignal` when all retries fail |
| `scrape.py --enrich-backfill` | On `RateLimitSignal`: stops pipeline; unprocessed jobs stay `NULL` → resume with `--enrich-backfill` |
| `eval/eval.py run` | On `RateLimitSignal`: stops pipeline; saves checkpoint; resume with `eval/eval.py run --resume` |

**Provider retry mechanism** (`enrich.py: _MAX_PROVIDER_RETRIES = 3`):
- OpenRouter error messages contain the provider name: `"Provider Crusoe returned error: 429"`
- `_extract_rate_limited_provider(e)` parses the provider name via regex
- Each retry passes that provider in `ignore_providers` → OpenRouter routes to a different provider
- If provider unknown: uses `sort_by="throughput"` to prefer less-loaded providers
- After 3 failed retries: raises `RateLimitSignal` to stop the pipeline

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
| `TURSO_URL` | Recommended | e.g. `libsql://your-db.turso.io` — falls back to local `jobs.db` |
| `TURSO_AUTH_TOKEN` | Recommended | Turso database auth token |
| `OPENROUTER_API_KEY` | Optional | LLM enrichment silently skipped if unset |
| `ENRICHMENT_MODEL` | Optional | Default: `openai/gpt-oss-120b` |

Local: set in `.env` (git-ignored). GitHub Actions: set as repository secrets.

## Database

Two tables in SQLite (local file or Turso libsql cloud):

**`jobs` table** — scraped postings:
- `url` (PK), `company`, `title`, `location`, `posted`, `ats`, `description`, `first_seen`, `last_seen`

**`job_enrichments` table** — LLM output:
- Active columns (written by current `save_enrichment()`):
  `url` (FK), `work_mode`, `remote_geo`, `canada_eligible`, `seniority`, `role_family`,
  `years_exp_min`, `years_exp_max`, `required_skills`, `preferred_skills`,
  `salary_min`, `salary_max`, `salary_currency`, `visa_sponsorship`, `red_flags`,
  `enriched_at`, `enrichment_status`, `enrichment_model`
- Legacy columns (created by `CREATE TABLE` but never populated by current code):
  `must_have_skills`, `nice_to_have_skills`, `tech_stack` — these are V3/V4 schema leftovers,
  always NULL in practice. The rename to `required_skills`/`preferred_skills` happened in V5.

`canada_eligible` values: `"yes"` | `"no"` | `"unknown"` — LLM determines whether the job allows
working from Canada based on the full description text.

`enrichment_status` values: `"ok"` | `"failed"` | `"skipped"` | `NULL` (unenriched, picked up by backfill).
`"skipped"` = job has no description text to enrich.

**Schema drift note**: `init_db()` runs `CREATE TABLE IF NOT EXISTS` (creates legacy columns)
then `ALTER TABLE ADD COLUMN` migrations to add `canada_eligible`, `required_skills`, `preferred_skills`.
On a fresh DB, both sets of columns exist; only the new ones are ever written to.

## Eval framework (`eval/eval.py`)

Measures general LLM extraction quality for AI/ML roles. Compares student models against a teacher
(GPT-5.2) on a curated dataset built from a no-location-filter crawl.

**Subcommands:**
- `crawl` — scrapes all companies (no location filter, broader title filter including `deep learning`,
  `reinforcement learning`, `ml intern`, etc.) into `eval/eval_jobs.db` via a local SQLite file
- `build [--db PATH]` — reads `eval_jobs.db`, tags segments (6 types), writes `eval/dataset.yaml`
- `cost [--models ...] [--teacher MODEL]` — token + cost estimate per model, no API calls
- `run [--models ...] [--teacher MODEL] [--subset N] [--resume]` — runs teacher then students,
  saves `eval/results/<ts>_<teacher>_<N>models.json`; `--resume` loads checkpoint and skips done work
- `report [file]` — field-by-field table + list diagnostics + confusion matrix + per-segment breakdown

**Checkpointing (`eval/results/checkpoint.json`):**
- Written after every individual job result (per-job granularity, atomic write via `.tmp` rename)
- Stores `teacher_results` and `student_results` keyed by job ID
- On rate limit: checkpoint already has all completed work; partial results JSON is also saved
- On resume: skips teacher if fully complete, skips completed student models, resumes partial model
  from the exact job where it stopped
- Checkpoint is invalidated (fresh start) if teacher, student_models, or job_ids differ
- `eval/eval.py` uses `sys.path.insert(0, str(Path(__file__).parent.parent / "src"))` to import siblings

**Scoring (14 fields, equal-weight mean):**
- Categorical (partial credit for adjacent values): `work_mode`, `canada_eligible`, `seniority`,
  `role_family`, `visa_sponsorship`
- List fields (F1 + Precision/Recall): `required_skills`, `preferred_skills`, `red_flags`
- Numeric (ordinal tolerance: ±1yr = score 0.75): `years_exp_min`, `years_exp_max`
- Salary (percentage tolerance + unit normalization): `salary_min`, `salary_max`, `salary_currency`
- Skill normalization before comparison: aliases (`js→javascript`, `k8s→kubernetes`, `torch→pytorch`,
  `ts→typescript`, `postgres→postgresql`, etc.) + parenthetical stripping
- Not scored: `remote_geo` (free-form string, no reliable automatic comparison)

**Segments** (6): `core`, `remote_geo_edge`, `red_flag`, `seniority_extreme`, `salary_disclosed`, `sparse`

**Pricing table** ($/M tokens, update if OpenRouter changes):
- `google/gemma-3-12b-it`: $0.04 in / $0.13 out (not in PRICING dict → uses PRICING_FALLBACK)
- `google/gemma-3-27b-it`: $0.04 in / $0.15 out
- `openai/gpt-oss-120b`: $0.039 in / $0.19 out
- `nvidia/nemotron-3-nano-30b-a3b`: (uses PRICING_FALLBACK $1.00/$4.00)
- `mistralai/mistral-small-3.2-24b-instruct`: $0.06 in / $0.18 out
- `qwen/qwen3-30b-a3b-thinking-2507`: $0.051 in / $0.34 out
- `meta-llama/llama-4-scout`: $0.08 in / $0.30 out
- `openai/gpt-5.2` (teacher): $1.75 in / $14.00 out

## Adding companies

Three methods, in order of preference:

**Method 1: Interactive discovery** (new — `add_company.py`)
```bash
uv run python src/add_company.py "Company Name"
uv run python src/add_company.py "Company Name" --slug known-slug
uv run python src/add_company.py "Company Name" --slug known-slug --add   # non-interactive
```
Generates slug candidates automatically, probes all 5 ATS platforms concurrently, shows results table,
offers to append matches to `companies.yaml`. Best starting point for adding individual companies.

**Method 2: Manual slug probe** (`scrape.py --check`)
```bash
uv run python src/scrape.py --check openai
```
Probes all 5 platforms for one specific slug. Use when you know the slug but not the ATS.

**Method 3: Bulk import** (`scrape.py --import-companies`)
```bash
uv run python src/scrape.py --import-companies --dry-run  # preview first
uv run python src/scrape.py --import-companies
```
Fetches 3 GitHub community lists, deduplicates against existing companies.yaml, appends new entries.
Sources: `pittcsc/Summer2024-Internships`, `j-delaney/easy-application`, `SimplifyJobs/New-Grad-Positions`.

**Direct edit**: Edit `companies.yaml` manually with `name`, `ats_type`, `ats_url`, `enabled: true`.

## SmartRecruiters API (`src/fetchers.py`)

5th ATS platform. REST API at `api.smartrecruiters.com`.
- `fetch_smartrecruiters(company_slug)` — `GET /v1/companies/{slug}/postings?limit=100&offset=0`
- `normalize_smartrecruiters(raw, company)` — constructs location from `raw["location"]` dict
  (city/region/country + `remote` bool); sets `_job_id` for description fetch
- `fetch_smartrecruiters_description(company_slug, job_id)` — `GET /v1/companies/{slug}/postings/{job_id}`;
  extracts `jobAd.sections` (companyDescription, jobDescription, otherDetails), strips HTML
- `enrich_descriptions()` dispatches on `ats == "smartrecruiters"` using `_company_slug` + `_job_id`

## HN "Who is Hiring?" (`src/fetchers.py`)

Monthly community thread on Hacker News — always-on, no credentials needed.
- `_HN_ML_KEYWORDS` — frozenset of ML/AI phrases for comment pre-filtering
- `_find_hn_hiring_thread()` — Algolia `hn.algolia.com` search for latest `whoishiring` story;
  matches `author == "whoishiring"` and title contains "Who is Hiring?"
- `fetch_hn_jobs()` — paginates all comments (`tags=comment,story_{id}`, 1000 per page);
  pre-filters by `_HN_ML_KEYWORDS`; returns normalized jobs
- `normalize_hn(raw)` — parses `Company | Location | Role` format from first line;
  `ats="hn_hiring"`; description = `strip_html(full comment text)`
  (Algolia returns HTML-encoded comment text; `strip_html` handles first-line parsing)
- Runs in `scrape_all()` after the company loop; all exceptions caught gracefully (skip on failure)
- HN jobs already have `description` set → `enrich_descriptions()` short-circuits them

## Fetchers & Normalizers (`src/fetchers.py`)

**Retry decorator**: `@retry_with_backoff(max_attempts, base_delay)` — exponential backoff on
`requests.RequestException`; delay capped at 60s; applied to all ATS fetchers.

**Description fetching** (`enrich_descriptions`): mutates `job["description"]` in-place.
Concurrent via `ThreadPoolExecutor(max_workers=10)`. Per-ATS dispatch:
- **Greenhouse**: second GET to `/v1/boards/{token}/jobs/{id}` → strip HTML from `content`
- **Lever**: built from `descriptionPlain` + `lists` + `additionalPlain` fields already in the
  list-API response — **no extra HTTP request needed**
- **Ashby**: GET job detail page → extract `__NEXT_DATA__` JSON → `descriptionHtml` → strip HTML
- **Workable**: GET `/api/v3/accounts/{slug}/jobs/{shortcode}` → `full_description` → strip HTML
- **SmartRecruiters**: GET `/v1/companies/{slug}/postings/{job_id}` → `jobAd.sections` → strip HTML
- **HN**: description already set; `enrich_descriptions()` short-circuits (returns existing value)

**Date normalization** (`_normalize_datetime`): handles Unix timestamps (seconds or ms), ISO strings,
and `%Y-%m-%d` / `%m/%d/%Y` formats. Always returns `YYYY-MM-DD` string or empty string.

## Telegram notifications (`src/notify.py`)

- `bucket_country(location)` — classifies into `"Canada"` / `"USA / Remote"` / `"Other"`
  using substring matching on the location string
- `format_telegram_message(new_jobs, run_date)` — groups jobs by country bucket, formats HTML,
  splits into ≤4096-char chunks to respect Telegram's message limit
- `send_telegram(token, chat_id, text)` — single POST to `api.telegram.org/bot{token}/sendMessage`
  with `parse_mode="HTML"` and `disable_web_page_preview=True`
- `notify_new_jobs()` — sends all chunks with `time.sleep(1)` between them to avoid Telegram rate limits
- `_load_dotenv(path)` — custom minimal `.env` loader (no external dependency); uses
  `os.environ.setdefault` so existing env vars (e.g. from GitHub Actions secrets) are never overwritten

## GitHub Actions

Workflow: `.github/workflows/daily_scrape.yml`
- Runs daily at 10:00 AM MST (cron: `0 17 * * *` UTC = UTC-7 in winter)
- Required secrets: `TURSO_URL`, `TURSO_AUTH_TOKEN`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `OPENROUTER_API_KEY`
- HN "Who is Hiring?" always runs (no secrets needed)
- Manual trigger available via `workflow_dispatch`

## prompts.yaml

Reference copy of the LLM prompts. The actual prompt strings live directly in `src/enrich.py`
(`_SYSTEM_PROMPT`, `_SCHEMA_DESCRIPTION`, `build_enrichment_prompt()`). `prompts.yaml` is a
human-readable reference only — changes here have no effect on runtime behavior. If you update
the prompts, update both files to keep them in sync.

## Known issues / gotchas

- **Windows CP1252 terminal**: `→`, em-dash `—`, and emoji crash the Windows legacy terminal
  renderer (`UnicodeEncodeError: 'charmap' codec can't encode character`). Use ASCII (`->`, `-`)
  in `console.print()` messages. This is a display-only issue; Telegram receives Unicode fine.
- **Turso free tier**: never pauses (as of March 2025 policy change). 5 GB storage, no manual restarts needed. Connection via hrana HTTP API using `requests` — no compiled extension. `_TursoConnection` in `db.py` is a sqlite3-compatible wrapper; `commit()` is a no-op (auto-committed per statement).
- **SmartRecruiters/Workable false positives**: their APIs return HTTP 200 for any slug, even
  companies not on that platform (with `content: []` or `results: []`). The `--check` and
  `add_company.py` probes will show these as "FOUND" with 0 jobs.
- **Telegram rate limiting**: splitting messages with `time.sleep(1)` between chunks handles it.
- **Schema drift**: `must_have_skills`, `nice_to_have_skills`, `tech_stack` columns exist in the
  `job_enrichments` table (created by `CREATE TABLE`) but are never written to. Active skill columns
  are `required_skills`, `preferred_skills` (added by migration). Query the latter.
- **`.env.example`**: always use placeholder values, never real credentials.
- **`eval/eval.py` sys.path**: uses `sys.path.insert(0, str(Path(__file__).parent.parent / "src"))`
  to import from `src/` without installing the package. The `src/` scripts themselves don't need this
  because Python automatically adds the running script's directory to `sys.path[0]`.
