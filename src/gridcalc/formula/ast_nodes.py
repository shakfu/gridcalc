from __future__ import annotations

from dataclasses import dataclass

from .errors import ExcelError


@dataclass(frozen=True)
class Number:
    value: float


@dataclass(frozen=True)
class String:
    value: str


@dataclass(frozen=True)
class Bool:
    value: bool


@dataclass(frozen=True)
class ErrorLit:
    error: ExcelError


@dataclass(frozen=True)
class CellRef:
    col: int
    row: int
    abs_col: bool
    abs_row: bool
    sheet: str | None = None


@dataclass(frozen=True)
class RangeRef:
    start: CellRef
    end: CellRef


@dataclass(frozen=True)
class Ref3D:
    """A 3D reference, `Jan:Mar!B2:B5`: the same cells on every sheet from
    ``first`` to ``last`` in workbook order. ``start`` and ``end`` carry no sheet."""

    first: str
    last: str
    start: CellRef
    end: CellRef


@dataclass(frozen=True)
class SpillRef:
    """The spill-range operator ``A1#``: the whole dynamic array that the
    formula in ``anchor`` spilled, as opposed to ``A1`` which reads only
    the top-left scalar."""

    anchor: CellRef


@dataclass(frozen=True)
class Name:
    name: str


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple[Node, ...]


@dataclass(frozen=True)
class PyCall:
    name: str
    args: tuple[Node, ...]


@dataclass(frozen=True)
class Apply:
    """Application of an expression's result to arguments, e.g.
    ``LAMBDA(x, x+1)(5)``. ``func`` evaluates to a first-class lambda
    value; distinct from ``Call``, whose callee is a static name."""

    func: Node
    args: tuple[Node, ...]


@dataclass(frozen=True)
class BinOp:
    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class UnaryOp:
    op: str
    operand: Node


@dataclass(frozen=True)
class Percent:
    operand: Node


@dataclass(frozen=True)
class RangeOp:
    """``left:right`` where a side is not a plain cell, as in
    ``A1:INDEX(A:A, 5)``: the rectangle spanning both references."""

    left: Node
    right: Node


@dataclass(frozen=True)
class StructRef:
    """A structured reference, `Table1[[#This Row],[Amount]]`. ``table`` is
    None for a bare `[@Amount]`, which names the table holding the formula.
    ``areas`` holds lower-case specifiers (`#all`, `#data`, `#headers`,
    `#totals`, `#this row`); none means `#data`. No column means every one."""

    table: str | None
    areas: tuple[str, ...]
    col1: str | None
    col2: str | None


@dataclass(frozen=True)
class Missing:
    """An omitted argument, as in ``IF(1,,2)``. Evaluates to blank."""


@dataclass(frozen=True)
class ArrayLit:
    """An array constant such as ``{1,2;3,4}``: rows of literal values."""

    rows: tuple[tuple[object, ...], ...]


Node = (
    Number
    | Missing
    | ArrayLit
    | String
    | Bool
    | ErrorLit
    | CellRef
    | RangeRef
    | Ref3D
    | SpillRef
    | Name
    | Call
    | PyCall
    | Apply
    | BinOp
    | UnaryOp
    | Percent
    | RangeOp
    | StructRef
)
