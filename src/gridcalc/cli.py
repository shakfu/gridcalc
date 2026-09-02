"""Headless mode: the solve/goal/sweep/eval/convert pipeline without a screen.

`gridcalc book.json` opens the curses editor. `gridcalc book.json --solve`
runs the workbook's saved model and prints the result as JSON, which is what
lets the differentiator -- optimization with spreadsheet semantics -- be
driven by cron, CI, a Makefile, or another program. Excel's Solver needs a
human in a dialog; PuLP needs the model rewritten as code. This needs neither:
the model lives in the sheet, and the sheet is the input file.

Design notes:

* **The grammar is the TUI's.** ``--solve 'max B4 vars A4:A5 st D4:D6'``,
  ``--goal 'B10 = 100 by A1'`` and ``--sweep 'D5 6:24 9'`` are parsed by
  :mod:`gridcalc.optspec`, the same module `:opt` and `:goal` use, so a spec
  that works in the terminal works in a script and vice versa.
* **JSON is the default output**, because the audience is a program. The
  schema is documented in ``docs/reference/cli.md`` and treated as a contract;
  ``--format text`` is the human-readable rendering, and nothing parses it.
* **Nothing is written unless asked.** Solve and goal-seek default to
  ``--no-apply``: they report what they found and leave the file alone. Adding
  ``--apply`` writes the result into the in-memory grid, which only reaches
  disk if ``--convert`` (or ``--write-back``) is also given. A tool that
  rewrites the user's workbook because they asked it a question is a tool
  nobody runs twice.
* **Exit codes carry the answer**, so `if gridcalc book.json --solve; then`
  works without parsing anything:

  - ``0`` -- the operation ran and succeeded.
  - ``2`` -- it ran and produced a negative result: INFEASIBLE, UNBOUNDED, or
    a goal-seek that iterated without converging. There is output to read.
  - ``1`` -- it never ran: bad spec, missing file, no such model, or a
    goal-seek rejected before searching (a non-formula target, a bracket with
    no sign change). The message is on stderr and stdout is empty.

  That split is what makes the difference in CI between "the plan is
  infeasible, alert someone" and "the job is broken".
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, TextIO, cast

from . import goalseek, opt
from .display import cell_text
from .engine import EMPTY, NCOL, NROW, SPILL, Grid
from .loader import load_workbook
from .optspec import (
    GoalSpec,
    SweepSpec,
    parse_goal,
    parse_inline_model,
    parse_sweep,
    resolve_model,
)
from .report import goal_json, num, solve_json, sweep_json

# Exit codes. `OK`/`FAILED` are the two outcomes of an operation that ran;
# `ERROR` means it never got that far.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_FAILED = 2

# The actions that make this a headless run rather than an editor launch.
HEADLESS_FLAGS = ("solve", "goal", "sweep", "eval", "convert")


class CliError(Exception):
    """A usage or I/O failure: reported on stderr, exits :data:`EXIT_ERROR`."""


# --- argument wiring --------------------------------------------------------


def add_headless_arguments(p: argparse.ArgumentParser) -> None:
    """Attach the headless flags to the ``gridcalc`` parser.

    Kept separate from the parser itself so `tui.cli_parser` stays a
    description of the command line and this stays a description of the
    headless surface.
    """
    g = p.add_argument_group(
        "headless mode",
        "Run an operation and exit instead of opening the editor. "
        "Results go to stdout as JSON (see --format).",
    )
    g.add_argument(
        "--solve",
        nargs="?",
        const="default",
        metavar="MODEL|SPEC",
        help="run a saved model by name (default: 'default'), or an inline "
        "spec: 'max B4 vars A4:A5 st D4:D6 [bounds ...] [int ...] [bin ...]'",
    )
    g.add_argument(
        "--sens",
        action="store_true",
        help="with --solve, include shadow prices, reduced costs and ranging",
    )
    g.add_argument(
        "--diagnose",
        action="store_true",
        help="with --solve, explain an INFEASIBLE or UNBOUNDED result",
    )
    g.add_argument(
        "--goal",
        metavar="SPEC",
        help="goal-seek: '<cell> = <target> by <cell> [in <lo>:<hi>]'",
    )
    g.add_argument(
        "--sweep",
        metavar="SPEC",
        help="parametric RHS sweep: '<cell> <lo>:<hi> [steps] [model]'",
    )
    g.add_argument(
        "--eval",
        action="append",
        metavar="FORMULA",
        help="evaluate a formula against the workbook and report its value; "
        "repeatable. Never modifies the sheet.",
    )
    g.add_argument(
        "--convert",
        metavar="PATH",
        help="write the workbook to PATH; the format follows the extension "
        "(.xlsx / .csv / otherwise JSON)",
    )
    g.add_argument(
        "--apply",
        action="store_true",
        help="let --solve/--goal write their result into the grid (default: "
        "report only). Reaches disk only with --convert.",
    )
    g.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="output format (default: json). 'text' is for humans; the JSON "
        "schema is the documented, stable one.",
    )
    g.add_argument(
        "--sheet",
        metavar="NAME",
        help="operate on this sheet instead of the workbook's active one",
    )


def is_headless(args: argparse.Namespace) -> bool:
    """Whether the parsed arguments ask for an operation rather than the editor."""
    return any(getattr(args, name, None) for name in HEADLESS_FLAGS)


# --- operations -------------------------------------------------------------


def _load(path: str | None) -> Grid:
    if not path:
        raise CliError("headless mode needs a workbook: gridcalc FILE --solve ...")
    try:
        return load_workbook(path)
    except OSError as exc:
        raise CliError(str(exc)) from exc


def _select_sheet(g: Grid, name: str | None) -> None:
    if name is None:
        return
    names = g.sheet_names()
    if name not in names:
        raise CliError(f"no such sheet: {name!r} (have: {', '.join(names)})")
    g.set_active(names.index(name))


def _model_for(g: Grid, spec: str) -> opt.OptModel:
    """Resolve ``--solve``'s argument to a model.

    A spec starting with `max`/`min` is an inline model; anything else names
    one saved in the workbook. That is the same rule `:opt` applies, so the
    two cannot disagree about what `--solve plan` means.
    """
    head = spec.split(None, 1)[0].lower() if spec.split() else ""
    if head in ("max", "min"):
        try:
            return parse_inline_model(spec.split())
        except (ValueError, RuntimeError) as exc:
            # A syntax error in the spec is a usage failure, not a crash: the
            # parser's message is already the `:opt` usage line.
            raise CliError(str(exc)) from exc
    model = g.models.get(spec)
    if model is None:
        known = ", ".join(sorted(g.models)) or "none"
        raise CliError(f"no model named {spec!r} in this workbook (saved models: {known})")
    # `Grid.models` is typed `dict[str, Any]` because engine.py cannot import
    # opt.py without a cycle; the loader only ever puts OptModel in it.
    return cast(opt.OptModel, model)


def run_solve(g: Grid, spec: str, *, sens: bool, diagnose: bool, apply: bool) -> dict[str, Any]:
    model = _model_for(g, spec)
    try:
        objective, decision_vars, constraints, bounds, integers, binaries = resolve_model(model)
    except (ValueError, RuntimeError) as exc:
        raise CliError(f"invalid model: {exc}") from exc
    try:
        res = opt.solve(
            g,
            objective,
            decision_vars,
            constraints,
            maximize=(model.sense == "max"),
            bounds=bounds,
            integer_vars=integers,
            binary_vars=binaries,
            apply=apply,
            sensitivity=sens,
            diagnose=diagnose,
        )
    except opt.OptError as exc:
        raise CliError(str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise CliError(f"invalid model: {exc}") from exc
    out = solve_json(res)
    out["model"] = model.to_json()
    return out


def run_goal(g: Grid, spec: GoalSpec, *, apply: bool) -> dict[str, Any]:
    try:
        res = goalseek.seek(
            g,
            spec.formula_cell,
            spec.target,
            spec.var_cell,
            lo=spec.lo,
            hi=spec.hi,
            apply=apply,
        )
    except goalseek.GoalSeekError as exc:
        raise CliError(str(exc)) from exc
    return goal_json(res, spec.formula_cell, spec.var_cell, spec.target)


def run_sweep(g: Grid, spec: SweepSpec) -> dict[str, Any]:
    model = _model_for(g, spec.model)
    try:
        objective, decision_vars, constraints, bounds, integers, binaries = resolve_model(model)
    except (ValueError, RuntimeError) as exc:
        raise CliError(f"invalid model: {exc}") from exc
    try:
        points = opt.sweep(
            g,
            objective,
            decision_vars,
            constraints,
            constraint=spec.constraint,
            lo=spec.lo,
            hi=spec.hi,
            steps=spec.steps,
            maximize=(model.sense == "max"),
            bounds=bounds,
            integer_vars=integers,
            binary_vars=binaries,
        )
    except opt.OptError as exc:
        raise CliError(str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise CliError(f"invalid model: {exc}") from exc
    return sweep_json(points, spec.constraint)


def run_eval(g: Grid, formulas: list[str]) -> list[dict[str, Any]]:
    """Evaluate each formula against the workbook without disturbing it.

    The expression is written into a scratch cell far outside any data, read
    back, and erased -- there is no evaluate-an-expression entry point that
    does not go through a cell, because a formula's meaning depends on where
    it sits (relative refs, the active sheet). Using a real cell means
    `--eval '=SUM(A1:A10)'` resolves exactly as it would if typed there. The
    cell is restored afterwards, so the workbook `--convert` writes is the one
    that was loaded.
    """
    out: list[dict[str, Any]] = []
    sheet = g._active
    # Bottom-right corner: outside any plausible data, and restored regardless.
    sc, sr = NCOL - 1, NROW - 1
    had = (sc, sr) in sheet._cells
    saved = sheet._cells[(sc, sr)].snapshot() if had else None
    try:
        for text in formulas:
            expr = text if text.startswith("=") else "=" + text
            g.setcell(sc, sr, expr)
            cl = g.cell(sc, sr)
            entry: dict[str, Any] = {
                "formula": expr,
                "text": cell_text(cl) if cl is not None else "",
                "value": None,
                "error": None,
            }
            if cl is not None:
                if cl.err is not None:
                    entry["error"] = str(cl.err)
                elif isinstance(cl.val, float) and math.isnan(cl.val):
                    entry["error"] = "ERROR"
                else:
                    entry["value"] = num(cl.val)
                if cl.sval is not None:
                    entry["value"] = cl.sval
            out.append(entry)
    finally:
        g.setcell(sc, sr, "")
        if saved is not None:
            sheet._cells[(sc, sr)] = saved
        else:
            sheet._cells.pop((sc, sr), None)
        g.recalc()
    return out


def run_convert(g: Grid, path: str) -> dict[str, Any]:
    low = path.lower()
    if low.endswith(".xlsx"):
        rc = g.xlsxsave(path)
        fmt = "xlsx"
    elif low.endswith(".csv"):
        rc = g.csvsave(path)
        fmt = "csv"
    else:
        rc = g.jsonsave(path)
        fmt = "json"
    if rc < 0:
        raise CliError(f"could not write {path}")
    return {"path": str(Path(path)), "format": fmt, "cells": _cell_count(g)}


def _cell_count(g: Grid) -> int:
    return sum(1 for s in g.sheets for cl in s._cells.values() if cl.type not in (EMPTY, SPILL))


# --- text rendering ---------------------------------------------------------
#
# Deliberately not a parseable format: --format json is what a script reads.
# This exists so a human running the command by hand gets something legible.


def _fmt_num(x: Any) -> str:
    if x is None:
        return "-"
    if isinstance(x, float) and x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return f"{x:g}" if isinstance(x, (int, float)) else str(x)


def _text_solve(d: dict[str, Any]) -> list[str]:
    lines = [f"status:    {d['status']}", f"objective: {_fmt_num(d['objective'])}"]
    if d["quadratic"]:
        lines.append("           (quadratic objective, solved as a QP)")
    if d["values"]:
        lines.append("values:")
        lines += [f"  {k:<8} {_fmt_num(v)}" for k, v in d["values"].items()]
    if d.get("conflict"):
        lines.append("conflicting constraints: " + ", ".join(d["conflict"]))
    if d.get("unbounded"):
        lines.append("unbounded variables: " + ", ".join(d["unbounded"]))
    sens = d.get("sensitivity")
    if sens:
        lines.append("variables:")
        lines.append(f"  {'cell':<8}{'value':>12}{'reduced':>12}{'coef':>12}")
        for v in sens["variables"]:
            lines.append(
                f"  {v['cell']:<8}{_fmt_num(v['value']):>12}"
                f"{_fmt_num(v['reduced_cost']):>12}{_fmt_num(v['obj_coef']):>12}"
            )
        lines.append("constraints:")
        lines.append(f"  {'cell':<8}{'shadow':>12}{'slack':>12}  binding")
        for c in sens["constraints"]:
            lines.append(
                f"  {c['cell']:<8}{_fmt_num(c['shadow_price']):>12}"
                f"{_fmt_num(c['slack']):>12}  {'yes' if c['binding'] else 'no'}"
            )
    lines.append(f"applied:   {'yes' if d['applied'] else 'no'}")
    return lines


def _text_sweep(d: dict[str, Any]) -> list[str]:
    lines = [
        f"sweep of {d['constraint']}",
        f"  {'rhs':>10}{'objective':>14}{'shadow':>12}{'delta':>12}  status",
    ]
    for p in d["points"]:
        mark = " *" if p["breakpoint"] else ""
        lines.append(
            f"  {_fmt_num(p['rhs']):>10}{_fmt_num(p['objective']):>14}"
            f"{_fmt_num(p['shadow_price']):>12}{_fmt_num(p['delta']):>12}  {p['status']}{mark}"
        )
    if d["breakpoints"]:
        lines.append(
            "  * marginal value changes at: " + ", ".join(_fmt_num(b) for b in d["breakpoints"])
        )
    return lines


def _text_goal(d: dict[str, Any]) -> list[str]:
    return [
        f"goal:      {d['formula_cell']} = {_fmt_num(d['target'])} by {d['var_cell']}",
        f"converged: {'yes' if d['converged'] else 'no'} in {d['iterations']} iterations",
        f"{d['var_cell']:<10} {_fmt_num(d['var_value'])}",
        f"{d['formula_cell']:<10} {_fmt_num(d['formula_value'])}  (residual {d['residual']:.3g})",
        f"applied:   {'yes' if d['applied'] else 'no'}",
    ]


def _text_eval(entries: list[dict[str, Any]]) -> list[str]:
    return [f"{e['formula']}  ->  {e['error'] or e['text']}" for e in entries]


def render_text(result: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, render in (
        ("eval", _text_eval),
        ("solve", _text_solve),
        ("goal", _text_goal),
        ("sweep", _text_sweep),
    ):
        if key in result:
            if lines:
                lines.append("")
            lines += render(result[key])
    if "convert" in result:
        c = result["convert"]
        if lines:
            lines.append("")
        lines.append(f"wrote {c['path']} ({c['format']}, {c['cells']} cells)")
    return "\n".join(lines)


# --- driver -----------------------------------------------------------------


def run(args: argparse.Namespace, out: TextIO | None = None, err: TextIO | None = None) -> int:
    """Execute the requested headless operations. Returns the exit code.

    Operations run in a fixed order -- eval, solve, goal, sweep, convert --
    rather than in the order the flags appear, so `--convert` always sees the
    state the other operations left and the result of a given command line
    does not depend on argument order. Everything lands in one JSON object
    keyed by operation, so a single run can answer several questions.
    """
    out = out or sys.stdout
    err = err or sys.stderr
    result: dict[str, Any] = {}
    failed = False
    try:
        g = _load(args.file)
        _select_sheet(g, getattr(args, "sheet", None))

        if args.eval:
            result["eval"] = run_eval(g, args.eval)
        if args.solve:
            d = run_solve(g, args.solve, sens=args.sens, diagnose=args.diagnose, apply=args.apply)
            result["solve"] = d
            failed = failed or not d["optimal"]
        if args.goal:
            try:
                spec = parse_goal(args.goal)
            except (ValueError, RuntimeError) as exc:
                raise CliError(str(exc)) from exc
            d = run_goal(g, spec, apply=args.apply)
            result["goal"] = d
            failed = failed or not d["converged"]
        if args.sweep:
            try:
                spec_s = parse_sweep(args.sweep.split())
            except (ValueError, RuntimeError) as exc:
                raise CliError(str(exc)) from exc
            result["sweep"] = run_sweep(g, spec_s)
        if args.convert:
            result["convert"] = run_convert(g, args.convert)
    except CliError as exc:
        print(f"gridcalc: {exc}", file=err)
        return EXIT_ERROR

    if args.format == "json":
        print(json.dumps(result, indent=2, sort_keys=False, allow_nan=False), file=out)
    else:
        text = render_text(result)
        if text:
            print(text, file=out)
    return EXIT_FAILED if failed else EXIT_OK


__all__ = [
    "EXIT_ERROR",
    "EXIT_FAILED",
    "EXIT_OK",
    "CliError",
    "add_headless_arguments",
    "is_headless",
    "run",
]
