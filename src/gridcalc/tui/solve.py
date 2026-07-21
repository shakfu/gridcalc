"""CLI parsing and execution for the ``:opt`` and ``:goal`` commands."""

from __future__ import annotations

import curses
import math

from ..engine import EMPTY, LABEL, NCOL, NROW, NUM, Grid, cellname, ref
from ..goalseek import GoalSeekError
from ..goalseek import seek as goal_seek
from ..opt import OptError, OptModel, infer_model
from ..opt import solve as opt_solve
from ..opt import sweep as opt_sweep
from .format import (
    format_conflict,
    format_sensitivity,
    format_sweep,
    format_unbounded,
    sensitivity_block,
)
from .undo import UndoManager
from .widgets import _flash, pager, show_error


def _parse_cells(spec: str) -> list[tuple[int, int]]:
    """Expand a cell-list spec like ``A1:B3`` or ``A1,A2,B5`` into (col,row)s.

    Returns the cells in row-major order within each range and in spec order
    across comma-separated parts. Duplicate-detection is the caller's job.
    """
    out: list[tuple[int, int]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            a_str, b_str = part.split(":", 1)
            a = ref(a_str.strip())
            b = ref(b_str.strip())
            if not a or not b:
                raise ValueError(f"bad cell range: {part}")
            _, c1, r1 = a
            _, c2, r2 = b
            c1, c2 = sorted((c1, c2))
            r1, r2 = sorted((r1, r2))
            for c in range(c1, c2 + 1):
                for r in range(r1, r2 + 1):
                    out.append((c, r))
        else:
            m = ref(part)
            if not m:
                raise ValueError(f"bad cell ref: {part}")
            _, c, r = m
            out.append((c, r))
    return out


def _parse_bound_value(s: str, *, positive: bool) -> float:
    """Parse a bound endpoint, accepting 'inf' / '-inf' for ±infinity.

    `positive` decides which way a bare 'inf' goes; '+inf'/'-inf' override it.
    """
    s = s.strip().lower()
    if s in ("inf", "+inf", "infinity", "+infinity"):
        return math.inf
    if s in ("-inf", "-infinity"):
        return -math.inf
    return float(s)


def _parse_bounds(spec: str) -> dict[tuple[int, int], tuple[float, float]]:
    """Parse ``A1=lo:hi,B2=lo:hi`` into a bounds dict."""
    out: dict[tuple[int, int], tuple[float, float]] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"bounds entry missing '=': {part}")
        cellref_str, range_str = part.split("=", 1)
        m = ref(cellref_str.strip())
        if not m:
            raise ValueError(f"bad cell ref in bounds: {cellref_str}")
        _, c, r = m
        if ":" not in range_str:
            raise ValueError(f"bounds range needs 'lo:hi': {range_str}")
        lo_s, hi_s = range_str.split(":", 1)
        out[(c, r)] = (
            _parse_bound_value(lo_s, positive=False),
            _parse_bound_value(hi_s, positive=True),
        )
    return out


_OPT_USAGE = (
    "usage: opt [max|min <cell> vars <cells> st <cells> [bounds <spec>] | "
    "def <name> max|min ... | run [<name>] | list | undef <name>]"
)


