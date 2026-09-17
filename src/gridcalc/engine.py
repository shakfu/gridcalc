from __future__ import annotations

import contextlib
import csv
import json
import math
import os
import re
import shutil
import stat
import tempfile
import warnings
from collections.abc import Callable, Iterable, Iterator
from enum import IntEnum
from io import StringIO
from types import MappingProxyType
from typing import Any, NamedTuple

from .dates import is_date_format, normalise_format
from .formula.lexer import parse_number
from .sandbox import load_modules, validate_code, validate_formula


class Mode(IntEnum):
    EXCEL = 1
    HYBRID = 2
    PYTHON = 3

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
            # Accept "legacy" as an alias for "python" so older JSON files
            # with `"mode": "LEGACY"` still load. The canonical name is
            # "python" -- jsonsave always writes `Mode.PYTHON.name`.
            if s in ("3", "python", "legacy"):
                return cls.PYTHON
        return None


MAXIN = 256
NCOL = 256
NROW = 1024
MAXNAMES = 256
MAXCODE = 8192
CW_DEFAULT = 8
# Bounds for `Sheet.widths`, the per-column pixel widths a graphical frontend
# records. Wide enough to be usable, narrow enough that a corrupt or hostile
# file cannot lay out a sheet kilometres across.
COL_PX_MIN = 20
COL_PX_MAX = 2000
FILE_VERSION = 2

EMPTY = 0
NUM = 1
LABEL = 2
FORMULA = 3
# A cell painted by a neighbouring formula's spilled array. It holds the
# spilled value but no formula of its own; its anchor owns and recomputes
# it. Not persisted -- rebuilt on load by recomputing the anchor.
SPILL = 4

# Spill shapes are only known after a formula evaluates, so a spill can
# create/destroy cells whose consumers were not in the current topo pass.
# `recalc` re-runs the pass over the changed spill positions until the
# spill topology stabilises, bounded like the PYTHON fixpoint engine.
_MAX_SPILL_PASSES = 64


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


def _agg_operands(args: tuple[Any, ...]) -> list[float]:
    """Flatten several aggregate arguments into one numeric list. Only the
    multi-argument path uses this; one argument keeps its own fast paths,
    which read an ndarray whole rather than element by element."""
    out: list[float] = []
    for a in args:
        if isinstance(a, Vec):
            out.extend(_numeric_only(a.data))
        elif _is_ndarray(a):
            out.extend(_numeric_only(a.flat))
        elif _is_num(a):
            out.append(float(a))
    return out


def SUM(x: Any, *rest: Any) -> float:
    if rest:
        return sum(_agg_operands((x, *rest)))
    if isinstance(x, Vec):
        return sum(_numeric_only(x.data))
    if _is_ndarray(x):
        return float(x.sum())
    if not _is_num(x):
        return 0.0
    return float(x)


def AVG(x: Any, *rest: Any) -> float:
    if rest:
        nums = _agg_operands((x, *rest))
        return sum(nums) / len(nums) if nums else 0.0
    if isinstance(x, Vec):
        nums = _numeric_only(x.data)
        return sum(nums) / len(nums) if nums else 0.0
    if _is_ndarray(x):
        return float(x.mean()) if x.size > 0 else 0.0
    if not _is_num(x):
        return 0.0
    return float(x)


def MIN(x: Any, *rest: Any) -> float:
    if rest:
        nums = _agg_operands((x, *rest))
        return min(nums) if nums else 0.0
    if isinstance(x, Vec):
        nums = _numeric_only(x.data)
        return min(nums) if nums else 0.0
    if _is_ndarray(x):
        return float(x.min())
    if not _is_num(x):
        return 0.0
    return float(x)


def MAX(x: Any, *rest: Any) -> float:
    if rest:
        nums = _agg_operands((x, *rest))
        return max(nums) if nums else 0.0
    if isinstance(x, Vec):
        nums = _numeric_only(x.data)
        return max(nums) if nums else 0.0
    if _is_ndarray(x):
        return float(x.max())
    if not _is_num(x):
        return 0.0
    return float(x)


def COUNT(x: Any, *rest: Any) -> int | float:
    if rest:
        return len(_agg_operands((x, *rest)))
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
        "spill_parent",
        "spill_shape",
    )

    def __init__(self) -> None:
        self.type: int = EMPTY
        # A bool for a boolean formula result (with `sval` "TRUE"/"FALSE"), so
        # a reader can tell it from the text "TRUE"; numerically still 1/0.
        self.val: float = 0.0
        self.sval: str | None = None
        self.arr: list[float] | None = None
        # When arr holds a 2D Vec result, arr_cols is the column count.
        # None means 1D (or no array).
        self.arr_cols: int | None = None
        self.matrix: Any = None
        # Spill bookkeeping. `spill_parent` is the (col, row) anchor of a
        # SPILL cell; None for every other cell. `spill_shape` is the
        # (rows, cols) rectangle a spilling anchor currently occupies;
        # None when the cell is not an anchor or is not spilling.
        self.spill_parent: tuple[int, int] | None = None
        self.spill_shape: tuple[int, int] | None = None
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
        self.spill_parent = None
        self.spill_shape = None

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
        self.spill_parent = src.spill_parent
        self.spill_shape = src.spill_shape

    def snapshot(self) -> Cell:
        c = Cell()
        c.copy_from(self)
        return c


class NamedRange:
    __slots__ = ("name", "c1", "r1", "c2", "r2", "sheet")

    def __init__(
        self,
        name: str = "",
        c1: int = 0,
        r1: int = 0,
        c2: int = 0,
        r2: int = 0,
        sheet: str | None = None,
    ) -> None:
        self.name = name
        self.c1 = c1
        self.r1 = r1
        self.c2 = c2
        self.r2 = r2
        # Sheet the range lives on, or None for a sheet-agnostic name that
        # resolves against whichever sheet the referencing formula is on
        # (the historical gridcalc behaviour; xlsx imports set it explicitly).
        self.sheet = sheet


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


def _ref_at(text: str, i: int) -> RefMatch | None:
    """``refabs`` at ``text[i]``, or None when the match is part of a name.

    A reference cannot continue an identifier or number (`LOG10`, `Sheet1`,
    `1E5`) or be followed by a letter or `(` (`A1B`, `X1(`).
    """
    if i > 0 and (text[i - 1].isalnum() or text[i - 1] in "_."):
        return None
    m = refabs(text[i:])
    if m is None:
        return None
    j = i + m.chars_consumed
    if j < len(text) and (text[j].isalnum() or text[j] in "_("):
        return None
    return m


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


def _skip_quoted(text: str, i: int) -> int | None:
    """Index just past the string literal starting at ``i``, or None if it is
    not a quote.

    Both formula transformers below walk raw text looking for things shaped like
    cell references, and a reference is shaped exactly like ordinary prose: the
    ``A1`` in ``="col A1 total"`` is indistinguishable from the ``A1`` in
    ``=A1+1`` without tracking quoting. Skipping literals wholesale is what
    keeps a copy/paste from silently editing the user's text.

    Handles both dialects, since formulas may be Excel or Python: a backslash
    escapes the next character (Python), and a doubled quote is a literal quote
    (Excel style). Single quotes count too -- they delimit strings in
    PYTHON mode and sheet names in Excel (``'My Sheet'!A1``), and in neither case
    should the contents be rewritten. An unterminated literal swallows the rest
    of the text, which is the conservative choice: better to adjust nothing than
    to corrupt something.
    """
    if i >= len(text) or text[i] not in ('"', "'"):
        return None
    q = text[i]
    j = i + 1
    while j < len(text):
        if text[j] == "\\" and j + 1 < len(text):
            j += 2
        elif text[j] == q:
            if j + 1 < len(text) and text[j + 1] == q:
                j += 2  # doubled quote: an escaped quote, not the end
            else:
                return j + 1
        else:
            j += 1
    return len(text)


def _strip_literals(text: str) -> str:
    """``text`` with every string literal emptied, e.g. ``len("A1")`` to
    ``len("")``, so a scan for references ignores prose."""
    out: list[str] = []
    i = 0
    while i < len(text):
        end = _skip_quoted(text, i)
        if end is None:
            out.append(text[i])
            i += 1
        else:
            out.append(text[i] * 2)
            i = end
    return "".join(out)


# `Sheet1!`, `'My Sheet'!` -- the sheet qualifier ahead of a reference.
_SHEET_QUAL_RE = re.compile(r"(?:'((?:[^']|'')*)'|([A-Za-z_][A-Za-z0-9_.]*))!")


# Maps a reference's corners ``(c1, r1, c2, r2)`` (equal for a single cell) to
# new corners, or to None when the lines it covered were all deleted.
_RefMove = Callable[[int, int, int, int], "tuple[int, int, int, int] | None"]


