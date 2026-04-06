from __future__ import annotations

import contextlib
import curses
import math
import os
import subprocess
import tempfile

from .config import Config, load_config
from .engine import (
    CW_DEFAULT,
    EMPTY,
    FORMULA,
    LABEL,
    MAXCODE,
    MAXIN,
    MAXNAMES,
    NCOL,
    NROW,
    NUM,
    Cell,
    Grid,
    NamedRange,
    _is_dataframe,
    cellname,
    col_name,
    ref,
)
from .sandbox import (
    SANDBOX_ENABLED,
    FileInfo,
    LoadPolicy,
    classify_module,
    configure_sandbox,
    inspect_file,
)

GW = 4
UNDO_MAX = 64

_cfg: Config = Config()


# -- Cell display formatting --


def _insert_commas(s: str) -> str:
    neg = s.startswith("-")
    digits = s[1:] if neg else s
    result = []
    for i, ch in enumerate(digits):
        if i > 0 and (len(digits) - i) % 3 == 0:
            result.append(",")
        result.append(ch)
    return ("-" if neg else "") + "".join(result)


def fmt_float(val: float, spec: str) -> str | None:
    """Format a float using a Python-style format spec subset.
    Returns formatted string or None if spec not recognized."""
    p = 0
    commas = False
    prec = -1
    ftype = "f"

    if p < len(spec) and spec[p] == ",":
        commas = True
        p += 1
    if p < len(spec) and spec[p] == ".":
        p += 1
        prec = 0
        while p < len(spec) and spec[p].isdigit():
            prec = prec * 10 + int(spec[p])
            p += 1
    if p < len(spec) and spec[p] in "fe%":
        ftype = spec[p]
        p += 1
    if p != len(spec):
        return None

    v = float(val)
    if ftype == "%":
        v *= 100.0
    if prec < 0:
        prec = 0 if commas else 6

    raw = f"{v:.{prec}e}" if ftype == "e" else f"{v:.{prec}f}"

    if commas and ftype != "e":
        dot_pos = raw.find(".")
        if dot_pos >= 0:
            intpart = raw[:dot_pos]
            fracpart = raw[dot_pos:]
            raw = _insert_commas(intpart) + fracpart
        else:
            raw = _insert_commas(raw)

    if ftype == "%":
        raw += "%"

    return raw


def fmtcell(cl: Cell | None, cw: int, global_fmt: str = "") -> str:
    """Format a cell value for display. Returns a string of exactly cw chars."""
    if cl is None or cl.type == EMPTY:
        return " " * cw

    if cl.type == LABEL:
        t = cl.text
        if t.startswith('"'):
            t = t[1:]
        return f"{t:<{cw}}"[:cw]

    if cl.matrix is not None:
        if _is_dataframe(cl.matrix):
            nrows, ncols = cl.matrix.shape
            t = f"df[{nrows}x{ncols}]"
        else:
            shape = cl.matrix.shape
            if len(shape) == 2:
                t = f"[{shape[0]}x{shape[1]}]"
            elif len(shape) == 1:
                t = f"[{shape[0]}]"
            else:
                t = "[" + "x".join(str(s) for s in shape) + "]"
        return f"{t:>{cw}}"[:cw]

    if cl.arr is not None and len(cl.arr) > 0:
        v = cl.arr[0]
        numstr = str(int(v)) if v == int(v) and abs(v) < 1e9 else f"{v:g}"
        t = f"{numstr}[{len(cl.arr)}]"
        return f"{t:>{cw}}"[:cw]

    if isinstance(cl.val, float) and math.isnan(cl.val):
        return f"{'ERROR':>{cw}}"

    if cl.fmtstr:
        formatted = fmt_float(cl.val, cl.fmtstr)
        if formatted is not None:
            return f"{formatted:>{cw}}"[:cw]

    fc = cl.fmt
    if not fc or fc == "D":
        fc = global_fmt

    if fc == "$":
        t = f"{cl.val:.2f}"
    elif fc == "%":
        t = f"{cl.val * 100:.2f}%"
    elif fc == "*":
        bar_len = min(cw, max(0, int(cl.val)))
        t = "*" * bar_len
        return f"{t:<{cw}}"[:cw]
    elif fc == "I" or (cl.val == int(cl.val) and abs(cl.val) < 1e9):
        t = str(int(cl.val))
    else:
        t = f"{cl.val:g}"

    if fc == "L":
        return f"{t:<{cw}}"[:cw]
    return f"{t:>{cw}}"[:cw]


