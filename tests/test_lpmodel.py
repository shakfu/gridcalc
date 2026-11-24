"""Tests for `gridcalc.lpmodel`, the PuLP subset solved by builtin HiGHS."""

from __future__ import annotations

import math

import pytest

from gridcalc import lpmodel
from gridcalc.dataitems import apply_writes, collect_writes, read_items
from gridcalc.lpmodel import (
    LpAffineExpression,
    LpBinary,
    LpInteger,
    LpMaximize,
    LpMinimize,
    LpProblem,
    LpStatus,
    LpStatusInfeasible,
    LpStatusNotSolved,
    LpStatusOptimal,
    LpStatusUnbounded,
    LpVariable,
    PulpError,
    lpSum,
    value,
)

# PuLP's BeerDistributionProblem as SolverStudio ships it, reading data items.
BEER_MODEL = """\
from pulp import *

prob = LpProblem("Beer Distribution Problem", LpMinimize)
Routes = [(w, b) for w in Warehouses for b in Bars]
vars = LpVariable.dicts("Route", (Warehouses, Bars), 0, None, LpInteger)
prob += lpSum([vars[w][b] * costs[w, b] for (w, b) in Routes]), "Sum_of_Transporting_Costs"
for w in Warehouses:
    out = lpSum([vars[w][b] for b in Bars])
    prob += out <= supply[w], "Sum_of_Products_out_of_Warehouse_%s" % w
for b in Bars:
    prob += lpSum([vars[w][b] for w in Warehouses]) >= demand[b], "Sum_of_Products_into_Bar%s" % b
prob.solve()
for (w, b) in Routes:
    flow[w, b] = vars[w][b].varValue
SolverResult = LpStatus[prob.status]
"""


def _import(name, globals=None, locals=None, fromlist=(), level=0):
    if name == "pulp":
        return lpmodel
    raise ImportError(name)


def test_beer_model_solves_and_writes_back(beer) -> None:
    items = read_items(beer)
    ns = {"__builtins__": {**__builtins__, "__import__": _import}, **items}  # type: ignore[dict-item]
    exec(BEER_MODEL, ns)
    assert ns["SolverResult"] == "Optimal"
    assert value(ns["prob"].objective) == pytest.approx(8400)
    writes = collect_writes(items)
    writes["SolverResult"] = ns["SolverResult"]
    assert apply_writes(beer, writes) == 11
    shipped = [[beer.cells[2 + j][8 + i].val for j in range(5)] for i in range(2)]
    assert [sum(col) for col in zip(*shipped, strict=True)] == [500, 900, 1800, 200, 700]
    assert beer.cells[1][13].text == "Optimal"


def test_expression_algebra() -> None:
    x, y = LpVariable("x"), LpVariable("y")
    e = 2 * x + y * 3 - 4 + (x - y) / 2
    assert e.terms == {x: 2.5, y: 2.5}
    assert e.constant == -4
    assert (-e).terms == {x: -2.5, y: -2.5}
    assert (5 - x).constant == 5 and (5 - x).terms == {x: -1.0}
    assert lpSum([x, 2, y, x]).terms == {x: 2.0, y: 1.0}
    assert lpSum([]).terms == {}


def test_comparisons_build_constraints() -> None:
    x = LpVariable("x")
    c = x + 1 <= 3
    assert c.sense == lpmodel.LpConstraintLE
    assert c.expr.terms == {x: 1.0} and c.expr.constant == -2
    assert (3 >= x).sense == lpmodel.LpConstraintLE  # noqa: SIM300  (reflected)
    assert (x == 2).sense == lpmodel.LpConstraintEQ


def test_variables_stay_hashable_and_distinct() -> None:
    a, b = LpVariable("a"), LpVariable("a")
    assert len({a: 1, b: 2}) == 2


def test_lp_max_with_bounds() -> None:
    x = LpVariable("x", 0)
    y = LpVariable("y", 0, 3)
    prob = LpProblem("p", LpMaximize)
    prob += 3 * x + 2 * y
    prob += x + y <= 4
    prob += x + 3 * y <= 6
    assert prob.solve() == LpStatusOptimal
    assert value(prob.objective) == pytest.approx(12)
    assert x.varValue == pytest.approx(4) and y.varValue == pytest.approx(0)


def test_objective_constant_is_kept() -> None:
    x = LpVariable("x", 1)
    prob = LpProblem()
    prob += x + 10
    prob.solve()
    assert value(prob.objective) == pytest.approx(11)


