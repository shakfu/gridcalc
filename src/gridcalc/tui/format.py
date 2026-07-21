"""Cell display formatting -- pure functions, no curses or shared state."""

from __future__ import annotations

import math
from collections.abc import Callable

from ..engine import EMPTY, FORMULA, LABEL, Cell, _is_dataframe
from ..opt import Sensitivity


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


def _num_str(v: float) -> str:
    """Compact numeric string: integer form when integral and not huge."""
    return str(int(v)) if v == int(v) and abs(v) < 1e9 else f"{v:g}"


def cell_clip_value(cl: Cell | None) -> str:
    """Plain, unpadded value of a cell for the system clipboard.

    Interchange with other programs expects *values*, not formula text or
    width-padded display fields: a label yields its text, a formula yields
    its computed value (string, number, or error), and a blank yields "".
    A spilled-array cell yields its first value (TSV cannot nest arrays).
    """
    if cl is None or cl.type == EMPTY:
        return ""
    if cl.type == LABEL:
        t = cl.text
        return t[1:] if t.startswith('"') else t
    if cl.err is not None:
        return str(cl.err)
    if cl.arr is not None and len(cl.arr) > 0:
        return _num_str(cl.arr[0])
    if cl.type == FORMULA and cl.sval is not None:
        return cl.sval
    if isinstance(cl.val, float) and math.isnan(cl.val):
        return ""
    return _num_str(cl.val)


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

    if cl.type == FORMULA and cl.sval is not None:
        fc = cl.fmt or global_fmt
        if fc == "L":
            return f"{cl.sval:<{cw}}"[:cw]
        return f"{cl.sval:>{cw}}"[:cw]

    if cl.err is not None:
        return f"{str(cl.err):>{cw}}"[:cw]
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


def _sens_num(v: float) -> str:
    """Render a sensitivity number, showing infinities as words.

    lp_solve's ranging arrays are unbounded on at least one side for any
    non-binding constraint, and `1e+30` in a report column is noise.
    """
    if math.isinf(v):
        return "inf" if v > 0 else "-inf"
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.6g}"


def format_sensitivity(sens: Sensitivity, cellname: Callable[[int, int], str]) -> list[str]:
    """Render a solver sensitivity report as plain lines for the pager.

    Two tables, mirroring what an operator actually asks after a solve:
    which inputs would change the answer (variables), and which limits are
    actually costing something (constraints). Shadow price leads the
    constraint table because it is the number the question "what should I
    buy more of?" resolves to.

    Pure and curses-free so the layout can be tested directly.

    Every line is kept under `MAX_WIDTH` so the pager's two-space indent
    still fits an 80-column terminal; the pager truncates rather than wraps,
    and a silently clipped number is worse than a narrow column. The binding
    flag is a leading marker rather than a trailing word for the same reason
    -- a trailing label is the first thing lost to truncation.
    """
    lines: list[str] = []
    w = 10  # numeric column width

    lines.append("Variable cells")
    lines.append(
        f"   {'cell':<5}{'value':>{w}}{'reduced':>{w}}{'obj coef':>{w}}"
        f"{'coef from':>{w}}{'coef till':>{w}}"
    )
    for v in sens.variables:
        lines.append(
            f"   {cellname(*v.cell):<5}{_sens_num(v.value):>{w}}"
            f"{_sens_num(v.reduced_cost):>{w}}{_sens_num(v.obj_coef):>{w}}"
            f"{_sens_num(v.obj_from):>{w}}{_sens_num(v.obj_till):>{w}}"
        )

    lines.append("")
    lines.append("Constraints   (* = binding)")
    lines.append(
        f"   {'cell':<5}{'shadow':>{w}}{'rhs':>{w}}{'activity':>{w}}"
        f"{'slack':>{w}}{'rhs from':>{w}}{'rhs till':>{w}}"
    )
    for c in sens.constraints:
        mark = "*" if c.binding else " "
        lines.append(
            f" {mark} {cellname(*c.cell):<5}{_sens_num(c.shadow_price):>{w}}"
            f"{_sens_num(c.rhs):>{w}}{_sens_num(c.activity):>{w}}"
            f"{_sens_num(c.slack):>{w}}{_sens_num(c.rhs_from):>{w}}"
            f"{_sens_num(c.rhs_till):>{w}}"
        )

    lines.append("")
    lines.append("Shadow price is the objective gain per unit of extra")
    lines.append("right-hand side, valid only within rhs from..till.")
    return lines


def format_conflict(
    conflict: list[tuple[int, int]],
    total: int,
    cellname: Callable[[int, int], str],
    max_cells: int = 8,
) -> str:
    """One-line summary of an infeasibility diagnosis for the status bar.

    The empty case is defensive -- `lb > ub` is rejected before solving, so a
    model with no implicated constraint is not currently reachable. Handled
    anyway so the branch degrades to a useful hint rather than an empty
    "conflict: " if that ever changes.

    Long lists are truncated with a count, since the status bar is one line
    and the leading cells are the useful part.
    """
    if not conflict:
        return "no constraint conflict -- check variable bounds"
    names = [cellname(c, r) for c, r in conflict]
    if len(names) > max_cells:
        shown = ", ".join(names[:max_cells])
        body = f"{shown}, +{len(names) - max_cells} more"
    else:
        body = ", ".join(names)
    return f"conflict: {body} ({len(names)} of {total} constraints)"
