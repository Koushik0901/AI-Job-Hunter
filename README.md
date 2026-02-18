# AI Job Hunter

A daily ML/AI/Data Science job scraper that monitors 38+ company career pages, stores results in **SQLite Cloud**, enriches job postings with **LLM-extracted metadata**, and sends Telegram notifications for new postings — grouped by country.

## Features

- Scrapes **Greenhouse, Lever, Ashby, and Workable** ATS platforms
- Filters jobs by **title keywords** (ML, AI, Data Science, NLP, LLM, etc.) and **location** (Canada + Remote)
- Fetches **full job descriptions** concurrently (ThreadPoolExecutor)
- **LLM enrichment** via OpenRouter — extracts seniority, work mode, skills, salary, visa sponsorship, and whether the role allows working from Canada (`canada_eligible`). Uses **LangChain** + **Pydantic** for structured output validation
- Stores all jobs in **SQLite Cloud** (or a local SQLite file as fallback) with deduplication
- Sends **Telegram notifications** grouped by 🇨🇦 Canada / 🌐 USA & Remote / 🌍 Other
- Runs **daily via GitHub Actions** (free) or Windows Task Scheduler
- **Eval framework** — compare N enrichment models side-by-side against a teacher model

---

## Quickstart (Local)

### 1. Install dependencies