def _rewrite_refs_on_sheet(
    text: str,
    home_sheet: str,
    edited_sheet: str,
    move: _RefMove,
) -> str | None:
    """Rewrite the references in ``text`` that resolve against ``edited_sheet``.

    Returns the new text, or None when nothing moved. A reference ``move``
    deletes becomes ``#REF!``, qualifier included.

    ``home_sheet`` is the sheet the formula lives on, which is what a bare
    reference resolves against; a reference carrying a qualifier resolves
    against that sheet instead. Inserting a row on one sheet must not move
    `Data!A2`, because Data's rows did not move -- the rule `_shift_names`
    already applies to named ranges. String literals are skipped, since prose
    is shaped like a reference.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    changed = False

    def take_refs(at: int, sheet: str, qual: str) -> tuple[int, bool]:
        """Consume a reference at ``at``, plus the ``:ref`` completing a range
        so a qualifier governs both ends, and append it after ``qual``."""
        m1 = _ref_at(text, at)
        if m1 is None:
            if qual:
                out.append(qual)
                return at, False
            out.append(text[at])
            return at + 1, False
        at += m1.chars_consumed
        m2 = _ref_at(text, at + 1) if at < n and text[at] == ":" else None
        end = m2 if m2 is not None else m1
        rect = (m1.col, m1.row, end.col, end.row)
        new = move(*rect) if sheet == edited_sheet else rect
        if m2 is not None:
            at += 1 + m2.chars_consumed
        if new is None:
            out.append("#REF!")
            return at, True
        out.append(qual + _emitref(new[0], new[1], m1.abs_col, m1.abs_row))
        if m2 is not None:
            out.append(":" + _emitref(new[2], new[3], m2.abs_col, m2.abs_row))
        return at, new != rect

    while i < n:
        if i > 0 and (text[i - 1].isalnum() or text[i - 1] in "_."):
            out.append(text[i])  # inside a name: `LOG10`, `Sheet1`
            i += 1
            continue
        # The qualifier is matched before `_skip_quoted`, or a quoted sheet
        # name would be mistaken for a string literal and its reference left
        # to resolve against the wrong sheet.
        q = _SHEET_QUAL_RE.match(text, i)
        if q:
            quoted, bare = q.group(1), q.group(2)
            sheet = bare if quoted is None else quoted.replace("''", "'")
            i, moved = take_refs(q.end(), sheet, q.group(0))
            changed = changed or moved
            continue
        end = _skip_quoted(text, i)
        if end is not None:
            out.append(text[i:end])
            i = end
            continue
        i, moved = take_refs(i, home_sheet, "")
        changed = changed or moved

    return "".join(out) if changed else None


def adjust_refs(text: str, dcol: int, drow: int) -> str:
    """Shift every relative cell reference in ``text`` by ``(dcol, drow)``.

    Absolute (``$``-prefixed) columns/rows are left unchanged. Used both by
    replicate (copy a formula across the grid) and by the frontends' paste, so
    the two share one definition of reference adjustment.
    """
    out = []
    i = 0
    while i < len(text):
        end = _skip_quoted(text, i)
        if end is not None:
            out.append(text[i:end])  # a literal is copied through untouched
            i = end
            continue
        result = _ref_at(text, i)
        if result:
            n, rc, rr, ac, ar = result
            if not ac:
                rc += dcol
            if not ar:
                rr += drow
            out.append(_emitref(rc, rr, ac, ar))
            i += n
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _expand_ranges(expr: str) -> str:
    """Expand A1:B3 range syntax into Vec([A1,A2,...]) calls."""
    result = []
    i = 0
    while i < len(expr):
        end = _skip_quoted(expr, i)
        if end is not None:
            result.append(expr[i:end])  # `"A1:B2"` is text, not a range
            i = end
            continue
        r1 = _ref_at(expr, i)
        if r1:
            n1, c1, row1, _, _ = r1
            if i + n1 < len(expr) and expr[i + n1] == ":":
                r2 = _ref_at(expr, i + n1 + 1)
                if r2:
                    n2, c2, row2, _, _ = r2
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


# File types `pdload` and `pdsave` accept; no extension means CSV.
_PD_EXTS = frozenset({"", ".csv", ".txt", ".tsv", ".tab", ".json"})


def _number_text(v: float) -> str:
    """Source text that ``setcell`` parses back to exactly ``v``."""
    return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)


def _write_atomic(filename: str, write: Callable[[str], object]) -> None:
    """Run ``write(tmp)`` on a new file beside ``filename``, then rename it over ``filename``.

    Raises on any failure and leaves ``filename`` untouched. ``tmp`` sits in a
    private directory, so scratch files a writer leaves on failure go with it.
    """
    target = os.path.realpath(filename)
    head, base = os.path.split(target)
    tmpdir = tempfile.mkdtemp(prefix=f".{base}.", dir=head)
    tmp = os.path.join(tmpdir, base)
    try:
        # 0o666 lets the umask set a new file's mode, as open() would.
        os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666))
        write(tmp)
        with contextlib.suppress(FileNotFoundError):
            os.chmod(tmp, stat.S_IMODE(os.stat(target).st_mode))
        # Windows fsync needs a writable handle; "rb" fails with EBADF there.
        with open(tmp, "r+b") as f:
            os.fsync(f.fileno())
        os.replace(tmp, target)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _xlsx_read_cells(filename: str) -> tuple[list[str], list[tuple[Any, ...]], int]:
    """Read xlsx via the OpenXLSX-backed `_core.xlsx_read`.

    Returns ``(worksheet_names, cells, fallbacks)``: every worksheet in
    workbook order, ``(sheet_name, col0, row0, kind, value, numfmt_code,
    numfmt_id)`` tuples, and the count of shared or array formulas read as
    their cached value. Raises if the file cannot be read.

    The number format rides along because xlsx has no date type: a date is a
    serial wearing a date format, so the format is the only thing that says
    a column of floats is a column of dates.
    """
    from gridcalc import _core

    names, cells, fallbacks = _core.xlsx_read(filename)
    return list(names), list(cells), int(fallbacks)


def _parse_defined_ref(text: str) -> tuple[str, int, int, int, int] | None:
    """Parse a defined-name target like ``Data!$B$2:$B$4`` or
    ``'My Sheet'!$A$1`` into ``(sheet, c1, r1, c2, r2)`` (0-based inclusive).

    Returns None for anything that is not a single-area cell/range on one
    sheet -- constants, formulas, and multi-area unions are skipped, since
    gridcalc's named ranges model only a rectangle on a sheet.
    """
    if "!" not in text or "," in text or "(" in text:
        return None
    sheet_part, _, ref_part = text.rpartition("!")
    sheet = sheet_part.strip()
    if len(sheet) >= 2 and sheet[0] == "'" and sheet[-1] == "'":
        sheet = sheet[1:-1].replace("''", "'")
    if not sheet:
        return None
    ref_part = ref_part.replace("$", "")
    lo, _, hi = ref_part.partition(":")
    hi = hi or lo
    a = ref(lo)
    b = ref(hi)
    if a is None or b is None:
        return None
    _, c1, r1 = a
    _, c2, r2 = b
    return sheet, min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2)


def _xlsx_workbook_xml(filename: str) -> Any:
    """The root of the xlsx zip's ``xl/workbook.xml``, or None if unreadable.

    OpenXLSX exposes neither defined names nor the date system, so both are
    read here. Never raises.
    """
    import xml.etree.ElementTree as ET
    import zipfile

    try:
        with zipfile.ZipFile(filename) as z, z.open("xl/workbook.xml") as f:
            # noqa justification: `filename` is an xlsx the user explicitly
            # chose to open; the C++ reader already parses all of its XML, so
            # reading one more member here adds no attack surface.
            return ET.parse(f).getroot()  # noqa: S314
    except (KeyError, zipfile.BadZipFile, OSError, ET.ParseError):
        return None


_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xlsx_date1904(root: Any) -> bool:
    """Whether the workbook counts date serials from 1904 (old Mac Excel)."""
    pr = None if root is None else root.find(f"{_XLSX_NS}workbookPr")
    return pr is not None and pr.get("date1904", "").lower() in ("1", "true")


def _xlsx_read_defined_names(root: Any) -> list[tuple[str, str, int, int, int, int]]:
    """Read simple cell/range defined names from a parsed ``xl/workbook.xml``.
    Returns ``(name, sheet, c1, r1, c2, r2)`` tuples. Built-in names
    (``_xlnm.*``) and non-reference names are skipped. Never raises -- a
    malformed or name-less workbook yields an empty list."""
    out: list[tuple[str, str, int, int, int, int]] = []
    container = None if root is None else root.find(f"{_XLSX_NS}definedNames")
    if container is None:
        return out
    for el in container.findall(f"{_XLSX_NS}definedName"):
        name = el.get("name", "")
        if not name or name.startswith("_xlnm."):
            continue
        parsed = _parse_defined_ref((el.text or "").strip())
        if parsed is not None:
            out.append((name, *parsed))
    return out


def _xlsx_sheet_name_error(names: list[str]) -> str | None:
    """Why Excel would reject this list of sheet names, or None."""
    seen: set[str] = set()
    for name in names:
        if not name.strip() or len(name) > 31:
            return f"sheet name {name!r} must be 1-31 characters for xlsx"
        if any(ch in name for ch in ":\\/?*[]") or name[0] == "'" or name[-1] == "'":
            return f"sheet name {name!r} has a character xlsx forbids (: \\ / ? * [ ] or edge ')"
        if name.lower() == "history":
            return "sheet name 'History' is reserved in xlsx"
        if name.lower() in seen:
            return f"sheet name {name!r} differs from another only by case, which xlsx forbids"
        seen.add(name.lower())
    return None


def _xlsx_write_cells(
    filename: str, cells: list[tuple[Any, ...]], sheet_names: list[str] | None = None
) -> None:
    """Write ``(sheet_name, col0, row0, kind, value[, cached])`` tuples.

    ``kind`` is in ``{'s','n','b','f'}``. For ``'f'``, ``value`` is the
    formula text (with or without leading ``=``) and the optional 6th
    element is a cached number or bool (``None`` writes no cached value).
    ``sheet_names`` lists every sheet in workbook order and fixes both the
    sheet order and the fate of sheets holding no cells; without it, sheets
    are created in the order they first appear in ``cells``. Raises on
    failure.
    """
    from gridcalc import _core

    _core.xlsx_write(filename, cells, list(sheet_names or []))


def _ast_has_pycall(node: Any) -> bool:
    from .formula.ast_nodes import (
        Apply,
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
    if isinstance(node, Apply):
        return _ast_has_pycall(node.func) or any(_ast_has_pycall(a) for a in node.args)
    if isinstance(node, BinOp):
        return _ast_has_pycall(node.left) or _ast_has_pycall(node.right)
    if isinstance(node, (UnaryOp, Percent)):
        return _ast_has_pycall(node.operand)
    return False


# Shared sentinel for read access to unpopulated cells.
# Must never be mutated -- all mutation paths go through cells
# that already exist in the sparse dict (post-setcell).
class _FrozenCell(Cell):
    """The shared placeholder returned for cells that don't exist yet.

    ``_ColProxy`` hands the *same* object back for every empty coordinate, so
    a caller that writes through ``grid.cells[c][r]`` without checking whether
    the cell exists mutates a process-wide singleton: every empty cell in
    every Grid then reports the written value. That failure is silent, global,
    and survives into unrelated Grids.

    Writing is therefore refused outright. Callers that intend to create a
    cell must go through ``Grid._ensure_cell`` (or ``setcell``), which stores
    a real Cell in the sparse dict.
    """

    __slots__ = ()

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(
            f"cannot assign to {name!r} on the shared empty-cell placeholder; "
            "use Grid._ensure_cell(c, r) to create a real cell first"
        )


def _make_empty_cell() -> Cell:
    """Build the singleton as a normal Cell, then freeze it.

    Re-classing after construction is what lets ``Cell.__init__`` populate the
    slots through ordinary assignment; ``_FrozenCell`` adds no slots of its
    own, so the layouts are compatible.
    """
    cl = Cell()
    cl.__class__ = _FrozenCell
    return cl


_EMPTY_CELL = _make_empty_cell()


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


def _quote_sheet(name: str) -> str:
    """``name`` as a formula sheet qualifier: bare when it lexes as one
    identifier, else in single quotes with ``'`` doubled."""
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and name.upper() not in ("TRUE", "FALSE"):
        return name
    return "'" + name.replace("'", "''") + "'"


