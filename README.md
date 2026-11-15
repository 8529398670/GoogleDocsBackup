# GoogleDocsBackup

A copy of the Google Drive backup program that runs on the HP EliteBook.
Google Drive is the backup: Docs, Sheets, and Slides are exported from two
Google accounts, converted to portable formats, and uploaded back into each
account's Drive `Backups` folder, mirroring the folder structure.

> This folder is a copy for reference. The live program runs from
> `C:\Users\juno\agent\scripts\`, and the weekly scheduled task
> `JunoDriveBackup` still runs that live copy (Sundays 03:00, as SYSTEM).
> Editing the copies here does not change the backup.

## What it backs up

- Google Docs -> `.md` (images as ordinary local files, never base64) + `.docx`
- Google Sheets -> `.xlsx`
- Google Slides -> `.pptx`
- Remotes: `gdrive` (banjo.kazooie.2955@gmail.com),
  `gdrive2` (cerbus.collin@gmail.com)
- Each account's own `Backups/**` folder is excluded from the export, so the
  backup never backs itself up.

## How a run works (`drive-backup.ps1`)

1. For each remote, rclone exports the native files into a local staging dir
   (`--drive-export-formats docx,xlsx,pptx`, only those three types). If the
   export fails, it logs `export failed, skipping` and moves on to the next
   remote.
2. Every `.docx` is also converted to Markdown with pandoc
   (`--extract-media`, images land in a `*_media` folder next to the `.md`).
   It only re-converts when the `.docx` is newer than the `.md`. Empty media
   folders are cleaned up; a failed conversion is logged as `PANDOC FAILED`.
3. The portable tree is uploaded into `<remote>:Backups`, preserving folder
   structure. Staging is temporary - conversion only, then uploaded.

## Files in this folder

- `drive-backup.ps1` - the backup itself (above)
- `fetch-tools.ps1` - downloads rclone + pandoc into the bin folder
- `start-rclone-auth.ps1` - adds a Drive account (creates an rclone remote)
  via an auth task
- `migrate-stage.ps1` - one-off staging-folder move, Sep 2026
- `check_rclone.ps1` - checks whether rclone is currently running
- `gitPushUpdate.bat` - commits everything in this folder with the next
  commit number as the message, then pushes (keeps this copy in git)

## Live paths (where the running program actually lives)

- Scripts: `C:\Users\juno\agent\scripts\`
- Tools: `C:\Users\juno\agent\bin` (rclone.exe, pandoc.exe)
- rclone config: `C:\Users\juno\agent\rclone\rclone.conf`
- Staging: `C:\Users\juno\agent\drive-backup-stage` (transient)
- Log: `C:\Users\juno\agent\rclone\backup.log`
- Schedule: `JunoDriveBackup`, weekly Sundays 03:00

`rclone.conf` was deliberately NOT copied here - it holds the Google account
tokens. The staging folder and logs were not copied either.

## Running it by hand

Start the scheduled task (uses the live copy):

```
Start-ScheduledTask JunoDriveBackup
```

Then watch the log: check `C:\Users\juno\agent\rclone\backup.log` for
`--- backup done ---` and the per-remote results.

## If something looks wrong

- Check `backup.log` first. A run logs `--- backup start ---` /
  `--- backup done ---` and one `--- start ---` per remote; an export failure
  logs `export failed, skipping`.
- 2026-11-09 run: the `gdrive2` export failed with 401 invalid credentials
  (plus a DNS lookup failure). If `gdrive2` keeps being skipped, re-authorize
  that remote with `start-rclone-auth.ps1`.
- rclone logs a NOTICE that its shared Google Drive client_id is being
  retired during 2026. If Drive auth starts failing later, that is the first
  thing to check.
