# Juno Drive backup — weekly.
#   Google Docs   -> .md (images as local files, never base64) + .docx
#   Google Sheets -> .xlsx
#   Google Slides -> .pptx
# Direction: everything is uploaded INTO Google Drive (<remote>:Backups),
# mirroring each account's folder structure. Drive is the backup.
# A local staging dir is used only for conversion, then uploaded.
# Remotes: gdrive  = banjo.kazooie.2955@gmail.com
#          gdrive2 = cerbus.collin@gmail.com
$bin   = 'C:\Users\juno\agent\bin'
$cfg   = 'C:\Users\juno\agent\rclone\rclone.conf'
$stage = 'C:\Users\juno\agent\drive-backup-stage'
$log   = 'C:\Users\juno\agent\rclone\backup.log'
$remotes = @('gdrive', 'gdrive2')

function Log($m){ $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'; Add-Content $log "$ts $m" }

Log '--- backup start ---'
foreach ($r in $remotes) {
  $rstage = Join-Path $stage $r
  $dest = "${r}:Backups"
  $null = New-Item -ItemType Directory -Force -Path $rstage
  Log "[$r] --- start ---"

  # 1. export native files from Drive into staging (skip our own Backups folder)
  & "$bin\rclone.exe" copy "${r}:" $rstage --config $cfg `
    --drive-export-formats 'docx,xlsx,pptx' `
    --include '*.docx' --include '*.xlsx' --include '*.pptx' `
    --exclude 'Backups/**' `
    --log-file $log --log-level NOTICE
  if ($LASTEXITCODE -ne 0) { Log "[$r] export failed, skipping"; continue }

  # 2. every docx also becomes markdown, images as ordinary local files
  Get-ChildItem -Path $rstage -Recurse -Filter '*.docx' -File | ForEach-Object {
    $md = [IO.Path]::ChangeExtension($_.FullName, '.md')
    $need = -not (Test-Path $md)
    if (-not $need) { $need = $_.LastWriteTime -gt (Get-Item $md).LastWriteTime }
    if ($need) {
      $media = ([IO.Path]::ChangeExtension($_.FullName, '') + '_media')
      if (Test-Path $media) { Remove-Item $media -Recurse -Force }
      & "$bin\pandoc.exe" -f docx -t markdown --wrap=none --extract-media="$media" $_.FullName -o $md
      if ($LASTEXITCODE -eq 0) {
        if ((Test-Path $media) -and -not (Get-ChildItem $media -Force)) { Remove-Item $media -Force }
        Log "[$r] md: $($_.Name)"
      } else { Log "[$r] PANDOC FAILED: $($_.FullName)" }
    }
  }

  # 3. upload the portable copies back into that account's Drive
  & "$bin\rclone.exe" copy $rstage $dest --config $cfg --log-file $log --log-level NOTICE
  Log "[$r] upload exit: $LASTEXITCODE"
}
Log '--- backup done ---'