def _rewrite_sheet_prefix(text: str, old: str, new: str) -> str:
    """Replace ``<old>!`` sheet prefixes in formula ``text`` with ``<new>!``.

    Matches bare and quoted (``'My Data'!``) qualifiers, and quotes ``new``
    when it needs quoting. Skips double-quoted string literals (``""`` is
    the escape for a literal quote). A qualifier must start on a
    non-identifier boundary, so ``X<old>!`` does not match.
    """
    out: list[str] = []
    i = 0
    n = len(text)
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
        prev = text[i - 1] if i > 0 else ""
        q = None if prev.isalnum() or prev == "_" else _SHEET_QUAL_RE.match(text, i)
        if q:
            quoted, bare = q.group(1), q.group(2)
            sheet = bare if quoted is None else quoted.replace("''", "'")
            out.append(_quote_sheet(new) + "!" if sheet == old else q.group(0))
            i = q.end()
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _decode_widths(payload: Any) -> dict[int, int]:
    """Parse a sheet's ``widths`` mapping from JSON, dropping anything odd.

    Keys arrive as strings (JSON object keys always do) and both keys and
    values come from a file the loader does not control, so entries that are
    not in-range integers are skipped rather than trusted -- a malformed
    width should cost the user that one column's size, not the workbook.
    """
    if not isinstance(payload, dict):
        return {}
    out: dict[int, int] = {}
    for key, value in payload.items():
        try:
            col, width = int(key), int(value)
        except (TypeError, ValueError):
            continue
        if 0 <= col < NCOL and COL_PX_MIN <= width <= COL_PX_MAX:
            out[col] = width
    return out


