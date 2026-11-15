param([string]$Remote = 'gdrive')
$ErrorActionPreference = 'Stop'
$bin = 'C:\Users\juno\agent\bin\rclone.exe'
$cfg = 'C:\Users\juno\agent\rclone\rclone.conf'
$log = "C:\Users\juno\agent\rclone\auth-$Remote.log"
$task = "JunoRcloneAuth-$Remote"
if (Test-Path $log) { Remove-Item $log -Force }
try { schtasks /delete /tn $task /f 2>$null | Out-Null } catch {}
$startAt = (Get-Date).AddMinutes(1).ToString('HH:mm')
$tr = "cmd /c `"$bin`" config create $Remote drive scope drive --config `"$cfg`" > `"$log`" 2>&1"
schtasks /create /tn $task /tr $tr /sc once /st $startAt /ru SYSTEM /f | Out-Null
schtasks /run /tn $task | Out-Null
Write-Host 'auth task started'
# wait for the auth URL to appear in the log
for ($i = 0; $i -lt 45; $i++) {
  Start-Sleep -Seconds 2
  if (Test-Path $log) {
    $t = Get-Content $log -Raw
    if ($t -match 'http://127\.0\.0\.1:\d+/auth\?state=\S+') { Write-Host "AUTH_URL $($Matches[0])"; break }
    if ($t -match '(?i)error|failed') { Write-Host "AUTH_LOG:"; Write-Host $t; break }
  }
}
