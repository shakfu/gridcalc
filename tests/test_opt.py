"""Tests for sheet-level linear optimization (gridcalc.opt)."""

from __future__ import annotations

import math

import pytest

from gridcalc.engine import Grid
from gridcalc.formula.parser import parse
from gridcalc.opt import (
    LinearForm,
    NotLinear,
    OptError,
    extract_constraint,
    extract_linear,
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
    reported objective even though lp_solve never sees them."""
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
    """Continuous LP optimum is fractional; integer flag forces an integer
    solution from lp_solve's branch-and-bound."""
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
    """Binary flag implies bounds [0,1]; lp_solve does the clamping."""
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
