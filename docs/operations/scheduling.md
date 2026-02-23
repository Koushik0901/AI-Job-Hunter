# Scheduling and Automation

## GitHub Actions

Workflow file: `.github/workflows/daily_scrape.yml`

Current configuration:

- Name: `Daily Job Scrape`
- Trigger:
  - scheduled cron `0 17 * * *`
  - manual `workflow_dispatch`
- Runner: `ubuntu-latest`
- Timeout: `30` minutes
- Run command: `uv run python src/scrape.py`

Required secrets:

- `TURSO_URL`
- `TURSO_AUTH_TOKEN`
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`
- `OPENROUTER_API_KEY`

## Windows Task Scheduler

Script: `setup_scheduler.ps1`

Behavior:

- Creates task `AIJobHunter`
- Default run time in script: `11:00AM`
- Runs `uv run python src/scrape.py` from repo directory
- Execution time limit: 30 minutes

Usage:

```powershell
powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
```

Remove task:

```powershell
Unregister-ScheduledTask -TaskName "AIJobHunter" -Confirm:$false
```
