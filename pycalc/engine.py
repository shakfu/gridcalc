from __future__ import annotations

import contextlib
import json
import math
import re
from typing import Any

MAXIN = 256
NCOL = 256
NROW = 1024
MAXNAMES = 256
MAXCODE = 8192
CW_DEFAULT = 8

EMPTY = 0
NUM = 1
LABEL = 2
FORMULA = 3


class Vec:
    def __init__(self, data):
        self.data = list(data)

    def __repr__(self):
        return "Vec(" + repr(self.data) + ")"

    def __len__(self):
        return len(self.data)

    def __iter__(self):
        return iter(self.data)

    def __getitem__(self, i):
        return self.data[i]

    def _binop(self, other, op):
        if isinstance(other, Vec):
            return Vec([op(a, b) for a, b in zip(self.data, other.data, strict=False)])
        return Vec([op(a, other) for a in self.data])

    def _rbinop(self, other, op):
        return Vec([op(other, a) for a in self.data])

    def __add__(self, o):
        return self._binop(o, lambda a, b: a + b)

    def __radd__(self, o):
        return self._rbinop(o, lambda a, b: a + b)

    def __sub__(self, o):
        return self._binop(o, lambda a, b: a - b)

    def __rsub__(self, o):
        return self._rbinop(o, lambda a, b: a - b)

    def __mul__(self, o):
        return self._binop(o, lambda a, b: a * b)

    def __rmul__(self, o):
        return self._rbinop(o, lambda a, b: a * b)

    def __truediv__(self, o):
        return self._binop(o, lambda a, b: a / b)

    def __rtruediv__(self, o):
        return self._rbinop(o, lambda a, b: a / b)

    def __pow__(self, o):
        return self._binop(o, lambda a, b: a**b)

    def __rpow__(self, o):
        return self._rbinop(o, lambda a, b: a**b)

    def __neg__(self):
        return Vec([-a for a in self.data])

    def __abs__(self):
        return Vec([abs(a) for a in self.data])


def SUM(x):
    if isinstance(x, Vec):
        return sum(x.data)
    return float(x)


def AVG(x):
    if isinstance(x, Vec):
        return sum(x.data) / len(x.data) if x.data else 0.0
    return float(x)


def MIN(x):
    if isinstance(x, Vec):
        return min(x.data)
    return float(x)


def MAX(x):
    if isinstance(x, Vec):
        return max(x.data)
    return float(x)


def COUNT(x):
    if isinstance(x, Vec):
        return len(x.data)
    return 1


def ABS(x):
    if isinstance(x, Vec):
        return Vec([abs(a) for a in x.data])
    return abs(x)


def SQRT(x):
    if isinstance(x, Vec):
        return Vec([math.sqrt(a) for a in x.data])
    return math.sqrt(x)


def INT(x):
    if isinstance(x, Vec):
        return Vec([int(a) for a in x.data])
    return int(x)


def _make_eval_globals():
    g = {
        "__builtins__": {
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "len": len,
            "int": int,
            "float": float,
            "round": round,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "map": map,
            "filter": filter,
            "list": list,
            "tuple": tuple,
            "True": True,
            "False": False,
            "None": None,
            "isinstance": isinstance,
        },
        "math": math,
        "Vec": Vec,
        "SUM": SUM,
        "AVG": AVG,
        "MIN": MIN,
        "MAX": MAX,
        "COUNT": COUNT,
        "ABS": ABS,
        "SQRT": SQRT,
        "INT": INT,
        "pi": math.pi,
        "e": math.e,
        "inf": math.inf,
        "nan": math.nan,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
        "atan2": math.atan2,
        "exp": math.exp,
        "log": math.log,
        "log2": math.log2,
        "log10": math.log10,
        "floor": math.floor,
        "ceil": math.ceil,
        "fabs": math.fabs,
        "fsum": math.fsum,
        "isnan": math.isnan,
        "isinf": math.isinf,
        "degrees": math.degrees,
        "radians": math.radians,
    }
    return g


