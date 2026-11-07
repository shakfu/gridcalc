"""Run a command with a time limit and a memory cap on its whole process group.

macOS does not enforce `RLIMIT_AS`, and `uv run` starts the Python that does the
work as a child, so a cap must cover the group. `run_guarded` polls the group's
resident memory and kills the group past either limit.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass

MEM_MB = 2048  # default cap per command
_POLL_S = 0.5


@dataclass
class Result:
    returncode: int | None
    stdout: str
    stderr: str
    killed: str | None  # "timeout", "memory: N MB", or None
    peak_mb: int


def group_rss_mb(pgid: int) -> int:
    """Resident memory of every process in group ``pgid``, in MB."""
    ps = shutil.which("ps") or "/bin/ps"
    out = subprocess.run(  # noqa: S603
        [ps, "-A", "-o", "pgid=,rss="], capture_output=True, text=True, check=False
    ).stdout
    kb = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == str(pgid):
            kb += int(parts[1])
    return kb // 1024


def default_jobs(mem_mb: int) -> int:
    """Parallel jobs whose caps together stay under half of physical memory."""
    total_mb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1 << 20)
    return max(1, min((os.cpu_count() or 2) - 1, total_mb // 2 // mem_mb))


def run_guarded(
    argv: list[str],
    *,
    timeout: float,
    mem_mb: int = MEM_MB,
    cwd: str | os.PathLike[str] | None = None,
    capture_stdout: bool = True,
) -> Result:
    """Run ``argv`` in a new process group; kill the group past ``timeout`` or ``mem_mb``."""
    p = subprocess.Popen(  # noqa: S603 -- callers name their own engines
        argv,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        start_new_session=True,
    )
    killed: list[str] = []
    peak = [0]
    done = threading.Event()

    def watch() -> None:
        deadline = time.monotonic() + timeout
        while not done.wait(_POLL_S):
            rss = group_rss_mb(p.pid)
            peak[0] = max(peak[0], rss)
            reason = None
            if rss > mem_mb:
                reason = f"memory: {rss} MB"
            elif time.monotonic() > deadline:
                reason = "timeout"
            if reason:
                killed.append(reason)
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(p.pid, signal.SIGKILL)
                return

    t = threading.Thread(target=watch, daemon=True)
    t.start()
    try:
        out, err = p.communicate()
    finally:
        done.set()
        t.join()
        # A child that outlived its parent would escape the next poll.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGKILL)
    return Result(p.returncode, out or "", err or "", killed[0] if killed else None, peak[0])
