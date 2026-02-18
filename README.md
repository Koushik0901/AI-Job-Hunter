# AI Job Hunter

A daily ML/AI/Data Science job scraper that monitors 38+ company career pages, stores results in **SQLite Cloud**, and sends Telegram notifications for new postings — grouped by country.

## Features

- Scrapes **Greenhouse, Lever, Ashby, and Workable** ATS platforms
- Filters jobs by **title keywords** (ML, AI, Data Science, NLP, LLM, etc.) and **location** (Canada + Remote)
- Fetches **full job descriptions** concurrently (ThreadPoolExecutor)
- Stores all jobs in **SQLite Cloud** (or a local SQLite file as fallback) with deduplication — only new postings trigger a notification
- Sends **Telegram notifications** grouped by 🇨🇦 Canada / 🌐 USA & Remote / 🌍 Other
- Runs **daily via GitHub Actions** (free) or Windows Task Scheduler

---

## Quickstart (Local)

### 1. Install dependencies

Requires Python 3.12+ and [uv](https://github.com/astral-sh/uv).

```bash
uv sync
```

### 2. Configure credentials

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

**Telegram bot** (for notifications):
1. Open Telegram → search **@BotFather** → send `/newbot` → copy the token
2. Send your bot any message, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat ID under `"chat":{"id":...}`

**SQLite Cloud** (for persistent storage):
1. Sign up at [sqlitecloud.io](https://sqlitecloud.io) (free tier: 1 GB)
2. Create a project → create a database named `jobs.db`
3. Copy the connection string from the dashboard (format: `sqlitecloud://host:8860/jobs.db?apikey=...`)

```
TELEGRAM_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
SQLITECLOUD_URL=sqlitecloud://your-host.sqlite.cloud:8860/jobs.db?apikey=your-key
```

If `SQLITECLOUD_URL` is not set, the scraper falls back to a local `jobs.db` file.

### 3. Run

```bash
uv run python scrape.py
```

On first run: scrapes all companies, saves to `jobs.db`, sends Telegram message for all new jobs.
On subsequent runs: only new postings trigger a notification.

---

## Usage

```
uv run python scrape.py [OPTIONS]

Options:
  --config PATH       Path to companies.yaml (default: companies.yaml next to script)
  --db PATH           Path to SQLite database (default: jobs.db next to script)
  --limit N           Max rows to display in terminal table (default: 50)
  --no-location-filter  Show all title-matched jobs, not just Canada/Remote
  --no-enrich         Skip fetching full descriptions (faster, no description stored)
  --no-notify         Skip Telegram notification even if credentials are configured
  --check SLUG        Probe all ATS platforms for a company slug (for discovery)
```

### Examples

```bash
# Standard daily run
uv run python scrape.py

# Browse all matched jobs worldwide (no location filter)
uv run python scrape.py --no-location-filter --limit 200

# Fast run without descriptions or notifications
uv run python scrape.py --no-enrich --no-notify

# Check if a company has a supported ATS board
uv run python scrape.py --check openai
```

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
uv run python scrape.py --check mistral
```

---

## Project Structure

```
ai-job-hunter/
├── scrape.py               # Main scraper — all logic lives here
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

Jobs are stored in `jobs.db` (SQLite). You can query it directly:

```bash
# Most recent new jobs
uv run python -c "
import sqlite3
conn = sqlite3.connect('jobs.db')
for row in conn.execute('SELECT first_seen, company, title, location FROM jobs ORDER BY first_seen DESC LIMIT 20').fetchall():
    print(row)
"
```

Schema:

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

---

## Title Filters

Jobs must match at least one **include** keyword and none of the **exclude** keywords (case-insensitive).

**Include:** machine learning, ml engineer, mlops, ai engineer, applied scientist, data scientist, data science, research scientist, nlp, llm, computer vision, generative ai

**Exclude:** sales, recruiter, marketing, legal, designer, customer success, director, vp, principal staff

Edit `TITLE_INCLUDE` and `TITLE_EXCLUDE` at the top of `scrape.py` to customise.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `requests` | HTTP calls to ATS APIs and Telegram |
| `pyyaml` | Parse `companies.yaml` |
| `rich` | Terminal table output |
| `sqlitecloud` | SQLite Cloud connection (falls back to stdlib `sqlite3` locally) |

All other functionality (threading, HTML parsing) uses Python stdlib.
