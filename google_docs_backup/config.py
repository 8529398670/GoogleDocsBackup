"""Load config.yaml into typed settings."""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Remote:
    name: str
    label: str = ""
    enabled: bool = True


@dataclass
class Paths:
    bin: Path
    rclone_config: Path
    backup_dir: Path
    log: Path


@dataclass
class RcloneOpts:
    log_level: str = "NOTICE"
    transfers: int = 4
    checkers: int = 8
    extra_args: list[str] = field(default_factory=list)


@dataclass
class MarkdownOpts:
    enabled: bool = True
    pandoc_to: str = "markdown"
    wrap: str = "none"
    media_suffix: str = "._media"
    only_if_newer: bool = True
    workers: int = 4
    extra_args: list[str] = field(default_factory=list)


@dataclass
class ToolsOpts:
    rclone_url: str = "https://downloads.rclone.org/rclone-current-windows-amd64.zip"
    pandoc_release_api: str = "https://api.github.com/repos/jgm/pandoc/releases/latest"
    pandoc_asset_glob: str = "pandoc-*-windows-x86_64.zip"


@dataclass
class SnapshotOpts:
    enabled: bool = True
    name_prefix: str = "snapshot-"
    local_dir: Path = Path("snapshots")
    keep_local: int = 5
    keep_drive: int = 5
    compress_level: int = 6


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


@dataclass
class ServiceOpts:
    name: str = "google_docs_backup"
    days: list[str] = field(default_factory=lambda: ["sunday"])
    time: str = "03:00"
    windows_run_as: str = "system"
    linux_scope: str = "user"

    @property
    def hour_minute(self) -> tuple[int, int]:
        h, m = self.time.split(":")
        return int(h), int(m)


@dataclass
class AuthOpts:
    task_prefix: str = "google_docs_backup_auth-"
    timeout_seconds: int = 90


@dataclass
class Config:
    paths: Paths
    remotes: list[Remote]
    upload_to_drive: bool = False
    backup_folder: str = "Backups"
    export_formats: list[str] = field(default_factory=lambda: ["docx", "xlsx", "pptx"])
    exclude: list[str] = field(default_factory=list)
    rclone: RcloneOpts = field(default_factory=RcloneOpts)
    markdown: MarkdownOpts = field(default_factory=MarkdownOpts)
    progress: str = "auto"
    snapshot: SnapshotOpts = field(default_factory=SnapshotOpts)
    service: ServiceOpts = field(default_factory=ServiceOpts)
    tools: ToolsOpts = field(default_factory=ToolsOpts)
    auth: AuthOpts = field(default_factory=AuthOpts)

    source: Path | None = None  # the config.yaml this came from (not a yaml key)
    exes: dict[str, Path] = field(default_factory=dict)  # resolved tool paths

    def bin_target(self, name: str) -> Path:
        """Where fetch-tools installs a tool."""
        return self.paths.bin / (name + EXE)

    @property
    def rclone_exe(self) -> Path:
        return self.exes.get("rclone") or self.bin_target("rclone")

    @property
    def pandoc_exe(self) -> Path:
        return self.exes.get("pandoc") or self.bin_target("pandoc")

    def remember_tool(self, name: str, exe: Path) -> None:
        """Use exe for this tool and write it into config.yaml."""
        self.exes[name] = exe
        if self.source:
            # inside the repo -> save as ./relative so no username/home path lands in git
            base = self.source.resolve().parent
            try:
                value = "./" + exe.resolve().relative_to(base).as_posix()
            except ValueError:
                value = str(exe)
            save_path_value(self.source, f"{name}_exe", value)


EXE = ".exe" if os.name == "nt" else ""
COMMON_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/snap/bin",
               str(Path.home() / ".local" / "bin")]


def find_tool(name: str, bin_dir: Path) -> Path | None:
    """Look for a tool: the bin folder, then PATH, then the usual install dirs."""
    candidates = [bin_dir / (name + EXE)]
    if found := shutil.which(name):
        candidates.append(Path(found))
    candidates += [Path(d) / (name + EXE) for d in COMMON_DIRS]
    return next((c.resolve() for c in candidates if c.is_file()), None)


