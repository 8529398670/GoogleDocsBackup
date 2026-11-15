$ErrorActionPreference = 'Stop'
$bin = 'C:\Users\juno\agent\bin'
$null = New-Item -ItemType Directory -Force -Path $bin
$null = New-Item -ItemType Directory -Force -Path 'C:\Users\juno\agent\rclone'

# --- rclone ---
if (-not (Test-Path "$bin\rclone.exe")) {
  Write-Host 'downloading rclone...'
  $z = "$env:TEMP\rclone.zip"
  Invoke-WebRequest -Uri 'https://downloads.rclone.org/rclone-current-windows-amd64.zip' -OutFile $z
  $d = "$env:TEMP\rclone-x"; if (Test-Path $d) { Remove-Item $d -Recurse -Force }
  Expand-Archive -Path $z -DestinationPath $d
  $exe = Get-ChildItem -Path $d -Recurse -Filter 'rclone.exe' | Select-Object -First 1
  Copy-Item $exe.FullName "$bin\rclone.exe"
  Write-Host 'rclone ok'
} else { Write-Host 'rclone already present' }

# --- pandoc ---
if (-not (Test-Path "$bin\pandoc.exe")) {
  Write-Host 'resolving pandoc latest release...'
  $rel = Invoke-RestMethod -Uri 'https://api.github.com/repos/jgm/pandoc/releases/latest'
  $asset = $rel.assets | Where-Object { $_.name -like 'pandoc-*-windows-x86_64.zip' } | Select-Object -First 1
  if (-not $asset) { throw 'pandoc windows asset not found' }
  Write-Host "downloading $($asset.name) ..."
  $z = "$env:TEMP\pandoc.zip"
  Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $z
  $d = "$env:TEMP\pandoc-x"; if (Test-Path $d) { Remove-Item $d -Recurse -Force }
  Expand-Archive -Path $z -DestinationPath $d
  $exe = Get-ChildItem -Path $d -Recurse -Filter 'pandoc.exe' | Select-Object -First 1
  Copy-Item $exe.FullName "$bin\pandoc.exe"
  Write-Host 'pandoc ok'
} else { Write-Host 'pandoc already present' }

& "$bin\rclone.exe" version | Select-Object -First 1
& "$bin\pandoc.exe" --version | Select-Object -First 1
Write-Host 'FETCH_DONE'
