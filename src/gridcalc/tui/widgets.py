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


def select_from_list(
    stdscr: curses.window,
    title: str,
    items: list[str],
    *,
    initial: int = 0,
) -> int | None:
    """Interactive single-choice picker over ``items``.

    Draws ``title`` at the top and one row per item, highlighting the current
    row. j/down and k/up move; g/G jump to first/last; Enter selects and
    returns its zero-based index; Esc or q cancels and returns ``None``. The
    view scrolls when the list is taller than the terminal.
    """
    if not items:
        return None
    sel = max(0, min(initial, len(items) - 1))
    offset = 0
    while True:
        stdscr.erase()
        stdscr.attron(curses.A_BOLD)
        stdscr.addnstr(0, 0, title, curses.COLS - 1)
        stdscr.attroff(curses.A_BOLD)

        visible = max(1, curses.LINES - 3)
        if sel < offset:
            offset = sel
        elif sel >= offset + visible:
            offset = sel - visible + 1

        for i in range(visible):
            idx = offset + i
            if idx >= len(items):
                break
            marker = ">" if idx == sel else " "
            attr = curses.A_REVERSE if idx == sel else 0
            stdscr.addnstr(i + 1, 0, f"{marker} {items[idx]}", curses.COLS - 1, attr)

        footer = "  [j/k]move [enter]select [g/G]top/bot [q/esc]cancel"
        stdscr.addnstr(curses.LINES - 1, 0, footer, curses.COLS - 1, curses.A_DIM)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch in (ord("j"), curses.KEY_DOWN):
            sel = min(sel + 1, len(items) - 1)
        elif ch in (ord("k"), curses.KEY_UP):
            sel = max(sel - 1, 0)
        elif ch == ord("g"):
            sel = 0
        elif ch == ord("G"):
            sel = len(items) - 1
        elif ch in (10, 13, curses.KEY_ENTER):
            return sel
        elif ch in (27, ord("q")):
            return None


def pager(stdscr: curses.window, title: str, lines: list[str]) -> None:
    """Full-screen scrollable view of ``lines`` under a bold ``title``.

    j/down scroll one line; k/up scroll back; space/PgDn page down; b/PgUp
    page up; g/G jump to top/bottom; any other key returns to the caller.

    Lives here rather than in ``commands`` so both the trust prompt and the
    optimizer reports can use it -- ``commands`` imports ``solve``, so the
    dependency could not run the other way.
    """
    body = lines or [""]
    offset = 0
    while True:
        stdscr.erase()
        stdscr.attron(curses.A_BOLD)
        stdscr.addnstr(0, 0, title, curses.COLS - 1)
        stdscr.attroff(curses.A_BOLD)

        visible = max(1, curses.LINES - 3)
        max_offset = max(0, len(body) - visible)
        offset = max(0, min(offset, max_offset))

        for i in range(visible):
            idx = offset + i
            if idx >= len(body):
                break
            stdscr.addnstr(i + 1, 0, f"  {body[idx]}", curses.COLS - 1)

        end = min(offset + visible, len(body))
        footer = (
            f"  lines {offset + 1}-{end}/{len(body)}  "
            "[j/k]scroll [space/b]page [g/G]top/bot [q]back"
        )
        stdscr.addnstr(curses.LINES - 1, 0, footer, curses.COLS - 1, curses.A_DIM)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch in (ord("j"), curses.KEY_DOWN):
            offset += 1
        elif ch in (ord("k"), curses.KEY_UP):
            offset -= 1
        elif ch in (ord(" "), curses.KEY_NPAGE):
            offset += visible
        elif ch in (ord("b"), curses.KEY_PPAGE):
            offset -= visible
        elif ch == ord("g"):
            offset = 0
        elif ch == ord("G"):
            offset = max_offset
        else:
            return
