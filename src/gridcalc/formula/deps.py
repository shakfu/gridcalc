"""Static dependency extraction over the formula AST.

Used by `Grid` to maintain forward/reverse dependency indexes for
topological recalc. Pure-AST analysis: no evaluation.
"""

from __future__ import annotations

from .ast_nodes import (
    BinOp,
    Bool,
    Call,
    CellRef,
    ErrorLit,
    Name,
    Node,
    Number,
    Percent,
    PyCall,
    RangeRef,
    String,
    UnaryOp,
)

# Functions whose read set depends on a value, not on static text. Cells
# containing one of these calls cannot have their dependencies determined
# statically and must be treated as volatile (always recompute).
DYNAMIC_REF_FUNCS: frozenset[str] = frozenset({"INDIRECT", "OFFSET", "INDEX"})

# Functions that return a different value on every call (RAND, RANDBETWEEN).
# Cells calling them must recompute on every recalc -- treat as volatile.
VOLATILE_FUNCS: frozenset[str] = frozenset({"RAND", "RANDBETWEEN", "RANDARRAY"})

# Functions whose CellRef/RangeRef arguments are inspected as references
# rather than read for value. Their args do not contribute to the cell's
# dependency set -- e.g. `=ROWS(A1:B10)` does not read A1..B10, it only
# uses the range's shape. Mirrors `formula.evaluator.RAW_ARG_FUNCS`.
ADDRESS_ONLY_FUNCS: frozenset[str] = frozenset(
    {"ROW", "COLUMN", "ROWS", "COLUMNS", "ISREF", "ISFORMULA"}
)


def extract_refs(
    node: Node,
    named_ranges: dict[str, Node] | None = None,
    formula_sheet: str | None = None,
) -> set[tuple[str | None, int, int]]:
    """Return the set of (sheet, col, row) cells that `node` reads.

    Range references expand to the full rectangular set. Named ranges
    are resolved through `named_ranges`; unknown names are ignored.

    Sheet identity per ref:
      - if the ref carries an explicit sheet (``Sheet2!A1``), use it;
      - otherwise the ref resolves against ``formula_sheet`` (the
        sheet containing the formula). When ``formula_sheet`` is None,
        the returned key is ``(None, c, r)`` -- correct for the
        single-sheet case before phase 1's Sheet class lands and
        sufficient for any caller that doesn't differentiate sheets.

    Does not detect dynamic-ref functions; use ``has_dynamic_refs``.
    """
    out: set[tuple[str | None, int, int]] = set()
    _walk(node, named_ranges or {}, out, formula_sheet)
    return out


def has_dynamic_refs(node: Node) -> bool:
    """True if `node` contains a call whose read set depends on a value.

    Cells matching this need always-recompute treatment in topo recalc.
    """
    if isinstance(node, Call):
        up = node.name.upper()
        if up in DYNAMIC_REF_FUNCS or up in VOLATILE_FUNCS:
            return True
        return any(has_dynamic_refs(a) for a in node.args)
    if isinstance(node, PyCall):
        return True  # py.* gateway can read arbitrary cells
    if isinstance(node, BinOp):
        return has_dynamic_refs(node.left) or has_dynamic_refs(node.right)
    if isinstance(node, (UnaryOp, Percent)):
        return has_dynamic_refs(node.operand)
    return False


def _walk(
    node: Node,
    named: dict[str, Node],
    out: set[tuple[str | None, int, int]],
    formula_sheet: str | None,
) -> None:
    if isinstance(node, CellRef):
        sheet = node.sheet if node.sheet is not None else formula_sheet
        out.add((sheet, node.col, node.row))
        return
    if isinstance(node, RangeRef):
        sheet = node.start.sheet if node.start.sheet is not None else formula_sheet
        c1, c2 = sorted([node.start.col, node.end.col])
        r1, r2 = sorted([node.start.row, node.end.row])
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                out.add((sheet, c, r))
        return
    if isinstance(node, Name):
        target = named.get(node.name.lower())
        if target is not None:
            _walk(target, named, out, formula_sheet)
        return
    if isinstance(node, Call):
        if node.name.upper() in ADDRESS_ONLY_FUNCS:
            # Args are used as references, not read for value.
            return
        for a in node.args:
            _walk(a, named, out, formula_sheet)
        return
    if isinstance(node, PyCall):
        for a in node.args:
            _walk(a, named, out, formula_sheet)
        return
    if isinstance(node, BinOp):
        _walk(node.left, named, out, formula_sheet)
        _walk(node.right, named, out, formula_sheet)
        return
    if isinstance(node, (UnaryOp, Percent)):
        _walk(node.operand, named, out, formula_sheet)
        return
    # Number, String, Bool, ErrorLit have no refs
    if isinstance(node, (Number, String, Bool, ErrorLit)):
        return
