# AI Job Hunter

A daily ML/AI/Data Science job scraper that monitors 100+ company career pages, stores results in
**SQLite Cloud**, enriches job postings with **LLM-extracted metadata**, and sends Telegram
notifications for new postings — grouped by country.

## Features

- Scrapes **Greenhouse, Lever, Ashby, Workable, and SmartRecruiters** ATS platforms (100+ companies)
- Pulls ML/AI job comments from **HN "Who is Hiring?"** (monthly thread via Algolia API, no credentials needed)
- Filters jobs by **title keywords** (ML, AI, Data Science, NLP, LLM, etc.) and **location** (Canada + Remote)
- Fetches **full job descriptions** concurrently (ThreadPoolExecutor, 10 workers)
- **LLM enrichment** via OpenRouter — extracts seniority, work mode, skills, salary, visa sponsorship, and
  whether the role allows working from Canada (`canada_eligible`). Uses **LangChain** + **Pydantic** for
  structured output with automatic validation and provider-rotation on rate limits
- Stores all jobs in **SQLite Cloud** (or a local SQLite file as fallback) with deduplication
- Sends **Telegram notifications** grouped by 🇨🇦 Canada / 🌐 USA & Remote / 🌍 Other
- Runs **daily via GitHub Actions** (free) or Windows Task Scheduler
- **Interactive company discovery** (`add_company.py`) — start from just a company name, auto-probe
  all ATS platforms, and append the match to `companies.yaml`
- **Eval framework** — compare N enrichment models side-by-side against a teacher model across 14 fields

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

### `src/scrape.py` — Daily scraper

```
uv run python src/scrape.py [OPTIONS]

Options:
  --config PATH          Path to companies.yaml (default: companies.yaml in current directory)
  --db PATH              Path to local SQLite file (default: jobs.db). Ignored if SQLITECLOUD_URL is set.
  --limit N              Max rows to display in terminal table (default: 50)
  --no-location-filter   Show all title-matched jobs, not just Canada/Remote
  --no-enrich            Skip fetching full descriptions (faster, no description stored)
  --no-notify            Skip Telegram notification even if credentials are configured
  --no-enrich-llm        Skip LLM enrichment even if OPENROUTER_API_KEY is set
  --enrich-backfill      Enrich all unenriched/failed jobs in DB, then exit (no scraping)
  --check SLUG           Probe all 5 ATS platforms for a company slug (for discovery)
  --import-companies     Fetch community GitHub lists and append new companies to companies.yaml
  --dry-run              With --import-companies: preview without writing
```

#### Examples

```bash
# Standard daily run
uv run python src/scrape.py

# Browse all matched jobs worldwide (no location filter)
uv run python src/scrape.py --no-location-filter --limit 200

# Fast run without descriptions, notifications, or enrichment
uv run python src/scrape.py --no-enrich --no-notify --no-enrich-llm

# Backfill LLM enrichment on all existing unenriched/failed jobs
uv run python src/scrape.py --enrich-backfill

# Check if a company has a supported ATS board (need to know slug)
uv run python src/scrape.py --check mistral
```

---

### `src/add_company.py` — Interactive Company Discovery

Start from just a company name — no slug required. The script auto-generates slug candidates,
probes all 5 ATS platforms concurrently, and offers to append the match to `companies.yaml`.

```
uv run python src/add_company.py COMPANY [OPTIONS]

Positional:
  company                Company name (e.g. "Hugging Face")

Options:
  --slug SLUG            Extra slug to probe in addition to auto-generated ones (repeatable)
  --add                  Non-interactive: auto-add all new matches without prompting
  --config PATH          Path to companies.yaml (default: companies.yaml in current directory)
```

#### Examples

```bash
# Auto-discover (tries huggingface, hugging-face, hugging, ...)
uv run python src/add_company.py "Hugging Face"

# Provide a specific slug to narrow the search
uv run python src/add_company.py "Toyota Research Institute" --slug tri

# Provide multiple slugs
uv run python src/add_company.py "Toyota" --slug tri --slug toyota-research

# Non-interactive (useful in scripts)
uv run python src/add_company.py "Scale AI" --slug scaleai --add

# Verify the entry was added
grep -A3 "Scale AI" companies.yaml
```