class Cell:
    __slots__ = ("type", "val", "arr", "text", "fmt", "bold", "underline", "italic", "fmtstr")

    def __init__(self):
        self.type = EMPTY
        self.val = 0.0
        self.arr = None
        self.text = ""
        self.fmt = 0
        self.bold = 0
        self.underline = 0
        self.italic = 0
        self.fmtstr = ""

    def clear(self):
        self.type = EMPTY
        self.val = 0.0
        self.arr = None
        self.text = ""
        self.fmt = 0
        self.bold = 0
        self.underline = 0
        self.italic = 0
        self.fmtstr = ""

    def copy_from(self, src):
        self.type = src.type
        self.val = src.val
        self.arr = list(src.arr) if src.arr is not None else None
        self.text = src.text
        self.fmt = src.fmt
        self.bold = src.bold
        self.underline = src.underline
        self.italic = src.italic
        self.fmtstr = src.fmtstr

    def snapshot(self):
        c = Cell()
        c.copy_from(self)
        return c


class NamedRange:
    __slots__ = ("name", "c1", "r1", "c2", "r2")

    def __init__(self, name="", c1=0, r1=0, c2=0, r2=0):
        self.name = name
        self.c1 = c1
        self.r1 = r1
        self.c2 = c2
        self.r2 = r2


_REF_RE = re.compile(r"(\$?)([A-Za-z]{1,2})(\$?)(\d+)")


def refabs(s):
    """Parse a cell reference at the start of string s.
    Returns (chars_consumed, col, row, abs_col, abs_row) or None."""
    m = _REF_RE.match(s)
    if not m:
        return None
    absc = 1 if m.group(1) == "$" else 0
    letters = m.group(2).upper()
    absr = 1 if m.group(3) == "$" else 0
    rownum = int(m.group(4))
    if rownum <= 0:
        return None
    col = 0
    for ch in letters:
        col = col * 26 + (ord(ch) - ord("A") + 1)
    col -= 1
    row = rownum - 1
    return (m.end(), col, row, absc, absr)


def ref(s):
    """Parse a cell reference. Returns (chars_consumed, col, row) or None."""
    result = refabs(s)
    if result is None:
        return None
    n, col, row, _, _ = result
    return (n, col, row)


