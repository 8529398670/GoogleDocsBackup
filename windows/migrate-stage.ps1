$stage = 'C:\Users\juno\agent\drive-backup-stage'
$gd = Join-Path $stage 'gdrive'
$null = New-Item -ItemType Directory -Force -Path $gd
Get-ChildItem $stage -Force | Where-Object { $_.Name -notin @('gdrive', 'gdrive2') } |
  Move-Item -Destination $gd -Force
'--- after ---'
Get-ChildItem $stage
