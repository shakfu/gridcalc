"""Sheet-level linear optimization.

Builds a linear program from cells in a Grid and solves it via the lp_solve-
backed `_opt` extension. The user-facing model is sheet-resident:

  - One **objective** cell containing a linear formula (e.g. ``=3*A1+5*A2``).
  - A list of **decision variable** cells. They must hold numeric values
    (or be empty); formula cells are refused so the optimizer doesn't
    silently overwrite live computations.
  - A list of **constraint** cells, each containing a comparison formula
    (e.g. ``=A1+A2<=10``). Their current evaluated values (True/False)
    indicate live feasibility; the optimizer reads the underlying AST.

Linearity is enforced by walking gridcalc's formula AST. Cell references
that resolve to decision variables become coefficients; everything else is
folded into the constant term using the cell's currently evaluated value.
This means non-decision cells act as parameters: edit them and re-run.

Supported AST shapes:
  Number, CellRef, BinOp(+,-,*,/), UnaryOp(+,-), Percent,
  Call("SUM", RangeRef|expr), parenthesized expressions.

Anything else (Bool, String, ErrorLit, other Call/PyCall, RangeRef outside
SUM, Name) raises NotLinear with a message naming the offending node.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from . import _opt as _ext  # type: ignore[attr-defined]  # nanobind extension
from .engine import EMPTY, FORMULA, NUM, Cell, Grid
from .formula.ast_nodes import (
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
from .formula.parser import ParseError
from .formula.parser import parse as _formula_parse

CellKey = tuple[int, int]


def _cell_ast(cell: Cell) -> Node | None:
    """Return the cell's parsed formula AST, parsing on-demand if needed.

    LEGACY mode (the default) leaves ``cell.ast`` empty because the engine
    evaluates formulas via a Python ``eval`` of transformed text rather than
    through the AST. We re-parse here so optimization works regardless of
    grid mode.

    Note on sandboxing: ``sandbox.validate_formula`` cannot run on raw
    gridcalc-formula text -- gridcalc syntax (``A1:A3`` ranges, ``SUM(...)``
    calls, sheet-qualified ``Sheet2!A1``) is not valid Python and would be
    rejected by the Python AST parser. The optimizer is safe regardless
    because the linearity walker accepts only a closed whitelist of AST
    node types (Number, CellRef, BinOp(+,-,*,/), UnaryOp, Percent, SUM
    call); anything that could be used for sandbox escape (Name, PyCall,
    other Call, attribute access at parse time) raises NotLinear.
    """
    cached: Node | None = cell.ast
    if cached is not None:
        return cached
    text = cell.text
    if not text:
        return None
    source = text[1:] if text.startswith("=") else text
    try:
        parsed: Node = _formula_parse(source)
    except ParseError:
        return None
    return parsed


# Map gridcalc comparison-op strings to _opt sense codes. Strict inequalities
# are folded onto their non-strict counterparts because LP has no strict-form
# equivalent; "<>" has no LP analogue and is rejected upstream.
_SENSE = {
    "<=": _ext.LE,
    "<": _ext.LE,
    ">=": _ext.GE,
    ">": _ext.GE,
    "=": _ext.EQ,
}

_STATUS_NAMES = {
    _ext.OPTIMAL: "OPTIMAL",
    _ext.SUBOPTIMAL: "SUBOPTIMAL",
    _ext.INFEASIBLE: "INFEASIBLE",
    _ext.UNBOUNDED: "UNBOUNDED",
    _ext.DEGENERATE: "DEGENERATE",
    _ext.NUMFAILURE: "NUMFAILURE",
    _ext.USERABORT: "USERABORT",
    _ext.TIMEOUT: "TIMEOUT",
}


class OptError(Exception):
    """Caller-facing error: malformed model, bad cell selection, etc."""


class NotLinear(OptError):
    """A formula cannot be expressed as a linear combination of decision vars."""


@dataclass
class OptModel:
    """A persisted LP model definition stored in the workbook.

    The fields hold the *string specs* the user typed for each component
    (`"A4:A5"`, `"D4:D6"`, `"A1=-inf:10"`), not pre-parsed cell coordinates.
    This preserves the user's range/list intent verbatim through save/load
    round-trips, mirrors how named ranges are stored, and defers cell-ref
    resolution (and any errors it would produce) to ``:opt run`` time.
    """

    sense: str  # "max" or "min"
    objective: str  # single cell ref, e.g. "B4"
    vars: str  # cell-list spec, e.g. "A4:A5" or "A1,A3,B5"
    constraints: str  # cell-list spec
    bounds: str = ""  # optional bounds spec, e.g. "A1=-inf:10,A2=0:100"
    integers: str = ""  # optional cell-list spec; flagged as integer-valued
    binaries: str = ""  # optional cell-list spec; flagged as binary (0/1)

    def to_json(self) -> dict[str, str]:
        out: dict[str, str] = {
            "sense": self.sense,
            "objective": self.objective,
            "vars": self.vars,
            "constraints": self.constraints,
        }
        # Only emit optional fields when set, so saved JSON stays minimal
        # for the LP-only case.
        if self.bounds:
            out["bounds"] = self.bounds
        if self.integers:
            out["integers"] = self.integers
        if self.binaries:
            out["binaries"] = self.binaries
        return out

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> OptModel:
        sense = d.get("sense", "")
        if sense not in ("max", "min"):
            raise OptError(f"invalid sense {sense!r} in saved model")
        for required in ("objective", "vars", "constraints"):
            if not isinstance(d.get(required), str) or not d[required]:
                raise OptError(f"saved model missing required field {required!r}")
        return cls(
            sense=sense,
            objective=d["objective"],
            vars=d["vars"],
            constraints=d["constraints"],
            bounds=d.get("bounds", ""),
            integers=d.get("integers", ""),
            binaries=d.get("binaries", ""),
        )


@dataclass
class LinearForm:
    """A sum of (coefficient * decision_var) terms plus a constant.

    `coeffs` is sparse: missing keys are zero. Two LinearForms can be added,
    subtracted, scaled, and negated to compose larger expressions.
    """

    coeffs: dict[CellKey, float] = field(default_factory=dict)
    constant: float = 0.0

    def add(self, other: LinearForm) -> LinearForm:
        out = LinearForm(dict(self.coeffs), self.constant + other.constant)
        for k, v in other.coeffs.items():
            out.coeffs[k] = out.coeffs.get(k, 0.0) + v
        return out

    def sub(self, other: LinearForm) -> LinearForm:
        out = LinearForm(dict(self.coeffs), self.constant - other.constant)
        for k, v in other.coeffs.items():
            out.coeffs[k] = out.coeffs.get(k, 0.0) - v
        return out

    def neg(self) -> LinearForm:
        return LinearForm({k: -v for k, v in self.coeffs.items()}, -self.constant)

    def scale(self, k: float) -> LinearForm:
        if k == 0.0:
            return LinearForm()
        return LinearForm({c: v * k for c, v in self.coeffs.items()}, self.constant * k)

    @property
    def is_constant(self) -> bool:
        return not any(self.coeffs.values())


class NotQuadratic(NotLinear):
    """An objective is nonlinear in a way this optimizer cannot express.

    Deliberately a subclass of :class:`NotLinear` rather than a sibling. Both
    walkers are the safety boundary for the optimizer -- each accepts a closed
    whitelist of AST nodes and rejects everything else, so nothing that could
    be a sandbox concern (``Name``, ``PyCall``, attribute-style ``Call``)
    reaches an evaluation path. Callers written against that guarantee catch
    ``NotLinear``; widening the objective walker to degree 2 must not quietly
    slip past those handlers.
    """


@dataclass
class QuadForm:
    """A degree-<=2 polynomial over decision variables.

    ``quad`` is keyed by an ordered pair of cells: ``(k, k)`` is a squared
    term, ``(j, k)`` with ``j != k`` is a cross term. Cross terms are tracked
    rather than rejected on sight so the error message can name the pair that
    made the objective non-separable.
    """

    quad: dict[tuple[CellKey, CellKey], float] = field(default_factory=dict)
    linear: dict[CellKey, float] = field(default_factory=dict)
    constant: float = 0.0

    @property
    def is_constant(self) -> bool:
        return not any(self.quad.values()) and not any(self.linear.values())

    @property
    def is_linear(self) -> bool:
        return not any(self.quad.values())

    def add(self, other: QuadForm) -> QuadForm:
        out = QuadForm(dict(self.quad), dict(self.linear), self.constant + other.constant)
        for pair, qv in other.quad.items():
            out.quad[pair] = out.quad.get(pair, 0.0) + qv
        for cell, lv in other.linear.items():
            out.linear[cell] = out.linear.get(cell, 0.0) + lv
        return out

    def neg(self) -> QuadForm:
        return QuadForm(
            {k: -v for k, v in self.quad.items()},
            {k: -v for k, v in self.linear.items()},
            -self.constant,
        )

    def sub(self, other: QuadForm) -> QuadForm:
        return self.add(other.neg())

    def scale(self, k: float) -> QuadForm:
        if k == 0.0:
            return QuadForm()
        return QuadForm(
            {c: v * k for c, v in self.quad.items()},
            {c: v * k for c, v in self.linear.items()},
            self.constant * k,
        )

    def mul(self, other: QuadForm) -> QuadForm:
        """Multiply, refusing anything that would exceed degree 2."""
        if not self.is_linear and not other.is_constant:
            raise NotQuadratic("objective is degree 3 or higher")
        if not other.is_linear and not self.is_constant:
            raise NotQuadratic("objective is degree 3 or higher")

        out = QuadForm({}, {}, self.constant * other.constant)
        for pair, qv in self.quad.items():
            out.quad[pair] = out.quad.get(pair, 0.0) + qv * other.constant
        for pair, qv in other.quad.items():
            out.quad[pair] = out.quad.get(pair, 0.0) + qv * self.constant
        for cell, lv in self.linear.items():
            out.linear[cell] = out.linear.get(cell, 0.0) + lv * other.constant
        for cell, lv in other.linear.items():
            out.linear[cell] = out.linear.get(cell, 0.0) + lv * self.constant
        # The outer product of the two linear parts is where squares and
        # cross terms come from.
        for a, va in self.linear.items():
            for b, vb in other.linear.items():
                key = (a, b) if a <= b else (b, a)
                out.quad[key] = out.quad.get(key, 0.0) + va * vb
        return out

    def squares(self) -> dict[CellKey, float]:
        """Diagonal terms, after checking there are no cross terms."""
        for (a, b), v in self.quad.items():
            if a != b and v != 0.0:
                raise NotQuadratic(
                    f"objective couples {_cellname(*a)} and {_cellname(*b)}; "
                    "only separable quadratics (no cross terms) are supported"
                )
        return {a: v for (a, b), v in self.quad.items() if a == b and v != 0.0}


def extract_quadratic(node: Node, decision_vars: set[CellKey], grid: Grid) -> QuadForm:
    """Reduce ``node`` to a degree-<=2 form over ``decision_vars``.

    The quadratic counterpart of :func:`extract_linear`, and deliberately a
    separate walker: constraints must stay linear, so widening the shared one
    would have quietly admitted quadratic constraints the solver cannot take.
    """
    if isinstance(node, Number):
        return QuadForm({}, {}, float(node.value))

    if isinstance(node, CellRef):
        _check_sheet(node.sheet, _active_sheet_name(grid))
        key: CellKey = (node.col, node.row)
        if key in decision_vars:
            return QuadForm({}, {key: 1.0}, 0.0)
        return QuadForm({}, {}, _cell_value(grid, node.col, node.row))

    if isinstance(node, UnaryOp):
        inner = extract_quadratic(node.operand, decision_vars, grid)
        if node.op == "+":
            return inner
        if node.op == "-":
            return inner.neg()
        raise NotQuadratic(f"unsupported unary operator '{node.op}'")

    if isinstance(node, Percent):
        return extract_quadratic(node.operand, decision_vars, grid).scale(0.01)

    if isinstance(node, BinOp):
        if node.op == "+":
            return extract_quadratic(node.left, decision_vars, grid).add(
                extract_quadratic(node.right, decision_vars, grid)
            )
        if node.op == "-":
            return extract_quadratic(node.left, decision_vars, grid).sub(
                extract_quadratic(node.right, decision_vars, grid)
            )
        if node.op == "*":
            return extract_quadratic(node.left, decision_vars, grid).mul(
                extract_quadratic(node.right, decision_vars, grid)
            )
        if node.op == "^":
            base = extract_quadratic(node.left, decision_vars, grid)
            power = extract_quadratic(node.right, decision_vars, grid)
            if not power.is_constant:
                raise NotQuadratic("exponent must be a constant")
            p = power.constant
            if p == 0.0:
                return QuadForm({}, {}, 1.0)
            if p == 1.0:
                return base
            if p == 2.0:
                return base.mul(base)
            raise NotQuadratic(f"exponent {p:g} is not supported (only 0, 1, 2)")
        if node.op == "/":
            lhs = extract_quadratic(node.left, decision_vars, grid)
            rhs = extract_quadratic(node.right, decision_vars, grid)
            if not rhs.is_constant:
                raise NotQuadratic("division by a decision-variable expression")
            if rhs.constant == 0.0:
                raise NotQuadratic("division by zero")
            return lhs.scale(1.0 / rhs.constant)
        raise NotQuadratic(f"unsupported operator '{node.op}'")

    if isinstance(node, Call):
        if node.name.upper() == "SUM":
            total = QuadForm()
            for arg in node.args:
                lin = _sum_arg(arg, decision_vars, grid)
                total = total.add(QuadForm({}, dict(lin.coeffs), lin.constant))
            return total
        raise NotQuadratic(f"function '{node.name}' is not allowed")

    raise NotQuadratic(f"{type(node).__name__} is not allowed in an objective")


@dataclass
class VarSensitivity:
    """Sensitivity of the optimum to one decision variable.

    ``reduced_cost`` is the amount the objective would change per unit if the
    variable were forced away from its bound; it is zero for any variable
    already in the basis. ``obj_from`` / ``obj_till`` bracket the range over
    which this variable's objective coefficient can move without changing the
    optimal basis (the values themselves would change, the choice of which
    variables are non-zero would not).
    """

    cell: CellKey
    value: float
    reduced_cost: float
    obj_coef: float
    obj_from: float
    obj_till: float


@dataclass
class ConstraintSensitivity:
    """Sensitivity of the optimum to one constraint.

    ``shadow_price`` is the marginal change in the objective per unit
    relaxation of the right-hand side -- the value of one more unit of this
    resource, and the number a user actually wants when deciding what to buy
    more of. It is valid only within ``rhs_from``..``rhs_till``; past those
    limits the basis changes and the price no longer applies.
    """

    cell: CellKey
    shadow_price: float
    rhs: float
    activity: float
    slack: float
    binding: bool
    rhs_from: float
    rhs_till: float


@dataclass
class Sensitivity:
    variables: list[VarSensitivity]
    constraints: list[ConstraintSensitivity]


@dataclass
class SweepPoint:
    """One re-solve of the model at a substituted right-hand side."""

    rhs: float
    status_name: str
    objective: float
    # Shadow price of the swept constraint at this point, or None when the
    # solve failed or the model is a MIP.
    shadow_price: float | None
    # Objective change from the previous point, or None for the first.
    delta: float | None
    # True when this point's shadow price differs from the previous point's:
    # the marginal value of the resource just changed, which is the whole
    # reason to sweep rather than read a single shadow price.
    breakpoint: bool


@dataclass
class SolveResult:
    status: int
    status_name: str
    objective: float
    values: dict[CellKey, float]  # decision cell -> optimal value (empty if not OPTIMAL)
    applied: bool  # True if cells were written
    # Populated only when solve(sensitivity=True) succeeded on a pure LP.
    # None for MIPs, where a dual has no valid interpretation.
    sensitivity: Sensitivity | None = None
    # Populated only when solve(diagnose=True) and the model was INFEASIBLE:
    # a minimal set of mutually contradictory constraint cells.
    conflict: list[CellKey] | None = None
    # Populated only when solve(diagnose=True) and the model was UNBOUNDED:
    # the decision cells that can grow without limit. Empty if the probe
    # could not identify them (see `_unbounded_variables`).
    unbounded: list[CellKey] | None = None
    # True when the objective had squared terms and was solved through the
    # piecewise-linear relaxation, in which case the result is approximate.
    quadratic: bool = False
    # Bound on how far `objective` may sit from the true optimum. Zero for a
    # plain LP, where the answer is exact.
    quadratic_gap: float = 0.0


# --- Linearity walker -------------------------------------------------------


def _cell_value(grid: Grid, c: int, r: int) -> float:
    """Current numeric value of a cell, treating EMPTY/non-numeric as 0."""
    cell = grid.cells[c][r]
    if cell.type == NUM:
        return float(cell.val)
    if cell.type == FORMULA:
        # Use the most recently evaluated numeric value. Non-numeric formula
        # results (errors, strings) collapse to 0 here -- they make the
        # linearization meaningless anyway, so the LP would be wrong even
        # if we propagated NaN.
        return float(cell.val) if isinstance(cell.val, (int, float)) else 0.0
    return 0.0


def _active_sheet_name(grid: Grid) -> str:
    return grid.sheets[grid.active].name


def _check_sheet(node_sheet: str | None, active: str) -> None:
    """Reject AST nodes that point at a non-active sheet.

    Cross-sheet LP models aren't supported yet: the linearity walker uses
    the active sheet's cell store to look up constant values, so silently
    treating a foreign-sheet ref as if it were on the active sheet would
    return wrong coefficients.
    """
    if node_sheet is not None and node_sheet != active:
        raise OptError(
            f"cross-sheet reference to '{node_sheet}!...' is not supported "
            f"(active sheet is '{active}')"
        )


def extract_linear(node: Node, decision_vars: set[CellKey], grid: Grid) -> LinearForm:
    """Reduce ``node`` to a LinearForm over ``decision_vars``.

    Cells in ``decision_vars`` contribute coefficients; all other cells are
    looked up in ``grid`` and folded into the constant term.
    """
    if isinstance(node, Number):
        return LinearForm({}, float(node.value))

    if isinstance(node, CellRef):
        _check_sheet(node.sheet, _active_sheet_name(grid))
        key: CellKey = (node.col, node.row)
        if key in decision_vars:
            return LinearForm({key: 1.0}, 0.0)
        return LinearForm({}, _cell_value(grid, node.col, node.row))

    if isinstance(node, UnaryOp):
        inner = extract_linear(node.operand, decision_vars, grid)
        if node.op == "+":
            return inner
        if node.op == "-":
            return inner.neg()
        raise NotLinear(f"unsupported unary operator '{node.op}'")

    if isinstance(node, Percent):
        return extract_linear(node.operand, decision_vars, grid).scale(0.01)

    if isinstance(node, BinOp):
        if node.op == "+":
            return extract_linear(node.left, decision_vars, grid).add(
                extract_linear(node.right, decision_vars, grid)
            )
        if node.op == "-":
            return extract_linear(node.left, decision_vars, grid).sub(
                extract_linear(node.right, decision_vars, grid)
            )
        if node.op == "*":
            lhs = extract_linear(node.left, decision_vars, grid)
            rhs = extract_linear(node.right, decision_vars, grid)
            if lhs.is_constant:
                return rhs.scale(lhs.constant)
            if rhs.is_constant:
                return lhs.scale(rhs.constant)
            raise NotLinear("product of two decision-variable expressions is nonlinear")
        if node.op == "/":
            lhs = extract_linear(node.left, decision_vars, grid)
            rhs = extract_linear(node.right, decision_vars, grid)
            if not rhs.is_constant:
                raise NotLinear("division by a decision-variable expression is nonlinear")
            if rhs.constant == 0.0:
                raise NotLinear("division by zero in linear expression")
            return lhs.scale(1.0 / rhs.constant)
        # ^, &, comparisons, etc. -- not allowed inside an expression body
        raise NotLinear(f"unsupported operator '{node.op}' in linear expression")

    if isinstance(node, Call):
        if node.name.upper() == "SUM":
            total = LinearForm()
            for arg in node.args:
                total = total.add(_sum_arg(arg, decision_vars, grid))
            return total
        raise NotLinear(f"function '{node.name}' is not allowed in a linear expression")

    if isinstance(node, (Bool, String, ErrorLit, RangeRef, Name, PyCall)):
        raise NotLinear(f"{type(node).__name__} is not allowed in a linear expression")

    raise NotLinear(f"unhandled AST node: {type(node).__name__}")


def _sum_arg(arg: Node, decision_vars: set[CellKey], grid: Grid) -> LinearForm:
    """Handle one argument inside SUM(...). Ranges expand cell-by-cell."""
    if isinstance(arg, RangeRef):
        active = _active_sheet_name(grid)
        _check_sheet(arg.start.sheet, active)
        _check_sheet(arg.end.sheet, active)
        out = LinearForm()
        c0, c1 = sorted((arg.start.col, arg.end.col))
        r0, r1 = sorted((arg.start.row, arg.end.row))
        for c in range(c0, c1 + 1):
            for r in range(r0, r1 + 1):
                key = (c, r)
                if key in decision_vars:
                    out.coeffs[key] = out.coeffs.get(key, 0.0) + 1.0
                else:
                    out.constant += _cell_value(grid, c, r)
        return out
    return extract_linear(arg, decision_vars, grid)


# --- Constraint extraction --------------------------------------------------


def extract_constraint(
    node: Node,
    decision_vars: set[CellKey],
    grid: Grid,
) -> tuple[dict[CellKey, float], int, float]:
    """Reduce a comparison-rooted formula to (coeffs, sense, rhs) form.

    Both sides are walked as linear forms; variables move to the left and
    constants to the right, so the LP sees a single row ``a^T x OP b``.
    """
    if not isinstance(node, BinOp) or node.op not in _SENSE:
        if isinstance(node, BinOp) and node.op == "<>":
            raise OptError("'<>' is not a valid LP constraint operator")
        raise OptError("constraint formula must be a comparison (<=, >=, =, <, >)")
    lhs = extract_linear(node.left, decision_vars, grid)
    rhs = extract_linear(node.right, decision_vars, grid)
    diff = lhs.sub(rhs)  # coeffs * x + (lhs.const - rhs.const) OP 0
    rhs_value = -diff.constant  # move constant to RHS
    return diff.coeffs, _SENSE[node.op], rhs_value


# --- Solver entry point -----------------------------------------------------


def solve(
    grid: Grid,
    objective_cell: CellKey,
    decision_vars: list[CellKey],
    constraint_cells: list[CellKey],
    *,
    maximize: bool = True,
    bounds: dict[CellKey, tuple[float, float]] | None = None,
    integer_vars: set[CellKey] | None = None,
    binary_vars: set[CellKey] | None = None,
    apply: bool = True,
    sensitivity: bool = False,
    diagnose: bool = False,
    rhs_override: dict[CellKey, float] | None = None,
    quadratic_segments: int = 64,
) -> SolveResult:
    """Build an LP (or MIP) from the named cells, solve, and (by default) write back.

    The objective cell must contain a formula. Decision-variable cells must
    NOT contain formulas (they get overwritten on success). Each constraint
    cell must contain a formula whose root is a comparison operator.

    ``integer_vars`` and ``binary_vars`` are subsets of ``decision_vars``;
    cells in either set are flagged as integer or binary respectively, which
    routes the solve through lp_solve's branch-and-bound. Binary cells have
    their bounds clamped to [0,1] by lp_solve regardless of ``bounds``; a
    cell appearing in both sets raises ``OptError``.

    ``sensitivity=True`` additionally returns shadow prices, reduced costs,
    and ranging information in ``SolveResult.sensitivity``. It is silently
    ignored for MIPs (the field stays ``None``): branch-and-bound duals
    describe one LP relaxation rather than the integer problem, so reporting
    them would be actively misleading.

    ``rhs_override`` replaces the right-hand side of the named constraint
    cells for this solve only, without touching the sheet. The constraint's
    coefficients still come from its formula; only the constant moves. This
    is what makes what-if analysis possible without rewriting cells and
    recalculating -- see ``sweep``.

    ``diagnose=True`` explains a failed solve. On INFEASIBLE it populates
    ``SolveResult.conflict`` with a minimal set of contradictory constraint
    cells (one extra solve per constraint); on UNBOUNDED it populates
    ``SolveResult.unbounded`` with the decision cells that can grow without
    limit (two extra solves). Neither runs on a successful solve.
    """
    if not decision_vars:
        raise OptError("at least one decision variable is required")
    if len(set(decision_vars)) != len(decision_vars):
        raise OptError("decision variables must be unique")

    var_set = set(decision_vars)
    var_index = {v: i for i, v in enumerate(decision_vars)}
    n = len(decision_vars)

    # Reject formula decision cells up-front so the operator never silently
    # destroys live computation. Override for advanced use cases isn't
    # supported yet (would need a flag and an undo guarantee).
    for c, r in decision_vars:
        cell = grid.cells[c][r]
        if cell.type == FORMULA:
            raise OptError(
                f"decision cell {_cellname(c, r)} contains a formula; "
                "decision variables must hold values (or be empty)"
            )
        if cell.type not in (EMPTY, NUM):
            raise OptError(f"decision cell {_cellname(c, r)} must be numeric or empty")

    # Objective.
    obj_c, obj_r = objective_cell
    obj_cell = grid.cells[obj_c][obj_r]
    obj_ast = _cell_ast(obj_cell) if obj_cell.type == FORMULA else None
    if obj_cell.type != FORMULA or obj_ast is None:
        raise OptError(f"objective cell {_cellname(obj_c, obj_r)} must contain a formula")
    obj_quad = extract_quadratic(obj_ast, var_set, grid)
    obj_squares = obj_quad.squares()  # raises NotQuadratic on cross terms
    obj_form = LinearForm(dict(obj_quad.linear), obj_quad.constant)
    c_vec = [obj_form.coeffs.get(v, 0.0) for v in decision_vars]
    # The objective constant is dropped here: lp_solve's `solve` returns
    # only the linear part. We add it back to the reported objective below.

    # Constraints.
    A: list[list[float]] = []
    sense: list[int] = []
    rhs: list[float] = []
    for c, r in constraint_cells:
        cell = grid.cells[c][r]
        cell_ast = _cell_ast(cell) if cell.type == FORMULA else None
        if cell.type != FORMULA or cell_ast is None:
            raise OptError(f"constraint cell {_cellname(c, r)} must contain a comparison formula")
        coeffs, op_code, rhs_val = extract_constraint(cell_ast, var_set, grid)
        if rhs_override and (c, r) in rhs_override:
            rhs_val = float(rhs_override[(c, r)])
        row = [coeffs.get(v, 0.0) for v in decision_vars]
        A.append(row)
        sense.append(op_code)
        rhs.append(rhs_val)

    if rhs_override:
        unknown = sorted(set(rhs_override) - set(constraint_cells))
        if unknown:
            raise OptError(
                f"rhs_override names {_cellname(*unknown[0])} which is not a constraint cell"
            )

    # Bounds: default to [0, +inf) for each decision var, mirroring lp_solve
    # and matching the "amounts" intuition (no negative production levels).
    inf = float("inf")
    lb = [0.0] * n
    ub = [inf] * n
    if bounds:
        for cell_key, (lo, hi) in bounds.items():
            i = var_index.get(cell_key)
            if i is None:
                raise OptError(
                    f"bounds reference {_cellname(*cell_key)} which is not a decision variable"
                )
            # Validate here rather than letting the C++ bridge reject it.
            # The bridge raises ValueError("lb[j] > ub[j]") -- a column index
            # the user never sees, in an exception type callers of this
            # module do not expect, from a layer they cannot catch
            # meaningfully. Both conditions are reachable from a typed
            # `bounds A1=20:10` or `A1=nan:5`.
            lo_f, hi_f = float(lo), float(hi)
            name = _cellname(*cell_key)
            if math.isnan(lo_f) or math.isnan(hi_f):
                raise OptError(f"bounds for {name} are not numeric")
            if lo_f > hi_f:
                raise OptError(
                    f"bounds for {name} are reversed: lower {lo_f:g} exceeds upper {hi_f:g}"
                )
            lb[i] = lo_f
            ub[i] = hi_f

    # Integer / binary flags. Both must be subsets of decision_vars, and
    # they must be disjoint -- the C++ bridge re-checks for overlap but we
    # surface a clearer message here with the offending cell names.
    int_set = integer_vars or set()
    bin_set = binary_vars or set()
    for cell_key in int_set | bin_set:
        if cell_key not in var_index:
            raise OptError(
                f"integer/binary flag references {_cellname(*cell_key)} "
                "which is not a decision variable"
            )
    overlap = int_set & bin_set
    if overlap:
        c0, r0 = next(iter(overlap))
        raise OptError(f"cell {_cellname(c0, r0)} cannot be both integer and binary")
    int_indices = sorted(var_index[k] for k in int_set)
    bin_indices = sorted(var_index[k] for k in bin_set)

    # A separable quadratic objective is handled by extending the LP with one
    # auxiliary column per squared term plus a fan of tangent constraints; see
    # `_add_quadratic_relaxation`. Everything downstream still sees an LP.
    quad_gap = 0.0
    if obj_squares:
        quad_gap = _add_quadratic_relaxation(
            obj_squares,
            decision_vars,
            var_index,
            c_vec,
            A,
            sense,
            rhs,
            lb,
            ub,
            maximize=maximize,
            segments=quadratic_segments,
        )
        # The relaxation's duals belong to the approximating LP, not to the
        # quadratic problem, and its extra rows are not user constraints.
        # Withhold both analyses rather than report numbers about the wrong
        # model -- the same call made for MIPs.
        sensitivity = False
        diagnose = False

    # Solve.
    sol = _ext.solve_lp(
        c_vec,
        A,
        sense,
        rhs,
        lb,
        ub,
        maximize=maximize,
        integer_vars=int_indices,
        binary_vars=bin_indices,
        sensitivity=sensitivity,
    )

    # Add back the constant term that we dropped from the objective vector
    # so the user sees the formula's actual value at the optimum.
    solved_ok = sol.status in (_ext.OPTIMAL, _ext.SUBOPTIMAL)
    objective_total = sol.objective + obj_form.constant if solved_ok else 0.0

    values: dict[CellKey, float] = {}
    if solved_ok:
        # `sol.x` is longer than `decision_vars` when a quadratic relaxation
        # appended auxiliary columns; the trailing entries are not cells.
        for v, x in zip(decision_vars, sol.x[: len(decision_vars)], strict=True):
            values[v] = float(x)
        if obj_squares:
            # Report the objective's true value at the solved point rather
            # than the relaxation's. The point is feasible for the real
            # problem, so its true objective is achievable; the relaxed value
            # is an artefact of the approximation and reads slightly better
            # than reality.
            objective_total = evaluate_quadratic(obj_squares, obj_form, values)

    applied = False
    if apply and values:
        for (c, r), x in values.items():
            # `_ensure_cell`, not `grid.cells[c][r]`: decision cells are
            # allowed to be empty, and empty coordinates hand back a shared
            # placeholder rather than a stored Cell. Writing through that
            # placeholder used to corrupt every empty cell in the process.
            cell = grid._ensure_cell(c, r)
            cell.type = NUM
            cell.val = x
            cell.text = ""
            cell.ast = None
            cell.ast_text = ""
            cell.err = None
            cell.err_msg = None
        grid.recalc()
        applied = True

    sens: Sensitivity | None = None
    if sensitivity and solved_ok and sol.sensitivity_valid:
        sens = _build_sensitivity(decision_vars, constraint_cells, c_vec, A, rhs, sol, values)

    runaway: list[CellKey] | None = None
    if diagnose and sol.status == _ext.UNBOUNDED:
        runaway = [
            decision_vars[j]
            for j in _unbounded_variables(
                c_vec, A, sense, rhs, lb, ub, maximize, int_indices, bin_indices
            )
        ]

    conflict: list[CellKey] | None = None
    if diagnose and sol.status == _ext.INFEASIBLE:
        conflict = [
            constraint_cells[i]
            for i in _irreducible_conflict(
                c_vec, A, sense, rhs, lb, ub, maximize, int_indices, bin_indices
            )
        ]

    return SolveResult(
        status=sol.status,
        status_name=_STATUS_NAMES.get(sol.status, f"UNKNOWN({sol.status})"),
        objective=objective_total,
        values=values,
        applied=applied,
        sensitivity=sens,
        conflict=conflict,
        unbounded=runaway,
        quadratic=bool(obj_squares),
        quadratic_gap=quad_gap if obj_squares else 0.0,
    )


def _unbounded_variables(
    c_vec: list[float],
    A: list[list[float]],
    sense: list[int],
    rhs: list[float],
    lb: list[float],
    ub: list[float],
    maximize: bool,
    int_indices: list[int],
    bin_indices: list[int],
) -> list[int]:
    """Column indices of decision variables that can grow without limit.

    lp_solve exposes no extreme ray -- ``is_unbounded(lp, col)`` is the query
    counterpart to ``set_unbounded`` and reports whether a column was
    *declared* free, not which column runs away. So this is derived instead
    of asked for.

    Method: for each variable whose objective coefficient is non-zero,
    re-solve the *same feasible region* with a throwaway objective of just
    that variable, pushed in whichever direction improves the real
    objective. If that sub-problem is itself UNBOUNDED, the variable can run
    to infinity inside the constraints, which is exactly the claim the report
    makes. Costs at most one solve per contributing variable and runs only
    on the unbounded path.

    Variables with a zero objective coefficient are skipped: they cannot be
    the cause, since moving them does not change the objective at all.

    An earlier version bounded the infinite directions with a large finite
    box and looked for variables pinned against it. That is the textbook
    big-M approach and it is *wrong here* -- the box has to be derived from
    the model's own magnitudes, so a variable whose genuine limit sits far
    above the largest coefficient in the model (``1e-9*A1 <= 1``, capping A1
    at 1e9 in a model whose numbers are order 1) pins against the box and is
    reported as a runaway when it is not. Solving for the actual bound has no
    such threshold to get wrong.
    """
    ok_unbounded = _ext.UNBOUNDED
    out: list[int] = []
    for j, cj in enumerate(c_vec):
        if cj == 0.0:
            continue
        # Which way does this variable have to move to improve the objective?
        # max with c>0 and min with c<0 both improve by increasing it.
        push_up = (cj > 0) == maximize
        probe_obj = [0.0] * len(c_vec)
        probe_obj[j] = 1.0
        probe = _ext.solve_lp(
            probe_obj,
            A,
            sense,
            rhs,
            lb,
            ub,
            maximize=push_up,
            integer_vars=int_indices,
            binary_vars=bin_indices,
        )
        if probe.status == ok_unbounded:
            out.append(j)
    return out


def _irreducible_conflict(
    c_vec: list[float],
    A: list[list[float]],
    sense: list[int],
    rhs: list[float],
    lb: list[float],
    ub: list[float],
    maximize: bool,
    int_indices: list[int],
    bin_indices: list[int],
) -> list[int]:
    """Row indices of an irreducible inconsistent subsystem (IIS).

    Returns a subset of the constraints that is still infeasible but becomes
    feasible if any single member is dropped -- i.e. a minimal explanation of
    *why* the model has no solution, rather than the bare word INFEASIBLE.

    Classic deletion filter: try removing each constraint in turn; if what
    remains is still infeasible the constraint was not part of the conflict,
    so drop it permanently. Costs one solve per constraint, which is fine at
    spreadsheet scale and only runs on the failure path.

    Variable bounds are never dropped -- they are held fixed as part of the
    background against which the conflict is minimal. A constraint that
    contradicts the bounds is therefore reported as the conflict, which is
    the useful answer: the bounds are context, the constraint is the thing
    the user can point at. An empty result would mean the bounds alone are
    contradictory; that is unreachable today because ``lb > ub`` is rejected
    before any solve, so the empty branch below is defensive only.

    Note the test is specifically for INFEASIBLE, not "not OPTIMAL". Dropping
    a constraint can leave the problem UNBOUNDED, which means the feasible
    region is non-empty -- so that constraint *is* needed for the conflict
    and must be kept.
    """

    def infeasible_without(rows: list[int]) -> bool:
        if not rows:
            trial_A: list[list[float]] = []
            trial_sense: list[int] = []
            trial_rhs: list[float] = []
        else:
            trial_A = [A[i] for i in rows]
            trial_sense = [sense[i] for i in rows]
            trial_rhs = [rhs[i] for i in rows]
        probe = _ext.solve_lp(
            c_vec,
            trial_A,
            trial_sense,
            trial_rhs,
            lb,
            ub,
            maximize=maximize,
            integer_vars=int_indices,
            binary_vars=bin_indices,
        )
        return bool(probe.status == _ext.INFEASIBLE)

    keep = list(range(len(A)))
    for i in range(len(A)):
        if i not in keep:
            continue
        trial = [j for j in keep if j != i]
        if infeasible_without(trial):
            keep = trial
    return keep


# lp_solve uses 1e30 as its infinity sentinel in the ranging arrays. Convert
# to a real infinity so callers can format it as "inf" rather than printing a
# meaningless 1e+30.
_LP_INF = 1e30


def _from_lp_inf(v: float) -> float:
    if v >= _LP_INF:
        return float("inf")
    if v <= -_LP_INF:
        return float("-inf")
    return float(v)


def _build_sensitivity(
    decision_vars: list[CellKey],
    constraint_cells: list[CellKey],
    c_vec: list[float],
    A: list[list[float]],
    rhs: list[float],
    sol: Any,
    values: dict[CellKey, float],
) -> Sensitivity:
    """Assemble the solver's raw sensitivity arrays into per-cell records."""
    variables = [
        VarSensitivity(
            cell=cell,
            value=values.get(cell, 0.0),
            reduced_cost=float(sol.reduced_costs[j]) if j < len(sol.reduced_costs) else 0.0,
            obj_coef=c_vec[j],
            obj_from=_from_lp_inf(sol.obj_from[j]) if j < len(sol.obj_from) else float("-inf"),
            obj_till=_from_lp_inf(sol.obj_till[j]) if j < len(sol.obj_till) else float("inf"),
        )
        for j, cell in enumerate(decision_vars)
    ]

    x = [values.get(v, 0.0) for v in decision_vars]
    n_rows = len(sol.duals)
    constraints = []
    for i, cell in enumerate(constraint_cells):
        activity = sum(coef * xj for coef, xj in zip(A[i], x, strict=True))
        slack = rhs[i] - activity
        lo = _from_lp_inf(sol.dual_from[i]) if i < len(sol.dual_from) else float("-inf")
        hi = _from_lp_inf(sol.dual_till[i]) if i < len(sol.dual_till) else float("inf")
        # Bindingness is derived from slack rather than from a non-zero dual.
        # A degenerate optimum can leave a binding constraint with a zero
        # shadow price, and calling that non-binding would be wrong.
        constraints.append(
            ConstraintSensitivity(
                cell=cell,
                shadow_price=float(sol.duals[i]) if i < n_rows else 0.0,
                rhs=rhs[i],
                activity=activity,
                slack=slack,
                binding=abs(slack) <= 1e-9,
                rhs_from=lo,
                rhs_till=hi,
            )
        )

    return Sensitivity(variables=variables, constraints=constraints)