class Sheet:
    """A single named sheet's cell store, cycle set, and cursor.

    Workbook-level state (mode, code, named ranges, dep graph, etc.)
    lives on ``Grid``; each ``Sheet`` only owns the data that varies
    per-tab. ``Grid`` exposes ``_cells`` / ``cells`` / ``cc`` / ``cr`` /
    ``_circular`` as properties that delegate to ``sheets[active]`` so
    existing single-sheet code keeps working unchanged.
    """

    __slots__ = ("name", "_cells", "_circular", "cc", "cr", "widths")

    def __init__(self, name: str = "Sheet1") -> None:
        self.name: str = name
        self._cells: dict[tuple[int, int], Cell] = {}
        self._circular: set[tuple[int, int]] = set()
        self.cc: int = 0
        self.cr: int = 0
        # Per-column display widths in pixels, keyed by column index; absent
        # columns use the frontend's default. A *pixel* map is deliberately
        # not the same thing as `Grid.cw`, which is a uniform width in
        # character cells: the curses renderer lays columns out by multiplying
        # that one number and has no notion of a per-column size, so it
        # ignores this. Written by the web view, which does, and carried
        # through save/load so a resize survives the session.
        self.widths: dict[int, int] = {}


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
        # Named ranges bound into the PYTHON-mode eval globals on the last
        # recalc, so a name that disappears can be unbound again.
        # Workbook-persistent LP model definitions. Maps a user-chosen
        # name (or "default" for the convention slot) to an OptModel
        # holding the spec strings the user typed for sense/objective/
        # vars/constraints/bounds. Loaded from "models" in the JSON;
        # serialized back on jsonsave; consumed by the `:opt` dispatcher.
        self.models: dict[str, Any] = {}
        self.code: str = ""
        # A file's code block that the load policy refused. Never executed;
        # jsonsave writes it back so saving does not delete it.
        self.withheld_code: str = ""
        # Why the last load or save returned -1, and what the last load dropped.
        self.io_error: str | None = None
        self.load_warnings: list[str] = []
        self.mc: int = -1
        self.mr: int = -1
        self._eval_globals: dict[str, Any] = _make_eval_globals()
        self.requires: list[str] = []
        self.libs: list[str] = []
        self._module_errors: list[str] = []
        self.code_error: str | None = None
        self._mode: Mode = Mode.PYTHON
        # Topological recalc bookkeeping. Workbook-wide dep graph keyed by
        # (sheet, c, r) 3-tuples; `sheet` is the sheet name, never None for
        # entries that _refresh_deps installs (only `extract_refs` may emit
        # None transiently for unsheeted refs, but `_refresh_deps` always
        # passes a concrete sheet via formula_sheet).
        self._dep_of: dict[tuple[str | None, int, int], set[tuple[str | None, int, int]]] = {}
        self._subscribers: dict[tuple[str | None, int, int], set[tuple[str | None, int, int]]] = {}
        self._volatile: set[tuple[str | None, int, int]] = set()
        # Anchors currently rejected with #SPILL!. A blocked anchor has no
        # dependency on the cell blocking it, so any edit re-attempts every
        # blocked anchor -- cheap, since the set is normally empty.
        self._spill_blocked: set[tuple[str | None, int, int]] = set()
        # True means the graph matches the cells. Set by `_rebuild_dep_graph`,
        # kept by `_refresh_deps`/`_clear_deps`; cleared by any change the
        # incremental path misses (mode, `clear_all`, sheet rename/removal).
        # While False, the next recalc is a full one, which always rebuilds.
        self._dep_graph_built: bool = False

    @property
    def mode(self) -> Mode:
        return self._mode

    @mode.setter
    def mode(self, value: Mode) -> None:
        # PYTHON mode maintains no graph, so any switch leaves it stale.
        if value != self._mode:
            self._dep_graph_built = False
        self._mode = value

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
        self._dep_graph_built = False
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
        ``="Other!A1"`` is left untouched. Named ranges bound to ``old``
        follow it. The dep graph is marked stale; the caller recalcs.
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
        for nr in self.names:
            if nr.sheet == old:
                nr.sheet = new
        self._dep_graph_built = False

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
        if target == Mode.PYTHON:
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

    def load_requires(self, modules: list[str], allow_unknown: bool = False) -> None:
        """Load required modules into the eval namespace.

        ``allow_unknown`` passes through to ``load_modules``: unclassified
        modules are refused unless the caller has explicitly approved them.
        """
        if not modules:
            return
        mods, errors = load_modules(modules, allow_unknown=allow_unknown)
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
        """Remove all cells from the active sheet."""
        self._cells.clear()
        self._dep_graph_built = False

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
        self._spill_blocked.clear()
        named = self._dep_named_ranges()
        for s in self.sheets:
            for (c, r), cl in s._cells.items():
                if cl.type == FORMULA:
                    self._refresh_deps(c, r, cl, sheet=s.name, named=named)
                elif cl.type == SPILL and cl.spill_parent is not None:
                    self._register_deps((s.name, c, r), {(s.name, *cl.spill_parent)}, False)
        self._dep_graph_built = True

    def _refresh_deps(
        self,
        c: int,
        r: int,
        cl: Cell,
        sheet: str | None = None,
        named: dict[str, Any] | None = None,
    ) -> None:
        """Recompute the dep graph for one cell. Call after writing the cell.

        Parses the formula text if the AST cache is stale, extracts the
        static read set, and updates `_dep_of` / `_subscribers` / `_volatile`.
        Non-formula cells get their entries cleared. LEGACY mode skips
        graph maintenance entirely -- it uses fixed-point recalc, not topo.

        ``sheet`` defaults to the active sheet's name. Pass it explicitly
        from ``_rebuild_dep_graph`` when iterating non-active sheets.
        """
        if self.mode == Mode.PYTHON:
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
        if named is None:
            named = self._dep_named_ranges()
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
        cl.spill_parent = None
        cl.spill_shape = None
        # A formula result carries its error here; the literal or label
        # replacing it has none. `_store_formula_result` rewrites this for a
        # formula, so clearing unconditionally only affects the other two --
        # which previously kept the error of whatever formula they replaced.
        cl.err = None
        cl.err_msg = None
        cl.text = text
        self.dirty = 1

        if text.startswith("="):
            cl.type = FORMULA
        elif (num := parse_number(text.rstrip())) is not None:
            cl.val = num
            cl.type = NUM
        else:
            cl.type = LABEL
            cl.val = 0
        self._refresh_deps(c, r, cl)
        return True

    def _spill_predirty(self, c: int, r: int) -> set[tuple[int, int]]:
        """Handle the spill side-effects of overwriting the active-sheet
        cell (c, r), *before* it is written.

        If (c, r) is a spill cell, its anchor must recompute (to notice the
        blockage and go #SPILL!). If (c, r) is a spilling anchor, its spill
        is torn down here -- the write is about to clear ``spill_shape``, so
        ``_apply_spill`` could not do it later -- and the consumers of the
        removed cells are returned so recalc recomputes them.
        """
        if self.mode == Mode.PYTHON:
            return set()
        sheet = self._active.name
        cells = self._active._cells
        cl = cells.get((c, r))
        if cl is None:
            return set()
        extra: set[tuple[int, int]] = set()
        if cl.type == SPILL and cl.spill_parent is not None:
            extra.add(cl.spill_parent)
        if cl.spill_shape is not None:
            for sc_c, sc_r in self._spill_positions(c, r, cl.spill_shape):
                for sub_s, sub_c, sub_r in self._subscribers.get((sheet, sc_c, sc_r), ()):
                    if sub_s == sheet:
                        extra.add((sub_c, sub_r))
            self._clear_spill(sheet, c, r, cl)
        return extra

    def _blocked_anchors_active(self) -> set[tuple[int, int]]:
        """Blocked anchors on the active sheet, as (c, r) -- re-attempted on
        every edit since an edit may have cleared what blocked them."""
        name = self._active.name
        return {(c, r) for (s, c, r) in self._spill_blocked if s == name}

    def setcell(self, c: int, r: int, text: str) -> None:
        extra = self._spill_predirty(c, r) | self._blocked_anchors_active()
        if self._setcell_no_recalc(c, r, text) or not text:
            self.recalc({(c, r)} | extra)
        elif extra:
            self.recalc(extra)

    def setcells_bulk(self, cells: Iterable[tuple[int, int, str]]) -> None:
        """Set many cells, deferring recalc until all are written.

        Each tuple is (col, row, text). Out-of-bounds entries are ignored.
        Roughly N x faster than calling setcell() N times because recalc()
        runs once instead of after every cell.
        """
        changed: set[tuple[int, int]] = set()
        for c, r, text in cells:
            changed |= self._spill_predirty(c, r)
            if self._setcell_no_recalc(c, r, text):
                changed.add((c, r))
        if changed:
            self.recalc(changed | self._blocked_anchors_active())

    def recalc(self, dirty: set[tuple[int, int]] | None = None) -> None:
        if self.mode == Mode.PYTHON:
            self._recalc_python()
            return
        # `dirty` arrives as (c, r) 2-tuples on the active sheet; promote to
        # workbook keys once, then run the topo pass in a bounded fixpoint so
        # spills whose shape changed can recompute their new/old consumers.
        active_name = self._active.name
        if not self._dep_graph_built:
            dirty = None
        dirty3: set[tuple[str | None, int, int]] | None = (
            None if dirty is None else {(active_name, c, r) for (c, r) in dirty}
        )
        for _ in range(_MAX_SPILL_PASSES):
            spill_changed = self._recalc_topo(dirty3)
            if not spill_changed:
                break
            dirty3 = spill_changed

    def _recalc_python(self) -> None:
        # Derive the evaluation namespace fresh from the clean base on every
        # pass. `self._eval_globals` holds the base builtins plus whatever
        # `load_lib`/`load_requires` added, and user code is never executed into
        # it -- the same discipline `_build_py_registry` already uses for HYBRID.
        #
        # Executing into the persistent dict instead let definitions outlive the
        # code block that made them: clearing `code` left `f` callable and `=f()`
        # still answering, and a replacement block inherited whatever the old one
        # had defined but it did not. It also leaked those names into the
        # `builtins` handed to EXCEL/HYBRID evaluation, so a mode switch carried
        # them along. A copy costs one shallow dict per recalc.
        g = dict(self._eval_globals)
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

        # A value moves at least one link per pass, so an acyclic chain needs up
        # to one pass per formula. Past 100 passes, an unchanged set of changing
        # cells means a cycle: an acyclic graph cannot repeat that set.
        n_formulas = sum(1 for cl in self._cells.values() if cl.type == FORMULA)
        changed_cells: set[tuple[int, int]] = set()
        prev_changed: set[tuple[int, int]] = set()
        for npass in range(max(100, n_formulas + 1)):
            if npass >= 100 and changed_cells == prev_changed:
                break
            prev_changed = changed_cells
            changed_cells = set()

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

            # Inject named ranges (PYTHON mode). A sheet-qualified name reads
            # from that sheet; a sheet-agnostic one from the active sheet.
            for nr in self.names:
                nr_cells = self._sheet_cells(nr.sheet) if nr.sheet else self._cells
                data = []
                for r in range(nr.r1, nr.r2 + 1):
                    for c in range(nr.c1, nr.c2 + 1):
                        cl2 = nr_cells.get((c, r))
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
            stripped = _addr_only_re.sub("", _strip_literals(formula.replace("$", "")))
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
            start = F_CellRef(nr.c1, nr.r1, False, False, sheet=nr.sheet)
            if nr.c1 == nr.c2 and nr.r1 == nr.r2:
                named[nr.name] = start
            else:
                end = F_CellRef(nr.c2, nr.r2, False, False, sheet=nr.sheet)
                named[nr.name] = F_RangeRef(start, end)
        return named

    def _dep_named_ranges(self) -> dict[str, Any]:
        """Named ranges keyed lowercase, as `extract_refs` looks them up:
        names are case-insensitive, so `=SUM(sales)` depends on `Sales`."""
        return {k.lower(): v for k, v in self._build_named_ranges().items()}

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

    def _cell_formula_text(self, c: int, r: int, sheet: str | None = None) -> object:
        """Formula text (leading '=' included) of a formula cell, else None.
        Backs FORMULATEXT."""
        cl = self._sheet_cells(sheet).get((c, r))
        if cl is None or cl.type != FORMULA:
            return None
        return cl.text if cl.text.startswith("=") else f"={cl.text}"

    def _cell_lookup_value(self, c: int, r: int, sheet: str | None = None) -> object:
        cl = self._sheet_cells(sheet).get((c, r))
        if cl is None or cl.type == EMPTY:
            return None
        # An errored cell reads as its error, not as the NaN standing in for a
        # value it does not have. Returning the NaN dropped the code at the
        # reference boundary: `=1-A1` over a `#NAME?` produced an untyped NaN,
        # which is why `ISERROR` had to test `isnan` and `ERROR.TYPE` could
        # only answer `#N/A`. The evaluator already expects errors from here --
        # `_eval_range` returns one the moment a cell read yields it.
        if cl.err is not None:
            return cl.err
        if cl.type == LABEL:
            return cl.text
        if cl.matrix is not None:
            return cl.matrix
        # A bare reference to a spilling anchor reads only its top-left
        # scalar (Excel semantics); the whole array is reached via `A1#`
        # (see `_cell_spill_value`). This is what lets a range that
        # overlaps a spill -- `=SUM(A1:A3)` -- avoid double-counting the
        # anchor's array against the materialised spill cells.
        if cl.sval is not None:
            return cl.val if isinstance(cl.val, bool) else cl.sval
        return cl.val

    def _cell_spill_value(self, c: int, r: int, sheet: str | None = None) -> object:
        """Value of the `A1#` operator: the whole array a formula spilled,
        or the plain scalar for a non-array cell."""
        cl = self._sheet_cells(sheet).get((c, r))
        if cl is None or cl.type == EMPTY:
            return None
        if cl.err is not None:
            return cl.err
        if cl.arr is not None and cl.arr:
            return Vec(cl.arr, cols=cl.arr_cols)
        if cl.matrix is not None:
            return cl.matrix
        if cl.type == LABEL:
            return cl.text
        if cl.sval is not None:
            return cl.val if isinstance(cl.val, bool) else cl.sval
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
            cl.val = result
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
            # The anchor's own displayed value is the top-left element; keep
            # `val`/`sval`/`err` consistent with a spill cell's so a string-
            # or bool-first array renders correctly (the array itself stays
            # in `arr`, reachable via `A1#`).
            first = result.data[0] if result.data else float("nan")
            if isinstance(first, ExcelError):
                cl.val = float("nan")
                cl.err = first
            elif isinstance(first, bool):
                cl.val = first
                cl.sval = "TRUE" if first else "FALSE"
            elif isinstance(first, str):
                cl.val = 0.0
                cl.sval = first
            elif isinstance(first, (int, float)):
                cl.val = float(first)
            else:
                cl.val = float("nan")
            return
        cl.matrix = None
        cl.arr = None
        cl.arr_cols = None
        if result is None:
            cl.val = 0.0  # `=A1` over an empty cell is 0, as in Excel
            return
        try:
            cl.val = float(result)
        except (TypeError, ValueError):
            cl.val = float("nan")

    # -- Spill support --

    def _drop_all_spills(self) -> None:
        """Remove every SPILL cell and reset anchors so the next recalc
        rebuilds all spills from scratch. Called before structural edits
        (row/col insert/delete/swap) that relocate cells -- rebuilding is
        both simpler and safer than shifting spill ownership in place."""
        for s in self.sheets:
            for k in [k for k, cl in s._cells.items() if cl.type == SPILL]:
                del s._cells[k]
            for cl in s._cells.values():
                cl.spill_shape = None
        self._spill_blocked.clear()

    def _spill_anchor_at(self, c: int, r: int, sheet: str | None = None) -> tuple[int, int] | None:
        """If (c, r) is a spill cell, return its anchor (c, r); else None."""
        cl = self._sheet_cells(sheet).get((c, r))
        if cl is not None and cl.type == SPILL and cl.spill_parent is not None:
            return cl.spill_parent
        return None

    @staticmethod
    def _spill_positions(ac: int, ar: int, shape: tuple[int, int]) -> Iterator[tuple[int, int]]:
        """Non-anchor (c, r) positions of a spill rectangle."""
        rows, cols = shape
        for dr in range(rows):
            for dc in range(cols):
                if dr == 0 and dc == 0:
                    continue
                yield ac + dc, ar + dr

    def _clear_spill(
        self, sheet: str | None, ac: int, ar: int, anchor_cl: Cell
    ) -> set[tuple[str | None, int, int]]:
        """Remove the SPILL cells owned by the anchor at (ac, ar). Returns
        the workbook keys whose value was cleared."""
        changed: set[tuple[str | None, int, int]] = set()
        if anchor_cl.spill_shape is None:
            return changed
        cells = self._sheet_cells(sheet)
        for c, r in self._spill_positions(ac, ar, anchor_cl.spill_shape):
            sc = cells.get((c, r))
            if sc is not None and sc.type == SPILL and sc.spill_parent == (ac, ar):
                del cells[(c, r)]
                self._clear_deps((sheet, c, r))
                changed.add((sheet, c, r))
        anchor_cl.spill_shape = None
        return changed

    def _store_scalar_into(self, sc: Cell, val: Any) -> None:
        """Write one spilled element into a SPILL cell's value fields."""
        from .formula.errors import ExcelError

        sc.arr = None
        sc.arr_cols = None
        sc.matrix = None
        sc.sval = None
        sc.err = None
        sc.err_msg = None
        if isinstance(val, ExcelError):
            sc.val = float("nan")
            sc.err = val
        elif isinstance(val, bool):
            sc.val = val
            sc.sval = "TRUE" if val else "FALSE"
        elif isinstance(val, str):
            sc.val = 0.0
            sc.sval = val
        elif isinstance(val, (int, float)):
            sc.val = float(val)
        elif val is None:
            sc.val = 0.0
        else:
            try:
                sc.val = float(val)
            except (TypeError, ValueError):
                sc.val = float("nan")

    def _set_spill_error(self, cl: Cell) -> None:
        from .formula.errors import ExcelError

        cl.arr = None
        cl.arr_cols = None
        cl.matrix = None
        cl.sval = None
        cl.val = float("nan")
        cl.err = ExcelError.SPILL
        cl.err_msg = None
        cl.spill_shape = None

    def _apply_spill(
        self, sheet: str | None, ac: int, ar: int, anchor_cl: Cell
    ) -> set[tuple[str | None, int, int]]:
        """Materialise (or tear down) the spill for the anchor at (ac, ar).

        Returns the set of workbook keys whose value changed -- spill cells
        created, removed, or updated -- so the caller can recompute their
        consumers in a follow-up pass.
        """
        changed: set[tuple[str | None, int, int]] = set()
        self._spill_blocked.discard((sheet, ac, ar))
        arr = anchor_cl.arr
        cols = anchor_cl.arr_cols if anchor_cl.arr_cols else 1
        # No array, or a single element: not a spill. Tear down any prior.
        if anchor_cl.type != FORMULA or not arr or len(arr) <= 1:
            return self._clear_spill(sheet, ac, ar, anchor_cl)
        rows = len(arr) // cols
        if rows * cols <= 1:
            return self._clear_spill(sheet, ac, ar, anchor_cl)
        new_shape = (rows, cols)
        cells = self._sheet_cells(sheet)
        old_positions = (
            set(self._spill_positions(ac, ar, anchor_cl.spill_shape))
            if anchor_cl.spill_shape is not None
            else set()
        )
        # Off-sheet, or blocked by a foreign non-empty cell -> #SPILL!.
        if ac + cols > NCOL or ar + rows > NROW:
            changed |= self._clear_spill(sheet, ac, ar, anchor_cl)
            self._set_spill_error(anchor_cl)
            self._spill_blocked.add((sheet, ac, ar))
            return changed
        for c, r in self._spill_positions(ac, ar, new_shape):
            other = cells.get((c, r))
            if other is None or other.type == EMPTY:
                continue
            if other.type == SPILL and other.spill_parent == (ac, ar):
                continue
            changed |= self._clear_spill(sheet, ac, ar, anchor_cl)
            self._set_spill_error(anchor_cl)
            self._spill_blocked.add((sheet, ac, ar))
            return changed
        # Materialise each non-anchor element (arr is row-major).
        new_positions: set[tuple[int, int]] = set()
        for dr in range(rows):
            for dc in range(cols):
                if dr == 0 and dc == 0:
                    continue
                c, r = ac + dc, ar + dr
                sc = cells.get((c, r))
                if sc is None:
                    sc = Cell()
                    cells[(c, r)] = sc
                prev = (sc.type, sc.val, sc.sval, sc.err)
                sc.clear()
                sc.type = SPILL
                sc.spill_parent = (ac, ar)
                self._store_scalar_into(sc, arr[dr * cols + dc])
                new_positions.add((c, r))
                self._clear_deps((sheet, c, r))
                self._register_deps((sheet, c, r), {(sheet, ac, ar)}, False)
                if (sc.type, sc.val, sc.sval, sc.err) != prev:
                    changed.add((sheet, c, r))
        # Remove cells that were in the old rectangle but not the new one.
        for c, r in old_positions - new_positions:
            sc = cells.get((c, r))
            if sc is not None and sc.type == SPILL and sc.spill_parent == (ac, ar):
                del cells[(c, r)]
                self._clear_deps((sheet, c, r))
                changed.add((sheet, c, r))
        anchor_cl.spill_shape = new_shape
        return changed

    def _recalc_topo(
        self, dirty3: set[tuple[str | None, int, int]] | None
    ) -> set[tuple[str | None, int, int]]:
        """Topological recalc: evaluate only the closure of dirty cells.

        Multi-sheet aware: dep keys are ``(sheet, c, r)`` workbook-wide;
        the closure spans every sheet that has formulas reading the
        dirty cells.

        ``dirty3`` is a set of workbook ``(sheet, c, r)`` keys, or ``None``
        for a full recompute across all sheets. Returns the set of spill
        positions whose value changed this pass, so ``recalc`` can drive a
        follow-up pass over their consumers.
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
            cell_spill_value=self._cell_spill_value,
            cell_formula_text=self._cell_formula_text,
        )

        spill_changed: set[tuple[str | None, int, int]] = set()

        # Build the closure: BFS over `_subscribers` from the dirty set and
        # the volatile cells, so a volatile cell's consumers recompute too.
        # If dirty is None, the closure is every formula cell across every
        # sheet, and the graph is rebuilt: callers such as undo and sort
        # write cells directly and rely on a full recalc to catch up.
        if dirty3 is None:
            self._rebuild_dep_graph()
            closure: set[tuple[str | None, int, int]] = set()
            for s in self.sheets:
                for (c, r), cl in s._cells.items():
                    if cl.type == FORMULA:
                        closure.add((s.name, c, r))
        else:
            closure = set(self._volatile)
            for k in dirty3:
                cl_dirty = self._cell_at(k)
                if cl_dirty is not None and cl_dirty.type == FORMULA:
                    closure.add(k)
            stack = list(dirty3 | self._volatile)
            while stack:
                k = stack.pop()
                for sub in self._subscribers.get(k, ()):
                    if sub not in closure:
                        closure.add(sub)
                        stack.append(sub)

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
                env.current_sheet = sheet_name
                try:
                    result = evaluate(fcl.ast, env)
                except Exception:
                    result = float("nan")
                self._store_formula_result(fcl, result)
                spill_changed |= self._apply_spill(sheet_name, c, r, fcl)
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
                    if circ_cl.spill_shape is not None:
                        spill_changed |= self._clear_spill(key[0], key[1], key[2], circ_cl)
                    circ_cl.arr = None
                    circ_cl.matrix = None
                    circ_cl.val = float("nan")
                    circ_cl.err = _XE.CIRC
                    circ_cl.err_msg = None

        return spill_changed

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

    def _rewrite_all_sheets(self, move: _RefMove) -> None:
        """Apply ``move`` to every reference in the workbook that resolves
        against the active sheet -- the one a structural edit acts on.

        Every sheet's formulas are scanned, not just the active sheet's: a
        formula on another sheet that names this one (`Sheet1!A2`) has to
        follow the edit, and one on the active sheet that names another
        (`Data!A2`) must not. Scanning only the active sheet got both wrong,
        rewriting the cross-sheet references it should have left alone and
        missing the ones it should have moved.
        """
        edited = self._active.name
        for sheet in self.sheets:
            for cl in sheet._cells.values():
                if cl.type != FORMULA:
                    continue
                new = _rewrite_refs_on_sheet(cl.text, sheet.name, edited, move)
                if new is not None:
                    cl.text = new

    def _fixrefs(self, axis: str, a: int, b: int) -> None:
        def swap(v: int) -> int:
            return b if v == a else a if v == b else v

        def move(c1: int, r1: int, c2: int, r2: int) -> tuple[int, int, int, int]:
            if axis == "R":
                return c1, swap(r1), c2, swap(r2)
            return swap(c1), r1, swap(c2), r2

        self._rewrite_all_sheets(move)

    def _shiftrefs(self, axis: str, pos: int, direction: int) -> None:
        def move(c1: int, r1: int, c2: int, r2: int) -> tuple[int, int, int, int] | None:
            a1, a2 = (r1, r2) if axis == "R" else (c1, c2)
            if direction > 0:
                n1 = a1 + 1 if a1 >= pos else a1
                n2 = a2 + 1 if a2 >= pos else a2
            elif a1 == pos and a2 == pos:
                return None  # Excel: #REF!
            else:
                # A deleted range corner lands on the surviving line next to it
                # on the range's side, so the range shrinks.
                n1 = a1 - 1 if a1 > pos or (a1 == pos and a2 < pos) else a1
                n2 = a2 - 1 if a2 > pos or (a2 == pos and a1 < pos) else a2
            return (c1, n1, c2, n2) if axis == "R" else (n1, r1, n2, r2)

        self._rewrite_all_sheets(move)

    def _shift_names(self, axis: str, pos: int, direction: int) -> None:
        """Move named-range coordinates across an insert/delete.

        The sibling of `_shiftrefs`: that rewrites references written in cell
        text, this moves the rectangles held in `self.names`. Without it a name
        keeps pointing at the coordinates it had before the edit, so it reads
        the wrong cells and reports no error at all -- silently wrong answers,
        the worst failure mode available.

        Rules match a spreadsheet's: a line inserted *above* a range moves the
        whole range down; one inserted *inside* it grows the range; deletes
        mirror both. A delete that consumes every line of a range leaves
        nothing to point at, so the name is dropped -- a formula using it then
        fails as an unknown name, which is visible, rather than resolving to a
        rectangle that no longer means anything. (Excel shows `#REF!` here; the
        distinction is the error text, not the outcome.)

        Only names resolving against the edited sheet move: sheet-qualified
        ones bound elsewhere are untouched, and a sheet-agnostic name follows
        the active sheet because that is where it resolves.
        """
        active = self._active.name
        limit = NROW if axis == "R" else NCOL
        kept: list[NamedRange] = []
        for nr in self.names:
            if nr.sheet is not None and nr.sheet != active:
                kept.append(nr)
                continue
            lo, hi = (nr.r1, nr.r2) if axis == "R" else (nr.c1, nr.c2)
            if direction > 0:
                if pos <= lo:
                    lo += 1
                    hi += 1
                elif pos <= hi:
                    hi += 1
                lo = min(lo, limit - 1)
                hi = min(hi, limit - 1)
            else:
                if pos < lo:
                    lo -= 1
                    hi -= 1
                elif pos <= hi:
                    hi -= 1
                if hi < lo:
                    continue  # the range lost every line it covered
            if axis == "R":
                nr.r1, nr.r2 = lo, hi
            else:
                nr.c1, nr.c2 = lo, hi
            kept.append(nr)
        self.names = kept

    def _shift_widths(self, pos: int, direction: int) -> None:
        """Move per-column widths across a column insert/delete.

        A width belongs to the column it was dragged on, so it has to travel
        with that column -- otherwise inserting a column leaves every width to
        the right attached to its neighbour. A deleted column's width goes with
        it.
        """
        widths = self._active.widths
        if not widths:
            return
        shifted: dict[int, int] = {}
        for c, w in widths.items():
            if direction < 0 and c == pos:
                continue  # the column itself is gone
            nc = c + direction if c >= pos else c
            if 0 <= nc < NCOL:
                shifted[nc] = w
        self._active.widths = shifted

    def can_insert(self, axis: str, at: int, count: int = 1) -> bool:
        """True when inserting ``count`` lines at ``at`` would lose no data.

        The sheet is a fixed NROW x NCOL grid, so an insert near the end pushes
        the last lines past the edge. Silently dropping them is data loss the
        user never asked for and cannot see, so callers check first and refuse.
        ``axis`` is "R" for rows or "C" for columns.
        """
        limit = NROW if axis == "R" else NCOL
        edge = limit - count  # a line at or past this is pushed off the end
        for (c, r), cl in self._cells.items():
            if cl.type == EMPTY:
                continue
            pos = r if axis == "R" else c
            if pos >= at and pos >= edge:
                return False
        return True

    def insertrow(self, at: int) -> bool:
        """Insert one row at ``at``. False, without mutating, if that would push
        a populated row off the bottom of the sheet."""
        if not self.can_insert("R", at):
            return False
        self._drop_all_spills()
        new_cells: dict[tuple[int, int], Cell] = {}
        for (c, r), cl in self._cells.items():
            if r >= at:
                new_cells[(c, r + 1)] = cl
            else:
                new_cells[(c, r)] = cl
        self._cells = new_cells
        self._shiftrefs("R", at, +1)
        self._shift_names("R", at, +1)
        self._rebuild_dep_graph()
        self.dirty = 1
        return True

    def insertcol(self, at: int) -> bool:
        """Insert one column at ``at``. False, without mutating, if that would
        push a populated column off the right edge of the sheet."""
        if not self.can_insert("C", at):
            return False
        self._drop_all_spills()
        new_cells: dict[tuple[int, int], Cell] = {}
        for (c, r), cl in self._cells.items():
            if c >= at:
                new_cells[(c + 1, r)] = cl
            else:
                new_cells[(c, r)] = cl
        self._cells = new_cells
        self._shiftrefs("C", at, +1)
        self._shift_names("C", at, +1)
        self._shift_widths(at, +1)
        self._rebuild_dep_graph()
        self.dirty = 1
        return True

    def deleterow(self, at: int) -> None:
        self._drop_all_spills()
        self._shiftrefs("R", at, -1)
        self._shift_names("R", at, -1)
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
        self._drop_all_spills()
        self._shiftrefs("C", at, -1)
        self._shift_names("C", at, -1)
        self._shift_widths(at, -1)
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
        self._drop_all_spills()
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
        self._drop_all_spills()
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
        self._setcell_no_recalc(dc, dr, adjust_refs(src.text, dc - sc, dr - sr))
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
                label = False
                if isinstance(v, dict):
                    label = v.get("label") is True
                    cell_bold = 1 if v.get("bold") else 0
                    cell_underline = 1 if v.get("underline") else 0
                    cell_italic = 1 if v.get("italic") else 0
                    fmt_val = v.get("fmt", "")
                    cell_fmtstr = v.get("fmtstr", "")
                    if not isinstance(fmt_val, str) or not isinstance(cell_fmtstr, str):
                        raise ValueError(
                            f"{cellname(c_idx, r_idx)}: fmt and fmtstr must be strings"
                        )
                    cell_fmt = fmt_val[:1]
                    v = v.get("v", None)
                if v is None or (isinstance(v, str) and v == ""):
                    continue
                if isinstance(v, str):
                    text = v
                elif isinstance(v, (int, float)):
                    if isinstance(v, int) or (abs(v) < 1e15 and v == int(v)):
                        text = str(int(v))
                    else:
                        # repr round-trips a double; "%g" kept 6 digits.
                        text = repr(v)
                else:
                    continue
                if label:
                    self._put_label(c_idx, r_idx, text)
                else:
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
        self.io_error = None
        try:
            with open(filename) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
            self.io_error = str(exc)
            return -1

        # A workbook is a JSON *object*. `[]`, `null`, a bare number or string
        # are all valid JSON and decode without error, so the type has to be
        # checked before anything reads a key off it -- otherwise a malformed
        # file raises AttributeError out of a function documented to report
        # failure by returning -1.
        if not isinstance(d, dict):
            return -1

        version = d.get("version", 1)
        if not isinstance(version, int) or version > FILE_VERSION:
            return -1

        # Field types are checked here, above the reset, for the same reason
        # the document type is: the loader must report a malformed file by
        # returning -1, not by raising out of the middle of a half-applied
        # load. `code` and `requires` are the two fields whose contents are
        # handed to something that assumes a string -- `ast.parse` and the
        # requirement regex -- so a JSON number or object in either one took
        # the load path out with an AttributeError or TypeError *after* the
        # workbook had already been cleared.
        if "code" in d and not isinstance(d["code"], str):
            return -1
        requires_field = d.get("requires")
        if isinstance(requires_field, list) and not all(isinstance(r, str) for r in requires_field):
            return -1

        # A malformed nested field, or a recalc that raises, is found only
        # while loading, after the reset.
        return self._load_or_restore(lambda: self._jsonload_into(d, policy))

    def _reset_workbook(self) -> None:
        """Drop every sheet and workbook-level field before a load.

        A load *replaces* the workbook; it does not merge into it. Without an
        explicit reset the v1 path wrote its cells into whichever sheet was
        already open, so anything outside the incoming payload survived -- a
        second workbook silently inherited the first one's data. Worse, a file
        whose code the policy refused kept the *previous* workbook's code, and
        its functions stayed callable, which is precisely what refusing to
        load code is meant to prevent.
        """
        self.sheets = [Sheet()]
        self.active = 0
        self.clear_all()  # also drops the workbook-wide dep graph
        self.names = []
        self.models = {}
        self.libs = []
        self.requires = []
        self.code = ""
        self.withheld_code = ""
        self.code_error = None
        self._module_errors = []
        self.load_warnings = []
        # Rebuild the eval namespace from the bare base: a previous workbook's
        # libs and required modules must not stay reachable either.
        self._eval_globals = _make_eval_globals()

    def _jsonload_into(self, d: dict[str, Any], policy: Any) -> None:
        """Replace the workbook with the decoded file ``d``; may raise part-way."""
        self._reset_workbook()

        if "mode" in d:
            parsed = Mode.parse(d.get("mode"))
            self.mode = parsed if parsed is not None else Mode.PYTHON
        else:
            self.mode = Mode.PYTHON

        # Only adopt the file's code when the policy allows it. The reset above
        # already cleared any inherited code, so a refusal now means "no code",
        # not "whatever was loaded before".
        if policy is None or policy.load_code:
            self.code = d.get("code", "")
        else:
            self.withheld_code = d.get("code", "")

        libs = d.get("libs", [])
        if isinstance(libs, list):
            self.libs = [str(lib) for lib in libs]
            for lib in self.libs:
                self.load_lib(lib)
        self._apply_mode_libs()

        requires = d.get("requires", [])
        if isinstance(requires, list):
            self.requires = requires
            # No policy means the caller vouched for the file (the library
            # API, not a UI open), so unclassified modules are theirs to
            # allow; a policy decides for itself.
            approved = requires if policy is None else policy.approved_modules
            allow_unknown = True if policy is None else policy.allow_unknown
            if approved:
                self.load_requires(approved, allow_unknown=allow_unknown)

        names_dict = d.get("names", {})
        self.names = []
        # Structured fields are as untrusted as the top level: `names` may be a
        # list, and an entry's range may be a number, which would fail on
        # `.items()` and on the `"!" in rng` test respectively.
        if not isinstance(names_dict, dict):
            names_dict = {}
        for name, rng in names_dict.items():
            if not isinstance(name, str) or not isinstance(rng, str):
                continue
            nr = NamedRange(name=name)
            # A ``Sheet!A1:B3`` name carries an explicit sheet; a bare
            # ``A1:B3`` stays sheet-agnostic.
            if "!" in rng:
                sheet_part, _, rng = rng.rpartition("!")
                nr.sheet = sheet_part or None
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

        # LP model definitions (see `:opt def NAME ...`). Stored as a
        # mapping `name -> {sense, objective, vars, constraints, bounds?}`
        # of *spec strings* the user typed -- not pre-resolved cell
        # coordinates. Parsing is deferred to `:opt run`; an unparseable
        # entry surfaces there, not silently at load time.
        models_dict = d.get("models", {})
        self.models = {}
        if isinstance(models_dict, dict):
            from .opt import OptError, OptModel

            for mname, mdata in models_dict.items():
                if not isinstance(mname, str) or not isinstance(mdata, dict):
                    continue
                try:
                    self.models[mname] = OptModel.from_json(mdata)
                except OptError:
                    # Skip malformed entries rather than aborting the load.
                    # The user can re-define via `:opt def` to overwrite.
                    continue

        fmt_dict = d.get("format", {})
        if not isinstance(fmt_dict, dict):
            fmt_dict = {}
        w = fmt_dict.get("width", 0)
        # A non-numeric width would raise from the comparison, not just be
        # ignored; bool is an int subclass but never lands in 4..40.
        if isinstance(w, (int, float)) and 4 <= w <= 40:
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
                sh.widths = _decode_widths(entry.get("widths"))
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
        if self.mode != Mode.PYTHON:
            self._dep_graph_built = True
        self.recalc()

    def _encode_sheet_rows(self, cells: dict[tuple[int, int], Cell]) -> list[list[Any]]:
        """Encode one sheet's cell store as a v2 ``cells`` rows list."""
        # SPILL cells are derived from their anchor's formula and are not
        # persisted -- they are rebuilt when the anchor recomputes on load.
        maxr = -1
        maxc = -1
        for (c, r), cl in cells.items():
            if cl.type != EMPTY and cl.type != SPILL:
                if r > maxr:
                    maxr = r
                if c > maxc:
                    maxc = c
        rows: list[list[Any]] = []
        for r in range(maxr + 1):
            row: list[Any] = []
            for c in range(maxc + 1):
                sc = cells.get((c, r))
                if not sc or sc.type == EMPTY or sc.type == SPILL:
                    row.append(None)
                    continue
                elif sc.type == NUM:
                    if math.isinf(sc.val):
                        # JSON has no infinity; this text reloads as one.
                        val: Any = "1e999" if sc.val > 0 else "-1e999"
                    elif math.isnan(sc.val):
                        val = None  # no text reloads as NaN
                    elif abs(sc.val) < 1e15 and sc.val == int(sc.val):
                        val = int(sc.val)
                    else:
                        val = sc.val
                    row.append(val)
                else:
                    row.append(sc.text)
                # A label whose text would load back as a number or formula
                # (an imported "00123") says so; older readers ignore the key.
                label = sc.type == LABEL and (
                    sc.text.startswith("=") or parse_number(sc.text.rstrip()) is not None
                )

                has_style = sc.bold or sc.underline or sc.italic or sc.fmt or sc.fmtstr or label
                if has_style:
                    styled: dict[str, Any] = {"v": row[-1]}
                    if label:
                        styled["label"] = True
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

        if self.code or self.withheld_code:
            out["code"] = self.code or self.withheld_code

        if self.names:
            out["names"] = {}
            for nr in self.names:
                a = cellname(nr.c1, nr.r1)
                rng = f"{a}:{col_name(nr.c2)}{nr.r2 + 1}"
                # A sheet-qualified name serialises as ``Sheet!A1:B3`` so the
                # sheet survives the round-trip; sheet-agnostic names keep the
                # bare ``A1:B3`` form (backward compatible with v1/v2 files).
                if nr.sheet:
                    rng = f"{nr.sheet}!{rng}"
                out["names"][nr.name] = rng

        if self.models:
            out["models"] = {name: m.to_json() for name, m in self.models.items()}

        out["format"] = {"width": self.cw}

        # v2: per-sheet payload. Active sheet recorded by name so the
        # round-trip restores the user's view even when sheet order
        # changes.
        out["active"] = self._active.name
        out["sheets"] = []
        for s in self.sheets:
            entry: dict[str, Any] = {"name": s.name, "cells": self._encode_sheet_rows(s._cells)}
            if s.widths:
                # Omitted when empty, so a workbook never touched by a
                # graphical frontend serializes exactly as it did before.
                entry["widths"] = {str(c): w for c, w in sorted(s.widths.items())}
            out["sheets"].append(entry)

        def write(path: str) -> None:
            with open(path, "w") as f:
                json.dump(out, f, indent=2, allow_nan=False)
                f.write("\n")

        return self._save_via(filename, write)

    def _save_via(self, filename: str, write: Callable[[str], object]) -> int:
        """Write ``filename`` atomically with ``write``; 0, or -1 with ``io_error`` set."""
        self.io_error = None
        try:
            _write_atomic(filename, write)
        except Exception as exc:  # noqa: BLE001
            self.io_error = str(exc) or type(exc).__name__
            return -1
        return 0

    def xlsxload(self, filename: str) -> int:
        self.io_error = None
        try:
            sheet_order, cells, fallbacks = _xlsx_read_cells(filename)
        except Exception as exc:  # noqa: BLE001
            self.io_error = str(exc) or type(exc).__name__
            return -1
        return self._load_or_restore(
            lambda: self._xlsxload_into(filename, sheet_order, cells, fallbacks)
        )

    def _xlsxload_into(
        self, filename: str, sheet_order: list[str], cells: list[tuple[Any, ...]], fallbacks: int
    ) -> None:
        """Replace the workbook with the cells ``_xlsx_read_cells`` returned."""
        self._reset_workbook()
        self.mode = Mode.EXCEL
        self._apply_mode_libs()

        # Replace the auto-created Sheet1 with the first xlsx sheet
        # (preserves the source workbook's first-sheet name) and add
        # the rest, empty ones included.
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
        sheet_index = {name: i for i, name in enumerate(sheet_order)}

        # Import simple defined names as sheet-qualified named ranges, so
        # formulas like `=SUM(SalesData)` resolve.
        root = _xlsx_workbook_xml(filename)
        self.names = [
            NamedRange(name=nm, c1=c1, r1=r1, c2=c2, r2=r2, sheet=sh)
            for (nm, sh, c1, r1, c2, r2) in _xlsx_read_defined_names(root)
        ]
        # 1462 days separate the 1904 and 1900 epochs. A value under 1 is a
        # time of day, which has no epoch.
        date_shift = 1462.0 if _xlsx_date1904(root) else 0.0

        # Each value is stored by its xlsx type, not re-parsed as input text:
        # the string "00123" stays text and "TRUE" the boolean stays a boolean.
        from .formula.errors import parse_error_literal

        dropped = 0
        for sname, c, r, kind, value, numfmt_code, numfmt_id in cells:
            if not (0 <= c < NCOL and 0 <= r < NROW):
                dropped += 1
                continue
            self.active = sheet_index[sname]
            datefmt = normalise_format(numfmt_code, numfmt_id)
            if kind == "s":
                self._put_label(c, r, value)
            elif kind == "e":
                if parse_error_literal(value) is not None:
                    self._setcell_no_recalc(c, r, "=" + value)
                else:
                    self._put_label(c, r, value)
            elif kind == "b":
                self._setcell_no_recalc(c, r, "=TRUE" if value else "=FALSE")
            elif kind == "n":
                if not math.isfinite(value):
                    continue
                if datefmt and value >= 1:
                    value += date_shift
                self._setcell_no_recalc(c, r, _number_text(value))
            else:
                self._setcell_no_recalc(c, r, value)
            cl = self._cells.get((c, r))
            if datefmt and cl is not None and cl.type in (NUM, FORMULA):
                cl.fmtstr = datefmt
        self.active = 0
        if dropped:
            self.load_warnings.append(
                f"{dropped} cells beyond {NCOL} columns x {NROW} rows were not imported"
            )
        if fallbacks:
            self.load_warnings.append(
                f"{fallbacks} shared or array formulas were imported as their cached values"
            )

        # One full recalc, which rebuilds the dep graph, so every formula sees
        # the final workbook, including cross-sheet names loaded out of order.
        self.recalc()
        self.dirty = 0
        self.filename = filename

    def _put_label(self, c: int, r: int, text: str) -> None:
        """Store ``text`` as a label on the active sheet without parsing it."""
        if not text:
            return
        cl = self._ensure_cell(c, r)
        cl.clear()
        cl.type = LABEL
        cl.text = text
        self._clear_deps((self._active.name, c, r))
        self.dirty = 1

    def _load_or_restore(self, load: Callable[[], None]) -> int:
        """Run ``load``; if it raises, put the previous workbook back and return -1.

        A load replaces sheets, names and globals rather than mutating them, so
        restoring the attributes restores the workbook. The dep graph dicts are
        mutated in place, hence the forced rebuild.
        """
        saved = dict(self.__dict__)
        try:
            load()
        except Exception as exc:  # noqa: BLE001
            self.__dict__.clear()
            self.__dict__.update(saved)
            self._dep_graph_built = False
            self.io_error = f"{type(exc).__name__}: {exc}"
            return -1
        return 0

    def xlsxsave(self, filename: str) -> int:
        self.io_error = None
        # Empty workbook: nothing to write.
        if all(cl.type == EMPTY for s in self.sheets for cl in s._cells.values()):
            self.io_error = "workbook is empty"
            return -1
        bad = _xlsx_sheet_name_error([s.name for s in self.sheets])
        if bad:
            self.io_error = bad
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
                # A date cell is a serial plus a format; without the format
                # the file that comes back out is a column of five-digit
                # numbers, which is what "dates are neither read nor written"
                # used to mean in practice.
                datefmt = cl.fmtstr if cl.fmtstr and is_date_format(cl.fmtstr) else ""
                if cl.type == LABEL:
                    text = cl.text[1:] if cl.text.startswith('"') else cl.text
                    payload.append((s.name, c, r, "s", text))
                elif cl.type == NUM:
                    payload.append((s.name, c, r, "n", float(cl.val), datefmt))
                elif cl.type == FORMULA or (cl.type == SPILL and not preserve_formulas):
                    # The cached result: a bool or a finite float. A text or
                    # error result is written with no cached value.
                    val = cl.val
                    result = cl.sval if cl.err is None and not isinstance(val, bool) else None
                    cached: float | bool | None = None
                    if cl.err is None and result is None:
                        if isinstance(val, bool):
                            cached = val
                        elif math.isfinite(val):
                            cached = float(val)
                    if preserve_formulas and cl.type == FORMULA and cl.text:
                        payload.append((s.name, c, r, "f", cl.text, cached, datefmt))
                    elif result is not None:
                        payload.append((s.name, c, r, "s", result))
                    elif isinstance(cached, bool):
                        payload.append((s.name, c, r, "b", cached))
                    elif cached is not None:
                        payload.append((s.name, c, r, "n", cached, datefmt))
        return self._save_via(
            filename,
            lambda path: _xlsx_write_cells(path, payload, [s.name for s in self.sheets]),
        )

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

        def value(cl: Cell | None) -> str:
            if not cl or cl.type == EMPTY:
                return ""
            if cl.type == LABEL:
                return cl.text[1:] if cl.text.startswith('"') else cl.text
            if cl.err is not None:
                return ""
            if cl.sval is not None:
                return cl.sval  # a text or boolean result
            v = cl.val
            if isinstance(v, float) and math.isnan(v):
                return ""
            return str(int(v)) if abs(v) < 1e15 and v == int(v) else repr(float(v))

        def write(path: str) -> None:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                for r in range(maxr + 1):
                    writer.writerow([value(self._cells.get((c, r))) for c in range(maxc + 1)])

        return self._save_via(filename, write)

    def csvload(self, filename: str) -> int:
        """Import cells from a CSV file. Numbers become NUM cells, rest become LABELs."""
        self.io_error = None
        try:
            with open(filename, newline="") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            self.io_error = str(exc)
            return -1

        reader = csv.reader(StringIO(content))
        cells: list[tuple[int, int, str]] = []
        for r_idx, row in enumerate(reader):
            if r_idx >= NROW:
                break
            for c_idx, val in enumerate(row):
                if c_idx >= NCOL:
                    break
                val = val.strip()
                if val:
                    cells.append((c_idx, r_idx, val))
        # One recalc: a PYTHON-mode recalc per setcell made this quadratic.
        self.setcells_bulk(cells)
        return 0

    def pdload(self, filename: str, header: bool = True) -> int:
        """Load a CSV, TSV or JSON file into grid cells using pandas.

        CSV and TSV fields are parsed as typed input, as ``csvload`` does. JSON
        values keep their type: a string stays a label, a boolean becomes
        ``=TRUE``/``=FALSE``. ``header`` writes JSON column names into row 0.
        Returns -1 if pandas is not installed or the file type is unsupported.
        """
        try:
            import pandas as pd  # noqa: I001
        except ImportError:
            return -1

        self.io_error = None
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _PD_EXTS:
            self.io_error = f"unsupported file type: {ext}"
            return -1
        try:
            if ext == ".json":
                df = pd.read_json(filename, dtype=False, convert_dates=False, precise_float=True)
            else:
                # All fields as text: pandas' NA markers and float parser would
                # drop "NA" labels and round 0.30000000000000004. Fixed `names`
                # pad short rows and cut long ones at NCOL, as `csvload` does.
                sep = "\t" if ext in (".tsv", ".tab") else ","
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", pd.errors.ParserWarning)
                    df = pd.read_csv(
                        filename,
                        sep=sep,
                        header=None,
                        names=range(NCOL),
                        index_col=False,
                        dtype=str,
                        keep_default_na=False,
                    )
        except Exception as exc:  # noqa: BLE001
            self.io_error = str(exc) or type(exc).__name__
            return -1

        def label(v: object) -> str:
            t = str(v)
            return '"' + t if t.startswith("=") or parse_number(t.rstrip()) is not None else t

        def json_text(v: object) -> str:
            if isinstance(v, bool):
                t = "TRUE" if v else "FALSE"
                return "=" + (t.title() if self.mode == Mode.PYTHON else t)
            if isinstance(v, int):
                return str(v)
            if isinstance(v, float):
                return _number_text(v) if math.isfinite(v) else ""
            return label(v)

        rows: list[tuple[Any, ...]] = list(df.itertuples(index=False, name=None))
        if ext == ".json" and header:
            rows.insert(0, tuple(df.columns))
        cells: list[tuple[int, int, str]] = []
        for r, row in enumerate(rows[:NROW]):
            for c, v in enumerate(row[:NCOL]):
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    continue
                text = json_text(v) if ext == ".json" else str(v).strip()
                if text:
                    cells.append((c, r, text))
        self.setcells_bulk(cells)
        return 0

    def pdsave(self, filename: str) -> int:
        """Export grid values to a CSV, TSV or JSON file, with row 0 as headers.

        Returns -1 if pandas is not installed, the file type is unsupported, or
        JSON headers repeat.
        """
        try:
            import pandas as pd  # noqa: I001
        except ImportError:
            return -1

        self.io_error = None
        ext = os.path.splitext(filename)[1].lower()
        if ext not in _PD_EXTS:
            self.io_error = f"unsupported file type: {ext}"
            return -1

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

        def value(cl: Cell | None) -> Any:
            if not cl or cl.type == EMPTY:
                return None
            if cl.type == LABEL:
                return cl.text[1:] if cl.text.startswith('"') else cl.text
            if cl.err is not None:
                return None
            if isinstance(cl.val, bool):
                return cl.val if ext == ".json" else ("TRUE" if cl.val else "FALSE")
            if cl.sval is not None:
                return cl.sval  # a text result; val is a 0 placeholder
            v = float(cl.val)
            if not math.isfinite(v):
                return None
            return int(v) if v.is_integer() and abs(v) < 1e15 else v

        columns = [
            str(h) if (h := value(self._cells.get((c, 0)))) is not None else col_name(c)
            for c in range(maxc + 1)
        ]
        data = [
            [value(self._cells.get((c, r))) for c in range(maxc + 1)] for r in range(1, maxr + 1)
        ]

        if ext == ".json" and len(set(columns)) < len(columns):
            self.io_error = "JSON export needs unique headers in row 1"
            return -1

        def write(path: str) -> None:
            if ext == ".json":
                # pandas' to_json rounds floats to at most 15 digits.
                with open(path, "w") as f:
                    records = [dict(zip(columns, row, strict=True)) for row in data]
                    json.dump(records, f, indent=2, allow_nan=False)
            else:
                sep = "\t" if ext in (".tsv", ".tab") else ","
                df = pd.DataFrame(data, columns=columns, dtype=object)
                df.to_csv(path, sep=sep, index=False)

        return self._save_via(filename, write)
