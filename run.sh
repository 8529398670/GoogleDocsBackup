#!/usr/bin/env sh
# macOS / Linux equivalent of run.bat: runs the backup from the repo root.
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
"$PY" -m drive_backup "$@"
