"""The backup itself, per remote: export (sync) -> markdown -> (mirror) -> snapshot."""
from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import (BarColumn, Progress, ProgressColumn, SpinnerColumn,
                           TextColumn, TimeElapsedColumn)
from rich.table import Table
from rich.text import Text

from . import cancel, convert, rclone, snapshot
from .config import Config, Remote
from .util import Log, RunLock, human_bytes, human_secs


@dataclass
class RemoteSummary:
    name: str
    status: str = "ok"
    exported: int = 0
    exported_bytes: int = 0
    removed: int = 0          # files gone from Drive, removed locally (incl. orphan .md)
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


def steps_for(cfg: Config) -> list[str]:
    """The steps each account goes through, in order."""
    steps = ["export"]
    if cfg.markdown.enabled:
        steps.append("markdown")
    if cfg.upload_to_drive:
        steps.append("mirror")
    if cfg.snapshot.enabled:
        steps.append("snapshot")
    return steps


class Overall:
    """The 'overall' bar: steps done across every account + what each one is doing."""

    def __init__(self, progress: Progress, remotes: list[Remote], steps: list[str]):
        self.progress, self.steps = progress, steps
        self.names = [r.name for r in remotes]
        self.done = {n: 0 for n in self.names}
        self.now: dict[str, str] = {}
        self.failed: set[str] = set()
        self._lock = threading.Lock()
        self.task = progress.add_task("overall", total=len(self.names) * len(steps), detail="starting...")

    def _refresh(self) -> None:
        finished = sum(1 for n in self.names if self.done[n] >= len(self.steps))
        parts = [f"{finished}/{len(self.names)} accounts done"]
        parts += [f"{n}: {self.now[n]}" for n in self.names if n in self.now]
        if self.failed:
            parts.append(f"[red]{len(self.failed)} failed[/]")
        self.progress.update(self.task, completed=sum(self.done.values()), detail=" · ".join(parts))

    def start(self, name: str, step: str) -> None:
        with self._lock:
            self.now[name] = step
            self._refresh()

    def step_done(self, name: str) -> None:
        with self._lock:
            self.done[name] = min(self.done[name] + 1, len(self.steps))
            self._refresh()

    def finish(self, name: str, ok: bool) -> None:
        """Account finished (or gave up): count any skipped steps so the bar reaches 100%."""
        with self._lock:
            self.done[name] = len(self.steps)
            self.now.pop(name, None)
            if not ok:
                self.failed.add(name)
            self._refresh()


