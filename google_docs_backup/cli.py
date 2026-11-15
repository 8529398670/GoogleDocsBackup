"""google-docs-backup: back up Google Drive accounts with rclone + pandoc.

  google-docs-backup                      (same as: run)
  google-docs-backup run [--remote NAME] [--dry-run] [--no-snapshot]
  google-docs-backup status
  google-docs-backup fetch-tools
  google-docs-backup auth NAME
  google-docs-backup service install|uninstall|status|show

Also works as `python -m google_docs_backup ...`. Settings live in config.yaml
(see --config for how it is found).
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from . import __version__, auth, cancel, runner, service, tools
from .config import load

REPO_ROOT = Path(__file__).resolve().parent.parent


def default_config() -> Path:
    """$GOOGLE_DOCS_BACKUP_CONFIG, else ./config.yaml, else config.yaml next to the package."""
    if env := os.environ.get("GOOGLE_DOCS_BACKUP_CONFIG"):
        return Path(env)
    here = Path.cwd() / "config.yaml"
    return here if here.exists() else REPO_ROOT / "config.yaml"


def _rclone_pids() -> list[str]:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq rclone.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True).stdout
        return [row[1] for row in csv.reader(io.StringIO(out)) if len(row) > 1]
    out = subprocess.run(["pgrep", "-x", "rclone"], capture_output=True, text=True).stdout
    return out.split()


def status(cfg, console: Console) -> int:
    pids = _rclone_pids()
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
    keys = ("---", "summary:", "exit:", "snapshot", "failed", "FAILED")
    ours = [l for l in last if any(k in l for k in keys)]
    console.print("[bold]last run:[/]")
    for l in ours[-30:]:
        console.print(f"  {l}", markup=False, highlight=False)
    if starts and not any("--- backup done ---" in l or "--- backup cancelled ---" in l for l in last):
        console.print("  [yellow](no 'backup done' yet - still running, or it was killed hard)[/]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="google-docs-backup", description="Google Drive backup")
    ap.add_argument("--config", type=Path, default=None,
                    help="config file (default: $GOOGLE_DOCS_BACKUP_CONFIG, ./config.yaml, "
                         "or config.yaml in the repo root)")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd")  # no command = run
    p_run = sub.add_parser("run", help="export, convert, snapshot and upload (default)")
    p_run.add_argument("--remote", help="only back up this remote")
    p_run.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    p_run.add_argument("--no-snapshot", action="store_true", help="skip the tar.gz snapshot this time")
    sub.add_parser("status", help="is rclone running, and how did the last run go")
    sub.add_parser("fetch-tools", help="download rclone + pandoc (Windows)")
    p_auth = sub.add_parser("auth", help="sign in Drive accounts (optionally with your own OAuth client)")
    p_auth.add_argument("remote", nargs="*", help="which remotes (default: all enabled)")
    p_auth.add_argument("--client-json", nargs="?", type=Path, const=Path("auto"), default=None,
                        metavar="FILE_OR_DIR",
                        help="use your own Google OAuth client from its downloaded JSON "
                             "(default: newest client_secret_*.json in ./config, then Downloads)")
    p_svc = sub.add_parser("service", help="scheduled runs: install / uninstall / status / show")
    p_svc.add_argument("action", choices=["install", "uninstall", "status", "show"],
                       help="show = print the task/plist/unit that install would write")
    return ap


def main(argv: list[str] | None = None) -> int:
    # Old Windows consoles / redirected output default to cp1252, which can't
    # draw the progress spinner or file names with non-Latin characters.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    cancel.install()  # Ctrl-C / window close / SIGTERM -> clean cancel; children die with us
    try:
        return _main(argv)
    except KeyboardInterrupt:  # cancelled outside a backup run (startup, auth, ...)
        cancel.stop_children(grace=1)
        print("\ncancelled.", file=sys.stderr)
        return 130


def _main(argv: list[str] | None) -> int:
    a = build_parser().parse_args(argv)
    if a.cmd is None:
        a.cmd, a.remote, a.dry_run, a.no_snapshot = "run", None, False, False

    console = Console()
    try:
        cfg = load(a.config or default_config())
    except (OSError, ValueError, TypeError) as e:
        console.print(f"[red]config error:[/] {e}")
        return 2

    if a.cmd == "run":
        if a.no_snapshot:
            cfg.snapshot.enabled = False
        return runner.run(cfg, a.remote, a.dry_run, console)
    if a.cmd == "fetch-tools":
        return tools.fetch(cfg, console)
    if a.cmd == "auth":
        return auth.start(cfg, a.remote, a.client_json, console)
    if a.cmd == "service":
        return service.main(cfg, a.action, console)
    return status(cfg, console)
