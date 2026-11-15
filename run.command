#!/usr/bin/env sh
# macOS: double-click this in Finder to run the backup in Terminal.
cd "$(dirname "$0")" || exit 1
./run.sh
printf '\nPress Enter to close...'
read -r _
