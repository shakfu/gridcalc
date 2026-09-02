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


def _needs_quoting(s: str) -> bool:
    """Whether ``s`` cannot survive the wire unquoted.

    A tab or a newline would be read back as a cell or row boundary. A double
    quote matters too, and less obviously: a cell whose text is literally
    ``"x"`` would come back as ``x``, because the parser has no way to tell an
    unquoted quote from a field the writer quoted.
    """
    return any(ch in s for ch in ("\t", "\n", "\r", '"'))


def rows_to_tsv(rows: list[list[str]]) -> str:
    """Serialise a rectangular grid of cell strings to TSV.

    Rows are newline-separated, cells tab-separated. No trailing newline,
    so a round-trip through ``pbcopy``/``pbpaste`` compares equal.

    A cell containing a tab, a newline or a double quote is wrapped in double
    quotes with its own quotes doubled -- the CSV convention from RFC 4180,
    which is also what Excel, Numbers and Sheets write into the clipboard for
    such a cell, so the quoting is understood on the other side rather than
    being a gridcalc dialect. Cells that need none of this are written
    verbatim, so ordinary content is byte-for-byte what it always was.

    This replaced sanitising tabs and newlines to spaces. That kept the shape
    of the grid but silently rewrote the user's data, and a copy-paste that
    corrupts a cell is worse than one that fails.
    """

    def field(s: str) -> str:
        if not _needs_quoting(s):
            return s
        return '"' + s.replace('"', '""') + '"'

    return "\n".join("\t".join(field(c) for c in row) for row in rows)


def _split_row(line: str, start: int) -> tuple[list[str], int, bool]:
    """Read one row from ``line[start:]``.

    Returns its cells, the offset to resume at, and whether the row ended on a
    newline rather than at the end of the text -- which is what says another
    row follows, even an empty one. Takes the whole text rather than a single
    line because a quoted field may contain newlines, so rows cannot be found
    by splitting on ``\n`` first.
    """
    cells: list[str] = []
    i = start
    n = len(line)
    while True:
        if i < n and line[i] == '"':
            # Quoted field: consume to the closing quote, unescaping "" -> ".
            i += 1
            buf: list[str] = []
            while i < n:
                if line[i] == '"':
                    if i + 1 < n and line[i + 1] == '"':
                        buf.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                buf.append(line[i])
                i += 1
            cells.append("".join(buf))
            # Anything between the closing quote and the next delimiter is
            # malformed input; keep it rather than dropping the user's bytes.
            while i < n and line[i] not in ("\t", "\n"):
                cells[-1] += line[i]
                i += 1
        else:
            j = i
            while j < n and line[j] not in ("\t", "\n"):
                j += 1
            cells.append(line[i:j])
            i = j
        if i >= n:
            return cells, i, False
        if line[i] == "\t":
            i += 1
            continue
        return cells, i + 1, True  # line[i] == "\n"


def tsv_to_rows(text: str) -> list[list[str]]:
    """Parse TSV text into a grid of cell strings.

    Accepts LF or CRLF line endings and drops a single trailing blank line
    (the newline many clipboard tools append). Returns [] for empty input.

    Understands the quoting :func:`rows_to_tsv` writes, so a cell holding a
    tab or a newline round-trips; a field that is not quoted is taken
    literally, which is what unquoted TSV from another program means.
    """
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    if body.endswith("\n"):
        body = body[:-1]
    if body == "":
        return []
    rows: list[list[str]] = []
    pos = 0
    while True:
        cells, pos, more = _split_row(body, pos)
        rows.append(cells)
        if not more:
            return rows
