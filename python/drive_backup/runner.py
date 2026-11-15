"""The backup itself: export -> convert -> upload, per remote."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import (BarColumn, Progress, SpinnerColumn, TextColumn,
                           TimeElapsedColumn)
from rich.table import Table

from . import convert, rclone
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
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


def make_progress(cfg: Config, console: Console) -> Progress:
    enabled = cfg.progress == "on" or (cfg.progress == "auto" and console.is_terminal)
    return Progress(
        SpinnerColumn(),
        TextColumn("{task.description}", style="bold"),
        BarColumn(bar_width=30),
        TextColumn("{task.percentage:>3.0f}%"),
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
    progress.update(t, detail=f"{res.transfers} files · {human_bytes(res.bytes)}")

    # 2. every docx also becomes markdown
    if cfg.markdown.enabled:
        t = progress.add_task(f"{label} markdown", total=None, detail="scanning...")
        cr = convert.convert_tree(cfg, rstage, r.name, log, progress, t, dry_run)
        s.converted, s.up_to_date, s.pandoc_failed = cr.converted, cr.skipped, len(cr.failed)
        if cr.failed:
            s.status = "ok (pandoc errors)"

    # 3. optionally upload the portable copies back into that account's Drive
    if not cfg.upload_to_drive:
        s.seconds = time.monotonic() - t0
        return s
    t = progress.add_task(f"{label} upload", total=None, detail="comparing...")
    res = rclone.run(cfg, ["copy", str(rstage), dest, *dry], log, progress, t)
    s.uploaded, s.uploaded_bytes = res.transfers, res.bytes
    log(f"[{r.name}] upload exit: {res.code}")
    if res.code != 0:
        progress.update(t, detail=f"[red]failed (exit {res.code})[/]")
        s.status = f"upload failed ({res.code})"
    else:
        progress.update(t, detail=f"{res.transfers} files · {human_bytes(res.bytes)}")

    s.seconds = time.monotonic() - t0
    return s


def _summary_table(cfg: Config, rows: list[RemoteSummary], dry_run: bool) -> Table:
    tbl = Table(title="Backup summary" + (" (dry run)" if dry_run else ""),
                caption=f"backup folder: {cfg.paths.backup_dir}")
    cols = ["remote", "status", "exported", "md converted", "md up to date", "pandoc failed"]
    if cfg.upload_to_drive:
        cols.append("uploaded")
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
    bad = [str(d) for d in (cfg.paths.log.parent, cfg.paths.backup_dir) if not _can_write_dir(d)]
    bad += [str(f) for f in (cfg.paths.log, cfg.paths.rclone_config) if not _can_write_file(f)]
    if not bad:
        return True
    console.print("[red]no write access to:[/]")
    for b in bad:
        console.print(f"  {b}")
    console.print(
        "\nThe backup folders are writable only by SYSTEM / Administrators.\n"
        "Either run this from a terminal opened with [bold]Run as administrator[/], or start\n"
        "the scheduled task (runs as SYSTEM, no progress bars):\n"
        "  [bold]schtasks /run /tn JunoDriveBackup[/]   then   python python/backup.py status"
    )
    return False


def run(cfg: Config, only: str | None, dry_run: bool, console: Console) -> int:
    if not _check_access(cfg, console):
        return 2

    for exe in (cfg.rclone_exe, cfg.pandoc_exe):
        if not exe.exists() and not (exe == cfg.pandoc_exe and not cfg.markdown.enabled):
            console.print(f"[red]missing {exe}[/] - run: python backup.py fetch-tools")
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
                    f"uploaded {s.uploaded}; {human_secs(s.seconds)}")
            log("--- backup done ---")
    except RuntimeError as e:
        console.print(f"[red]{e}[/]")
        return 3

    console.print(_summary_table(cfg, rows, dry_run))
    failed = any(not s.status.startswith("ok") for s in rows)
    pandoc_errors = any(s.pandoc_failed for s in rows)
    return 1 if failed else (4 if pandoc_errors else 0)