def _cellname(c: int, r: int) -> str:
    """Local helper to avoid an engine import cycle for a one-line format."""
    from .engine import cellname

    return cellname(c, r)


def sweep(
    grid: Grid,
    objective_cell: CellKey,
    decision_vars: list[CellKey],
    constraint_cells: list[CellKey],
    *,
    constraint: CellKey,
    lo: float,
    hi: float,
    steps: int = 10,
    maximize: bool = True,
    bounds: dict[CellKey, tuple[float, float]] | None = None,
    integer_vars: set[CellKey] | None = None,
    binary_vars: set[CellKey] | None = None,
) -> list[SweepPoint]:
    """Re-solve the model across a range of right-hand sides for one constraint.

    A shadow price answers "what is the next unit worth". It is valid only
    inside its ranging interval, so it cannot answer "how much more should I
    buy" -- past the interval edge the basis changes and the marginal value
    drops. Sweeping re-solves at each point and reports where that happens.

    The sheet is never modified: each point substitutes the right-hand side
    via ``solve(rhs_override=...)`` with ``apply=False``. The constraint's
    coefficients still come from its formula; only the constant moves.

    ``steps`` is the number of intervals, so the result has ``steps + 1``
    points spanning ``lo``..``hi`` inclusive. Points where the model becomes
    infeasible or unbounded are included with their status rather than
    dropped -- discovering that a resource level is unattainable is a real
    answer to the question being asked.
    """
    if steps < 1:
        raise OptError("sweep needs at least 1 step")
    if hi < lo:
        raise OptError(f"sweep range is reversed: {lo:g} to {hi:g}")
    if constraint not in constraint_cells:
        raise OptError(f"{_cellname(*constraint)} is not one of the constraint cells")

    points: list[SweepPoint] = []
    prev_obj: float | None = None
    prev_price: float | None = None

    for k in range(steps + 1):
        value = lo if steps == 0 else lo + (hi - lo) * k / steps
        result = solve(
            grid,
            objective_cell,
            decision_vars,
            constraint_cells,
            maximize=maximize,
            bounds=bounds,
            integer_vars=integer_vars,
            binary_vars=binary_vars,
            apply=False,
            sensitivity=True,
            rhs_override={constraint: value},
        )
        solved = result.status_name in ("OPTIMAL", "SUBOPTIMAL")

        price: float | None = None
        if result.sensitivity is not None:
            for c in result.sensitivity.constraints:
                if c.cell == constraint:
                    price = c.shadow_price
                    break

        delta = result.objective - prev_obj if (solved and prev_obj is not None) else None
        # Only call it a breakpoint when both prices are known; a None on
        # either side means "not comparable", not "changed".
        changed = price is not None and prev_price is not None and abs(price - prev_price) > 1e-9

        points.append(
            SweepPoint(
                rhs=value,
                status_name=result.status_name,
                objective=result.objective if solved else float("nan"),
                shadow_price=price,
                delta=delta,
                breakpoint=changed,
            )
        )
        if solved:
            prev_obj = result.objective
        prev_price = price

    return points


