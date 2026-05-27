"""Generic curses I/O helpers: bottom-line messages and single-line input."""

from __future__ import annotations

import curses
from collections.abc import Callable


def _accept_any(ch: str, buf: str) -> bool:
    return True


def _line_input(
    stdscr: curses.window,
    y: int,
    *,
    prefix: str = "",
    initial: str = "",
    accept: Callable[[str, str], bool] = _accept_any,
    allow_empty: bool = True,
) -> str | None:
    """Single-line text input drawn at row ``y`` as ``{prefix}{buf}_``.

    Returns the buffer on Enter (or ``None`` on Enter when ``allow_empty`` is
    False and the buffer is empty), and ``None`` on Escape. ``accept(ch, buf)``
    decides whether a printable char is appended -- letting callers restrict
    input (digits only, identifier rules, ...) while sharing the edit loop.
    """
    buf = initial
    while True:
        stdscr.addnstr(y, 0, f"{prefix}{buf}_", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == 27:
            return None
        if ch in (10, 13, curses.KEY_ENTER):
            return buf if (buf or allow_empty) else None
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            buf = buf[:-1]
        elif 32 <= ch < 127 and accept(chr(ch), buf):
            buf += chr(ch)


def prompt_filename(stdscr: curses.window, prompt: str, dflt: str | None = None) -> str | None:
    return _line_input(
        stdscr, curses.LINES - 1, prefix=prompt, initial=dflt or "", allow_empty=False
    )


def _flash(stdscr: curses.window, msg: str) -> None:
    """Write a transient status message to the bottom line and return.

    The no-wait counterpart of :func:`show_error`, which blocks for a keypress.
    """
    stdscr.addnstr(curses.LINES - 1, 0, msg, curses.COLS - 1)
    stdscr.clrtoeol()
    stdscr.refresh()


def show_error(stdscr: curses.window, msg: str) -> None:
    stdscr.addnstr(curses.LINES - 1, 0, msg, curses.COLS - 1)
    stdscr.clrtoeol()
    stdscr.refresh()
    stdscr.getch()
