"""docx -> markdown with pandoc, images as ordinary local files (never base64)."""
from __future__ import annotations

import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from rich.progress import Progress, TaskID

from .config import Config
from .util import Log


@dataclass
class ConvertResult:
    converted: int = 0
    skipped: int = 0
    failed: list[Path] = field(default_factory=list)


def _long(p: Path) -> str:
    s = str(p.resolve())
    return "\\\\?\\" + s if os.name == "nt" and not s.startswith("\\\\?\\") else s


def prune_orphans(cfg: Config, root: Path, tag: str, log: Log, dry_run: bool) -> int:
    """Remove .md files and ._media folders whose .docx is gone (moved/renamed/deleted
    on Drive), so the markdown follows the docs. Returns how many were removed."""
    suffix = cfg.markdown.media_suffix
    removed = 0
    for dp, dns, fns in os.walk(_long(root)):
        names = set(fns)
        for fn in fns:
            if fn.lower().endswith(".md") and fn[:-3] + ".docx" not in names:
                removed += 1
                if not dry_run:
                    os.remove(os.path.join(dp, fn))
                log(f"[{tag}] orphan md {'would be ' if dry_run else ''}removed: "
                    f"{os.path.relpath(os.path.join(dp, fn), _long(root))}")
        for dn in list(dns):
            if dn.endswith(suffix) and dn[:-len(suffix)] + ".docx" not in names:
                dns.remove(dn)  # don't walk into it
                removed += 1
                if not dry_run:
                    shutil.rmtree(os.path.join(dp, dn), ignore_errors=True)
                log(f"[{tag}] orphan media {'would be ' if dry_run else ''}removed: "
                    f"{os.path.relpath(os.path.join(dp, dn), _long(root))}")
    return removed


def _needs(docx: Path, md: Path, only_if_newer: bool) -> bool:
    if not md.exists():
        return True
    return (not only_if_newer) or docx.stat().st_mtime > md.stat().st_mtime


def _convert_one(cfg: Config, docx: Path) -> tuple[Path, bool, str]:
    m = cfg.markdown
    media_name = docx.stem + m.media_suffix
    media = docx.parent / media_name
    if media.exists():
        shutil.rmtree(media, ignore_errors=True)

    # Run inside the doc's folder with a relative media dir, so image links in the
    # .md are relative and still work after the tree is uploaded or downloaded.
    cmd = [
        str(cfg.pandoc_exe),
        "-f", "docx",
        "-t", m.pandoc_to,
        f"--wrap={m.wrap}",
        f"--extract-media={media_name}",
        *m.extra_args,
        docx.name,
        "-o", docx.with_suffix(".md").name,
    ]
    proc = subprocess.run(cmd, cwd=docx.parent, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode == 0 and media.is_dir() and not any(media.iterdir()):
        media.rmdir()
    return docx, proc.returncode == 0, proc.stderr.strip()


def convert_tree(cfg: Config, root: Path, tag: str, log: Log, progress: Progress,
                 task: TaskID, dry_run: bool) -> ConvertResult:
    res = ConvertResult()
    docs = sorted(root.rglob("*.docx"))
    todo = [d for d in docs if _needs(d, d.with_suffix(".md"), cfg.markdown.only_if_newer)]
    res.skipped = len(docs) - len(todo)
    progress.update(task, total=max(len(todo), 1), completed=0,
                    detail=f"0/{len(todo)} docs ({res.skipped} up to date)")

    if dry_run or not todo:
        progress.update(task, completed=max(len(todo), 1),
                        detail=f"{len(todo)} would convert ({res.skipped} up to date)" if dry_run
                        else f"nothing to convert ({res.skipped} up to date)")
        res.converted = 0
        return res

    with ThreadPoolExecutor(max_workers=max(1, cfg.markdown.workers)) as pool:
        futures = [pool.submit(_convert_one, cfg, d) for d in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            docx, ok, err = fut.result()
            if ok:
                res.converted += 1
                log(f"[{tag}] md: {docx.name}")
            else:
                res.failed.append(docx)
                log(f"[{tag}] PANDOC FAILED: {docx}" + (f" ({err.splitlines()[-1]})" if err else ""))
            progress.update(task, completed=i,
                            detail=f"{i}/{len(todo)} docs · {len(res.failed)} failed")
    return res
