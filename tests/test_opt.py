"""Tests for sheet-level linear optimization (gridcalc.opt)."""

from __future__ import annotations

import math

import pytest

from gridcalc.engine import Grid
from gridcalc.formula.parser import parse
from gridcalc.opt import (
    LinearForm,
    NotLinear,
    NotQuadratic,
    OptError,
    extract_constraint,
    extract_linear,
    extract_quadratic,
    solve,
)


def make_grid() -> Grid:
    return Grid()


# --- Linearity walker ------------------------------------------------------


def test_linear_constant():
    g = make_grid()
    f = extract_linear(parse("=42"), set(), g)
    assert f.coeffs == {}
    assert f.constant == 42.0


def test_linear_decision_var_only():
    g = make_grid()
    g.setcell(0, 0, "0")  # A1 is a decision var, currently empty/0
    dvs = {(0, 0)}
    f = extract_linear(parse("=A1"), dvs, g)
    assert f.coeffs == {(0, 0): 1.0}
    assert f.constant == 0.0


def test_linear_constant_cell_folded_into_constant():
    g = make_grid()
    g.setcell(0, 0, "0")  # A1 = decision var
    g.setcell(1, 0, "7")  # B1 = parameter, currently 7
    f = extract_linear(parse("=A1+B1"), {(0, 0)}, g)
    assert f.coeffs == {(0, 0): 1.0}
    assert f.constant == 7.0


def test_linear_arithmetic_combinations():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    dvs = {(0, 0), (0, 1)}
    f = extract_linear(parse("=3*A1 + 5*A2 - 2"), dvs, g)
    assert f.coeffs == {(0, 0): 3.0, (0, 1): 5.0}
    assert f.constant == -2.0


def test_linear_unary_minus_and_division():
    g = make_grid()
    g.setcell(0, 0, "0")
    f = extract_linear(parse("=-A1/2 + 4"), {(0, 0)}, g)
    assert f.coeffs == {(0, 0): -0.5}
    assert f.constant == 4.0


def test_linear_percent():
    g = make_grid()
    g.setcell(0, 0, "0")
    f = extract_linear(parse("=A1*50%"), {(0, 0)}, g)
    assert f.coeffs == {(0, 0): pytest.approx(0.5)}


def test_linear_sum_over_range():
    g = make_grid()
    for r in range(3):
        g.setcell(0, r, "0")  # A1, A2, A3 -- decision vars
    g.setcell(1, 0, "10")  # B1 -- constant cell
    dvs = {(0, 0), (0, 1), (0, 2)}
    f = extract_linear(parse("=SUM(A1:A3) + B1"), dvs, g)
    assert f.coeffs == {(0, 0): 1.0, (0, 1): 1.0, (0, 2): 1.0}
    assert f.constant == 10.0


def test_linear_rejects_nonlinear_product():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    with pytest.raises(NotLinear, match="product"):
        extract_linear(parse("=A1*A2"), {(0, 0), (0, 1)}, g)


def test_linear_rejects_division_by_decision_var():
    g = make_grid()
    g.setcell(0, 0, "0")
    with pytest.raises(NotLinear, match="division"):
        extract_linear(parse("=1/A1"), {(0, 0)}, g)


def test_linear_rejects_unsupported_function():
    g = make_grid()
    g.setcell(0, 0, "0")
    with pytest.raises(NotLinear, match="not allowed"):
        extract_linear(parse("=ABS(A1)"), {(0, 0)}, g)


# --- Constraint extraction -------------------------------------------------


def test_constraint_simple_le():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    coeffs, sense, rhs = extract_constraint(parse("=A1+A2<=10"), {(0, 0), (0, 1)}, g)
    assert coeffs == {(0, 0): 1.0, (0, 1): 1.0}
    assert rhs == 10.0
    # _opt.LE == 1
    from gridcalc import _opt as _ext

    assert sense == _ext.LE


def test_constraint_moves_vars_to_lhs_constants_to_rhs():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    # 5 - A1 >= 2*A2 - 3   =>  -A1 - 2*A2 >= -8   (LHS - RHS = -A1 - 2*A2 + 8)
    coeffs, sense, rhs = extract_constraint(parse("=5-A1>=2*A2-3"), {(0, 0), (0, 1)}, g)
    assert coeffs == {(0, 0): -1.0, (0, 1): -2.0}
    assert rhs == -8.0


def test_constraint_rejects_non_comparison():
    g = make_grid()
    g.setcell(0, 0, "0")
    with pytest.raises(OptError, match="comparison"):
        extract_constraint(parse("=A1+1"), {(0, 0)}, g)


def test_constraint_rejects_ne():
    g = make_grid()
    g.setcell(0, 0, "0")
    with pytest.raises(OptError, match="<>"):
        extract_constraint(parse("=A1<>3"), {(0, 0)}, g)


# --- End-to-end solve ------------------------------------------------------


def test_solve_textbook_max():
    """Classic 2-variable LP:
        maximize 3*x + 5*y
        subject to  x        <= 4
                       2*y   <= 12
                    3*x + 2*y <= 18
                    x, y >= 0   (default bounds)
    Optimum: x=2, y=6, obj=36.
    """
    g = make_grid()
    # Decision vars at A1, A2 (currently 0).
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    # Objective at C1.
    g.setcell(2, 0, "=3*A1+5*A2")
    # Constraints at D1, D2, D3.
    g.setcell(3, 0, "=A1<=4")
    g.setcell(3, 1, "=2*A2<=12")
    g.setcell(3, 2, "=3*A1+2*A2<=18")

    result = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0), (0, 1)],
        constraint_cells=[(3, 0), (3, 1), (3, 2)],
        maximize=True,
    )
    assert result.status_name == "OPTIMAL"
    assert result.objective == pytest.approx(36.0)
    assert result.values[(0, 0)] == pytest.approx(2.0)
    assert result.values[(0, 1)] == pytest.approx(6.0)
    assert result.applied is True
    # Decision cells were overwritten with the optimum, and recalc propagated
    # the new objective and constraint values.
    assert g.cells[0][0].val == pytest.approx(2.0)
    assert g.cells[0][1].val == pytest.approx(6.0)
    assert g.cells[2][0].val == pytest.approx(36.0)


# --- Sensitivity analysis --------------------------------------------------


def _wyndor_grid() -> Grid:
    """The `test_solve_textbook_max` LP, whose duals are known analytically.

    max 3x + 5y  s.t.  x <= 4 (slack), 2y <= 12 (tight), 3x + 2y <= 18 (tight)
    Optimum x=2, y=6, obj=36; shadow prices 0, 3/2, 1.
    """
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    g.setcell(2, 0, "=3*A1+5*A2")
    g.setcell(3, 0, "=A1<=4")
    g.setcell(3, 1, "=2*A2<=12")
    g.setcell(3, 2, "=3*A1+2*A2<=18")
    return g


