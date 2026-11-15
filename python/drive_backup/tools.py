"""Download rclone and pandoc into the bin folder (port of fetch-tools.ps1)."""
from __future__ import annotations

import fnmatch
import json
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from rich.console import Console
from rich.progress import (BarColumn, DownloadColumn, Progress, TextColumn,
                           TimeRemainingColumn, TransferSpeedColumn)

from .config import Config

UA = {"User-Agent": "drive-backup-fetch-tools"}


def _download(url: str, dest: Path, console: Console) -> None:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as out, Progress(
        TextColumn("{task.description}"), BarColumn(), DownloadColumn(),
        TransferSpeedColumn(), TimeRemainingColumn(), console=console,
    ) as prog:
        total = int(resp.headers.get("Content-Length") or 0) or None
        task = prog.add_task(f"download {Path(url).name}", total=total)
        while chunk := resp.read(1 << 16):
            out.write(chunk)
            prog.advance(task, len(chunk))


def _install_from_zip(url: str, exe_name: str, bin_dir: Path, console: Console) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        z = Path(tmp) / "tool.zip"
        _download(url, z, console)
        with zipfile.ZipFile(z) as zf:
            member = next((m for m in zf.namelist() if Path(m).name.lower() == exe_name), None)
            if not member:
                raise RuntimeError(f"{exe_name} not found in {url}")
            with zf.open(member) as src, open(bin_dir / exe_name, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _version(exe: Path) -> str:
    try:
        out = subprocess.run([str(exe), "version" if exe.stem == "rclone" else "--version"],
                             capture_output=True, text=True, timeout=30).stdout
        return out.splitlines()[0] if out else "?"
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def fetch(cfg: Config, console: Console) -> int:
    bin_dir = cfg.paths.bin
    bin_dir.mkdir(parents=True, exist_ok=True)
    cfg.paths.rclone_config.parent.mkdir(parents=True, exist_ok=True)

    if cfg.rclone_exe.exists():
        console.print("rclone already present")
    else:
        _install_from_zip(cfg.tools.rclone_url, "rclone.exe", bin_dir, console)
        console.print("[green]rclone ok[/]")

    if cfg.pandoc_exe.exists():
        console.print("pandoc already present")
    else:
        console.print("resolving pandoc latest release...")
        req = urllib.request.Request(cfg.tools.pandoc_release_api, headers=UA)
        with urllib.request.urlopen(req) as resp:
            rel = json.load(resp)
        asset = next((a for a in rel.get("assets", [])
                      if fnmatch.fnmatch(a["name"], cfg.tools.pandoc_asset_glob)), None)
        if not asset:
            console.print("[red]pandoc windows asset not found[/]")
            return 1
        _install_from_zip(asset["browser_download_url"], "pandoc.exe", bin_dir, console)
        console.print("[green]pandoc ok[/]")

    console.print(_version(cfg.rclone_exe))
    console.print(_version(cfg.pandoc_exe))
    return 0
