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


def _detail(stats: dict) -> str:
    done, total = stats.get("bytes", 0), stats.get("totalBytes", 0)
    files = f"{stats.get('transfers', 0)}/{stats.get('totalTransfers', 0)} files"
    checks = stats.get("totalChecks", 0)
    parts = [f"{human_bytes(done)} / {human_bytes(total)}", files]
    if checks:
        parts.append(f"{stats.get('checks', 0)}/{checks} checked")
    if stats.get("speed"):
        parts.append(f"{human_bytes(stats['speed'])}/s")
    if stats.get("eta") is not None:
        parts.append(f"ETA {human_secs(stats['eta'])}")
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
            total = stats.get("totalBytes") or None
            progress.update(task, completed=stats.get("bytes", 0), total=total, detail=_detail(stats))
            continue

        level = str(rec.get("level", "")).upper()
        obj = rec.get("object")
        msg = rec.get("msg", "")
        log(f"{level}: {obj}: {msg}" if obj else f"{level}: {msg}")

    code = proc.wait()
    if last.get("totalBytes"):
        progress.update(task, completed=last.get("bytes", 0), total=last["totalBytes"])
    return RcloneResult(code=code, stats=last)