def _solve_wyndor(**kwargs):
    return solve(
        _wyndor_grid(),
        objective_cell=(2, 0),
        decision_vars=[(0, 0), (0, 1)],
        constraint_cells=[(3, 0), (3, 1), (3, 2)],
        maximize=True,
        **kwargs,
    )


def test_sensitivity_off_by_default():
    assert _solve_wyndor().sensitivity is None


def test_sensitivity_shadow_prices_match_analytic_duals():
    sens = _solve_wyndor(sensitivity=True).sensitivity
    assert sens is not None
    prices = [c.shadow_price for c in sens.constraints]
    assert prices == pytest.approx([0.0, 1.5, 1.0])


def test_sensitivity_binding_flags_derive_from_slack():
    """The first constraint has slack (x=2 against a limit of 4); the other
    two are tight. Bindingness must come from slack, not from a non-zero
    dual -- a degenerate optimum can bind at a zero shadow price."""
    sens = _solve_wyndor(sensitivity=True).sensitivity
    assert [c.binding for c in sens.constraints] == [False, True, True]
    assert [c.slack for c in sens.constraints] == pytest.approx([2.0, 0.0, 0.0])
    assert [c.activity for c in sens.constraints] == pytest.approx([2.0, 12.0, 18.0])


def test_sensitivity_reports_cells_not_indices():
    """The report is keyed by the sheet cells the user typed, so a caller can
    render it without re-deriving the ordering."""
    sens = _solve_wyndor(sensitivity=True).sensitivity
    assert [v.cell for v in sens.variables] == [(0, 0), (0, 1)]
    assert [c.cell for c in sens.constraints] == [(3, 0), (3, 1), (3, 2)]


def test_sensitivity_reduced_costs_zero_for_basic_variables():
    """Both variables are non-zero at the optimum, so neither is pinned at a
    bound and both have zero reduced cost."""
    sens = _solve_wyndor(sensitivity=True).sensitivity
    assert [v.reduced_cost for v in sens.variables] == pytest.approx([0.0, 0.0])
    assert [v.value for v in sens.variables] == pytest.approx([2.0, 6.0])
    assert [v.obj_coef for v in sens.variables] == pytest.approx([3.0, 5.0])


def test_sensitivity_reduced_cost_nonzero_for_unattractive_variable():
    """A third product so unprofitable it stays out of the mix must report a
    negative reduced cost -- the amount the objective would drop per unit if
    it were forced in."""
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    g.setcell(0, 2, "0")  # the unattractive one
    g.setcell(2, 0, "=3*A1+5*A2+1*A3")
    g.setcell(3, 0, "=A1<=4")
    g.setcell(3, 1, "=2*A2<=12")
    g.setcell(3, 2, "=3*A1+2*A2+3*A3<=18")

    res = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0), (0, 1), (0, 2)],
        constraint_cells=[(3, 0), (3, 1), (3, 2)],
        maximize=True,
        sensitivity=True,
    )
    third = res.sensitivity.variables[2]
    assert third.value == pytest.approx(0.0), "expected the third product to stay out"
    assert third.reduced_cost < 0.0


def test_sensitivity_rhs_ranging_brackets_the_rhs():
    """Shadow prices are only valid inside the RHS range, so the range must
    actually contain the current right-hand side."""
    sens = _solve_wyndor(sensitivity=True).sensitivity
    for c in sens.constraints:
        assert c.rhs_from <= c.rhs <= c.rhs_till, f"rhs outside its own range: {c}"


def test_sensitivity_infinite_ranges_are_real_infinities():
    """A solver may signal an unbounded range with a large sentinel; leaking
    one into the report would render as a meaningless '1e+30'."""
    sens = _solve_wyndor(sensitivity=True).sensitivity
    assert sens.constraints[0].rhs_till == float("inf")
    assert sens.variables[1].obj_till == float("inf")
    assert all(abs(v.obj_from) < 1e29 or math.isinf(v.obj_from) for v in sens.variables)


def test_slack_constraint_range_starts_at_its_activity():
    """The first constraint (`A1 <= 4`) has slack: A1 sits at 2. Its shadow
    price is 0 and stays 0 until the bound tightens onto the activity, so the
    range is [2, inf) -- verified against a re-solve sweep, where the dual
    jumps from 0 to 3 exactly as the bound crosses 2.

    The previous lp_solve backend reported (-inf, inf) here, which was simply
    wrong; this value is derived rather than read from the solver.
    """
    sens = _solve_wyndor(sensitivity=True).sensitivity
    slack_row = sens.constraints[0]
    assert slack_row.binding is False
    assert slack_row.activity == pytest.approx(2.0)
    assert slack_row.rhs_from == pytest.approx(2.0)
    assert slack_row.rhs_till == float("inf")


def test_binding_constraint_range_comes_from_the_solver():
    """Binding rows keep the solver's ranging, which was cross-checked
    against `sweep`: the shadow price of 1.5 holds from 6 to 18."""
    sens = _solve_wyndor(sensitivity=True).sensitivity
    binding = sens.constraints[1]
    assert binding.binding is True
    assert binding.rhs_from == pytest.approx(6.0)
    assert binding.rhs_till == pytest.approx(18.0)


def test_sensitivity_withheld_for_mip():
    """Branch-and-bound duals describe one LP relaxation, not the integer
    problem. Returning them would be worse than returning nothing."""
    res = _solve_wyndor(sensitivity=True, integer_vars={(0, 0), (0, 1)})
    assert res.status_name == "OPTIMAL"
    assert res.sensitivity is None


def test_sensitivity_absent_when_infeasible():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=A1>=10")
    g.setcell(3, 1, "=A1<=5")
    res = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0)],
        constraint_cells=[(3, 0), (3, 1)],
        maximize=True,
        sensitivity=True,
    )
    assert res.status_name == "INFEASIBLE"
    assert res.sensitivity is None


def test_sensitivity_does_not_change_the_optimum():
    """Asking for sensitivity may change how the solver presolves, so the
    primal answer must be identical with and without it. (This mattered
    concretely under lp_solve, where duals required PRESOLVE_SENSDUALS.)"""
    plain = _solve_wyndor()
    sens = _solve_wyndor(sensitivity=True)
    assert sens.objective == pytest.approx(plain.objective)
    assert sens.values == pytest.approx(plain.values)


def test_solve_no_apply_leaves_cells_untouched():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    g.setcell(2, 0, "=3*A1+5*A2")
    g.setcell(3, 0, "=A1<=4")

    result = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0), (0, 1)],
        constraint_cells=[(3, 0)],
        maximize=True,
        bounds={(0, 1): (0.0, 5.0)},  # cap A2 so the LP is bounded
        apply=False,
    )
    assert result.status_name == "OPTIMAL"
    assert result.applied is False
    # Cells unchanged.
    assert g.cells[0][0].val == 0.0
    assert g.cells[0][1].val == 0.0


