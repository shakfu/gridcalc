from __future__ import annotations

import contextlib
import json
import math
import re
from collections.abc import Callable, Iterable, Iterator
from typing import Any

from .sandbox import load_modules, validate_formula

MAXIN = 256
NCOL = 256
NROW = 1024
MAXNAMES = 256
MAXCODE = 8192
CW_DEFAULT = 8
FILE_VERSION = 1

EMPTY = 0
NUM = 1
LABEL = 2
FORMULA = 3


class Vec:
    def __init__(self, data: Iterable[float]) -> None:
        self.data: list[float] = list(data)

    def __repr__(self) -> str:
        return "Vec(" + repr(self.data) + ")"

    def __len__(self) -> int:
        return len(self.data)

    def __iter__(self) -> Iterator[float]:
        return iter(self.data)

    def __getitem__(self, i: int) -> float:
        return self.data[i]

    def _binop(self, other: Vec | float, op: Callable[[float, float], float]) -> Vec:
        if isinstance(other, Vec):
            return Vec([op(a, b) for a, b in zip(self.data, other.data, strict=False)])
        return Vec([op(a, other) for a in self.data])

    def _rbinop(self, other: float, op: Callable[[float, float], float]) -> Vec:
        return Vec([op(other, a) for a in self.data])

    def __add__(self, o: Vec | float) -> Vec:
        return self._binop(o, lambda a, b: a + b)

    def __radd__(self, o: float) -> Vec:
        return self._rbinop(o, lambda a, b: a + b)

    def __sub__(self, o: Vec | float) -> Vec:
        return self._binop(o, lambda a, b: a - b)

    def __rsub__(self, o: float) -> Vec:
        return self._rbinop(o, lambda a, b: a - b)

    def __mul__(self, o: Vec | float) -> Vec:
        return self._binop(o, lambda a, b: a * b)

    def __rmul__(self, o: float) -> Vec:
        return self._rbinop(o, lambda a, b: a * b)

    def __truediv__(self, o: Vec | float) -> Vec:
        return self._binop(o, lambda a, b: a / b)

    def __rtruediv__(self, o: float) -> Vec:
        return self._rbinop(o, lambda a, b: a / b)

    def __pow__(self, o: Vec | float) -> Vec:
        return self._binop(o, lambda a, b: a**b)

    def __rpow__(self, o: float) -> Vec:
        return self._rbinop(o, lambda a, b: a**b)

    def __neg__(self) -> Vec:
        return Vec([-a for a in self.data])

    def __abs__(self) -> Vec:
        return Vec([abs(a) for a in self.data])


def SUM(x: Vec | float) -> float:
    if isinstance(x, Vec):
        return sum(x.data)
    return float(x)


def AVG(x: Vec | float) -> float:
    if isinstance(x, Vec):
        return sum(x.data) / len(x.data) if x.data else 0.0
    return float(x)


def MIN(x: Vec | float) -> float:
    if isinstance(x, Vec):
        return min(x.data)
    return float(x)


def MAX(x: Vec | float) -> float:
    if isinstance(x, Vec):
        return max(x.data)
    return float(x)


def COUNT(x: Vec | float) -> int | float:
    if isinstance(x, Vec):
        return len(x.data)
    return 1


def ABS(x: Vec | float) -> Vec | float:
    if isinstance(x, Vec):
        return Vec([abs(a) for a in x.data])
    return abs(x)


def SQRT(x: Vec | float) -> Vec | float:
    if isinstance(x, Vec):
        return Vec([math.sqrt(a) for a in x.data])
    return math.sqrt(x)


def INT(x: Vec | float) -> Vec | int:
    if isinstance(x, Vec):
        return Vec([int(a) for a in x.data])
    return int(x)


