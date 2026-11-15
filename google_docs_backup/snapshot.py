"""tar.gz snapshots of a remote's backup folder: create, upload, keep the newest N."""
from __future__ import annotations

import os
import re
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rich.progress import Progress, TaskID

from . import rclone
from .config import Config
from .util import Log, human_bytes

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def snapshot_name(prefix: str, when: datetime) -> str:
    """snapshot-14NOV2026-23-47.tar.gz (English month, independent of the PC's locale)."""
    return (f"{prefix}{when.day:02d}{MONTHS[when.month - 1]}{when.year}"
            f"-{when.hour:02d}-{when.minute:02d}.tar.gz")


def parse_snapshot_date(prefix: str, name: str) -> datetime | None:
    """Accepts snapshot-14NOV2026-23-47.tar.gz and the older snapshot-14NOV2026.tar.gz."""
    m = re.fullmatch(re.escape(prefix) + r"(\d{2})([A-Z]{3})(\d{4})(?:-(\d{2})-(\d{2}))?\.tar\.gz", name)
    if not m or m.group(2) not in MONTHS:
        return None
    try:
        return datetime(int(m.group(3)), MONTHS.index(m.group(2)) + 1, int(m.group(1)),
                        int(m.group(4) or 0), int(m.group(5) or 0))
    except ValueError:
        return None


def to_prune(prefix: str, names: list[str], keep: int) -> list[str]:
    """Names beyond the newest `keep` snapshots. Files that aren't ours are never touched."""
    dated = [(d, n) for n in names if (d := parse_snapshot_date(prefix, n))]
    dated.sort(reverse=True)
    return [n for _, n in dated[keep:]]


def _long(p: Path) -> str:
    """Windows paths over 260 chars need the \\\\?\\ prefix (deep Drive folders hit this)."""
    s = str(p.resolve())
    return "\\\\?\\" + s if os.name == "nt" and not s.startswith("\\\\?\\") else s


def _files(root: Path):
    base = _long(root)
    for dp, _, fns in os.walk(base):
        for fn in fns:
            full = os.path.join(dp, fn)
            yield full, os.path.relpath(full, base)


@dataclass
class SnapshotResult:
    name: str = ""
    bytes: int = 0
    status: str = "ok"
    pruned_drive: list[str] = field(default_factory=list)
    pruned_local: list[str] = field(default_factory=list)


def make_tarball(src: Path, out: Path, arc_root: str, level: int,
                 progress: Progress, task: TaskID) -> int:
    files = list(_files(src))
    total = sum(os.path.getsize(f) for f, _ in files)
    progress.update(task, total=max(total, 1), completed=0,
                    detail=f"packing {len(files)} files ({human_bytes(total)})")
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    done = 0
    with tarfile.open(_long(part), "w:gz", compresslevel=level) as tar:
        for full, rel in files:
            tar.add(full, arcname=f"{arc_root}/{rel.replace(os.sep, '/')}", recursive=False)
            done += os.path.getsize(full)
            progress.update(task, completed=done)
    os.replace(_long(part), _long(out))
    return out.stat().st_size


def _list_drive(cfg: Config, remote: str) -> tuple[int, list[str]]:
    p = rclone.simple(cfg, ["lsf", f"{remote}:{cfg.backup_folder}", "--files-only",
                            "--include", f"{cfg.snapshot.name_prefix}*.tar.gz"])
    return p.returncode, [l.strip() for l in p.stdout.splitlines() if l.strip()]


def run(cfg: Config, remote: str, log: Log, progress: Progress, task: TaskID,
        dry_run: bool, now: datetime | None = None) -> SnapshotResult:
    s = cfg.snapshot
    res = SnapshotResult(name=snapshot_name(s.name_prefix, now or datetime.now()))
    src = cfg.paths.backup_dir / remote
    local_dir = s.local_dir / remote
    dest = f"{remote}:{cfg.backup_folder}/{res.name}"

    if dry_run:
        progress.update(task, total=1, completed=1,
                        detail=f"would create {res.name} -> {dest}, keep newest {s.keep_drive}")
        return res

    # 1. pack
    out = local_dir / res.name
    try:
        res.bytes = make_tarball(src, out, remote, s.compress_level, progress, task)
    except OSError as e:
        res.status = "snapshot failed"
        log(f"[{remote}] snapshot FAILED to pack: {e}")
        progress.update(task, detail=f"[red]pack failed: {e}[/]")
        return res
    log(f"[{remote}] snapshot packed: {out} ({human_bytes(res.bytes)})")

    # 2. upload
    progress.update(task, total=None, detail=f"uploading {res.name} ({human_bytes(res.bytes)})")
    up = rclone.run(cfg, ["copyto", str(out), dest], log, progress, task)
    log(f"[{remote}] snapshot upload exit: {up.code}")
    if up.code != 0:
        res.status = "snapshot upload failed"
        progress.update(task, detail=f"[red]upload failed (exit {up.code})[/]")
        return res  # don't prune anything if the new one didn't make it

    # 3. keep the newest N in Drive (older ones go to Drive's trash)
    code, names = _list_drive(cfg, remote)
    if code != 0:
        log(f"[{remote}] snapshot: could not list {remote}:{cfg.backup_folder}, not pruning")
    elif res.name not in names:
        log(f"[{remote}] snapshot: {res.name} not found in Drive after upload, not pruning")
    else:
        for old in to_prune(s.name_prefix, names, s.keep_drive):
            d = rclone.simple(cfg, ["deletefile", f"{remote}:{cfg.backup_folder}/{old}"])
            if d.returncode == 0:
                res.pruned_drive.append(old)
                log(f"[{remote}] snapshot pruned from Drive (to trash): {old}")
            else:
                log(f"[{remote}] snapshot prune FAILED in Drive: {old}: {d.stderr.strip()}")

    # 4. keep the newest N locally
    local = [p.name for p in local_dir.glob(f"{s.name_prefix}*.tar.gz")]
    for old in to_prune(s.name_prefix, local, s.keep_local):
        try:
            (local_dir / old).unlink()
            res.pruned_local.append(old)
            log(f"[{remote}] snapshot pruned locally: {old}")
        except OSError as e:
            log(f"[{remote}] snapshot local prune FAILED: {old}: {e}")

    extra = []
    if res.pruned_drive:
        extra.append(f"{len(res.pruned_drive)} old removed from Drive")
    if res.pruned_local:
        extra.append(f"{len(res.pruned_local)} old removed locally")
    progress.update(task, total=1, completed=1,
                    detail=f"{res.name} · {human_bytes(res.bytes)} · uploaded"
                           + (" · " + " · ".join(extra) if extra else ""))
    return res