@dataclass
class InferredModel:
    """A model deduced from a selected block rather than typed out."""

    objective: CellKey
    decision_vars: list[CellKey]
    constraint_cells: list[CellKey]


def infer_model(grid: Grid, c1: int, r1: int, c2: int, r2: int) -> InferredModel:
    """Classify the cells in a rectangular block into an LP model.

    The spatial layout of a sheet already encodes the model; this reads it
    instead of making the user retype it as ranges:

      * a formula whose root is a comparison is a **constraint**
      * any other formula is the **objective** (exactly one must be present)
      * a plain number is a **decision variable**
      * labels, blanks, and errors are ignored

    Blank cells are deliberately *not* treated as decision variables even
    though ``solve`` accepts empty ones. A selected rectangle is mostly
    whitespace, and silently promoting every gap to a variable would build a
    model the user did not describe.

    Cells are returned in column-major order within the block, matching how
    ``_parse_cells`` expands a typed range, so an inferred model and a typed
    one produce the same variable ordering for the same cells.

    Raises ``OptError`` naming what was missing or ambiguous -- the whole
    point is to fail with something the user can act on.
    """
    objective: list[CellKey] = []
    decision_vars: list[CellKey] = []
    constraint_cells: list[CellKey] = []

    for c in range(c1, c2 + 1):
        for r in range(r1, r2 + 1):
            cell = grid.cells[c][r]
            if cell is None or cell.type == EMPTY:
                continue
            if cell.type == NUM:
                decision_vars.append((c, r))
                continue
            if cell.type != FORMULA:
                continue  # labels
            node = _cell_ast(cell)
            if node is None:
                continue
            if isinstance(node, BinOp) and node.op in _SENSE:
                constraint_cells.append((c, r))
            elif isinstance(node, BinOp) and node.op == "<>":
                raise OptError(f"{_cellname(c, r)} uses '<>', which is not a valid LP constraint")
            else:
                objective.append((c, r))

    if not objective:
        raise OptError("no objective formula in the selection")
    if len(objective) > 1:
        names = ", ".join(_cellname(*k) for k in objective[:4])
        raise OptError(
            f"selection has {len(objective)} candidate objective formulas ({names}); "
            "narrow it to one"
        )
    if not decision_vars:
        raise OptError("no numeric decision cells in the selection")
    if not constraint_cells:
        raise OptError("no constraint formulas in the selection")

    return InferredModel(
        objective=objective[0],
        decision_vars=decision_vars,
        constraint_cells=constraint_cells,
    )


