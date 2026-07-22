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


Node = (
    Number
    | String
    | Bool
    | ErrorLit
    | CellRef
    | RangeRef
    | SpillRef
    | Name
    | Call
    | PyCall
    | Apply
    | BinOp
    | UnaryOp
    | Percent
)
