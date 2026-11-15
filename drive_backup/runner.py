"""The backup itself, per remote: export -> markdown -> (mirror) -> snapshot."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import (BarColumn, Progress, ProgressColumn, SpinnerColumn,
                           TextColumn, TimeElapsedColumn)
from rich.table import Table
from rich.text import Text

from . import convert, rclone, snapshot
from .config import Config, Remote
from .util import Log, RunLock, human_bytes, human_secs


@dataclass
class RemoteSummary:
    name: str
    status: str = "ok"
    exported: int = 0
    exported_bytes: int = 0
    converted: int = 0
    up_to_date: int = 0
    pandoc_failed: int = 0
    uploaded: int = 0
    uploaded_bytes: int = 0
    snapshot: str = "-"
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


class _PercentColumn(ProgressColumn):
    """Percentage, or blank while the total is still unknown."""

    def render(self, task):
        return Text("    " if task.total is None else f"{task.percentage:>3.0f}%")


def make_progress(cfg: Config, console: Console) -> Progress:
    enabled = cfg.progress == "on" or (cfg.progress == "auto" and console.is_terminal)
    return Progress(
        SpinnerColumn(),
        TextColumn("{task.description}", style="bold"),
        BarColumn(bar_width=30),
        _PercentColumn(),
        TimeElapsedColumn(),
        TextColumn("{task.fields[detail]}"),
        console=console,
        disable=not enabled,
        transient=False,
    )


def _backup_remote(cfg: Config, r: Remote, log: Log, progress: Progress,
                   dry_run: bool) -> RemoteSummary:
    s = RemoteSummary(r.name)
    t0 = time.monotonic()
    rstage = cfg.paths.backup_dir / r.name
    rstage.mkdir(parents=True, exist_ok=True)
    dest = f"{r.name}:{cfg.backup_folder}"
    dry = ["--dry-run"] if dry_run else []
    label = f"{r.name}" + (f" ({r.label})" if r.label else "")
    log(f"[{r.name}] --- start ---")

    # 1. export native files from Drive into staging
    t = progress.add_task(f"{label} export", total=None, detail="listing...")
    res = rclone.run(cfg, [
        "copy", f"{r.name}:", str(rstage),
        "--drive-export-formats", ",".join(cfg.export_formats),
        *rclone.export_filters(cfg), *dry,
    ], log, progress, t)
    s.exported, s.exported_bytes = res.transfers, res.bytes
    if res.code != 0:
        progress.update(t, detail=f"[red]failed (exit {res.code})[/]")
        log(f"[{r.name}] export failed, skipping")
        s.status = f"export failed ({res.code})"
        s.seconds = time.monotonic() - t0
        return s

    # 2. every docx also becomes markdown
    if cfg.markdown.enabled:
        t = progress.add_task(f"{label} markdown", total=None, detail="scanning...")
        cr = convert.convert_tree(cfg, rstage, r.name, log, progress, t, dry_run)
        s.converted, s.up_to_date, s.pandoc_failed = cr.converted, cr.skipped, len(cr.failed)
        if cr.failed:
            s.status = "ok (pandoc errors)"

    # 3. optionally mirror the portable copies file-by-file into that account's Drive
    if cfg.upload_to_drive:
        t = progress.add_task(f"{label} mirror", total=None, detail="comparing...")
        res = rclone.run(cfg, ["copy", str(rstage), dest, *dry], log, progress, t)
        s.uploaded, s.uploaded_bytes = res.transfers, res.bytes
        log(f"[{r.name}] upload exit: {res.code}")
        if res.code != 0:
            progress.update(t, detail=f"[red]failed (exit {res.code})[/]")
            s.status = f"upload failed ({res.code})"

    # 4. tar.gz snapshot -> Drive, keep the newest N
    if cfg.snapshot.enabled:
        t = progress.add_task(f"{label} snapshot", total=None, detail="")
        sr = snapshot.run(cfg, r.name, log, progress, t, dry_run)
        s.snapshot = f"{sr.name} ({human_bytes(sr.bytes)})" if sr.bytes else sr.name
        if sr.status != "ok":
            s.status = sr.status

    s.seconds = time.monotonic() - t0
    return s


def _summary_table(cfg: Config, rows: list[RemoteSummary], dry_run: bool) -> Table:
    tbl = Table(title="Backup summary" + (" (dry run)" if dry_run else ""),
                caption=f"backup folder: {cfg.paths.backup_dir}")
    cols = ["remote", "status", "exported", "md converted", "md up to date", "pandoc failed"]
    if cfg.upload_to_drive:
        cols.append("mirrored")
    if cfg.snapshot.enabled:
        cols.append("snapshot")
    cols.append("time")
    for col in cols:
        tbl.add_column(col, justify="left" if col in ("remote", "status") else "right")
    for s in rows:
        color = "green" if s.status == "ok" else ("yellow" if s.status.startswith("ok") else "red")
        cells = [s.name, f"[{color}]{s.status}[/]",
                 f"{s.exported} ({human_bytes(s.exported_bytes)})",
                 str(s.converted), str(s.up_to_date), str(s.pandoc_failed)]
        if cfg.upload_to_drive:
            cells.append(f"{s.uploaded} ({human_bytes(s.uploaded_bytes)})")
        if cfg.snapshot.enabled:
            cells.append(s.snapshot)
        cells.append(human_secs(s.seconds))
        tbl.add_row(*cells)
    return tbl


def _can_write_dir(d) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write-test"
        probe.write_text("x")
        probe.unlink()
        return True
    except OSError:
        return False


def _can_write_file(f) -> bool:
    try:
        with open(f, "r+b"):  # opens for writing without changing anything
            return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _check_access(cfg: Config, console: Console) -> bool:
    dirs = [cfg.paths.log.parent, cfg.paths.backup_dir]
    if cfg.snapshot.enabled:
        dirs.append(cfg.snapshot.local_dir)
    bad = [str(d) for d in dirs if not _can_write_dir(d)]
    bad += [str(f) for f in (cfg.paths.log, cfg.paths.rclone_config) if not _can_write_file(f)]
    if not bad:
        return True
    console.print("[red]no write access to:[/]")
    for b in bad:
        console.print(f"  {b}")
    console.print("\nPoint those paths in config.yaml somewhere you can write, "
                  "or run from an admin / root terminal.")
    return False


def run(cfg: Config, only: str | None, dry_run: bool, console: Console) -> int:
    if not _check_access(cfg, console):
        return 2

    for exe in (cfg.rclone_exe, cfg.pandoc_exe):
        if not exe.exists() and not (exe == cfg.pandoc_exe and not cfg.markdown.enabled):
            hint = ("run: drive-backup fetch-tools" if os.name == "nt" else
                    "install it: brew install rclone pandoc  (macOS)  /  "
                    "sudo apt install rclone pandoc  (Debian/Ubuntu)")
            console.print(f"[red]missing {exe.name}[/] - {hint}")
            return 2

    remotes = [r for r in cfg.remotes if r.enabled and (only is None or r.name == only)]
    if not remotes:
        console.print(f"[red]no enabled remote matches {only!r}[/]")
        return 2

    log = Log(cfg.paths.log)
    try:
        with RunLock(cfg.paths.log.parent / "backup.lock"):
            log("--- backup start ---" + (" (dry run)" if dry_run else ""))
            rows: list[RemoteSummary] = []
            with make_progress(cfg, console) as progress:
                for r in remotes:
                    rows.append(_backup_remote(cfg, r, log, progress, dry_run))
            for s in rows:
                log(f"[{s.name}] summary: {s.status}; exported {s.exported}; md {s.converted} "
                    f"(+{s.up_to_date} up to date, {s.pandoc_failed} failed); "
                    f"mirrored {s.uploaded}; snapshot {s.snapshot}; {human_secs(s.seconds)}")
            log("--- backup done ---")
    except RuntimeError as e:
        console.print(f"[red]{e}[/]")
        return 3

    console.print(_summary_table(cfg, rows, dry_run))
    failed = any(not s.status.startswith("ok") for s in rows)
    pandoc_errors = any(s.pandoc_failed for s in rows)
    return 1 if failed else (4 if pandoc_errors else 0)