def test_integer_and_binary() -> None:
    x = LpVariable("x", 0, None, LpInteger)
    prob = LpProblem("p", LpMaximize)
    prob += x
    prob += 2 * x <= 7
    prob.solve()
    assert x.varValue == pytest.approx(3)
    b = LpVariable("b", cat=LpBinary)
    assert (b.lowBound, b.upBound) == (0.0, 1.0)


def test_default_variable_is_free() -> None:
    x = LpVariable("x")
    prob = LpProblem()
    prob += x
    prob += x >= -5
    prob.solve()
    assert x.varValue == pytest.approx(-5)


@pytest.mark.parametrize(
    ("build", "status"),
    [
        (lambda p, x: p.__iadd__(x >= 2).__iadd__(x <= 1), LpStatusInfeasible),
        (lambda p, x: p, LpStatusUnbounded),
    ],
)
def test_failure_statuses(build, status) -> None:
    x = LpVariable("x")
    prob = LpProblem("p", LpMaximize)
    prob += x
    build(prob, x)
    assert prob.solve() == status
    assert x.varValue is None
    assert value(prob.objective) is None


def test_constant_constraint_decided_without_solver() -> None:
    x = LpVariable("x", 0)
    prob = LpProblem()
    prob += x
    prob += LpVariable("y") * 0 + 3 <= 0
    assert prob.solve() == LpStatusInfeasible


def test_dicts_shapes() -> None:
    flat = LpVariable.dicts("v", ["a", "b"], 0)
    assert flat["a"].name == "v_a" and flat["a"].lowBound == 0
    nested = LpVariable.dicts("r", (["A", "B"], [1, 2]))
    assert nested["B"][2].name == "r_B_2"
    tupled = LpVariable.dicts("t", [("A", 1)])
    assert ("A", 1) in tupled


def test_constraint_names() -> None:
    x = LpVariable("x")
    prob = LpProblem()
    prob += x >= 1, "lower bound"
    prob += x <= 5
    assert list(prob.constraints) == ["lower_bound", "_C1"]
    with pytest.raises(PulpError, match="overlapping"):
        prob += x <= 6, "lower bound"


def test_variables_lists_used_columns_only() -> None:
    x, y, _unused = LpVariable("x"), LpVariable("y"), LpVariable("z")
    prob = LpProblem()
    prob += y + x
    assert [v.name for v in prob.variables()] == ["x", "y"]


@pytest.mark.parametrize(
    ("action", "message"),
    [
        (lambda x, p: x * x * x, "past degree 2"),
        (lambda x, p: x**3, "only a square"),
        (lambda x, p: x * x <= 1, "only the objective may be quadratic"),
        (lambda x, p: 1 / x, "unsupported operand|not linear"),
        (lambda x, p: x / x, "dividing by a variable"),
        (lambda x, p: p.writeLP("f.lp"), "LpProblem.writeLP is not in gridcalc's PuLP subset"),
        (lambda x, p: x.lowbound, "LpVariable.lowbound is not in"),
        (lambda x, p: p.solve(object()), "solver selection"),
        (lambda x, p: p.solve(msg=0), "does not take msg"),
        (lambda x, p: bool(x <= 1), "no truth value"),
        (lambda x, p: p.__iadd__(1 <= 2), "comparing plain numbers"),
        (lambda x, p: x + "a", "is not a number"),
        (lambda x, p: LpVariable("y", cat="Semi"), "unknown category"),
        (lambda x, p: LpProblem("p", 0), "sense must be"),
    ],
)
def test_outside_the_subset_fails_by_name(action, message) -> None:
    x = LpVariable("x")
    prob = LpProblem()
    with pytest.raises((PulpError, TypeError), match=message):
        action(x, prob)


def test_unsolved_status() -> None:
    prob = LpProblem()
    assert prob.status == LpStatusNotSolved
    assert LpStatus[prob.status] == "Not Solved"
    assert value(3) == 3 and value(None) is None


def test_time_limit_passed_through() -> None:
    x = LpVariable("x", 0, 1)
    prob = LpProblem("p", LpMinimize)
    prob += x
    assert prob.solve(time_limit=5) == LpStatusOptimal
    assert not math.isnan(x.varValue or 0.0)