Requires Python 3.12+ and [uv](https://github.com/astral-sh/uv).

```bash
uv sync
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Edit `.env` with your values (see [Environment Variables](#environment-variables) below).

### 3. Run

```bash
uv run python src/scrape.py
```

On first run: scrapes all companies, saves to DB, sends Telegram message for all new jobs, enriches them with LLM.
On subsequent runs: only new postings trigger a notification and enrichment.

---

## Usage

```
uv run python src/scrape.py [OPTIONS]

Options:
  --config PATH          Path to companies.yaml (default: companies.yaml next to script)
  --db PATH              Path to local SQLite file (default: jobs.db). Ignored if SQLITECLOUD_URL is set.
  --limit N              Max rows to display in terminal table (default: 50)
  --no-location-filter   Show all title-matched jobs, not just Canada/Remote
  --no-enrich            Skip fetching full descriptions (faster, no description stored)
  --no-notify            Skip Telegram notification even if credentials are configured
  --no-enrich-llm        Skip LLM enrichment even if OPENROUTER_API_KEY is set
  --enrich-backfill      Enrich all unenriched/failed jobs in DB, then exit (no scraping)
  --check SLUG           Probe all ATS platforms for a company slug (for discovery)
```

### Examples

```bash
# Standard daily run
uv run python src/scrape.py

# Browse all matched jobs worldwide (no location filter)
uv run python src/scrape.py --no-location-filter --limit 200

# Fast run without descriptions, notifications, or enrichment
uv run python src/scrape.py --no-enrich --no-notify --no-enrich-llm

# Backfill LLM enrichment on all existing jobs
uv run python src/scrape.py --enrich-backfill

# Check if a company has a supported ATS board
uv run python src/scrape.py --check openai
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_TOKEN` | Yes | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Your chat ID with the bot |
| `SQLITECLOUD_URL` | Recommended | Connection string from sqlitecloud.io. Falls back to local `jobs.db` if not set. |
| `OPENROUTER_API_KEY` | Optional | API key from openrouter.ai. LLM enrichment is silently skipped if not set. |
| `ENRICHMENT_MODEL` | Optional | Model used for job enrichment (default: `google/gemma-3-12b-it`) |

**Telegram setup:**
1. Open Telegram → search **@BotFather** → send `/newbot` → copy the token
2. Send your bot any message, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat ID under `"chat":{"id":...}`

**SQLite Cloud setup:**
1. Sign up at [sqlitecloud.io](https://sqlitecloud.io) (free tier: 1 GB)
2. Create a project → create a database named `jobs.db`
3. Copy the connection string: `sqlitecloud://host:8860/jobs.db?apikey=...`

**OpenRouter setup:**
1. Sign up at [openrouter.ai](https://openrouter.ai) (pay-per-use, ~$1.80/year at 50 jobs/day)
2. Create an API key and add it to `.env`

---

## Adding Companies

Edit `companies.yaml`. Each entry needs a `name`, `ats_type`, and `ats_url`:

```yaml
companies:
  - name: Cohere
    ats_type: ashby
    ats_url: https://jobs.ashbyhq.com/cohere
    enabled: true

  - name: Anthropic
    ats_type: greenhouse
    ats_url: https://boards-api.greenhouse.io/v1/boards/anthropic/jobs
    enabled: true
```

Supported `ats_type` values: `greenhouse`, `lever`, `ashby`, `workable`.

Use `--check <slug>` to discover which ATS a company uses:

```bash
uv run python src/scrape.py --check mistral
```

---

## Project Structure

```
ai-job-hunter/
├── src/
│   ├── scrape.py           # CLI entry point: main(), scrape_all(), filters
│   ├── fetchers.py         # ATS fetchers, normalizers, description helpers
│   ├── db.py               # SQLite persistence (jobs + job_enrichments tables)
│   ├── notify.py           # Telegram notifications
│   └── enrich.py           # LLM enrichment pipeline (OpenRouter)
├── eval/
│   ├── eval.py             # Eval framework: build / cost / run / report
│   ├── dataset.yaml        # Curated dataset (auto-generated + manual jobs)
│   └── results/            # JSON results files (git-ignored)
├── companies.yaml          # List of companies to scrape
├── pyproject.toml          # Python project config and dependencies
├── uv.lock                 # Locked dependency versions
├── .env.example            # Credentials template (copy to .env)
├── .env                    # Your real credentials (git-ignored)
├── jobs.db                 # SQLite database (git-ignored, created on first run)
├── setup_scheduler.ps1     # Windows Task Scheduler setup script
└── .github/
    └── workflows/
        └── daily_scrape.yml  # GitHub Actions daily workflow
```

---

## Scheduling

### GitHub Actions (recommended — free, no local machine needed)

1. Push this repo to GitHub (private repo is fine — 2,000 free minutes/month)
2. Go to **Settings → Secrets and variables → Actions** and add:
   - `SQLITECLOUD_URL`
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `OPENROUTER_API_KEY`
3. The workflow runs daily at **10:00 AM MT**. To trigger manually: **Actions → Daily Job Scrape → Run workflow**

To change the schedule, edit the cron line in `.github/workflows/daily_scrape.yml`:
```yaml
- cron: '0 17 * * *'  # 10:00 AM MST (UTC-7)
```

### Windows Task Scheduler (local machine)

Run once in an elevated PowerShell prompt:

```powershell
powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
```

Defaults to **10:00 AM daily**. Edit `$runAt` in `setup_scheduler.ps1` to change the time.

---

## Database

Jobs are stored in two tables. Query them directly:

```bash
# Most recent new jobs
uv run python -c "
import sqlite3
conn = sqlite3.connect('jobs.db')
for row in conn.execute('SELECT first_seen, company, title, location FROM jobs ORDER BY first_seen DESC LIMIT 20').fetchall():
    print(row)
"

# Remote US jobs and whether they allow working from Canada
uv run python -c "
import sqlite3
conn = sqlite3.connect('jobs.db')
for row in conn.execute('''
    SELECT j.company, j.title, j.location, e.canada_eligible, e.remote_geo
    FROM jobs j JOIN job_enrichments e ON j.url = e.url
    WHERE j.location LIKE \"%remote%\"
    ORDER BY e.canada_eligible DESC, j.company
''').fetchall():
    print(row)
"

# Enriched jobs with salary info
uv run python -c "
import sqlite3
conn = sqlite3.connect('jobs.db')
for row in conn.execute('''
    SELECT j.company, j.title, e.seniority, e.work_mode, e.salary_min, e.salary_max, e.salary_currency
    FROM jobs j JOIN job_enrichments e ON j.url = e.url
    WHERE e.enrichment_status = \"ok\" AND e.salary_min IS NOT NULL
    ORDER BY e.salary_min DESC LIMIT 20
''').fetchall():
    print(row)
"
```

### `jobs` table

| Column | Description |
|--------|-------------|
| `url` | Primary key — job posting URL |
| `company` | Company name |
| `title` | Job title |
| `location` | Location string from ATS |
| `posted` | Date posted (YYYY-MM-DD) |
| `ats` | ATS platform (greenhouse / lever / ashby / workable) |
| `description` | Full plain-text job description |
| `first_seen` | Date first scraped (YYYY-MM-DD) |
| `last_seen` | Date last confirmed active (YYYY-MM-DD) |

### `job_enrichments` table

| Column | Description |
|--------|-------------|
| `url` | Foreign key → `jobs.url` |
| `work_mode` | `remote` / `hybrid` / `onsite` |
| `remote_geo` | e.g. `"Canada only"`, `"North America"`, `"US only"` |
| `canada_eligible` | `yes` / `no` / `unknown` — can you work from Canada? |
| `seniority` | `intern` / `junior` / `mid` / `senior` / `staff` / `principal` |
| `role_family` | `data scientist` / `ml engineer` / `mlops engineer` / etc. |
| `years_exp_min` | Minimum years experience required |
| `years_exp_max` | Maximum (null if open-ended) |
| `must_have_skills` | JSON array of required skills |
| `nice_to_have_skills` | JSON array of preferred skills |
| `tech_stack` | JSON array of languages, frameworks, tools |
| `salary_min` | Annual minimum (null if not mentioned) |
| `salary_max` | Annual maximum |
| `salary_currency` | `CAD` / `USD` |
| `visa_sponsorship` | `yes` / `no` / `unknown` |
| `red_flags` | JSON array (e.g. `["requires clearance", "no sponsorship"]`) |
| `enrichment_status` | `ok` / `failed` / `skipped` |
| `enrichment_model` | Model used (e.g. `google/gemma-3-12b-it`) |
| `enriched_at` | ISO timestamp of enrichment |

---

## Title Filters

Jobs must match at least one **include** keyword and none of the **exclude** keywords (case-insensitive).

**Include:** machine learning, ml engineer, mlops, ai engineer, applied scientist, data scientist, data science, research scientist, nlp, llm, computer vision, generative ai

**Exclude:** sales, recruiter, marketing, legal, designer, customer success, director, vp, principal staff

Edit `TITLE_INCLUDE` and `TITLE_EXCLUDE` at the top of `scrape.py` to customise.

---

## Location Filter

The location filter runs on the raw ATS location string before any LLM call.

**Accepted:**
- Any location containing "canada"
- Canadian province or territory names ("ontario", "british columbia", "alberta", etc.)
- Canadian province abbreviations as whole tokens ("BC", "AB", "ON", "QC", etc.) — checked by splitting on punctuation so "ABC Corp" doesn't match
- Major Canadian cities ("Vancouver", "Toronto", "Calgary", "Edmonton", "Montreal", "Ottawa", etc.)
- Any "Remote ..." location — including "Remote US" and "Remote USA" — since US-based remote roles often allow Canadian workers (verified by the `canada_eligible` enrichment field)
- "Anywhere"
- Empty/unknown locations (let through)

**Rejected:**
- Non-remote US locations ("United States", "New York, NY", "San Francisco, CA", etc.)
- Remote roles explicitly restricted to: UK, Europe, Germany, France, Australia, India, Brazil, Japan, Singapore, Mexico

For "Remote US" jobs, the `canada_eligible` field extracted by the LLM from the full job description provides the definitive answer about whether you can actually work from Canada.

---

## LLM Enrichment

Each new job's full description is sent to an LLM via OpenRouter to extract structured metadata.
Uses **LangChain** (`ChatOpenAI`) for the API call and **Pydantic** (`JobEnrichment` model) for
output validation — invalid enum values, wrong types, and missing required fields are caught
automatically before the result is stored.

Two attempts are made per job: first with the full schema, then with a simplified prompt if the
first fails. `enrich_one_job()` never raises — it always returns a dict with `enrichment_status`
set to `ok`, `failed`, or `skipped`.

The enrichment is the **second check** for Canada eligibility: `canada_eligible` is extracted from
phrases like "must be authorized to work in the US" (→ `no`), "open to North America" (→ `yes`),
or no mention (→ `unknown`).

---

## Eval Framework

`eval/eval.py` measures general LLM extraction quality for AI/ML roles by comparing student models
against a high-quality teacher (default: `openai/gpt-5.2`). Uses a dedicated crawl DB
(`eval_jobs.db`) built without a location filter, covering a broader range of roles and geographies
than the production scraper sees.

```bash
# 1. Crawl jobs into eval_jobs.db (no location filter, broader title filter)
uv run python eval/eval.py crawl

# 2. Tag segments, write dataset.yaml
uv run python eval/eval.py build

# 3. Estimate cost before running
uv run python eval/eval.py cost

# 4. Quick sanity check (5 jobs)
uv run python eval/eval.py run --subset 5

# 5. Full eval — all 7 student models
uv run python eval/eval.py run

# 6. Print report with field-by-field breakdown
uv run python eval/eval.py report
```

**Default student models:**

| Model | Input $/M | Output $/M |
|-------|-----------|------------|
| `google/gemma-3-12b-it` | $0.04 | $0.13 |
| `google/gemma-3-27b-it` | $0.04 | $0.15 |
| `openai/gpt-oss-120b` | $0.039 | $0.19 |
| `nvidia/nemotron-3-nano-30b-a3b` | $0.05 | $0.20 |
| `mistralai/mistral-small-3.2-24b-instruct` | $0.06 | $0.18 |
| `qwen/qwen3-30b-a3b-thinking-2507` | $0.051 | $0.34 |
| `meta-llama/llama-4-scout` | $0.08 | $0.30 |
| `openai/gpt-5.2` *(teacher)* | $1.75 | $14.00 |

**Scoring:**
- Categorical (partial credit): `work_mode`, `canada_eligible`, `seniority`, `role_family`, `visa_sponsorship`
- List fields (F1 + Precision/Recall): `must_have_skills`, `nice_to_have_skills`, `tech_stack`, `red_flags`
- Overall = equal-weight mean across all 9 fields
- Skill normalization: aliases (`js→javascript`, `k8s→kubernetes`, etc.) + parenthetical stripping

**Report output:** field × model accuracy table · list field P/R diagnostics · `canada_eligible` confusion matrix · per-segment breakdown

See `eval/README.md` for full details.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `langchain-openai` | LLM calls via OpenRouter (ChatOpenAI) + structured output |
| `pydantic` | Output schema validation (`JobEnrichment` model) — pulled in by langchain-openai |
| `requests` | HTTP calls to ATS APIs and Telegram |
| `pyyaml` | Parse `companies.yaml` and `eval/dataset.yaml` |
| `rich` | Terminal table output |
| `sqlitecloud` | SQLite Cloud connection (falls back to stdlib `sqlite3` locally) |

All other functionality (threading, HTML parsing, JSON) uses Python stdlib.
