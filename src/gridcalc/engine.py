from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Callable, Iterable, Iterator
from enum import IntEnum
from io import StringIO
from types import MappingProxyType
from typing import Any, NamedTuple

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
FILE_VERSION = 2

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
    builtins = {
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
    }
    g: dict[str, Any] = {
        # Frozen so a sandbox escape that obtains a reference to
        # `__builtins__` cannot inject new names that would persist
        # across formulas in the same recalc.
        "__builtins__": MappingProxyType(builtins),
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
        "err",
        "err_msg",
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
        self.err: Any = None
        self.err_msg: str | None = None

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
        self.err = None
        self.err_msg = None

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
        self.err = src.err
        self.err_msg = src.err_msg

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


class RefMatch(NamedTuple):
    chars_consumed: int
    col: int
    row: int
    abs_col: int
    abs_row: int


def refabs(s: str) -> RefMatch | None:
    """Parse a cell reference at the start of `s`.

    Returns a `RefMatch` (still tuple-unpackable as
    `n, col, row, abs_col, abs_row`), or None if no ref matches.
    """
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
    return RefMatch(m.end(), col, row, absc, absr)


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


def _xlsx_read_cells(filename: str) -> list[tuple[str, int, int, str]] | None:
    """Read xlsx via the OpenXLSX-backed `_core.xlsx_read`.

    Returns the list of ``(sheet_name, col0, row0, text)`` tuples
    across every sheet in the workbook (workbook order), or ``None``
    if the file cannot be opened.
    """
    from gridcalc import _core

    try:
        return list(_core.xlsx_read(filename))
    except Exception:
        return None


def _xlsx_write_cells(filename: str, cells: list[tuple[Any, ...]]) -> int:
    """Write ``(sheet_name, col0, row0, kind, value[, cached])`` tuples.

    ``kind`` is in ``{'s','n','f'}``. For ``'f'``, ``value`` is the
    formula text (with or without leading ``=``) and the optional 6th
    element is a cached numeric value (or ``None``). Sheets are created
    in the order they first appear in ``cells``. Returns 0 on success,
    -1 on failure.
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


def _rewrite_sheet_prefix(text: str, old: str, new: str) -> str:
    """Replace ``<old>!`` sheet prefixes in formula ``text`` with ``<new>!``.

    Skips matches inside double-quoted string literals (gridcalc's only
    string syntax; ``""`` is the escape for a literal quote). Matches
    are anchored on a non-identifier boundary before the name, so
    ``X<old>!`` does not match.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    old_with_bang = f"{old}!"
    new_with_bang = f"{new}!"
    while i < n:
        ch = text[i]
        if ch == '"':
            # Pass through the entire quoted string verbatim.
            out.append(ch)
            i += 1
            while i < n:
                if text[i] == '"':
                    out.append('"')
                    i += 1
                    if i < n and text[i] == '"':
                        # Escaped quote inside the string.
                        out.append('"')
                        i += 1
                        continue
                    break
                out.append(text[i])
                i += 1
            continue
        # Try to match `<old>!` here, anchored on a non-identifier
        # boundary on the left.
        if text.startswith(old_with_bang, i):
            prev = text[i - 1] if i > 0 else ""
            if not (prev.isalnum() or prev == "_"):
                out.append(new_with_bang)
                i += len(old_with_bang)
                continue
        out.append(ch)
        i += 1
    return "".join(out)


class Sheet:
    """A single named sheet's cell store, cycle set, and cursor.

    Workbook-level state (mode, code, named ranges, dep graph, etc.)
    lives on ``Grid``; each ``Sheet`` only owns the data that varies
    per-tab. ``Grid`` exposes ``_cells`` / ``cells`` / ``cc`` / ``cr`` /
    ``_circular`` as properties that delegate to ``sheets[active]`` so
    existing single-sheet code keeps working unchanged.
    """

    __slots__ = ("name", "_cells", "_circular", "cc", "cr")

    def __init__(self, name: str = "Sheet1") -> None:
        self.name: str = name
        self._cells: dict[tuple[int, int], Cell] = {}
        self._circular: set[tuple[int, int]] = set()
        self.cc: int = 0
        self.cr: int = 0


class Grid:
    def __init__(self) -> None:
        self.sheets: list[Sheet] = [Sheet()]
        self.active: int = 0
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
        self.code_error: str | None = None
        self.mode: Mode = Mode.LEGACY
        # Topological recalc bookkeeping. Off by default; opt-in via
        # `_use_topo_recalc = True`. Maintained alongside the fixed-point
        # path so flipping the flag is safe at any point.
        # Workbook-wide dep graph keyed by (sheet, c, r) 3-tuples;
        # `sheet` is the sheet name, never None for entries that
        # _refresh_deps installs (only `extract_refs` may emit None
        # transiently for unsheeted refs, but `_refresh_deps` always
        # passes a concrete sheet via formula_sheet).
        self._dep_of: dict[tuple[str | None, int, int], set[tuple[str | None, int, int]]] = {}
        self._subscribers: dict[tuple[str | None, int, int], set[tuple[str | None, int, int]]] = {}
        self._volatile: set[tuple[str | None, int, int]] = set()
        self._use_topo_recalc: bool = True
        # Set True by `_rebuild_dep_graph`; remains True while
        # `_refresh_deps`/`_clear_deps` maintain the graph incrementally.
        # Reset to False on mode entry into EXCEL/HYBRID (LEGACY skips
        # graph maintenance, so the graph is stale on mode transition).
        # `_recalc_topo` skips its rebuild call when this flag is True.
        self._dep_graph_built: bool = False

    # -- Per-sheet state delegated to the active sheet --

    @property
    def _active(self) -> Sheet:
        return self.sheets[self.active]

    @property
    def _cells(self) -> dict[tuple[int, int], Cell]:
        return self._active._cells

    @_cells.setter
    def _cells(self, new_cells: dict[tuple[int, int], Cell]) -> None:
        self._active._cells = new_cells

    @property
    def cells(self) -> _CellsProxy:
        return _CellsProxy(self._active._cells)

    @property
    def cc(self) -> int:
        return self._active.cc

    @cc.setter
    def cc(self, value: int) -> None:
        self._active.cc = value

    @property
    def cr(self) -> int:
        return self._active.cr

    @cr.setter
    def cr(self, value: int) -> None:
        self._active.cr = value

    @property
    def _circular(self) -> set[tuple[int, int]]:
        return self._active._circular

    @_circular.setter
    def _circular(self, value: set[tuple[int, int]]) -> None:
        self._active._circular = value

    # -- Sheet management --

    def sheet_names(self) -> list[str]:
        return [s.name for s in self.sheets]

    def add_sheet(self, name: str) -> Sheet:
        """Append a new sheet. Returns the sheet.

        NOTE (phase 1): the dep graph keys are still ``(c, r)`` tuples
        and do not carry sheet identity. Until phase 2 (sheet-qualified
        references) lands, formulas on different sheets that touch the
        same ``(c, r)`` collide in the dep graph. Treat multi-sheet
        workbooks as preview-only until then.
        """
        if any(s.name == name for s in self.sheets):
            raise ValueError(f"sheet {name!r} already exists")
        sh = Sheet(name=name)
        self.sheets.append(sh)
        return sh

    def remove_sheet(self, name: str) -> None:
        if len(self.sheets) <= 1:
            raise ValueError("cannot remove the last sheet")
        idx = next((i for i, s in enumerate(self.sheets) if s.name == name), -1)
        if idx < 0:
            raise KeyError(name)
        del self.sheets[idx]
        if self.active >= len(self.sheets):
            self.active = len(self.sheets) - 1
        elif self.active > idx:
            self.active -= 1

    def move_sheet(self, name: str, new_idx: int) -> None:
        """Reorder ``name`` to ``new_idx`` (zero-based).

        Active-sheet identity is preserved: if the active sheet is the
        one being moved, it follows; if some other sheet is active, its
        index is recomputed so the same sheet stays active.

        Dep graph keys carry sheet names rather than indices, so
        reordering doesn't invalidate the graph -- no rebuild needed.
        """
        if not (0 <= new_idx < len(self.sheets)):
            raise IndexError(new_idx)
        cur_idx = next((i for i, s in enumerate(self.sheets) if s.name == name), -1)
        if cur_idx < 0:
            raise KeyError(name)
        if cur_idx == new_idx:
            return
        active_sheet = self._active
        sh = self.sheets.pop(cur_idx)
        self.sheets.insert(new_idx, sh)
        # Restore active by identity.
        self.active = self.sheets.index(active_sheet)

    def rename_sheet(self, old: str, new: str) -> None:
        """Rename a sheet and rewrite formula text that references the old name.

        Walks every formula cell on every sheet and rewrites any
        ``<old>!`` sheet prefix to ``<new>!``. Skips matches inside
        double-quoted string literals so a user formula like
        ``="Other!A1"`` is left untouched. Invalidates the cached AST
        on each rewritten cell so the next recalc re-parses with the
        new sheet name.

        Caller is responsible for rebuilding the dep graph and
        triggering a recalc; ``cmd_sheet`` does both.
        """
        if old == new:
            return
        if any(s.name == new for s in self.sheets):
            raise ValueError(f"sheet {new!r} already exists")
        target = next((s for s in self.sheets if s.name == old), None)
        if target is None:
            raise KeyError(old)
        target.name = new
        # Rewrite formula text that references the old sheet name.
        for sh in self.sheets:
            for cl in sh._cells.values():
                if cl.type != FORMULA:
                    continue
                rewritten = _rewrite_sheet_prefix(cl.text, old, new)
                if rewritten != cl.text:
                    cl.text = rewritten
                    cl.ast = None
                    cl.ast_text = ""

    def set_active(self, name_or_idx: str | int) -> None:
        if isinstance(name_or_idx, int):
            if not (0 <= name_or_idx < len(self.sheets)):
                raise IndexError(name_or_idx)
            self.active = name_or_idx
            return
        idx = next((i for i, s in enumerate(self.sheets) if s.name == name_or_idx), -1)
        if idx < 0:
            raise KeyError(name_or_idx)
        self.active = idx

    def next_sheet(self) -> None:
        """Advance the active sheet by one, wrapping at the end. No-op
        on a single-sheet workbook."""
        n = len(self.sheets)
        if n <= 1:
            return
        self.active = (self.active + 1) % n

    def prev_sheet(self) -> None:
        """Retreat the active sheet by one, wrapping at the start.
        No-op on a single-sheet workbook."""
        n = len(self.sheets)
        if n <= 1:
            return
        self.active = (self.active - 1) % n

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

    def _clear_deps(self, key: tuple[str | None, int, int]) -> None:
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
        self,
        key: tuple[str | None, int, int],
        deps: set[tuple[str | None, int, int]],
        volatile: bool,
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
        Cost is O(formulas across all sheets) -- a single AST walk per
        formula cell.
        """
        self._dep_of.clear()
        self._subscribers.clear()
        self._volatile.clear()
        for s in self.sheets:
            for (c, r), cl in s._cells.items():
                if cl.type == FORMULA:
                    self._refresh_deps(c, r, cl, sheet=s.name)
        self._dep_graph_built = True

    def _refresh_deps(self, c: int, r: int, cl: Cell, sheet: str | None = None) -> None:
        """Recompute the dep graph for one cell. Call after writing the cell.

        Parses the formula text if the AST cache is stale, extracts the
        static read set, and updates `_dep_of` / `_subscribers` / `_volatile`.
        Non-formula cells get their entries cleared. LEGACY mode skips
        graph maintenance entirely -- it uses fixed-point recalc, not topo.

        ``sheet`` defaults to the active sheet's name. Pass it explicitly
        from ``_rebuild_dep_graph`` when iterating non-active sheets.
        """
        if self.mode == Mode.LEGACY:
            return
        from .formula import parse
        from .formula.deps import extract_refs, has_dynamic_refs
        from .formula.errors import FormulaError

        if sheet is None:
            sheet = self._active.name
        key = (sheet, c, r)
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
        deps = extract_refs(cl.ast, named, formula_sheet=sheet)
        volatile = has_dynamic_refs(cl.ast)
        self._register_deps(key, deps, volatile)

    def _setcell_no_recalc(self, c: int, r: int, text: str) -> bool:
        """Set a single cell without triggering recalc. Returns True if grid changed."""
        if not (0 <= c < NCOL and 0 <= r < NROW):
            return False
        if not text:
            if self._cells.pop((c, r), None) is None:
                return False
            self._clear_deps((self._active.name, c, r))
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
            valid, msg = validate_code(self.code)
            if not valid:
                self.code_error = f"code rejected: {msg}"
            else:
                try:
                    exec(self.code, g)  # noqa: S102
                    self.code_error = None
                except Exception as exc:  # noqa: BLE001
                    self.code_error = f"{type(exc).__name__}: {exc}"
        else:
            self.code_error = None

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
                valid, vmsg = validate_formula(evalbuf)
                if not valid:
                    from .formula.errors import ExcelError as _XE

                    cl.arr = None
                    cl.arr_cols = None
                    cl.matrix = None
                    cl.val = float("nan")
                    cl.err = _XE.NAME
                    cl.err_msg = vmsg
                else:
                    cl.err = None
                    cl.err_msg = None
                    try:
                        result = eval(evalbuf, g)  # noqa: S307
                        from .formula.errors import ExcelError as _XE

                        if isinstance(result, _XE):
                            cl.matrix = None
                            cl.arr = None
                            cl.arr_cols = None
                            cl.val = float("nan")
                            cl.err = result
                        elif _is_dataframe(result):
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
                    except Exception as exc:  # noqa: BLE001
                        from .formula.errors import ExcelError as _XE

                        cl.arr = None
                        cl.arr_cols = None
                        cl.matrix = None
                        cl.val = float("nan")
                        cl.err = _XE.VALUE
                        cl.err_msg = f"{type(exc).__name__}: {exc}"
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
            from .formula.errors import ExcelError as _XE

            for pos in self._circular:
                circ = self._cells.get(pos)
                if circ:
                    circ.arr = None
                    circ.arr_cols = None
                    circ.matrix = None
                    circ.val = float("nan")
                    circ.err = _XE.CIRC
                    circ.err_msg = None

    def _build_py_registry(self) -> dict[str, Any]:
        if self.mode != Mode.HYBRID or not self.code:
            self.code_error = None
            return {}
        valid, msg = validate_code(self.code)
        if not valid:
            self.code_error = f"code rejected: {msg}"
            return {}
        ns: dict[str, Any] = dict(self._eval_globals)
        try:
            exec(self.code, ns)  # noqa: S102
            self.code_error = None
        except Exception as exc:  # noqa: BLE001
            self.code_error = f"{type(exc).__name__}: {exc}"
            return {}
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

    def _sheet_cells(self, sheet: str | None) -> dict[tuple[int, int], Cell]:
        """Return the cell store for the named sheet, or active when None.

        Returns an empty dict for unknown sheet names; the caller treats
        that as "no such cell" via the same path as a missing key. (A
        formula referencing ``Bogus!A1`` evaluates to 0 / empty, matching
        what an unset cell would do; ``#REF!`` semantics for unknown
        sheets are deferred until phase 3 surfaces sheet management.)
        """
        if sheet is None:
            return self._active._cells
        for s in self.sheets:
            if s.name == sheet:
                return s._cells
        return {}

    def _cell_is_formula(self, c: int, r: int, sheet: str | None = None) -> bool:
        cl = self._sheet_cells(sheet).get((c, r))
        return cl is not None and cl.type == FORMULA

    def _cell_lookup_value(self, c: int, r: int, sheet: str | None = None) -> object:
        cl = self._sheet_cells(sheet).get((c, r))
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
            cl.err = result
            cl.err_msg = None
            return
        cl.err = None
        cl.err_msg = None
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
            from .formula.errors import ExcelError as _XE

            for pos in self._circular:
                circ = self._cells.get(pos)
                if circ:
                    circ.arr = None
                    circ.arr_cols = None
                    circ.matrix = None
                    circ.val = float("nan")
                    circ.err = _XE.CIRC
                    circ.err_msg = None

    def _recalc_topo(self, dirty: set[tuple[int, int]] | None) -> None:
        """Topological recalc: evaluate only the closure of dirty cells.

        Multi-sheet aware: dep keys are ``(sheet, c, r)`` workbook-wide;
        the closure spans every sheet that has formulas reading the
        dirty cells.

        ``dirty`` is supplied as ``(c, r)`` 2-tuples relative to the
        active sheet (the API setcell/setcells_bulk uses today). They
        are promoted to 3-tuples internally. Pass ``None`` for a full
        recompute across all sheets.
        """
        from .formula import Env, evaluate, parse
        from .formula.errors import FormulaError

        py_registry = self._build_py_registry()
        named = self._build_named_ranges()
        env = Env(
            cell_value=self._cell_lookup_value,
            builtins=self._eval_globals,
            named_ranges=named,
            py_registry=py_registry,
            cell_is_formula=self._cell_is_formula,
        )

        active_name = self._active.name
        # Promote `dirty` (2-tuples on the active sheet) to 3-tuples.
        dirty3: set[tuple[str | None, int, int]] | None = (
            None if dirty is None else {(active_name, c, r) for (c, r) in dirty}
        )

        # Build the closure: BFS over `_subscribers` from the dirty set,
        # plus all volatile cells. If dirty is None, the closure is every
        # formula cell across every sheet.
        if dirty3 is None:
            if not self._dep_graph_built:
                self._rebuild_dep_graph()
            closure: set[tuple[str | None, int, int]] = set()
            for s in self.sheets:
                for (c, r), cl in s._cells.items():
                    if cl.type == FORMULA:
                        closure.add((s.name, c, r))
        else:
            closure = set()
            for k in dirty3:
                cl_dirty = self._cell_at(k)
                if cl_dirty is not None and cl_dirty.type == FORMULA:
                    closure.add(k)
            stack = list(dirty3)
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
        in_count: dict[tuple[str | None, int, int], int] = {}
        children: dict[tuple[str | None, int, int], list[tuple[str | None, int, int]]] = {}
        for k in closure:
            deps = self._dep_of.get(k, set())
            in_closure = deps & closure
            in_count[k] = len(in_closure)
            for d in in_closure:
                children.setdefault(d, []).append(k)

        ready = [k for k, n in in_count.items() if n == 0]
        order: list[tuple[str | None, int, int]] = []
        while ready:
            k = ready.pop()
            order.append(k)
            for child in children.get(k, ()):
                in_count[child] -= 1
                if in_count[child] == 0:
                    ready.append(child)

        # Evaluate in dependency order. Switch the active sheet for
        # each formula so `current_cell` and the active-sheet cell
        # callback resolve in the right scope -- but capture+restore
        # so user-visible `g.active` doesn't change.
        saved_active = self.active
        try:
            for key in order:
                sheet_name, c, r = key
                fcl = self._cell_at(key)
                if fcl is None or fcl.type != FORMULA:
                    continue
                text = fcl.text[1:] if fcl.text.startswith("=") else fcl.text
                if fcl.ast is None or fcl.ast_text != text:
                    fcl.ast_text = text
                    try:
                        fcl.ast = parse(text)
                    except FormulaError:
                        fcl.ast = None
                if fcl.ast is None:
                    fcl.arr = None
                    fcl.matrix = None
                    fcl.val = float("nan")
                    continue
                # Make this formula's home sheet active during eval so
                # unsheeted refs in the formula resolve to its own
                # sheet via the Env callback.
                if sheet_name is not None:
                    for i, s in enumerate(self.sheets):
                        if s.name == sheet_name:
                            self.active = i
                            break
                env.current_cell = (c, r)
                try:
                    result = evaluate(fcl.ast, env)
                except Exception:
                    result = float("nan")
                self._store_formula_result(fcl, result)
        finally:
            self.active = saved_active

        # Anything left in the closure but not in `order` is in a cycle.
        # Cells that were in the closure get their `_circular` membership
        # rewritten from scratch; cells outside the closure are left alone.
        unresolved = closure - set(order)
        # Update each affected sheet's `_circular` set (per-sheet 2-tuples).
        affected_sheets: set[str | None] = {s for (s, _c, _r) in closure}
        for s_name in affected_sheets:
            sh: Sheet | None = self._sheet_by_name(s_name) if s_name is not None else self._active
            if sh is None:
                continue
            # Drop closure cells from this sheet's circular set.
            closure_cr = {(c, r) for (sn, c, r) in closure if sn == s_name}
            sh._circular -= closure_cr
            if dirty3 is not None:
                dirty_cr = {(c, r) for (sn, c, r) in dirty3 if sn == s_name}
                sh._circular -= dirty_cr
            unres_cr = {(c, r) for (sn, c, r) in unresolved if sn == s_name}
            sh._circular |= unres_cr
        if unresolved:
            from .formula.errors import ExcelError as _XE

            for key in unresolved:
                circ_cl: Cell | None = self._cell_at(key)
                if circ_cl is not None:
                    circ_cl.arr = None
                    circ_cl.matrix = None
                    circ_cl.val = float("nan")
                    circ_cl.err = _XE.CIRC
                    circ_cl.err_msg = None

    def _cell_at(self, key: tuple[str | None, int, int]) -> Cell | None:
        """Resolve a workbook-level dep key to its Cell, if any."""
        sheet, c, r = key
        return self._sheet_cells(sheet).get((c, r))

    def _sheet_by_name(self, name: str | None) -> Sheet | None:
        if name is None:
            return self._active
        for s in self.sheets:
            if s.name == name:
                return s
        return None

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
                self._clear_deps((self._active.name, dc, dr))
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

    def _load_cells_into_active(self, rows: list[Any]) -> None:
        """Load a v1/v2 cell-rows array into the currently active sheet."""
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

        # Sheet population. v2 has a `sheets` array of {name, cells};
        # v1 has top-level `cells` (single sheet).
        sheets_payload = d.get("sheets")
        if isinstance(sheets_payload, list) and sheets_payload:
            # v2: replace the auto-created Sheet1 with the saved sheets.
            self.sheets = []
            for entry in sheets_payload:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name")
                if not isinstance(name, str) or not name:
                    continue
                # add_sheet rejects duplicates; if a save somehow has
                # them, tolerate by appending a numeric suffix.
                final_name = name
                suffix = 1
                while any(s.name == final_name for s in self.sheets):
                    final_name = f"{name}_{suffix}"
                    suffix += 1
                sh = Sheet(name=final_name)
                self.sheets.append(sh)
                self.active = len(self.sheets) - 1
                cells_payload = entry.get("cells", [])
                if isinstance(cells_payload, list):
                    self._load_cells_into_active(cells_payload)
            if not self.sheets:
                self.sheets = [Sheet()]
                self.active = 0
            else:
                # Pick the requested active sheet (by name); fall back
                # to the first sheet if absent or unknown.
                requested = d.get("active")
                if isinstance(requested, str):
                    for i, s in enumerate(self.sheets):
                        if s.name == requested:
                            self.active = i
                            break
                    else:
                        self.active = 0
                else:
                    self.active = 0
        else:
            # v1: load into the auto-created Sheet1.
            rows = d.get("cells", [])
            if isinstance(rows, list):
                self._load_cells_into_active(rows)

        # Single recalc at the end. Per-cell `_refresh_deps` already
        # populated the dep graph during the load loop, so flag it as
        # built and skip the redundant rebuild inside `_recalc_topo`.
        # LEGACY mode never built a graph in the first place; no flag.
        if self.mode != Mode.LEGACY:
            self._dep_graph_built = True
        self.recalc()
        return 0

    def _encode_sheet_rows(self, cells: dict[tuple[int, int], Cell]) -> list[list[Any]]:
        """Encode one sheet's cell store as a v2 ``cells`` rows list."""
        maxr = -1
        maxc = -1
        for (c, r), cl in cells.items():
            if cl.type != EMPTY:
                if r > maxr:
                    maxr = r
                if c > maxc:
                    maxc = c
        rows: list[list[Any]] = []
        for r in range(maxr + 1):
            row: list[Any] = []
            for c in range(maxc + 1):
                sc = cells.get((c, r))
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
        return rows

    def jsonsave(self, filename: str) -> int:
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

        # v2: per-sheet payload. Active sheet recorded by name so the
        # round-trip restores the user's view even when sheet order
        # changes.
        out["active"] = self._active.name
        out["sheets"] = [
            {"name": s.name, "cells": self._encode_sheet_rows(s._cells)} for s in self.sheets
        ]

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
        self.mode = Mode.EXCEL
        # Reset the workbook to a single empty sheet, then create
        # additional sheets as encountered in the payload.
        self.sheets = [Sheet()]
        self.active = 0
        self._dep_of.clear()
        self._subscribers.clear()
        self._volatile.clear()
        self._apply_mode_libs()

        # Group payload by sheet, preserving first-seen order.
        per_sheet: dict[str, list[tuple[int, int, str]]] = {}
        sheet_order: list[str] = []
        for sname, c, r, text in cells:
            if sname not in per_sheet:
                per_sheet[sname] = []
                sheet_order.append(sname)
            per_sheet[sname].append((c, r, text))

        # Replace the auto-created Sheet1 with the first xlsx sheet
        # (preserves the source workbook's first-sheet name) and add
        # the rest.
        if sheet_order:
            self.sheets[0].name = sheet_order[0]
            for extra in sheet_order[1:]:
                # Tolerate duplicate names by appending a numeric
                # suffix; OpenXLSX itself rejects duplicates so this
                # branch is defensive.
                final_name = extra
                suffix = 1
                while any(s.name == final_name for s in self.sheets):
                    final_name = f"{extra}_{suffix}"
                    suffix += 1
                self.sheets.append(Sheet(name=final_name))

        # Bulk-load each sheet's cells via setcells_bulk on the active
        # sheet, switching active per sheet.
        for i, sname in enumerate(sheet_order):
            self.active = i
            # Use the resolved name rather than `sname` in case the
            # de-dupe path renamed it.
            self.setcells_bulk(per_sheet[sname])
        self.active = 0

        self.dirty = 0
        self.filename = filename
        return 0

    def xlsxsave(self, filename: str) -> int:
        # Empty workbook: nothing to write.
        if all(cl.type == EMPTY for s in self.sheets for cl in s._cells.values()):
            return -1

        # In EXCEL mode, formula text is preserved (with cached numeric
        # value when available). In LEGACY/HYBRID mode, gridcalc formula
        # syntax is not guaranteed to be valid Excel, so we keep the
        # historical values-only behavior.
        preserve_formulas = self.mode == Mode.EXCEL
        payload: list[tuple[Any, ...]] = []
        for s in self.sheets:
            for (c, r), cl in s._cells.items():
                if cl.type == EMPTY:
                    continue
                if cl.type == LABEL:
                    payload.append((s.name, c, r, "s", cl.text))
                elif cl.type == NUM:
                    payload.append((s.name, c, r, "n", float(cl.val)))
                elif cl.type == FORMULA:
                    val = cl.val
                    cached: float | None
                    if isinstance(val, (int, float)) and not (
                        isinstance(val, float) and math.isnan(val)
                    ):
                        cached = float(val)
                    else:
                        cached = None
                    if preserve_formulas and cl.text:
                        payload.append((s.name, c, r, "f", cl.text, cached))
                    elif cached is not None:
                        payload.append((s.name, c, r, "n", cached))
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
