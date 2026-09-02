"""CLI parsing and execution for the ``:opt`` and ``:goal`` commands."""

from __future__ import annotations

import curses

from ..engine import EMPTY, LABEL, NCOL, NROW, NUM, Grid, cellname, ref
from ..goalseek import GoalSeekError
from ..goalseek import seek as goal_seek
from ..opt import (
    OptError,
    OptModel,
    infer_model,
)
from ..opt import (
    cells_to_spec as _cells_to_spec,
)
from ..opt import (
    solve as opt_solve,
)
from ..opt import (
    sweep as opt_sweep,
)
from ..optspec import (
    parse_goal as _parse_goal,
)
from ..optspec import (
    parse_inline_model as _parse_opt_inline,
)
from ..optspec import (
    parse_sweep as _parse_sweep,
)
from ..optspec import (
    resolve_model as _resolve_model,
)
from .format import (
    format_conflict,
    format_sensitivity,
    format_sweep,
    format_unbounded,
    sensitivity_block,
)
from .undo import UndoManager
from .widgets import _flash, pager, show_error

_OPT_USAGE = (
    "usage: opt [max|min <cell> vars <cells> st <cells> [bounds <spec>] | "
    "def <name> max|min ... | run [<name>] | list | undef <name>]"
)


def _write_sensitivity(
    g: Grid,
    undo: UndoManager,
    block: list[list[str | float]],
    anchor: tuple[int, int],
    *,
    force: bool,
) -> str | None:
    """Write a report block into the grid at ``anchor``.

    Returns an error message, or None on success. Refuses to overwrite a
    non-empty cell unless ``force``: the block is several columns wide and
    silently flattening a corner of someone's sheet is not recoverable by
    reading the screen. ``into!`` is the force form, matching ``:q!``.
    """
    ac, ar = anchor
    height = len(block)
    width = max((len(r) for r in block), default=0)
    if ac + width > NCOL or ar + height > NROW:
        return f"report ({width}x{height}) does not fit at {cellname(ac, ar)}"

    # The report owns its whole bounding rectangle, including the short
    # separator row between the two tables. Checking and clearing only the
    # populated positions would leave a user's stray value sitting inside the
    # gap, reading as part of the report.
    if not force:
        for dr in range(height):
            for dc in range(width):
                cell = g.cells[ac + dc][ar + dr]
                if cell is not None and cell.type != EMPTY:
                    return f"{cellname(ac + dc, ar + dr)} is not empty (use 'into!' to overwrite)"

    undo.save_region(g, ac, ar, ac + width - 1, ar + height - 1)
    for dr in range(height):
        row = block[dr]
        for dc in range(width):
            c, r = ac + dc, ar + dr
            if dc >= len(row):
                g._cells.pop((c, r), None)  # gap inside the report: clear it
                continue
            value = row[dc]
            # The report lands on empty cells by design, so this must create
            # them rather than write through the shared empty placeholder.
            cell = g._ensure_cell(c, r)
            cell.ast = None
            cell.ast_text = ""
            cell.err = None
            cell.err_msg = None
            if isinstance(value, str):
                cell.type = LABEL
                cell.text = value
            else:
                cell.type = NUM
                cell.val = float(value)
                cell.text = ""
    g.recalc()
    g.dirty = 1
    return None


def _execute_selection(
    stdscr: curses.window,
    g: Grid,
    undo: UndoManager,
    sense: str,
    sel: tuple[int, int, int, int],
) -> bool:
    """``:opt max|min`` over a visual selection: infer the model, then run it.

    The inferred model is stored as ``default`` before running, matching the
    inline form -- so the block only has to be selected once, and `:opt`
    re-runs it afterwards without a selection.
    """
    c1, r1, c2, r2 = sel
    try:
        inferred = infer_model(g, c1, r1, c2, r2)
    except OptError as e:
        show_error(stdscr, f"opt: {e}")
        return False

    model = OptModel(
        sense=sense,
        objective=cellname(*inferred.objective),
        vars=_cells_to_spec(inferred.decision_vars),
        constraints=_cells_to_spec(inferred.constraint_cells),
    )
    g.models["default"] = model
    g.dirty = 1
    return _execute_model(stdscr, g, undo, model)