def _backup_remote(cfg: Config, r: Remote, log: Log, progress: Progress,
                   dry_run: bool, ov: Overall) -> RemoteSummary:
    s = RemoteSummary(r.name)
    t0 = time.monotonic()
    rstage = cfg.paths.backup_dir / r.name
    rstage.mkdir(parents=True, exist_ok=True)
    dest = f"{r.name}:{cfg.backup_folder}"
    dry = ["--dry-run"] if dry_run else []
    label = f"{r.name}" + (f" ({r.label})" if r.label else "")
    log(f"[{r.name}] --- start ---")
    if not dry_run:  # half-written files from a run that was killed hard
        convert.remove_partials(rstage, r.name, log)

    # 1. export native files from Drive into staging
    ov.start(r.name, "export")
    t = progress.add_task(f"{label} export", total=None, detail="listing...")
    # sync = mirror Drive (moves/deletes follow). Our own .md/._media files are
    # excluded by the filters, and rclone never deletes excluded files.
    res = rclone.run(cfg, [
        "sync" if cfg.mirror_deletes else "copy", f"{r.name}:", str(rstage),
        "--drive-export-formats", ",".join(cfg.export_formats),
        *rclone.export_filters(cfg), *dry,
    ], log, progress, t)
    s.exported, s.exported_bytes, s.removed = res.transfers, res.bytes, res.deletes
    if res.deletes:
        log(f"[{r.name}] {res.deletes} file(s) no longer on Drive, removed locally")
    if res.code != 0:
        progress.update(t, detail=f"[red]failed (exit {res.code})[/]")
        log(f"[{r.name}] export failed, skipping")
        s.status = f"export failed ({res.code})"
        s.seconds = time.monotonic() - t0
        return s
    ov.step_done(r.name)

    # 2. every docx also becomes markdown
    if cfg.markdown.enabled:
        ov.start(r.name, "markdown")
        t = progress.add_task(f"{label} markdown", total=None, detail="scanning...")
        if cfg.mirror_deletes:  # .md / ._media of docs that moved or were deleted
            orphans = convert.prune_orphans(cfg, rstage, r.name, log, dry_run)
            s.removed += orphans
            if orphans:
                log(f"[{r.name}] {orphans} orphan md/media {'would be ' if dry_run else ''}removed")
        cr = convert.convert_tree(cfg, rstage, r.name, log, progress, t, dry_run)
        s.converted, s.up_to_date, s.pandoc_failed = cr.converted, cr.skipped, len(cr.failed)
        if cr.failed:
            s.status = "ok (pandoc errors)"
        ov.step_done(r.name)

    # 3. optionally mirror the portable copies file-by-file into that account's Drive
    if cfg.upload_to_drive:
        ov.start(r.name, "mirror")
        t = progress.add_task(f"{label} mirror", total=None, detail="comparing...")
        res = rclone.run(cfg, ["copy", str(rstage), dest, *dry], log, progress, t)
        s.uploaded, s.uploaded_bytes = res.transfers, res.bytes
        log(f"[{r.name}] upload exit: {res.code}")
        if res.code != 0:
            progress.update(t, detail=f"[red]failed (exit {res.code})[/]")
            s.status = f"upload failed ({res.code})"
        ov.step_done(r.name)

    # 4. tar snapshot -> Drive, keep the newest N
    if cfg.snapshot.enabled:
        ov.start(r.name, "snapshot")
        t = progress.add_task(f"{label} snapshot", total=None, detail="")
        sr = snapshot.run(cfg, r.name, log, progress, t, dry_run)
        s.snapshot = f"{sr.name} ({human_bytes(sr.bytes)})" if sr.bytes else sr.name
        if sr.status != "ok":
            s.status = sr.status
        ov.step_done(r.name)

    s.seconds = time.monotonic() - t0
    return s


