"""Solver-report formatting for the TUI -- pure functions, no curses.

Renders optimizer output (sensitivity, infeasibility/unboundedness
diagnoses, parametric sweeps) into `list[str]` for the pager or one-line
status strings. This is TUI-shaped presentation -- a GUI would render the
same data as a table widget -- so it stays under `tui/` rather than moving to
the frontend-neutral `gridcalc.display`, which owns cell formatting
(`fmtcell` / `cell_clip_value`).
"""

from __future__ import annotations

import math
from collections.abc import Callable

from ..opt import Sensitivity, SweepPoint


def _sens_num(v: float) -> str:
    """Render a sensitivity number, showing infinities as words.

    A ranging value is unbounded on at least one side for any non-binding
    constraint, and a raw `1e+30` in a report column is noise.
    """
    if math.isinf(v):
        return "inf" if v > 0 else "-inf"
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return f"{v:.6g}"


def format_sensitivity(sens: Sensitivity, cellname: Callable[[int, int], str]) -> list[str]:
    """Render a solver sensitivity report as plain lines for the pager.

    Two tables, mirroring what an operator actually asks after a solve:
    which inputs would change the answer (variables), and which limits are
    actually costing something (constraints). Shadow price leads the
    constraint table because it is the number the question "what should I
    buy more of?" resolves to.

    Pure and curses-free so the layout can be tested directly.

    Every line is kept under `MAX_WIDTH` so the pager's two-space indent
    still fits an 80-column terminal; the pager truncates rather than wraps,
    and a silently clipped number is worse than a narrow column. The binding
    flag is a leading marker rather than a trailing word for the same reason
    -- a trailing label is the first thing lost to truncation.
    """
    lines: list[str] = []
    w = 10  # numeric column width

    lines.append("Variable cells")
    lines.append(
        f"   {'cell':<5}{'value':>{w}}{'reduced':>{w}}{'obj coef':>{w}}"
        f"{'coef from':>{w}}{'coef till':>{w}}"
    )
    for v in sens.variables:
        lines.append(
            f"   {cellname(*v.cell):<5}{_sens_num(v.value):>{w}}"
            f"{_sens_num(v.reduced_cost):>{w}}{_sens_num(v.obj_coef):>{w}}"
            f"{_sens_num(v.obj_from):>{w}}{_sens_num(v.obj_till):>{w}}"
        )

    lines.append("")
    lines.append("Constraints   (* = binding)")
    lines.append(
        f"   {'cell':<5}{'shadow':>{w}}{'rhs':>{w}}{'activity':>{w}}"
        f"{'slack':>{w}}{'rhs from':>{w}}{'rhs till':>{w}}"
    )
    for c in sens.constraints:
        mark = "*" if c.binding else " "
        lines.append(
            f" {mark} {cellname(*c.cell):<5}{_sens_num(c.shadow_price):>{w}}"
            f"{_sens_num(c.rhs):>{w}}{_sens_num(c.activity):>{w}}"
            f"{_sens_num(c.slack):>{w}}{_sens_num(c.rhs_from):>{w}}"
            f"{_sens_num(c.rhs_till):>{w}}"
        )

    lines.append("")
    lines.append("Shadow price is the objective gain per unit of extra")
    lines.append("right-hand side, valid only within rhs from..till.")
    return lines


def format_conflict(
    conflict: list[tuple[int, int]],
    total: int,
    cellname: Callable[[int, int], str],
    max_cells: int = 8,
) -> str:
    """One-line summary of an infeasibility diagnosis for the status bar.

    The empty case is defensive -- `lb > ub` is rejected before solving, so a
    model with no implicated constraint is not currently reachable. Handled
    anyway so the branch degrades to a useful hint rather than an empty
    "conflict: " if that ever changes.

    Long lists are truncated with a count, since the status bar is one line
    and the leading cells are the useful part.
    """
    if not conflict:
        return "no constraint conflict -- check variable bounds"
    names = _cell_list(conflict, cellname, max_cells)
    return f"conflict: {names} ({len(conflict)} of {total} constraints)"


def _cell_list(
    cells: list[tuple[int, int]],
    cellname: Callable[[int, int], str],
    max_cells: int,
) -> str:
    """Comma-joined cell names, truncated with a count past `max_cells`.

    The status bar is one line; the leading cells are the useful part and a
    silent cut would misrepresent how many were found.
    """
    names = [cellname(c, r) for c, r in cells]
    if len(names) <= max_cells:
        return ", ".join(names)
    return f"{', '.join(names[:max_cells])}, +{len(names) - max_cells} more"


