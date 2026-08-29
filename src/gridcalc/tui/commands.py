"""``:``-command implementations and the command dispatcher.

Everything reachable from a colon command lives here: the ``cmd_*`` handlers,
the interactive cursor commands (move / replicate / range-select), the
file-trust prompt, and ``cmdexec`` which dispatches a typed command line.
"""

from __future__ import annotations

import contextlib
import curses
import os
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

from .. import commands as shared
from ..engine import (
    FORMULA,
    MAXCODE,
    MAXIN,
    NCOL,
    NROW,
    Grid,
    _is_dataframe,
    col_name,
    ref,
)
from ..sandbox import (
    SANDBOX_ENABLED,
    FileInfo,
    LoadPolicy,
    _parse_requirement,
    classify_module,
    inspect_file,
)
from . import _state
from .render import CP_CHROME, CP_CURSOR, CP_ERROR, CP_GUTTER, CP_LOCKED, draw
from .solve import cmd_goal, cmd_opt
from .undo import UndoManager
from .widgets import _line_input, pager, prompt_filename, select_from_list, show_error


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
            if info.unknown_modules:
                # Shown on its own line because "not on any list" is a risk
                # statement, not the absence of one: an unclassified module
                # is unreviewed, not known-safe.
                stdscr.attron(curses.color_pair(CP_LOCKED))
                unk = f"  Unknown:  {', '.join(info.unknown_modules)}"
                stdscr.addnstr(y, 0, unk, curses.COLS - 1)
                stdscr.attroff(curses.color_pair(CP_LOCKED))
                y += 1

        if info.has_code:
            stdscr.addnstr(y, 0, f"  Code:     {info.code_lines} lines", curses.COLS - 1)
            y += 1

        y += 1
        prompt = "[a]pprove  [f]ormulas only"
        if info.unknown_modules:
            prompt += "  [u] approve incl. unknown"
        if info.has_code:
            prompt += "  [v]iew code"
        prompt += "  [c]ancel"
        stdscr.addnstr(y, 0, f"  {prompt}", curses.COLS - 1)
        stdscr.refresh()

        ch = stdscr.getch()
        if ch == ord("a") or (ch == ord("u") and info.unknown_modules):
            # `a` approves what the lists vouch for. Loading an unclassified
            # module is a second, deliberate answer (`u`) rather than a
            # by-product of approving the file: the blocklist names only the
            # dangers known when it was written, so "not blocked" was never
            # the same claim as "safe".
            allow_unknown = ch == ord("u")
            approved = [
                m for m in info.requires if classify_module(_parse_requirement(m)[0]) != "blocked"
            ]
            return LoadPolicy(
                load_code=True, approved_modules=approved, allow_unknown=allow_unknown
            )
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

    # No pre-clear: `jsonload` performs its own (wider) reset once the file
    # is known to be loadable, and every rejection returns before it. Clearing
    # here first meant any unreadable or malformed file left the user holding
    # an empty workbook -- the open failed *and* took the open sheet with it.
    try:
        rc = g.jsonload(fn, policy=policy)
    except Exception as exc:  # noqa: BLE001
        # Defence in depth. `jsonload` is documented to report failure by
        # returning -1, but it runs a recalc over file-supplied formulas; an
        # uncaught exception here tears down curses and takes the user's
        # unsaved sheet with it.
        show_error(stdscr, f"Failed to load: {fn} ({type(exc).__name__}). Press any key.")
        return False
    if rc == 0:
        g.filename = fn
        g.dirty = 0
    else:
        show_error(stdscr, f"Failed to load: {fn}. Press any key.")
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
                    if abs(val) < 1e15 and val == int(val):
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


def cmd_sheets(stdscr: curses.window, g: Grid) -> bool:
    """Interactive sheet picker: list every sheet and switch to the chosen one.

    A single-sheet workbook has nothing to choose, so it just reports the lone
    sheet. Otherwise it opens a full-screen list positioned on the active
    sheet; selecting a row switches to it, Esc leaves the active sheet as is.
    """
    if len(g.sheets) <= 1:
        show_error(stdscr, f"sheets: {g._active.name} (only sheet)")
        return False
    items = [f"{i}: {s.name}" for i, s in enumerate(g.sheets)]
    choice = select_from_list(stdscr, "Select sheet", items, initial=g.active)
    if choice is not None and choice != g.active:
        g.set_active(choice)
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


# Sentinel distinguishing "not a shared command" from "cancelled at a prompt",
# since both would otherwise be None.
_NOT_SHARED: Any = object()

# Terminal shorthands that are the same shared command with the argument baked
# in. `:tv` is `:title v`; there is no reason for the registry to carry four
# near-identical entries just because the keyboard shorthand predates it.
_ARG_ALIASES: dict[str, tuple[str, list[str]]] = {
    "tv": ("title", ["v"]),
    "th": ("title", ["h"]),
    "tb": ("title", ["b"]),
    "tn": ("title", ["n"]),
}