def _parse_opt_inline(parts: list[str]) -> OptModel:
    """Parse the body after ``max|min`` into an :class:`OptModel`.

    Raises :class:`ValueError` with a human-readable message on syntax errors.
    The returned model stores the *spec strings* as the user wrote them, not
    pre-resolved cell coordinates -- resolution happens at run time, which
    matches how saved models round-trip through the JSON file.
    """
    if len(parts) < 5 or parts[0].lower() not in ("max", "min") or parts[2].lower() != "vars":
        raise ValueError(
            "usage: max|min <cell> vars <cells> st <cells> "
            "[bounds <spec>] [int <cells>] [bin <cells>]"
        )

    sense = parts[0].lower()
    obj_str = parts[1]

    try:
        st_idx = next(i for i in range(3, len(parts)) if parts[i].lower() in ("st", "subject"))
    except StopIteration as e:
        raise ValueError("expected 'st' keyword for constraints") from e

    # Locate every optional-clause keyword that follows `st`. Order is
    # flexible: bounds / int / bin may appear in any sequence. Each clause
    # runs from the keyword to the next keyword (or end of input).
    _CLAUSE_KEYWORDS = ("bounds", "int", "bin")
    clause_positions: list[tuple[int, str]] = []
    for i in range(st_idx + 1, len(parts)):
        lo = parts[i].lower()
        if lo in _CLAUSE_KEYWORDS:
            clause_positions.append((i, lo))

    vars_spec = " ".join(parts[3:st_idx])
    first_clause = clause_positions[0][0] if clause_positions else len(parts)
    st_spec = " ".join(parts[st_idx + 1 : first_clause])

    clauses: dict[str, str] = {"bounds": "", "int": "", "bin": ""}
    for j, (pos, kw) in enumerate(clause_positions):
        end = clause_positions[j + 1][0] if j + 1 < len(clause_positions) else len(parts)
        if clauses[kw]:
            raise ValueError(f"'{kw}' clause appears more than once")
        clauses[kw] = " ".join(parts[pos + 1 : end])

    if not _looks_like_cellref(obj_str):
        raise ValueError(f"bad objective cell: {obj_str}")

    return OptModel(
        sense=sense,
        objective=obj_str,
        vars=vars_spec,
        constraints=st_spec,
        bounds=clauses["bounds"],
        integers=clauses["int"],
        binaries=clauses["bin"],
    )


def _looks_like_cellref(s: str) -> bool:
    """Quick syntactic check that ``s`` is a single cell ref (no range)."""
    m = ref(s)
    return m is not None and m[0] == len(s)


_ResolvedModel = tuple[
    tuple[int, int],
    list[tuple[int, int]],
    list[tuple[int, int]],
    dict[tuple[int, int], tuple[float, float]] | None,
    set[tuple[int, int]] | None,
    set[tuple[int, int]] | None,
]


