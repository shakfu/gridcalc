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

    ``diagnose=True`` populates ``SolveResult.conflict`` when the model turns
    out to be infeasible: a minimal set of constraint cells that contradict
    each other. It costs one extra solve per constraint and runs only on the
    infeasible path.
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
    obj_form = extract_linear(obj_ast, var_set, grid)
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
        row = [coeffs.get(v, 0.0) for v in decision_vars]
        A.append(row)
        sense.append(op_code)
        rhs.append(rhs_val)

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
        for v, x in zip(decision_vars, sol.x, strict=True):
            values[v] = float(x)

    applied = False
    if apply and values:
        for (c, r), x in values.items():
            cell = grid.cells[c][r]
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
    )


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
