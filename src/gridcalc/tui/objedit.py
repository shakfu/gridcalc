"""Sub-grid editor for Vec / ndarray / DataFrame cell literals."""

from __future__ import annotations

import curses

from ..engine import Grid, _is_dataframe, cellname
from .undo import UndoManager
from .widgets import _line_input


def _fmt_val(s: str) -> str:
    """Format a string as a Python numeric literal or string repr."""
    try:
        v = float(s)
        if abs(v) < 1e15 and v == int(v):
            return str(int(v))
        return repr(v)
    except (ValueError, OverflowError):
        return repr(s)


def _build_formula(mode: str, data: list[list[str]], headers: list[str] | None) -> str:
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
        if headers is None:
            return ""
        parts = []
        for ci, h in enumerate(headers):
            vals = [_fmt_val(data[ri][ci]) for ri in range(len(data))]
            parts.append(f"{repr(h)}: [{', '.join(vals)}]")
        return f"=pd.DataFrame({{{', '.join(parts)}}})"


def _obj_mini_input(stdscr: curses.window, prompt: str, initial: str) -> str | None:
    """Single-line input at bottom of screen. Returns None on Escape."""
    return _line_input(stdscr, curses.LINES - 2, prefix=prompt, initial=initial)


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
        stdscr.addnstr(curses.LINES - 1, 0, status, curses.COLS - 1, curses.A_DIM)
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
