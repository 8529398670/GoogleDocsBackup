"""Install / remove / inspect the scheduled backup with the OS's own scheduler.

Windows : Task Scheduler (task XML, so the working folder is set properly)
macOS   : launchd LaunchAgent  ~/Library/LaunchAgents/<label>.plist
Linux   : systemd timer        ~/.config/systemd/user/  or  /etc/systemd/system/

The scheduled command is always:
    <this python> -m google_docs_backup --config <config.yaml> run
run from the folder config.yaml lives in.
"""
from __future__ import annotations

import ctypes
import getpass
import os
import plistlib
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from rich.console import Console

from .config import WEEKDAYS, Config

# ---------------------------------------------------------------- helpers


def _platform() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _python() -> Path:
    """The interpreter running us now - normally the repo's .venv."""
    exe = Path(sys.executable)
    if os.name == "nt" and exe.name.lower() == "pythonw.exe":
        exe = exe.with_name("python.exe")
    return exe.resolve()


def _command(cfg: Config) -> list[str]:
    return [str(_python()), "-m", "google_docs_backup", "--config", str(cfg.source.resolve()), "run"]


def _workdir(cfg: Config) -> Path:
    return cfg.source.resolve().parent


def _days(cfg: Config) -> list[str]:
    return cfg.service.days or list(WEEKDAYS)


def describe(cfg: Config) -> str:
    sv = cfg.service
    when = "every day" if not sv.days or len(sv.days) == 7 else ", ".join(d.capitalize() for d in sv.days)
    return f"{when} at {sv.time}"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", **kw)


# ---------------------------------------------------------------- windows


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def windows_task_xml(cfg: Config) -> str:
    sv = cfg.service
    h, m = sv.hour_minute
    start = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).replace(hour=h, minute=m)
    cmd = _command(cfg)
    args = " ".join(f'"{a}"' if " " in a else a for a in cmd[1:])
    if sv.windows_run_as == "system":
        principal = "<UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel>"
    else:
        principal = (f"<UserId>{escape(os.environ.get('USERDOMAIN', '') + chr(92) + getpass.getuser())}</UserId>"
                     "<LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel>")
    if sv.days and len(sv.days) < 7:
        days = "".join(f"<{d.capitalize()} />" for d in sv.days)
        schedule = f"<ScheduleByWeek><DaysOfWeek>{days}</DaysOfWeek><WeeksInterval>1</WeeksInterval></ScheduleByWeek>"
    else:
        schedule = "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>google-docs-backup: Google Drive backup ({escape(describe(cfg))})</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start:%Y-%m-%dT%H:%M:%S}</StartBoundary>
      <Enabled>true</Enabled>
      {schedule}
    </CalendarTrigger>
  </Triggers>
  <Principals><Principal id="Author">{principal}</Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT72H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(cmd[0])}</Command>
      <Arguments>{escape(args)}</Arguments>
      <WorkingDirectory>{escape(str(_workdir(cfg)))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _in_venv() -> bool:
    return sys.prefix != sys.base_prefix


def _win_install(cfg: Config, console: Console) -> int:
    if cfg.service.windows_run_as == "system" and not _in_venv():
        console.print("[red]Run this from the repo's .venv[/] (install.bat does that). SYSTEM can't "
                      "see packages installed for your user, so the task would fail.")
        return 2
    if cfg.service.windows_run_as == "system" and not _is_admin():
        console.print("[red]Installing as SYSTEM needs an admin terminal.[/]\n"
                      "Run install.bat (it asks for admin), or set service.windows_run_as: user "
                      "in config.yaml (then it only runs while you're logged in).")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        xml = Path(tmp) / "task.xml"
        xml.write_text(windows_task_xml(cfg), encoding="utf-16")
        p = _run(["schtasks", "/create", "/tn", cfg.service.name, "/xml", str(xml), "/f"])
    if p.returncode != 0:
        console.print(f"[red]schtasks failed:[/] {(p.stderr or p.stdout).strip()}")
        return 1
    console.print(f"[green]installed[/] Task Scheduler task [bold]{cfg.service.name}[/] "
                  f"({describe(cfg)}, as {cfg.service.windows_run_as})")
    return 0


def _win_uninstall(cfg: Config, console: Console) -> int:
    p = _run(["schtasks", "/delete", "/tn", cfg.service.name, "/f"])
    if p.returncode != 0:
        console.print(f"[yellow]{(p.stderr or p.stdout).strip()}[/]")
        return 1
    console.print(f"[green]removed[/] task {cfg.service.name}")
    return 0


def _win_status(cfg: Config, console: Console) -> int:
    p = _run(["schtasks", "/query", "/tn", cfg.service.name, "/fo", "LIST", "/v"])
    if p.returncode != 0:
        console.print(f"task {cfg.service.name}: [yellow]not installed[/] "
                      f"({(p.stderr or p.stdout).strip()})")
        return 1
    keep = ("TaskName", "Status", "Next Run Time", "Last Run Time", "Last Result",
            "Task To Run", "Run As User", "Days", "Start Time")
    for line in p.stdout.splitlines():
        if line.split(":", 1)[0].strip() in keep:
            console.print("  " + line.strip(), markup=False, highlight=False)
    return 0


# ---------------------------------------------------------------- macOS


def _mac_label(cfg: Config) -> str:
    return f"local.{cfg.service.name.lower()}"


def _mac_plist_path(cfg: Config) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_mac_label(cfg)}.plist"