def _resolve_model(model: OptModel) -> _ResolvedModel:
    """Turn a saved model's spec strings into cell coordinates.

    Raises ``ValueError`` with a user-facing message; callers report it.
    Shared by every command that runs a model so the specs cannot be
    interpreted one way by ``:opt run`` and another by ``:opt sweep``.
    """
    obj_match = ref(model.objective)
    if not obj_match or obj_match[0] != len(model.objective):
        raise ValueError(f"bad objective cell: {model.objective}")
    _, oc, or_ = obj_match
    return (
        (oc, or_),
        _parse_cells(model.vars),
        _parse_cells(model.constraints),
        _parse_bounds(model.bounds) if model.bounds else None,
        set(_parse_cells(model.integers)) if model.integers else None,
        set(_parse_cells(model.binaries)) if model.binaries else None,
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


def _cells_to_spec(cells: list[tuple[int, int]]) -> str:
    """Render a cell list as a comma-separated spec string.

    Inferred models are stored as specs, exactly like typed ones, so they
    round-trip through the workbook JSON and can be re-run with `:opt` after
    reopening. A contiguous single-column or single-row run collapses to
    range syntax so the saved model stays readable.
    """
    if not cells:
        return ""
    cols = {c for c, _ in cells}
    rows = {r for _, r in cells}
    if len(cols) == 1:
        rs = sorted(rows)
        if rs == list(range(rs[0], rs[-1] + 1)) and len(rs) > 1:
            c = next(iter(cols))
            return f"{cellname(c, rs[0])}:{cellname(c, rs[-1])}"
    if len(rows) == 1:
        cs = sorted(cols)
        if cs == list(range(cs[0], cs[-1] + 1)) and len(cs) > 1:
            r = next(iter(rows))
            return f"{cellname(cs[0], r)}:{cellname(cs[-1], r)}"
    return ",".join(cellname(c, r) for c, r in cells)


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
    if len(args) < 2:
        show_error(stdscr, _SWEEP_USAGE)
        return False

    cell_str, range_str = args[0], args[1]
    steps = 10
    name = "default"
    for extra in args[2:]:
        if extra.isdigit():
            steps = int(extra)
        else:
            name = extra

    model = g.models.get(name)
    if model is None:
        show_error(stdscr, f"opt: no model named {name!r}")
        return False

    try:
        m = ref(cell_str)
        if not m or m[0] != len(cell_str):
            raise ValueError(f"bad constraint cell: {cell_str}")
        _, cc, cr = m
        if ":" not in range_str:
            raise ValueError(f"sweep range needs 'lo:hi': {range_str}")
        lo_s, hi_s = range_str.split(":", 1)
        lo, hi = float(lo_s), float(hi_s)
        if math.isnan(lo) or math.isnan(hi):
            raise ValueError(f"sweep range is not numeric: {range_str}")
        resolved = _resolve_model(model)
    except ValueError as e:
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
    except ValueError as e:
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
    except ValueError as e:
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
    except ValueError as e:
        # Defence in depth. `solve` validates the user-reachable cases and
        # raises OptError, but the `_opt` bridge enforces further invariants
        # with ValueError. If one ever escapes, report it and keep the
        # session alive -- an uncaught exception here tears down curses and
        # takes the user's unsaved sheet with it.
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
        # A quadratic objective is solved through a piecewise-linear
        # relaxation, so the answer is approximate. Saying OPTIMAL without
        # qualification would overstate it.
        summary += f"  (quadratic, within {result.quadratic_gap:.3g})"

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
        except ValueError as e:
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
        except ValueError as e:
            show_error(stdscr, f"opt: {e}")
            return False
        g.models["default"] = model
        return _execute_model(stdscr, g, undo, model)

    show_error(stdscr, _OPT_USAGE)
    return False


def _parse_single_cell(s: str) -> tuple[int, int]:
    m = ref(s)
    if not m or m[0] != len(s):
        raise ValueError(f"bad cell ref: {s}")
    _, c, r = m
    return (c, r)


def cmd_goal(stdscr: curses.window, g: Grid, undo: UndoManager, args: str) -> bool:
    """``:goal <formula_cell> = <target> by <var_cell> [in <lo>:<hi>]``.

    Adjusts the variable cell to make the formula cell evaluate to the
    target value. On success the grid is left in the solved state and the
    pre-search snapshot is on the undo stack so ``u`` rolls back.

    Compared to ``:opt``, goal-seek doesn't persist a model -- it's a
    one-shot operation whose entire state is the three short args. Just
    retype the command to re-run.
    """
    parts = args.split()
    usage = "usage: goal <formula_cell> = <target> by <var_cell> [in <lo>:<hi>]"

    if len(parts) < 5 or parts[1] != "=" or parts[3].lower() != "by":
        show_error(stdscr, usage)
        return False

    formula_str = parts[0]
    target_str = parts[2]
    var_str = parts[4]

    in_idx: int | None = None
    for i in range(5, len(parts)):
        if parts[i].lower() == "in":
            in_idx = i
            break

    lo: float | None = None
    hi: float | None = None
    if in_idx is not None:
        bracket_spec = " ".join(parts[in_idx + 1 :]).strip()
        if ":" not in bracket_spec:
            show_error(stdscr, "goal: bracket needs 'lo:hi' after 'in'")
            return False
        lo_s, hi_s = bracket_spec.split(":", 1)
        try:
            lo = _parse_bound_value(lo_s, positive=False)
            hi = _parse_bound_value(hi_s, positive=True)
        except ValueError as e:
            show_error(stdscr, f"goal: bad bracket: {e}")
            return False
    elif len(parts) > 5:
        # Trailing junk that isn't `in ...` is a syntax error rather than
        # silently ignored, so typos surface immediately.
        show_error(stdscr, usage)
        return False

    try:
        formula_cell = _parse_single_cell(formula_str)
        var_cell = _parse_single_cell(var_str)
        target = float(target_str)
    except ValueError as e:
        show_error(stdscr, f"goal: {e}")
        return False

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
