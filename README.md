# GoogleDocsBackup

`google-docs-backup` backs up Google Drive accounts with rclone and pandoc:

- Google Docs -> `.docx` + `.md` (images as ordinary local files, never base64)
- Google Sheets -> `.xlsx`
- Google Slides -> `.pptx`

Each run exports every account into `backups/<remote>/`, packs it into a
`snapshot-14NOV2026-23-47.tar`, uploads that to the account's own Drive
(`<remote>:Backups/`), and keeps the newest 3 snapshots there and in
`snapshots/<remote>/`.

## Moving, renaming and deleting on Drive

`backups/<remote>/` is an exact mirror of Drive (`mirror_deletes: true`):

| On Drive you... | Locally |
|---|---|
| move or rename a doc | it moves/renames locally too; its `.md` and `._media` follow |
| delete a doc or folder | it's removed locally |
| reorganize everything | the local tree is reorganized to match |

History lives in the snapshots: anything that disappears is still in the
newest 3. If Drive can't be listed completely (network drop, API error),
rclone skips all deletions that run, so a bad connection can't empty the
local copy. Files you put in `backups/` yourself (not `.docx`/`.xlsx`/`.pptx`)
are never touched. `mirror_deletes: false` goes back to add-only (moves then
leave duplicates).

## Run it

Double-click `run.bat` (Windows) or `run.command` (macOS), or:

```
./run.sh                          # macOS / Linux
python -m google_docs_backup            # anywhere, from the repo root
```

Or install it as a command:

```
pip install -e .
google-docs-backup                      # same as: google-docs-backup run
google-docs-backup run --remote gdrive  # one account
google-docs-backup run --dry-run        # show what would happen, change nothing
google-docs-backup run --no-snapshot    # skip the snapshot this time
google-docs-backup status               # is rclone running? how did the last run go?
google-docs-backup fetch-tools          # Windows: download rclone + pandoc
google-docs-backup auth gdrive2         # add / re-authorize an account
google-docs-backup auth --client-json   # switch all accounts to your own Google OAuth client
                                        # (newest client_secret_*.json in Downloads)
```

Needs Python 3.10+, `rclone` and `pandoc`. On macOS/Linux install them with
`brew install rclone pandoc` or `sudo apt install rclone pandoc`.

## Cancelling

Ctrl-C (or closing the window, or stopping the scheduled task) cancels cleanly:
rclone and pandoc are stopped, nothing half-written is left (`.md` files and
snapshots are written to a temp name and renamed only when complete), the
summary shows which accounts finished, and the log ends with
`--- backup cancelled ---` (exit code 130). Accounts that were cut off just
catch up on the next run. On Windows, rclone/pandoc also die with the backup
if it's killed hard (Task Manager); leftover partial files from that are
cleaned up at the start of the next run.

## Settings: `config.yaml`

Everything tweakable is in `config.yaml` in the repo root. It's found via
`--config`, then `$GOOGLE_DOCS_BACKUP_CONFIG`, then `./config.yaml`, then the one
next to the package. Relative paths in it are relative to the file itself.

- `paths.rclone_exe` / `paths.pandoc_exe`: leave these empty or wrong and the
  next run finds the tools (bin folder, PATH, Homebrew, /usr/bin, ...) and
  writes the paths back into `config.yaml`.
- `remotes`: one entry per Google account (`enabled: false` skips one).
- `parallel_remotes`: how many accounts back up at the same time (`0` = all
  at once, the default; `1` = one by one). One account failing doesn't stop
  the others.
- `snapshot`: `enabled`, `keep_drive`, `keep_local`, `format` (`tar` or `tar.gz`), `compress_level`,
  `name_prefix`, `local_dir`. Names carry the local date and time
  (`snapshot-14NOV2026-23-47.tar`), so every run keeps its own snapshot.
  Old snapshots removed from Drive go to Drive's trash (30 days). Only files
  matching `snapshot-DDMONYYYY[-HH-MM].tar[.gz]` are ever pruned. Plain `tar` is the default: the backup is already-compressed Office files, so gzip was ~15x slower for ~4% smaller.
- `exclude`: extra folders/files to skip. Each account's own `Backups/`
  folder is always skipped automatically, so snapshots never get backed up
  into themselves.
- `upload_to_drive`: also mirror `backups/<remote>` file-by-file into Drive
  (the old behaviour, off by default).

## Layout

| Path | What |
|---|---|
| `google_docs_backup/` | the Python package (`cli.py` is the entry point) |
| `config.yaml` | all settings |
| `pyproject.toml` | package metadata, the `google-docs-backup` command |
| `run.bat`, `run.sh`, `run.command` | double-click / one-word launchers |
| `install-service.bat`, `install-service.sh`, `install-service.command` | set up `.venv` + the scheduled service |
| `gitPushUpdate.bat` | commits everything as the next commit number and pushes |
| `backups/` | live backup, one folder per account (git-ignored) |
| `snapshots/` | local snapshots (git-ignored) |
| `private/rclone.conf` | Google tokens (git-ignored, never commit) |
| `bin/` | rclone + pandoc on Windows (git-ignored) |
| `logs/backup.log` | run log (git-ignored) |

## Install as a scheduled service

```
install-service.bat              # Windows (asks for admin)
./install-service.sh             # macOS / Debian / Linux
```

On macOS you can also double-click `install-service.command` in Finder.
(`.command` files open in Terminal; `.sh` files would open in a text editor.)

Both create `.venv`, install the package into it, and register the weekly run
with the OS's own scheduler. Run them again after changing `service:` in
`config.yaml`; `install-service.bat uninstall` / `./install-service.sh uninstall` removes it.

| OS | Scheduler | Runs while logged out? |
|---|---|---|
| Windows | Task Scheduler task `google_docs_backup`, as SYSTEM | yes (`windows_run_as: user`: no, but no admin needed) |
| macOS | launchd agent `~/Library/LaunchAgents/local.google_docs_backup.plist` | no; a missed run starts after wake |
| Linux | systemd timer `google_docs_backup.timer` (user units) | only with `sudo loginctl enable-linger $USER`, or set `linux_scope: system` and run `sudo ./install-service.sh` |

Missed runs (PC off at the scheduled time) start at the next chance on all
three. Directly:

```
google-docs-backup service install | uninstall | status | show
```

`show` prints the task XML / plist / unit files without installing anything.

## Exit codes

0 ok · 1 an account failed (export or snapshot) · 2 setup/config error ·
3 another run is in progress · 4 only pandoc errors
