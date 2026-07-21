"""``:``-command implementations and the command dispatcher.

Everything reachable from a colon command lives here: the ``cmd_*`` handlers,
the interactive cursor commands (move / replicate / range-select), the
file-trust prompt, and ``cmdexec`` which dispatches a typed command line.
"""

from __future__ import annotations

import contextlib
import curses
import math
import os
import subprocess
import tempfile
from collections.abc import Callable

from ..engine import (
    EMPTY,
    FORMULA,
    MAXCODE,
    MAXIN,
    MAXNAMES,
    NCOL,
    NROW,
    NUM,
    Cell,
    Grid,
    Mode,
    NamedRange,
    _is_dataframe,
    cellname,
    col_name,
    ref,
)
from ..sandbox import (
    SANDBOX_ENABLED,
    FileInfo,
    LoadPolicy,
    classify_module,
    inspect_file,
)
from . import _state
from .render import CP_CHROME, CP_CURSOR, CP_ERROR, CP_GUTTER, CP_LOCKED, draw
from .solve import cmd_goal, cmd_opt
from .undo import UndoManager
from .widgets import _line_input, pager, prompt_filename, show_error


def _arrow_move(g: Grid, ch: int) -> None:
    """Move the cursor one cell for an arrow keypress, clamped to the grid."""
    if ch == curses.KEY_UP and g.cr > 0:
        g.cr -= 1
    elif ch == curses.KEY_DOWN and g.cr < NROW - 1:
        g.cr += 1
    elif ch == curses.KEY_LEFT and g.cc > 0:
        g.cc -= 1
    elif ch == curses.KEY_RIGHT and g.cc < NCOL - 1:
        g.cc += 1


def movecmd(stdscr: curses.window, g: Grid, undo: UndoManager) -> None:
    origc, origr = g.cc, g.cr
    src = f"{col_name(origc)}{origr + 1}"
    while True:
        draw(stdscr, g, "MOVE", "")
        if g.cc == origc and g.cr == origr:
            stdscr.addnstr(1, 0, f"Source: {src}  (move cursor, Esc cancel)", curses.COLS - 1)
        else:
            stdscr.addnstr(
                1,
                0,
                f"{src}...{col_name(g.cc)}{g.cr + 1}  (Enter confirm, Esc cancel)",
                curses.COLS - 1,
            )
        stdscr.clrtoeol()
        stdscr.refresh()
        k = stdscr.getch()
        if k == 27:
            if g.cc != origc:
                while g.cc < origc:
                    g.swapcol(g.cc, g.cc + 1)
                    g.cc += 1
                while g.cc > origc:
                    g.swapcol(g.cc, g.cc - 1)
                    g.cc -= 1
            else:
                while g.cr < origr:
                    g.swaprow(g.cr, g.cr + 1)
                    g.cr += 1
                while g.cr > origr:
                    g.swaprow(g.cr, g.cr - 1)
                    g.cr -= 1
            g.recalc()
            break
        elif k in (10, 13, curses.KEY_ENTER):
            if g.cc != origc or g.cr != origr:
                g.dirty = 1
            g.recalc()
            break
        elif k == curses.KEY_UP and g.cc == origc:
            lo = g.tr if g.tr > 0 else 0
            if g.cr > lo:
                g.swaprow(g.cr, g.cr - 1)
                g.cr -= 1
        elif k == curses.KEY_DOWN and g.cc == origc:
            if g.cr < NROW - 1:
                g.swaprow(g.cr, g.cr + 1)
                g.cr += 1
        elif k == curses.KEY_LEFT and g.cr == origr:
            lo = g.tc if g.tc > 0 else 0
            if g.cc > lo:
                g.swapcol(g.cc, g.cc - 1)
                g.cc -= 1
        elif k == curses.KEY_RIGHT and g.cr == origr:
            if g.cc < NCOL - 1:
                g.swapcol(g.cc, g.cc + 1)
                g.cc += 1


def selectrange(
    stdscr: curses.window,
    g: Grid,
    prompt: str,
    ac: int,
    ar: int,
) -> tuple[int, int, int, int] | None:
    buf = ""
    typed = False
    g.cc = ac
    g.cr = ar
    while True:
        if typed:
            rng = f"{buf}_"
        else:
            c1 = min(ac, g.cc)
            r1 = min(ar, g.cr)
            c2 = max(ac, g.cc)
            r2 = max(ar, g.cr)
            rng = g.fmtrange(c1, r1, c2, r2)
        draw(stdscr, g, "REPL", "")
        stdscr.addnstr(1, 0, f"{prompt} {rng}", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == 27:
            return None
        if ch in (10, 13, curses.KEY_ENTER):
            if typed:
                r = ref(buf)
                if not r:
                    return None
                n, c1, r1 = r
                c2, r2 = c1, r1
                rest = buf[n:]
                if rest.startswith("..."):
                    r3 = ref(rest[3:])
                    if not r3:
                        return None
                    _, c2, r2 = r3
            else:
                c1 = min(ac, g.cc)
                r1 = min(ar, g.cr)
                c2 = max(ac, g.cc)
                r2 = max(ar, g.cr)
            if c1 > c2:
                c1, c2 = c2, c1
            if r1 > r2:
                r1, r2 = r2, r1
            return (c1, r1, c2, r2)
        elif ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT):
            typed = False
            buf = ""
            _arrow_move(g, ch)
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            typed = True
            buf = buf[:-1]
        elif 32 <= ch < 127:
            typed = True
            buf += chr(ch).upper()


