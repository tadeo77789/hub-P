# Registers the hub to start at Windows logon (Task Scheduler, current user).
# Run from the repo root after creating .venv and .env:
#   powershell -ExecutionPolicy Bypass -File scripts\install-startup.ps1
# Remove with:
#   Unregister-ScheduledTask -TaskName "Paula Hub" -Confirm:$false

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $repo ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $pythonw)) { throw "Missing $pythonw. Create the virtual environment first." }
if (-not (Test-Path (Join-Path $repo ".env"))) { throw "Missing .env. Copy .env.example and fill it in." }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m paula_hub" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName "Paula Hub" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Paula Port hub" -Force | Out-Null
Write-Host "Registered 'Paula Hub' to start at logon."
