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
    dispatch: Callable[[int], str | None] | None = None,
    commit_keys: tuple[int, ...] = (10, 13, curses.KEY_ENTER),
    transform: Callable[[str], str] | None = None,
    maxlen: int | None = None,
) -> str | None:
    """Single-line text input drawn at row ``y`` as ``{prefix}{buf}_``.

    Returns the buffer on commit (or ``None`` on commit when ``allow_empty`` is
    False and the buffer is empty), and ``None`` on Escape.

    The hooks let the keybinding-aware prompts share this one loop:

    * ``accept(ch, buf)`` -- whether a printable char (after ``transform``) is
      appended; lets callers restrict input (digits, identifier rules, a live
      cell-ref probe, ...).
    * ``transform`` -- map a typed char before it is tested/appended (e.g.
      upper-casing cell refs in ``nav``).
    * ``dispatch(ch)`` -- resolve a keycode to ``"cancel"`` / ``"commit"`` /
      ``"delete_back"`` (the ``_action_for`` keymap), consulted before the
      hardcoded Esc / Enter / Backspace fallbacks.
    * ``commit_keys`` -- extra keycodes that commit (e.g. Tab in ``nav``).
    * ``maxlen`` -- cap the buffer length.
    """
    buf = initial
    while True:
        stdscr.addnstr(y, 0, f"{prefix}{buf}_", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        ch = stdscr.getch()
        action = dispatch(ch) if dispatch else None
        if action == "cancel" or ch == 27:
            return None
        if action == "commit" or ch in commit_keys:
            return buf if (buf or allow_empty) else None
        if action == "delete_back" or ch in (curses.KEY_BACKSPACE, 127, 8):
            buf = buf[:-1]
        elif 32 <= ch < 127:
            cand = transform(chr(ch)) if transform else chr(ch)
            if (maxlen is None or len(buf) < maxlen) and accept(cand, buf):
                buf += cand


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