def macos_plist(cfg: Config) -> bytes:
    h, m = cfg.service.hour_minute
    # launchd weekdays: 0 = Sunday ... 6 = Saturday
    lday = {d: (i + 1) % 7 for i, d in enumerate(WEEKDAYS)}
    if cfg.service.days and len(cfg.service.days) < 7:
        cal = [{"Weekday": lday[d], "Hour": h, "Minute": m} for d in cfg.service.days]
    else:
        cal = [{"Hour": h, "Minute": m}]
    logs = cfg.paths.log.parent
    return plistlib.dumps({
        "Label": _mac_label(cfg),
        "ProgramArguments": _command(cfg),
        "WorkingDirectory": str(_workdir(cfg)),
        "StartCalendarInterval": cal,
        "StandardOutPath": str(logs / "service.out.log"),
        "StandardErrorPath": str(logs / "service.err.log"),
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
        "ProcessType": "Background",
    })


def _mac_install(cfg: Config, console: Console) -> int:
    plist = _mac_plist_path(cfg)
    plist.parent.mkdir(parents=True, exist_ok=True)
    cfg.paths.log.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    _run(["launchctl", "bootout", domain, str(plist)])  # replace an older copy, ignore errors
    plist.write_bytes(macos_plist(cfg))
    p = _run(["launchctl", "bootstrap", domain, str(plist)])
    if p.returncode != 0:
        console.print(f"[red]launchctl bootstrap failed:[/] {(p.stderr or p.stdout).strip()}")
        return 1
    console.print(f"[green]installed[/] launchd agent [bold]{_mac_label(cfg)}[/] ({describe(cfg)})\n"
                  f"  {plist}\n  runs while you're logged in; a missed run starts after the Mac wakes")
    return 0


def _mac_uninstall(cfg: Config, console: Console) -> int:
    plist = _mac_plist_path(cfg)
    _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)])
    if plist.exists():
        plist.unlink()
        console.print(f"[green]removed[/] {plist}")
        return 0
    console.print(f"[yellow]not installed[/] ({plist} not found)")
    return 1


def _mac_status(cfg: Config, console: Console) -> int:
    plist = _mac_plist_path(cfg)
    if not plist.exists():
        console.print(f"launchd agent {_mac_label(cfg)}: [yellow]not installed[/]")
        return 1
    p = _run(["launchctl", "print", f"gui/{os.getuid()}/{_mac_label(cfg)}"])
    console.print(f"launchd agent {_mac_label(cfg)}: "
                  + ("[green]loaded[/]" if p.returncode == 0 else "[yellow]file present, not loaded[/]"))
    for line in p.stdout.splitlines():
        if any(k in line for k in ("state =", "last exit code", "runs =")):
            console.print("  " + line.strip(), markup=False, highlight=False)
    return 0


# ---------------------------------------------------------------- linux / systemd


def _unit(cfg: Config) -> str:
    return cfg.service.name.lower()


def _systemd_dir(cfg: Config) -> Path:
    if cfg.service.linux_scope == "system":
        return Path("/etc/systemd/system")
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"


def _systemctl(cfg: Config) -> list[str]:
    return ["systemctl"] + (["--user"] if cfg.service.linux_scope == "user" else [])


