"""Fixtures for PTY-driven integration tests of the curses TUI.

These tests spawn a real ``gridcalc`` process attached to a pseudo-terminal
and drive it by writing keystroke bytes to the master fd. They exercise the
curses layer end-to-end -- input handling, rendering, redraw -- which unit
tests with a ``MockStdscr`` cannot reach.

The tests are slow (each one allocates a PTY, forks a subprocess, and
synchronizes with the curses redraw via ANSI-stripped output polling) and
PTY-only (skipped on platforms without ``pty`` such as Windows). They are
gated behind the ``tty`` marker and excluded from the default test run.
Invoke them with ``make test-tty`` or ``pytest -m tty``.
"""

from __future__ import annotations

import contextlib
import os
import re
import select
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

# Skip the whole module on Windows: pty.openpty() doesn't exist there, and
# curses doesn't ship on stock Python for Windows either.
pty = pytest.importorskip("pty")

REPO_ROOT = Path(__file__).resolve().parents[2]
GRIDCALC_BIN = REPO_ROOT / ".venv" / "bin" / "gridcalc"

# Strips ANSI CSI / OSC / charset-select / single-char escape sequences plus
# bare carriage returns. The result is the raw text curses would paint to a
# dumb display -- good enough to assert on status-bar contents and cell text.
_ANSI = re.compile(
    rb"\x1b\[[0-9;?]*[a-zA-Z]"  # CSI sequences (cursor moves, SGR, ...)
    rb"|\x1b\][^\x07]*\x07"  # OSC ... BEL (terminal title, etc.)
    rb"|\x1b[()][0-9A-Za-z]"  # G0/G1 charset selection
    rb"|\r"  # carriage returns
)


def _strip_ansi(b: bytes) -> str:
    return _ANSI.sub(b"", b).decode("utf-8", errors="replace")


@dataclass
class TuiSession:
    """A running gridcalc subprocess attached to a PTY.

    ``send`` writes keystroke bytes to the master fd; ``wait_for`` polls
    output until a substring appears in the de-ANSI'd render or a timeout
    elapses. The fixture owns shutdown -- tests should not call terminate().
    """

    proc: subprocess.Popen[bytes]
    master_fd: int
    _buffer: bytearray

    def send(self, data: str | bytes) -> None:
        if isinstance(data, str):
            data = data.encode("utf-8")
        os.write(self.master_fd, data)

    def wait_for(self, needle: str, timeout: float = 4.0) -> str:
        """Read output until ``needle`` appears in the de-ANSI'd text.

        Returns the full accumulated render (de-ANSI'd) up to the point the
        needle appeared, or all collected output if it never did. Raises
        ``AssertionError`` on timeout so the test fails with a useful
        decoded snapshot rather than a bare TimeoutError.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            r, _, _ = select.select([self.master_fd], [], [], 0.1)
            if not r:
                continue
            try:
                chunk = os.read(self.master_fd, 8192)
            except OSError:
                break
            if not chunk:
                break
            self._buffer.extend(chunk)
            decoded = _strip_ansi(bytes(self._buffer))
            if needle in decoded:
                return decoded
        decoded = _strip_ansi(bytes(self._buffer))
        raise AssertionError(
            f"timed out waiting for {needle!r} in TUI output. "
            f"Last 800 chars of render:\n{decoded[-800:]}"
        )

    def drain(self, idle_seconds: float = 0.3, total_cap: float = 1.5) -> str:
        """Read until the output goes idle for ``idle_seconds``, or cap hit.

        Useful after a keystroke whose effect is a redraw rather than a
        specific substring -- e.g. ``u`` for undo, where the assertion is
        ``cell value reverted`` not ``string X appeared``.
        """
        deadline = time.time() + total_cap
        last_read = time.time()
        while time.time() < deadline:
            r, _, _ = select.select([self.master_fd], [], [], 0.05)
            if r:
                try:
                    chunk = os.read(self.master_fd, 8192)
                except OSError:
                    break
                if chunk:
                    self._buffer.extend(chunk)
                    last_read = time.time()
                    continue
            if time.time() - last_read > idle_seconds:
                break
        return _strip_ansi(bytes(self._buffer))


def _spawn(args: list[str | os.PathLike[str]]) -> tuple[subprocess.Popen[bytes], int]:
    """Fork gridcalc with a PTY on stdin/stdout/stderr."""
    master, slave = pty.openpty()
    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "LINES": "30",
        "COLUMNS": "120",
        "GRIDCALC_SANDBOX": "1",
    }
    proc = subprocess.Popen(
        [str(a) for a in args],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
        env=env,
        start_new_session=True,
    )
    os.close(slave)
    return proc, master


def _shutdown(proc: subprocess.Popen[bytes], master_fd: int) -> None:
    """Terminate the child and release the PTY. SIGTERM -> SIGKILL escalation.

    We don't try ``:q!`` from inside -- it's timing-sensitive depending on
    what mode the TUI is in, and the tests' invariants don't depend on a
    clean curses teardown.
    """
    if proc.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=2.0)
    with contextlib.suppress(OSError):
        os.close(master_fd)


@pytest.fixture
def tui_session(request: pytest.FixtureRequest) -> Iterator[TuiSession]:
    """Yield a running gridcalc session opened to a file.

    Mark the test with ``pytest.mark.tui_file("examples/example_lp.json")``
    to choose the file; defaults to launching with no file.
    """
    marker = request.node.get_closest_marker("tui_file")
    args: list[str | os.PathLike[str]] = [GRIDCALC_BIN]
    if marker is not None:
        rel = marker.args[0]
        args.append(REPO_ROOT / rel)

    if not GRIDCALC_BIN.exists():
        pytest.skip(f"gridcalc entry point not found at {GRIDCALC_BIN}. Run `make build` first.")

    proc, master = _spawn(args)
    session = TuiSession(proc=proc, master_fd=master, _buffer=bytearray())
    try:
        yield session
    finally:
        _shutdown(proc, master)


_INTEGRATION_DIR = str(Path(__file__).resolve().parent)


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Auto-mark every test under ``tests/integration/`` with ``tty`` so the
    default run filters them out. This hook is global -- pytest calls it
    with every item in the session, regardless of which conftest defined
    it -- so we filter on the file path before applying the marker.
    """
    for item in items:
        if item.fspath and str(item.fspath).startswith(_INTEGRATION_DIR):
            item.add_marker(pytest.mark.tty)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "tty: PTY-driven curses integration test")
    config.addinivalue_line("markers", "tui_file(path): preload gridcalc with this file on launch")


# Skip the entire module on platforms where pty isn't usable.
if sys.platform == "win32":  # pragma: no cover - platform guard
    collect_ignore_glob = ["test_*.py"]