def test_solve_infeasible():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=A1>=5")
    g.setcell(3, 1, "=A1<=3")
    result = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0)],
        constraint_cells=[(3, 0), (3, 1)],
        maximize=False,
    )
    assert result.status_name == "INFEASIBLE"
    assert result.values == {}
    assert result.applied is False  # nothing to write on failure


def test_solve_with_negative_bounds():
    """Free variable, finite optimum at the lower bound."""
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=A1>=-5")
    result = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0)],
        constraint_cells=[(3, 0)],
        maximize=False,
        bounds={(0, 0): (-math.inf, math.inf)},
    )
    assert result.status_name == "OPTIMAL"
    assert result.objective == pytest.approx(-5.0)
    assert result.values[(0, 0)] == pytest.approx(-5.0)


def test_solve_objective_with_constant_term():
    """Constant terms in the objective formula must be reflected in the
    reported objective even though the solver never sees them -- only the
    linear part is passed down."""
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1+100")  # objective has +100 constant
    g.setcell(3, 0, "=A1<=10")
    result = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0)],
        constraint_cells=[(3, 0)],
        maximize=True,
    )
    assert result.status_name == "OPTIMAL"
    assert result.values[(0, 0)] == pytest.approx(10.0)
    assert result.objective == pytest.approx(110.0)


def test_solve_rejects_formula_decision_cell():
    g = make_grid()
    g.setcell(0, 0, "=1+1")  # A1 is a formula -- not allowed as decision var
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=A1<=5")
    with pytest.raises(OptError, match="formula"):
        solve(
            g,
            objective_cell=(2, 0),
            decision_vars=[(0, 0)],
            constraint_cells=[(3, 0)],
        )


def test_solve_rejects_non_formula_objective():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "5")  # objective is a literal, not a formula
    with pytest.raises(OptError, match="formula"):
        solve(
            g,
            objective_cell=(2, 0),
            decision_vars=[(0, 0)],
            constraint_cells=[],
        )


def test_solve_requires_unique_decision_vars():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    with pytest.raises(OptError, match="unique"):
        solve(
            g,
            objective_cell=(2, 0),
            decision_vars=[(0, 0), (0, 0)],
            constraint_cells=[],
        )


def test_solve_diet_problem_with_sum():
    """Minimal SUM-flavored problem to exercise SUM in objective+constraint:

        Decision vars A1..A3 (servings of foods 1..3), each >= 0.
        Cost (objective)     :  2*A1 + 3*A2 + A3, minimize.
        Calorie constraint   :  SUM(A1:A3) >= 5.

    The cheapest food is food 3 (cost 1), so the optimum sets A3=5 and the
    rest to 0, with total cost 5.
    """
    g = make_grid()
    for r in range(3):
        g.setcell(0, r, "0")
    g.setcell(2, 0, "=2*A1+3*A2+A3")
    g.setcell(3, 0, "=SUM(A1:A3)>=5")
    result = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0), (0, 1), (0, 2)],
        constraint_cells=[(3, 0)],
        maximize=False,
    )
    assert result.status_name == "OPTIMAL"
    assert result.objective == pytest.approx(5.0)
    assert result.values[(0, 0)] == pytest.approx(0.0)
    assert result.values[(0, 1)] == pytest.approx(0.0)
    assert result.values[(0, 2)] == pytest.approx(5.0)


def test_solve_rejects_cross_sheet_objective_ref():
    """Objective formulas referring to other sheets must be rejected, not
    silently treated as referring to the active sheet."""
    g = make_grid()
    g.setcell(0, 0, "0")
    # Objective references Sheet2!A1; Sheet2 doesn't even exist, but the
    # error fires on the AST walk regardless.
    g.setcell(2, 0, "=Sheet2!A1+A1")
    g.setcell(3, 0, "=A1<=5")
    with pytest.raises(OptError, match="cross-sheet"):
        solve(
            g,
            objective_cell=(2, 0),
            decision_vars=[(0, 0)],
            constraint_cells=[(3, 0)],
        )


def test_solve_rejects_cross_sheet_sum_range():
    g = make_grid()
    for r in range(3):
        g.setcell(0, r, "0")
    g.setcell(2, 0, "=SUM(Sheet2!A1:A3)")
    g.setcell(3, 0, "=A1<=5")
    with pytest.raises(OptError, match="cross-sheet"):
        solve(
            g,
            objective_cell=(2, 0),
            decision_vars=[(0, 0), (0, 1), (0, 2)],
            constraint_cells=[(3, 0)],
        )


def test_solve_walker_rejects_attribute_access_via_notlinear():
    """The linearity walker is the safety boundary for opt: any AST node
    not on its whitelist (Name, PyCall, attribute-style Calls, ranges
    outside SUM, etc.) raises NotLinear, so the LP path can never reach
    code that would be a sandbox concern."""
    g = make_grid()
    g.setcell(0, 0, "0")
    # `foo` is parsed as a Name node, which is rejected.
    g.setcell(2, 0, "=A1+foo")
    g.setcell(3, 0, "=A1<=5")
    with pytest.raises(NotLinear, match="Name"):
        solve(
            g,
            objective_cell=(2, 0),
            decision_vars=[(0, 0)],
            constraint_cells=[(3, 0)],
        )


def test_linear_form_arithmetic():
    """Spot-check the LinearForm helpers used by the walker."""
    a = LinearForm({(0, 0): 1.0, (0, 1): 2.0}, 3.0)
    b = LinearForm({(0, 1): 1.0}, 4.0)
    s = a.add(b)
    assert s.coeffs == {(0, 0): 1.0, (0, 1): 3.0}
    assert s.constant == 7.0
    d = a.sub(b)
    assert d.coeffs == {(0, 0): 1.0, (0, 1): 1.0}
    assert d.constant == -1.0
    n = a.neg()
    assert n.coeffs == {(0, 0): -1.0, (0, 1): -2.0}
    assert n.constant == -3.0
    s2 = a.scale(2.0)
    assert s2.coeffs == {(0, 0): 2.0, (0, 1): 4.0}
    assert s2.constant == 6.0


# --- OptModel serialization ------------------------------------------------


def test_optmodel_to_from_json_roundtrip():
    from gridcalc.opt import OptModel

    m = OptModel(
        sense="max",
        objective="B4",
        vars="A4:A5",
        constraints="D4:D6",
        bounds="A4=0:10",
    )
    encoded = m.to_json()
    assert encoded == {
        "sense": "max",
        "objective": "B4",
        "vars": "A4:A5",
        "constraints": "D4:D6",
        "bounds": "A4=0:10",
    }
    restored = OptModel.from_json(encoded)
    assert restored == m


def test_optmodel_omits_empty_bounds_in_json():
    from gridcalc.opt import OptModel

    m = OptModel(sense="min", objective="C1", vars="A1:A2", constraints="D1")
    assert "bounds" not in m.to_json()


