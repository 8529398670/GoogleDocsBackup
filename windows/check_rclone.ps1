$procs = Get-Process rclone -ErrorAction SilentlyContinue
if ($procs) {
  foreach ($p in $procs) { Write-Output ("RUNNING " + $p.Id) }
} else {
  Write-Output "NOT_RUNNING"
}