def _make_eval_globals() -> dict[str, Any]:
    g: dict[str, Any] = {
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

    def __init__(self) -> None:
        self.type: int = EMPTY
        self.val: float = 0.0
        self.arr: list[float] | None = None
        self.text: str = ""
        self.fmt: str = ""
        self.bold: int = 0
        self.underline: int = 0
        self.italic: int = 0
        self.fmtstr: str = ""

    def clear(self) -> None:
        self.type = EMPTY
        self.val = 0.0
        self.arr = None
        self.text = ""
        self.fmt = ""
        self.bold = 0
        self.underline = 0
        self.italic = 0
        self.fmtstr = ""

    def copy_from(self, src: Cell) -> None:
        self.type = src.type
        self.val = src.val
        self.arr = list(src.arr) if src.arr is not None else None
        self.text = src.text
        self.fmt = src.fmt
        self.bold = src.bold
        self.underline = src.underline
        self.italic = src.italic
        self.fmtstr = src.fmtstr

    def snapshot(self) -> Cell:
        c = Cell()
        c.copy_from(self)
        return c


class NamedRange:
    __slots__ = ("name", "c1", "r1", "c2", "r2")

    def __init__(self, name: str = "", c1: int = 0, r1: int = 0, c2: int = 0, r2: int = 0) -> None:
        self.name = name
        self.c1 = c1
        self.r1 = r1
        self.c2 = c2
        self.r2 = r2


_REF_RE = re.compile(r"(\$?)([A-Za-z]{1,2})(\$?)(\d+)")


def refabs(s: str) -> tuple[int, int, int, int, int] | None:
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


def ref(s: str) -> tuple[int, int, int] | None:
    """Parse a cell reference. Returns (chars_consumed, col, row) or None."""
    result = refabs(s)
    if result is None:
        return None
    n, col, row, _, _ = result
    return (n, col, row)


def col_name(c: int) -> str:
    if c < 26:
        return chr(ord("A") + c)
    return chr(ord("A") + c // 26 - 1) + chr(ord("A") + c % 26)


def cellname(c: int, r: int) -> str:
    return f"{col_name(c)}{r + 1}"


def _emitref(rc: int, rr: int, ac: int, ar: int) -> str:
    s = ""
    if ac:
        s += "$"
    s += col_name(rc)
    if ar:
        s += "$"
    s += str(rr + 1)
    return s


def _expand_ranges(expr: str) -> str:
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


# Shared sentinel for read access to unpopulated cells.
# Must never be mutated -- all mutation paths go through cells
# that already exist in the sparse dict (post-setcell).
_EMPTY_CELL = Cell()


class _ColProxy:
    """Emulates cells[c][r] access against the sparse dict."""

    __slots__ = ("_cells", "_c")

    def __init__(self, cells: dict[tuple[int, int], Cell], c: int) -> None:
        self._cells = cells
        self._c = c

    def __getitem__(self, r: int) -> Cell:
        return self._cells.get((self._c, r), _EMPTY_CELL)

    def __setitem__(self, r: int, value: Cell) -> None:
        self._cells[(self._c, r)] = value


class _CellsProxy:
    """Emulates the old cells[c][r] 2D-array interface over a sparse dict."""

    __slots__ = ("_cells",)

    def __init__(self, cells: dict[tuple[int, int], Cell]) -> None:
        self._cells = cells

    def __getitem__(self, c: int) -> _ColProxy:
        return _ColProxy(self._cells, c)


class Grid:
    def __init__(self) -> None:
        self._cells: dict[tuple[int, int], Cell] = {}
        self.cells: _CellsProxy = _CellsProxy(self._cells)
        self.cc: int = 0
        self.cr: int = 0
        self.vc: int = 0
        self.vr: int = 0
        self.tc: int = 0
        self.tr: int = 0
        self.fmt: str = ""
        self.dirty: int = 0
        self.cw: int = CW_DEFAULT
        self.filename: str | None = None
        self.names: list[NamedRange] = []
        self.code: str = ""
        self.mc: int = -1
        self.mr: int = -1
        self._eval_globals: dict[str, Any] = _make_eval_globals()
        self.requires: list[str] = []
        self.libs: list[str] = []
        self._module_errors: list[str] = []
        self._circular: set[tuple[int, int]] = set()

    def load_lib(self, name: str) -> None:
        """Load a formula lib's builtins into the eval namespace."""
        if not name:
            return
        from .libs import get_lib_builtins

        self._eval_globals.update(get_lib_builtins(name))

    def load_requires(self, modules: list[str]) -> None:
        """Load required modules into the eval namespace."""
        if not modules:
            return
        mods, errors = load_modules(modules)
        self._eval_globals.update(mods)
        self._module_errors = errors

    def cell(self, c: int, r: int) -> Cell | None:
        if 0 <= c < NCOL and 0 <= r < NROW:
            return self._cells.get((c, r))
        return None

    def _ensure_cell(self, c: int, r: int) -> Cell:
        """Return the cell at (c, r), creating it if it doesn't exist."""
        key = (c, r)
        cl = self._cells.get(key)
        if cl is None:
            cl = Cell()
            self._cells[key] = cl
        return cl

    def clear_all(self) -> None:
        """Remove all cells from the grid."""
        self._cells.clear()

    def setcell(self, c: int, r: int, text: str) -> None:
        if not (0 <= c < NCOL and 0 <= r < NROW):
            return
        if not text:
            self._cells.pop((c, r), None)
            self.recalc()
            return

        cl = self._ensure_cell(c, r)
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

    def recalc(self) -> None:
        g = self._eval_globals
        self._circular = set()

        if self.code:
            with contextlib.suppress(Exception):
                exec(self.code, g)

        changed_cells: set[tuple[int, int]] = set()
        for _ in range(100):
            changed_cells.clear()

            # Inject cell values (only populated cells)
            for (c, r), cl in self._cells.items():
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
                        cl2 = self._cells.get((c, r))
                        if cl2 and cl2.type not in (EMPTY, LABEL):
                            data.append(cl2.val)
                        else:
                            data.append(0.0)
                g[nr.name] = Vec(data)

            # Evaluate formulas (only formula cells)
            for (fc, fr), cl in self._cells.items():
                if cl.type != FORMULA:
                    continue
                formula = cl.text
                if formula.startswith("="):
                    formula = formula[1:]
                # Strip $ signs
                stripped = formula.replace("$", "")
                evalbuf = _expand_ranges(stripped)
                oldval = cl.val
                valid, _ = validate_formula(evalbuf)
                if not valid:
                    cl.arr = None
                    cl.val = float("nan")
                else:
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
                    changed_cells.add((fc, fr))

            if not changed_cells:
                break

        # Mark cells that never stabilized as circular references
        if changed_cells:
            self._circular = set(changed_cells)

        # Detect stable self-references (cells whose formula references
        # their own value, directly or via range, but converge at 0)
        for (c, r), cl in self._cells.items():
            if cl.type != FORMULA:
                continue
            name = cellname(c, r)
            formula = cl.text[1:] if cl.text.startswith("=") else cl.text
            expanded = _expand_ranges(formula.replace("$", ""))
            if re.search(r"\b" + re.escape(name) + r"\b", expanded):
                self._circular.add((c, r))

        if self._circular:
            for pos in self._circular:
                circ = self._cells.get(pos)
                if circ:
                    circ.arr = None
                    circ.val = float("nan")

    def _fixrefs(self, axis: str, a: int, b: int) -> None:
        for cl in self._cells.values():
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

    def _shiftrefs(self, axis: str, pos: int, direction: int) -> None:
        for cl in self._cells.values():
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

    def insertrow(self, at: int) -> None:
        new_cells: dict[tuple[int, int], Cell] = {}
        for (c, r), cl in self._cells.items():
            if r >= at:
                if r + 1 < NROW:
                    new_cells[(c, r + 1)] = cl
            else:
                new_cells[(c, r)] = cl
        self._cells = new_cells
        self.cells = _CellsProxy(self._cells)
        self._shiftrefs("R", at, +1)
        self.dirty = 1

    def insertcol(self, at: int) -> None:
        new_cells: dict[tuple[int, int], Cell] = {}
        for (c, r), cl in self._cells.items():
            if c >= at:
                if c + 1 < NCOL:
                    new_cells[(c + 1, r)] = cl
            else:
                new_cells[(c, r)] = cl
        self._cells = new_cells
        self.cells = _CellsProxy(self._cells)
        self._shiftrefs("C", at, +1)
        self.dirty = 1

    def deleterow(self, at: int) -> None:
        self._shiftrefs("R", at, -1)
        new_cells: dict[tuple[int, int], Cell] = {}
        for (c, r), cl in self._cells.items():
            if r == at:
                continue
            elif r > at:
                new_cells[(c, r - 1)] = cl
            else:
                new_cells[(c, r)] = cl
        self._cells = new_cells
        self.cells = _CellsProxy(self._cells)
        self.dirty = 1

    def deletecol(self, at: int) -> None:
        self._shiftrefs("C", at, -1)
        new_cells: dict[tuple[int, int], Cell] = {}
        for (c, r), cl in self._cells.items():
            if c == at:
                continue
            elif c > at:
                new_cells[(c - 1, r)] = cl
            else:
                new_cells[(c, r)] = cl
        self._cells = new_cells
        self.cells = _CellsProxy(self._cells)
        self.dirty = 1

    def swaprow(self, a: int, b: int) -> None:
        new_cells: dict[tuple[int, int], Cell] = {}
        for (c, r), cl in self._cells.items():
            if r == a:
                new_cells[(c, b)] = cl
            elif r == b:
                new_cells[(c, a)] = cl
            else:
                new_cells[(c, r)] = cl
        self._cells = new_cells
        self.cells = _CellsProxy(self._cells)
        self._fixrefs("R", a, b)

    def swapcol(self, a: int, b: int) -> None:
        new_cells: dict[tuple[int, int], Cell] = {}
        for (c, r), cl in self._cells.items():
            if c == a:
                new_cells[(b, r)] = cl
            elif c == b:
                new_cells[(a, r)] = cl
            else:
                new_cells[(c, r)] = cl
        self._cells = new_cells
        self.cells = _CellsProxy(self._cells)
        self._fixrefs("C", a, b)

    def replicatecell(self, sc: int, sr: int, dc: int, dr: int) -> None:
        if not (0 <= dc < NCOL and 0 <= dr < NROW):
            return
        src = self.cell(sc, sr)
        if not src:
            # Source is empty -- clear destination
            self._cells.pop((dc, dr), None)
            return
        dst = self._ensure_cell(dc, dr)
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

    def fmtrange(self, c1: int, r1: int, c2: int, r2: int) -> str:
        if c1 == c2 and r1 == r2:
            return cellname(c1, r1)
        a = cellname(c1, r1)
        return f"{a}...{col_name(c2)}{r2 + 1}"

    def jsonload(self, filename: str, policy: Any = None) -> int:
        try:
            with open(filename) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            return -1

        version = d.get("version", 1)
        if not isinstance(version, int) or version > FILE_VERSION:
            return -1

        code = d.get("code", "")
        if policy is None or policy.load_code:
            self.code = code

        libs = d.get("libs", [])
        if isinstance(libs, list):
            self.libs = [str(lib) for lib in libs]
            for lib in self.libs:
                self.load_lib(lib)

        requires = d.get("requires", [])
        if isinstance(requires, list):
            self.requires = requires
            approved = requires if policy is None else policy.approved_modules
            if approved:
                self.load_requires(approved)

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
                cell_fmt = ""
                cell_fmtstr = ""
                if isinstance(v, dict):
                    cell_bold = 1 if v.get("bold") else 0
                    cell_underline = 1 if v.get("underline") else 0
                    cell_italic = 1 if v.get("italic") else 0
                    fmt_val = v.get("fmt", "")
                    if fmt_val:
                        cell_fmt = fmt_val[0]
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
                cl = self._cells.get((c_idx, r_idx))
                if not cl:
                    continue
                cl.bold = cell_bold
                cl.underline = cell_underline
                cl.italic = cell_italic
                cl.fmt = cell_fmt
                cl.fmtstr = cell_fmtstr

        return 0

    def jsonsave(self, filename: str) -> int:
        maxr = -1
        maxc = -1
        for (c, r), cl in self._cells.items():
            if cl.type != EMPTY:
                if r > maxr:
                    maxr = r
                if c > maxc:
                    maxc = c

        out: dict[str, Any] = {"version": FILE_VERSION}

        if self.libs:
            out["libs"] = self.libs

        if self.requires:
            out["requires"] = self.requires

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
                sc = self._cells.get((c, r))
                if not sc or sc.type == EMPTY:
                    row.append(None)
                    continue
                elif sc.type == NUM:
                    if sc.val == int(sc.val) and abs(sc.val) < 1e15:
                        val: Any = int(sc.val)
                    else:
                        val = sc.val
                    row.append(val)
                else:
                    row.append(sc.text)

                has_style = sc.bold or sc.underline or sc.italic or sc.fmt or sc.fmtstr
                if has_style:
                    styled: dict[str, Any] = {"v": row[-1]}
                    if sc.bold:
                        styled["bold"] = True
                    if sc.underline:
                        styled["underline"] = True
                    if sc.italic:
                        styled["italic"] = True
                    if sc.fmt:
                        styled["fmt"] = sc.fmt
                    if sc.fmtstr:
                        styled["fmtstr"] = sc.fmtstr
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