def test_optmodel_from_json_rejects_invalid_sense():
    from gridcalc.opt import OptError, OptModel

    bad = {"sense": "maximize", "objective": "A1", "vars": "B1", "constraints": "C1"}
    with pytest.raises(OptError, match="invalid sense"):
        OptModel.from_json(bad)


def test_optmodel_from_json_rejects_missing_fields():
    from gridcalc.opt import OptError, OptModel

    with pytest.raises(OptError, match="missing required field"):
        OptModel.from_json({"sense": "max", "objective": "A1"})


# --- Grid persistence of models -------------------------------------------


def test_grid_json_roundtrip_preserves_models(tmp_path):
    from gridcalc.opt import OptModel

    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=3*A1")
    g.setcell(3, 0, "=A1<=4")
    g.models["default"] = OptModel(
        sense="max",
        objective="C1",
        vars="A1",
        constraints="D1",
    )
    g.models["with_caps"] = OptModel(
        sense="min",
        objective="C1",
        vars="A1",
        constraints="D1",
        bounds="A1=0:2",
    )
    path = tmp_path / "lp.json"
    assert g.jsonsave(str(path)) == 0

    g2 = make_grid()
    assert g2.jsonload(str(path)) == 0
    assert set(g2.models) == {"default", "with_caps"}
    assert g2.models["default"].sense == "max"
    assert g2.models["default"].objective == "C1"
    assert g2.models["with_caps"].bounds == "A1=0:2"


def test_grid_jsonload_skips_malformed_model_entries(tmp_path):
    """Malformed model entries on disk are skipped silently rather than
    aborting the workbook load. The user can re-define via :opt def to fix."""
    import json

    payload = {
        "version": 1,
        "mode": "LEGACY",
        "models": {
            "good": {
                "sense": "max",
                "objective": "B1",
                "vars": "A1",
                "constraints": "D1",
            },
            "bad_sense": {
                "sense": "maximize",
                "objective": "B1",
                "vars": "A1",
                "constraints": "D1",
            },
            "missing_field": {"sense": "max"},
        },
        "sheets": [{"name": "Sheet1", "cells": []}],
    }
    path = tmp_path / "lp.json"
    path.write_text(json.dumps(payload))
    g = make_grid()
    assert g.jsonload(str(path)) == 0
    assert set(g.models) == {"good"}


# --- Mixed-integer programming --------------------------------------------


def test_solve_mip_integer_var_snaps_to_integer():
    """Continuous LP optimum is fractional; the integer flag forces an
    integer solution out of branch-and-bound."""
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    g.setcell(2, 0, "=A1+A2")
    g.setcell(3, 0, "=A1+A2<=5.5")
    # Without integer flag, optimum is on the boundary (A1+A2 = 5.5).
    cont = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0), (0, 1)],
        constraint_cells=[(3, 0)],
        maximize=True,
    )
    assert cont.objective == pytest.approx(5.5)
    # With both as integers, optimum drops to 5 (e.g., (5,0) or (0,5)).
    mip = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0), (0, 1)],
        constraint_cells=[(3, 0)],
        maximize=True,
        integer_vars={(0, 0), (0, 1)},
    )
    assert mip.status_name == "OPTIMAL"
    assert mip.objective == pytest.approx(5.0)
    for v in (mip.values[(0, 0)], mip.values[(0, 1)]):
        assert v == pytest.approx(round(v))


def test_solve_mip_binary_var_clamped_to_zero_one():
    """Binary flag implies bounds [0,1], whatever `bounds` said."""
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    g.setcell(2, 0, "=A1+2*A2")
    g.setcell(3, 0, "=A1+A2<=1")
    result = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0), (0, 1)],
        constraint_cells=[(3, 0)],
        maximize=True,
        binary_vars={(0, 0), (0, 1)},
    )
    assert result.status_name == "OPTIMAL"
    assert result.objective == pytest.approx(2.0)
    assert result.values[(0, 0)] == pytest.approx(0.0)
    assert result.values[(0, 1)] == pytest.approx(1.0)


def test_solve_mip_rejects_non_decision_var_flag():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=A1<=5")
    with pytest.raises(OptError, match="not a decision variable"):
        solve(
            g,
            objective_cell=(2, 0),
            decision_vars=[(0, 0)],
            constraint_cells=[(3, 0)],
            integer_vars={(99, 99)},  # not a decision var
        )


def test_solve_mip_rejects_overlap_between_int_and_bin():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=A1<=5")
    with pytest.raises(OptError, match="both integer and binary"):
        solve(
            g,
            objective_cell=(2, 0),
            decision_vars=[(0, 0)],
            constraint_cells=[(3, 0)],
            integer_vars={(0, 0)},
            binary_vars={(0, 0)},
        )


def test_optmodel_to_from_json_with_integers_and_binaries():
    from gridcalc.opt import OptModel

    m = OptModel(
        sense="max",
        objective="B4",
        vars="A4:A5",
        constraints="D4:D6",
        integers="A4",
        binaries="A5",
    )
    encoded = m.to_json()
    assert encoded["integers"] == "A4"
    assert encoded["binaries"] == "A5"
    restored = OptModel.from_json(encoded)
    assert restored == m


# --- Infeasibility diagnosis (IIS) -----------------------------------------


def _conflict_grid() -> Grid:
    """Five constraints, exactly two of which contradict each other.

    D1: A1 >= 10  |  D2: A1 <= 5   <- the conflict
    D3: A2 <= 100 |  D4: A2 >= 1   |  D5: A1+A2 <= 1000   <- all irrelevant
    """
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    g.setcell(2, 0, "=A1+A2")
    g.setcell(3, 0, "=A1>=10")
    g.setcell(3, 1, "=A1<=5")
    g.setcell(3, 2, "=A2<=100")
    g.setcell(3, 3, "=A2>=1")
    g.setcell(3, 4, "=A1+A2<=1000")
    return g


_CONFLICT_CELLS = [(3, 0), (3, 1), (3, 2), (3, 3), (3, 4)]


def _solve_conflict(cells=None, **kwargs):
    return solve(
        _conflict_grid(),
        objective_cell=(2, 0),
        decision_vars=[(0, 0), (0, 1)],
        constraint_cells=_CONFLICT_CELLS if cells is None else cells,
        maximize=True,
        **kwargs,
    )


def test_diagnose_off_by_default():
    assert _solve_conflict().conflict is None


def test_diagnose_isolates_the_contradictory_pair():
    """The whole point: 5 constraints in, the 2 that actually fight come out."""
    res = _solve_conflict(diagnose=True)
    assert res.status_name == "INFEASIBLE"
    assert res.conflict == [(3, 0), (3, 1)]