_SWEEP_USAGE = "usage: opt sweep <constraint-cell> <lo>:<hi> [steps] [model]"


def _execute_sweep(stdscr: curses.window, g: Grid, args: list[str]) -> bool:
    """``:opt sweep <cell> <lo>:<hi> [steps] [model]``.

    Read-only: the sweep re-solves with substituted right-hand sides and
    never writes to the sheet, so there is no undo snapshot to take and
    nothing to roll back.
    """
    try:
        spec = _parse_sweep(args)
    except (ValueError, RuntimeError) as e:
        show_error(stdscr, f"opt: {e}")
        return False

    model = g.models.get(spec.model)
    if model is None:
        show_error(stdscr, f"opt: no model named {spec.model!r}")
        return False

    cc, cr = spec.constraint
    lo, hi = spec.lo, spec.hi
    steps = spec.steps
    try:
        resolved = _resolve_model(model)
    except (ValueError, RuntimeError) as e:
        show_error(stdscr, f"opt: {e}")
        return False

    (oc, or_), decision_vars, constraint_cells, bounds, integer_vars, binary_vars = resolved
    try:
        points = opt_sweep(
            g,
            (oc, or_),
            decision_vars,
            constraint_cells,
            constraint=(cc, cr),
            lo=lo,
            hi=hi,
            steps=steps,
            maximize=(model.sense == "max"),
            bounds=bounds,
            integer_vars=integer_vars,
            binary_vars=binary_vars,
        )
    except OptError as e:
        show_error(stdscr, f"opt: {e}")
        return False
    except (ValueError, RuntimeError) as e:
        show_error(stdscr, f"opt: invalid model ({e})")
        return False

    pager(stdscr, "Parametric sweep", format_sweep(points, cellname(cc, cr)))
    return False


def _execute_model(
    stdscr: curses.window,
    g: Grid,
    undo: UndoManager,
    model: OptModel,
    *,
    sensitivity: bool = False,
    write_to: tuple[int, int] | None = None,
    force: bool = False,
) -> bool:
    """Resolve a model's spec strings, run the solver, and report.

    Snapshots the grid before solving so ``u`` rolls back a successful
    optimization; pops the undo entry on any failure path (parse error,
    OptError from the solver, non-OPTIMAL status) so undo doesn't no-op
    afterwards.

    With ``sensitivity`` the solve still applies its result to the sheet --
    the report is about the optimum that was just written, so computing it
    without applying would describe a state the user cannot see.
    """
    try:
        resolved = _resolve_model(model)
    except (ValueError, RuntimeError) as e:
        show_error(stdscr, f"opt: {e}")
        return False
    (oc, or_), decision_vars, constraint_cells, bounds, integer_vars, binary_vars = resolved

    undo.save_grid(g)
    try:
        result = opt_solve(
            g,
            objective_cell=(oc, or_),
            decision_vars=decision_vars,
            constraint_cells=constraint_cells,
            maximize=(model.sense == "max"),
            bounds=bounds,
            integer_vars=integer_vars,
            binary_vars=binary_vars,
            apply=True,
            sensitivity=sensitivity,
            # Always diagnose from the TUI. The extra solves only run when
            # the model is infeasible, and at that point the user is stuck
            # with a one-word error -- naming the contradictory cells is the
            # whole difference between a dead end and a next step.
            diagnose=True,
        )
    except OptError as e:
        undo.undo_stack.pop()
        show_error(stdscr, f"opt: {e}")
        return False
    except (ValueError, RuntimeError) as e:
        # Defence in depth. `solve` validates the user-reachable cases and
        # raises OptError, but the `_opt` bridge enforces further invariants
        # with ValueError and reports a failed HiGHS call with RuntimeError.
        # If one ever escapes, report it and keep the session alive -- an
        # uncaught exception here tears down curses and takes the user's
        # unsaved sheet with it.
        undo.undo_stack.pop()
        show_error(stdscr, f"opt: invalid model ({e})")
        return False

    if not result.applied:
        undo.undo_stack.pop()
        msg = f"opt: {result.status_name}"
        if result.conflict is not None:
            msg += "  " + format_conflict(result.conflict, len(constraint_cells), cellname)
        elif result.unbounded is not None:
            msg += "  " + format_unbounded(result.unbounded, cellname)
        show_error(stdscr, msg)
        return False

    summary = f"opt: {result.status_name}  obj={result.objective:.6g}"
    if result.quadratic:
        summary += "  (quadratic)"

    if sensitivity:
        if result.sensitivity is None:
            # The solve succeeded; only the sensitivity half is unavailable.
            # Say why rather than showing an empty report -- a MIP is the
            # common case and the reason is not obvious.
            _flash(stdscr, f"{summary}  (no sensitivity: integer/binary model)")
            return False
        if write_to is not None:
            err = _write_sensitivity(
                g,
                undo,
                sensitivity_block(result.sensitivity, cellname),
                write_to,
                force=force,
            )
            if err:
                _flash(stdscr, f"opt: {err}")
            else:
                _flash(stdscr, f"{summary}  sensitivity written at {cellname(*write_to)}")
            return False
        pager(
            stdscr,
            f"Sensitivity -- {summary}",
            format_sensitivity(result.sensitivity, cellname),
        )
        return False

    _flash(stdscr, summary)
    return False


