#Requires -RunAsAdministrator
# Points the weekly JunoDriveBackup task at the Python version (python/backup.py).
# Keeps the existing schedule, waits for any running backup to finish first,
# and saves the old task definition so it can be restored.
#
# Restore the PowerShell version:
#   Register-ScheduledTask -TaskName JunoDriveBackup -Force `
#     -Xml (Get-Content "$PSScriptRoot\JunoDriveBackup.old.xml" -Raw)

$ErrorActionPreference = 'Stop'
$task = 'JunoDriveBackup'
$repo = Split-Path $PSScriptRoot -Parent
$py   = Join-Path $repo 'python'
$venv = Join-Path $py '.venv'
$vpy  = Join-Path $venv 'Scripts\python.exe'

# 1. let the current run finish
while ((Get-ScheduledTask -TaskName $task).State -eq 'Running' -or (Get-Process rclone -ErrorAction SilentlyContinue)) {
  Write-Host "$(Get-Date -Format HH:mm:ss) backup still running, checking again in 60s..."
  Start-Sleep -Seconds 60
}
Write-Host 'no backup running'

# 2. a venv SYSTEM can use (user-site packages are invisible to SYSTEM)
if (-not (Test-Path $vpy)) {
  Write-Host 'creating venv...'
  & 'C:\Program Files\Python312\python.exe' -m venv $venv
}
& $vpy -m pip install --disable-pip-version-check -q -r (Join-Path $py 'requirements.txt')
& $vpy -c "import yaml, rich; print('deps ok')"

# 3. save the old definition
$old = Join-Path $PSScriptRoot 'JunoDriveBackup.old.xml'
if (-not (Test-Path $old)) { Export-ScheduledTask -TaskName $task | Out-File $old -Encoding utf8 }
Write-Host "old task saved to $old"

# 4. swap the action, keep triggers/principal/settings
$action = New-ScheduledTaskAction -Execute $vpy -Argument "`"$py\backup.py`" run" -WorkingDirectory $py
Set-ScheduledTask -TaskName $task -Action $action | Out-Null

$t = Get-ScheduledTask -TaskName $task
Write-Host "`nJunoDriveBackup now runs:"
$t.Actions | Format-List Execute, Arguments, WorkingDirectory
$t.Triggers | Format-List StartBoundary, DaysOfWeek, WeeksInterval
$t.Principal | Format-List UserId, RunLevel
Read-Host 'done - press Enter to close'