def test_diagnosed_conflict_is_minimal():
    """Dropping either member must restore feasibility -- that is what makes
    the subsystem irreducible rather than merely infeasible."""
    res = _solve_conflict(diagnose=True)
    for dropped in res.conflict:
        rest = [c for c in _CONFLICT_CELLS if c != dropped]
        assert _solve_conflict(cells=rest).status_name != "INFEASIBLE"


def test_diagnosed_conflict_is_still_infeasible_on_its_own():
    """The other half of irreducibility: the reported subset must actually
    reproduce the infeasibility by itself."""
    res = _solve_conflict(diagnose=True)
    assert _solve_conflict(cells=res.conflict).status_name == "INFEASIBLE"


def test_diagnose_absent_when_feasible():
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=A1<=5")
    res = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0)],
        constraint_cells=[(3, 0)],
        maximize=True,
        diagnose=True,
    )
    assert res.status_name == "OPTIMAL"
    assert res.conflict is None


def test_diagnose_implicates_a_constraint_that_conflicts_with_bounds():
    """Bounds are held fixed by the filter, so a constraint that contradicts
    them is reported as the conflict -- the bounds are the background, the
    constraint is the thing the user can point at and change."""
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=A1<=5")
    res = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0)],
        constraint_cells=[(3, 0)],
        maximize=True,
        bounds={(0, 0): (10.0, 20.0)},  # A1 in [10,20] cannot also be <= 5
        diagnose=True,
    )
    assert res.status_name == "INFEASIBLE"
    assert res.conflict == [(3, 0)]


def test_contradictory_bounds_are_rejected_before_solving():
    """Documents why an empty conflict list is unreachable in practice: the
    only way for a constraint-free model to be infeasible is lb > ub, and
    that is refused up-front rather than solved. The empty-list branch in
    `_irreducible_conflict` is therefore defensive, not a live path."""
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    with pytest.raises(OptError, match="reversed"):
        solve(
            g,
            objective_cell=(2, 0),
            decision_vars=[(0, 0)],
            constraint_cells=[],
            maximize=True,
            bounds={(0, 0): (20.0, 10.0)},
            diagnose=True,
        )


def test_diagnose_handles_a_three_way_conflict():
    """A conflict with no contradictory pair -- only all three together are
    infeasible. A pairwise check would miss it."""
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    g.setcell(2, 0, "=A1+A2")
    g.setcell(3, 0, "=A1+A2>=10")
    g.setcell(3, 1, "=A1<=2")
    g.setcell(3, 2, "=A2<=2")
    res = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0), (0, 1)],
        constraint_cells=[(3, 0), (3, 1), (3, 2)],
        maximize=True,
        diagnose=True,
    )
    assert res.status_name == "INFEASIBLE"
    assert set(res.conflict) == {(3, 0), (3, 1), (3, 2)}


def test_diagnose_keeps_constraints_whose_removal_unbounds():
    """Dropping a constraint can make the model UNBOUNDED, which means the
    feasible region is non-empty -- so that constraint belongs to the
    conflict. Testing 'not OPTIMAL' instead of 'INFEASIBLE' would wrongly
    discard it."""
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=A1>=10")
    g.setcell(3, 1, "=A1<=5")
    res = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0)],
        constraint_cells=[(3, 0), (3, 1)],
        maximize=True,
        bounds={(0, 0): (float("-inf"), float("inf"))},
        diagnose=True,
    )
    assert res.status_name == "INFEASIBLE"
    assert set(res.conflict) == {(3, 0), (3, 1)}


# --- Bounds validation -----------------------------------------------------


def _bounded_solve(bounds):
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=A1<=5")
    return solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0)],
        constraint_cells=[(3, 0)],
        maximize=True,
        bounds=bounds,
    )


def test_reversed_bounds_raise_opterror_not_valueerror():
    """The `_opt` bridge rejects lb > ub with ValueError("lb[j] > ub[j]") --
    a column index the user never typed, in a type callers of this module do
    not expect. Reachable from `:opt ... bounds A1=20:10`."""
    with pytest.raises(OptError, match="reversed"):
        _bounded_solve({(0, 0): (20.0, 10.0)})


def test_reversed_bounds_message_names_the_cell():
    with pytest.raises(OptError) as exc:
        _bounded_solve({(0, 0): (20.0, 10.0)})
    assert "A1" in str(exc.value)
    assert "20" in str(exc.value) and "10" in str(exc.value)


def test_nan_bounds_raise_opterror():
    """`_parse_bound_value` ends in `float(s)`, so a typed `nan` parses."""
    with pytest.raises(OptError, match="not numeric"):
        _bounded_solve({(0, 0): (float("nan"), 10.0)})
    with pytest.raises(OptError, match="not numeric"):
        _bounded_solve({(0, 0): (0.0, float("nan"))})


def test_equal_bounds_are_allowed():
    """lo == hi pins a variable; only lo > hi is an error."""
    res = _bounded_solve({(0, 0): (3.0, 3.0)})
    assert res.status_name == "OPTIMAL"
    assert res.values[(0, 0)] == pytest.approx(3.0)


def test_infinite_bounds_still_accepted():
    res = _bounded_solve({(0, 0): (float("-inf"), float("inf"))})
    assert res.status_name == "OPTIMAL"


# --- Unboundedness diagnosis -----------------------------------------------


def _unbounded_solve(cells, dvars, constraints, **kwargs):
    g = make_grid()
    for c, r, t in cells:
        g.setcell(c, r, t)
    return solve(
        g,
        objective_cell=(2, 0),
        decision_vars=dvars,
        constraint_cells=constraints,
        **kwargs,
    )


_FREE_A2 = [(0, 0, "0"), (0, 1, "0"), (2, 0, "=A1+A2"), (3, 0, "=A1<=4")]


def test_unbounded_diagnosis_off_by_default():
    res = _unbounded_solve(_FREE_A2, [(0, 0), (0, 1)], [(3, 0)], maximize=True)
    assert res.status_name == "UNBOUNDED"
    assert res.unbounded is None


def test_unbounded_names_only_the_runaway_variable():
    """A1 is capped by its constraint; A2 has no upper bound. Naming both
    would be no more useful than the bare status."""
    res = _unbounded_solve(_FREE_A2, [(0, 0), (0, 1)], [(3, 0)], maximize=True, diagnose=True)
    assert res.status_name == "UNBOUNDED"
    assert res.unbounded == [(0, 1)]


def test_unbounded_reports_every_runaway():
    cells = [(0, 0, "0"), (0, 1, "0"), (2, 0, "=A1+A2"), (3, 0, "=A1>=0")]
    res = _unbounded_solve(cells, [(0, 0), (0, 1)], [(3, 0)], maximize=True, diagnose=True)
    assert set(res.unbounded) == {(0, 0), (0, 1)}