**How slug generation works:**
Given "Hugging Face Inc", the script generates candidates from the full name and suffix-stripped form
("Hugging Face" after removing "Inc"):
- `huggingface` — joined, no separators
- `hugging-face` — hyphenated
- `hugging` — first word only

**Zero-job hits are suppressed automatically.** SmartRecruiters and Workable return HTTP 200
for any slug; hits with 0 active jobs are hidden from the results table and never offered for adding.
A dim note shows how many zero-job hits were suppressed.

**Duplicate detection is cross-platform.** Before offering to add a match, the script checks
`companies.yaml` in two ways:
1. Exact `ats_url` match — same company, same platform
2. Slug appears as a path segment in any existing entry's URL — same company, different platform
   (e.g., won't offer to add `openai` on SmartRecruiters if `openai` is already in Greenhouse)

Prints `Already in companies.yaml as '<existing name>'` and skips duplicates automatically.

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

## Job Sources

| Source | Type | Notes |
|--------|------|-------|
| **Greenhouse** | ATS API | `boards-api.greenhouse.io` — job list + per-job description fetch |
| **Lever** | ATS API | `api.lever.co` — full description included in list response (no extra request) |
| **Ashby** | ATS HTML | `jobs.ashbyhq.com` — HTML scrape + embedded `__NEXT_DATA__` JSON |
| **Workable** | ATS API | `apply.workable.com` — POST to jobs endpoint + per-job description fetch |
| **SmartRecruiters** | ATS API | `api.smartrecruiters.com` — REST API for listings + description fetch |
| **HN "Who is Hiring?"** | Community | Monthly Algolia scrape — latest Ask HN thread; ~50–200 ML/AI comments per month. No credentials needed. |

---

## Adding Companies

Three methods are available:

### Method 1: Interactive discovery (`add_company.py`) — recommended for individual companies

```bash
uv run python src/add_company.py "Anthropic"
```

See [add_company.py usage](#srcadd_companypy--interactive-company-discovery) above.

### Method 2: Slug probe (`--check`) — when you know the slug

```bash
uv run python src/scrape.py --check anthropic
```

Probes all 5 ATS platforms and prints which ones have a live board for that slug.
Does not modify `companies.yaml` — copy the matching URL manually.

### Method 3: Bulk import (`--import-companies`) — for adding many companies at once

Fetches 3 community GitHub lists and appends new companies to `companies.yaml`:

```bash
# Step 1: Preview (dry run)
uv run python src/scrape.py --import-companies --dry-run

# Step 2: Import
uv run python src/scrape.py --import-companies
```

**Sources fetched:**
- `pittcsc/Summer2024-Internships` — HTML table, Greenhouse + Lever (~100 companies)
- `j-delaney/easy-application` — markdown, Greenhouse + Lever (~10 companies)
- `SimplifyJobs/New-Grad-Positions` — HTML table, Greenhouse + Lever + SmartRecruiters

The dry-run table shows a **Source** column so you can see which list each company came from.
Duplicates (same slug already in `companies.yaml`) are automatically skipped.

### Method 4: Direct edit — for full control

Edit `companies.yaml` directly. Each entry needs `name`, `ats_type`, `ats_url`, and `enabled`:

```yaml
companies:
  - name: Cohere
    ats_type: ashby
    ats_url: https://jobs.ashbyhq.com/cohere
    enabled: true

  - name: Unity Technologies
    ats_type: smartrecruiters
    ats_url: https://api.smartrecruiters.com/v1/companies/UnityTechnologies/postings
    enabled: true
```

Supported `ats_type` values: `greenhouse`, `lever`, `ashby`, `workable`, `smartrecruiters`.

**ATS URL formats:**

| ATS | URL template |
|-----|-------------|
| `greenhouse` | `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs` |
| `lever` | `https://api.lever.co/v0/postings/{slug}` |
| `ashby` | `https://jobs.ashbyhq.com/{slug}` |
| `workable` | `https://apply.workable.com/api/v3/accounts/{slug}/jobs` |
| `smartrecruiters` | `https://api.smartrecruiters.com/v1/companies/{slug}/postings` |

To disable a company temporarily without removing it, set `enabled: false`.

---

## Project Structure

```
ai-job-hunter/
├── src/
│   ├── scrape.py           # CLI entry point: main(), scrape_all(), filters, --check, --import-companies
│   ├── add_company.py      # Interactive company discovery: slug gen + ATS probing + yaml append
│   ├── fetchers.py         # ATS fetchers, normalizers, description helpers, retry decorator
│   ├── db.py               # SQLite persistence (jobs + job_enrichments tables, migrations)
│   ├── notify.py           # .env loader, Telegram formatting and sending, bucket_country()
│   └── enrich.py           # LLM enrichment pipeline (LangChain + Pydantic, rate-limit retry)
├── eval/
│   ├── eval.py             # Eval framework: crawl / build / cost / run / report
│   ├── eval_jobs.db        # Local crawl DB (git-ignored)
│   ├── dataset.yaml        # Curated eval dataset (auto-generated + manual jobs)
│   └── results/            # JSON results files + checkpoint.json (git-ignored)
├── companies.yaml          # List of companies to scrape
├── prompts.yaml            # LLM prompt templates (reference copy; actual strings in enrich.py)
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
- cron: '0 17 * * *'  # 10:00 AM MST (UTC-7 in winter, UTC-6 in summer)
```

### Windows Task Scheduler (local machine)

Run once in an elevated PowerShell prompt:

```powershell
powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
```

Defaults to **10:00 AM daily**. Edit `$runAt` in `setup_scheduler.ps1` to change the time.

---

## Database

Jobs are stored in two tables:

### `jobs` table

| Column | Type | Description |
|--------|------|-------------|
| `url` | TEXT PK | Job posting URL (unique identifier) |
| `company` | TEXT | Company name |
| `title` | TEXT | Job title |
| `location` | TEXT | Location string from ATS |
| `posted` | TEXT | Date posted (YYYY-MM-DD) |
| `ats` | TEXT | Platform: `greenhouse` / `lever` / `ashby` / `workable` / `smartrecruiters` / `hn_hiring` |
| `description` | TEXT | Full plain-text job description |
| `first_seen` | TEXT | Date first scraped (YYYY-MM-DD) |
| `last_seen` | TEXT | Date last confirmed active (YYYY-MM-DD) |

### `job_enrichments` table

| Column | Type | Description |
|--------|------|-------------|
| `url` | TEXT PK/FK | Foreign key → `jobs.url` |
| `work_mode` | TEXT | `remote` / `hybrid` / `onsite` / null |
| `remote_geo` | TEXT | e.g. `"Canada only"`, `"North America"`, `"US only"` |
| `canada_eligible` | TEXT | `yes` / `no` / `unknown` — can you work from Canada? |
| `seniority` | TEXT | `intern` / `junior` / `mid` / `senior` / `staff` / `principal` |
| `role_family` | TEXT | `data scientist` / `ml engineer` / `mlops engineer` / `data engineer` / `research scientist` / `analyst` / `other` |
| `years_exp_min` | INTEGER | Minimum years experience required |
| `years_exp_max` | INTEGER | Maximum (null if open-ended) |
| `required_skills` | TEXT | JSON array of required skills/tools/certs |
| `preferred_skills` | TEXT | JSON array of preferred/nice-to-have skills |
| `salary_min` | INTEGER | Annual minimum (null if not mentioned) |
| `salary_max` | INTEGER | Annual maximum |
| `salary_currency` | TEXT | `CAD` / `USD` |
| `visa_sponsorship` | TEXT | `yes` / `no` / `unknown` |
| `red_flags` | TEXT | JSON array of Canada-ineligibility phrases (verbatim quotes) |
| `enrichment_status` | TEXT | `ok` / `failed` / `skipped` (no description) |
| `enrichment_model` | TEXT | Model used (e.g. `google/gemma-3-12b-it`) |
| `enriched_at` | TEXT | ISO timestamp of enrichment |

### Query examples

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

# Jobs where required skills include Python (JSON search)
uv run python -c "
import sqlite3, json
conn = sqlite3.connect('jobs.db')
for row in conn.execute(\"SELECT j.company, j.title, e.required_skills FROM jobs j JOIN job_enrichments e ON j.url = e.url WHERE e.enrichment_status = 'ok'\").fetchall():
    skills = json.loads(row[2] or '[]')
    if any('python' in s.lower() for s in skills):
        print(row[0], '|', row[1])
"
```

---

## Title Filters

Jobs must match at least one **include** keyword and none of the **exclude** keywords (case-insensitive).
Defined in `TITLE_INCLUDE` and `TITLE_EXCLUDE` at the top of `src/scrape.py`.

**Include keywords:**
`machine learning`, `ml engineer`, `mlops`, `ml ops`, `applied ml`, `ai engineer`,
`applied scientist`, `data scientist`, `data science`, `research scientist`,
`nlp`, `llm`, `computer vision`, `generative ai`

**Exclude keywords:**
`sales`, `recruiter`, `marketing`, `legal`, `hr `, `designer`, `customer success`,
`director`, `vp `, `principal staff`

The eval framework uses a broader `EVAL_TITLE_INCLUDE` superset that also includes:
`deep learning`, `reinforcement learning`, `ml researcher`, `ai researcher`,
`ml intern`, `ai intern`, `data science intern`

---

## Location Filter

The location filter runs on the raw ATS location string before any LLM call.
Defined in `passes_location_filter()` in `src/scrape.py`.

**Accepted:**
- Empty/unknown locations (let through for LLM to decide)
- Any location containing "canada"
- Canadian province/territory full names: Ontario, British Columbia, Alberta, Quebec, Nova Scotia,
  New Brunswick, Prince Edward Island, Newfoundland, Labrador, Manitoba, Saskatchewan,
  Northwest Territories, Yukon, Nunavut
- Canadian province abbreviations as **whole tokens** (checked by splitting on punctuation/whitespace):
  BC, AB, ON, QC, NS, NB, PEI, NL, MB, SK, NT, YT, NU
  (so "Vancouver, BC" matches but "ABC Corp" does not)
- Major Canadian cities: Vancouver, Toronto, Calgary, Edmonton, Montreal, Ottawa, Winnipeg,
  Halifax, Victoria, Waterloo, Kitchener
- Any "Remote..." location — **including "Remote US" and "Remote USA"** — since US-based remote
  roles often allow Canadian workers (verified by the `canada_eligible` LLM field)
- "Anywhere"

**Rejected:**
- Non-remote US locations ("United States", "New York, NY", "San Francisco, CA", plain "US", "USA")
- Remote roles explicitly restricted to: UK, United Kingdom, Europe, Germany, France,
  Australia, India, Brazil, Japan, Singapore, Mexico

For "Remote US" jobs, `canada_eligible` extracted by the LLM from the full job description provides
the definitive answer about whether you can actually work from Canada.

---

## LLM Enrichment

Each new job's full description is sent to an LLM via OpenRouter to extract structured metadata.
Uses **LangChain** (`ChatOpenAI`) for the API call and **Pydantic** (`JobEnrichment` model) for
output validation — invalid enum values, wrong types, and missing required fields are handled by
field validators that coerce values to safe defaults (e.g. unrecognized `work_mode` → `null`).

### Extracted fields

| Field | Values | Notes |
|-------|--------|-------|
| `work_mode` | `remote` / `hybrid` / `onsite` / null | Delivery model |
| `remote_geo` | Free text | Geographic scope (e.g. "North America", "US only") |
| `canada_eligible` | `yes` / `no` / `unknown` | Key field: can you work from Canada? |
| `seniority` | `intern`–`principal` / null | Career level from title + requirements |
| `role_family` | 7 options | Closest functional category |
| `years_exp_min/max` | integer / null | Extracted from "3-5 years" patterns |
| `required_skills` | JSON array | From Requirements/Qualifications sections |
| `preferred_skills` | JSON array | From Nice to Have/Preferred sections |
| `salary_min/max` | integer / null | Full dollar amounts (e.g. 150000, not 150k) |
| `salary_currency` | `CAD` / `USD` / null | — |
| `visa_sponsorship` | `yes` / `no` / `unknown` | — |
| `red_flags` | JSON array | Verbatim phrases signalling Canada-ineligibility |

### Two-attempt strategy

1. First attempt: full `JobEnrichment` schema + one-shot example
2. If that fails (non-rate-limit error): simplified prompt (no example)
3. Jobs with no description text are `skipped` immediately (no API call)

### Rate-limit handling

The enrichment pipeline retries up to **3 times** per job on HTTP 429:
1. Identifies which OpenRouter provider rate-limited the request (from error message)
2. Excludes that provider on the next retry via OpenRouter's `provider.ignore` field
3. If provider is unknown: asks OpenRouter to `sort_by="throughput"` to prefer less-loaded providers
4. Only raises `RateLimitSignal` (stopping the pipeline) after all 3 retries fail

When the pipeline stops: unprocessed jobs stay `NULL` in the DB. Resume with:
```bash
uv run python src/scrape.py --enrich-backfill
```

### Concurrency

`run_enrichment_pipeline()` uses `ThreadPoolExecutor(max_workers=5)` — enough for good throughput
without hammering the API.

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

# 5. Full eval — all 7 student models vs teacher
uv run python eval/eval.py run

# 6. Resume after rate limit
uv run python eval/eval.py run --resume

# 7. Print report with field-by-field breakdown
uv run python eval/eval.py report

# Specify models or teacher explicitly
uv run python eval/eval.py run --models google/gemma-3-12b-it meta-llama/llama-4-scout
uv run python eval/eval.py run --teacher openai/gpt-4o --subset 10
```

### Default student models

| Model | Input $/M | Output $/M |
|-------|-----------|------------|
| `google/gemma-3-12b-it` | $0.04 | $0.13 |
| `google/gemma-3-27b-it` | $0.04 | $0.15 |
| `openai/gpt-oss-120b` | $0.039 | $0.19 |
| `nvidia/nemotron-3-nano-30b-a3b` | ~$1.00 | ~$4.00 |
| `mistralai/mistral-small-3.2-24b-instruct` | $0.06 | $0.18 |
| `qwen/qwen3-30b-a3b-thinking-2507` | $0.051 | $0.34 |
| `meta-llama/llama-4-scout` | $0.08 | $0.30 |
| `openai/gpt-5.2` *(teacher)* | $1.75 | $14.00 |

### Scoring (14 fields, equal-weight mean)

- **Categorical** (partial credit for adjacent values): `work_mode`, `canada_eligible`, `seniority`, `role_family`, `visa_sponsorship`
- **List fields** (F1 + Precision/Recall with skill normalization): `required_skills`, `preferred_skills`, `red_flags`
- **Numeric** (ordinal tolerance: ±1yr = 0.75 credit): `years_exp_min`, `years_exp_max`
- **Salary** (percentage tolerance + unit normalization): `salary_min`, `salary_max`, `salary_currency`
- **Skill normalization**: aliases (`js→javascript`, `k8s→kubernetes`, `torch→pytorch`, `ts→typescript`, `postgres→postgresql`) + parenthetical stripping before F1 computation
- **Not scored**: `remote_geo` (free-form string, no reliable automatic comparison)

### Segments (6)

`core` · `remote_geo_edge` · `red_flag` · `seniority_extreme` · `salary_disclosed` · `sparse`

### Checkpointing

The eval writes `eval/results/checkpoint.json` after every single job result (atomic write via `.tmp` rename).
On rate limit or interruption: resume exactly where you left off with `--resume`.
The checkpoint is invalidated if you change the teacher model, student models, or job set.

### Report output

- Field × model accuracy table (overall + per-field scores)
- List field P/R/F1 diagnostics for `required_skills`, `preferred_skills`, `red_flags`
- `canada_eligible` confusion matrix (teacher vs each student)
- Per-segment score breakdown

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `langchain-openai` | LLM calls via OpenRouter (`ChatOpenAI`) + structured output (`with_structured_output`) |
| `pydantic` | Output schema validation (`JobEnrichment` model) — transitively from langchain-openai |
| `requests` | HTTP calls to ATS APIs, Algolia, and Telegram |
| `pyyaml` | Parse `companies.yaml` and `eval/dataset.yaml` |
| `rich` | Terminal table output and console formatting |
| `sqlitecloud` | SQLite Cloud connection — API-compatible with stdlib `sqlite3` |

All other functionality (threading, HTML parsing, JSON, regex, date handling) uses Python stdlib.