class Clipboard:
    """Internal clipboard for cell copy/paste."""

    def __init__(self) -> None:
        self.cells: list[tuple[int, int, Cell]] = []  # (dc, dr, snapshot) offsets from origin
        self.width: int = 0
        self.height: int = 0

    def yank(self, g: Grid, c1: int, r1: int, c2: int, r2: int) -> int:
        """Copy a rectangular region of cells. Returns count of non-empty cells copied."""
        self.cells = []
        self.width = c2 - c1 + 1
        self.height = r2 - r1 + 1
        count = 0
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cl = g.cell(c, r)
                if cl and cl.type != EMPTY:
                    self.cells.append((c - c1, r - r1, cl.snapshot()))
                    count += 1
        return count

    def paste(self, g: Grid, undo: UndoManager, dc: int, dr: int) -> None:
        """Paste clipboard contents at (dc, dr). Text is copied verbatim."""
        if not self.cells:
            return
        undo.save_region(g, dc, dr, dc + self.width - 1, dr + self.height - 1)
        for oc, orr, snap in self.cells:
            tc, tr = dc + oc, dr + orr
            if 0 <= tc < NCOL and 0 <= tr < NROW:
                g.setcell(tc, tr, snap.text)
                cl = g.cell(tc, tr)
                if cl:
                    cl.bold = snap.bold
                    cl.underline = snap.underline
                    cl.italic = snap.italic
                    cl.fmt = snap.fmt
                    cl.fmtstr = snap.fmtstr
        g.recalc()

    @property
    def empty(self) -> bool:
        return len(self.cells) == 0


class UndoEntry:
    __slots__ = ("cells", "cc", "cr", "is_grid")

    def __init__(self) -> None:
        self.cells: list[tuple[int, int, Cell]] = []
        self.cc: int = 0
        self.cr: int = 0
        self.is_grid: bool = False


class UndoManager:
    def __init__(self) -> None:
        self.undo_stack: list[UndoEntry] = []
        self.redo_stack: list[UndoEntry] = []

    def save_region(self, g: Grid, c1: int, r1: int, c2: int, r2: int) -> None:
        e = UndoEntry()
        e.cc = g.cc
        e.cr = g.cr
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cl = g.cell(c, r)
                # Save a snapshot (or empty Cell) so undo can restore the state
                e.cells.append((c, r, cl.snapshot() if cl else Cell()))
        self.undo_stack.append(e)
        if len(self.undo_stack) > UNDO_MAX:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def save_cell(self, g: Grid, c: int, r: int) -> None:
        self.save_region(g, c, r, c, r)

    def save_grid(self, g: Grid) -> None:
        e = UndoEntry()
        e.cc = g.cc
        e.cr = g.cr
        e.is_grid = True
        for (c, r), cl in g._cells.items():
            if cl.type != EMPTY:
                e.cells.append((c, r, cl.snapshot()))
        self.undo_stack.append(e)
        if len(self.undo_stack) > UNDO_MAX:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _apply(self, g: Grid, from_stack: list[UndoEntry], to_stack: list[UndoEntry]) -> None:
        if not from_stack:
            return
        e = from_stack.pop()

        # Save current state to opposite stack
        re = UndoEntry()
        re.cc = g.cc
        re.cr = g.cr
        re.is_grid = e.is_grid
        if e.is_grid:
            for (c, r), cl in g._cells.items():
                if cl.type != EMPTY:
                    re.cells.append((c, r, cl.snapshot()))
            to_stack.append(re)
            g.clear_all()
        else:
            for c, r, _ in e.cells:
                maybe_cl: Cell | None = g.cell(c, r)
                re.cells.append((c, r, maybe_cl.snapshot() if maybe_cl else Cell()))
            to_stack.append(re)

        for c, r, snap in e.cells:
            if snap.type == EMPTY:
                g._cells.pop((c, r), None)
            else:
                cl = g._ensure_cell(c, r)
                cl.copy_from(snap)

        g.cc = e.cc
        g.cr = e.cr
        g.recalc()

    def undo(self, g: Grid) -> None:
        self._apply(g, self.undo_stack, self.redo_stack)

    def redo(self, g: Grid) -> None:
        self._apply(g, self.redo_stack, self.undo_stack)


CP_CHROME = 1
CP_GUTTER = 2
CP_CURSOR = 3
CP_LOCKED = 4
CP_MARK = 5
CP_ERROR = 6
CP_MODE_READY = 7
CP_MODE_ENTRY = 8
CP_MODE_CMD = 9
CP_SELECT = 10


