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

# Functions whose CellRef/RangeRef arguments are inspected as references
# rather than read for value. Their args do not contribute to the cell's
# dependency set -- e.g. `=ROWS(A1:B10)` does not read A1..B10, it only
# uses the range's shape. Mirrors `formula.evaluator.RAW_ARG_FUNCS`.
ADDRESS_ONLY_FUNCS: frozenset[str] = frozenset({"ROW", "COLUMN", "ROWS", "COLUMNS"})


def extract_refs(
    node: Node,
    named_ranges: dict[str, Node] | None = None,
) -> set[tuple[int, int]]:
    """Return the set of (col, row) cells that `node` reads, statically.

    Range references expand to the full rectangular set. Named ranges are
    resolved through `named_ranges`; unknown names are ignored.

    Does not detect dynamic-ref functions; use `has_dynamic_refs` for that.
    """
    out: set[tuple[int, int]] = set()
    _walk(node, named_ranges or {}, out)
    return out


def has_dynamic_refs(node: Node) -> bool:
    """True if `node` contains a call whose read set depends on a value.

    Cells matching this need always-recompute treatment in topo recalc.
    """
    if isinstance(node, Call):
        if node.name.upper() in DYNAMIC_REF_FUNCS:
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
    out: set[tuple[int, int]],
) -> None:
    if isinstance(node, CellRef):
        out.add((node.col, node.row))
        return
    if isinstance(node, RangeRef):
        c1, c2 = sorted([node.start.col, node.end.col])
        r1, r2 = sorted([node.start.row, node.end.row])
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                out.add((c, r))
        return
    if isinstance(node, Name):
        target = named.get(node.name.lower())
        if target is not None:
            _walk(target, named, out)
        return
    if isinstance(node, Call):
        if node.name.upper() in ADDRESS_ONLY_FUNCS:
            # Args are used as references, not read for value.
            return
        for a in node.args:
            _walk(a, named, out)
        return
    if isinstance(node, PyCall):
        for a in node.args:
            _walk(a, named, out)
        return
    if isinstance(node, BinOp):
        _walk(node.left, named, out)
        _walk(node.right, named, out)
        return
    if isinstance(node, (UnaryOp, Percent)):
        _walk(node.operand, named, out)
        return
    # Number, String, Bool, ErrorLit have no refs
    if isinstance(node, (Number, String, Bool, ErrorLit)):
        return
