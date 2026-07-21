"""Curses TUI for gridcalc.

This package is split by concern, but ``gridcalc.tui`` remains the single
public namespace: the submodule symbols are re-exported below, so existing
imports (``from gridcalc.tui import cmdexec`` etc.) keep working.

The interactive controller -- the keypress/event functions and the shared
keymap state -- lives in *this* module rather than a submodule. That is
deliberate: the test-suite patches ``gridcalc.tui.draw`` and rebinds
``gridcalc.tui._resolved_keymap`` and then drives ``cmdline``. For those
patches to be observed, the patched names and the functions that read them
must resolve in the same module namespace (Python looks free variables up in
the *defining* module's globals). So ``_resolved_keymap``, ``_action_for`` and
``cmdline`` are defined here, and ``draw`` is imported here so ``cmdline``'s
reference to it is the patchable ``gridcalc.tui.draw``.
"""

from __future__ import annotations

import curses
import sys
from collections.abc import Callable

from ..config import emit_warnings, load_config
from ..engine import (
    CW_DEFAULT,
    EMPTY,
    LABEL,
    MAXIN,
    NCOL,
    NROW,
    Grid,
    Mode,
    cellname,
    ref,
)
from ..keys import build_resolved_keymap
from ..sandbox import (
    SANDBOX_ENABLED,
    FileInfo,
    LoadPolicy,
    classify_module,
    configure_sandbox,
    inspect_file,
)
from . import _state
from .commands import (
    cmd_blank,
    cmd_clear,
    cmd_csv,
    cmd_edit,
    cmd_format,
    cmd_gformat,
    cmd_mode,
    cmd_name,
    cmd_names,
    cmd_open,
    cmd_pd,
    cmd_quit,
    cmd_save,
    cmd_savequit,
    cmd_sheet,
    cmd_sort,
    cmd_title,
    cmd_unname,
    cmd_view,
    cmd_width,
    cmd_xlsx,
    cmdexec,
    movecmd,
    name_set,
    replcmd,
    selectrange,
    trust_prompt,
)
from .format import fmt_float, fmtcell
from .objedit import _build_formula, _fmt_val, obj_editor
from .osclip import SystemClipboard
from .render import GW, _paint_label_overflow, draw, init_colors, vcols, vrows
from .search import _search_grid, search_indicator, search_next
from .solve import (
    _parse_bounds,
    _parse_cells,
    cmd_goal,
    cmd_opt,
)
from .undo import Clipboard, UndoEntry, UndoManager
from .widgets import _line_input, show_error

# Resolved keymap (context -> {keycode: action_name}). Populated once
# by ``mainloop`` after curses initialisation; consumed by the
# context-specific dispatchers (``entry``, ``visual_mode``, etc.).
# Empty until ``mainloop`` runs, so unit tests calling those helpers
# in isolation see no user bindings -- exactly the no-config baseline.
_resolved_keymap: dict[str, dict[int, str]] = {}


def _action_for(context: str, ch: int) -> str | None:
    """Resolve a keystroke to an action name in the given context.

    Returns ``None`` when the key isn't bound. For text-input
    contexts (``entry``, ``cmdline``, ``search``), printable bytes
    (``32 <= ch < 127``) always return ``None`` so they self-insert
    into the buffer regardless of any binding -- otherwise a stray
    ``[keys.entry] cancel = ["a"]`` would lock the user out of typing
    the letter ``a``. ``grid`` and ``visual`` are command-mode and
    have no self-insert behaviour, so all keys dispatch normally.
    """
    if context in ("entry", "cmdline", "search") and 32 <= ch < 127:
        return None
    return _resolved_keymap.get(context, {}).get(ch)


def cmdline(
    stdscr: curses.window,
    g: Grid,
    undo: UndoManager,
    sel: tuple[int, int, int, int] | None = None,
) -> bool:
    draw(stdscr, g, "CMD", "", sel=sel)
    buf = _line_input(
        stdscr,
        curses.LINES - 1,
        prefix=":",
        dispatch=lambda ch: _action_for("cmdline", ch),
        maxlen=255,
        allow_empty=False,
    )
    if buf is None:
        return False
    return cmdexec(stdscr, g, undo, buf, sel=sel)


