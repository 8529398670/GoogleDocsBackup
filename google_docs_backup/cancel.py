"""Clean cancellation: one cancel flag for the whole run, and every child process
(rclone, pandoc) tracked so a cancel - or our own death - takes them down too.

- Ctrl-C, Ctrl-Break, closing the console window (Windows) and SIGTERM/SIGHUP
  (macOS/Linux) all become KeyboardInterrupt in the main thread.
- Windows: we put ourselves in a Job Object with KILL_ON_JOB_CLOSE, so even a
  hard kill (Task Manager, "End task") kills rclone/pandoc with us.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time

CANCEL = threading.Event()


class Cancelled(Exception):
    """Raised inside workers once a cancel was requested."""


def check() -> None:
    if CANCEL.is_set():
        raise Cancelled()


_procs: set[subprocess.Popen] = set()
_lock = threading.Lock()
_job = None  # keep the job handle alive for the life of the process


def popen(cmd: list[str], **kw) -> subprocess.Popen:
    check()
    # Own process group: a Ctrl-C / Ctrl-Break goes to us only, so we decide the
    # order (set CANCEL first, then stop the children) and a cancel is reported as
    # "cancelled", not as rclone failing. On Windows the Job Object still kills
    # them if we die; closing the console window still reaches them too.
    if os.name == "nt":
        kw["creationflags"] = kw.get("creationflags", 0) | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw.setdefault("start_new_session", True)
    p = subprocess.Popen(cmd, **kw)
    with _lock:
        _procs.add(p)
    return p


def forget(p: subprocess.Popen) -> None:
    with _lock:
        _procs.discard(p)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """subprocess.run(..., capture_output=True), but tracked and cancellable."""
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    p = popen(cmd, **kw)
    try:
        out, err = p.communicate()
    finally:
        forget(p)
    return subprocess.CompletedProcess(cmd, p.returncode, out, err)


def stop_children(grace: float = 5.0) -> int:
    """Ask every child to stop, then force it after `grace` seconds. Returns how many."""
    with _lock:
        procs = [p for p in _procs if p.poll() is None]
    for p in procs:  # polite first: rclone tidies up its own .partial files on an interrupt
        try:
            if os.name == "nt":
                p.send_signal(signal.CTRL_BREAK_EVENT)  # works because each child has its own group
            else:
                p.send_signal(signal.SIGINT)
        except (OSError, ValueError):
            try:
                p.terminate()
            except OSError:
                pass
    deadline = time.monotonic() + grace
    for p in procs:
        try:
            p.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            p.kill()
    return len(procs)


def _raise_interrupt(signum, frame):  # noqa: ARG001
    raise KeyboardInterrupt


def _windows_job() -> None:
    """Children die with us, however we die."""
    global _job
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                    ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = k32.SetInformationJobObject(wintypes.HANDLE(job), 9,  # JobObjectExtendedLimitInformation
                                     ctypes.byref(info), ctypes.sizeof(info))
    if ok and k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(k32.GetCurrentProcess())):
        _job = job


def install() -> None:
    """Call once, from the main thread, before starting any child process."""
    if os.name == "nt":
        try:
            _windows_job()
        except Exception:  # noqa: BLE001 - best effort; Ctrl-C handling still works
            pass
        # Ctrl-Break and closing the console window arrive as SIGBREAK
        signal.signal(signal.SIGBREAK, _raise_interrupt)
    else:
        signal.signal(signal.SIGTERM, _raise_interrupt)
        signal.signal(signal.SIGHUP, _raise_interrupt)