def format_unbounded(
    unbounded: list[tuple[int, int]],
    cellname: Callable[[int, int], str],
    max_cells: int = 8,
) -> str:
    """One-line summary of an unboundedness diagnosis for the status bar.

    An empty list is a real outcome here, unlike in `format_conflict`: the
    probe declines to guess when its bounded re-solves do not converge, so
    the message says the model is unbounded without naming a culprit rather
    than inventing one.
    """
    if not unbounded:
        return "could not identify the unbounded variable"
    names = _cell_list(unbounded, cellname, max_cells)
    remedy = (
        "add upper bounds or constraints"
        if len(unbounded) > 1
        else "add an upper bound or a constraint"
    )
    return f"unbounded: {names} -- {remedy}"


def format_sweep(
    points: list[SweepPoint],
    constraint: str,
    cw: int = 10,
) -> list[str]:
    """Render a parametric RHS sweep as plain lines for the pager.

    The column that matters is `shadow`, and the marker beside it: while the
    marginal value holds steady another unit is worth buying, and where it
    drops is the point past which it is not. `delta` is shown alongside
    because it is the same information in absolute terms, which is usually
    how the question was asked ("what do I get for the next 5 units").

    Failed points are kept rather than dropped -- finding out that a
    right-hand side is unattainable answers the question too.
    """
    lines: list[str] = []
    span = f" from {_sens_num(points[0].rhs)} to {_sens_num(points[-1].rhs)}" if points else ""
    lines.append(f"{constraint} right-hand side{span}   (* = marginal value changed)")
    lines.append(f"   {'rhs':>{cw}}{'objective':>{cw}}{'delta':>{cw}}{'shadow':>{cw}}  status")
    for p in points:
        mark = "*" if p.breakpoint else " "
        solved = p.status_name in ("OPTIMAL", "SUBOPTIMAL")
        obj = _sens_num(p.objective) if solved else "--"
        delta = _sens_num(p.delta) if p.delta is not None else "--"
        shadow = _sens_num(p.shadow_price) if p.shadow_price is not None else "--"
        status = "" if p.status_name == "OPTIMAL" else f"  {p.status_name}"
        lines.append(
            f" {mark} {_sens_num(p.rhs):>{cw}}{obj:>{cw}}{delta:>{cw}}{shadow:>{cw}}{status}"
        )

    prices = [p.shadow_price for p in points if p.shadow_price is not None]
    lines.append("")
    if prices and len(set(prices)) == 1:
        lines.append("Marginal value is constant across this range -- widen it")
        lines.append("to find where the value changes.")
    else:
        lines.append("Marginal value changes at the starred rows: buying past")
        lines.append("one is worth less per unit than buying up to it.")
    return lines


# Column headers for the written sensitivity block. Kept beside the writer
# so the layout is documented in one place -- downstream formulas reference
# these cells by position, so the layout is a compatibility surface.
SENS_VAR_HEADERS = ("cell", "value", "reduced", "obj coef", "coef from", "coef till")
SENS_CON_HEADERS = ("cell", "shadow", "rhs", "activity", "slack", "rhs from", "rhs till")


def sensitivity_block(
    sens: Sensitivity,
    cellname: Callable[[int, int], str],
) -> list[list[str | float]]:
    """The sensitivity report as a rectangular block of cell values.

    Rows are lists of label strings or floats, ready to be written into the
    grid. Numbers stay numbers so downstream formulas can reference them --
    that is the entire point of writing into cells rather than paging a
    report. Infinities are written as floats too; the display layer renders
    them as `inf`.

    Layout (a blank row separates the two tables):

        Variables   cell value reduced "obj coef" "coef from" "coef till"
        <one row per decision variable>
        (blank)
        Constraints cell shadow rhs activity slack "rhs from" "rhs till"
        <one row per constraint>
    """
    rows: list[list[str | float]] = []
    rows.append(["Variables", *SENS_VAR_HEADERS[1:]])
    for v in sens.variables:
        rows.append(
            [
                cellname(*v.cell),
                v.value,
                v.reduced_cost,
                v.obj_coef,
                v.obj_from,
                v.obj_till,
            ]
        )
    rows.append([])
    rows.append(["Constraints", *SENS_CON_HEADERS[1:]])
    for c in sens.constraints:
        rows.append(
            [
                cellname(*c.cell),
                c.shadow_price,
                c.rhs,
                c.activity,
                c.slack,
                c.rhs_from,
                c.rhs_till,
            ]
        )
    return rows
