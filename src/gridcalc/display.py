"""Frontend-neutral cell display formatting.

Pure functions that turn a `Cell` into a string a *view* can paint -- the
width-padded grid field (`fmtcell`), the plain clipboard value
(`cell_clip_value`), and the number-format helper they share (`fmt_float`).
This module imports only the engine, never `curses` or anything under
`gridcalc.tui`, so any frontend (the curses TUI and the web view today, a Qt
or other view later) can reuse it without dragging in a terminal dependency. The
`tests/test_architecture.py` guard pins that: `display` is a core module and
importing it must not load `curses`.

Solver-report rendering (`format_sensitivity` and friends) is deliberately
*not* here -- it lives in `tui/format.py` because it emits `list[str]`/status
lines shaped for the pager and status bar, which is TUI presentation a GUI
would render differently.
"""

from __future__ import annotations

import math

from .dates import format_serial as _format_serial
from .dates import is_date_format
from .engine import EMPTY, FORMULA, LABEL, NUM, SPILL, Cell, _is_dataframe

# Width (in characters) handed to ``fmtcell`` by :func:`cell_text` before the
# padding is stripped. Wide enough that ordinary values and array badges
# survive; over-long labels are truncated, which a GUI cell tolerates since it
# manages its own column width.
_CELL_CHARS = 64


def _insert_commas(s: str) -> str:
    neg = s.startswith("-")
    digits = s[1:] if neg else s
    result = []
    for i, ch in enumerate(digits):
        if i > 0 and (len(digits) - i) % 3 == 0:
            result.append(",")
        result.append(ch)
    return ("-" if neg else "") + "".join(result)


def format_date(val: float, spec: str) -> str | None:
    """Render ``val`` as a date if ``spec`` is an xlsx date format, else None.

    The gate is deliberate: `fmtstr` is one field holding two languages, and
    a numeric spec like ``,.2f`` must not be mistaken for a date pattern
    because it happens to contain an `f`.
    """
    if not is_date_format(spec):
        return None
    return _format_serial(val, spec)


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
    """Compact numeric string: integer form when integral and not huge.

    The magnitude test comes first so short-circuiting keeps ``int(v)`` away
    from an infinity, which raises OverflowError. Same ordering applies
    everywhere this idiom appears.
    """
    return str(int(v)) if abs(v) < 1e9 and v == int(v) else f"{v:g}"


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
    if cl.type in (FORMULA, SPILL) and cl.sval is not None:
        return cl.sval
    if isinstance(cl.val, float) and math.isnan(cl.val):
        return ""
    return _num_str(cl.val)


def cell_text(cl: Cell | None, global_fmt: str = "") -> str:
    """Unpadded display string for a cell, for a GUI table cell.

    ``fmtcell`` pads and justifies to a fixed width; stripping recovers the
    bare token (value, label, error, or array badge) for a frontend that
    manages its own column widths (the web view).
    """
    if cl is None or cl.type == EMPTY:
        return ""
    return fmtcell(cl, _CELL_CHARS, global_fmt).strip()


def cell_right_aligned(cl: Cell | None) -> bool:
    """Whether a cell should be right-aligned (numbers and computed values)."""
    if cl is None or cl.type == LABEL:
        return False
    return cl.type in (NUM, FORMULA, SPILL)


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

    # A spilling anchor (spill_shape set) shows its own top-left scalar --
    # the array is laid out in the neighbouring cells. Only a non-spilling
    # array cell (PYTHON mode, where arrays live in one cell) shows the
    # `1[3]` array badge.
    if cl.arr is not None and len(cl.arr) > 0 and cl.spill_shape is None:
        v = cl.arr[0]
        numstr = str(int(v)) if abs(v) < 1e9 and v == int(v) else f"{v:g}"
        t = f"{numstr}[{len(cl.arr)}]"
        return f"{t:>{cw}}"[:cw]

    if cl.type in (FORMULA, SPILL) and cl.sval is not None:
        fc = cl.fmt or global_fmt
        if fc == "L":
            return f"{cl.sval:<{cw}}"[:cw]
        return f"{cl.sval:>{cw}}"[:cw]

    if cl.err is not None:
        return f"{str(cl.err):>{cw}}"[:cw]
    if isinstance(cl.val, float) and math.isnan(cl.val):
        return f"{'ERROR':>{cw}}"
    # Infinity has to be caught before any format branch: the `I` and `*`
    # specs call int() unconditionally, and a number format spec applied to
    # an infinity is meaningless anyway. `=1e308*10` reaches here.
    if isinstance(cl.val, float) and math.isinf(cl.val):
        return f"{('inf' if cl.val > 0 else '-inf'):>{cw}}"[:cw]

    if cl.fmtstr:
        # `fmtstr` carries either a Python numeric spec (",.2f") or an xlsx
        # number-format code ("yyyy-mm-dd"). The date branch goes first
        # because `fmt_float` would reject a date code and fall through to
        # printing the raw serial, which is the behaviour dates were added to
        # end. Both return None when the spec is not theirs, so an
        # unrecognised code still reaches the ordinary numeric path.
        formatted = format_date(cl.val, cl.fmtstr)
        if formatted is None:
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
    elif fc == "I" or (abs(cl.val) < 1e9 and cl.val == int(cl.val)):
        t = str(int(cl.val))
    else:
        t = f"{cl.val:g}"

    if fc == "L":
        return f"{t:<{cw}}"[:cw]
    return f"{t:>{cw}}"[:cw]