def col_name(c):
    if c < 26:
        return chr(ord("A") + c)
    return chr(ord("A") + c // 26 - 1) + chr(ord("A") + c % 26)


def cellname(c, r):
    return f"{col_name(c)}{r + 1}"


def _emitref(rc, rr, ac, ar):
    s = ""
    if ac:
        s += "$"
    s += col_name(rc)
    if ar:
        s += "$"
    s += str(rr + 1)
    return s


def _insert_commas(s):
    neg = s.startswith("-")
    digits = s[1:] if neg else s
    result = []
    for i, ch in enumerate(digits):
        if i > 0 and (len(digits) - i) % 3 == 0:
            result.append(",")
        result.append(ch)
    return ("-" if neg else "") + "".join(result)


def fmt_float(val, spec):
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
        prec = 6

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


def _expand_ranges(expr):
    """Expand A1:B3 range syntax into Vec([A1,A2,...]) calls."""
    result = []
    i = 0
    while i < len(expr):
        r1 = ref(expr[i:])
        if r1:
            n1, c1, row1 = r1
            if i + n1 < len(expr) and expr[i + n1] == ":":
                r2 = ref(expr[i + n1 + 1 :])
                if r2:
                    n2, c2, row2 = r2
                    if c1 > c2:
                        c1, c2 = c2, c1
                    if row1 > row2:
                        row1, row2 = row2, row1
                    cells = []
                    for r in range(row1, row2 + 1):
                        for c in range(c1, c2 + 1):
                            cells.append(cellname(c, r))
                    result.append("Vec([" + ",".join(cells) + "])")
                    i += n1 + 1 + n2
                    continue
        result.append(expr[i])
        i += 1
    return "".join(result)


class Grid:
    def __init__(self):
        self.cells = [[Cell() for _ in range(NROW)] for _ in range(NCOL)]
        self.cc = 0
        self.cr = 0
        self.vc = 0
        self.vr = 0
        self.tc = 0
        self.tr = 0
        self.fmt = 0
        self.dirty = 0
        self.cw = CW_DEFAULT
        self.filename = None
        self.names = []
        self.code = ""
        self.mc = -1
        self.mr = -1
        self._eval_globals = _make_eval_globals()

    def cell(self, c, r):
        if 0 <= c < NCOL and 0 <= r < NROW:
            return self.cells[c][r]
        return None

    def setcell(self, c, r, text):
        cl = self.cell(c, r)
        if cl is None:
            return
        if not text:
            cl.clear()
            self.recalc()
            return

        cl.arr = None
        cl.text = text
        self.dirty = 1

        if text.startswith("="):
            cl.type = FORMULA
        elif (
            text[0].isdigit()
            or text[0] == "."
            or (text[0] in "+-" and len(text) > 1 and (text[1].isdigit() or text[1] == "."))
        ):
            try:
                cl.val = float(text)
                cl.type = NUM
            except ValueError:
                cl.type = LABEL
                cl.val = 0
        else:
            cl.type = LABEL
            cl.val = 0

        self.recalc()

    def recalc(self):
        g = self._eval_globals

        if self.code:
            with contextlib.suppress(Exception):
                exec(self.code, g)

        for _ in range(100):
            changed = False

            # Inject cell values
            for r in range(NROW):
                for c in range(NCOL):
                    cl = self.cells[c][r]
                    if cl.type == EMPTY or cl.type == LABEL:
                        continue
                    name = cellname(c, r)
                    if cl.arr is not None and len(cl.arr) > 0:
                        g[name] = Vec(cl.arr)
                    else:
                        g[name] = cl.val

            # Inject named ranges
            for nr in self.names:
                data = []
                for r in range(nr.r1, nr.r2 + 1):
                    for c in range(nr.c1, nr.c2 + 1):
                        cl = self.cell(c, r)
                        if cl and cl.type not in (EMPTY, LABEL):
                            data.append(cl.val)
                        else:
                            data.append(0.0)
                g[nr.name] = Vec(data)

            # Evaluate formulas
            for r in range(NROW):
                for c in range(NCOL):
                    cl = self.cells[c][r]
                    if cl.type != FORMULA:
                        continue
                    formula = cl.text
                    if formula.startswith("="):
                        formula = formula[1:]
                    # Strip $ signs
                    stripped = formula.replace("$", "")
                    evalbuf = _expand_ranges(stripped)
                    oldval = cl.val
                    try:
                        result = eval(evalbuf, g)  # noqa: S307
                        if isinstance(result, Vec):
                            cl.arr = list(result.data)
                            cl.val = result.data[0] if result.data else float("nan")
                        else:
                            cl.arr = None
                            cl.val = float(result)
                    except Exception:
                        cl.arr = None
                        cl.val = float("nan")
                    both_nan = (
                        isinstance(cl.val, float)
                        and math.isnan(cl.val)
                        and isinstance(oldval, float)
                        and math.isnan(oldval)
                    )
                    if cl.val != oldval and not both_nan:
                        changed = True

            if not changed:
                break

    def _fixrefs(self, axis, a, b):
        for r in range(NROW):
            for c in range(NCOL):
                cl = self.cells[c][r]
                if cl.type != FORMULA:
                    continue
                out = []
                s = cl.text
                i = 0
                changed_flag = False
                while i < len(s):
                    result = refabs(s[i:])
                    if result:
                        n, rc, rr, ac, ar = result
                        if axis == "R":
                            if rr == a:
                                rr = b
                                changed_flag = True
                            elif rr == b:
                                rr = a
                                changed_flag = True
                        else:
                            if rc == a:
                                rc = b
                                changed_flag = True
                            elif rc == b:
                                rc = a
                                changed_flag = True
                        out.append(_emitref(rc, rr, ac, ar))
                        i += n
                    else:
                        out.append(s[i])
                        i += 1
                if changed_flag:
                    cl.text = "".join(out)

    def _shiftrefs(self, axis, pos, direction):
        for r in range(NROW):
            for c in range(NCOL):
                cl = self.cells[c][r]
                if cl.type != FORMULA:
                    continue
                out = []
                s = cl.text
                i = 0
                changed_flag = False
                while i < len(s):
                    result = refabs(s[i:])
                    if result:
                        n, rc, rr, ac, ar = result
                        if axis == "R":
                            if direction > 0 and rr >= pos:
                                rr += 1
                                changed_flag = True
                            elif direction < 0 and rr > pos:
                                rr -= 1
                                changed_flag = True
                        else:
                            if direction > 0 and rc >= pos:
                                rc += 1
                                changed_flag = True
                            elif direction < 0 and rc > pos:
                                rc -= 1
                                changed_flag = True
                        out.append(_emitref(rc, rr, ac, ar))
                        i += n
                    else:
                        out.append(s[i])
                        i += 1
                if changed_flag:
                    cl.text = "".join(out)

    def insertrow(self, at):
        for c in range(NCOL):
            self.cells[c][NROW - 1].clear()
            for r in range(NROW - 1, at, -1):
                self.cells[c][r].copy_from(self.cells[c][r - 1])
            self.cells[c][at].clear()
        self._shiftrefs("R", at, +1)
        self.dirty = 1

    def insertcol(self, at):
        for r in range(NROW):
            self.cells[NCOL - 1][r].clear()
            for c in range(NCOL - 1, at, -1):
                self.cells[c][r].copy_from(self.cells[c - 1][r])
            self.cells[at][r].clear()
        self._shiftrefs("C", at, +1)
        self.dirty = 1

    def deleterow(self, at):
        self._shiftrefs("R", at, -1)
        for c in range(NCOL):
            self.cells[c][at].clear()
            for r in range(at, NROW - 1):
                self.cells[c][r].copy_from(self.cells[c][r + 1])
            self.cells[c][NROW - 1].clear()
        self.dirty = 1

    def deletecol(self, at):
        self._shiftrefs("C", at, -1)
        for r in range(NROW):
            self.cells[at][r].clear()
            for c in range(at, NCOL - 1):
                self.cells[c][r].copy_from(self.cells[c + 1][r])
            self.cells[NCOL - 1][r].clear()
        self.dirty = 1

    def swaprow(self, a, b):
        for c in range(NCOL):
            ca = self.cells[c][a].snapshot()
            self.cells[c][a].copy_from(self.cells[c][b])
            self.cells[c][b].copy_from(ca)
        self._fixrefs("R", a, b)

    def swapcol(self, a, b):
        for r in range(NROW):
            ca = self.cells[a][r].snapshot()
            self.cells[a][r].copy_from(self.cells[b][r])
            self.cells[b][r].copy_from(ca)
        self._fixrefs("C", a, b)

    def replicatecell(self, sc, sr, dc, dr):
        src = self.cell(sc, sr)
        dst = self.cell(dc, dr)
        if not src or not dst:
            return
        if src.type == EMPTY:
            dst.clear()
            return
        dst.copy_from(src)
        if src.type != FORMULA:
            return

        dcol = dc - sc
        drow = dr - sr
        out = []
        s = src.text
        i = 0
        while i < len(s):
            result = refabs(s[i:])
            if result:
                n, rc, rr, ac, ar = result
                if not ac:
                    rc += dcol
                if not ar:
                    rr += drow
                out.append(_emitref(rc, rr, ac, ar))
                i += n
            else:
                out.append(s[i])
                i += 1
        dst.text = "".join(out)

    def fmtcell(self, cl, cw):
        if cl is None or cl.type == EMPTY:
            return " " * cw

        if cl.type == LABEL:
            t = cl.text
            if t.startswith('"'):
                t = t[1:]
            return f"{t:<{cw}}"[:cw]

        if isinstance(cl.val, float) and math.isnan(cl.val):
            return f"{'ERROR':>{cw}}"

        if cl.arr is not None and len(cl.arr) > 0:
            v = cl.arr[0]
            numstr = str(int(v)) if v == int(v) and abs(v) < 1e9 else f"{v:g}"
            t = f"{numstr}[{len(cl.arr)}]"
            return f"{t:>{cw}}"[:cw]

        if cl.fmtstr:
            formatted = fmt_float(cl.val, cl.fmtstr)
            if formatted is not None:
                return f"{formatted:>{cw}}"[:cw]

        fmt_code = cl.fmt
        if not fmt_code or fmt_code == ord("D"):
            fmt_code = self.fmt

        if isinstance(fmt_code, str):
            fmt_code = ord(fmt_code) if fmt_code else 0

        if fmt_code == ord("$"):
            t = f"{cl.val:.2f}"
        elif fmt_code == ord("%"):
            t = f"{cl.val * 100:.2f}%"
        elif fmt_code == ord("*"):
            bar_len = min(cw, max(0, int(cl.val)))
            t = "*" * bar_len
            return f"{t:<{cw}}"[:cw]
        elif fmt_code == ord("I") or (cl.val == int(cl.val) and abs(cl.val) < 1e9):
            t = str(int(cl.val))
        else:
            t = f"{cl.val:g}"

        if fmt_code == ord("L"):
            return f"{t:<{cw}}"[:cw]
        return f"{t:>{cw}}"[:cw]

    def fmtrange(self, c1, r1, c2, r2):
        if c1 == c2 and r1 == r2:
            return cellname(c1, r1)
        a = cellname(c1, r1)
        return f"{a}...{col_name(c2)}{r2 + 1}"

    def jsonload(self, filename):
        try:
            with open(filename) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            return -1

        self.code = d.get("code", "")

        names_dict = d.get("names", {})
        self.names = []
        for name, rng in names_dict.items():
            nr = NamedRange(name=name)
            r = ref(rng)
            if r:
                n, c1, r1 = r
                nr.c1 = c1
                nr.r1 = r1
                rest = rng[n:]
                if rest.startswith(":"):
                    r2 = ref(rest[1:])
                    if r2:
                        _, c2, row2 = r2
                        nr.c2 = c2
                        nr.r2 = row2
                    else:
                        nr.c2 = c1
                        nr.r2 = r1
                else:
                    nr.c2 = c1
                    nr.r2 = r1
                self.names.append(nr)

        fmt_dict = d.get("format", {})
        w = fmt_dict.get("width", 0)
        if 4 <= w <= 40:
            self.cw = int(w)
        elif not self.cw:
            self.cw = CW_DEFAULT

        rows = d.get("cells", [])
        for r_idx, row in enumerate(rows):
            if r_idx >= NROW or not isinstance(row, list):
                continue
            for c_idx, v in enumerate(row):
                if c_idx >= NCOL:
                    break
                cell_bold = 0
                cell_underline = 0
                cell_italic = 0
                cell_fmt = 0
                cell_fmtstr = ""
                if isinstance(v, dict):
                    cell_bold = 1 if v.get("bold") else 0
                    cell_underline = 1 if v.get("underline") else 0
                    cell_italic = 1 if v.get("italic") else 0
                    fmt_val = v.get("fmt", "")
                    if fmt_val:
                        cell_fmt = ord(fmt_val[0])
                    cell_fmtstr = v.get("fmtstr", "")
                    v = v.get("v", None)
                if v is None or (isinstance(v, str) and v == ""):
                    continue
                if isinstance(v, str):
                    text = v
                elif isinstance(v, (int, float)):
                    if isinstance(v, int) or (v == int(v) and abs(v) < 1e15):
                        text = str(int(v))
                    else:
                        text = f"{v:g}"
                else:
                    continue
                self.setcell(c_idx, r_idx, text)
                cl = self.cells[c_idx][r_idx]
                cl.bold = cell_bold
                cl.underline = cell_underline
                cl.italic = cell_italic
                cl.fmt = cell_fmt
                cl.fmtstr = cell_fmtstr

        return 0

    def jsonsave(self, filename):
        maxr = -1
        maxc = -1
        for r in range(NROW):
            for c in range(NCOL):
                if self.cells[c][r].type != EMPTY:
                    if r > maxr:
                        maxr = r
                    if c > maxc:
                        maxc = c

        out: dict[str, Any] = {}

        if self.code:
            out["code"] = self.code

        if self.names:
            out["names"] = {}
            for nr in self.names:
                a = cellname(nr.c1, nr.r1)
                rng = f"{a}:{col_name(nr.c2)}{nr.r2 + 1}"
                out["names"][nr.name] = rng

        out["format"] = {"width": self.cw}

        rows: list[list[Any]] = []
        for r in range(maxr + 1):
            row: list[Any] = []
            for c in range(maxc + 1):
                cl = self.cells[c][r]
                if cl.type == EMPTY:
                    row.append(None)
                elif cl.type == NUM:
                    if cl.val == int(cl.val) and abs(cl.val) < 1e15:
                        val: Any = int(cl.val)
                    else:
                        val = cl.val
                    row.append(val)
                else:
                    row.append(cl.text)

                has_style = cl.bold or cl.underline or cl.italic or cl.fmt or cl.fmtstr
                if cl.type != EMPTY and has_style:
                    styled: dict[str, Any] = {"v": row[-1]}
                    if cl.bold:
                        styled["bold"] = True
                    if cl.underline:
                        styled["underline"] = True
                    if cl.italic:
                        styled["italic"] = True
                    if cl.fmt:
                        styled["fmt"] = chr(cl.fmt) if isinstance(cl.fmt, int) else cl.fmt
                    if cl.fmtstr:
                        styled["fmtstr"] = cl.fmtstr
                    row[-1] = styled
            rows.append(row)
        out["cells"] = rows

        try:
            with open(filename, "w") as f:
                json.dump(out, f, indent=2)
                f.write("\n")
        except OSError:
            return -1
        return 0