def test_large_sparse_model() -> None:
    # 300 x 300 transport: 90,000 variables, 600 constraints. A dense matrix
    # would be 54M entries (432 MB); CSR holds 180,000.
    n = 300
    x = {(i, j): LpVariable(f"x_{i}_{j}", 0) for i in range(n) for j in range(n)}
    prob = LpProblem("t", LpMinimize)
    prob += lpSum(((i * 7 + j * 13) % 17 + 1) * v for (i, j), v in x.items())
    for i in range(n):
        prob += lpSum(x[i, j] for j in range(n)) <= 10
    for j in range(n):
        prob += lpSum(x[i, j] for i in range(n)) >= 10
    assert prob.solve() == LpStatusOptimal
    assert sum(v.varValue or 0 for v in x.values()) == pytest.approx(3000)


def test_bad_csr_is_refused_by_the_extension() -> None:
    from gridcalc import _opt

    with pytest.raises(ValueError, match="a_index entry out of range"):
        _opt.solve_lp_sparse([1.0], [0], [5], [1.0], [_opt.LE], [1.0], [0.0], [1.0])
    with pytest.raises(ValueError, match="non-decreasing"):
        _opt.solve_lp_sparse([1.0], [0, 3], [0], [1.0], [_opt.LE] * 2, [1.0] * 2, [0.0], [1.0])
    with pytest.raises(ValueError, match="too small"):
        _opt.solve_lp_sparse([1.0], [0], [0], [1e-12], [_opt.LE], [1.0], [0.0], [1.0])
    with pytest.raises(ValueError, match="finite"):
        _opt.solve_lp_sparse([1.0], [0], [0], [float("nan")], [_opt.LE], [1.0], [0.0], [1.0])


def _case(maximize, obj, cons):
    xs = [LpVariable(n, 0) for n in ("x", "y", "z")[: len(obj)]]
    p = LpProblem("c", LpMaximize if maximize else LpMinimize)
    p += lpSum(a * x for a, x in zip(obj, xs, strict=True))
    for name, coefs, op, rhs in cons:
        e = lpSum(a * x for a, x in zip(coefs, xs, strict=True))
        p += (e <= rhs if op == "<=" else e >= rhs if op == ">=" else e == rhs), name
    assert p.solve() == LpStatusOptimal
    return p, xs


@pytest.mark.parametrize(
    ("maximize", "obj", "cons", "pi", "dj"),
    [
        (
            True,
            [3, 2, -1],
            [("le", [1, 1, 0], "<=", 4), ("le2", [1, 0, 0], "<=", 3)],
            {"le": 2.0, "le2": 1.0},
            [0.0, 0.0, -1.0],
        ),
        (
            False,
            [2, 3, 1],
            [("ge", [1, 1, 0], ">=", 4), ("ge2", [0, 1, 0], ">=", 1)],
            {"ge": 2.0, "ge2": 1.0},
            [0.0, 0.0, 1.0],
        ),
        (
            False,
            [-1, -1],
            [("le", [1, 2], "<=", 6), ("le2", [1, 0], "<=", 2)],
            {"le": -0.5, "le2": -0.5},
            [0.0, 0.0],
        ),
        (
            True,
            [-1, -2],
            [("ge", [1, 1], ">=", 3), ("ge2", [1, 0], ">=", 1)],
            {"ge": -1.0, "ge2": 0.0},
            [0.0, -1.0],
        ),
        (
            False,
            [1, 3],
            [("eq", [1, 1], "==", 5), ("le", [1, 0], "<=", 2)],
            {"eq": 3.0, "le": -2.0},
            [0.0, 0.0],
        ),
    ],
)
def test_duals_match_pulp_with_cbc(maximize, obj, cons, pi, dj) -> None:
    p, xs = _case(maximize, obj, cons)
    assert {k: c.pi for k, c in p.constraints.items()} == pytest.approx(pi)
    assert [x.dj for x in xs] == pytest.approx(dj)


def test_mip_has_no_duals() -> None:
    x = LpVariable("x", 0, None, LpInteger)
    p = LpProblem("m", LpMaximize)
    p += x
    p += 2 * x <= 7, "cap"
    p.solve()
    assert p.constraints["cap"].pi is None and x.dj is None


def test_duals_cleared_by_a_failed_solve() -> None:
    p, xs = _case(False, [1, 3], [("eq", [1, 1], "==", 5), ("le", [1, 0], "<=", 2)])
    p += xs[0] >= 3, "conflict"
    assert p.solve() == LpStatusInfeasible
    assert p.constraints["eq"].pi is None and xs[0].dj is None


