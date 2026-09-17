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


def test_empty_variable_cell_is_created():
    g = Grid()
    g.setcell(1, 0, "=A1*2")
    result = seek(g, formula_cell=(1, 0), target=10.0, var_cell=(0, 0))
    assert result.converged and result.applied
    assert g.cells[0][0].val == pytest.approx(5.0)
    assert g.cells[1][0].val == pytest.approx(10.0)


def test_empty_variable_cell_stays_absent_without_apply():
    g = Grid()
    g.setcell(1, 0, "=A1*2")
    seek(g, formula_cell=(1, 0), target=10.0, var_cell=(0, 0), apply=False)
    assert g.cell(0, 0) is None
    assert Grid().cells[0][0].type == 0  # the shared placeholder is untouched


def test_small_scale_formula_converges_to_the_true_root():
    """An absolute residual tolerance of 1e-9 stopped at A1=124 here."""
    g = _grid_with("=A1*1E-9")
    result = seek(g, formula_cell=(1, 0), target=1.234567e-7, var_cell=(0, 0))
    assert result.converged
    assert result.var_value == pytest.approx(123.4567, rel=1e-8)


def test_large_scale_formula_reports_converged():
    g = _grid_with("=A1*1E9+0.1")
    result = seek(g, formula_cell=(1, 0), target=1e12, var_cell=(0, 0))
    assert result.converged
    assert result.var_value == pytest.approx((1e12 - 0.1) / 1e9, rel=1e-9)


def test_discontinuity_is_not_reported_converged():
    g = Grid()
    g.setcell(0, 0, "0")
    g.setcell(1, 0, "=1 if A1>=5 else -1")
    result = seek(g, formula_cell=(1, 0), target=0.0, var_cell=(0, 0))
    assert not result.converged
    assert g.cells[0][0].val == 0.0


def test_start_at_a_repeated_root_returns_converged():
    g = _grid_with("=(A1-2)*(A1-2)", var_start=2.0)
    result = seek(g, formula_cell=(1, 0), target=0.0, var_cell=(0, 0))
    assert result.converged
    assert result.var_value == 2.0
    assert result.iterations == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target": float("nan")},
        {"target": 10.0, "lo": float("-inf"), "hi": float("inf")},
        {"target": 10.0, "lo": 0.0, "hi": float("inf")},
    ],
)
def test_non_finite_target_or_bracket_is_refused(kwargs):
    g = _grid_with("=2*A1", var_start=1.0)
    with pytest.raises(GoalSeekError):
        seek(g, formula_cell=(1, 0), var_cell=(0, 0), **kwargs)
    assert g.cells[0][0].val == 1.0


def test_applied_value_carries_source_text():
    """Copy, edit and replicate read `text`; a stale one showed '1' for 2.5."""
    g = _grid_with("=A1*2", var_start=1.0)
    seek(g, formula_cell=(1, 0), target=5.0, var_cell=(0, 0))
    assert g.cells[0][0].text == "2.5"
    assert g.cells[0][0].val == 2.5


def test_unapplied_seek_keeps_source_text():
    g = Grid()
    g.setcell(0, 0, "1")
    g.setcell(1, 0, "=A1*2")
    seek(g, formula_cell=(1, 0), target=5.0, var_cell=(0, 0), apply=False)
    assert g.cells[0][0].text == "1"
    assert g.cells[0][0].val == 1.0


@pytest.mark.parametrize(
    "args",
    [
        "B1 = nan by A1",
        "B1 = inf by A1",
        "B1 = 10 by A1 in -inf:inf",
        "B1 = 10 by A1 in 0:inf",
        "B1 = 10 by A1 in nan:1",
    ],
)
def test_parse_goal_rejects_non_finite_numbers(args):
    from gridcalc.optspec import parse_goal

    with pytest.raises(ValueError):
        parse_goal(args)


def test_parse_goal_accepts_a_finite_bracket():
    from gridcalc.optspec import parse_goal

    spec = parse_goal("B1 = 10 by A1 in -5:1e3")
    assert (spec.lo, spec.hi, spec.target) == (-5.0, 1000.0, 10.0)


def _excel_grid() -> Grid:
    from gridcalc.engine import Mode

    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    return g


def test_goal_seek_follows_a_chain_through_another_sheet():
    g = _excel_grid()
    g.add_sheet("Other")
    g.setcell(0, 0, "1")  # Sheet1!A1, the variable
    g.set_active("Other")
    g.setcell(0, 0, "=Sheet1!A1*Sheet1!A1")
    g.set_active("Sheet1")
    g.setcell(1, 0, "=Other!A1+1")
    g.recalc()
    result = seek(g, formula_cell=(1, 0), target=10.0, var_cell=(0, 0))
    assert result.converged
    assert result.var_value == pytest.approx(3.0)
    assert g.sheets[1]._cells[(0, 0)].val == pytest.approx(9.0)


def test_goal_seek_recalcs_only_the_variables_dependants(monkeypatch):
    g = _excel_grid()
    g.setcells_bulk([(0, 0, "1"), (1, 0, "=A1^3+A1"), (2, 0, "=SIN(1)")])
    g.recalc()
    full = []
    real = g.recalc

    def spy(dirty=None):
        if dirty is None:
            full.append(1)
        real(dirty)

    monkeypatch.setattr(g, "recalc", spy)
    result = seek(g, formula_cell=(1, 0), target=50.0, var_cell=(0, 0))
    assert result.converged and result.iterations > 10
    assert full == []  # no whole-workbook pass per iteration
