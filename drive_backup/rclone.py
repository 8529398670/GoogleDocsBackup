"""Run rclone and turn its JSON stats into a live progress bar."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

from rich.progress import Progress, TaskID

from .config import Config
from .util import Log, human_bytes, human_secs


@dataclass
class RcloneResult:
    code: int
    stats: dict = field(default_factory=dict)

    @property
    def transfers(self) -> int:
        return int(self.stats.get("transfers", 0))

    @property
    def bytes(self) -> int:
        return int(self.stats.get("bytes", 0))

    @property
    def errors(self) -> int:
        return int(self.stats.get("errors", 0))


def base_args(cfg: Config) -> list[str]:
    o = cfg.rclone
    return [
        str(cfg.rclone_exe),
        "--config", str(cfg.paths.rclone_config),
        "--log-level", o.log_level,
        "--use-json-log",
        "--stats", "1s",
        "--stats-log-level", "NOTICE",
        "--transfers", str(o.transfers),
        "--checkers", str(o.checkers),
        *o.extra_args,
    ]


def simple(cfg: Config, args: list[str]) -> subprocess.CompletedProcess:
    """A plain rclone call (lsf, deletefile, ...) with captured text output."""
    return subprocess.run([str(cfg.rclone_exe), "--config", str(cfg.paths.rclone_config), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def export_filters(cfg: Config) -> list[str]:
    """Ordered filter rules: excludes FIRST, then the wanted types, then drop everything else.

    The old script mixed --include and --exclude; rclone matched '*.docx' before
    'Backups/**', so the Backups folder was re-exported into itself every week.
    """
    rules: list[str] = []
    for pat in cfg.exclude:
        rules += ["--filter", f"- {pat}"]
    for ext in cfg.export_formats:
        rules += ["--filter", f"+ *.{ext}"]
    rules += ["--filter", "- **"]
    return rules


def _detail(stats: dict, finished: bool = False) -> str:
    # rclone discovers files while it lists, so its totals keep growing until the
    # listing is done - show plain running counts instead of "x of y".
    parts = []
    if stats.get("listed"):
        parts.append(f"{stats['listed']} listed")
    parts.append(f"{stats.get('checks', 0)} unchanged")
    parts.append(f"{stats.get('transfers', 0)} copied ({human_bytes(stats.get('bytes', 0))})")
    in_flight = stats.get("transferring") or []
    if in_flight and not finished:
        name = str(in_flight[0].get("name", ""))
        parts.append(f"now: {name[-50:]}")
    if stats.get("speed") and not finished:
        parts.append(f"{human_bytes(stats['speed'])}/s")
    if stats.get("errors"):
        parts.append(f"[red]{stats['errors']} errors[/]")
    return " · ".join(parts)


def run(cfg: Config, args: list[str], log: Log, progress: Progress, task: TaskID) -> RcloneResult:
    cmd = base_args(cfg) + args
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    last: dict = {}
    assert proc.stderr is not None
    for line in proc.stderr:
        line = line.rstrip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            log(f"rclone: {line}")
            continue

        stats = rec.get("stats")
        if stats:
            last = stats
            # total stays None (pulsing bar) until rclone exits
            progress.update(task, detail=_detail(stats))
            continue

        level = str(rec.get("level", "")).upper()
        obj = rec.get("object")
        msg = rec.get("msg", "")
        log(f"{level}: {obj}: {msg}" if obj else f"{level}: {msg}")

    code = proc.wait()
    progress.update(task, total=1, completed=1, detail=_detail(last, finished=True))
    return RcloneResult(code=code, stats=last)
