"""Frontend-neutral JSON shapes for solve, sweep and goal-seek results.

The optimization results have to reach three places -- the web bridge, the
headless CLI, and anything a user scripts against the latter -- and they were
previously shaped by hand in `web.Api._solve_json`. A second hand-written copy
in the CLI is exactly the drift `commands.py` and `display.py` exist to
prevent: two callers disagreeing about whether a key is `status` or
`status_name`, or whether an unbounded objective serialises as `Infinity`
(which is not JSON) or `null`.

So the shapes live here, once. `web.Api` and `gridcalc.cli` both call these,
and :doc:`the CLI reference </reference/cli>` documents the result as a stable
contract -- the CLI's whole point is being scriptable, and a schema that moves
between releases is not something a script can depend on.

Two conventions run through all of it:

* **Cells are A1 strings**, not ``(col, row)`` pairs. A JSON object cannot key
  on a tuple, and ``"B4"`` is what the user typed and what they will grep for.
* **Non-finite floats become ``null``**, on *every* numeric field rather
  than only the ranging limits where an infinity is expected. JSON has no
  `Infinity` or `NaN`;
  `json.dumps` emits them anyway by default, producing output that a
  conforming parser on the other end rejects. An unbounded objective and a
  missing ranging limit are both genuinely "no number here", which is what
  ``null`` says. The CLI dumps with ``allow_nan=False`` precisely so a
  field that slipped through would be a loud failure rather than output no
  conforming parser accepts; passing everything through :func:`num` is what
  keeps that from ever firing.
"""

from __future__ import annotations

import math
from typing import Any

from .engine import col_name
from .goalseek import SeekResult
from .opt import SolveResult, SweepPoint

CellKey = tuple[int, int]


def a1(key: CellKey) -> str:
    """Render a ``(col, row)`` key as an A1 reference."""
    c, r = key
    return f"{col_name(c)}{r + 1}"


def num(x: Any) -> float | None:
    """JSON-safe number: inf/nan -> ``None``, everything else unchanged."""
    return x if isinstance(x, (int, float)) and math.isfinite(x) else None


def solve_json(res: SolveResult) -> dict[str, Any]:
    """Serialise a :class:`~gridcalc.opt.SolveResult`.

    ``optimal`` is derived rather than left to the caller: every consumer
    wants the boolean, and computing it from `status_name` in three places is
    how they end up disagreeing about whether `OPTIMAL` is the only success.
    The optional blocks (`sensitivity`, `conflict`, `unbounded`) are present
    only when the solve actually produced them, so a key's presence means
    "this was computed" rather than "this was requested".
    """
    out: dict[str, Any] = {
        "status": res.status_name,
        "optimal": res.status_name == "OPTIMAL",
        "objective": num(res.objective),
        "values": {a1(k): num(v) for k, v in res.values.items()},
        "applied": res.applied,
        "quadratic": res.quadratic,
    }
    if res.sensitivity is not None:
        out["sensitivity"] = {
            "variables": [
                {
                    "cell": a1(v.cell),
                    "value": num(v.value),
                    "reduced_cost": num(v.reduced_cost),
                    "obj_coef": num(v.obj_coef),
                    "obj_from": num(v.obj_from),
                    "obj_till": num(v.obj_till),
                }
                for v in res.sensitivity.variables
            ],
            "constraints": [
                {
                    "cell": a1(c.cell),
                    "shadow_price": num(c.shadow_price),
                    "rhs": num(c.rhs),
                    "activity": num(c.activity),
                    "slack": num(c.slack),
                    "binding": c.binding,
                    "rhs_from": num(c.rhs_from),
                    "rhs_till": num(c.rhs_till),
                }
                for c in res.sensitivity.constraints
            ],
        }
    if res.conflict is not None:
        out["conflict"] = [a1(k) for k in res.conflict]
    if res.unbounded is not None:
        out["unbounded"] = [a1(k) for k in res.unbounded]
    return out


def sweep_json(points: list[SweepPoint], constraint: CellKey) -> dict[str, Any]:
    """Serialise a parametric sweep.

    The swept constraint rides along at the top level: a bare list of points
    does not say what was varied, and a saved sweep result that cannot answer
    "of what?" is not much use in a report.
    """
    return {
        "constraint": a1(constraint),
        "points": [
            {
                "rhs": num(p.rhs),
                "status": p.status_name,
                "objective": num(p.objective),
                "shadow_price": num(p.shadow_price),
                "delta": num(p.delta),
                "breakpoint": p.breakpoint,
            }
            for p in points
        ],
        "breakpoints": [num(p.rhs) for p in points if p.breakpoint],
    }


def goal_json(
    res: SeekResult, formula_cell: CellKey, var_cell: CellKey, target: float
) -> dict[str, Any]:
    """Serialise a goal-seek result.

    Carries the question as well as the answer -- which cell was driven to
    which target by which variable -- for the same reason as the sweep: the
    output is meant to be kept.
    """
    return {
        "converged": res.converged,
        "iterations": res.iterations,
        "formula_cell": a1(formula_cell),
        "var_cell": a1(var_cell),
        "target": num(target),
        "var_value": num(res.var_value),
        "formula_value": num(res.formula_value),
        "residual": num(res.residual),
        "applied": res.applied,
    }
