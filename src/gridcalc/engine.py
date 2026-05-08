from __future__ import annotations

import contextlib
import csv
import json
import math
import re
from collections.abc import Callable, Iterable, Iterator
from enum import IntEnum
from io import StringIO
from typing import Any

from .sandbox import load_modules, validate_code, validate_formula


class Mode(IntEnum):
    EXCEL = 1
    HYBRID = 2
    LEGACY = 3

    @classmethod
    def parse(cls, value: object) -> Mode | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int) and value in (1, 2, 3):
            return cls(value)
        if isinstance(value, str):
            s = value.strip().lower()
            if s in ("1", "excel"):
                return cls.EXCEL
            if s in ("2", "hybrid"):
                return cls.HYBRID
            if s in ("3", "legacy"):
                return cls.LEGACY
        return None


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


def _is_ndarray(obj: object) -> bool:
    """Check if obj is a numpy ndarray without importing numpy."""
    return type(obj).__module__ == "numpy" and type(obj).__name__ == "ndarray"


def _is_dataframe(obj: object) -> bool:
    """Check if obj is a pandas DataFrame without importing pandas."""
    mod = type(obj).__module__
    name = type(obj).__name__
    return mod.startswith("pandas") and name == "DataFrame"


def _is_series(obj: object) -> bool:
    """Check if obj is a pandas Series without importing pandas."""
    mod = type(obj).__module__
    name = type(obj).__name__
    return mod.startswith("pandas") and name == "Series"


