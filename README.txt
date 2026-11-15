Google Docs backup program - copies, 2026-11-14.
Live program: C:\Users\juno\agent\scripts\ (drive-backup.ps1 etc.).
The weekly scheduled task JunoDriveBackup still runs the live copy there, Sundays 03:00.

drive-backup.ps1 expects:
  tools:  C:\Users\juno\agent\bin (rclone.exe, pandoc.exe)
  config: C:\Users\juno\agent\rclone\rclone.conf
  stage:  C:\Users\juno\agent\drive-backup-stage
  log:    C:\Users\juno\agent\rclone\backup.log

rclone.conf was NOT copied here - it holds the Google account tokens.
The staging folder (exported Drive files) and logs were not copied either.

Files in this folder:
  drive-backup.ps1      the backup: Docs -> .md + .docx, Sheets -> .xlsx, Slides -> .pptx, uploaded into Drive Backups
  fetch-tools.ps1       downloads rclone + pandoc into the bin folder
  start-rclone-auth.ps1 adds a Drive account (rclone remote) via an auth task
  migrate-stage.ps1     one-off staging-folder move, Sep 2026
  check_rclone.ps1      checks whether rclone is currently running
