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

## Set up Google API access (your own OAuth client)

Do this once. Without it, rclone uses its **shared** Google client, which is
heavily rate-limited (and being retired): big Drives crawl or stall, and the
log fills with `403 ... Quota exceeded ... rateLimitExceeded`. Your own client
gets its own quota and is free.

**1. Google Cloud Console** - <https://console.cloud.google.com/>, signed in
with any of your Google accounts:

1. Pick a project (top bar), or create one, e.g. `google-docs-backup`.
2. **APIs & Services → Library →** search **Google Drive API → Enable**.
3. **Google Auth Platform** (search for it, or *APIs & Services → OAuth
   consent screen*):
   - **Branding**: app name (e.g. `google-docs-backup`) and your email.
   - **Audience**: user type **External**, then **Publish app** so the
     status is **In production**. (In *Testing*, sign-ins expire every 7 days.)
4. **Clients → Create client** → application type **Desktop app**, name it
   `google-docs-backup` → **Create**.
5. In the "OAuth client created" dialog click **Download JSON** *before*
   closing it (the secret is only shown once), and save the file
   (`client_secret_....json`) into this project's **`config/`** folder.
   It's git-ignored; never commit it.

**2. Use it for every account** - from the project folder:

```
python -m google_docs_backup auth --client-json
```

It finds the newest `client_secret_*.json` in `config/` (then Downloads),
writes the client ID/secret into `private/rclone.conf` (git-ignored, never
printed), and signs in each enabled account in turn:

- Answer rclone's questions with **Enter** (the defaults: replace token =
  yes, use web browser = yes, Shared Drive = no).
- A browser opens: **pick the Google account that remote backs up** - check
  the name at the top before allowing.
- "Google hasn't verified this app" is expected for a personal app: click
  **Advanced → Go to google-docs-backup (unsafe) → Continue/Allow**.

It ends with `done: gdrive, gdrive2 signed in`.

**Adding another Google account later:** add it to `remotes:` in
`config/config.yaml` (e.g. `- {name: gdrive3, enabled: true}`), then
`python -m google_docs_backup auth gdrive3 --client-json`.

**If an account starts failing** with `invalid_grant` / token expired, or you
revoked access: `python -m google_docs_backup auth <name>` signs it in again.

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
                                        # (newest client_secret_*.json in ./config, then Downloads)
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

## Settings: `config/config.yaml`

Everything tweakable is in `config/config.yaml`. That file is git-ignored;
`config/config.example.yaml` is the template that's in git, and the first run
on a fresh clone copies it to `config/config.yaml` for you. Edit
`config.yaml`, not the example.

It's found via `--config`, then `$GOOGLE_DOCS_BACKUP_CONFIG`, then
`./config/config.yaml`, then the project's own. Relative paths in it are
relative to the project folder (the one containing `config/`), so
`./backups` means `<project>/backups`. `config/` is also where your Google
OAuth `client_secret_*.json` goes (git-ignored).

- `paths.rclone_exe` / `paths.pandoc_exe`: leave these empty or wrong and the
  next run finds the tools (bin folder, PATH, Homebrew, /usr/bin, ...) and
  writes the paths back into `config/config.yaml`.
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
| `config/config.example.yaml` | settings template (in git) |
| `config/config.yaml` | your settings (git-ignored, made from the template) |
| `config/client_secret_*.json` | your Google OAuth client (git-ignored) |
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
`config/config.yaml`; `install-service.bat uninstall` / `./install-service.sh uninstall` removes it.

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

The number the program returns when it finishes, so scripts and the scheduler
can tell how a run went:

| Code | Meaning |
|---|---|
| 0 | everything ok |
| 1 | an account failed (export or snapshot) |
| 2 | setup or config error |
| 3 | another run is already in progress |
| 4 | only some markdown conversions failed |
| 130 | cancelled (Ctrl-C, window closed, task stopped) |