def _summary_table(cfg: Config, rows: list[RemoteSummary], dry_run: bool) -> Table:
    tbl = Table(title="Backup summary" + (" (dry run)" if dry_run else ""),
                caption=f"backup folder: {cfg.paths.backup_dir}")
    cols = ["remote", "status", "exported"]
    if cfg.mirror_deletes:
        cols.append("removed")
    cols += ["md converted", "md up to date", "pandoc failed"]
    if cfg.upload_to_drive:
        cols.append("mirrored")
    if cfg.snapshot.enabled:
        cols.append("snapshot")
    cols.append("time")
    for col in cols:
        tbl.add_column(col, justify="left" if col in ("remote", "status") else "right")
    for s in rows:
        color = ("green" if s.status == "ok" else
                 "yellow" if s.status.startswith("ok") or s.status == "cancelled" else "red")
        cells = [s.name, f"[{color}]{s.status}[/]",
                 f"{s.exported} ({human_bytes(s.exported_bytes)})"]
        if cfg.mirror_deletes:
            cells.append(str(s.removed))
        cells += [str(s.converted), str(s.up_to_date), str(s.pandoc_failed)]
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
            hint = ("run: google-docs-backup fetch-tools" if os.name == "nt" else
                    "install it: brew install rclone pandoc  (macOS)  /  "
                    "sudo apt install rclone pandoc  (Debian/Ubuntu)")
            console.print(f"[red]missing {exe.name}[/] - {hint}")
            return 2

    remotes = [r for r in cfg.remotes if r.enabled and (only is None or r.name == only)]
    if not remotes:
        console.print(f"[red]no enabled remote matches {only!r}[/]")
        return 2

    log = Log(cfg.paths.log)
    cancelled = False
    try:
        with RunLock(cfg.paths.log.parent / "backup.lock"):
            log("--- backup start ---" + (" (dry run)" if dry_run else ""))
            workers = len(remotes) if cfg.parallel_remotes == 0 else min(cfg.parallel_remotes, len(remotes))
            if workers > 1:
                log(f"backing up {len(remotes)} accounts, {workers} at a time")
            with make_progress(cfg, console) as progress:
                ov = Overall(progress, remotes, steps_for(cfg))  # first task = top line

                def one(r: Remote) -> RemoteSummary:
                    try:
                        s = _backup_remote(cfg, r, log, progress, dry_run, ov)
                    except cancel.Cancelled:
                        log(f"[{r.name}] cancelled")
                        s = RemoteSummary(r.name, status="cancelled")
                    except Exception as e:  # one account crashing must not stop the others
                        log(f"[{r.name}] CRASHED: {type(e).__name__}: {e}")
                        s = RemoteSummary(r.name, status=f"crashed ({type(e).__name__})")
                    ov.finish(r.name, ok=s.status.startswith("ok"))
                    return s

                pool = ThreadPoolExecutor(max_workers=workers)
                futs = [pool.submit(one, r) for r in remotes]
                try:
                    # wait in short slices so Ctrl-C / window close is handled at once
                    while not all(f.done() for f in futs):
                        wait(futs, timeout=0.25)
                except KeyboardInterrupt:
                    cancelled = True
                    cancel.CANCEL.set()
                    progress.update(ov.task, detail="[yellow]cancelling: stopping rclone / pandoc...[/]")
                    n = cancel.stop_children()
                    log(f"cancel requested: stopped {n} running rclone/pandoc process(es)")
                    while True:  # workers unwind quickly now; extra Ctrl-Cs just hurry them
                        try:
                            wait(futs)
                            break
                        except KeyboardInterrupt:
                            cancel.stop_children(grace=0)
                finally:
                    pool.shutdown(wait=True, cancel_futures=True)
                if cancelled and not dry_run:  # safety net for anything a child left mid-write
                    for r in remotes:
                        convert.remove_partials(cfg.paths.backup_dir / r.name, r.name, log)
                rows = [f.result() if not f.cancelled() else RemoteSummary(r.name, status="cancelled")
                        for f, r in zip(futs, remotes)]
                ok = sum(1 for s in rows if s.status.startswith("ok"))
                if cancelled:
                    progress.update(ov.task, detail=f"[yellow]cancelled[/] · {ok}/{len(rows)} accounts finished")
                else:
                    progress.update(ov.task, detail=f"{ok}/{len(rows)} accounts ok"
                                    + (f" · [red]{len(rows) - ok} failed[/]" if ok < len(rows) else ""))
            for s in rows:
                log(f"[{s.name}] summary: {s.status}; exported {s.exported}; removed {s.removed}; md {s.converted} "
                    f"(+{s.up_to_date} up to date, {s.pandoc_failed} failed); "
                    f"mirrored {s.uploaded}; snapshot {s.snapshot}; {human_secs(s.seconds)}")
            log("--- backup cancelled ---" if cancelled else "--- backup done ---")
    except RuntimeError as e:
        console.print(f"[red]{e}[/]")
        return 3

    console.print(_summary_table(cfg, rows, dry_run))
    if cancelled:
        console.print("[yellow]Backup cancelled.[/] Accounts marked ok finished completely; the others "
                      "stopped where they were and catch up on the next run. Nothing half-written "
                      "was left behind.")
        return 130
    failed = any(not s.status.startswith("ok") for s in rows)
    pandoc_errors = any(s.pandoc_failed for s in rows)
    return 1 if failed else (4 if pandoc_errors else 0)
