"""Tests for one-dimensional goal-seek (gridcalc.goalseek)."""

from __future__ import annotations

import pytest

from gridcalc.engine import Grid
from gridcalc.goalseek import GoalSeekError, seek


def _grid_with(formula: str, var_start: float = 0.0) -> Grid:
    """Build a 2-cell grid: A1 holds the variable, B1 the formula in A1."""
    g = Grid()
    g.setcell(0, 0, str(var_start))
    g.setcell(1, 0, formula)
    return g


def test_linear_goal_seek():
    """Smallest possible case: f(x) = 2x + 3, target = 11, expected x = 4."""
    g = _grid_with("=2*A1+3")
    result = seek(g, formula_cell=(1, 0), target=11.0, var_cell=(0, 0))
    assert result.converged
    assert result.var_value == pytest.approx(4.0)
    assert result.formula_value == pytest.approx(11.0)
    # The grid is left in the solved state.
    assert g.cells[0][0].val == pytest.approx(4.0)
    assert g.cells[1][0].val == pytest.approx(11.0)
    assert result.applied is True


def test_quadratic_finds_positive_root_from_positive_start():
    """f(x) = x^2 - 16; starting at A1=1, the auto-bracket walks right and
    finds the +4 root (not -4)."""
    g = _grid_with("=A1*A1", var_start=1.0)
    result = seek(g, formula_cell=(1, 0), target=16.0, var_cell=(0, 0))
    assert result.converged
    assert result.var_value == pytest.approx(4.0)


def test_explicit_bracket_for_negative_root():
    """Force the -4 root via an explicit bracket."""
    g = _grid_with("=A1*A1", var_start=0.0)
    result = seek(
        g,
        formula_cell=(1, 0),
        target=16.0,
        var_cell=(0, 0),
        lo=-10.0,
        hi=-0.1,
    )
    assert result.converged
    assert result.var_value == pytest.approx(-4.0)


def test_apply_false_leaves_var_untouched():
    g = _grid_with("=2*A1+3", var_start=99.0)
    result = seek(
        g,
        formula_cell=(1, 0),
        target=11.0,
        var_cell=(0, 0),
        apply=False,
    )
    assert result.converged
    assert result.var_value == pytest.approx(4.0)
    # Var cell was restored to its original 99.0.
    assert g.cells[0][0].val == pytest.approx(99.0)
    assert result.applied is False


def test_rejects_formula_in_var_cell():
    """Goal-seek must not silently overwrite a live computation."""
    g = Grid()
    g.setcell(0, 0, "=2+3")  # A1 is a formula
    g.setcell(1, 0, "=A1*2")
    with pytest.raises(GoalSeekError, match="formula"):
        seek(g, formula_cell=(1, 0), target=10.0, var_cell=(0, 0))


def test_rejects_non_formula_target_cell():
    g = Grid()
    g.setcell(0, 0, "1")
    g.setcell(1, 0, "5")  # B1 is a value, not a formula
    with pytest.raises(GoalSeekError, match="formula"):
        seek(g, formula_cell=(1, 0), target=10.0, var_cell=(0, 0))


def test_rejects_var_not_influencing_target():
    """If B1 doesn't depend on A1, auto-bracket can't find a sign change."""
    g = Grid()
    g.setcell(0, 0, "0")  # A1 unused
    g.setcell(2, 0, "1")  # C1 = 1 (constant)
    g.setcell(1, 0, "=C1*2")  # B1 depends on C1 only, not A1
    with pytest.raises(GoalSeekError):
        seek(g, formula_cell=(1, 0), target=99.0, var_cell=(0, 0))


def test_rejects_empty_bracket():
    g = _grid_with("=2*A1+3")
    with pytest.raises(GoalSeekError, match="bracket is empty"):
        seek(
            g,
            formula_cell=(1, 0),
            target=11.0,
            var_cell=(0, 0),
            lo=5.0,
            hi=5.0,
        )


def test_rejects_bracket_without_sign_change():
    """A bracket where both endpoints give the same-sign residual must fail
    explicitly rather than return an arbitrary midpoint."""
    g = _grid_with("=2*A1+3")
    with pytest.raises(GoalSeekError, match="sign"):
        seek(
            g,
            formula_cell=(1, 0),
            target=11.0,
            var_cell=(0, 0),
            lo=10.0,
            hi=20.0,  # f(lo)=20, f(hi)=40; both > target
        )


def test_starting_at_root_returns_immediately():
    """If the variable's current value already satisfies the target, the
    auto-bracket sees f(x0)==0 and we return without expensive search."""
    g = _grid_with("=2*A1+3", var_start=4.0)  # already at the solution
    result = seek(g, formula_cell=(1, 0), target=11.0, var_cell=(0, 0))
    assert result.converged
    assert result.var_value == pytest.approx(4.0)


def test_failure_path_restores_var_cell():
    """When an error is raised mid-search, the variable cell must be left
    exactly as it was on entry -- no silent partial state."""
    g = Grid()
    g.setcell(0, 0, "7")
    g.setcell(2, 0, "1")
    g.setcell(1, 0, "=C1*2")  # not dependent on A1
    with pytest.raises(GoalSeekError):
        seek(g, formula_cell=(1, 0), target=99.0, var_cell=(0, 0))
    # A1 must still be 7.
    assert g.cells[0][0].val == pytest.approx(7.0)


def test_iterations_counted():
    """Bisection on a smooth linear problem should converge in a few iters
    -- not zero (would mean we returned the bracket midpoint untested) and
    not the cap."""
    g = _grid_with("=2*A1+3")
    result = seek(g, formula_cell=(1, 0), target=11.0, var_cell=(0, 0))
    assert 1 <= result.iterations < 100
