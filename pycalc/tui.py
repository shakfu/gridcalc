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
    cellname,
    col_name,
    ref,
)
from .sandbox import SANDBOX_ENABLED, LoadPolicy, classify_module, configure_sandbox

GW = 4
UNDO_MAX = 64

_cfg: Config = Config()


class UndoEntry:
    __slots__ = ("cells", "cc", "cr", "is_grid")

    def __init__(self):
        self.cells = []  # list of (c, r, Cell_snapshot)
        self.cc = 0
        self.cr = 0
        self.is_grid = False


class UndoManager:
    def __init__(self):
        self.undo_stack = []
        self.redo_stack = []

    def save_region(self, g, c1, r1, c2, r2):
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

    def save_cell(self, g, c, r):
        self.save_region(g, c, r, c, r)

    def save_grid(self, g):
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

    def _apply(self, g, from_stack, to_stack):
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
                cl = g.cell(c, r)
                re.cells.append((c, r, cl.snapshot() if cl else Cell()))
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

    def undo(self, g):
        self._apply(g, self.undo_stack, self.redo_stack)

    def redo(self, g):
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


def init_colors():
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


def mode_color(mode):
    if not mode:
        return CP_CHROME
    if mode == "READY":
        return CP_MODE_READY
    if mode in ("CMD", "VISUAL"):
        return CP_MODE_CMD
    return CP_MODE_ENTRY


def vcols(g):
    v = (curses.COLS - GW) // g.cw
    return max(v, 1)


def vrows():
    v = curses.LINES - 4
    return max(v, 1)


