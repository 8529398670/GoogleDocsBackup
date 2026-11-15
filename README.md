# GoogleDocsBackup

`drive-backup` backs up Google Drive accounts with rclone and pandoc:

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
python -m drive_backup            # anywhere, from the repo root
```

Or install it as a command:

```
pip install -e .
drive-backup                      # same as: drive-backup run
drive-backup run --remote gdrive  # one account
drive-backup run --dry-run        # show what would happen, change nothing
drive-backup run --no-snapshot    # skip the tar.gz this time
drive-backup status               # is rclone running? how did the last run go?
drive-backup fetch-tools          # Windows: download rclone + pandoc
drive-backup auth gdrive2         # add / re-authorize an account
```

Needs Python 3.10+, `rclone` and `pandoc`. On macOS/Linux install them with
`brew install rclone pandoc` or `sudo apt install rclone pandoc`.

## Settings: `config.yaml`

Everything tweakable is in `config.yaml` in the repo root. It's found via
`--config`, then `$DRIVE_BACKUP_CONFIG`, then `./config.yaml`, then the one
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
| `drive_backup/` | the Python package (`cli.py` is the entry point) |
| `config.yaml` | all settings |
| `pyproject.toml` | package metadata, the `drive-backup` command |
| `run.bat`, `run.sh`, `run.command` | double-click / one-word launchers |
| `gitPushUpdate.bat` | commits everything as the next commit number and pushes |
| `backups/` | live backup, one folder per account (git-ignored) |
| `snapshots/` | local tar.gz snapshots (git-ignored) |
| `private/rclone.conf` | Google tokens (git-ignored, never commit) |
| `logs/backup.log` | run log (git-ignored) |

## Scheduled run (Windows)

The `JunoDriveBackup` task runs `.venv\Scripts\python.exe -m drive_backup`
from the repo root as SYSTEM, weekly on Sundays at 03:00.

## Exit codes

0 ok · 1 an account failed (export or snapshot) · 2 setup/config error ·
3 another run is in progress · 4 only pandoc errors