def _add_quadratic_relaxation(
    squares: dict[CellKey, float],
    decision_vars: list[CellKey],
    var_index: dict[CellKey, int],
    c_vec: list[float],
    A: list[list[float]],
    sense: list[int],
    rhs: list[float],
    lb: list[float],
    ub: list[float],
    *,
    maximize: bool,
    segments: int,
) -> float:
    """Extend an LP in place so it approximates a separable quadratic objective.

    lp_solve is LP/MIP only. For a *convex* separable quadratic there is a
    standard exact-in-the-limit reformulation that needs no second solver: a
    convex function is the upper envelope of its tangents, so

        x^2  ==  max over a of ( 2*a*x - a^2 )

    Introduce one auxiliary column ``z_j`` per squared term and constrain it
    from below by a fan of tangents:

        z_j - 2*a_k*x_j >= -a_k^2      for tangent points a_k

    The objective then uses ``q_j * z_j``. When the objective pushes ``z_j``
    downward -- minimising with ``q_j > 0``, or maximising with ``q_j < 0`` --
    the solver drives each ``z_j`` down onto the envelope, so ``z_j``
    approaches ``x_j^2`` from below. That is exactly the convex case, and the
    reason the sign of every coefficient is checked before we get here: with
    the wrong sign the solver would push ``z_j`` to its bound instead and
    return a confident answer to a different problem.

    Returns a bound on the objective gap. The tangent envelope understates
    ``x^2`` by at most ``h^2/4`` between adjacent tangent points spaced ``h``
    apart, so the bound is ``sum_j |q_j| * h_j^2 / 4``.

    Requires finite bounds on every quadratic variable: tangent points have to
    be placed across a known interval, and there is no meaningful place to put
    them on an unbounded one.
    """
    if segments < 1:
        raise OptError("quadratic_segments must be at least 1")

    for cell, q in squares.items():
        name = _cellname(*cell)
        # Convexity. Minimising needs a convex objective (q > 0); maximising
        # needs concave (q < 0). The wrong sign makes the true optimum sit at
        # a corner of the feasible region and the relaxation unbounded or
        # simply wrong, so refuse rather than approximate.
        if maximize and q > 0.0:
            raise NotQuadratic(
                f"maximising a convex objective: {name}^2 has a positive "
                f"coefficient ({q:g}); the maximum is unbounded or at a corner, "
                "which this solver cannot find reliably"
            )
        if not maximize and q < 0.0:
            raise NotQuadratic(
                f"minimising a concave objective: {name}^2 has a negative "
                f"coefficient ({q:g}); the minimum is at a corner, which this "
                "solver cannot find reliably"
            )

    gap = 0.0
    for cell in sorted(squares, key=lambda k: var_index[k]):
        q = squares[cell]
        j = var_index[cell]
        lo, hi = lb[j], ub[j]
        name = _cellname(*cell)
        if math.isinf(lo) or math.isinf(hi):
            raise OptError(
                f"{name} appears squared in the objective but is unbounded; "
                "give it finite bounds (e.g. 'bounds " + name + "=0:100')"
            )
        if hi <= lo:
            # Pinned variable: the square is a constant, nothing to model.
            continue

        z = len(c_vec)  # index of the new auxiliary column
        c_vec.append(q)
        lb.append(0.0)
        ub.append(max(lo * lo, hi * hi))
        for row in A:
            row.append(0.0)

        step = (hi - lo) / segments
        for k in range(segments + 1):
            a = lo + step * k
            row = [0.0] * len(c_vec)
            row[j] = -2.0 * a
            row[z] = 1.0
            A.append(row)
            sense.append(_ext.GE)
            rhs.append(-a * a)

        gap += abs(q) * step * step / 4.0

    return gap


def evaluate_quadratic(
    squares: dict[CellKey, float],
    linear: LinearForm,
    values: dict[CellKey, float],
) -> float:
    """The objective's true value at ``values``.

    Reported instead of the relaxation's objective. The solved point is
    feasible for the real problem, so its true objective is an achievable
    number the user can trust; the relaxation's value is an artefact of the
    approximation and would be slightly optimistic.
    """
    total = linear.constant
    for cell, coef in linear.coeffs.items():
        total += coef * values.get(cell, 0.0)
    for cell, q in squares.items():
        x = values.get(cell, 0.0)
        total += q * x * x
    return total