def systemd_units(cfg: Config) -> dict[str, str]:
    import shlex
    h, m = cfg.service.hour_minute
    short = {d: d[:3].capitalize() for d in WEEKDAYS}
    days = ",".join(short[d] for d in cfg.service.days) if cfg.service.days and len(cfg.service.days) < 7 else ""
    on_cal = f"{days + ' ' if days else ''}*-*-* {h:02d}:{m:02d}:00"
    user = ""
    if cfg.service.linux_scope == "system":
        user = f"User={os.environ.get('SUDO_USER') or getpass.getuser()}\n"
    service = f"""[Unit]
Description=google-docs-backup: Google Drive backup
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
{user}WorkingDirectory={_workdir(cfg)}
ExecStart={shlex.join(_command(cfg))}
Nice=10
"""
    timer = f"""[Unit]
Description=google-docs-backup schedule ({describe(cfg)})

[Timer]
OnCalendar={on_cal}
Persistent=true
RandomizedDelaySec=5min

[Install]
WantedBy=timers.target
"""
    return {f"{_unit(cfg)}.service": service, f"{_unit(cfg)}.timer": timer}


def _linux_install(cfg: Config, console: Console) -> int:
    if cfg.service.linux_scope == "system" and os.geteuid() != 0:
        console.print("[red]linux_scope: system needs root[/] - run: sudo ./install.sh")
        return 2
    d = _systemd_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    for name, text in systemd_units(cfg).items():
        (d / name).write_text(text)
    sc = _systemctl(cfg)
    for cmd in (sc + ["daemon-reload"], sc + ["enable", "--now", f"{_unit(cfg)}.timer"]):
        p = _run(cmd)
        if p.returncode != 0:
            console.print(f"[red]{' '.join(cmd)} failed:[/] {(p.stderr or p.stdout).strip()}")
            return 1
    console.print(f"[green]installed[/] systemd timer [bold]{_unit(cfg)}.timer[/] ({describe(cfg)})\n  {d}")
    if cfg.service.linux_scope == "user":
        linger = _run(["loginctl", "show-user", getpass.getuser(), "--property=Linger"]).stdout.strip()
        if linger != "Linger=yes":
            console.print("  [yellow]note:[/] user timers only run while you're logged in. To run "
                          f"while logged out:  [bold]sudo loginctl enable-linger {getpass.getuser()}[/]")
    return 0


def _linux_uninstall(cfg: Config, console: Console) -> int:
    sc = _systemctl(cfg)
    _run(sc + ["disable", "--now", f"{_unit(cfg)}.timer"])
    removed = []
    for name in systemd_units(cfg):
        f = _systemd_dir(cfg) / name
        if f.exists():
            f.unlink()
            removed.append(str(f))
    _run(sc + ["daemon-reload"])
    if not removed:
        console.print("[yellow]not installed[/]")
        return 1
    console.print("[green]removed[/] " + ", ".join(removed))
    return 0


def _linux_status(cfg: Config, console: Console) -> int:
    sc = _systemctl(cfg)
    p = _run(sc + ["list-timers", "--all", f"{_unit(cfg)}.timer", "--no-pager"])
    if f"{_unit(cfg)}.timer" not in p.stdout:
        console.print(f"systemd timer {_unit(cfg)}.timer: [yellow]not installed[/]")
        return 1
    console.print(p.stdout.rstrip(), markup=False, highlight=False)
    last = _run(sc + ["show", f"{_unit(cfg)}.service", "--property=Result,ExecMainStatus"]).stdout.split()
    console.print("  last run: " + " ".join(last), markup=False, highlight=False)
    return 0


# ---------------------------------------------------------------- dispatch

_IMPL = {
    "windows": (_win_install, _win_uninstall, _win_status),
    "macos": (_mac_install, _mac_uninstall, _mac_status),
    "linux": (_linux_install, _linux_uninstall, _linux_status),
}


def preview(cfg: Config) -> str:
    plat = _platform()
    if plat == "windows":
        return windows_task_xml(cfg)
    if plat == "macos":
        return macos_plist(cfg).decode()
    return "\n".join(f"# {n}\n{t}" for n, t in systemd_units(cfg).items())


def main(cfg: Config, action: str, console: Console) -> int:
    install, uninstall, status = _IMPL[_platform()]
    if action == "install":
        if cfg.source is None:
            console.print("[red]no config file[/]")
            return 2
        return install(cfg, console)
    if action == "uninstall":
        return uninstall(cfg, console)
    if action == "show":
        console.print(preview(cfg), markup=False, highlight=False)
        return 0
    return status(cfg, console)
