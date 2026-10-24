"""Static dependency extraction over the formula AST.

Used by `Grid` to maintain forward/reverse dependency indexes for
topological recalc. Pure-AST analysis: no evaluation.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import NamedTuple, cast

from .ast_nodes import (
    Apply,
    BinOp,
    Call,
    CellRef,
    Name,
    Node,
    Percent,
    PyCall,
    RangeOp,
    RangeRef,
    Ref3D,
    SpillRef,
    StructRef,
    UnaryOp,
)

CellKey = tuple[str | None, int, int]


class RangeKey(NamedTuple):
    """A rectangular range as one dependency-graph node, corners normalised."""

    sheet: str | None
    c1: int
    r1: int
    c2: int
    r2: int

    def cells(self) -> set[CellKey]:
        return {
            (self.sheet, c, r)
            for r in range(self.r1, self.r2 + 1)
            for c in range(self.c1, self.c2 + 1)
        }


DepKey = CellKey | RangeKey


class RangeIndex:
    """The live `RangeKey` nodes, found by a cell they contain.

    A range does not list its cells in the graph: `A:A` would be 1M entries.
    Ranges up to `_NARROW` columns wide are bucketed by column; wider ones
    are scanned per sheet.
    """

    _NARROW = 64

    def __init__(self) -> None:
        self._all: set[RangeKey] = set()
        self._cols: dict[tuple[str | None, int], set[RangeKey]] = {}
        self._wide: dict[str | None, set[RangeKey]] = {}

    def __contains__(self, rk: object) -> bool:
        return rk in self._all

    def __iter__(self) -> Iterator[RangeKey]:
        return iter(self._all)

    def __len__(self) -> int:
        return len(self._all)

    def _buckets(self, rk: RangeKey) -> list[set[RangeKey]]:
        if rk.c2 - rk.c1 < self._NARROW:
            return [self._cols.setdefault((rk.sheet, c), set()) for c in range(rk.c1, rk.c2 + 1)]
        return [self._wide.setdefault(rk.sheet, set())]

    def add(self, rk: RangeKey) -> None:
        if rk not in self._all:
            self._all.add(rk)
            for b in self._buckets(rk):
                b.add(rk)

    def discard(self, rk: RangeKey) -> None:
        if rk in self._all:
            self._all.discard(rk)
            for b in self._buckets(rk):
                b.discard(rk)

    def clear(self) -> None:
        self._all.clear()
        self._cols.clear()
        self._wide.clear()

    def containing(self, sheet: str | None, c: int, r: int) -> list[RangeKey]:
        """The live ranges on `sheet` that contain cell (c, r)."""
        out = [rk for rk in self._cols.get((sheet, c), ()) if rk.r1 <= r <= rk.r2]
        for rk in self._wide.get(sheet, ()):
            if rk.c1 <= c <= rk.c2 and rk.r1 <= r <= rk.r2:
                out.append(rk)
        return out


# `(first, last) -> sheet names in workbook order`, or None for a missing end.
SheetSpan = Callable[[str, str], "list[str] | None"]


# Functions whose read set depends on a value, not on static text. Cells
# containing one of these calls cannot have their dependencies determined
# statically and must be treated as volatile (always recompute). `INDEX` is
# not one: it reads inside its first argument, whose cells are static deps.
DYNAMIC_REF_FUNCS: frozenset[str] = frozenset({"INDIRECT", "OFFSET"})

# Functions whose value changes between calls: random numbers and the clock.
# Cells calling them must recompute on every recalc -- treat as volatile.
VOLATILE_FUNCS: frozenset[str] = frozenset({"RAND", "RANDBETWEEN", "RANDARRAY", "NOW", "TODAY"})

# Functions whose CellRef/RangeRef arguments are inspected as references
# rather than read for value. Their args do not contribute to the cell's
# dependency set -- e.g. `=ROWS(A1:B10)` does not read A1..B10, it only
# uses the range's shape.
#
# Deliberately a subset of `formula.evaluator.RAW_ARG_FUNCS`, not a mirror of
# it: taking raw AST nodes is about *evaluation*, while membership here is
# about whether the answer can change when the referenced cell is edited.
# Every name below is purely positional or structural. `ISFORMULA` is not --
# it reports the cell's kind, so it belongs to the dependency graph even
# though it too receives a raw reference. Listing it here left
# `=ISFORMULA(A1)` reading its old answer after A1 became a formula, until
# something forced a full recalc. `FORMULATEXT` was never listed, for the
# same reason.
ADDRESS_ONLY_FUNCS: frozenset[str] = frozenset(
    {"ROW", "COLUMN", "ROWS", "COLUMNS", "ISREF", "AREAS", "SHEET", "SHEETS"}
)


# Excel sums or averages a range that starts at the sum range's top-left cell
# and has the criteria range's dimensions, whatever the sum range's size.
_RESIZED_SUM_RANGE = frozenset({"SUMIF", "AVERAGEIF"})


def _corners(node: Node) -> tuple[CellRef, int, int, int, int] | None:
    if type(node) is CellRef:
        return node, node.col, node.row, node.col, node.row
    if type(node) is RangeRef:
        c1, c2 = sorted([node.start.col, node.end.col])
        r1, r2 = sorted([node.start.row, node.end.row])
        return node.start, c1, r1, c2, r2
    return None


def resize_sum_range(node: Call) -> Call:
    """``node`` with a SUMIF/AVERAGEIF sum range resized to the criteria range's shape.

    Only literal references resize; the evaluator and dependency extraction
    both call this, so the cells read are the cells tracked.
    """
    if len(node.args) != 3 or node.name.upper() not in _RESIZED_SUM_RANGE:
        return node
    crit, total = _corners(node.args[0]), _corners(node.args[2])
    if crit is None or total is None:
        return node
    _, c1, r1, c2, r2 = crit
    ref, sc1, sr1, sc2, sr2 = total
    if (sc2 - sc1, sr2 - sr1) == (c2 - c1, r2 - r1):
        return node
    start = CellRef(sc1, sr1, ref.abs_col, ref.abs_row, ref.sheet)
    end = CellRef(sc1 + c2 - c1, sr1 + r2 - r1, ref.abs_col, ref.abs_row, ref.sheet)
    return Call(node.name, (*node.args[:2], RangeRef(start, end)))


def extract_refs(
    node: Node,
    named_ranges: dict[str, Node] | None = None,
    formula_sheet: str | None = None,
) -> set[tuple[str | None, int, int]]:
    """Return the set of (sheet, col, row) cells that `node` reads.

    Range references expand to the full rectangular set. Named ranges
    are resolved through `named_ranges`, keyed by lowercase name; unknown
    names are ignored.

    Sheet identity per ref:
      - if the ref carries an explicit sheet (``Sheet2!A1``), use it;
      - otherwise the ref resolves against ``formula_sheet`` (the
        sheet containing the formula). When ``formula_sheet`` is None,
        the returned key is ``(None, c, r)`` -- correct for the
        single-sheet case before phase 1's Sheet class lands and
        sufficient for any caller that doesn't differentiate sheets.

    Does not detect dynamic-ref functions; use ``has_dynamic_refs``.
    """
    out: set[DepKey] = set()
    _walk(node, named_ranges or {}, out, formula_sheet, False)
    return cast("set[CellKey]", out)  # without collapse, _walk emits only cells


def extract_deps(
    node: Node,
    named_ranges: dict[str, Node] | None = None,
    formula_sheet: str | None = None,
    sheet_span: SheetSpan | None = None,
) -> set[DepKey]:
    """As `extract_refs`, but a multi-cell range is one `RangeKey`, not its cells.

    The graph shares one node per distinct range, so N formulas over one
    range cost N + size edges rather than N * size.
    """
    out: set[DepKey] = set()
    _walk(node, named_ranges or {}, out, formula_sheet, True, sheet_span)
    return out


def reads_range_as_array(
    node: Node,
    named: dict[str, Node] | None = None,
    scalar_params: Callable[[str], tuple[bool, ...]] | None = None,
) -> bool:
    """Whether ``node`` uses a range other than as a function's whole argument:
    `SUM(A1:A3*2)`, `A1:A3+1`. Excel saves such a formula as a dynamic array,
    since a legacy formula would read each such range by implicit intersection.
    A range passed whole (`SUM(A1:A3)`) is the same either way.
    ``scalar_params(name)`` flags each parameter of a function that takes one
    value, so a range there (`WEEKDAY(A1:A3)`) counts too."""
    named = named or {}
    scalar = scalar_params or (lambda _name: ())

    def rangeish(n: Node) -> bool:
        if type(n) in (RangeRef, Ref3D, SpillRef, RangeOp, StructRef):
            return True
        if type(n) is Name:
            target = named.get(n.name.lower())
            return type(target) in (RangeRef, Ref3D)
        return False

    def walk(n: Node, whole_arg: bool) -> bool:
        if rangeish(n):
            return not whole_arg
        if type(n) is Call:
            flags = scalar(n.name.lower())
            return any(
                walk(a, not (i < len(flags) and flags[i])) for i, a in enumerate(n.args)
            )
        if type(n) is Apply:
            return walk(n.func, False) or any(walk(a, True) for a in n.args)
        if type(n) is BinOp:
            return walk(n.left, False) or walk(n.right, False)
        if type(n) is UnaryOp or type(n) is Percent:
            return walk(n.operand, False)
        return False

    return walk(node, False)


def has_dynamic_refs(
    node: Node, named: dict[str, Node] | None = None, seen: frozenset[str] = frozenset()
) -> bool:
    """True if `node` contains a call whose read set depends on a value.

    Cells matching this need always-recompute treatment in topo recalc.
    ``named`` (keyed lowercase) lets a name, or a call to a named LAMBDA,
    count by its definition.
    """
    named = named or {}

    def dyn(n: Node) -> bool:
        return has_dynamic_refs(n, named, seen)

    def via_name(key: str) -> bool:
        target = named.get(key)
        return (
            target is not None and key not in seen and has_dynamic_refs(target, named, seen | {key})
        )

    if type(node) is BinOp:
        while type(node) is BinOp:  # a long chain nests on the left; loop it
            if dyn(node.right):
                return True
            node = node.left
        return dyn(node)
    if type(node) is Call:
        up = node.name.upper()
        if up in DYNAMIC_REF_FUNCS or up in VOLATILE_FUNCS:
            return True
        return any(dyn(a) for a in node.args) or via_name(node.name.lower())
    if type(node) is Apply:
        return dyn(node.func) or any(dyn(a) for a in node.args)
    if type(node) is RangeOp:
        return True  # its rectangle is known only once both sides are
    if type(node) is PyCall:
        return True  # py.* gateway can read arbitrary cells
    if type(node) is UnaryOp or type(node) is Percent:
        return dyn(node.operand)
    if type(node) is Name:
        return via_name(node.name.lower())
    return False


def _walk(
    node: Node,
    named: dict[str, Node],
    out: set[DepKey],
    formula_sheet: str | None,
    collapse: bool,
    span: SheetSpan | None = None,
    seen: frozenset[str] = frozenset(),
) -> None:
    if type(node) is CellRef:
        sheet = node.sheet if node.sheet is not None else formula_sheet
        out.add((sheet, node.col, node.row))
    elif type(node) is BinOp:
        while type(node) is BinOp:  # a long chain nests on the left; loop it
            _walk(node.right, named, out, formula_sheet, collapse, span, seen)
            node = node.left
        _walk(node, named, out, formula_sheet, collapse, span, seen)
    elif type(node) is Call:
        # An address-only function uses a reference argument for its address,
        # not its value; any other argument (`ROWS(FILTER(...))`) is read.
        address_only = node.name.upper() in ADDRESS_ONLY_FUNCS
        for a in resize_sum_range(node).args:
            if not (address_only and type(a) in (CellRef, RangeRef, Name)):
                _walk(a, named, out, formula_sheet, collapse, span, seen)
        # A call to a named LAMBDA reads what its body reads.
        fn = node.name.lower()
        if fn in named and fn not in seen:
            _walk(named[fn], named, out, formula_sheet, collapse, span, seen | {fn})
    elif type(node) is Ref3D:
        # One range per sheet in the span. Sheet order is not tracked here:
        # adding, moving or removing a sheet rebuilds the whole graph.
        for sheet in (span(node.first, node.last) if span else None) or ():
            start = CellRef(node.start.col, node.start.row, False, False, sheet)
            end = CellRef(node.end.col, node.end.row, False, False, sheet)
            _walk(RangeRef(start, end), named, out, formula_sheet, collapse, span, seen)
    elif type(node) is RangeRef:
        sheet = node.start.sheet if node.start.sheet is not None else formula_sheet
        c1, c2 = sorted([node.start.col, node.end.col])
        r1, r2 = sorted([node.start.row, node.end.row])
        key = RangeKey(sheet, c1, r1, c2, r2)
        if collapse and (c1, r1) != (c2, r2):
            out.add(key)
        else:
            out.update(key.cells())
    elif type(node) is UnaryOp or type(node) is Percent:
        _walk(node.operand, named, out, formula_sheet, collapse, span, seen)
    elif type(node) is SpillRef:
        # A spill range depends on its anchor: when the anchor's array
        # changes, the whole spill (and its consumers) must recompute.
        anchor = node.anchor
        sheet = anchor.sheet if anchor.sheet is not None else formula_sheet
        out.add((sheet, anchor.col, anchor.row))
    elif type(node) is Name:
        nm = node.name.lower()
        target = named.get(nm)
        if target is not None and nm not in seen:  # a name may refer to itself
            _walk(target, named, out, formula_sheet, collapse, span, seen | {nm})
    elif type(node) is RangeOp:
        _walk(node.left, named, out, formula_sheet, collapse, span, seen)
        _walk(node.right, named, out, formula_sheet, collapse, span, seen)
    elif type(node) is Apply:
        _walk(node.func, named, out, formula_sheet, collapse, span, seen)
        for a in node.args:
            _walk(a, named, out, formula_sheet, collapse, span, seen)
    elif type(node) is PyCall:
        for a in node.args:
            _walk(a, named, out, formula_sheet, collapse, span, seen)
    # Constants have no refs.