def test_unbounded_detects_downward_runaway():
    """Minimising with a free lower bound runs to -inf; the probe must test
    the direction the variable actually moved, not assume growth upward."""
    cells = [(0, 0, "0"), (2, 0, "=A1"), (3, 0, "=A1<=100")]
    res = _unbounded_solve(
        cells,
        [(0, 0)],
        [(3, 0)],
        maximize=False,
        bounds={(0, 0): (float("-inf"), float("inf"))},
        diagnose=True,
    )
    assert res.status_name == "UNBOUNDED"
    assert res.unbounded == [(0, 0)]


def test_large_but_finite_optimum_is_not_called_unbounded():
    """The false-positive guard. A legitimate optimum of 1e9 must not be
    mistaken for a runaway just because it is large -- which is exactly what
    a single-probe implementation with a fixed big-M would do."""
    cells = [(0, 0, "0"), (2, 0, "=A1"), (3, 0, "=A1<=1000000000")]
    res = _unbounded_solve(cells, [(0, 0)], [(3, 0)], maximize=True, diagnose=True)
    assert res.status_name == "OPTIMAL"
    assert res.values[(0, 0)] == pytest.approx(1e9)
    assert res.unbounded is None


def test_finite_user_bound_is_not_a_runaway():
    """A variable pinned at a large bound the user typed is at a deliberate
    limit, not running away, however big the number."""
    cells = [(0, 0, "0"), (0, 1, "0"), (2, 0, "=A1+A2"), (3, 0, "=A1<=4")]
    res = _unbounded_solve(
        cells,
        [(0, 0), (0, 1)],
        [(3, 0)],
        maximize=True,
        bounds={(0, 1): (0.0, 1e12)},
        diagnose=True,
    )
    # With A2 capped the model is bounded, so there is nothing to diagnose.
    assert res.status_name == "OPTIMAL"
    assert res.unbounded is None


def test_unbounded_diagnosis_absent_on_success():
    res = _unbounded_solve(
        [(0, 0, "0"), (2, 0, "=A1"), (3, 0, "=A1<=5")],
        [(0, 0)],
        [(3, 0)],
        maximize=True,
        diagnose=True,
    )
    assert res.status_name == "OPTIMAL"
    assert res.unbounded is None


def test_infeasible_model_gets_conflict_not_unbounded_field():
    """The two diagnoses are mutually exclusive; a failed solve is one or the
    other, never both."""
    cells = [(0, 0, "0"), (2, 0, "=A1"), (3, 0, "=A1>=10"), (3, 1, "=A1<=5")]
    res = _unbounded_solve(cells, [(0, 0)], [(3, 0), (3, 1)], maximize=True, diagnose=True)
    assert res.status_name == "INFEASIBLE"
    assert res.conflict is not None
    assert res.unbounded is None


def test_unbounded_ignores_a_variable_capped_far_above_the_model_scale():
    """Regression for a big-M implementation that was replaced.

    A1 is capped at 1e9 by `1e-9*A1 <= 1`, in a model whose other numbers are
    order 1. Any artificial box derived from the model's own magnitudes is
    smaller than A1's real limit, so a pinned-against-the-box test reports A1
    as a runaway. Solving for A1's actual bound has no threshold to misjudge.
    """
    cells = [
        (0, 0, "0"),
        (0, 1, "0"),
        (2, 0, "=A1+A2"),
        (3, 0, "=0.000001*A1<=1"),  # caps A1 at 1e6, far above the model scale
    ]
    res = _unbounded_solve(cells, [(0, 0), (0, 1)], [(3, 0)], maximize=True, diagnose=True)
    assert res.status_name == "UNBOUNDED"
    assert res.unbounded == [(0, 1)], "only A2 is unbounded; A1 is capped at 1e6"


def test_vanishing_constraint_coefficient_is_rejected_with_advice():
    """A coefficient at or below 1e-9 is numerically indistinguishable from
    zero and the solver refuses the model. The bridge names the cause rather
    than surfacing a generic solver failure."""
    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=0.000000001*A1<=1")
    with pytest.raises(ValueError, match="too small"):
        solve(
            g,
            objective_cell=(2, 0),
            decision_vars=[(0, 0)],
            constraint_cells=[(3, 0)],
            maximize=True,
            apply=False,
        )


def test_unbounded_ignores_variables_absent_from_the_objective():
    """A variable with a zero objective coefficient cannot be the cause --
    moving it does not change the objective -- so blaming it would send the
    user to the wrong cell.

    A1 is deliberately given free bounds so that the direction the probe
    would push it in *is* unbounded: without the zero-coefficient skip it
    would be reported, so this test actually exercises the rule rather than
    passing for an unrelated reason.
    """
    cells = [(0, 0, "0"), (0, 1, "0"), (2, 0, "=A2"), (3, 0, "=A1<=1000")]
    res = _unbounded_solve(
        cells,
        [(0, 0), (0, 1)],
        [(3, 0)],
        maximize=True,
        bounds={(0, 0): (float("-inf"), float("inf"))},
        diagnose=True,
    )
    assert res.status_name == "UNBOUNDED"
    assert res.unbounded == [(0, 1)], "A1 has no objective coefficient"


# --- Parametric RHS sweep --------------------------------------------------


def _sweep_wyndor(**kwargs):
    from gridcalc.opt import sweep

    defaults = dict(
        constraint=(3, 1),
        lo=6.0,
        hi=24.0,
        steps=9,
        maximize=True,
    )
    defaults.update(kwargs)
    return sweep(
        _wyndor_grid(),
        (2, 0),
        [(0, 0), (0, 1)],
        [(3, 0), (3, 1), (3, 2)],
        **defaults,
    )


def test_sweep_returns_steps_plus_one_points():
    """`steps` counts intervals, so the endpoints are both included."""
    pts = _sweep_wyndor(steps=9)
    assert len(pts) == 10
    assert pts[0].rhs == pytest.approx(6.0)
    assert pts[-1].rhs == pytest.approx(24.0)


def test_sweep_tracks_the_objective_across_the_range():
    """Wyndor: relaxing 2y<=12 is worth 1.5/unit until the 3x+2y<=18
    constraint takes over at rhs=18, after which extra capacity is free but
    worthless."""
    pts = {p.rhs: p for p in _sweep_wyndor()}
    assert pts[12.0].objective == pytest.approx(36.0)
    assert pts[18.0].objective == pytest.approx(45.0)
    assert pts[24.0].objective == pytest.approx(45.0), "objective must plateau"


def test_sweep_shadow_price_collapses_past_the_breakpoint():
    pts = {p.rhs: p for p in _sweep_wyndor()}
    assert pts[12.0].shadow_price == pytest.approx(1.5)
    assert pts[20.0].shadow_price == pytest.approx(0.0)


def test_sweep_marks_breakpoints_where_the_marginal_value_changes():
    """The point of sweeping: a single shadow price cannot show where the
    marginal value stops applying."""
    pts = _sweep_wyndor()
    marked = [p.rhs for p in pts if p.breakpoint]
    assert marked == pytest.approx([8.0, 20.0])