def _resolve_shared_args(
    stdscr: curses.window,
    g: Grid,
    cmd: str,
    args: str,
    sel: tuple[int, int, int, int] | None,
) -> Any:
    """Collect a shared command's arguments the way a terminal collects them.

    Returns the argument list, ``None`` if the user cancelled a prompt, or
    ``_NOT_SHARED`` when the name is not in the registry (so `cmdexec` falls
    through to the view-owned commands).

    This is the whole of what the TUI still owns for these commands: a status
    line prompt, a format picker, a range selector. The operation itself is in
    `gridcalc.commands`.
    """
    alias, prefix = _ARG_ALIASES.get(cmd, (cmd, []))
    found = shared.lookup(alias)
    if found is None:
        return _NOT_SHARED
    # Branch on the *canonical* name: `:f` and `:format` are the same command,
    # and matching on whatever the user typed would skip the prompt for one.
    name = found.name
    argv = prefix + args.split()
    if argv:
        return argv

    # No arguments given: prompt for the ones this command cannot do without.
    if name == "format":
        fmt = _resolve_fmt(stdscr, args)
        return None if fmt is None else [fmt]
    if name == "gformat":
        stdscr.addnstr(curses.LINES - 1, 0, "Global format: L R I G D $ % *", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        k = stdscr.getch()
        return [chr(k)] if 32 <= k < 127 else []
    if name == "name":
        entered = _line_input(
            stdscr,
            curses.LINES - 1,
            prefix="Name: ",
            accept=lambda ch, buf: ch.isalpha() or (bool(buf) and (ch.isalnum() or ch == "_")),
            allow_empty=False,
        )
        if entered is None:
            return None
        picked = selectrange(stdscr, g, "Range:", g.cc, g.cr)
        if picked is None:
            return None
        c1, r1, c2, r2 = picked
        return [entered, shared.range_a1(c1, r1, c2, r2)]
    if name == "unname":
        entered = _line_input(stdscr, curses.LINES - 1, prefix="Remove name: ", allow_empty=False)
        return None if entered is None else [entered]
    if name == "title":
        return []  # `:title` with no argument reports its usage via the command
    return argv


def _run_shared(
    stdscr: curses.window,
    g: Grid,
    undo: UndoManager,
    cmd: str,
    argv: list[str],
    sel: tuple[int, int, int, int] | None,
) -> bool:
    """Run a shared command and present its result in the terminal.

    Presentation follows the convention this frontend has always had: a
    failure and a *query* both stop for a keypress so they can be read, while
    a mutation says nothing -- the redrawn grid is the feedback. (The web view
    shows every message, because it has a status bar that does not block; that
    difference is exactly the kind the registry leaves to each frontend.)

    Always returns False: none of the shared commands quit the application.
    """
    result = shared.run(_ARG_ALIASES.get(cmd, (cmd, []))[0], g, undo, argv, sel)
    if result.changed:
        g.dirty = 1
    if not result.ok:
        show_error(stdscr, result.message)
    elif result.lines:
        pager(stdscr, f"Named ranges ({len(result.lines)})", list(result.lines))
    elif result.message and not result.changed:
        show_error(stdscr, result.message)
    return False


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

    # Shared commands first. `gridcalc.commands` owns the operation; this
    # layer's job is to collect the arguments a terminal collects (a prompt on
    # the status line, a range picker) and to present the result. A command
    # that needs no prompting falls straight through to `_run_shared`.
    resolved = _resolve_shared_args(stdscr, g, cmd, args, sel)
    if resolved is not _NOT_SHARED:
        if resolved is None:
            return False  # the user cancelled at a prompt
        return _run_shared(stdscr, g, undo, cmd, resolved, sel)

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
    if cmd == "clear":
        return cmd_clear(stdscr, g, undo)
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
    if cmd == "opt":
        return cmd_opt(stdscr, g, undo, args, sel=sel)
    if cmd == "goal":
        return cmd_goal(stdscr, g, undo, args)
    if cmd in ("m", "move"):
        undo.save_grid(g)
        movecmd(stdscr, g, undo)
        return False
    if cmd in ("r", "replicate"):
        undo.save_grid(g)
        replcmd(stdscr, g, undo)
        return False
    if cmd in ("sheet", "s"):
        return cmd_sheet(stdscr, g, args)
    if cmd == "sheets":
        return cmd_sheets(stdscr, g)

    stdscr.addnstr(curses.LINES - 1, 0, f"Unknown command: {cmd} (press any key)", curses.COLS - 1)
    stdscr.clrtoeol()
    stdscr.refresh()
    stdscr.getch()
    return False