def nav(stdscr: curses.window, g: Grid) -> None:
    draw(stdscr, g, "GOTO", "")

    def _accept_ref(cand: str, buf: str) -> bool:
        # Accept a char only if the buffer still parses to an in-bounds ref.
        # A bare column letter (e.g. "B") is probed as "B1" so it isn't
        # rejected before a row digit is typed.
        probe = buf + cand + ("1" if cand.isalpha() else "")
        r = ref(probe)
        return r is not None and r[1] < NCOL and r[2] < NROW

    buf = _line_input(
        stdscr,
        1,
        prefix="> ",
        commit_keys=(10, 13, curses.KEY_ENTER, 9),
        transform=str.upper,
        accept=_accept_ref,
        maxlen=MAXIN - 2,
    )
    if buf is None:
        return
    r = ref(buf)
    if r:
        _, c, row = r
        g.cc = c
        g.cr = row


def search_prompt(stdscr: curses.window, g: Grid) -> tuple[str, list[tuple[int, int]]]:
    """Prompt for a search pattern and return (pattern, matches)."""
    draw(stdscr, g, "SEARCH", "")
    buf = _line_input(
        stdscr,
        curses.LINES - 1,
        prefix="/",
        dispatch=lambda ch: _action_for("search", ch),
        maxlen=255,
        allow_empty=False,
    )
    if buf is None:
        return ("", [])
    matches = _search_grid(g, buf)
    if matches:
        g.cc, g.cr = matches[0]
    else:
        show_error(stdscr, f"No matches for: {buf}")
    return (buf, matches)


def entry(
    stdscr: curses.window,
    g: Grid,
    undo: UndoManager,
    label: bool,
    initial_ch: int,
    initial_text: str = "",
) -> None:
    buf = initial_text
    origc, origr = g.cc, g.cr
    picking = False
    refstart = 0
    pc, pr = 0, 0
    g.mc = -1
    g.mr = -1

    draw(stdscr, g, "ENTRY", "")
    if initial_ch:
        buf += chr(initial_ch)

    while True:
        if picking:
            g.cc = pc
            g.cr = pr
            g.mc = origc
            g.mr = origr
            draw(stdscr, g, "POINT", "")
            g.cc = origc
            g.cr = origr
        stdscr.addnstr(1, 0, f"> {buf}_", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        ch = stdscr.getch()

        action = _action_for("entry", ch)
        if action == "cancel" or ch == 27:
            g.cc = origc
            g.cr = origr
            g.mc = -1
            g.mr = -1
            break

        if picking:
            if ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT):
                if ch == curses.KEY_UP and pr > 0:
                    pr -= 1
                elif ch == curses.KEY_DOWN and pr < NROW - 1:
                    pr += 1
                elif ch == curses.KEY_LEFT and pc > 0:
                    pc -= 1
                elif ch == curses.KEY_RIGHT and pc < NCOL - 1:
                    pc += 1
                buf = buf[:refstart]
                buf += cellname(pc, pr)
                continue
            if ch == ord(":"):
                buf += ":"
                refstart = len(buf)
                continue
            picking = False
            g.mc = -1
            g.mr = -1

        if ch in (curses.KEY_UP, curses.KEY_DOWN) and not label:
            picking = True
            refstart = len(buf)
            pc, pr = origc, origr
            if ch == curses.KEY_UP and pr > 0:
                pr -= 1
            elif ch == curses.KEY_DOWN and pr < NROW - 1:
                pr += 1
            buf += cellname(pc, pr)
            continue

        if action == "commit_and_advance_row" or ch in (10, 13, curses.KEY_ENTER):
            g.mc = -1
            g.mr = -1
            undo.save_cell(g, origc, origr)
            g.setcell(origc, origr, buf)
            g.cc = origc
            g.cr = origr
            if g.cr < NROW - 1:
                g.cr += 1
            break
        elif action == "commit_and_advance_col" or ch == 9:
            g.mc = -1
            g.mr = -1
            undo.save_cell(g, origc, origr)
            g.setcell(origc, origr, buf)
            g.cc = origc
            g.cr = origr
            if g.cc < NCOL - 1:
                g.cc += 1
            break
        elif action == "delete_back" or ch in (curses.KEY_BACKSPACE, 127, 8):
            buf = buf[:-1]
        elif ch in (curses.KEY_LEFT, curses.KEY_RIGHT):
            pass
        elif len(buf) < MAXIN - 1 and 32 <= ch < 127:
            buf += chr(ch)


