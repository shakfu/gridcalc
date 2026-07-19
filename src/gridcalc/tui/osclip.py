"""OS clipboard access and TSV (de)serialisation for the TUI.

The TUI keeps a full-fidelity *internal* clipboard (formulas + formatting)
in :class:`gridcalc.tui.undo.Clipboard`. This module adds the *interchange*
path: pushing a tab-separated snapshot of a region to the operating-system
clipboard so it can be pasted into another program, and reading TSV back so
content copied elsewhere can be pasted into the grid.

:class:`SystemClipboard` shells out to whichever platform tool is available
and degrades gracefully -- every method is a no-op returning ``False`` /
``None`` when no tool is found or the subprocess fails, so the TUI never
crashes on a headless box. The TSV helpers are pure and do not touch the OS.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

# Per platform, ordered (copy_argv, paste_argv) pairs; the first pair whose
# binaries both resolve on PATH wins. Kept as full argv lists (never a shell
# string) so nothing is interpreted by a shell.
_TIMEOUT = 5


def _candidates() -> list[tuple[list[str], list[str]]]:
    if sys.platform == "darwin":
        return [(["pbcopy"], ["pbpaste"])]
    if sys.platform == "win32":
        return [(["clip"], ["powershell", "-NoProfile", "-Command", "Get-Clipboard"])]
    # Linux / BSD: prefer Wayland, then X11 tools.
    return [
        (["wl-copy"], ["wl-paste", "--no-newline"]),
        (["xclip", "-selection", "clipboard"], ["xclip", "-selection", "clipboard", "-o"]),
        (["xsel", "--clipboard", "--input"], ["xsel", "--clipboard", "--output"]),
    ]


def _first_available() -> tuple[list[str], list[str]] | None:
    for copy_cmd, paste_cmd in _candidates():
        if shutil.which(copy_cmd[0]) and shutil.which(paste_cmd[0]):
            return copy_cmd, paste_cmd
    return None


class SystemClipboard:
    """Best-effort access to the operating-system clipboard.

    Resolves the platform tool once at construction. When none is present
    the instance stays valid but inert: :attr:`available` is ``False`` and
    the read/write methods no-op.
    """

    def __init__(self) -> None:
        self._cmds = _first_available()

    @property
    def available(self) -> bool:
        return self._cmds is not None

    def copy_text(self, text: str) -> bool:
        """Write ``text`` to the OS clipboard. Returns True on success."""
        if self._cmds is None:
            return False
        copy_cmd, _ = self._cmds
        try:
            subprocess.run(  # noqa: S607 -- fixed binary names, no shell
                copy_cmd,
                input=text.encode("utf-8"),
                check=True,
                timeout=_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return True

    def paste_text(self) -> str | None:
        """Read the OS clipboard as text, or None if unavailable/failed."""
        if self._cmds is None:
            return None
        _, paste_cmd = self._cmds
        try:
            out = subprocess.run(  # noqa: S607 -- fixed binary names, no shell
                paste_cmd,
                capture_output=True,
                check=True,
                timeout=_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.decode("utf-8", errors="replace")


def rows_to_tsv(rows: list[list[str]]) -> str:
    """Serialise a rectangular grid of cell strings to TSV.

    Rows are newline-separated, cells tab-separated. No trailing newline,
    so a round-trip through ``pbcopy``/``pbpaste`` compares equal. Embedded
    tabs/newlines in a cell are replaced with spaces (TSV has no quoting).
    """

    def clean(s: str) -> str:
        return s.replace("\t", " ").replace("\r", " ").replace("\n", " ")

    return "\n".join("\t".join(clean(c) for c in row) for row in rows)


def tsv_to_rows(text: str) -> list[list[str]]:
    """Parse TSV text into a grid of cell strings.

    Accepts LF or CRLF line endings and drops a single trailing blank line
    (the newline many clipboard tools append). Returns [] for empty input.
    """
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    if body.endswith("\n"):
        body = body[:-1]
    if body == "":
        return []
    return [line.split("\t") for line in body.split("\n")]