def _is_num(v: Any) -> bool:
    """True for real numerics; bools excluded (Excel ranges don't auto-coerce)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _unary_or_error(a: Any, op: Callable[[float], float]) -> Any:
    from .formula.errors import ExcelError

    if isinstance(a, ExcelError):
        return a
    if not _is_num(a):
        return ExcelError.VALUE
    return op(float(a))


def _vec_elem_op(a: Any, b: Any, op: Callable[[float, float], Any]) -> Any:
    """Per-element binary op with Excel-style type guard.

    ExcelError on either side propagates. Mixed numeric/non-numeric -> #VALUE!.
    """
    from .formula.errors import ExcelError

    if isinstance(a, ExcelError):
        return a
    if isinstance(b, ExcelError):
        return b
    if not (_is_num(a) and _is_num(b)):
        return ExcelError.VALUE
    try:
        r = op(float(a), float(b))
    except ZeroDivisionError:
        return ExcelError.DIV0
    except (ValueError, OverflowError, ArithmeticError):
        return ExcelError.NUM
    if isinstance(r, complex):
        return ExcelError.NUM
    return r


class Vec:
    def __init__(self, data: Iterable[Any], cols: int | None = None) -> None:
        self.data: list[Any] = list(data)
        # Number of columns when this Vec materialises a 2D range (row-major).
        # None means shape is unknown / treat as 1D. Set by _eval_range when
        # building from a RangeRef so INDEX(rng, row, col) can re-index.
        self.cols: int | None = cols

    def __repr__(self) -> str:
        if self.is_2d:
            return f"Vec[{self.rows}x{self.cols}]({self.data!r})"
        return "Vec(" + repr(self.data) + ")"

    def __len__(self) -> int:
        return len(self.data)

    def __iter__(self) -> Iterator[Any]:
        return iter(self.data)

    def __getitem__(self, i: int) -> Any:
        return self.data[i]

    # -- Shape API (Phase 1: read-only views, no behaviour change) --

    @property
    def is_2d(self) -> bool:
        return self.cols is not None and self.cols > 0

    @property
    def rows(self) -> int:
        """Row count. For 1D Vecs this is the flat length."""
        if not self.is_2d:
            return len(self.data)
        assert self.cols is not None  # noqa: S101 -- type-narrowing after is_2d guard
        return len(self.data) // self.cols

    @property
    def shape(self) -> tuple[int, int]:
        """``(rows, cols)``. 1D Vecs report ``(len, 1)``."""
        if not self.is_2d:
            return (len(self.data), 1)
        assert self.cols is not None  # noqa: S101 -- type-narrowing after is_2d guard
        return (len(self.data) // self.cols, self.cols)

    def at(self, r: int, c: int) -> Any:
        """1-based 2D access. Treats a 1D Vec as a column vector (n×1)
        so ``at(i, 1)`` walks the flat data."""
        rows, cols = self.shape
        if not 1 <= r <= rows or not 1 <= c <= cols:
            raise IndexError(f"Vec.at({r},{c}) out of range for shape {self.shape}")
        if not self.is_2d:
            return self.data[r - 1]
        assert self.cols is not None  # noqa: S101 -- type-narrowing after is_2d guard
        return self.data[(r - 1) * self.cols + (c - 1)]

    def row(self, i: int) -> Vec:
        """1-based row extraction. Returns a 1D Vec.

        A 1D Vec is treated as a column vector (n×1), so ``row(i)``
        returns a 1-element Vec for valid ``i``.
        """
        rows, _ = self.shape
        if not 1 <= i <= rows:
            raise IndexError(f"Vec.row({i}) out of range for shape {self.shape}")
        if not self.is_2d:
            return Vec([self.data[i - 1]])
        assert self.cols is not None  # noqa: S101 -- type-narrowing after is_2d guard
        start = (i - 1) * self.cols
        return Vec(self.data[start : start + self.cols])

    def col(self, j: int) -> Vec:
        """1-based column extraction. Returns a 1D Vec.

        A 1D Vec is treated as a column vector (n×1), so ``col(1)``
        returns the whole vec; other indices raise.
        """
        _, cols = self.shape
        if not 1 <= j <= cols:
            raise IndexError(f"Vec.col({j}) out of range for shape {self.shape}")
        if not self.is_2d:
            return Vec(list(self.data))
        assert self.cols is not None  # noqa: S101 -- type-narrowing after is_2d guard
        return Vec([self.data[i * self.cols + (j - 1)] for i in range(self.rows)])

    def iter_rows(self) -> Iterator[list[Any]]:
        """Iterate rows as plain ``list``s. A 1D Vec is treated as
        column-shaped (n×1), so each element yields its own 1-element row."""
        if not self.is_2d:
            for v in self.data:
                yield [v]
            return
        assert self.cols is not None  # noqa: S101 -- type-narrowing after is_2d guard
        for i in range(self.rows):
            yield list(self.data[i * self.cols : (i + 1) * self.cols])

    def _binop(self, other: Vec | float, op: Callable[[float, float], Any]) -> Vec:
        if isinstance(other, Vec):
            # Two 2D Vecs: shapes must match exactly; mismatch -> #VALUE!
            # per element. Otherwise pair element-wise; the result inherits
            # whichever side carries shape (or self.cols if both do).
            if self.is_2d and other.is_2d and self.shape != other.shape:
                from .formula.errors import ExcelError

                n = max(len(self.data), len(other.data))
                return Vec([ExcelError.VALUE] * n)
            out_cols = self.cols if self.is_2d else other.cols
            return Vec(
                [_vec_elem_op(a, b, op) for a, b in zip(self.data, other.data, strict=False)],
                cols=out_cols,
            )
        return Vec([_vec_elem_op(a, other, op) for a in self.data], cols=self.cols)

    def _rbinop(self, other: float, op: Callable[[float, float], Any]) -> Vec:
        return Vec([_vec_elem_op(other, a, op) for a in self.data], cols=self.cols)

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
        return Vec([_unary_or_error(a, lambda v: -v) for a in self.data], cols=self.cols)

    def __abs__(self) -> Vec:
        return Vec([_unary_or_error(a, abs) for a in self.data], cols=self.cols)


def _numeric_only(data: Iterable[Any]) -> list[float]:
    """Excel rule: SUM/AVG/MIN/MAX/COUNT skip text and bools-from-ranges."""
    return [float(v) for v in data if _is_num(v)]


def SUM(x: Any) -> float:
    if isinstance(x, Vec):
        return sum(_numeric_only(x.data))
    if _is_ndarray(x):
        return float(x.sum())
    if not _is_num(x):
        return 0.0
    return float(x)


def AVG(x: Any) -> float:
    if isinstance(x, Vec):
        nums = _numeric_only(x.data)
        return sum(nums) / len(nums) if nums else 0.0
    if _is_ndarray(x):
        return float(x.mean()) if x.size > 0 else 0.0
    if not _is_num(x):
        return 0.0
    return float(x)


def MIN(x: Any) -> float:
    if isinstance(x, Vec):
        nums = _numeric_only(x.data)
        return min(nums) if nums else 0.0
    if _is_ndarray(x):
        return float(x.min())
    if not _is_num(x):
        return 0.0
    return float(x)


def MAX(x: Any) -> float:
    if isinstance(x, Vec):
        nums = _numeric_only(x.data)
        return max(nums) if nums else 0.0
    if _is_ndarray(x):
        return float(x.max())
    if not _is_num(x):
        return 0.0
    return float(x)


def COUNT(x: Any) -> int | float:
    if isinstance(x, Vec):
        return len(_numeric_only(x.data))
    if _is_ndarray(x):
        return int(x.size)
    return 1 if _is_num(x) else 0


def _scalar_or_error(x: Any, op: Callable[[float], float]) -> Any:
    from .formula.errors import ExcelError

    if isinstance(x, ExcelError):
        return x
    if not _is_num(x):
        return ExcelError.VALUE
    try:
        return op(float(x))
    except (ValueError, OverflowError, ArithmeticError):
        return ExcelError.NUM


def _vec_per_elem(x: Vec, op: Callable[[float], float]) -> Vec:
    return Vec([_scalar_or_error(v, op) for v in x.data])


def ABS(x: Any) -> Any:
    if isinstance(x, Vec):
        return _vec_per_elem(x, abs)
    if _is_ndarray(x):
        return abs(x)
    return _scalar_or_error(x, abs)


def SQRT(x: Any) -> Any:
    if isinstance(x, Vec):
        return _vec_per_elem(x, math.sqrt)
    if _is_ndarray(x):
        import numpy as _np  # noqa: I001

        return _np.sqrt(x)
    return _scalar_or_error(x, math.sqrt)


def INT(x: Any) -> Any:
    if isinstance(x, Vec):
        return _vec_per_elem(x, lambda v: float(int(v)))
    if _is_ndarray(x):
        return x.astype(int)
    return _scalar_or_error(x, lambda v: float(int(v)))


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
    __slots__ = (
        "type",
        "val",
        "sval",
        "arr",
        "arr_cols",
        "matrix",
        "text",
        "fmt",
        "bold",
        "underline",
        "italic",
        "fmtstr",
        "ast",
        "ast_text",
    )

    def __init__(self) -> None:
        self.type: int = EMPTY
        self.val: float = 0.0
        self.sval: str | None = None
        self.arr: list[float] | None = None
        # When arr holds a 2D Vec result, arr_cols is the column count.
        # None means 1D (or no array).
        self.arr_cols: int | None = None
        self.matrix: Any = None
        self.text: str = ""
        self.fmt: str = ""
        self.bold: int = 0
        self.underline: int = 0
        self.italic: int = 0
        self.fmtstr: str = ""
        self.ast: Any = None
        self.ast_text: str = ""

    def clear(self) -> None:
        self.type = EMPTY
        self.val = 0.0
        self.sval = None
        self.arr = None
        self.arr_cols = None
        self.matrix = None
        self.text = ""
        self.fmt = ""
        self.bold = 0
        self.underline = 0
        self.italic = 0
        self.fmtstr = ""
        self.ast = None
        self.ast_text = ""

    def copy_from(self, src: Cell) -> None:
        self.type = src.type
        self.val = src.val
        self.sval = src.sval
        self.arr = list(src.arr) if src.arr is not None else None
        self.arr_cols = src.arr_cols
        self.matrix = src.matrix.copy() if src.matrix is not None else None
        self.text = src.text
        self.fmt = src.fmt
        self.bold = src.bold
        self.underline = src.underline
        self.italic = src.italic
        self.fmtstr = src.fmtstr
        self.ast = None
        self.ast_text = ""

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
                    # Normalise B1:A1 -> A1:B1. Matches Excel, which treats
                    # A1:B3 and B3:A1 as identical ranges.
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


def _xlsx_read_cells(filename: str) -> list[tuple[int, int, str]] | None:
    """Read xlsx via the OpenXLSX-backed `_core.xlsx_read`.

    Returns the list of (col0, row0, text) tuples, or None if the file cannot
    be opened.
    """
    from gridcalc import _core

    try:
        return list(_core.xlsx_read(filename))
    except Exception:
        return None


def _xlsx_write_cells(filename: str, cells: list[tuple[int, int, str, object]]) -> int:
    """Write (col0, row0, kind, value) tuples; kind in {'s','n'}.

    Returns 0 on success, -1 on failure.
    """
    from gridcalc import _core

    try:
        _core.xlsx_write(filename, cells)
        return 0
    except Exception:
        return -1


def _ast_has_pycall(node: Any) -> bool:
    from .formula.ast_nodes import (
        BinOp,
        Call,
        Percent,
        PyCall,
        UnaryOp,
    )

    if isinstance(node, PyCall):
        return True
    if isinstance(node, Call):
        return any(_ast_has_pycall(a) for a in node.args)
    if isinstance(node, BinOp):
        return _ast_has_pycall(node.left) or _ast_has_pycall(node.right)
    if isinstance(node, (UnaryOp, Percent)):
        return _ast_has_pycall(node.operand)
    return False


def _ast_uses_cell(node: Any, c: int, r: int) -> bool:
    from .formula.ast_nodes import (
        BinOp,
        Call,
        CellRef,
        Percent,
        PyCall,
        RangeRef,
        UnaryOp,
    )

    if isinstance(node, CellRef):
        return node.col == c and node.row == r
    if isinstance(node, RangeRef):
        c1, c2 = sorted([node.start.col, node.end.col])
        r1, r2 = sorted([node.start.row, node.end.row])
        return c1 <= c <= c2 and r1 <= r <= r2
    if isinstance(node, Call):
        from .formula.deps import ADDRESS_ONLY_FUNCS

        if node.name.upper() in ADDRESS_ONLY_FUNCS:
            return False  # ROW/COLUMN/ROWS/COLUMNS use addresses, not values
        return any(_ast_uses_cell(a, c, r) for a in node.args)
    if isinstance(node, PyCall):
        return any(_ast_uses_cell(a, c, r) for a in node.args)
    if isinstance(node, BinOp):
        return _ast_uses_cell(node.left, c, r) or _ast_uses_cell(node.right, c, r)
    if isinstance(node, (UnaryOp, Percent)):
        return _ast_uses_cell(node.operand, c, r)
    return False


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
        self.mode: Mode = Mode.LEGACY
        # Topological recalc bookkeeping. Off by default; opt-in via
        # `_use_topo_recalc = True`. Maintained alongside the fixed-point
        # path so flipping the flag is safe at any point.
        self._dep_of: dict[tuple[int, int], set[tuple[int, int]]] = {}
        self._subscribers: dict[tuple[int, int], set[tuple[int, int]]] = {}
        self._volatile: set[tuple[int, int]] = set()
        self._use_topo_recalc: bool = True
        # Set True by `_rebuild_dep_graph`; remains True while
        # `_refresh_deps`/`_clear_deps` maintain the graph incrementally.
        # Reset to False on mode entry into EXCEL/HYBRID (LEGACY skips
        # graph maintenance, so the graph is stale on mode transition).
        # `_recalc_topo` skips its rebuild call when this flag is True.
        self._dep_graph_built: bool = False

    def load_lib(self, name: str) -> None:
        """Load a formula lib's builtins into the eval namespace."""
        if not name:
            return
        from .libs import get_lib_builtins

        self._eval_globals.update(get_lib_builtins(name))

    def _apply_mode_libs(self) -> None:
        if self.mode in (Mode.EXCEL, Mode.HYBRID) and "xlsx" not in self.libs:
            self.libs.append("xlsx")
            self.load_lib("xlsx")

    def validate_for_mode(self, target: Mode) -> list[str]:
        if target == Mode.LEGACY:
            return []
        from .formula import parse
        from .formula.errors import FormulaError

        errors: list[str] = []
        if target == Mode.EXCEL and self.code:
            errors.append("EXCEL mode forbids code blocks; clear the code first")
        for (c, r), cl in self._cells.items():
            if cl.type != FORMULA:
                continue
            text = cl.text[1:] if cl.text.startswith("=") else cl.text
            try:
                ast = parse(text)
            except FormulaError as e:
                errors.append(f"{cellname(c, r)}: {e}")
                continue
            if target == Mode.EXCEL and _ast_has_pycall(ast):
                errors.append(f"{cellname(c, r)}: py.* calls not allowed in EXCEL")
        return errors

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
        self._dep_of.clear()
        self._subscribers.clear()
        self._volatile.clear()

    def _clear_deps(self, key: tuple[int, int]) -> None:
        """Drop `key` from forward + reverse indexes and the volatile set."""
        old = self._dep_of.pop(key, None)
        if old is not None:
            for d in old:
                subs = self._subscribers.get(d)
                if subs is not None:
                    subs.discard(key)
                    if not subs:
                        del self._subscribers[d]
        self._volatile.discard(key)

    def _register_deps(
        self, key: tuple[int, int], deps: set[tuple[int, int]], volatile: bool
    ) -> None:
        """Install forward + reverse edges for `key` from `deps`."""
        if deps:
            self._dep_of[key] = deps
            for d in deps:
                self._subscribers.setdefault(d, set()).add(key)
        if volatile:
            self._volatile.add(key)

    def _rebuild_dep_graph(self) -> None:
        """Discard `_dep_of`/`_subscribers`/`_volatile` and rebuild from scratch.

        Used when bulk operations move cells around in the grid (insert/
        delete row or column, swap, replicate) or when entering a mode
        whose recalc consumes the graph (EXCEL/HYBRID from LEGACY).
        Cost is O(formulas) -- a single AST walk per formula cell.
        """
        self._dep_of.clear()
        self._subscribers.clear()
        self._volatile.clear()
        for (c, r), cl in self._cells.items():
            if cl.type == FORMULA:
                self._refresh_deps(c, r, cl)
        self._dep_graph_built = True

    def _refresh_deps(self, c: int, r: int, cl: Cell) -> None:
        """Recompute the dep graph for one cell. Call after writing the cell.

        Parses the formula text if the AST cache is stale, extracts the
        static read set, and updates `_dep_of` / `_subscribers` / `_volatile`.
        Non-formula cells get their entries cleared. LEGACY mode skips
        graph maintenance entirely -- it uses fixed-point recalc, not topo.
        """
        if self.mode == Mode.LEGACY:
            return
        from .formula import parse
        from .formula.deps import extract_refs, has_dynamic_refs
        from .formula.errors import FormulaError

        key = (c, r)
        self._clear_deps(key)
        if cl.type != FORMULA:
            return
        text = cl.text[1:] if cl.text.startswith("=") else cl.text
        if cl.ast is None or cl.ast_text != text:
            cl.ast_text = text
            try:
                cl.ast = parse(text)
            except FormulaError:
                cl.ast = None
        if cl.ast is None:
            return
        named = self._build_named_ranges()
        deps = extract_refs(cl.ast, named)
        volatile = has_dynamic_refs(cl.ast)
        self._register_deps(key, deps, volatile)

    def _setcell_no_recalc(self, c: int, r: int, text: str) -> bool:
        """Set a single cell without triggering recalc. Returns True if grid changed."""
        if not (0 <= c < NCOL and 0 <= r < NROW):
            return False
        if not text:
            if self._cells.pop((c, r), None) is None:
                return False
            self._clear_deps((c, r))
            self.dirty = 1
            return True

        cl = self._ensure_cell(c, r)
        cl.arr = None
        cl.arr_cols = None
        cl.matrix = None
        cl.sval = None
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
        self._refresh_deps(c, r, cl)
        return True

    def setcell(self, c: int, r: int, text: str) -> None:
        if self._setcell_no_recalc(c, r, text) or not text:
            self.recalc({(c, r)})

    def setcells_bulk(self, cells: Iterable[tuple[int, int, str]]) -> None:
        """Set many cells, deferring recalc until all are written.

        Each tuple is (col, row, text). Out-of-bounds entries are ignored.
        Roughly N x faster than calling setcell() N times because recalc()
        runs once instead of after every cell.
        """
        changed: set[tuple[int, int]] = set()
        for c, r, text in cells:
            if self._setcell_no_recalc(c, r, text):
                changed.add((c, r))
        if changed:
            self.recalc(changed)

    def recalc(self, dirty: set[tuple[int, int]] | None = None) -> None:
        if self.mode != Mode.LEGACY:
            if self._use_topo_recalc:
                self._recalc_topo(dirty)
                return
            self._recalc_formula()
            return
        self._recalc_legacy()

    def _recalc_legacy(self) -> None:
        g = self._eval_globals
        self._circular = set()

        if self.code:
            valid, _ = validate_code(self.code)
            if valid:
                with contextlib.suppress(Exception):
                    exec(self.code, g)  # noqa: S102

        changed_cells: set[tuple[int, int]] = set()
        for _ in range(100):
            changed_cells.clear()

            # Inject cell values (only populated cells)
            for (c, r), cl in self._cells.items():
                if cl.type == EMPTY or cl.type == LABEL:
                    continue
                name = cellname(c, r)
                if cl.matrix is not None:
                    g[name] = cl.matrix
                elif cl.arr is not None and len(cl.arr) > 0:
                    g[name] = Vec(cl.arr, cols=cl.arr_cols)
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
                old_matrix = cl.matrix
                valid, _ = validate_formula(evalbuf)
                if not valid:
                    cl.arr = None
                    cl.arr_cols = None
                    cl.matrix = None
                    cl.val = float("nan")
                else:
                    try:
                        result = eval(evalbuf, g)  # noqa: S307
                        if _is_dataframe(result):
                            cl.matrix = result
                            cl.arr = None
                            cl.arr_cols = None
                            try:
                                cl.val = float(result.iloc[0, 0])
                            except (TypeError, ValueError, IndexError):
                                cl.val = float("nan")
                        elif _is_series(result):
                            cl.matrix = result.to_frame()
                            cl.arr = None
                            cl.arr_cols = None
                            try:
                                cl.val = float(result.iloc[0])
                            except (TypeError, ValueError, IndexError):
                                cl.val = float("nan")
                        elif _is_ndarray(result):
                            if result.ndim == 0:
                                cl.matrix = None
                                cl.arr = None
                                cl.arr_cols = None
                                cl.val = float(result)
                            else:
                                cl.matrix = result
                                cl.arr = None
                                cl.arr_cols = None
                                try:
                                    cl.val = float(result.flat[0])
                                except (TypeError, ValueError):
                                    cl.val = float("nan")
                        elif isinstance(result, Vec):
                            cl.matrix = None
                            cl.arr = list(result.data)
                            cl.arr_cols = result.cols
                            cl.val = result.data[0] if result.data else float("nan")
                        else:
                            cl.matrix = None
                            cl.arr = None
                            cl.arr_cols = None
                            cl.val = float(result)
                    except Exception:
                        cl.arr = None
                        cl.arr_cols = None
                        cl.matrix = None
                        cl.val = float("nan")
                both_nan = (
                    isinstance(cl.val, float)
                    and math.isnan(cl.val)
                    and isinstance(oldval, float)
                    and math.isnan(oldval)
                )
                matrix_changed = False
                if cl.matrix is not None or old_matrix is not None:
                    if cl.matrix is None or old_matrix is None:
                        matrix_changed = True
                    elif _is_dataframe(cl.matrix) and _is_dataframe(old_matrix):
                        try:
                            matrix_changed = not cl.matrix.equals(old_matrix)
                        except Exception:
                            matrix_changed = cl.matrix is not old_matrix
                    else:
                        try:
                            import numpy as _np  # noqa: I001

                            matrix_changed = not _np.array_equal(cl.matrix, old_matrix)
                        except ImportError:
                            matrix_changed = cl.matrix is not old_matrix
                if (cl.val != oldval and not both_nan) or matrix_changed:
                    changed_cells.add((fc, fr))

            if not changed_cells:
                break

        # Mark cells that never stabilized as circular references
        if changed_cells:
            self._circular = set(changed_cells)

        # Detect stable self-references (cells whose formula references
        # their own value, directly or via range, but converge at 0).
        # Strip address-only function calls first -- ROW(A6)/ROWS(A1:B10)
        # use the address, not the value, so a self-reference inside their
        # arg is not a real cycle.
        _addr_only_re = re.compile(r"(?i)\b(ROW|COLUMN|ROWS|COLUMNS)\s*\([^()]*\)")
        for (c, r), cl in self._cells.items():
            if cl.type != FORMULA:
                continue
            name = cellname(c, r)
            formula = cl.text[1:] if cl.text.startswith("=") else cl.text
            stripped = _addr_only_re.sub("", formula.replace("$", ""))
            expanded = _expand_ranges(stripped)
            if re.search(r"\b" + re.escape(name) + r"\b", expanded):
                self._circular.add((c, r))

        if self._circular:
            for pos in self._circular:
                circ = self._cells.get(pos)
                if circ:
                    circ.arr = None
                    circ.arr_cols = None
                    circ.matrix = None
                    circ.val = float("nan")

    def _build_py_registry(self) -> dict[str, Any]:
        if self.mode != Mode.HYBRID or not self.code:
            return {}
        valid, _ = validate_code(self.code)
        if not valid:
            return {}
        ns: dict[str, Any] = dict(self._eval_globals)
        with contextlib.suppress(Exception):
            exec(self.code, ns)  # noqa: S102
        base_keys = set(self._eval_globals.keys())
        registry: dict[str, Any] = {}
        for k, v in ns.items():
            if k.startswith("_") or k in base_keys:
                continue
            if callable(v):
                registry[k] = v
        return registry

    def _build_named_ranges(self) -> dict[str, Any]:
        from .formula.ast_nodes import CellRef as F_CellRef
        from .formula.ast_nodes import RangeRef as F_RangeRef

        named: dict[str, Any] = {}
        for nr in self.names:
            start = F_CellRef(nr.c1, nr.r1, False, False)
            if nr.c1 == nr.c2 and nr.r1 == nr.r2:
                named[nr.name] = start
            else:
                end = F_CellRef(nr.c2, nr.r2, False, False)
                named[nr.name] = F_RangeRef(start, end)
        return named

    def _cell_is_formula(self, c: int, r: int) -> bool:
        cl = self._cells.get((c, r))
        return cl is not None and cl.type == FORMULA

    def _cell_lookup_value(self, c: int, r: int) -> object:
        cl = self._cells.get((c, r))
        if cl is None or cl.type == EMPTY:
            return None
        if cl.type == LABEL:
            return cl.text
        if cl.matrix is not None:
            return cl.matrix
        if cl.arr is not None and cl.arr:
            return Vec(cl.arr, cols=cl.arr_cols)
        return cl.val

    def _store_formula_result(self, cl: Cell, result: Any) -> None:
        from .formula.errors import ExcelError

        cl.sval = None
        if isinstance(result, ExcelError):
            cl.arr = None
            cl.arr_cols = None
            cl.matrix = None
            cl.val = float("nan")
            return
        if isinstance(result, str):
            cl.matrix = None
            cl.arr = None
            cl.arr_cols = None
            cl.sval = result
            cl.val = 0.0
            return
        if isinstance(result, bool):
            cl.matrix = None
            cl.arr = None
            cl.arr_cols = None
            cl.sval = "TRUE" if result else "FALSE"
            cl.val = 1.0 if result else 0.0
            return
        if _is_dataframe(result):
            cl.matrix = result
            cl.arr = None
            cl.arr_cols = None
            try:
                cl.val = float(result.iloc[0, 0])
            except (TypeError, ValueError, IndexError):
                cl.val = float("nan")
            return
        if _is_series(result):
            cl.matrix = result.to_frame()
            cl.arr = None
            cl.arr_cols = None
            try:
                cl.val = float(result.iloc[0])
            except (TypeError, ValueError, IndexError):
                cl.val = float("nan")
            return
        if _is_ndarray(result):
            if result.ndim == 0:
                cl.matrix = None
                cl.arr = None
                cl.arr_cols = None
                try:
                    cl.val = float(result)
                except (TypeError, ValueError):
                    cl.val = float("nan")
            else:
                cl.matrix = result
                cl.arr = None
                cl.arr_cols = None
                try:
                    cl.val = float(result.flat[0])
                except (TypeError, ValueError):
                    cl.val = float("nan")
            return
        if isinstance(result, Vec):
            cl.matrix = None
            cl.arr = list(result.data)
            cl.arr_cols = result.cols
            cl.val = result.data[0] if result.data else float("nan")
            return
        cl.matrix = None
        cl.arr = None
        cl.arr_cols = None
        try:
            cl.val = float(result)
        except (TypeError, ValueError):
            cl.val = float("nan")

    def _recalc_formula(self) -> None:
        from .formula import Env, evaluate, parse
        from .formula.errors import FormulaError

        self._circular = set()
        py_registry = self._build_py_registry()
        named = self._build_named_ranges()
        env = Env(
            cell_value=self._cell_lookup_value,
            builtins=self._eval_globals,
            named_ranges=named,
            py_registry=py_registry,
            cell_is_formula=self._cell_is_formula,
        )

        changed_cells: set[tuple[int, int]] = set()
        for _ in range(100):
            changed_cells = set()
            # Cache materialised ranges for the duration of one
            # fixed-point iteration only -- next iteration may change
            # source values.
            env.clear_range_cache()
            for (fc, fr), cl in self._cells.items():
                if cl.type != FORMULA:
                    continue
                text = cl.text
                if text.startswith("="):
                    text = text[1:]
                if cl.ast is None or cl.ast_text != text:
                    cl.ast_text = text
                    try:
                        cl.ast = parse(text)
                    except FormulaError:
                        cl.ast = None
                oldval = cl.val
                old_matrix = cl.matrix
                if cl.ast is None:
                    cl.arr = None
                    cl.matrix = None
                    cl.val = float("nan")
                else:
                    env.current_cell = (fc, fr)
                    try:
                        result = evaluate(cl.ast, env)
                    except Exception:
                        result = float("nan")
                    self._store_formula_result(cl, result)
                both_nan = (
                    isinstance(cl.val, float)
                    and math.isnan(cl.val)
                    and isinstance(oldval, float)
                    and math.isnan(oldval)
                )
                matrix_changed = False
                if cl.matrix is not None or old_matrix is not None:
                    if cl.matrix is None or old_matrix is None:
                        matrix_changed = True
                    elif _is_dataframe(cl.matrix) and _is_dataframe(old_matrix):
                        try:
                            matrix_changed = not cl.matrix.equals(old_matrix)
                        except Exception:
                            matrix_changed = cl.matrix is not old_matrix
                    else:
                        try:
                            import numpy as _np  # noqa: I001

                            matrix_changed = not _np.array_equal(cl.matrix, old_matrix)
                        except ImportError:
                            matrix_changed = cl.matrix is not old_matrix
                if (cl.val != oldval and not both_nan) or matrix_changed:
                    changed_cells.add((fc, fr))
            if not changed_cells:
                break

        if changed_cells:
            self._circular = set(changed_cells)

        for (c, r), cl in self._cells.items():
            if cl.type != FORMULA or cl.ast is None:
                continue
            if _ast_uses_cell(cl.ast, c, r):
                self._circular.add((c, r))

        if self._circular:
            for pos in self._circular:
                circ = self._cells.get(pos)
                if circ:
                    circ.arr = None
                    circ.arr_cols = None
                    circ.matrix = None
                    circ.val = float("nan")

    def _recalc_topo(self, dirty: set[tuple[int, int]] | None) -> None:
        """Topological recalc: evaluate only the closure of dirty cells.

        If `dirty` is None, recompute every formula cell (initial load).
        Otherwise BFS the reverse-dep index from `dirty` to find affected
        formulas, then evaluate them in topological order. Volatile cells
        (PyCall, INDIRECT/OFFSET/INDEX) are unconditionally added to the
        closure. Cells that remain after the topo sort form structural
        cycles; they are flagged via `_circular` and set to NaN.
        """
        from .formula import Env, evaluate, parse
        from .formula.errors import FormulaError

        # `_circular` is updated incrementally below: cells outside the
        # closure aren't re-examined this recalc, so their flag stays.
        py_registry = self._build_py_registry()
        named = self._build_named_ranges()
        env = Env(
            cell_value=self._cell_lookup_value,
            builtins=self._eval_globals,
            named_ranges=named,
            py_registry=py_registry,
            cell_is_formula=self._cell_is_formula,
        )

        # Build the closure: BFS over `_subscribers` from the dirty set,
        # plus all volatile cells. If dirty is None, the closure is every
        # formula cell.
        if dirty is None:
            # The graph may be stale after structural edits or a mode
            # switch from LEGACY; otherwise `_refresh_deps` has been
            # maintaining it incrementally and the rebuild is wasted.
            if not self._dep_graph_built:
                self._rebuild_dep_graph()
            closure: set[tuple[int, int]] = {
                k for k, cl in self._cells.items() if cl.type == FORMULA
            }
        else:
            # Dirty cells that are themselves formulas need evaluation.
            closure = {
                k for k in dirty if (cl := self._cells.get(k)) is not None and cl.type == FORMULA
            }
            stack = list(dirty)
            while stack:
                k = stack.pop()
                for sub in self._subscribers.get(k, ()):
                    if sub not in closure:
                        closure.add(sub)
                        stack.append(sub)
            closure |= self._volatile

        # Topological order via Kahn's algorithm. In-edges restricted to
        # cells inside the closure -- deps outside the closure are already
        # up to date and don't gate evaluation order.
        in_count: dict[tuple[int, int], int] = {}
        children: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for k in closure:
            deps = self._dep_of.get(k, set())
            in_closure = deps & closure
            in_count[k] = len(in_closure)
            for d in in_closure:
                children.setdefault(d, []).append(k)

        ready = [k for k, n in in_count.items() if n == 0]
        order: list[tuple[int, int]] = []
        while ready:
            k = ready.pop()
            order.append(k)
            for child in children.get(k, ()):
                in_count[child] -= 1
                if in_count[child] == 0:
                    ready.append(child)

        # Evaluate in dependency order.
        for c, r in order:
            cl = self._cells.get((c, r))
            if cl is None or cl.type != FORMULA:
                continue
            text = cl.text[1:] if cl.text.startswith("=") else cl.text
            if cl.ast is None or cl.ast_text != text:
                cl.ast_text = text
                try:
                    cl.ast = parse(text)
                except FormulaError:
                    cl.ast = None
            if cl.ast is None:
                cl.arr = None
                cl.matrix = None
                cl.val = float("nan")
                continue
            env.current_cell = (c, r)
            try:
                result = evaluate(cl.ast, env)
            except Exception:
                result = float("nan")
            self._store_formula_result(cl, result)

        # Anything left in the closure but not in `order` is in a cycle.
        # Cells that were in the closure get their `_circular` membership
        # rewritten from scratch; cells outside the closure are left alone.
        # The dirty set is also cleared -- a freshly written non-formula
        # cell can't be in a cycle even though it's not in the closure.
        unresolved = closure - set(order)
        self._circular -= closure
        if dirty is not None:
            self._circular -= dirty
        self._circular |= unresolved
        for pos in unresolved:
            cl = self._cells.get(pos)
            if cl is not None:
                cl.arr = None
                cl.matrix = None
                cl.val = float("nan")

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
        self._rebuild_dep_graph()
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
        self._rebuild_dep_graph()
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
        self._rebuild_dep_graph()
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
        self._rebuild_dep_graph()
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
        self._rebuild_dep_graph()

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
        self._rebuild_dep_graph()

    def replicatecell(self, sc: int, sr: int, dc: int, dr: int) -> None:
        if not (0 <= dc < NCOL and 0 <= dr < NROW):
            return
        src = self.cell(sc, sr)
        if not src:
            # Source is empty -- clear destination, including its deps.
            if (dc, dr) in self._cells:
                self._cells.pop((dc, dr), None)
                self._clear_deps((dc, dr))
            return
        if src.type != FORMULA:
            # Non-formula: copy text and styling, route through bulk-set
            # path so dep graph entries are cleared.
            self._setcell_no_recalc(dc, dr, src.text)
            dst = self._cells.get((dc, dr))
            if dst is not None:
                dst.fmt = src.fmt
                dst.bold = src.bold
                dst.underline = src.underline
                dst.italic = src.italic
                dst.fmtstr = src.fmtstr
            return

        # Formula: rewrite refs by replicate offset.
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
        self._setcell_no_recalc(dc, dr, "".join(out))
        dst = self._cells.get((dc, dr))
        if dst is not None:
            dst.fmt = src.fmt
            dst.bold = src.bold
            dst.underline = src.underline
            dst.italic = src.italic
            dst.fmtstr = src.fmtstr

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

        if "mode" in d:
            parsed = Mode.parse(d.get("mode"))
            self.mode = parsed if parsed is not None else Mode.LEGACY
        else:
            self.mode = Mode.LEGACY

        code = d.get("code", "")
        if policy is None or policy.load_code:
            self.code = code

        libs = d.get("libs", [])
        if isinstance(libs, list):
            self.libs = [str(lib) for lib in libs]
            for lib in self.libs:
                self.load_lib(lib)
        self._apply_mode_libs()

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
                self._setcell_no_recalc(c_idx, r_idx, text)
                cl = self._cells.get((c_idx, r_idx))
                if not cl:
                    continue
                cl.bold = cell_bold
                cl.underline = cell_underline
                cl.italic = cell_italic
                cl.fmt = cell_fmt
                cl.fmtstr = cell_fmtstr

        # Single recalc at the end. Per-cell `_refresh_deps` already
        # populated the dep graph during the load loop, so flag it as
        # built and skip the redundant rebuild inside `_recalc_topo`.
        # LEGACY mode never built a graph in the first place; no flag.
        if self.mode != Mode.LEGACY:
            self._dep_graph_built = True
        self.recalc()
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

        out: dict[str, Any] = {"version": FILE_VERSION, "mode": self.mode.name}

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

    def xlsxload(self, filename: str) -> int:
        cells = _xlsx_read_cells(filename)
        if cells is None:
            return -1
        self.clear_all()
        self.mode = Mode.EXCEL
        self._apply_mode_libs()
        self.setcells_bulk(cells)
        self.dirty = 0
        self.filename = filename
        return 0

    def xlsxsave(self, filename: str) -> int:
        maxr = -1
        for (_c, r), sc in self._cells.items():
            if sc.type != EMPTY and r > maxr:
                maxr = r
        if maxr < 0:
            return -1
        payload: list[tuple[int, int, str, object]] = []
        for (c, r), cl in self._cells.items():
            if cl.type == EMPTY:
                continue
            if cl.type == LABEL:
                payload.append((c, r, "s", cl.text))
            elif cl.type == NUM:
                payload.append((c, r, "n", float(cl.val)))
            elif cl.type == FORMULA:
                if isinstance(cl.val, float) and math.isnan(cl.val):
                    continue
                payload.append((c, r, "n", float(cl.val)))
        return _xlsx_write_cells(filename, payload)

    def csvsave(self, filename: str) -> int:
        """Export evaluated cell values to CSV."""
        maxr = -1
        maxc = -1
        for (c, r), sc in self._cells.items():
            if sc.type != EMPTY:
                if r > maxr:
                    maxr = r
                if c > maxc:
                    maxc = c

        if maxr < 0:
            try:
                with open(filename, "w", newline="") as f:
                    f.write("")
            except OSError:
                return -1
            return 0

        try:
            with open(filename, "w", newline="") as f:
                writer = csv.writer(f)
                for r in range(maxr + 1):
                    row: list[str] = []
                    for c in range(maxc + 1):
                        cl = self._cells.get((c, r))
                        if not cl or cl.type == EMPTY:
                            row.append("")
                        elif cl.type == LABEL:
                            row.append(cl.text)
                        elif cl.type in (NUM, FORMULA):
                            if isinstance(cl.val, float) and math.isnan(cl.val):
                                row.append("")
                            elif cl.val == int(cl.val) and abs(cl.val) < 1e15:
                                row.append(str(int(cl.val)))
                            else:
                                row.append(f"{cl.val:g}")
                        else:
                            row.append("")
                    writer.writerow(row)
        except OSError:
            return -1
        return 0

    def csvload(self, filename: str) -> int:
        """Import cells from a CSV file. Numbers become NUM cells, rest become LABELs."""
        try:
            with open(filename, newline="") as f:
                content = f.read()
        except OSError:
            return -1

        reader = csv.reader(StringIO(content))
        for r_idx, row in enumerate(reader):
            if r_idx >= NROW:
                break
            for c_idx, val in enumerate(row):
                if c_idx >= NCOL:
                    break
                val = val.strip()
                if not val:
                    continue
                self.setcell(c_idx, r_idx, val)
        return 0

    def pdload(self, filename: str, header: bool = True) -> int:
        """Load a file into grid cells using pandas for type inference.

        Supports CSV, TSV, Excel (.xlsx/.xls), JSON, and Parquet.
        Column headers become labels in row 0 when header=True.
        """
        import pandas as pd  # noqa: I001

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        pd_header: int | None = 0 if header else None
        try:
            if ext in ("xlsx", "xls"):
                df = pd.read_excel(filename, header=pd_header)
            elif ext == "parquet":
                df = pd.read_parquet(filename)
            elif ext == "json":
                df = pd.read_json(filename)
            elif ext in ("tsv", "tab"):
                df = pd.read_csv(filename, sep="\t", header=pd_header)
            else:
                df = pd.read_csv(filename, header=pd_header)
        except Exception:
            return -1

        if df.shape[0] >= NROW or df.shape[1] >= NCOL:
            # Truncate to grid limits
            df = df.iloc[: NROW - (1 if header else 0), :NCOL]

        r_offset = 0
        if header:
            for c_idx, col_name_str in enumerate(df.columns):
                if c_idx >= NCOL:
                    break
                self.setcell(c_idx, 0, str(col_name_str))
            r_offset = 1

        for r_idx in range(len(df)):
            if r_idx + r_offset >= NROW:
                break
            for c_idx in range(len(df.columns)):
                if c_idx >= NCOL:
                    break
                val = df.iloc[r_idx, c_idx]
                if pd.isna(val):
                    continue
                if isinstance(val, (int, float)):
                    if isinstance(val, int) or (
                        isinstance(val, float) and val == int(val) and abs(val) < 1e15
                    ):
                        self.setcell(c_idx, r_idx + r_offset, str(int(val)))
                    else:
                        self.setcell(c_idx, r_idx + r_offset, f"{val:g}")
                else:
                    self.setcell(c_idx, r_idx + r_offset, str(val))
        return 0

    def pdsave(self, filename: str) -> int:
        """Export grid cells to a file using pandas.

        Supports CSV, TSV, Excel (.xlsx), JSON, and Parquet.
        Row 0 is used as column headers.
        """
        import pandas as pd  # noqa: I001

        maxr = -1
        maxc = -1
        for (c, r), sc in self._cells.items():
            if sc.type != EMPTY:
                if r > maxr:
                    maxr = r
                if c > maxc:
                    maxc = c

        if maxr < 0:
            return -1

        # Build column headers from row 0
        columns: list[str] = []
        for c in range(maxc + 1):
            cl = self._cells.get((c, 0))
            if cl and cl.type != EMPTY:
                columns.append(cl.text if cl.type == LABEL else str(cl.val))
            else:
                columns.append(col_name(c))

        # Build data from row 1 onward
        data: list[list[Any]] = []
        for r in range(1, maxr + 1):
            row: list[Any] = []
            for c in range(maxc + 1):
                cl = self._cells.get((c, r))
                if not cl or cl.type == EMPTY:
                    row.append(None)
                elif cl.type == LABEL:
                    row.append(cl.text)
                elif cl.type in (NUM, FORMULA):
                    if isinstance(cl.val, float) and math.isnan(cl.val):
                        row.append(None)
                    else:
                        row.append(cl.val)
                else:
                    row.append(None)
            data.append(row)

        df = pd.DataFrame(data, columns=columns)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        try:
            if ext in ("xlsx", "xls"):
                df.to_excel(filename, index=False)
            elif ext == "parquet":
                df.to_parquet(filename, index=False)
            elif ext == "json":
                df.to_json(filename, orient="records", indent=2)
            elif ext in ("tsv", "tab"):
                df.to_csv(filename, sep="\t", index=False)
            else:
                df.to_csv(filename, index=False)
        except Exception:
            return -1
        return 0