def save_path_value(cfg_file: Path, key: str, value: str) -> None:
    """Set paths.<key> in config.yaml as text, so comments and layout survive."""
    text = cfg_file.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    quoted = "'" + value.replace("'", "''") + "'"
    start = next((i for i, l in enumerate(lines) if re.match(r"^paths:\s*(#.*)?$", l)), None)
    if start is None:
        raise ValueError("config.yaml has no 'paths:' section")
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() and not lines[i][0].isspace() and not lines[i].startswith("#")),
               len(lines))
    pat = re.compile(rf"^(\s+){re.escape(key)}:[ \t]*(?:'(?:[^']|'')*'|\"[^\"]*\"|[^#\r\n]*?)([ \t]*#[^\r\n]*)?(\r?\n)?$")
    for i in range(start + 1, end):
        if m := pat.match(lines[i]):
            comment = m.group(2) or ""
            lines[i] = f"{m.group(1)}{key}: {quoted}{comment}{m.group(3) or ''}"
            break
    else:
        nl = "\r\n" if text.count("\r\n") else "\n"
        lines.insert(end, f"  {key}: {quoted}  # found automatically{nl}")
    new = "".join(lines)
    try:  # never write a config.yaml that no longer parses or lost the value
        ok = (yaml.safe_load(new) or {}).get("paths", {}).get(key) == value
    except yaml.YAMLError:
        ok = False
    if not ok:
        raise OSError(f"could not safely update paths.{key} in {cfg_file}; set it by hand")
    cfg_file.write_text(new, encoding="utf-8", newline="")


def _build(cls, data: dict | None, where: str):
    data = data or {}
    known = set(cls.__dataclass_fields__)
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"config.yaml: unknown key(s) in {where}: {', '.join(sorted(unknown))}")
    return cls(**data)


def load(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "paths" not in raw or "remotes" not in raw:
        raise ValueError("config.yaml must define 'paths' and 'remotes'")

    p = raw.pop("paths")
    keys = ("bin", "rclone_config", "backup_dir", "log")
    missing = [k for k in keys if k not in p]
    if missing:
        raise ValueError(f"config.yaml: paths is missing {', '.join(missing)}")
    # relative paths are relative to the folder config.yaml lives in
    base = path.resolve().parent
    paths = Paths(**{k: (base / Path(p[k])).resolve() for k in keys})
    unknown = set(p) - set(keys) - {"rclone_exe", "pandoc_exe"}
    if unknown:
        raise ValueError(f"config.yaml: unknown key(s) in paths: {', '.join(sorted(unknown))}")
    remotes = [_build(Remote, r, "remotes") for r in raw.pop("remotes")]

    sub = {
        "rclone": RcloneOpts,
        "markdown": MarkdownOpts,
        "snapshot": SnapshotOpts,
        "service": ServiceOpts,
        "tools": ToolsOpts,
        "auth": AuthOpts,
    }
    kwargs = {k: _build(cls, raw.pop(k, None), k) for k, cls in sub.items()}
    cfg = _build(Config, {**raw, **kwargs, "paths": paths, "remotes": remotes}, "top level")

    if cfg.progress not in ("auto", "on", "off"):
        raise ValueError("config.yaml: progress must be auto, on or off")
    s = cfg.snapshot
    s.local_dir = (base / Path(s.local_dir)).resolve()
    if s.keep_local < 0 or s.keep_drive < 1:
        raise ValueError("config.yaml: snapshot.keep_local must be >= 0 and keep_drive >= 1")
    if not 0 <= s.compress_level <= 9:
        raise ValueError("config.yaml: snapshot.compress_level must be 0..9")
    sv = cfg.service
    sv.days = [d.lower() for d in sv.days]
    if bad := [d for d in sv.days if d not in WEEKDAYS]:
        raise ValueError(f"config.yaml: service.days has unknown day(s): {', '.join(bad)}")
    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", str(sv.time)):
        raise ValueError("config.yaml: service.time must be HH:MM (24h), e.g. \"03:00\"")
    if sv.windows_run_as not in ("system", "user"):
        raise ValueError("config.yaml: service.windows_run_as must be system or user")
    if sv.linux_scope not in ("user", "system"):
        raise ValueError("config.yaml: service.linux_scope must be user or system")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", sv.name):
        raise ValueError("config.yaml: service.name may only use letters, digits, _ . -")
    cfg.source = path

    # rclone / pandoc: use the configured path if it works; otherwise look the
    # tool up and save what was found back into config.yaml.
    for name in ("rclone", "pandoc"):
        given = p.get(f"{name}_exe")
        exe = (base / Path(given)).resolve() if given else None
        if exe and exe.is_file():
            cfg.exes[name] = exe
        elif found := find_tool(name, paths.bin):
            try:
                cfg.remember_tool(name, found)
            except OSError:  # config not writable - still use it this run
                cfg.exes[name] = found
    return cfg
