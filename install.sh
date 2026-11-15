#!/usr/bin/env sh
# macOS / Debian / Linux installer: .venv + package + scheduled run
# (launchd agent on macOS, systemd timer on Linux).
#   ./install.sh             install / update
#   ./install.sh uninstall   remove the scheduled run
# With service.linux_scope: system in config.yaml, run it with sudo.
set -e
cd "$(dirname "$0")"

if [ "$1" = "uninstall" ]; then
  exec .venv/bin/python -m google_docs_backup service uninstall
fi

if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv ..."
  "$PY" -m venv .venv || {
    echo "Could not create a venv. On Debian/Ubuntu: sudo apt install python3-venv"
    exit 1
  }
fi

echo "Installing google-docs-backup into .venv ..."
.venv/bin/python -m pip install --disable-pip-version-check -q -e .

for tool in rclone pandoc; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "warning: $tool not found. macOS: brew install rclone pandoc   Debian: sudo apt install rclone pandoc"
  fi
done

.venv/bin/python -m google_docs_backup service install
echo
.venv/bin/python -m google_docs_backup service status || true
