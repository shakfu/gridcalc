"""Static dependency extraction over the formula AST.

Used by `Grid` to maintain forward/reverse dependency indexes for
topological recalc. Pure-AST analysis: no evaluation.
"""

from __future__ import annotations

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
    RangeRef,
    SpillRef,
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


# Functions whose read set depends on a value, not on static text. Cells
# containing one of these calls cannot have their dependencies determined
# statically and must be treated as volatile (always recompute).
DYNAMIC_REF_FUNCS: frozenset[str] = frozenset({"INDIRECT", "OFFSET", "INDEX"})

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
    {"ROW", "COLUMN", "ROWS", "COLUMNS", "ISREF", "AREAS"}
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
) -> set[DepKey]:
    """As `extract_refs`, but a multi-cell range is one `RangeKey`, not its cells.

    The graph shares one node per distinct range, so N formulas over one
    range cost N + size edges rather than N * size.
    """
    out: set[DepKey] = set()
    _walk(node, named_ranges or {}, out, formula_sheet, True)
    return out


def has_dynamic_refs(node: Node) -> bool:
    """True if `node` contains a call whose read set depends on a value.

    Cells matching this need always-recompute treatment in topo recalc.
    """
    if type(node) is BinOp:
        return has_dynamic_refs(node.left) or has_dynamic_refs(node.right)
    if type(node) is Call:
        up = node.name.upper()
        if up in DYNAMIC_REF_FUNCS or up in VOLATILE_FUNCS:
            return True
        return any(has_dynamic_refs(a) for a in node.args)
    if type(node) is Apply:
        return has_dynamic_refs(node.func) or any(has_dynamic_refs(a) for a in node.args)
    if type(node) is PyCall:
        return True  # py.* gateway can read arbitrary cells
    if type(node) is UnaryOp or type(node) is Percent:
        return has_dynamic_refs(node.operand)
    return False


def _walk(
    node: Node,
    named: dict[str, Node],
    out: set[DepKey],
    formula_sheet: str | None,
    collapse: bool,
) -> None:
    if type(node) is CellRef:
        sheet = node.sheet if node.sheet is not None else formula_sheet
        out.add((sheet, node.col, node.row))
    elif type(node) is BinOp:
        _walk(node.left, named, out, formula_sheet, collapse)
        _walk(node.right, named, out, formula_sheet, collapse)
    elif type(node) is Call:
        # An address-only function uses a reference argument for its address,
        # not its value; any other argument (`ROWS(FILTER(...))`) is read.
        address_only = node.name.upper() in ADDRESS_ONLY_FUNCS
        for a in resize_sum_range(node).args:
            if not (address_only and type(a) in (CellRef, RangeRef, Name)):
                _walk(a, named, out, formula_sheet, collapse)
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
        _walk(node.operand, named, out, formula_sheet, collapse)
    elif type(node) is SpillRef:
        # A spill range depends on its anchor: when the anchor's array
        # changes, the whole spill (and its consumers) must recompute.
        anchor = node.anchor
        sheet = anchor.sheet if anchor.sheet is not None else formula_sheet
        out.add((sheet, anchor.col, anchor.row))
    elif type(node) is Name:
        target = named.get(node.name.lower())
        if target is not None:
            _walk(target, named, out, formula_sheet, collapse)
    elif type(node) is Apply:
        _walk(node.func, named, out, formula_sheet, collapse)
        for a in node.args:
            _walk(a, named, out, formula_sheet, collapse)
    elif type(node) is PyCall:
        for a in node.args:
            _walk(a, named, out, formula_sheet, collapse)
    # Constants have no refs.
