"""One-dimensional goal-seek over a Grid.

Find a value for a *variable cell* such that a *formula cell* evaluates to a
given target value. Useful for spreadsheet what-if of the form "what input
makes this output equal X?" -- the most common form of Solver use in Excel
and the only one that doesn't need an LP.

Algorithm: bisection with an auto-bracket pre-step. Bisection is slow
asymptotically but at spreadsheet scale a few dozen recalcs run in a few
milliseconds; correctness, simplicity, and graceful failure on non-monotonic
or noisy formulas are worth more than the iteration count. Brent's method
would converge faster on smooth f but adds edge cases (oscillation, the
mflag dance, slow-progress detection) that aren't justified here.

The variable cell must hold a value, not a formula (analogous to decision
cells in `opt.py`): goal-seek will overwrite it on success, and ``apply=False``
restores it. The formula cell must contain a formula; it should depend on
the variable cell (otherwise f doesn't change with x and bracketing fails).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .engine import EMPTY, FORMULA, NUM, Grid

CellKey = tuple[int, int]


class GoalSeekError(Exception):
    """User-facing failure: bad cell selection, no sign change, non-converged."""


@dataclass
class SeekResult:
    converged: bool
    iterations: int
    var_value: float  # the input value at termination
    formula_value: float  # f(var_value) -- the actual output reached
    residual: float  # formula_value - target
    applied: bool  # True if var_cell was written


def seek(
    grid: Grid,
    formula_cell: CellKey,
    target: float,
    var_cell: CellKey,
    *,
    lo: float | None = None,
    hi: float | None = None,
    tol: float = 1e-9,
    max_iter: int = 100,
    apply: bool = True,
) -> SeekResult:
    """Adjust ``var_cell`` so that ``formula_cell`` evaluates to ``target``.

    If both ``lo`` and ``hi`` are given they're used as the search bracket;
    otherwise the algorithm auto-brackets outward from the variable cell's
    current value.

    On success (residual within tolerance) the variable cell is left holding
    the solved value and the rest of the grid is recalculated to reflect it;
    callers can roll back via undo (the TUI wrapper records a grid snapshot).
    ``apply=False`` runs the search without leaving the grid mutated.
    """
    fc, fr = formula_cell
    vc, vr = var_cell
    fcell = grid.cells[fc][fr]
    vcell = grid.cells[vc][vr]

    if fcell.type != FORMULA:
        raise GoalSeekError("target cell must contain a formula")
    if vcell.type == FORMULA:
        raise GoalSeekError(
            "variable cell must hold a value (not a formula); "
            "goal-seek would otherwise overwrite a live computation"
        )
    if vcell.type not in (EMPTY, NUM):
        raise GoalSeekError("variable cell must be numeric or empty")

    orig_type = vcell.type
    orig_val = vcell.val

    def f(x: float) -> float:
        """Set var to x, recalc, return formula_value - target."""
        vcell.type = NUM
        vcell.val = x
        grid.recalc()
        v = fcell.val
        if not isinstance(v, (int, float)) or v != v:  # NaN-safe
            raise GoalSeekError(
                f"target cell evaluated to non-numeric at var={x!r}; "
                "ensure the formula depends only on numeric inputs"
            )
        return float(v) - target

    try:
        x_start = float(orig_val) if orig_type == NUM else 0.0
        if lo is not None and hi is not None:
            if lo >= hi:
                raise GoalSeekError(f"bracket is empty: lo={lo} >= hi={hi}")
            bracket = (lo, hi)
        else:
            bracket = _auto_bracket(f, x_start)

        x_solved, iters = _bisect(f, bracket[0], bracket[1], tol, max_iter)
        # Re-evaluate at the solution to capture the final formula value
        # and leave the grid in the solved state (or restore below).
        residual = f(x_solved)
        formula_value = residual + target
        converged = abs(residual) <= max(tol * 1e3, tol)
        applied = False

        if apply and converged:
            applied = True  # grid is already in the solved state
        else:
            vcell.type = orig_type
            vcell.val = orig_val
            grid.recalc()

        return SeekResult(
            converged=converged,
            iterations=iters,
            var_value=x_solved,
            formula_value=formula_value,
            residual=residual,
            applied=applied,
        )
    except Exception:
        # Any failure path leaves the grid as it was before the search.
        vcell.type = orig_type
        vcell.val = orig_val
        grid.recalc()
        raise


# --- Internal helpers -------------------------------------------------------


def _auto_bracket(
    f: Callable[[float], float],
    x0: float,
    *,
    max_expand: int = 60,
) -> tuple[float, float]:
    """Expand outward from ``x0`` until f changes sign.

    Doubles the step each iteration and tries both directions before
    widening, so monotone f near x0 is found in O(log range) evaluations.
    Each evaluation triggers a full grid recalc, so the cap is conservative.
    """
    f0 = f(x0)
    if f0 == 0.0:
        # Already at a root. Return a tiny bracket around x0 so bisection
        # has something to chew on and terminates immediately.
        return (x0 - 1.0, x0 + 1.0)

    step = max(abs(x0) * 0.1, 1.0)
    for _ in range(max_expand):
        a, b = x0 - step, x0 + step
        fa = f(a)
        if fa * f0 < 0.0:
            return (a, x0)
        fb = f(b)
        if fb * f0 < 0.0:
            return (x0, b)
        step *= 2.0

    raise GoalSeekError(
        "could not auto-bracket the root; provide an explicit search interval with `in <lo>:<hi>`"
    )


def _bisect(
    f: Callable[[float], float],
    a: float,
    b: float,
    tol: float,
    max_iter: int,
) -> tuple[float, int]:
    """Standard bisection. Assumes f(a) and f(b) have opposite signs."""
    fa = f(a)
    fb = f(b)
    if fa == 0.0:
        return a, 0
    if fb == 0.0:
        return b, 0
    if fa * fb > 0.0:
        raise GoalSeekError(
            "f does not change sign across the provided bracket; "
            "the variable may not influence the target cell, or the "
            "target is unreachable within the bracket"
        )

    for i in range(1, max_iter + 1):
        m = 0.5 * (a + b)
        fm = f(m)
        if abs(fm) < tol or 0.5 * (b - a) < tol:
            return m, i
        if fa * fm < 0.0:
            b, fb = m, fm
        else:
            a, fa = m, fm
    return 0.5 * (a + b), max_iter