def replcmd(stdscr: curses.window, g: Grid, undo: UndoManager) -> None:
    origc, origr = g.cc, g.cr
    result = selectrange(stdscr, g, "Source:", origc, origr)
    if not result:
        return
    sc1, sr1, sc2, sr2 = result
    sw = sc2 - sc1 + 1
    sh = sr2 - sr1 + 1
    srcstr = g.fmtrange(sc1, sr1, sc2, sr2)
    g.cc, g.cr = sc1, sr1

    buf = ""
    typed = False
    while True:
        tgt = f"{buf}_" if typed else g.fmtrange(g.cc, g.cr, g.cc + sw - 1, g.cr + sh - 1)
        draw(stdscr, g, "REPL", "")
        stdscr.addnstr(1, 0, f"{srcstr} to: {tgt}", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == 27:
            return
        if ch in (10, 13, curses.KEY_ENTER):
            if typed:
                r = ref(buf)
                if not r:
                    return
                _, tc1, tr1 = r
            else:
                tc1, tr1 = g.cc, g.cr
            for ri in range(sh):
                for ci in range(sw):
                    g.replicatecell(sc1 + ci, sr1 + ri, tc1 + ci, tr1 + ri)
            g.recalc()
            g.dirty = 1
            return
        elif ch in (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT):
            typed = False
            buf = ""
            _arrow_move(g, ch)
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            typed = True
            buf = buf[:-1]
        elif len(buf) < MAXIN - 1 and 32 <= ch < 127:
            typed = True
            buf += chr(ch).upper()


def cmd_quit(stdscr: curses.window, g: Grid) -> bool:
    if g.dirty:
        stdscr.addnstr(curses.LINES - 1, 0, "Unsaved changes. Quit anyway? (y/N)", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        ch = stdscr.getch()
        return ch in (ord("y"), ord("Y"))
    return True


def _do_save(stdscr: curses.window, g: Grid, args: str) -> bool:
    """Shared save logic. Returns True on success, False on failure/cancel."""
    fn = args.strip() if args.strip() else g.filename
    if not fn:
        fn = prompt_filename(stdscr, "Save as: ")
        if not fn:
            return False
    if g.jsonsave(fn) == 0:
        g.filename = fn
        g.dirty = 0
        return True
    show_error(stdscr, f"Failed to save: {fn}. Press any key.")
    return False


def cmd_save(stdscr: curses.window, g: Grid, args: str) -> bool:
    _do_save(stdscr, g, args)
    return False


def cmd_savequit(stdscr: curses.window, g: Grid, args: str) -> bool:
    return _do_save(stdscr, g, args)


def cmd_edit(stdscr: curses.window, g: Grid) -> bool:
    editor = os.environ.get("EDITOR") or _state._cfg.editor or "vi"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        if g.code:
            f.write(g.code)
        tmppath = f.name
    try:
        curses.def_prog_mode()
        curses.endwin()
        subprocess.run([editor, tmppath], check=False)
        curses.reset_prog_mode()
        stdscr.refresh()
        with open(tmppath) as f:
            content = f.read()
        g.code = content[:MAXCODE]
        g.dirty = 1
        g.recalc()
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmppath)
    return False


def _view_code_block(stdscr: curses.window, code: str) -> None:
    """Pager for the trust-prompt code preview."""
    lines = code.splitlines() or [""]
    pager(stdscr, f"Code block ({len(lines)} lines):", lines)


def trust_prompt(stdscr: curses.window, filename: str, info: FileInfo) -> LoadPolicy | None:
    """Curses-based trust prompt for loading files with code or requires.

    Returns a LoadPolicy, or None if the user cancels.
    """
    while True:
        stdscr.erase()
        stdscr.attron(curses.A_BOLD)
        stdscr.addnstr(0, 0, f"Loading: {os.path.basename(filename)}", curses.COLS - 1)
        stdscr.attroff(curses.A_BOLD)

        y = 2
        cells_str = f"  Cells: {info.cell_count} ({info.formula_count} formulas)"
        stdscr.addnstr(y, 0, cells_str, curses.COLS - 1)
        y += 1

        if info.requires:
            mods = ", ".join(info.requires)
            stdscr.addnstr(y, 0, f"  Requires: {mods}", curses.COLS - 1)
            y += 1
            if info.blocked_modules:
                stdscr.attron(curses.color_pair(CP_ERROR))
                blocked = f"  Blocked:  {', '.join(info.blocked_modules)}"
                stdscr.addnstr(y, 0, blocked, curses.COLS - 1)
                stdscr.attroff(curses.color_pair(CP_ERROR))
                y += 1
            if info.side_effect_modules:
                stdscr.attron(curses.color_pair(CP_LOCKED))
                io_mods = f"  I/O:      {', '.join(info.side_effect_modules)}"
                stdscr.addnstr(y, 0, io_mods, curses.COLS - 1)
                stdscr.attroff(curses.color_pair(CP_LOCKED))
                y += 1

        if info.has_code:
            stdscr.addnstr(y, 0, f"  Code:     {info.code_lines} lines", curses.COLS - 1)
            y += 1

        y += 1
        prompt = "[a]pprove  [f]ormulas only"
        if info.has_code:
            prompt += "  [v]iew code"
        prompt += "  [c]ancel"
        stdscr.addnstr(y, 0, f"  {prompt}", curses.COLS - 1)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch == ord("a"):
            approved = [m for m in info.requires if classify_module(m) != "blocked"]
            return LoadPolicy(load_code=True, approved_modules=approved)
        elif ch == ord("f"):
            return LoadPolicy.formulas_only()
        elif ch == ord("v") and info.has_code:
            _view_code_block(stdscr, info.code_preview)
            continue
        elif ch == ord("c") or ch == 27:
            return None


def cmd_open(stdscr: curses.window, g: Grid, args: str) -> bool:
    fn = args.strip() if args.strip() else None
    if not fn:
        fn = prompt_filename(stdscr, "Open: ", g.filename)
        if not fn:
            return False

    info = inspect_file(fn)
    if info is None:
        show_error(stdscr, f"Failed to read: {fn}. Press any key.")
        return False

    policy = None
    if info.has_code or info.requires:
        if SANDBOX_ENABLED:
            policy = trust_prompt(stdscr, fn, info)
            if policy is None:
                return False
        else:
            policy = LoadPolicy.trust_all(info.requires)

    g.clear_all()
    g.names = []
    g.code = ""
    if g.jsonload(fn, policy=policy) == 0:
        g.filename = fn
        g.dirty = 0
    else:
        show_error(stdscr, f"Failed to load: {fn}. Press any key.")
    return False


def cmd_blank(
    g: Grid,
    undo: UndoManager,
    sel: tuple[int, int, int, int] | None = None,
) -> bool:
    if sel:
        c1, r1, c2, r2 = sel
        undo.save_region(g, c1, r1, c2, r2)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                g.setcell(c, r, "")
    else:
        undo.save_cell(g, g.cc, g.cr)
        g.setcell(g.cc, g.cr, "")
    g.recalc()
    return False


def cmd_clear(stdscr: curses.window, g: Grid, undo: UndoManager) -> bool:
    stdscr.addnstr(curses.LINES - 1, 0, "Clear entire sheet? (y/N)", curses.COLS - 1)
    stdscr.clrtoeol()
    stdscr.refresh()
    ch = stdscr.getch()
    if ch in (ord("y"), ord("Y")):
        undo.save_grid(g)
        g.clear_all()
        g.dirty = 1
    return False


def _apply_fmt_to_range(
    g: Grid,
    undo: UndoManager,
    c1: int,
    r1: int,
    c2: int,
    r2: int,
    fmt_arg: str,
) -> bool:
    """Apply a format string to all non-empty cells in a range.

    fmt_arg is a resolved format: a style string like "bui", a single
    format char like "$", or a Python format spec like ",.2f".
    Returns True if applied, False if invalid.
    """
    all_style = all(ch in "bui" for ch in fmt_arg)
    if all_style:
        undo.save_region(g, c1, r1, c2, r2)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cl = g.cell(c, r)
                if not cl or cl.type == EMPTY:
                    continue
                for ch in fmt_arg:
                    if ch == "b":
                        cl.bold = 1 - cl.bold
                    elif ch == "u":
                        cl.underline = 1 - cl.underline
                    elif ch == "i":
                        cl.italic = 1 - cl.italic
        return True

    if len(fmt_arg) == 1 and fmt_arg.upper() in "LRIGD$%*":
        undo.save_region(g, c1, r1, c2, r2)
        fmt_ch = fmt_arg.upper()
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cl = g.cell(c, r)
                if not cl or cl.type == EMPTY:
                    continue
                cl.fmt = fmt_ch
                cl.fmtstr = ""
        return True

    # Python format spec
    undo.save_region(g, c1, r1, c2, r2)
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            cl = g.cell(c, r)
            if not cl or cl.type == EMPTY:
                continue
            cl.fmtstr = fmt_arg[:31]
            cl.fmt = ""
    return True


_FORMAT_OPTIONS = [
    ("b", "Bold", "Toggle bold text"),
    ("u", "Underline", "Toggle underline text"),
    ("i", "Italic", "Toggle italic text"),
    ("$", "Dollar", "Dollar sign, 2 decimal places (99.50)"),
    ("%", "Percent", "Percentage, 2 decimal places (25.00%)"),
    ("I", "Integer", "Truncate to whole number (1234)"),
    (",", "Comma", "Comma thousands, no decimals (1,234,567)"),
    ("*", "Bar chart", "Asterisks proportional to value"),
    ("L", "Left align", "Left-align cell content"),
    ("R", "Right align", "Right-align cell content"),
    ("G", "General", "Default number format"),
    ("D", "Use global", "Use the global default format"),
]


def _resolve_fmt(stdscr: curses.window, args: str) -> str | None:
    """Resolve a format argument, prompting interactively if empty.

    Returns the format string, or None if cancelled.
    """
    if args:
        return args

    sel_idx = 0
    while True:
        stdscr.erase()
        stdscr.attron(curses.A_BOLD)
        stdscr.addnstr(0, 0, " Format", curses.COLS - 1)
        stdscr.attroff(curses.A_BOLD)

        for idx, (key, name, desc) in enumerate(_FORMAT_OPTIONS):
            y = idx + 2
            if y >= curses.LINES - 2:
                break
            if idx == sel_idx:
                stdscr.attron(curses.color_pair(CP_CURSOR) | curses.A_BOLD)
            label = f"  {key:>2}  {name:<14} {desc}"
            stdscr.addnstr(y, 0, label, curses.COLS - 1)
            if idx == sel_idx:
                stdscr.attroff(curses.color_pair(CP_CURSOR) | curses.A_BOLD)

        footer_y = min(len(_FORMAT_OPTIONS) + 3, curses.LINES - 1)
        stdscr.addnstr(
            footer_y,
            0,
            "  Enter: apply  Esc: cancel  or type a Python spec (e.g. ,.2f)",
            curses.COLS - 1,
        )
        stdscr.refresh()

        ch = stdscr.getch()
        if ch == 27:
            return None
        elif ch == curses.KEY_UP and sel_idx > 0:
            sel_idx -= 1
        elif ch == curses.KEY_DOWN and sel_idx < len(_FORMAT_OPTIONS) - 1:
            sel_idx += 1
        elif ch in (10, 13, curses.KEY_ENTER):
            return _FORMAT_OPTIONS[sel_idx][0]
        elif 32 <= ch < 127:
            # Direct key press -- check if it matches a format option
            pressed = chr(ch)
            for key, _, _ in _FORMAT_OPTIONS:
                if pressed == key or pressed == key.lower():
                    return key
            # Otherwise treat the keypress as the start of a Python format spec.
            return _line_input(
                stdscr,
                curses.LINES - 1,
                prefix="  Format spec: ",
                initial=pressed,
                maxlen=31,
                allow_empty=False,
            )
    return None


def cmd_format(
    stdscr: curses.window,
    g: Grid,
    undo: UndoManager,
    args: str,
    sel: tuple[int, int, int, int] | None = None,
) -> bool:
    if sel:
        c1, r1, c2, r2 = sel
    else:
        cl = g.cell(g.cc, g.cr)
        if not cl or cl.type == EMPTY:
            return False
        c1, r1, c2, r2 = g.cc, g.cr, g.cc, g.cr

    fmt = _resolve_fmt(stdscr, args)
    if fmt is None:
        return False

    if not _apply_fmt_to_range(g, undo, c1, r1, c2, r2, fmt):
        show_error(
            stdscr,
            "Invalid format. Use: b u i L R I G D $ % * or Python spec",
        )
    return False


def cmd_gformat(stdscr: curses.window, g: Grid, args: str) -> bool:
    if args:
        ch = args[0].upper()
    else:
        stdscr.addnstr(curses.LINES - 1, 0, "Global format: L R I G D $ % *", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        k = stdscr.getch()
        ch = chr(k).upper() if 32 <= k < 127 else ""
    if ch in "LRIGD$%*":
        g.fmt = ch
    else:
        show_error(stdscr, "Invalid format. Use: L R I G D $ % *")
    return False


def cmd_width(stdscr: curses.window, g: Grid, args: str) -> bool:
    s = args.strip() if args else ""
    if not s:
        result = _line_input(
            stdscr,
            curses.LINES - 1,
            prefix="Column width (4-40): ",
            accept=lambda ch, buf: ch.isdigit(),
            allow_empty=False,
        )
        if result is None:
            return False
        s = result
    try:
        w = int(s)
    except ValueError:
        show_error(stdscr, "Invalid width. Use 4-40.")
        return False
    if 4 <= w <= 40:
        g.cw = w
    else:
        show_error(stdscr, "Invalid width. Use 4-40.")
    return False


def name_set(g: Grid, name: str, c1: int, r1: int, c2: int, r2: int) -> None:
    idx = -1
    for i, nr in enumerate(g.names):
        if nr.name == name:
            idx = i
            break
    if idx < 0 and len(g.names) < MAXNAMES:
        g.names.append(NamedRange(name, c1, r1, c2, r2))
    elif idx >= 0:
        g.names[idx].c1 = c1
        g.names[idx].r1 = r1
        g.names[idx].c2 = c2
        g.names[idx].r2 = r2
    g.dirty = 1
    g.recalc()


def cmd_name(stdscr: curses.window, g: Grid, args: str) -> bool:
    nbuf = ""
    if args:
        parts = args.split(None, 1)
        nbuf = parts[0]
        if len(parts) > 1:
            rest = parts[1]
            r = ref(rest)
            if r:
                n, c1, r1 = r
                c2, r2 = c1, r1
                remainder = rest[n:]
                if remainder.startswith(":"):
                    r3 = ref(remainder[1:])
                    if r3:
                        _, c2, r2 = r3
                name_set(g, nbuf, c1, r1, c2, r2)
                return False
    else:
        entered = _line_input(
            stdscr,
            curses.LINES - 1,
            prefix="Name: ",
            accept=lambda ch, buf: ch.isalpha() or (bool(buf) and (ch.isalnum() or ch == "_")),
            allow_empty=False,
        )
        if entered is None:
            return False
        nbuf = entered

    result = selectrange(stdscr, g, "Range:", g.cc, g.cr)
    if result:
        c1, r1, c2, r2 = result
        name_set(g, nbuf, c1, r1, c2, r2)
    return False


def cmd_names(stdscr: curses.window, g: Grid) -> bool:
    stdscr.erase()
    stdscr.attron(curses.A_BOLD)
    stdscr.addnstr(0, 0, f"Named Ranges ({len(g.names)})", curses.COLS - 1)
    stdscr.attroff(curses.A_BOLD)
    for i, nr in enumerate(g.names):
        a = cellname(nr.c1, nr.r1)
        stdscr.addnstr(i + 1, 0, f"  {nr.name} = {a}:{col_name(nr.c2)}{nr.r2 + 1}", curses.COLS - 1)
    stdscr.addnstr(len(g.names) + 2, 0, "Press any key.", curses.COLS - 1)
    stdscr.refresh()
    stdscr.getch()
    return False


def cmd_unname(stdscr: curses.window, g: Grid, args: str) -> bool:
    nbuf = args.strip() if args else ""
    if not nbuf:
        entered = _line_input(stdscr, curses.LINES - 1, prefix="Remove name: ", allow_empty=False)
        if entered is None:
            return False
        nbuf = entered

    for i, nr in enumerate(g.names):
        if nr.name == nbuf:
            g.names.pop(i)
            g.dirty = 1
            break
    return False


def cmd_view(stdscr: curses.window, g: Grid) -> bool:
    """View the DataFrame or matrix in the current cell as a scrollable table."""
    cl = g.cell(g.cc, g.cr)
    if not cl or cl.matrix is None:
        show_error(stdscr, "No DataFrame/matrix in current cell")
        return False

    matrix = cl.matrix
    is_df = _is_dataframe(matrix)

    if is_df:
        columns = [str(c) for c in matrix.columns]
        nrows, ncols = matrix.shape
        rows: list[list[str]] = []
        for r in range(nrows):
            row: list[str] = []
            for c in range(ncols):
                val = matrix.iloc[r, c]
                try:
                    import pandas as pd  # noqa: I001

                    if pd.isna(val):
                        row.append("")
                        continue
                except (TypeError, ValueError):
                    pass
                if isinstance(val, float):
                    if val == int(val) and abs(val) < 1e15:
                        row.append(str(int(val)))
                    else:
                        row.append(f"{val:g}")
                else:
                    row.append(str(val))
            rows.append(row)
    else:
        # ndarray
        import numpy as _np  # noqa: I001

        if matrix.ndim == 1:
            columns = ["[0]"]
            nrows = matrix.shape[0]
            rows = []
            for r in range(nrows):
                v = matrix[r]
                rows.append([f"{v:g}" if isinstance(v, (int, float)) else str(v)])
        elif matrix.ndim == 2:
            nrows, ncols = matrix.shape
            columns = [f"[{c}]" for c in range(ncols)]
            rows = []
            numtypes = (int, float, _np.integer, _np.floating)
            for r in range(nrows):
                cells: list[str] = []
                for c in range(ncols):
                    v = matrix[r, c]
                    cells.append(f"{v:g}" if isinstance(v, numtypes) else str(v))
                rows.append(cells)
        else:
            show_error(stdscr, f"Cannot display {matrix.ndim}D array as table")
            return False

    # Compute column widths
    col_widths = [len(c) for c in columns]
    for row in rows:
        for i, val in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(val))

    # Cap column widths
    col_widths = [min(w, 20) for w in col_widths]
    row_num_width = len(str(len(rows)))

    # Scrollable view
    scroll_r = 0
    scroll_c = 0

    while True:
        stdscr.erase()

        # Title
        label = "DataFrame" if is_df else "ndarray"
        title = f" {label} ({len(rows)}x{len(columns)})"
        if cl.type == FORMULA:
            title += f"  {cl.text}"
        stdscr.attron(curses.A_BOLD)
        stdscr.addnstr(0, 0, title, curses.COLS - 1)
        stdscr.attroff(curses.A_BOLD)

        # Determine visible columns
        vis_cols: list[int] = []
        x = row_num_width + 2
        for ci in range(scroll_c, len(columns)):
            w = col_widths[ci] + 2
            if x + w > curses.COLS:
                break
            vis_cols.append(ci)
            x += w

        # Column headers
        stdscr.attron(curses.color_pair(CP_CHROME) | curses.A_BOLD)
        hdr = " " * (row_num_width + 2)
        for ci in vis_cols:
            hdr += f"{columns[ci]:>{col_widths[ci]}}  "
        stdscr.addnstr(2, 0, hdr, curses.COLS - 1)
        stdscr.attroff(curses.color_pair(CP_CHROME) | curses.A_BOLD)

        # Data rows
        max_vis_rows = curses.LINES - 5
        for ri in range(max_vis_rows):
            data_r = scroll_r + ri
            if data_r >= len(rows):
                break
            y = 3 + ri
            # Row number
            stdscr.attron(curses.color_pair(CP_GUTTER))
            stdscr.addnstr(y, 0, f"{data_r:>{row_num_width}}  ", row_num_width + 2)
            stdscr.attroff(curses.color_pair(CP_GUTTER))
            # Cell values
            line = ""
            for ci in vis_cols:
                val = rows[data_r][ci] if ci < len(rows[data_r]) else ""
                line += f"{val:>{col_widths[ci]}}  "
            stdscr.addnstr(y, row_num_width + 2, line, curses.COLS - row_num_width - 2)

        # Footer
        footer_y = curses.LINES - 1
        pos = f"rows {scroll_r + 1}-{min(scroll_r + max_vis_rows, len(rows))}/{len(rows)}"
        footer = f" {pos}  Arrows: scroll  q/Esc: close"
        stdscr.attron(curses.color_pair(CP_CHROME))
        stdscr.addnstr(footer_y, 0, footer, curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.attroff(curses.color_pair(CP_CHROME))

        stdscr.refresh()
        ch = stdscr.getch()

        if ch in (27, ord("q")):
            break
        elif ch == curses.KEY_DOWN:
            if scroll_r + max_vis_rows < len(rows):
                scroll_r += 1
        elif ch == curses.KEY_UP and scroll_r > 0:
            scroll_r -= 1
        elif ch == curses.KEY_RIGHT:
            if scroll_c + 1 < len(columns):
                scroll_c += 1
        elif ch == curses.KEY_LEFT and scroll_c > 0:
            scroll_c -= 1
        elif ch == curses.KEY_NPAGE:
            scroll_r = min(scroll_r + max_vis_rows, max(0, len(rows) - max_vis_rows))
        elif ch == curses.KEY_PPAGE:
            scroll_r = max(0, scroll_r - max_vis_rows)
        elif ch == curses.KEY_HOME:
            scroll_r = 0
            scroll_c = 0
        elif ch == curses.KEY_END:
            scroll_r = max(0, len(rows) - max_vis_rows)

    return False


def cmd_mode(stdscr: curses.window, g: Grid, args: str) -> bool:
    arg = args.strip()
    if not arg:
        show_error(stdscr, f"mode: {g.mode.name.lower()} ({int(g.mode)})")
        return False
    parsed = Mode.parse(arg)
    if parsed is None:
        show_error(stdscr, "Invalid mode. Use: 1|excel, 2|hybrid, 3|python")
        return False
    if parsed == g.mode:
        return False
    errors = g.validate_for_mode(parsed)
    if errors:
        show_error(
            stdscr,
            f"Cannot switch to {parsed.name}: {len(errors)} issue(s). First: {errors[0]}",
        )
        return False
    g.mode = parsed
    g._apply_mode_libs()
    g.recalc()
    g.dirty = 1
    return False


def cmd_sheet(stdscr: curses.window, g: Grid, args: str) -> bool:
    """Multi-sheet management.

    Subcommands:
      :sheet                -> show all sheets (active marked with *)
      :sheet list           -> same as bare :sheet
      :sheet add NAME       -> append a new sheet (does not switch)
      :sheet del NAME       -> remove sheet (refuses last sheet)
      :sheet rename OLD NEW -> rename sheet (rewrites formula text)
      :sheet move NAME N    -> reorder sheet to zero-based index N
      :sheet NAME           -> switch active sheet by name
      :sheet N              -> switch active sheet by zero-based index
    """
    arg = args.strip()
    if not arg or arg == "list":
        names = ", ".join(f"*{s.name}" if i == g.active else s.name for i, s in enumerate(g.sheets))
        show_error(stdscr, f"sheets: {names}")
        return False

    parts = arg.split(None, 2)
    sub = parts[0].lower()

    if sub == "add":
        if len(parts) < 2:
            show_error(stdscr, "usage: :sheet add NAME")
            return False
        try:
            g.add_sheet(parts[1])
        except ValueError as exc:
            show_error(stdscr, f"sheet add: {exc}")
            return False
        g.dirty = 1
        return False

    if sub in ("del", "delete", "remove", "rm"):
        if len(parts) < 2:
            show_error(stdscr, "usage: :sheet del NAME")
            return False
        try:
            g.remove_sheet(parts[1])
        except (ValueError, KeyError) as exc:
            show_error(stdscr, f"sheet del: {exc}")
            return False
        g.recalc()
        g.dirty = 1
        return False

    if sub == "move":
        if len(parts) < 3:
            show_error(stdscr, "usage: :sheet move NAME INDEX")
            return False
        name, idx_str = parts[1], parts[2]
        try:
            idx = int(idx_str)
        except ValueError:
            show_error(stdscr, f"sheet move: bad index {idx_str!r}")
            return False
        try:
            g.move_sheet(name, idx)
        except (IndexError, KeyError) as exc:
            show_error(stdscr, f"sheet move: {exc}")
            return False
        g.dirty = 1
        return False

    if sub == "rename":
        if len(parts) < 3:
            show_error(stdscr, "usage: :sheet rename OLD NEW")
            return False
        old, new = parts[1], parts[2]
        try:
            g.rename_sheet(old, new)
        except (ValueError, KeyError) as exc:
            show_error(stdscr, f"sheet rename: {exc}")
            return False
        # Sheet identity changed -- dep graph keys carry sheet names,
        # so any subscriber edges referencing `old` are now stale. The
        # cheapest correct fix is a full rebuild.
        g._dep_graph_built = False
        g._rebuild_dep_graph()
        g.recalc()
        g.dirty = 1
        return False

    # Bare arg: switch active sheet by index (numeric) or name.
    target: int | str
    try:
        target = int(arg)
    except ValueError:
        target = arg
    try:
        g.set_active(target)
    except (KeyError, IndexError):
        show_error(stdscr, f"sheet: no such sheet {arg!r}")
    return False


def cmd_title(g: Grid, args: str) -> bool:
    ch = args[0].upper() if args else ""
    if ch == "V":
        g.tc = g.cc + 1
        g.tr = 0
        g.cc += 1
    elif ch == "H":
        g.tr = g.cr + 1
        g.tc = 0
        g.cr += 1
    elif ch == "B":
        g.tc = g.cc + 1
        g.tr = g.cr + 1
        g.cc += 1
        g.cr += 1
    elif ch == "N":
        g.tc = g.tr = 0
        g.vc = g.vr = 0
    return False


def cmd_sort(
    stdscr: curses.window,
    g: Grid,
    undo: UndoManager,
    args: str,
    sel: tuple[int, int, int, int] | None = None,
) -> bool:
    """Sort rows by a column. Usage: :sort [col] [desc]"""
    parts = args.strip().split()

    if sel:
        c1, r1, c2, r2 = sel
    else:
        # Find data extent
        maxr = -1
        maxc = -1
        for (c, r), cl in g._cells.items():
            if cl.type != EMPTY:
                if r > maxr:
                    maxr = r
                if c > maxc:
                    maxc = c
        if maxr < 0:
            return False
        c1, r1, c2, r2 = 0, 0, maxc, maxr

    # Determine sort column
    if parts:
        col_str = parts[0].upper()
        r_parsed = ref(col_str + "1")
        if r_parsed:
            sort_col = r_parsed[1]
        else:
            show_error(stdscr, f"Invalid column: {parts[0]}")
            return False
    else:
        sort_col = sel[0] if sel else g.cc

    descending = len(parts) > 1 and parts[1].lower() in ("desc", "d", "reverse", "r")

    if sort_col < c1 or sort_col > c2:
        show_error(stdscr, f"Column {col_name(sort_col)} is outside the range")
        return False

    undo.save_grid(g)

    # Collect rows as lists of cell snapshots
    row_data: list[tuple[float, str, int, list[tuple[int, Cell | None]]]] = []
    for r in range(r1, r2 + 1):
        sort_cl = g.cell(sort_col, r)
        if sort_cl and sort_cl.type in (NUM, FORMULA):
            sort_val = sort_cl.val if not math.isnan(sort_cl.val) else float("inf")
        else:
            sort_val = float("inf")
        sort_text = sort_cl.text if sort_cl and sort_cl.type != EMPTY else ""
        cells_in_row: list[tuple[int, Cell | None]] = []
        for c in range(c1, c2 + 1):
            maybe = g.cell(c, r)
            cells_in_row.append((c, maybe.snapshot() if maybe else None))
        row_data.append((sort_val, sort_text, r, cells_in_row))

    # Sort: numbers first (by value), then labels (alphabetically), then empties
    def sort_key(
        item: tuple[float, str, int, list[tuple[int, Cell | None]]],
    ) -> tuple[int, float, str]:
        val, text, _, _ = item
        if val < float("inf"):
            return (0, val, "")
        if text:
            return (1, 0.0, text.lower())
        return (2, 0.0, "")

    row_data.sort(key=sort_key, reverse=descending)

    # Write sorted rows back
    for new_r_offset, (_, _, _, cells_in_row) in enumerate(row_data):
        target_r = r1 + new_r_offset
        for c, snap in cells_in_row:
            if snap is None:
                g._cells.pop((c, target_r), None)
            else:
                dst = g._ensure_cell(c, target_r)
                dst.copy_from(snap)
    g.recalc()
    g.dirty = 1
    return False


def _io_command(
    stdscr: curses.window,
    g: Grid,
    undo: UndoManager,
    args: str,
    *,
    label: str,
    usage: str,
    save_fn: Callable[[str], int],
    load_fn: Callable[[str], int],
    save_ext: str,
    clear_on_load: bool,
    dirty_on_load: bool,
) -> bool:
    """Shared save/load dispatch for the :csv, :xlsx and :pd commands.

    ``save_fn``/``load_fn`` are the grid's serializers (e.g. ``g.csvsave``).
    The three commands differ only in: the default save extension, whether a
    load clears the grid first, and whether a load marks the grid dirty --
    captured by ``save_ext`` / ``clear_on_load`` / ``dirty_on_load``.
    """
    parts = args.strip().split(None, 1)
    if not parts:
        show_error(stdscr, usage)
        return False
    sub = parts[0].lower()
    farg = parts[1].strip() if len(parts) > 1 else ""

    if sub in ("save", "export", "w"):
        fn = farg if farg else None
        if not fn:
            dflt = g.filename.rsplit(".", 1)[0] + save_ext if g.filename else None
            fn = prompt_filename(stdscr, f"{label} save as: ", dflt)
            if not fn:
                return False
        if save_fn(fn) == 0:
            show_error(stdscr, f"Exported to {fn}")
        else:
            show_error(stdscr, f"Failed to export: {fn}. Press any key.")
        return False

    if sub in ("load", "import", "r"):
        fn = farg if farg else None
        if not fn:
            fn = prompt_filename(stdscr, f"{label} load: ")
            if not fn:
                return False
        undo.save_grid(g)
        if clear_on_load:
            g.clear_all()
        if load_fn(fn) == 0:
            g.recalc()
            if dirty_on_load:
                g.dirty = 1
        else:
            show_error(stdscr, f"Failed to load: {fn}. Press any key.")
        return False

    show_error(stdscr, usage)
    return False


def cmd_pd(stdscr: curses.window, g: Grid, undo: UndoManager, args: str) -> bool:
    """Pandas import/export. Usage: :pd load [file] | :pd save [file]"""
    return _io_command(
        stdscr,
        g,
        undo,
        args,
        label="pd",
        usage="Usage: pd load [file] | pd save [file]",
        save_fn=g.pdsave,
        load_fn=g.pdload,
        save_ext=".csv",
        clear_on_load=True,
        dirty_on_load=True,
    )


def cmd_xlsx(stdscr: curses.window, g: Grid, undo: UndoManager, args: str) -> bool:
    return _io_command(
        stdscr,
        g,
        undo,
        args,
        label="xlsx",
        usage="Usage: xlsx save [file] | xlsx load [file]",
        save_fn=g.xlsxsave,
        load_fn=g.xlsxload,
        save_ext=".xlsx",
        clear_on_load=False,
        dirty_on_load=False,
    )


def cmd_csv(stdscr: curses.window, g: Grid, undo: UndoManager, args: str) -> bool:
    return _io_command(
        stdscr,
        g,
        undo,
        args,
        label="CSV",
        usage="Usage: csv save [file] | csv load [file]",
        save_fn=g.csvsave,
        load_fn=g.csvload,
        save_ext=".csv",
        clear_on_load=True,
        dirty_on_load=False,
    )


def cmdexec(
    stdscr: curses.window,
    g: Grid,
    undo: UndoManager,
    text: str,
    sel: tuple[int, int, int, int] | None = None,
) -> bool:
    text = text.strip()
    if not text:
        return False

    parts = text.split(None, 1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd in ("q", "quit"):
        return cmd_quit(stdscr, g)
    if cmd == "q!":
        return True
    if cmd in ("w", "save"):
        return cmd_save(stdscr, g, args)
    if cmd == "wq":
        return cmd_savequit(stdscr, g, args)
    if cmd in ("e", "edit"):
        return cmd_edit(stdscr, g)
    if cmd in ("o", "open"):
        return cmd_open(stdscr, g, args)
    if cmd in ("b", "blank"):
        return cmd_blank(g, undo, sel=sel)
    if cmd == "clear":
        return cmd_clear(stdscr, g, undo)
    if cmd in ("f", "format"):
        return cmd_format(stdscr, g, undo, args, sel=sel)
    if cmd in ("gf", "gformat"):
        return cmd_gformat(stdscr, g, args)
    if cmd == "width":
        return cmd_width(stdscr, g, args)
    if cmd in ("view", "v"):
        return cmd_view(stdscr, g)
    if cmd == "csv":
        return cmd_csv(stdscr, g, undo, args)
    if cmd == "xlsx":
        return cmd_xlsx(stdscr, g, undo, args)
    if cmd == "pd":
        return cmd_pd(stdscr, g, undo, args)
    if cmd == "sort":
        return cmd_sort(stdscr, g, undo, args, sel=sel)
    if cmd == "opt":
        return cmd_opt(stdscr, g, undo, args)
    if cmd == "goal":
        return cmd_goal(stdscr, g, undo, args)
    if cmd in ("dr", "delrow"):
        undo.save_grid(g)
        if sel:
            for r in range(sel[3], sel[1] - 1, -1):
                g.deleterow(r)
        else:
            g.deleterow(g.cr)
        g.recalc()
        return False
    if cmd in ("dc", "delcol"):
        undo.save_grid(g)
        if sel:
            for c in range(sel[2], sel[0] - 1, -1):
                g.deletecol(c)
        else:
            g.deletecol(g.cc)
        g.recalc()
        return False
    if cmd in ("ir", "insrow"):
        undo.save_grid(g)
        g.insertrow(g.cr)
        g.recalc()
        return False
    if cmd in ("ic", "inscol"):
        undo.save_grid(g)
        g.insertcol(g.cc)
        g.recalc()
        return False
    if cmd in ("m", "move"):
        undo.save_grid(g)
        movecmd(stdscr, g, undo)
        return False
    if cmd in ("r", "replicate"):
        undo.save_grid(g)
        replcmd(stdscr, g, undo)
        return False
    if cmd == "name":
        return cmd_name(stdscr, g, args)
    if cmd == "names":
        return cmd_names(stdscr, g)
    if cmd == "unname":
        return cmd_unname(stdscr, g, args)
    if cmd == "tv":
        return cmd_title(g, "v")
    if cmd == "th":
        return cmd_title(g, "h")
    if cmd == "tb":
        return cmd_title(g, "b")
    if cmd == "tn":
        return cmd_title(g, "n")
    if cmd == "title":
        return cmd_title(g, args)
    if cmd == "mode":
        return cmd_mode(stdscr, g, args)
    if cmd in ("sheet", "s"):
        return cmd_sheet(stdscr, g, args)

    stdscr.addnstr(curses.LINES - 1, 0, f"Unknown command: {cmd} (press any key)", curses.COLS - 1)
    stdscr.clrtoeol()
    stdscr.refresh()
    stdscr.getch()
    return False
