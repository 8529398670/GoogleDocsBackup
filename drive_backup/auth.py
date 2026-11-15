"""Add/re-authorize a Drive account (port of start-rclone-auth.ps1).

rclone's config is used by the SYSTEM scheduled task, so the remote is created
from a one-off SYSTEM task too. This prints the local auth URL to open in a
browser. Needs an elevated (admin) prompt.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime, timedelta

from rich.console import Console

from .config import Config

URL_RE = re.compile(r"http://127\.0\.0\.1:\d+/auth\?state=\S+")


def start(cfg: Config, remote: str, console: Console) -> int:
    if os.name != "nt":  # macOS / Linux: rclone's own interactive flow is enough
        cfg.paths.rclone_config.parent.mkdir(parents=True, exist_ok=True)
        exists = subprocess.run([str(cfg.rclone_exe), "--config", str(cfg.paths.rclone_config),
                                 "listremotes"], capture_output=True, text=True).stdout
        args = (["config", "reconnect", f"{remote}:"] if f"{remote}:" in exists.split()
                else ["config", "create", remote, "drive", "scope", "drive"])
        return subprocess.call([str(cfg.rclone_exe), "--config", str(cfg.paths.rclone_config), *args])

    log =cfg.paths.rclone_config.parent / f"auth-{remote}.log"
    task = f"{cfg.auth.task_prefix}{remote}"
    log.unlink(missing_ok=True)

    subprocess.run(["schtasks", "/delete", "/tn", task, "/f"], capture_output=True)
    tr = (f'cmd /c ""{cfg.rclone_exe}" config create {remote} drive scope drive '
          f'--config "{cfg.paths.rclone_config}" > "{log}" 2>&1"')
    start_at = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
    created = subprocess.run(["schtasks", "/create", "/tn", task, "/tr", tr, "/sc", "once",
                              "/st", start_at, "/ru", "SYSTEM", "/f"],
                             capture_output=True, text=True)
    if created.returncode != 0:
        console.print(f"[red]could not create task (run as admin?)[/]\n{created.stderr.strip()}")
        return 1
    subprocess.run(["schtasks", "/run", "/tn", task], capture_output=True)
    console.print("auth task started, waiting for the auth URL...")

    deadline = time.monotonic() + cfg.auth.timeout_seconds
    with console.status("waiting for rclone"):
        while time.monotonic() < deadline:
            time.sleep(2)
            if not log.exists():
                continue
            text = log.read_text(encoding="utf-8", errors="replace")
            if m := URL_RE.search(text):
                console.print(f"[bold green]Open this URL in a browser:[/] {m.group(0)}")
                return 0
            if re.search(r"(?i)error|failed", text):
                console.print("[red]rclone reported an error:[/]")
                console.print(text)
                return 1
    console.print(f"[red]timed out after {cfg.auth.timeout_seconds}s[/] - check {log}")
    return 1
