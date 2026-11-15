"""Load config.yaml into typed settings."""
from __future__ import annotations

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
    stage: Path
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
class AuthOpts:
    task_prefix: str = "JunoRcloneAuth-"
    timeout_seconds: int = 90


@dataclass
class Config:
    paths: Paths
    remotes: list[Remote]
    backup_folder: str = "Backups"
    export_formats: list[str] = field(default_factory=lambda: ["docx", "xlsx", "pptx"])
    exclude: list[str] = field(default_factory=lambda: ["/Backups/**"])
    rclone: RcloneOpts = field(default_factory=RcloneOpts)
    markdown: MarkdownOpts = field(default_factory=MarkdownOpts)
    progress: str = "auto"
    tools: ToolsOpts = field(default_factory=ToolsOpts)
    auth: AuthOpts = field(default_factory=AuthOpts)

    @property
    def rclone_exe(self) -> Path:
        return self.paths.bin / "rclone.exe"

    @property
    def pandoc_exe(self) -> Path:
        return self.paths.bin / "pandoc.exe"


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
    paths = Paths(**{k: Path(p[k]) for k in ("bin", "rclone_config", "stage", "log")})
    remotes = [_build(Remote, r, "remotes") for r in raw.pop("remotes")]

    sub = {
        "rclone": RcloneOpts,
        "markdown": MarkdownOpts,
        "tools": ToolsOpts,
        "auth": AuthOpts,
    }
    kwargs = {k: _build(cls, raw.pop(k, None), k) for k, cls in sub.items()}
    cfg = _build(Config, {**raw, **kwargs, "paths": paths, "remotes": remotes}, "top level")

    if cfg.progress not in ("auto", "on", "off"):
        raise ValueError("config.yaml: progress must be auto, on or off")
    return cfg