def draw(stdscr, g, mode, buf, sel=None):
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
        if cur.arr and len(cur.arr) > 0:
            show = cur.arr[:10]
            items = ", ".join(f"{v:.10g}" for v in show)
            extra = ", ..." if len(cur.arr) > 10 else ""
            status += f"  [{items}{extra}] ({len(cur.arr)})"
        else:
            status += f"  {cur.val:.10g}"
    elif cur and cur.type == FORMULA:
        status += f"  {cur.text} = "
        if cur.arr and len(cur.arr) > 0:
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

    stdscr.attron(curses.color_pair(mode_color(mode)) | curses.A_BOLD)
    mode_x = curses.COLS - len(mode) - 1
    if mode_x > 0:
        stdscr.addnstr(0, mode_x, mode, len(mode))
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
            fb = g.fmtcell(cl, g.cw)

            is_cur = c == g.cc and row == g.cr
            is_mark = g.mc >= 0 and c == g.mc and row == g.mr
            is_sel = sel is not None and sel[0] <= c <= sel[2] and sel[1] <= row <= sel[3]
            is_locked = is_locked_row or is_locked_col
            is_error = (
                cl
                and cl.type in (NUM, FORMULA)
                and isinstance(cl.val, float)
                and math.isnan(cl.val)
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


def prompt_filename(stdscr, prompt, dflt=None):
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


def show_error(stdscr, msg):
    stdscr.addnstr(curses.LINES - 1, 0, msg, curses.COLS - 1)
    stdscr.clrtoeol()
    stdscr.refresh()
    stdscr.getch()


def movecmd(stdscr, g, undo):
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


def selectrange(stdscr, g, prompt, ac, ar):
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


def replcmd(stdscr, g, undo):
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
            for r in range(sh):
                for c in range(sw):
                    g.replicatecell(sc1 + c, sr1 + r, tc1 + c, tr1 + r)
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


def cmd_quit(stdscr, g):
    if g.dirty:
        stdscr.addnstr(curses.LINES - 1, 0, "Unsaved changes. Quit anyway? (y/N)", curses.COLS - 1)
        stdscr.clrtoeol()
        stdscr.refresh()
        ch = stdscr.getch()
        return ch in (ord("y"), ord("Y"))
    return True


def _do_save(stdscr, g, args):
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


def cmd_save(stdscr, g, args):
    _do_save(stdscr, g, args)
    return False


def cmd_savequit(stdscr, g, args):
    return _do_save(stdscr, g, args)


def cmd_edit(stdscr, g):
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


def trust_prompt(stdscr, filename, info):
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


def cmd_open(stdscr, g, args):
    fn = args.strip() if args.strip() else None
    if not fn:
        fn = prompt_filename(stdscr, "Open: ", g.filename)
        if not fn:
            return False

    info = Grid.jsoninspect(fn)
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


def cmd_blank(g, undo):
    undo.save_cell(g, g.cc, g.cr)
    g.setcell(g.cc, g.cr, "")
    g.recalc()
    return False


def cmd_clear(stdscr, g, undo):
    stdscr.addnstr(curses.LINES - 1, 0, "Clear entire sheet? (y/N)", curses.COLS - 1)
    stdscr.clrtoeol()
    stdscr.refresh()
    ch = stdscr.getch()
    if ch in (ord("y"), ord("Y")):
        undo.save_grid(g)
        g.clear_all()
        g.dirty = 1
    return False


def _apply_fmt_to_range(g, undo, c1, r1, c2, r2, fmt_arg):
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
            cl.fmt = 0
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


def _resolve_fmt(stdscr, args):
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


def cmd_format(stdscr, g, undo, args, sel=None):
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


def cmd_gformat(stdscr, g, args):
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


def cmd_width(stdscr, g, args):
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


def name_set(g, name, c1, r1, c2, r2):
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


def cmd_name(stdscr, g, args):
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


def cmd_names(stdscr, g):
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


def cmd_unname(stdscr, g, args):
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


def cmd_title(g, args):
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


def cmdexec(stdscr, g, undo, text, sel=None):
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
        return cmd_blank(g, undo)
    if cmd == "clear":
        return cmd_clear(stdscr, g, undo)
    if cmd in ("f", "format"):
        return cmd_format(stdscr, g, undo, args, sel=sel)
    if cmd in ("gf", "gformat"):
        return cmd_gformat(stdscr, g, args)
    if cmd == "width":
        return cmd_width(stdscr, g, args)
    if cmd in ("dr", "delrow"):
        undo.save_grid(g)
        g.deleterow(g.cr)
        g.recalc()
        return False
    if cmd in ("dc", "delcol"):
        undo.save_grid(g)
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


def cmdline(stdscr, g, undo, sel=None):
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


def nav(stdscr, g):
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


def entry(stdscr, g, undo, label, initial_ch):
    buf = ""
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


def visual_mode(stdscr, g, undo):
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


def mainloop(stdscr, g):
    undo = UndoManager()

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

        draw(stdscr, g, "READY", "")
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
        elif ch == ord("v"):
            visual_mode(stdscr, g, undo)
        elif ch == ord('"'):
            entry(stdscr, g, undo, True, 0)
        elif ch == ord("=") or ch == ord(".") or (48 <= ch <= 57):
            entry(stdscr, g, undo, False, ch)
        elif 32 <= ch < 127:
            entry(stdscr, g, undo, True, ch)


def startup_trust_prompt(filename, info):
    """Plain-terminal trust prompt for file loading at startup (before curses)."""
    print(f"\nLoading: {filename}")
    print(f"  Cells: {info.cell_count} ({info.formula_count} formulas)")
    if info.requires:
        for mod in info.requires:
            cls = classify_module(mod)
            tag = f" [{cls}]" if cls != "safe" else ""
            print(f"  Requires: {mod}{tag}")
    if info.has_code:
        print(f"  Code: {info.code_lines} lines")
    print()

    while True:
        prompt = "  [a]pprove  [f]ormulas only"
        if info.has_code:
            prompt += "  [v]iew code"
        prompt += "  [c]ancel: "
        resp = input(prompt).strip().lower()
        if resp == "a":
            approved = [m for m in info.requires if classify_module(m) != "blocked"]
            return LoadPolicy(load_code=True, approved_modules=approved)
        elif resp == "f":
            return LoadPolicy.formulas_only()
        elif resp == "v" and info.has_code:
            print(f"\n{info.code_preview}\n")
        elif resp == "c":
            return None


def main():
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
    if _cfg.allowed_modules:
        g.load_requires(_cfg.allowed_modules)
        g.requires = list(_cfg.allowed_modules)

    if len(sys.argv) == 2 and sys.argv[1] in ("-h", "--help"):
        print(f"Usage: {sys.argv[0]} sheet.json", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) > 1:
        fn = sys.argv[1]
        info = Grid.jsoninspect(fn)
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

    def _main(stdscr):
        curses.raw()
        curses.curs_set(0)
        init_colors()
        mainloop(stdscr, g)

    curses.wrapper(_main)
