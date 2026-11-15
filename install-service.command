#!/usr/bin/env sh
# macOS: double-click this in Finder to install the scheduled backup in Terminal.
cd "$(dirname "$0")" || exit 1
./install-service.sh "$@"
printf '\nPress Enter to close...'
read -r _
