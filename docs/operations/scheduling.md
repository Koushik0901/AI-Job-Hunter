# Scheduling and Automation

## GitHub Actions

Workflow files:

- `.github/workflows/daily_scrape.yml`
- `.github/workflows/enrichment.yml`

### `daily_scrape.yml` (scrape-only)

- Name: `Daily Job Scrape`
- Trigger:
  - scheduled cron `0 17 * * *`
  - manual `workflow_dispatch`
- Runner: `ubuntu-latest`
- Timeout: `30` minutes
- Run command: `uv run python src/cli.py scrape --no-enrich-llm`

Required secrets:

- `TURSO_URL`
- `TURSO_AUTH_TOKEN`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

### `enrichment.yml` (enrichment + formatting)

- Name: `Job Enrichment`
- Trigger:
  - scheduled cron `30 17 * * *`
  - manual `workflow_dispatch` with `processing_mode`:
    - `enrich_backfill`
    - `re_enrich_all`
    - `jd_reformat_missing`
    - `jd_reformat_all`
- Runner: `ubuntu-latest`
- Timeout: `30` minutes
- Run command:
  - `uv run python src/cli.py scrape --enrich-backfill`
  - or `uv run python src/cli.py scrape --re-enrich-all` (manual mode)
  - or `uv run python src/cli.py scrape --jd-reformat-missing` (manual mode)
  - or `uv run python src/cli.py scrape --jd-reformat-all` (manual mode)

Required secrets:

- `TURSO_URL`
- `TURSO_AUTH_TOKEN`
- `OPENROUTER_API_KEY`
- `ENRICHMENT_MODEL`
- `DESCRIPTION_FORMAT_MODEL`

## Windows Task Scheduler

Script: `setup_scheduler.ps1`

Behavior:

- Creates task `AIJobHunter`
- Default run time in script: `11:00AM`
- Runs `uv run python src/cli.py scrape` from repo directory
- Execution time limit: 30 minutes

Usage:

```powershell
powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
```

Remove task:

```powershell
Unregister-ScheduledTask -TaskName "AIJobHunter" -Confirm:$false
```
