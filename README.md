# GoogleDocsBackup

`google-docs-backup` backs up Google Drive accounts with rclone and pandoc:

- Google Docs -> `.docx` + `.md` (images as ordinary local files, never base64)
- Google Sheets -> `.xlsx`
- Google Slides -> `.pptx`

Each run exports every account into `backups/<remote>/`, packs it into a
`snapshot-14NOV2026.tar.gz`, uploads that to the account's own Drive
(`<remote>:Backups/`), and keeps the newest 5 snapshots there and in
`snapshots/<remote>/`.

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
google-docs-backup run --no-snapshot    # skip the tar.gz this time
google-docs-backup status               # is rclone running? how did the last run go?
google-docs-backup fetch-tools          # Windows: download rclone + pandoc
google-docs-backup auth gdrive2         # add / re-authorize an account
```

Needs Python 3.10+, `rclone` and `pandoc`. On macOS/Linux install them with
`brew install rclone pandoc` or `sudo apt install rclone pandoc`.

## Settings: `config.yaml`

Everything tweakable is in `config.yaml` in the repo root. It's found via
`--config`, then `$GOOGLE_DOCS_BACKUP_CONFIG`, then `./config.yaml`, then the one
next to the package. Relative paths in it are relative to the file itself.

- `paths.rclone_exe` / `paths.pandoc_exe`: leave these empty or wrong and the
  next run finds the tools (bin folder, PATH, Homebrew, /usr/bin, ...) and
  writes the paths back into `config.yaml`.
- `remotes`: one entry per Google account (`enabled: false` skips one).
- `snapshot`: `enabled`, `keep_drive`, `keep_local`, `compress_level`,
  `name_prefix`, `local_dir`. A second run on the same day replaces that
  day's snapshot. Old snapshots removed from Drive go to Drive's trash (30
  days). Only files matching `snapshot-DDMONYYYY.tar.gz` are ever pruned.
- `exclude: [/Backups/**]`: the export skips each account's own `Backups`
  folder, so snapshots never get backed up into themselves.
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
| `snapshots/` | local tar.gz snapshots (git-ignored) |
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