def cmd_opt(
    stdscr: curses.window,
    g: Grid,
    undo: UndoManager,
    args: str,
    sel: tuple[int, int, int, int] | None = None,
) -> bool:
    """Dispatch for ``:opt``.

    Subcommands:
      * ``:opt``                         - run the model named ``default``
      * ``:opt max|min`` with a visual selection
                                         - infer the model from the block
      * ``:opt max|min <cell> vars ...`` - solve inline, also saves as ``default``
      * ``:opt def <name> max|min ...``  - save under ``<name>``; does NOT execute
      * ``:opt run [<name>]``            - execute saved model (default: ``default``)
      * ``:opt sens [<name>]``           - execute and show a sensitivity report
      * ``:opt sweep <cell> <lo>:<hi> [steps] [name]``
                                         - re-solve across a range of RHS values
      * ``:opt list``                    - show saved model names
      * ``:opt undef <name>``            - remove a saved model

    Saved models live in ``Grid.models`` and round-trip through the JSON
    workbook file, so an LP defined once is reusable across sessions.
    """
    parts = args.split()

    # With a visual selection, `:opt max|min` reads the model out of the
    # selected block instead of requiring `vars ... st ...`. The sheet's
    # layout already encodes the model; this saves retyping it as ranges.
    if sel is not None and len(parts) == 1 and parts[0].lower() in ("max", "min"):
        return _execute_selection(stdscr, g, undo, parts[0].lower(), sel)

    # `:opt` alone: run the default model if defined.
    if not parts:
        model = g.models.get("default")
        if model is None:
            show_error(
                stdscr,
                "opt: no 'default' model defined "
                "(define one with :opt max ... or :opt def default ...)",
            )
            return False
        return _execute_model(stdscr, g, undo, model)

    head = parts[0].lower()

    if head == "list":
        if not g.models:
            show_error(stdscr, "opt: no models defined")
            return False
        _flash(stdscr, "opt models: " + ", ".join(sorted(g.models)))
        return False

    if head == "undef":
        if len(parts) != 2:
            show_error(stdscr, "usage: opt undef <name>")
            return False
        name = parts[1]
        if name not in g.models:
            show_error(stdscr, f"opt: no model named {name!r}")
            return False
        del g.models[name]
        _flash(stdscr, f"opt: removed model {name!r}")
        return False

    if head == "run":
        name = parts[1] if len(parts) >= 2 else "default"
        model = g.models.get(name)
        if model is None:
            show_error(stdscr, f"opt: no model named {name!r}")
            return False
        return _execute_model(stdscr, g, undo, model)

    if head == "sweep":
        return _execute_sweep(stdscr, g, parts[1:])

    if head == "sens":
        name = "default"
        target: tuple[int, int] | None = None
        force = False
        rest = parts[1:]
        i = 0
        while i < len(rest):
            tok = rest[i].lower()
            if tok in ("into", "into!"):
                if i + 1 >= len(rest):
                    show_error(stdscr, "usage: opt sens [<name>] into[!] <cell>")
                    return False
                m = ref(rest[i + 1])
                if not m or m[0] != len(rest[i + 1]):
                    show_error(stdscr, f"opt: bad target cell: {rest[i + 1]}")
                    return False
                force = tok.endswith("!")
                target = (m[1], m[2])
                i += 2
            else:
                name = rest[i]
                i += 1
        model = g.models.get(name)
        if model is None:
            show_error(stdscr, f"opt: no model named {name!r}")
            return False
        return _execute_model(
            stdscr, g, undo, model, sensitivity=True, write_to=target, force=force
        )

    if head == "def":
        if len(parts) < 6:
            show_error(
                stdscr,
                "usage: opt def <name> max|min <cell> vars <cells> st <cells> [bounds <spec>]",
            )
            return False
        name = parts[1]
        try:
            model = _parse_opt_inline(parts[2:])
        except (ValueError, RuntimeError) as e:
            show_error(stdscr, f"opt: {e}")
            return False
        g.models[name] = model
        _flash(stdscr, f"opt: defined model {name!r}")
        return False

    if head in ("max", "min"):
        # Inline form: parse, save as the conventional `default` slot, and run.
        # Storing the model alongside execution captures the LP in the workbook
        # so :w persists it and bare :opt re-runs after reopen.
        try:
            model = _parse_opt_inline(parts)
        except (ValueError, RuntimeError) as e:
            show_error(stdscr, f"opt: {e}")
            return False
        g.models["default"] = model
        return _execute_model(stdscr, g, undo, model)

    show_error(stdscr, _OPT_USAGE)
    return False


