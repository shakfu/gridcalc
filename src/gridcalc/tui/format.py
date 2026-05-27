"""Cell display formatting -- pure functions, no curses or shared state."""

from __future__ import annotations

import math

from ..engine import EMPTY, FORMULA, LABEL, Cell, _is_dataframe


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
