"""Add or re-authorize Drive accounts, optionally switching them to your own
Google OAuth client (so they use your own API quota, not rclone's shared one).

    google-docs-backup auth                         # re-sign-in every enabled account
    google-docs-backup auth gdrive2                 # just one
    google-docs-backup auth --client-json           # newest client_secret_*.json in ./config, then Downloads
    google-docs-backup auth --client-json FILE      # a specific file

The client ID/secret go only into rclone.conf (private/, git-ignored) and are
never printed.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from rich.console import Console

from .config import Config


def find_client_json(where: Path) -> Path | None:
    """A file, or the newest client_secret_*.json in a folder (default: Downloads)."""
    where = where.expanduser()
    if where.is_file():
        return where
    found = sorted(where.glob("client_secret_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0] if found else None


def _read_client(path: Path) -> tuple[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    block = data.get("installed") or data.get("web") or {}
    cid, secret = block.get("client_id"), block.get("client_secret")
    if not cid or not secret:
        raise ValueError(f"{path.name} has no installed.client_id / client_secret "
                         "(download the JSON of a 'Desktop app' OAuth client)")
    return cid, secret


def start(cfg: Config, remotes: list[str], client_json: Path | None, console: Console) -> int:
    rc = [str(cfg.rclone_exe), "--config", str(cfg.paths.rclone_config)]
    cfg.paths.rclone_config.parent.mkdir(parents=True, exist_ok=True)
    existing = subprocess.run(rc + ["listremotes"], capture_output=True, text=True).stdout.split()
    names = remotes or [r.name for r in cfg.remotes if r.enabled]

    client: list[str] = []
    if client_json is not None:
        places = ([cfg.root / "config", Path("~/Downloads")]
                  if str(client_json) == "auto" else [client_json])
        path = next((p for p in map(find_client_json, places) if p), None)
        if not path:
            console.print(f"[red]no client_secret_*.json found in {', '.join(map(str, places))}[/]")
            return 2
        try:
            cid, secret = _read_client(path)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            console.print(f"[red]{e}[/]")
            return 2
        client = ["client_id", cid, "client_secret", secret]
        console.print(f"using your OAuth client [bold]{cid.split('-')[0]}-...[/] from {path.name}")

    failed = []
    for name in names:
        console.rule(f"[bold]{name}")
        if f"{name}:" in existing:
            if client:  # switch this remote to your own client; secret stays out of the output
                p = subprocess.run(rc + ["config", "update", name, *client, "--non-interactive"],
                                   capture_output=True, text=True)
                if p.returncode != 0:
                    console.print(f"[red]could not update {name}[/]")
                    failed.append(name)
                    continue
                console.print(f"{name}: now uses your own OAuth client")
            console.print(f"Sign in to Google for [bold]{name}[/]. A browser opens: pick the account "
                          f"that {name} backs up, and allow access. (Answer rclone's questions with Enter.)")
            code = subprocess.call(rc + ["config", "reconnect", f"{name}:"])
        else:
            console.print(f"{name} doesn't exist yet - creating it. A browser opens: pick its account.")
            code = subprocess.call(rc + ["config", "create", name, "drive", "scope", "drive", *client])
        if code != 0:
            failed.append(name)

    console.rule()
    if failed:
        console.print(f"[red]not finished:[/] {', '.join(failed)} - run `google-docs-backup auth "
                      f"{' '.join(failed)}` again")
        return 1
    console.print(f"[green]done:[/] {', '.join(names)} signed in")
    return 0