def test_sweep_first_point_has_no_delta_or_breakpoint():
    """Nothing to compare against; reporting 0 would imply a measurement."""
    first = _sweep_wyndor()[0]
    assert first.delta is None
    assert first.breakpoint is False


def test_sweep_delta_matches_objective_difference():
    pts = _sweep_wyndor()
    for prev, cur in zip(pts, pts[1:], strict=False):
        if cur.delta is not None:
            assert cur.delta == pytest.approx(cur.objective - prev.objective)


def test_sweep_does_not_modify_the_sheet():
    """Every point solves with apply=False; a sweep is a question, not an
    edit, and silently moving the user's decision cells would be a nasty
    surprise from a read-only-sounding command."""
    from gridcalc.opt import sweep

    g = _wyndor_grid()
    sweep(
        g,
        (2, 0),
        [(0, 0), (0, 1)],
        [(3, 0), (3, 1), (3, 2)],
        constraint=(3, 1),
        lo=6.0,
        hi=24.0,
        steps=4,
        maximize=True,
    )
    assert g.cells[0][0].val == pytest.approx(0.0)
    assert g.cells[0][1].val == pytest.approx(0.0)


def test_sweep_keeps_infeasible_points_rather_than_dropping_them():
    """Learning that a resource level is unattainable answers the question
    too, so failed points stay in the series with their status."""
    from gridcalc.opt import sweep

    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(2, 0, "=A1")
    g.setcell(3, 0, "=A1>=10")
    g.setcell(3, 1, "=A1<=5")  # swept; below 10 the model is infeasible
    pts = sweep(
        g,
        (2, 0),
        [(0, 0)],
        [(3, 0), (3, 1)],
        constraint=(3, 1),
        lo=2.0,
        hi=20.0,
        steps=2,
        maximize=True,
    )
    assert [p.status_name for p in pts] == ["INFEASIBLE", "OPTIMAL", "OPTIMAL"]
    assert math.isnan(pts[0].objective)


def test_sweep_rejects_a_cell_that_is_not_a_constraint():
    with pytest.raises(OptError, match="not one of the constraint cells"):
        _sweep_wyndor(constraint=(0, 0))


def test_sweep_rejects_a_reversed_range():
    with pytest.raises(OptError, match="reversed"):
        _sweep_wyndor(lo=20.0, hi=5.0)


def test_sweep_rejects_zero_steps():
    with pytest.raises(OptError, match="at least 1 step"):
        _sweep_wyndor(steps=0)


def test_rhs_override_does_not_touch_the_sheet():
    """The primitive the sweep is built on."""
    g = _wyndor_grid()
    res = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0), (0, 1)],
        constraint_cells=[(3, 0), (3, 1), (3, 2)],
        maximize=True,
        apply=False,
        rhs_override={(3, 1): 24.0},
    )
    assert res.objective == pytest.approx(45.0)
    assert g.cells[3][1].text == "=2*A2<=12", "the constraint formula must be unchanged"


def test_rhs_override_rejects_a_non_constraint_cell():
    with pytest.raises(OptError, match="not a constraint cell"):
        solve(
            _wyndor_grid(),
            objective_cell=(2, 0),
            decision_vars=[(0, 0), (0, 1)],
            constraint_cells=[(3, 0), (3, 1), (3, 2)],
            maximize=True,
            apply=False,
            rhs_override={(0, 0): 5.0},
        )


# --- Model inference from a selection --------------------------------------


def _block_grid() -> Grid:
    """Wyndor laid out spatially, as a user would type it.

        A          B              C
    1   "Product"
    2   0          =3*A2+5*A3     =A2<=4
    3   0                         =2*A3<=12
    4                             =3*A2+2*A3<=18
    """
    g = make_grid()
    g.setcell(0, 0, '"Product')
    g.setcell(0, 1, "0")
    g.setcell(0, 2, "0")
    g.setcell(1, 1, "=3*A2+5*A3")
    g.setcell(2, 1, "=A2<=4")
    g.setcell(2, 2, "=2*A3<=12")
    g.setcell(2, 3, "=3*A2+2*A3<=18")
    return g


def test_infer_classifies_the_block():
    from gridcalc.opt import infer_model

    m = infer_model(_block_grid(), 0, 0, 2, 3)
    assert m.objective == (1, 1)
    assert m.decision_vars == [(0, 1), (0, 2)]
    assert m.constraint_cells == [(2, 1), (2, 2), (2, 3)]


def test_infer_ignores_labels_and_blanks():
    """A selected rectangle is mostly whitespace. Promoting every gap to a
    decision variable would build a model the user never described."""
    from gridcalc.opt import infer_model

    g = _block_grid()
    g.setcell(1, 0, '"Objective')
    g.setcell(2, 0, '"Limits')
    m = infer_model(g, 0, 0, 2, 3)
    assert m.decision_vars == [(0, 1), (0, 2)], "labels and blanks stay out"


def test_inferred_model_solves_to_the_same_optimum_as_a_typed_one():
    from gridcalc.opt import infer_model

    g = _block_grid()
    m = infer_model(g, 0, 0, 2, 3)
    res = solve(
        g,
        objective_cell=m.objective,
        decision_vars=m.decision_vars,
        constraint_cells=m.constraint_cells,
        maximize=True,
    )
    assert res.status_name == "OPTIMAL"
    assert res.objective == pytest.approx(36.0)


def test_infer_requires_exactly_one_objective():
    from gridcalc.opt import infer_model

    g = _block_grid()
    g.setcell(1, 2, "=A2+A3")  # a second non-comparison formula
    with pytest.raises(OptError, match="candidate objective"):
        infer_model(g, 0, 0, 2, 3)


def test_infer_error_names_the_candidates():
    from gridcalc.opt import infer_model

    g = _block_grid()
    g.setcell(1, 2, "=A2+A3")
    with pytest.raises(OptError) as exc:
        infer_model(g, 0, 0, 2, 3)
    assert "B2" in str(exc.value) and "B3" in str(exc.value)


def test_infer_requires_an_objective():
    from gridcalc.opt import infer_model

    g = _block_grid()
    with pytest.raises(OptError, match="no objective"):
        infer_model(g, 0, 0, 0, 3)  # column A only: numbers, no formula


def test_infer_requires_decision_cells():
    from gridcalc.opt import infer_model

    g = _block_grid()
    with pytest.raises(OptError, match="no numeric decision cells"):
        infer_model(g, 1, 0, 2, 3)  # columns B..C: formulas only


def test_infer_requires_constraints():
    from gridcalc.opt import infer_model

    g = _block_grid()
    with pytest.raises(OptError, match="no constraint formulas"):
        infer_model(g, 0, 0, 1, 3)  # columns A..B: objective + vars, no comparisons


def test_infer_rejects_ne_comparison():
    from gridcalc.opt import infer_model

    g = _block_grid()
    g.setcell(2, 0, "=A2<>3")
    with pytest.raises(OptError, match="<>"):
        infer_model(g, 0, 0, 2, 3)