def test_in_place_add_is_linear_and_leaves_variables_alone() -> None:
    import time

    xs = [LpVariable(f"x{i}", 0) for i in range(50_000)]
    t = time.perf_counter()
    e = LpAffineExpression()
    for x in xs:
        e += 2 * x
    assert time.perf_counter() - t < 2  # quadratic copying took minutes
    assert len(e.terms) == 50_000
    v = xs[0]
    w = v
    w += 1
    assert v.terms == {v: 1.0} and v.constant == 0.0
    assert w.constant == 1.0


# --- quadratic objectives: gridcalc's extension; PuLP itself has none -------


def test_convex_qp_minimum() -> None:
    x, y = LpVariable("x"), LpVariable("y")
    p = LpProblem("q", LpMinimize)
    p += (x - 1) ** 2 + (y - 2) ** 2
    p += x + y <= 2
    assert p.solve() == LpStatusOptimal
    assert (x.varValue, y.varValue) == (pytest.approx(0.5, abs=1e-5), pytest.approx(1.5, abs=1e-5))
    assert value(p.objective) == pytest.approx(0.5, abs=1e-5)  # constant 5 kept


def test_cross_terms_and_concave_maximum() -> None:
    # max -(x^2 + x*y + y^2) + 3x: optimum where 2x + y = 3, x + 2y = 0 -> x = 2, y = -1
    x, y = LpVariable("x"), LpVariable("y")
    p = LpProblem("q", LpMaximize)
    p += -(x * x + x * y + y * x * 0 + y * y) + 3 * x
    p.solve()
    assert (x.varValue, y.varValue) == (pytest.approx(2, abs=1e-5), pytest.approx(-1, abs=1e-5))
    assert value(p.objective) == pytest.approx(3, abs=1e-5)


def test_qp_has_no_duals() -> None:
    x = LpVariable("x")
    p = LpProblem("q", LpMinimize)
    p += x * x
    p += x >= 1, "lo"
    p.solve()
    assert x.varValue == pytest.approx(1, abs=1e-5)
    assert p.constraints["lo"].pi is None and x.dj is None


def test_non_convex_qp_explains() -> None:
    x = LpVariable("x", 0, 1)
    p = LpProblem("q", LpMinimize)
    p += -(x * x)
    with pytest.raises(PulpError, match="must be convex when minimising"):
        p.solve()


def test_miqp_refused() -> None:
    x = LpVariable("x", 0, 5, LpInteger)
    p = LpProblem("q", LpMinimize)
    p += (x - 2.5) ** 2
    with pytest.raises(PulpError, match="MIQP"):
        p.solve()


def test_expression_algebra_with_squares() -> None:
    x, y = LpVariable("x"), LpVariable("y")
    e = (x + 2 * y + 1) * (x - 1)
    assert e.constant == -1
    assert e.terms == {x: 0.0, y: -2.0} or e.terms == {y: -2.0, x: 0.0}
    sq = {frozenset(k): v for k, v in e.qterms.items()}
    assert sq == {frozenset([x]): 1.0, frozenset([x, y]): 2.0}
    x.varValue, y.varValue = 3.0, 1.0
    assert e.value() == pytest.approx((3 + 2 + 1) * (3 - 1))
    assert (x * y).qterms == (y * x).qterms  # one term, whichever order


def test_hessian_layout() -> None:
    from gridcalc.lpmodel import _hessian, _pair

    x, y, z = LpVariable("x"), LpVariable("y"), LpVariable("z")
    pos = {x: 0, y: 1, z: 2}
    q = {_pair(x, x): 3.0, _pair(x, y): 1.0, _pair(z, z): 1.0}
    assert _hessian(q, pos) == [[6.0], [1.0], [0.0, 0.0, 2.0]]


def test_quadratic_variables_come_first() -> None:
    a, b = LpVariable("a"), LpVariable("b")
    p = LpProblem("q", LpMinimize)
    p += a + b * b
    p += a + b >= 1
    assert p._columns()[0] is b


def test_lpsum_keeps_quadratic_terms() -> None:
    x = LpVariable("x")
    e = lpSum([x * x, 2 * x, 1])
    assert list(e.qterms.values()) == [1.0] and e.terms == {x: 2.0} and e.constant == 1
