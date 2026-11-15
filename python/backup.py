"""Google Drive backup - Python version.

  python backup.py run [--remote NAME] [--dry-run]
  python backup.py fetch-tools
  python backup.py auth NAME
  python backup.py status

All settings live in config.yaml next to this file (override with --config).
"""
from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from drive_backup import auth, runner, tools
from drive_backup.config import load

HERE = Path(__file__).resolve().parent


def status(cfg, console: Console) -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq rclone.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True).stdout
    pids = [row[1] for row in csv.reader(io.StringIO(out)) if len(row) > 1]
    console.print(f"rclone: [yellow]RUNNING[/] (pid {', '.join(pids)})" if pids
                  else "rclone: [green]NOT_RUNNING[/]")

    log = cfg.paths.log
    if not log.exists():
        console.print(f"no log yet at {log}")
        return 0
    with open(log, "rb") as f:  # read only the tail; the log can get big
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 512 * 1024))
        tail = f.read().decode("utf-8", errors="replace").splitlines()
    starts = [i for i, l in enumerate(tail) if "--- backup start ---" in l]
    last = tail[starts[-1]:] if starts else tail[-20:]
    keys = ("---", "summary:", "exit:", "failed", "FAILED")
    ours = [l for l in last if any(k in l for k in keys)]
    console.print("[bold]last run:[/]")
    for l in ours[-30:]:
        console.print(f"  {l}", markup=False, highlight=False)
    if starts and not any("--- backup done ---" in l for l in last):
        console.print("  [yellow](no 'backup done' yet - still running or it stopped early)[/]")
    return 0


def main() -> int:
    # Old Windows consoles / redirected output default to cp1252, which can't
    # draw the progress spinner or file names with non-Latin characters.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap =argparse.ArgumentParser(description="Google Drive backup")
    ap.add_argument("--config", type=Path, default=HERE / "config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="export, convert and upload")
    p_run.add_argument("--remote", help="only back up this remote")
    p_run.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    sub.add_parser("fetch-tools", help="download rclone + pandoc if missing")
    p_auth = sub.add_parser("auth", help="add or re-authorize a Drive remote (admin)")
    p_auth.add_argument("remote")
    sub.add_parser("status", help="is rclone running, and how did the last run go")
    a = ap.parse_args()

    console = Console()
    try:
        cfg = load(a.config)
    except (OSError, ValueError, TypeError) as e:
        console.print(f"[red]config error:[/] {e}")
        return 2

    if a.cmd == "run":
        return runner.run(cfg, a.remote, a.dry_run, console)
    if a.cmd == "fetch-tools":
        return tools.fetch(cfg, console)
    if a.cmd == "auth":
        return auth.start(cfg, a.remote, console)
    return status(cfg, console)


if __name__ == "__main__":
    sys.exit(main())