def test_infer_orders_cells_like_a_typed_range():
    """Column-major within the block, matching `_parse_cells` expansion, so
    an inferred model and a typed one give the same variable ordering."""
    from gridcalc.opt import infer_model

    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(1, 0, "0")
    g.setcell(0, 1, "0")
    g.setcell(1, 1, "0")
    g.setcell(2, 0, "=A1+B1+A2+B2")
    g.setcell(3, 0, "=A1<=1")
    m = infer_model(g, 0, 0, 3, 1)
    assert m.decision_vars == [(0, 0), (0, 1), (1, 0), (1, 1)]


# --- Quadratic objectives --------------------------------------------------


def _quad_solve(cells, dvars, cons, **kw):
    g = make_grid()
    for c, r, t in cells:
        g.setcell(c, r, t)
    return solve(
        g, objective_cell=(2, 0), decision_vars=dvars, constraint_cells=cons, apply=False, **kw
    )


def test_quadratic_minimum_matches_the_analytic_optimum():
    """min (x-3)^2 over x in [0,10] has its optimum at x=3, f=0."""
    res = _quad_solve(
        [(0, 0, "0"), (2, 0, "=(A1-3)*(A1-3)"), (3, 0, "=A1<=10")],
        [(0, 0)],
        [(3, 0)],
        maximize=False,
        bounds={(0, 0): (0.0, 10.0)},
    )
    assert res.status_name == "OPTIMAL"
    assert res.quadratic is True
    assert res.values[(0, 0)] == pytest.approx(3.0, abs=1e-6)
    assert res.objective == pytest.approx(0.0, abs=1e-9)


def test_quadratic_two_variables():
    """min x^2 + y^2 s.t. x + y >= 10 splits evenly: x=y=5, f=50."""
    res = _quad_solve(
        [(0, 0, "0"), (0, 1, "0"), (2, 0, "=A1*A1+A2*A2"), (3, 0, "=A1+A2>=10")],
        [(0, 0), (0, 1)],
        [(3, 0)],
        maximize=False,
        bounds={(0, 0): (0.0, 10.0), (0, 1): (0.0, 10.0)},
    )
    assert res.values[(0, 0)] == pytest.approx(5.0, abs=1e-6)
    assert res.values[(0, 1)] == pytest.approx(5.0, abs=1e-6)
    assert res.objective == pytest.approx(50.0, abs=1e-6)


def test_quadratic_maximum_of_a_concave_objective():
    res = _quad_solve(
        [(0, 0, "0"), (2, 0, "=5-(A1-2)^2"), (3, 0, "=A1<=9")],
        [(0, 0)],
        [(3, 0)],
        maximize=True,
        bounds={(0, 0): (0.0, 9.0)},
    )
    assert res.values[(0, 0)] == pytest.approx(2.0, abs=1e-6)
    assert res.objective == pytest.approx(5.0, abs=1e-6)


def test_reported_objective_is_recomputed_from_the_formula():
    """The reported objective is evaluated from the user's own cell rather
    than taken from the solver, so the number stays tied to what the sheet
    says."""
    res = _quad_solve(
        [(0, 0, "0"), (2, 0, "=(A1-3)*(A1-3)"), (3, 0, "=A1<=10")],
        [(0, 0)],
        [(3, 0)],
        maximize=False,
        bounds={(0, 0): (0.0, 10.0)},
    )
    x = res.values[(0, 0)]
    assert res.objective == pytest.approx((x - 3.0) ** 2, abs=1e-9)
    assert res.objective >= 0.0, "a squared term cannot evaluate negative"


def test_linear_objective_is_not_flagged_quadratic():
    res = _solve_wyndor()
    assert res.quadratic is False


def test_squares_helper_still_rejects_cross_terms():
    """`QuadForm.squares()` is no longer on the solve path -- the solver takes
    a full Hessian -- but it remains the accessor for callers that genuinely
    need a separable view, so its contract is kept."""
    from gridcalc.formula.parser import parse

    g = make_grid()
    g.setcell(0, 0, "0")
    g.setcell(0, 1, "0")
    form = extract_quadratic(parse("=A1*A2"), {(0, 0), (0, 1)}, g)
    with pytest.raises(NotQuadratic, match="couples A1 and A2"):
        form.squares()


def test_maximising_a_convex_objective_is_refused():
    """The relaxation only converges when the objective is convex for a
    minimisation (or concave for a maximisation). With the wrong sign the
    solver would return a confident answer to a different problem."""
    with pytest.raises(NotQuadratic, match="not concave"):
        _quad_solve(
            [(0, 0, "0"), (2, 0, "=A1*A1"), (3, 0, "=A1<=10")],
            [(0, 0)],
            [(3, 0)],
            maximize=True,
            bounds={(0, 0): (0.0, 10.0)},
        )


def test_minimising_a_concave_objective_is_refused():
    with pytest.raises(NotQuadratic, match="not convex"):
        _quad_solve(
            [(0, 0, "0"), (2, 0, "=0-A1*A1"), (3, 0, "=A1<=10")],
            [(0, 0)],
            [(3, 0)],
            maximize=False,
            bounds={(0, 0): (0.0, 10.0)},
        )


def test_cubic_objective_is_refused():
    with pytest.raises(NotQuadratic, match="degree 3"):
        _quad_solve(
            [(0, 0, "0"), (2, 0, "=A1*A1*A1"), (3, 0, "=A1<=10")],
            [(0, 0)],
            [(3, 0)],
            maximize=False,
            bounds={(0, 0): (0.0, 10.0)},
        )


def test_quadratic_withholds_sensitivity_and_diagnosis():
    """The relaxation's duals belong to the approximating LP and its extra
    rows are not user constraints, so both analyses are suppressed -- the
    same call made for MIPs."""
    res = _quad_solve(
        [(0, 0, "0"), (2, 0, "=(A1-3)*(A1-3)"), (3, 0, "=A1<=10")],
        [(0, 0)],
        [(3, 0)],
        maximize=False,
        bounds={(0, 0): (0.0, 10.0)},
        sensitivity=True,
        diagnose=True,
    )
    assert res.sensitivity is None
    assert res.conflict is None


def test_quadratic_applies_to_the_sheet_like_an_lp():
    g = make_grid()
    for c, r, t in [(0, 0, "0"), (2, 0, "=(A1-3)*(A1-3)"), (3, 0, "=A1<=10")]:
        g.setcell(c, r, t)
    res = solve(
        g,
        objective_cell=(2, 0),
        decision_vars=[(0, 0)],
        constraint_cells=[(3, 0)],
        maximize=False,
        bounds={(0, 0): (0.0, 10.0)},
    )
    assert res.applied is True
    assert g.cells[0][0].val == pytest.approx(3.0, abs=1e-6)