def init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(CP_CHROME, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(CP_GUTTER, curses.COLOR_CYAN, -1)
    curses.init_pair(CP_CURSOR, curses.COLOR_BLACK, curses.COLOR_GREEN)
    curses.init_pair(CP_LOCKED, curses.COLOR_YELLOW, -1)
    curses.init_pair(CP_MARK, curses.COLOR_MAGENTA, -1)
    curses.init_pair(CP_ERROR, curses.COLOR_RED, -1)
    curses.init_pair(CP_MODE_READY, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(CP_MODE_ENTRY, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(CP_MODE_CMD, curses.COLOR_RED, curses.COLOR_BLACK)
    curses.init_pair(CP_SELECT, curses.COLOR_WHITE, curses.COLOR_MAGENTA)


def mode_color(mode: str) -> int:
    if not mode:
        return CP_CHROME
    if mode == "READY":
        return CP_MODE_READY
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
    status = f" {col_name(g.cc)}{g.cr + 1}"
    if cur and cur.type == NUM:
        if cur.matrix is not None and _is_dataframe(cur.matrix):
            df = cur.matrix
            cols = ", ".join(str(c) for c in df.columns[:6])
            extra = ", ..." if len(df.columns) > 6 else ""
            status += f"  DataFrame({df.shape[0]}x{df.shape[1]}) [{cols}{extra}]"
        elif cur and cur.matrix is not None:
            shape = cur.matrix.shape
            flat = cur.matrix.flat
            show = [float(flat[i]) for i in range(min(6, cur.matrix.size))]
            items = ", ".join(f"{v:.10g}" for v in show)
            extra = ", ..." if cur.matrix.size > 6 else ""
            status += f"  ndarray{shape} [{items}{extra}]"
        elif cur.arr and len(cur.arr) > 0:
            show = cur.arr[:10]
            items = ", ".join(f"{v:.10g}" for v in show)
            extra = ", ..." if len(cur.arr) > 10 else ""
            status += f"  [{items}{extra}] ({len(cur.arr)})"
        else:
            status += f"  {cur.val:.10g}"
    elif cur and cur.type == FORMULA:
        status += f"  {cur.text} = "
        if cur.matrix is not None and _is_dataframe(cur.matrix):
            df = cur.matrix
            cols = ", ".join(str(c) for c in df.columns[:6])
            extra = ", ..." if len(df.columns) > 6 else ""
            status += f"DataFrame({df.shape[0]}x{df.shape[1]}) [{cols}{extra}]"
        elif cur.matrix is not None:
            shape = cur.matrix.shape
            flat = cur.matrix.flat
            show = [float(flat[i]) for i in range(min(6, cur.matrix.size))]
            items = ", ".join(f"{v:.10g}" for v in show)
            extra = ", ..." if cur.matrix.size > 6 else ""
            status += f"ndarray{shape} [{items}{extra}]"
        elif cur.arr and len(cur.arr) > 0:
            show = cur.arr[:10]
            items = ", ".join(f"{v:.10g}" for v in show)
            extra = ", ..." if len(cur.arr) > 10 else ""
            status += f"[{items}{extra}] ({len(cur.arr)})"
        else:
            if isinstance(cur.val, float) and math.isnan(cur.val):
                if (g.cc, g.cr) in g._circular:
                    status += "CIRC"
                else:
                    status += "ERR 0"
            else:
                status += f"{cur.val:.10g}"
    elif cur and cur.type == LABEL:
        status += f"  {cur.text}"
    stdscr.addnstr(0, 0, status, curses.COLS - 1)
    stdscr.attroff(curses.color_pair(CP_CHROME) | curses.A_BOLD)

    right_label = mode
    if search_info:
        right_label = f"{search_info}  {mode}"
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
            elif style:
                attr = style
            else:
                attr = 0

            x = GW + ci * g.cw
            if x < curses.COLS:
                if attr:
                    stdscr.attron(attr)
                stdscr.addnstr(y, x, fb, min(g.cw, curses.COLS - x))
                if attr:
                    stdscr.attroff(attr)


def prompt_filename(stdscr: curses.window, prompt: str, dflt: str | None = None) -> str | None:
    buf = dflt or ""
    plen = len(prompt)
    stdscr.move(curses.LINES - 1, 0)
    stdscr.addnstr(curses.LINES - 1, 0, prompt, curses.COLS - 1)
    stdscr.clrtoeol()
    while True:
        stdscr.addnstr(curses.LINES - 1, plen, f"{buf}_  ", curses.COLS - plen - 1)
        ch = stdscr.getch()
        if ch == 27:
            return None
        if ch in (10, 13, curses.KEY_ENTER):
            return buf if buf else None
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            buf = buf[:-1]
        elif 32 <= ch < 127:
            buf += chr(ch)


def show_error(stdscr: curses.window, msg: str) -> None:
    stdscr.addnstr(curses.LINES - 1, 0, msg, curses.COLS - 1)
    stdscr.clrtoeol()
    stdscr.refresh()
    stdscr.getch()


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
            if ch == curses.KEY_UP and g.cr > 0:
                g.cr -= 1
            elif ch == curses.KEY_DOWN and g.cr < NROW - 1:
                g.cr += 1
            elif ch == curses.KEY_LEFT and g.cc > 0:
                g.cc -= 1
            elif ch == curses.KEY_RIGHT and g.cc < NCOL - 1:
                g.cc += 1
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
            if ch == curses.KEY_UP and g.cr > 0:
                g.cr -= 1
            elif ch == curses.KEY_DOWN and g.cr < NROW - 1:
                g.cr += 1
            elif ch == curses.KEY_LEFT and g.cc > 0:
                g.cc -= 1
            elif ch == curses.KEY_RIGHT and g.cc < NCOL - 1:
                g.cc += 1
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
    editor = os.environ.get("EDITOR") or _cfg.editor or "vi"
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
            stdscr.erase()
            stdscr.attron(curses.A_BOLD)
            stdscr.addnstr(0, 0, "Code block:", curses.COLS - 1)
            stdscr.attroff(curses.A_BOLD)
            lines = info.code_preview.splitlines()
            for i, line in enumerate(lines):
                if i + 1 >= curses.LINES - 2:
                    break
                stdscr.addnstr(i + 1, 0, f"  {line}", curses.COLS - 1)
            footer_y = min(len(lines) + 2, curses.LINES - 1)
            stdscr.addnstr(footer_y, 0, "Press any key.", curses.COLS - 1)
            stdscr.refresh()
            stdscr.getch()
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
            # Otherwise treat as start of a Python format spec
            buf = pressed
            stdscr.addnstr(
                curses.LINES - 1,
                0,
                f"  Format spec: {buf}_",
                curses.COLS - 1,
            )
            stdscr.clrtoeol()
            stdscr.refresh()
            while True:
                k = stdscr.getch()
                if k == 27:
                    return None
                if k in (10, 13, curses.KEY_ENTER):
                    return buf if buf else None
                elif k in (curses.KEY_BACKSPACE, 127, 8):
                    buf = buf[:-1]
                elif 32 <= k < 127 and len(buf) < 31:
                    buf += chr(k)
                stdscr.addnstr(
                    curses.LINES - 1,
                    0,
                    f"  Format spec: {buf}_   ",
                    curses.COLS - 1,
                )
                stdscr.clrtoeol()
                stdscr.refresh()
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
    if args:
        try:
            w = int(args)
        except ValueError:
            show_error(stdscr, "Invalid width. Use 4-40.")
            return False
        if 4 <= w <= 40:
            g.cw = w
        else:
            show_error(stdscr, "Invalid width. Use 4-40.")
        return False

    stdscr.addnstr(curses.LINES - 1, 0, "Column width (4-40): ", curses.COLS - 1)
    stdscr.clrtoeol()
    buf = ""
    while True:
        stdscr.addnstr(curses.LINES - 1, 21, f"{buf}_  ", curses.COLS - 22)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == 27:
            break
        if ch in (10, 13, curses.KEY_ENTER):
            if buf:
                try:
                    w = int(buf)
                except ValueError:
                    show_error(stdscr, "Invalid width. Use 4-40.")
                    break
                if 4 <= w <= 40:
                    g.cw = w
                else:
                    show_error(stdscr, "Invalid width. Use 4-40.")
            break
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            buf = buf[:-1]
        elif chr(ch).isdigit() if 32 <= ch < 127 else False:
            buf += chr(ch)
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
        stdscr.addnstr(curses.LINES - 1, 0, "Name: ", curses.COLS - 1)
        stdscr.clrtoeol()
        while True:
            stdscr.addnstr(curses.LINES - 1, 6, f"{nbuf}_  ", curses.COLS - 7)
            stdscr.refresh()
            k = stdscr.getch()
            if k == 27:
                return False
            if k in (10, 13, curses.KEY_ENTER):
                break
            if k in (curses.KEY_BACKSPACE, 127, 8):
                nbuf = nbuf[:-1]
            elif 32 <= k < 127:
                ch = chr(k)
                if ch.isalpha() or (nbuf and (ch.isalnum() or ch == "_")):
                    nbuf += ch
        if not nbuf:
            return False

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
        stdscr.addnstr(curses.LINES - 1, 0, "Remove name: ", curses.COLS - 1)
        stdscr.clrtoeol()
        while True:
            stdscr.addnstr(curses.LINES - 1, 13, f"{nbuf}_  ", curses.COLS - 14)
            stdscr.refresh()
            k = stdscr.getch()
            if k == 27:
                return False
            if k in (10, 13, curses.KEY_ENTER):
                break
            if k in (curses.KEY_BACKSPACE, 127, 8):
                nbuf = nbuf[:-1]
            elif 32 <= k < 127:
                nbuf += chr(k)
        if not nbuf:
            return False

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


def cmd_pd(stdscr: curses.window, g: Grid, undo: UndoManager, args: str) -> bool:
    """Pandas import/export. Usage: :pd load [file] | :pd save [file]"""
    parts = args.strip().split(None, 1)
    if not parts:
        show_error(stdscr, "Usage: pd load [file] | pd save [file]")
        return False
    sub = parts[0].lower()
    farg = parts[1] if len(parts) > 1 else ""

    if sub in ("load", "import", "r"):
        fn = farg.strip() if farg.strip() else None
        if not fn:
            fn = prompt_filename(stdscr, "pd load: ")
            if not fn:
                return False
        undo.save_grid(g)
        g.clear_all()
        if g.pdload(fn) == 0:
            g.recalc()
            g.dirty = 1
        else:
            show_error(stdscr, f"Failed to load: {fn}. Press any key.")
        return False

    if sub in ("save", "export", "w"):
        fn = farg.strip() if farg.strip() else None
        if not fn:
            dflt = None
            if g.filename:
                dflt = g.filename.rsplit(".", 1)[0] + ".csv"
            fn = prompt_filename(stdscr, "pd save as: ", dflt)
            if not fn:
                return False
        if g.pdsave(fn) == 0:
            stdscr.addnstr(
                curses.LINES - 1,
                0,
                f"Exported to {fn}",
                curses.COLS - 1,
            )
            stdscr.clrtoeol()
            stdscr.refresh()
            stdscr.getch()
        else:
            show_error(stdscr, f"Failed to export: {fn}. Press any key.")
        return False

    show_error(stdscr, "Usage: pd load [file] | pd save [file]")
    return False


def cmd_csv(stdscr: curses.window, g: Grid, undo: UndoManager, args: str) -> bool:
    parts = args.strip().split(None, 1)
    if not parts:
        show_error(stdscr, "Usage: csv save [file] | csv load [file]")
        return False
    sub = parts[0].lower()
    farg = parts[1] if len(parts) > 1 else ""

    if sub in ("save", "export", "w"):
        fn = farg.strip() if farg.strip() else None
        if not fn:
            dflt = g.filename.rsplit(".", 1)[0] + ".csv" if g.filename else None
            fn = prompt_filename(stdscr, "CSV save as: ", dflt)
            if not fn:
                return False
        if g.csvsave(fn) == 0:
            stdscr.addnstr(curses.LINES - 1, 0, f"Exported to {fn}", curses.COLS - 1)
            stdscr.clrtoeol()
            stdscr.refresh()
            stdscr.getch()
        else:
            show_error(stdscr, f"Failed to export: {fn}. Press any key.")
        return False

    if sub in ("load", "import", "r"):
        fn = farg.strip() if farg.strip() else None
        if not fn:
            fn = prompt_filename(stdscr, "CSV load: ")
            if not fn:
                return False
        undo.save_grid(g)
        g.clear_all()
        if g.csvload(fn) == 0:
            g.recalc()
        else:
            show_error(stdscr, f"Failed to load: {fn}. Press any key.")
        return False

    show_error(stdscr, "Usage: csv save [file] | csv load [file]")
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
    if cmd == "pd":
        return cmd_pd(stdscr, g, undo, args)
    if cmd == "sort":
        return cmd_sort(stdscr, g, undo, args, sel=sel)
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

    stdscr.addnstr(curses.LINES - 1, 0, f"Unknown command: {cmd} (press any key)", curses.COLS - 1)
    stdscr.clrtoeol()
    stdscr.refresh()
    stdscr.getch()
    return False


def cmdline(
    stdscr: curses.window,
    g: Grid,
    undo: UndoManager,
    sel: tuple[int, int, int, int] | None = None,
) -> bool:
    buf = ""
    draw(stdscr, g, "CMD", "", sel=sel)
    while True:
        stdscr.addnstr(curses.LINES - 1, 0, f":{buf}_", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == 27:
            return False
        if ch in (10, 13, curses.KEY_ENTER):
            if buf:
                return cmdexec(stdscr, g, undo, buf, sel=sel)
            return False
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            buf = buf[:-1]
        elif len(buf) < 255 and 32 <= ch < 127:
            buf += chr(ch)


def nav(stdscr: curses.window, g: Grid) -> None:
    buf = ""
    draw(stdscr, g, "GOTO", "")
    while True:
        stdscr.addnstr(1, 0, f"> {buf}_", curses.COLS - 1)
        stdscr.clrtoeol()
        ch = stdscr.getch()
        if ch == 27:
            break
        if ch in (10, 13, curses.KEY_ENTER, 9):
            r = ref(buf)
            if r:
                _, c, row = r
                g.cc = c
                g.cr = row
            break
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            buf = buf[:-1]
        elif 32 <= ch < 127 and len(buf) < MAXIN - 2:
            test = buf + chr(ch).upper()
            test2 = test + "1" if chr(ch).isalpha() else test
            r = ref(test2)
            if r and r[1] < NCOL and r[2] < NROW:
                buf += chr(ch).upper()


def _search_grid(g: Grid, pattern: str) -> list[tuple[int, int]]:
    """Find all cells whose text or display value matches pattern (case-insensitive)."""
    pat = pattern.lower()
    matches: list[tuple[int, int]] = []
    for (c, r), cl in sorted(g._cells.items(), key=lambda x: (x[0][1], x[0][0])):
        if cl.type == EMPTY:
            continue
        text = cl.text.lower()
        if pat in text:
            matches.append((c, r))
            continue
        if cl.type in (NUM, FORMULA) and not math.isnan(cl.val):
            if cl.val == int(cl.val) and abs(cl.val) < 1e15:
                valstr = str(int(cl.val))
            else:
                valstr = f"{cl.val:g}"
            if pat in valstr:
                matches.append((c, r))
    return matches


def search_prompt(stdscr: curses.window, g: Grid) -> tuple[str, list[tuple[int, int]]]:
    """Prompt for a search pattern and return (pattern, matches)."""
    buf = ""
    draw(stdscr, g, "SEARCH", "")
    while True:
        stdscr.addnstr(curses.LINES - 1, 0, f"/{buf}_", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == 27:
            return ("", [])
        if ch in (10, 13, curses.KEY_ENTER):
            if buf:
                matches = _search_grid(g, buf)
                if matches:
                    g.cc, g.cr = matches[0]
                else:
                    stdscr.addnstr(
                        curses.LINES - 1,
                        0,
                        f"No matches for: {buf}",
                        curses.COLS - 1,
                    )
                    stdscr.clrtoeol()
                    stdscr.refresh()
                    stdscr.getch()
                return (buf, matches)
            return ("", [])
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            buf = buf[:-1]
        elif len(buf) < 255 and 32 <= ch < 127:
            buf += chr(ch)


def search_indicator(g: Grid, matches: list[tuple[int, int]]) -> str:
    """Return a string like '[3/12]' showing current match position, or '' if no matches."""
    if not matches:
        return ""
    cur = (g.cc, g.cr)
    if cur in matches:
        idx = matches.index(cur) + 1
        return f"[{idx}/{len(matches)}]"
    return f"[?/{len(matches)}]"


def search_next(g: Grid, matches: list[tuple[int, int]], forward: bool = True) -> None:
    """Jump to the next (or previous) search match."""
    if not matches:
        return
    cur = (g.cc, g.cr)
    if forward:
        for c, r in matches:
            if (r, c) > (cur[1], cur[0]):
                g.cc, g.cr = c, r
                return
        g.cc, g.cr = matches[0]
    else:
        for c, r in reversed(matches):
            if (r, c) < (cur[1], cur[0]):
                g.cc, g.cr = c, r
                return
        g.cc, g.cr = matches[-1]


def _fmt_val(s: str) -> str:
    """Format a string as a Python numeric literal or string repr."""
    try:
        v = float(s)
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return repr(v)
    except (ValueError, OverflowError):
        return repr(s)


def _build_formula(
    mode: str, data: list[list[str]], headers: list[str] | None
) -> str:
    """Build a formula string from edited object data."""
    if mode == "vec":
        vals = [_fmt_val(row[0]) for row in data]
        return f"=Vec([{', '.join(vals)}])"
    elif mode == "ndarray":
        ncols = len(data[0]) if data else 0
        if ncols == 1:
            vals = [_fmt_val(row[0]) for row in data]
            return f"=np.array([{', '.join(vals)}])"
        else:
            rows = []
            for row in data:
                vals = [_fmt_val(v) for v in row]
                rows.append(f"[{', '.join(vals)}]")
            return f"=np.array([{', '.join(rows)}])"
    else:
        assert headers is not None
        parts = []
        for ci, h in enumerate(headers):
            vals = [_fmt_val(data[ri][ci]) for ri in range(len(data))]
            parts.append(f"{repr(h)}: [{', '.join(vals)}]")
        return f"=pd.DataFrame({{{', '.join(parts)}}})"


def _obj_mini_input(stdscr: curses.window, prompt: str, initial: str) -> str | None:
    """Single-line input at bottom of screen. Returns None on Escape."""
    buf = initial
    while True:
        stdscr.addnstr(curses.LINES - 2, 0, f"{prompt}{buf}_", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        ch = stdscr.getch()
        if ch == 27:
            return None
        if ch in (10, 13, curses.KEY_ENTER):
            return buf
        if ch in (curses.KEY_BACKSPACE, 127, 8):
            buf = buf[:-1]
        elif 32 <= ch < 127:
            buf += chr(ch)


def obj_editor(stdscr: curses.window, g: Grid, undo: UndoManager) -> None:
    """Edit a Vec/ndarray/DataFrame literal in a sub-grid view."""
    cl = g.cell(g.cc, g.cr)
    if not cl:
        return

    cref = cellname(g.cc, g.cr)

    # Extract data into mutable list-of-lists
    headers: list[str] | None = None
    if cl.matrix is not None:
        if _is_dataframe(cl.matrix):
            mode = "dataframe"
            headers = [str(c) for c in cl.matrix.columns]
            data: list[list[str]] = []
            for _, row in cl.matrix.iterrows():
                data.append([str(v) for v in row])
        else:
            mode = "ndarray"
            arr = cl.matrix
            if arr.ndim == 1:
                data = [[str(float(v))] for v in arr]
            else:
                data = [[str(float(v)) for v in row] for row in arr]
    elif cl.arr is not None and len(cl.arr) > 0:
        mode = "vec"
        data = [[str(v)] for v in cl.arr]
    else:
        return

    if not data:
        return

    cr, cc = 0, 0  # cursor row/col in data
    vr, vc = 0, 0  # viewport top-left
    cw = 12  # cell display width
    on_header = False  # cursor is on header row (DataFrame only)

    while True:
        nrows = len(data)
        ncols = len(data[0]) if data else 1

        # Clamp cursor
        cr = min(cr, nrows - 1)
        cc = min(cc, ncols - 1)

        # Visible area
        row_label_w = max(len(str(nrows - 1)), 2) + 1
        max_cols_vis = max((curses.COLS - row_label_w) // (cw + 1), 1)
        header_rows = 1 if headers else 0
        max_rows_vis = max(curses.LINES - 4 - header_rows, 1)

        # Adjust viewport
        if cr < vr:
            vr = cr
        if cr >= vr + max_rows_vis:
            vr = cr - max_rows_vis + 1
        if cc < vc:
            vc = cc
        if cc >= vc + max_cols_vis:
            vc = cc - max_cols_vis + 1

        # Draw
        stdscr.erase()

        # Title
        if mode == "vec":
            title = f" Edit Vec {cref} [{nrows}]"
        elif mode == "ndarray":
            title = f" Edit ndarray {cref} [{nrows}x{ncols}]"
        else:
            title = f" Edit DataFrame {cref} [{nrows}x{ncols}]"
        stdscr.addnstr(0, 0, title, curses.COLS - 1, curses.A_BOLD)

        y = 1

        # Column headers
        if headers:
            line_x = row_label_w
            stdscr.addnstr(y, 0, " " * row_label_w, row_label_w)
            for ci in range(vc, min(vc + max_cols_vis, ncols)):
                h = headers[ci]
                cell_str = f"{h:^{cw}}"[:cw]
                attr = curses.A_UNDERLINE
                if on_header and ci == cc:
                    attr |= curses.A_REVERSE
                if line_x + cw <= curses.COLS:
                    stdscr.addnstr(y, line_x, cell_str, cw, attr)
                line_x += cw + 1
            y += 1

        # Data rows
        for ri in range(vr, min(vr + max_rows_vis, nrows)):
            rl = f"{ri:>{row_label_w - 1}} "
            stdscr.addnstr(y, 0, rl, curses.COLS - 1, curses.A_DIM)
            x = row_label_w
            for ci in range(vc, min(vc + max_cols_vis, ncols)):
                val = data[ri][ci] if ci < len(data[ri]) else ""
                cell_str = f"{val:>{cw}}"[:cw]
                attr = 0
                if ri == cr and ci == cc and not on_header:
                    attr = curses.A_REVERSE
                if x + cw <= curses.COLS:
                    stdscr.addnstr(y, x, cell_str, cw, attr)
                x += cw + 1
            y += 1

        # Status bar
        parts = ["[Enter]edit"]
        if mode == "dataframe":
            parts.append("[H]eader")
        parts.extend(["[o/O]row", "[w]save+exit", "[Esc]cancel"])
        if mode != "vec":
            parts.insert(-2, "[a/A]col")
        if nrows > 1:
            parts.insert(-2, "[x]del-row")
        if mode != "vec" and ncols > 1:
            parts.insert(-2, "[X]del-col")
        status = " ".join(parts)
        stdscr.addnstr(
            curses.LINES - 1, 0, status, curses.COLS - 1, curses.A_DIM
        )
        stdscr.refresh()

        ch = stdscr.getch()

        if ch == 27:
            break
        elif ch == curses.KEY_UP:
            if on_header:
                on_header = False
            elif cr > 0:
                cr -= 1
            elif mode == "dataframe" and headers:
                on_header = True
        elif ch == curses.KEY_DOWN:
            if on_header:
                on_header = False
                cr = 0
            elif cr < nrows - 1:
                cr += 1
        elif ch == curses.KEY_LEFT:
            if cc > 0:
                cc -= 1
        elif ch == curses.KEY_RIGHT:
            if cc < ncols - 1:
                cc += 1
        elif ch == ord("H") and mode == "dataframe" and headers:
            on_header = True
        elif ch in (10, 13, curses.KEY_ENTER, ord("e")):
            if on_header and headers:
                result = _obj_mini_input(stdscr, f"Header [{cc}]: ", headers[cc])
                if result is not None:
                    headers[cc] = result
            else:
                result = _obj_mini_input(stdscr, f"[{cr},{cc}]: ", data[cr][cc])
                if result is not None:
                    data[cr][cc] = result
        elif ch == ord("o"):
            # Insert row after current
            new_row = ["0"] * ncols
            data.insert(cr + 1, new_row)
            cr += 1
        elif ch == ord("O"):
            # Insert row before current
            new_row = ["0"] * ncols
            data.insert(cr, new_row)
        elif ch == ord("a") and mode != "vec":
            # Append column after current
            for row in data:
                row.insert(cc + 1, "0")
            if headers:
                headers.insert(cc + 1, f"c{ncols}")
            cc += 1
        elif ch == ord("A") and mode != "vec":
            # Insert column before current
            for row in data:
                row.insert(cc, "0")
            if headers:
                headers.insert(cc, f"c{ncols}")
        elif ch == ord("x") and nrows > 1:
            data.pop(cr)
            if cr >= len(data):
                cr = len(data) - 1
        elif ch == ord("X") and mode != "vec" and ncols > 1:
            for row in data:
                row.pop(cc)
            if headers:
                headers.pop(cc)
            if cc >= len(data[0]):
                cc = len(data[0]) - 1
        elif ch == ord("w"):
            formula = _build_formula(mode, data, headers)
            undo.save_cell(g, g.cc, g.cr)
            g.setcell(g.cc, g.cr, formula)
            break


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

        if ch == 27:
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

        if ch in (10, 13, curses.KEY_ENTER):
            g.mc = -1
            g.mr = -1
            undo.save_cell(g, origc, origr)
            g.setcell(origc, origr, buf)
            g.cc = origc
            g.cr = origr
            if g.cr < NROW - 1:
                g.cr += 1
            break
        elif ch == 9:
            g.mc = -1
            g.mr = -1
            undo.save_cell(g, origc, origr)
            g.setcell(origc, origr, buf)
            g.cc = origc
            g.cr = origr
            if g.cc < NCOL - 1:
                g.cc += 1
            break
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
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
        if ch == 27:
            break
        elif ch == ord("y"):
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
        elif ch == ord("p"):
            if not clipboard.empty:
                clipboard.paste(g, undo, c1, r1)
            break
        elif ch in (ord("d"), 127, 8, curses.KEY_BACKSPACE):
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
        elif ch == ord(":"):
            cmdline(stdscr, g, undo, sel=sel)
            break
        elif ch == curses.KEY_UP and g.cr > 0:
            g.cr -= 1
        elif ch == curses.KEY_DOWN and g.cr < NROW - 1:
            g.cr += 1
        elif ch == curses.KEY_LEFT and g.cc > 0:
            g.cc -= 1
        elif ch == curses.KEY_RIGHT and g.cc < NCOL - 1:
            g.cc += 1


def mainloop(stdscr: curses.window, g: Grid) -> None:
    undo = UndoManager()
    clipboard = Clipboard()
    search_matches: list[tuple[int, int]] = []

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
        draw(stdscr, g, "READY", "", search_info=si)
        ch = stdscr.getch()

        if ch == 0x1F & ord("c"):
            break
        elif ch == 0x1F & ord("z"):
            undo.undo(g)
        elif ch == 0x1F & ord("y"):
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
    """Syntax-highlight Python code for terminal output using Pygments."""
    from pygments import highlight
    from pygments.formatters import TerminalFormatter
    from pygments.lexers import PythonLexer

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
    import sys

    global _cfg
    _cfg = load_config()
    configure_sandbox(_cfg.sandbox)

    g = Grid()
    g.mc = -1
    g.mr = -1
    g.cw = _cfg.width if _cfg.width else CW_DEFAULT
    if _cfg.format and _cfg.format.upper() in "LRIGD$%*":
        g.fmt = _cfg.format.upper()
    for lib in _cfg.libs:
        g.load_lib(lib)
    if _cfg.allowed_modules:
        g.load_requires(_cfg.allowed_modules)
        g.requires = list(_cfg.allowed_modules)

    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(f"Usage: {sys.argv[0]} sheet.json", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) > 1:
        fn = sys.argv[1]
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
