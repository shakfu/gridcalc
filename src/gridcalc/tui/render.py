"""Curses rendering: color setup, the main grid draw, and label overflow."""

from __future__ import annotations

import curses
import math

# The module, not the name: `configure_sandbox` rebinds the flag in
# `sandbox`, and a `from ... import` here would freeze the import-time value.
# `sandbox = false` in gridcalc.toml is applied after this module loads.
from .. import sandbox
from ..display import fmtcell
from ..engine import (
    EMPTY,
    FORMULA,
    LABEL,
    NCOL,
    NROW,
    NUM,
    SPILL,
    Cell,
    Grid,
    _is_dataframe,
    col_name,
)
from ..formula.errors import ExcelError

GW = 4

CP_CHROME = 1
CP_GUTTER = 2
CP_CURSOR = 3
CP_LOCKED = 4
CP_MARK = 5
CP_ERROR = 6
CP_MODE_DEFAULT = 7
CP_MODE_ENTRY = 8
CP_MODE_CMD = 9
CP_SELECT = 10
CP_SPILL = 11


def init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(CP_CHROME, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(CP_GUTTER, curses.COLOR_CYAN, -1)
    curses.init_pair(CP_CURSOR, curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(CP_LOCKED, curses.COLOR_YELLOW, -1)
    curses.init_pair(CP_MARK, curses.COLOR_MAGENTA, -1)
    curses.init_pair(CP_ERROR, curses.COLOR_RED, -1)
    curses.init_pair(CP_MODE_DEFAULT, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(CP_MODE_ENTRY, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(CP_MODE_CMD, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(CP_SELECT, curses.COLOR_WHITE, curses.COLOR_MAGENTA)
    # A spilling anchor and the cells it painted share one subtle cyan tint,
    # so a dynamic-array result reads as a single cohesive block.
    curses.init_pair(CP_SPILL, curses.COLOR_CYAN, -1)


def _fmt_collection(cur: Cell) -> str | None:
    """Render a cell's DataFrame / ndarray / Vec value for the status bar.

    Returns ``None`` when the cell holds no collection, so the caller falls
    back to scalar / error formatting. Shared by the NUM and FORMULA branches
    of :func:`draw`, which only differ in the surrounding prefix.
    """
    if cur.matrix is not None and _is_dataframe(cur.matrix):
        df = cur.matrix
        cols = ", ".join(str(c) for c in df.columns[:6])
        extra = ", ..." if len(df.columns) > 6 else ""
        return f"DataFrame({df.shape[0]}x{df.shape[1]}) [{cols}{extra}]"
    if cur.matrix is not None:
        shape = cur.matrix.shape
        flat = cur.matrix.flat
        show = [float(flat[i]) for i in range(min(6, cur.matrix.size))]
        items = ", ".join(f"{v:.10g}" for v in show)
        extra = ", ..." if cur.matrix.size > 6 else ""
        return f"ndarray{shape} [{items}{extra}]"
    if cur.arr and len(cur.arr) > 0:
        show = cur.arr[:10]
        items = ", ".join(f"{v:.10g}" for v in show)
        extra = ", ..." if len(cur.arr) > 10 else ""
        return f"[{items}{extra}] ({len(cur.arr)})"
    return None


def mode_color(mode: str) -> int:
    # No transient mode -> the right-side label is just the formula-mode
    # tag (`[PYTHON]` etc.). Paint it in green to keep it visible against
    # the blue chrome of the status bar; transient modes override with
    # their own colors below.
    if not mode:
        return CP_MODE_DEFAULT
    if mode in ("CMD", "VISUAL"):
        return CP_MODE_CMD
    return CP_MODE_ENTRY


def vcols(g: Grid) -> int:
    v = (curses.COLS - GW) // g.cw
    return max(v, 1)


def vrows() -> int:
    v = curses.LINES - 4
    return max(v, 1)


def draw(
    stdscr: curses.window,
    g: Grid,
    mode: str,
    buf: str,
    sel: tuple[int, int, int, int] | None = None,
    search_info: str = "",
) -> None:
    stdscr.erase()

    lc = g.tc
    lr = g.tr
    fc = max(vcols(g) - lc, 1)
    fr = max(vrows() - lr, 1)

    # Status bar
    stdscr.attron(curses.color_pair(CP_CHROME) | curses.A_BOLD)
    stdscr.move(0, 0)
    stdscr.clrtoeol()
    cur = g.cell(g.cc, g.cr)
    # Show the active sheet only when the workbook has more than one;
    # single-sheet workbooks keep the original ` A1 10 ` chrome.
    if len(g.sheets) > 1:
        status = f" {g._active.name}!{col_name(g.cc)}{g.cr + 1}"
    else:
        status = f" {col_name(g.cc)}{g.cr + 1}"
    if cur and cur.type == NUM:
        coll = _fmt_collection(cur)
        if coll is not None:
            status += f"  {coll}"
        else:
            status += f"  {cur.val:.10g}"
    elif cur and cur.type == FORMULA:
        status += f"  {cur.text} = "
        coll = _fmt_collection(cur)
        if coll is not None:
            status += coll
        elif cur.sval is not None:
            status += repr(cur.sval)
        else:
            if cur.err is not None:
                status += str(cur.err)
                if cur.err is ExcelError.SPILL:
                    status += "  (spill range blocked -- clear the target cells)"
                elif cur.err_msg:
                    status += f"  ({cur.err_msg})"
            elif isinstance(cur.val, float) and math.isnan(cur.val):
                if (g.cc, g.cr) in g._circular:
                    status += "CIRC"
                else:
                    status += "ERR 0"
            else:
                status += f"{cur.val:.10g}"
    elif cur and cur.type == LABEL:
        status += f"  {cur.text}"
    elif cur and cur.type == SPILL:
        if cur.sval is not None:
            status += f"  {cur.sval!r}"
        elif cur.err is not None:
            status += f"  {cur.err}"
        elif isinstance(cur.val, float) and math.isnan(cur.val):
            status += "  ERR"
        else:
            status += f"  {cur.val:.10g}"
        if cur.spill_parent is not None:
            ac, ar = cur.spill_parent
            status += f"  (spill from {col_name(ac)}{ar + 1})"
    if g.code_error:
        status += f"  [CODE ERR: {g.code_error}]"
    stdscr.addnstr(0, 0, status, curses.COLS - 1)
    stdscr.attroff(curses.color_pair(CP_CHROME) | curses.A_BOLD)
    if not sandbox.SANDBOX_ENABLED:
        banner = " SANDBOX OFF "
        x = max(0, curses.COLS - len(banner) - 1)
        stdscr.attron(curses.color_pair(CP_ERROR) | curses.A_BOLD | curses.A_REVERSE)
        stdscr.addnstr(0, x, banner, len(banner))
        stdscr.attroff(curses.color_pair(CP_ERROR) | curses.A_BOLD | curses.A_REVERSE)

    grid_mode_tag = f"[{g.mode.name}]"
    right_label = f"{mode}  {grid_mode_tag}" if mode else grid_mode_tag
    if search_info:
        right_label = f"{search_info}  {right_label}"
    stdscr.attron(curses.color_pair(mode_color(mode)) | curses.A_BOLD)
    mode_x = curses.COLS - len(right_label) - 1
    if mode_x > 0:
        stdscr.addnstr(0, mode_x, right_label, len(right_label))
    stdscr.attroff(curses.color_pair(mode_color(mode)) | curses.A_BOLD)

    # Input line
    stdscr.move(1, 0)
    stdscr.clrtoeol()
    if mode:
        stdscr.addnstr(1, 0, f"{buf}_", curses.COLS - 1)
    elif cur and cur.type != EMPTY:
        stdscr.addnstr(1, 0, f"  {cur.text}", curses.COLS - 1)

    # Column headers
    stdscr.attron(curses.color_pair(CP_CHROME) | curses.A_BOLD)
    stdscr.move(2, 0)
    stdscr.clrtoeol()
    for ci in range(lc + fc):
        c = ci if ci < lc else g.vc + (ci - lc)
        if c >= NCOL:
            break
        x = GW + ci * g.cw
        if x < curses.COLS:
            hdr = f"{col_name(c):>{g.cw}}"
            stdscr.addnstr(2, x, hdr, min(g.cw, curses.COLS - x))
    stdscr.attroff(curses.color_pair(CP_CHROME) | curses.A_BOLD)

    # Grid
    for ri in range(lr + fr):
        row = ri if ri < lr else g.vr + (ri - lr)
        if row >= NROW:
            continue
        y = 3 + ri
        if y >= curses.LINES:
            break
        is_locked_row = ri < lr

        stdscr.move(y, 0)
        stdscr.clrtoeol()
        stdscr.attron(curses.color_pair(CP_GUTTER) | curses.A_BOLD)
        gutter = f"{row + 1:>{GW - 1}} "
        stdscr.addnstr(y, 0, gutter, min(GW, curses.COLS))
        stdscr.attroff(curses.color_pair(CP_GUTTER) | curses.A_BOLD)

        for ci in range(lc + fc):
            c = ci if ci < lc else g.vc + (ci - lc)
            if c >= NCOL:
                break
            is_locked_col = ci < lc

            cl = g.cell(c, row)
            fb = fmtcell(cl, g.cw, g.fmt)

            is_cur = c == g.cc and row == g.cr
            is_mark = g.mc >= 0 and c == g.mc and row == g.mr
            is_sel = sel is not None and sel[0] <= c <= sel[2] and sel[1] <= row <= sel[3]
            is_locked = is_locked_row or is_locked_col
            is_error = (
                cl
                and cl.type in (NUM, FORMULA)
                and isinstance(cl.val, float)
                and math.isnan(cl.val)
                and cl.matrix is None
            )
            # A spill cell, or a healthy spilling anchor: one cohesive block.
            # A blocked anchor (#SPILL!) has spill_shape cleared, so it falls
            # through to is_error and renders red instead.
            is_spill = cl is not None and (cl.type == SPILL or cl.spill_shape is not None)
            style = 0
            if cl:
                if cl.bold:
                    style |= curses.A_BOLD
                if cl.underline:
                    style |= curses.A_UNDERLINE
                if cl.italic:
                    style |= curses.A_ITALIC

            if is_cur:
                attr = curses.color_pair(CP_CURSOR) | curses.A_BOLD
            elif is_sel:
                attr = curses.color_pair(CP_SELECT)
            elif is_mark:
                attr = curses.color_pair(CP_MARK) | curses.A_UNDERLINE
            elif is_locked:
                attr = curses.color_pair(CP_LOCKED) | curses.A_BOLD
            elif is_error:
                attr = curses.color_pair(CP_ERROR) | curses.A_BOLD
            elif is_spill:
                attr = curses.color_pair(CP_SPILL) | style
            else:
                attr = style

            x = GW + ci * g.cw
            if x < curses.COLS:
                if attr:
                    stdscr.attron(attr)
                stdscr.addnstr(y, x, fb, min(g.cw, curses.COLS - x))
                if attr:
                    stdscr.attroff(attr)

        # Pass 2: Excel-style label overflow. After the per-cell loop has
        # painted the row with each cell clipped to its own column, walk the
        # row again and overpaint into adjacent empty cells for any LABEL
        # whose text exceeds the column width. Done as a separate pass so
        # the primary loop's cursor / selection / mark / lock handling stays
        # unchanged; overflow respects those by stopping at the first
        # non-empty or specially-styled cell to the right.
        _paint_label_overflow(stdscr, g, row, y, lc, fc, sel)

    _draw_sheet_tabs(stdscr, g)


def _draw_sheet_tabs(stdscr: curses.window, g: Grid) -> None:
    """Bottom-line sheet-tab strip, drawn only for multi-sheet workbooks.

    Single-sheet workbooks leave the last line for transient messages, so the
    strip doubles as the "this is a multi-sheet workbook" cue: its mere
    presence signals more than one sheet, and the right-aligned ``i/n`` counter
    makes the position explicit. The active tab is reverse-highlighted, and the
    strip scrolls so the active tab is always visible when the names overflow
    the terminal width.
    """
    n = len(g.sheets)
    if n <= 1:
        return

    y = curses.LINES - 1
    stdscr.move(y, 0)
    stdscr.clrtoeol()

    active = g.active
    labels = [f" {s.name} " for s in g.sheets]
    counter = f" {active + 1}/{n} "
    avail = max(0, curses.COLS - 1 - len(counter))

    # Scroll: advance the first drawn tab until the active tab fits in `avail`.
    start = 0
    while start < active and sum(len(labels[i]) for i in range(start, active + 1)) > avail:
        start += 1

    base = curses.color_pair(CP_CHROME) | curses.A_BOLD
    x = 0
    for i in range(start, n):
        lab = labels[i]
        if x + len(lab) > avail:
            break
        stdscr.addnstr(y, x, lab, len(lab), base | (curses.A_REVERSE if i == active else 0))
        x += len(lab)

    cx = curses.COLS - 1 - len(counter)
    if cx >= x:
        stdscr.addnstr(y, cx, counter, len(counter), base)


def _paint_label_overflow(
    stdscr: curses.window,
    g: Grid,
    row: int,
    y: int,
    lc: int,
    fc: int,
    sel: tuple[int, int, int, int] | None,
) -> None:
    """Overpaint LABEL text into consecutive empty cells to the right.

    Mirrors Excel's behavior: a label that doesn't fit its own column spills
    into the next empty cells, but is clipped the moment a right-neighbor
    cell holds content (or is the cursor / a selected / marked cell, since
    those need to keep their own visual state).
    """
    for ci in range(lc + fc):
        c = ci if ci < lc else g.vc + (ci - lc)
        if c >= NCOL:
            break
        cl = g.cell(c, row)
        if cl is None or cl.type != LABEL:
            continue

        text = cl.text
        if text.startswith('"'):
            text = text[1:]
        if len(text) <= g.cw:
            continue

        # Scan rightward for spillover targets. Stop on first non-empty
        # cell or on any cell carrying cursor / selection / mark state,
        # so those keep their normal-pass appearance.
        paint_cells = 1
        scan = ci + 1
        while scan < lc + fc and paint_cells * g.cw < len(text):
            nc = scan if scan < lc else g.vc + (scan - lc)
            if nc >= NCOL:
                break
            ncl = g.cell(nc, row)
            if ncl is not None and ncl.type != EMPTY:
                break
            is_cursor = nc == g.cc and row == g.cr
            is_sel = sel is not None and sel[0] <= nc <= sel[2] and sel[1] <= row <= sel[3]
            is_mark = g.mc >= 0 and nc == g.mc and row == g.mr
            if is_cursor or is_sel or is_mark:
                break
            paint_cells += 1
            scan += 1

        if paint_cells == 1:
            continue  # nothing to spill into; pass 1 already rendered fine

        # Only the overflow chars (those past the label's own column) need
        # painting -- pass 1 already painted the first cw chars in the
        # label's own cell, with whatever attributes it had.
        x_overflow = GW + (ci + 1) * g.cw
        if x_overflow >= curses.COLS:
            continue
        avail = min(paint_cells * g.cw, curses.COLS - GW - ci * g.cw) - g.cw
        if avail <= 0:
            continue
        overflow_text = text[g.cw : g.cw + avail]

        style = 0
        if cl.bold:
            style |= curses.A_BOLD
        if cl.underline:
            style |= curses.A_UNDERLINE
        if cl.italic:
            style |= curses.A_ITALIC

        if style:
            stdscr.attron(style)
        stdscr.addnstr(y, x_overflow, overflow_text, avail)
        if style:
            stdscr.attroff(style)
