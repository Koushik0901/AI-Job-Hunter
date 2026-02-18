# setup_scheduler.ps1
# Registers a Windows Task Scheduler task that runs the AI job scraper daily.
#
# Usage (from project directory, in an elevated PowerShell prompt):
#   powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1
#
# To change the run time, edit $runAt below before running.
# To remove the task later:
#   Unregister-ScheduledTask -TaskName "AIJobHunter" -Confirm:$false

$taskName  = "AIJobHunter"
$runAt     = "11:00AM"   # <-- change to your preferred daily run time

# Resolve project directory (same folder as this script)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Locate uv on PATH
$uvPath = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uvPath) {
    Write-Error "Could not find 'uv' on PATH. Install it from https://github.com/astral-sh/uv"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute $uvPath `
    -Argument "run python src/scrape.py" `
    -WorkingDirectory $scriptDir

$trigger = New-ScheduledTaskTrigger -Daily -At $runAt

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable $true `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Daily ML/AI job scraper with Telegram notifications" `
    -Force | Out-Null

Write-Host ""
Write-Host "Task '$taskName' registered successfully." -ForegroundColor Green
Write-Host "  Runs daily at: $runAt"
Write-Host "  Working dir:   $scriptDir"
Write-Host ""
Write-Host "To remove the task:"
Write-Host "  Unregister-ScheduledTask -TaskName '$taskName' -Confirm:`$false"
Write-Host ""
Write-Host "To run it now manually:"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'"