def cmd_goal(stdscr: curses.window, g: Grid, undo: UndoManager, args: str) -> bool:
    """``:goal <formula_cell> = <target> by <var_cell> [in <lo>:<hi>]``.

    Adjusts the variable cell to make the formula cell evaluate to the
    target value. On success the grid is left in the solved state and the
    pre-search snapshot is on the undo stack so ``u`` rolls back.

    Compared to ``:opt``, goal-seek doesn't persist a model -- it's a
    one-shot operation whose entire state is the three short args. Just
    retype the command to re-run.
    """
    try:
        spec = _parse_goal(args)
    except (ValueError, RuntimeError) as e:
        show_error(stdscr, f"goal: {e}" if "usage:" not in str(e) else str(e))
        return False

    formula_cell = spec.formula_cell
    var_cell = spec.var_cell
    target = spec.target
    lo, hi = spec.lo, spec.hi

    undo.save_grid(g)
    try:
        result = goal_seek(
            g,
            formula_cell=formula_cell,
            target=target,
            var_cell=var_cell,
            lo=lo,
            hi=hi,
            apply=True,
        )
    except GoalSeekError as e:
        undo.undo_stack.pop()
        show_error(stdscr, f"goal: {e}")
        return False

    if not result.applied:
        # The search ran but didn't converge; no mutation, no undo entry.
        undo.undo_stack.pop()
        show_error(
            stdscr,
            f"goal: did not converge (residual={result.residual:.3g} "
            f"after {result.iterations} iterations)",
        )
        return False

    _flash(
        stdscr,
        f"goal: converged in {result.iterations} iters  "
        f"{_cellname_short(*var_cell)}={result.var_value:.6g}  "
        f"{_cellname_short(*formula_cell)}={result.formula_value:.6g}",
    )
    return False


def _cellname_short(c: int, r: int) -> str:
    """Local wrapper around engine.cellname to keep cmd_goal self-contained."""
    return cellname(c, r)