def visual_mode(stdscr: curses.window, g: Grid, undo: UndoManager, clipboard: Clipboard) -> None:
    """Visual selection mode. Arrow keys extend selection, : enters command line."""
    ac, ar = g.cc, g.cr  # anchor

    while True:
        c1 = min(ac, g.cc)
        r1 = min(ar, g.cr)
        c2 = max(ac, g.cc)
        r2 = max(ar, g.cr)
        sel = (c1, r1, c2, r2)
        rng = g.fmtrange(c1, r1, c2, r2)

        draw(stdscr, g, "VISUAL", "", sel=sel)
        stdscr.addnstr(1, 0, f"  {rng}", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()

        ch = stdscr.getch()
        action = _action_for("visual", ch)
        if action == "cancel" or ch == 27:
            break
        elif action == "yank" or ch == ord("y"):
            count = clipboard.yank(g, c1, r1, c2, r2)
            stdscr.addnstr(
                curses.LINES - 1,
                0,
                f"{count} cell(s) yanked",
                curses.COLS - 1,
            )
            stdscr.clrtoeol()
            stdscr.refresh()
            break
        elif action == "paste" or ch == ord("p"):
            if not clipboard.empty:
                clipboard.paste(g, undo, c1, r1)
            break
        elif action == "delete" or ch in (ord("d"), 127, 8, curses.KEY_BACKSPACE):
            count = 0
            for c in range(c1, c2 + 1):
                for r in range(r1, r2 + 1):
                    cl = g.cell(c, r)
                    if cl and cl.type != EMPTY:
                        undo.save_cell(g, c, r)
                        g._cells.pop((c, r), None)
                        count += 1
            g.recalc()
            stdscr.addnstr(
                curses.LINES - 1,
                0,
                f"{count} cell(s) deleted",
                curses.COLS - 1,
            )
            stdscr.clrtoeol()
            stdscr.refresh()
            break
        elif action == "enter_command" or ch == ord(":"):
            cmdline(stdscr, g, undo, sel=sel)
            break
        elif (action == "cursor_up" or ch == curses.KEY_UP) and g.cr > 0:
            g.cr -= 1
        elif (action == "cursor_down" or ch == curses.KEY_DOWN) and g.cr < NROW - 1:
            g.cr += 1
        elif (action == "cursor_left" or ch == curses.KEY_LEFT) and g.cc > 0:
            g.cc -= 1
        elif (action == "cursor_right" or ch == curses.KEY_RIGHT) and g.cc < NCOL - 1:
            g.cc += 1


def _grid_action_cursor_up(g: Grid, lc: int, lr: int) -> None:
    if g.cr > lr:
        g.cr -= 1


def _grid_action_cursor_down(g: Grid, lc: int, lr: int) -> None:
    if g.cr < NROW - 1:
        g.cr += 1


def _grid_action_cursor_left(g: Grid, lc: int, lr: int) -> None:
    if g.cc > lc:
        g.cc -= 1


def _grid_action_cursor_right(g: Grid, lc: int, lr: int) -> None:
    if g.cc < NCOL - 1:
        g.cc += 1


def _grid_action_next_sheet(g: Grid, lc: int, lr: int) -> None:
    g.next_sheet()


def _grid_action_prev_sheet(g: Grid, lc: int, lr: int) -> None:
    g.prev_sheet()


# Registry of grid-context actions. Adding an action means: (1) put the
# name in keys.KNOWN_ACTIONS["grid"], (2) add a callable here. Each
# callable takes ``(grid, locked_col, locked_row)``.
_GRID_ACTIONS: dict[str, Callable[[Grid, int, int], None]] = {
    "cursor_up": _grid_action_cursor_up,
    "cursor_down": _grid_action_cursor_down,
    "cursor_left": _grid_action_cursor_left,
    "cursor_right": _grid_action_cursor_right,
    "next_sheet": _grid_action_next_sheet,
    "prev_sheet": _grid_action_prev_sheet,
}


def _dispatch_grid_key(
    g: Grid,
    resolved_grid: dict[int, str],
    ch: int,
    lc: int,
    lr: int,
) -> bool:
    """Dispatch ``ch`` through the user's grid-context keymap.

    Returns True if the keystroke matched a user binding and was
    handled; the caller skips its hardcoded fallback chain in that
    case. Returns False otherwise. Unknown action names (not in
    ``_GRID_ACTIONS``) silently fall through -- they were already
    warned about at config-load time.
    """
    action = resolved_grid.get(ch)
    if action is None:
        return False
    fn = _GRID_ACTIONS.get(action)
    if fn is None:
        return False
    fn(g, lc, lr)
    return True


def mainloop(stdscr: curses.window, g: Grid) -> None:
    undo = UndoManager()
    clipboard = Clipboard(SystemClipboard())
    search_matches: list[tuple[int, int]] = []

    # Resolve the user's keybindings against the live curses runtime.
    # Stash on the module-level ``_resolved_keymap`` so the
    # context-specific dispatchers (entry, visual_mode, cmdline,
    # search_prompt) can read it without threading it through every
    # call site. Warnings (unsupported terminal capabilities,
    # conflicts) print to stderr like the rest of the config
    # diagnostics.
    global _resolved_keymap
    _resolved_keymap, key_warnings = build_resolved_keymap(_state._cfg.keys)
    for w in key_warnings:
        print(f"gridcalc: keybinding warning: {w}", file=sys.stderr)
    resolved_grid = _resolved_keymap.get("grid", {})

    while True:
        lc = g.tc
        lr = g.tr
        fc = max(vcols(g) - lc, 1)
        fr = max(vrows() - lr, 1)

        if lc > 0 and g.cc < lc:
            g.cc = lc
        if lr > 0 and g.cr < lr:
            g.cr = lr
        if lc > 0 and g.vc < lc:
            g.vc = lc
        if lr > 0 and g.vr < lr:
            g.vr = lr
        if g.cc >= lc:
            if g.cc < g.vc:
                g.vc = g.cc
            if g.cc >= g.vc + fc:
                g.vc = g.cc - fc + 1
        if g.cr >= lr:
            if g.cr < g.vr:
                g.vr = g.cr
            if g.cr >= g.vr + fr:
                g.vr = g.cr - fr + 1

        si = search_indicator(g, search_matches)
        # Default state -- pass an empty mode string so the top-right shows
        # only the formula-mode tag (e.g. `[PYTHON]`) without a redundant
        # `READY`. Transient modes (ENTRY, CMD, VISUAL, ...) still announce
        # themselves; the absence of one means we're in default.
        draw(stdscr, g, "", "", search_info=si)
        ch = stdscr.getch()

        # User-bound keys take precedence over the hardcoded fallback
        # chain. A binding that fires here short-circuits the rest of
        # this iteration -- so binding e.g. Tab to next_sheet does
        # *replace* its previous "advance one column" meaning.
        if _dispatch_grid_key(g, resolved_grid, ch, lc, lr):
            continue

        if ch == 0x1F & ord("c"):
            break
        elif ch == ord("u") or ch == 0x1F & ord("z"):
            # vi-style u / Ctrl-R are the documented bindings; Ctrl-Z and
            # Ctrl-Y stay as aliases. `u` must be tested before the
            # printable-char fallthrough below, or it starts label entry.
            undo.undo(g)
        elif ch == 0x1F & ord("r") or ch == 0x1F & ord("y"):
            undo.redo(g)
        elif ch in (0x1F & ord("b"), 0x1F & ord("u")):
            cl = g.cell(g.cc, g.cr)
            if cl and cl.type != EMPTY:
                undo.save_cell(g, g.cc, g.cr)
                if ch == 0x1F & ord("b"):
                    cl.bold = 1 - cl.bold
                else:
                    cl.underline = 1 - cl.underline
        elif ch == curses.KEY_UP and g.cr > lr:
            g.cr -= 1
        elif ch == curses.KEY_DOWN and g.cr < NROW - 1:
            g.cr += 1
        elif ch == curses.KEY_LEFT and g.cc > lc:
            g.cc -= 1
        elif ch == curses.KEY_RIGHT and g.cc < NCOL - 1:
            g.cc += 1
        elif ch == curses.KEY_HOME:
            g.cc = lc
            g.cr = lr
        elif ch == 9 and g.cc < NCOL - 1:
            g.cc += 1
        elif ch in (10, 13, curses.KEY_ENTER):
            if g.cr < NROW - 1:
                g.cr += 1
        elif ch in (127, 8, curses.KEY_BACKSPACE):
            cl = g.cell(g.cc, g.cr)
            if cl and cl.type != EMPTY:
                undo.save_cell(g, g.cc, g.cr)
                g._cells.pop((g.cc, g.cr), None)
            g.recalc()
        elif ch == ord("!"):
            g.recalc()
        elif ch == ord(":"):
            if cmdline(stdscr, g, undo):
                break
        elif ch == ord(">"):
            nav(stdscr, g)
        elif ch == ord("/"):
            _, search_matches = search_prompt(stdscr, g)
        elif ch == ord("n"):
            search_next(g, search_matches, forward=True)
        elif ch == ord("N"):
            search_next(g, search_matches, forward=False)
        elif ch == ord("y"):
            clipboard.yank(g, g.cc, g.cr, g.cc, g.cr)
        elif ch == ord("p"):
            if not clipboard.empty:
                clipboard.paste(g, undo, g.cc, g.cr)
        elif ch == ord("v"):
            visual_mode(stdscr, g, undo, clipboard)
        elif ch in (ord("e"), curses.KEY_F2):
            cl = g.cell(g.cc, g.cr)
            if cl and cl.type != EMPTY:
                is_label = cl.type == LABEL
                entry(stdscr, g, undo, is_label, 0, initial_text=cl.text)
        elif ch == ord("E"):
            cl = g.cell(g.cc, g.cr)
            if cl and (cl.matrix is not None or (cl.arr is not None and cl.arr)):
                obj_editor(stdscr, g, undo)
        elif ch == ord('"'):
            entry(stdscr, g, undo, True, 0)
        elif ch == ord("=") or ch == ord(".") or (48 <= ch <= 57):
            entry(stdscr, g, undo, False, ch)
        elif 32 <= ch < 127:
            entry(stdscr, g, undo, True, ch)


def _highlight_code(code: str) -> str:
    """Syntax-highlight Python code for terminal output. Falls back to
    plain text when Pygments isn't installed."""
    try:
        from pygments import highlight
        from pygments.formatters import TerminalFormatter
        from pygments.lexers import PythonLexer
    except ImportError:
        return code
    return highlight(code, PythonLexer(), TerminalFormatter())


def startup_trust_prompt(filename: str, info: FileInfo) -> LoadPolicy | None:
    """Plain-terminal trust prompt for file loading at startup (before curses)."""
    print("\033[2J\033[H", end="")  # clear screen, cursor to top
    print(f"Loading: {filename}")
    print(f"  Cells: {info.cell_count} ({info.formula_count} formulas)")
    if info.requires:
        for mod in info.requires:
            cls = classify_module(mod)
            tag = f" [{cls}]" if cls != "safe" else ""
            print(f"  Requires: {mod}{tag}")
    if info.has_code:
        print(f"\n--- Code ({info.code_lines} lines) ---\n")
        print(_highlight_code(info.code_preview))
        print("--- End ---")
    print()

    while True:
        prompt = "  [l]oad code  [s]kip code  [q]uit: "
        resp = input(prompt).strip().lower()
        if resp == "l":
            approved = [m for m in info.requires if classify_module(m) != "blocked"]
            return LoadPolicy(load_code=True, approved_modules=approved)
        elif resp == "s":
            return LoadPolicy.formulas_only()
        elif resp == "q":
            return None


def main() -> None:
    _state._cfg = load_config()
    emit_warnings(_state._cfg)
    configure_sandbox(_state._cfg.sandbox)

    g = Grid()
    g.mode = Mode.HYBRID
    g._apply_mode_libs()
    g.mc = -1
    g.mr = -1
    g.cw = _state._cfg.width if _state._cfg.width else CW_DEFAULT
    if _state._cfg.format and _state._cfg.format.upper() in "LRIGD$%*":
        g.fmt = _state._cfg.format.upper()
    for lib in _state._cfg.libs:
        g.load_lib(lib)
    if _state._cfg.allowed_modules:
        g.load_requires(_state._cfg.allowed_modules)
        g.requires = list(_state._cfg.allowed_modules)

    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(f"Usage: {sys.argv[0]} <sheet.json | sheet.xlsx>", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) > 1:
        fn = sys.argv[1]
        if fn.lower().endswith(".xlsx"):
            # xlsx files have no code block / sandbox surface; load
            # directly via the OpenXLSX-backed C++ extension.
            if g.xlsxload(fn) < 0:
                print(f"Failed to load file: {fn}", file=sys.stderr)
                sys.exit(1)
            g.filename = fn
        else:
            info = inspect_file(fn)
            if info is None:
                print(f"Failed to load file: {fn}", file=sys.stderr)
                sys.exit(1)

            policy = None
            if info.has_code or info.requires:
                if SANDBOX_ENABLED:
                    policy = startup_trust_prompt(fn, info)
                    if policy is None:
                        print("Load cancelled.", file=sys.stderr)
                        sys.exit(0)
                else:
                    policy = LoadPolicy.trust_all(info.requires)

            if g.jsonload(fn, policy=policy) < 0:
                print(f"Failed to load file: {fn}", file=sys.stderr)
                sys.exit(1)
            g.filename = fn

    def _main(stdscr: curses.window) -> None:
        curses.raw()
        curses.curs_set(0)
        init_colors()
        mainloop(stdscr, g)

    curses.wrapper(_main)


__all__ = [
    "GW",
    "Clipboard",
    "SystemClipboard",
    "UndoEntry",
    "UndoManager",
    "_action_for",
    "_build_formula",
    "_dispatch_grid_key",
    "_fmt_val",
    "_paint_label_overflow",
    "_parse_bounds",
    "_parse_cells",
    "_resolved_keymap",
    "_search_grid",
    "cmd_blank",
    "cmd_clear",
    "cmd_csv",
    "cmd_edit",
    "cmd_format",
    "cmd_gformat",
    "cmd_goal",
    "cmd_mode",
    "cmd_name",
    "cmd_names",
    "cmd_open",
    "cmd_opt",
    "cmd_pd",
    "cmd_quit",
    "cmd_save",
    "cmd_savequit",
    "cmd_sheet",
    "cmd_sort",
    "cmd_title",
    "cmd_unname",
    "cmd_view",
    "cmd_width",
    "cmd_xlsx",
    "cmdexec",
    "cmdline",
    "draw",
    "entry",
    "fmt_float",
    "fmtcell",
    "init_colors",
    "main",
    "mainloop",
    "movecmd",
    "name_set",
    "nav",
    "obj_editor",
    "replcmd",
    "search_indicator",
    "search_next",
    "selectrange",
    "trust_prompt",
    "visual_mode",
    "vcols",
    "vrows",
]
