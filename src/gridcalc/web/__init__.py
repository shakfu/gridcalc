"""Experimental web frontend -- an editable grid in a desktop webview.

The second GUI spike from ``docs/gui.md``: the headless engine runs in-process
on CPython (C++ extensions intact) and a browser view renders a JSON viewport
over it. Unlike a server + fetch design, the view runs inside a **pywebview**
window and calls Python directly through the ``js_api`` bridge -- so the
network/serialization boundary collapses to in-process method calls, which
suits a single-user, offline desktop app.

Design:

* **All engine<->view logic is in :class:`Api`**, a plain Python object with no
  ``webview`` import, so every method is unit-testable without a display. The
  JS side is thin glue that renders whatever ``Api`` returns.
* **The heavy dependency is optional and lazy.** ``pywebview`` (the ``web``
  extra) is imported only inside :func:`run`; ``import gridcalc.web`` stays
  cheap.
* **Cell formatting is shared**, not reinvented: ``Api`` uses the
  frontend-neutral ``gridcalc.display.cell_text`` / ``cell_right_aligned``, so
  the web view and the curses TUI format cells identically.

Scope so far: a scrollable (virtualized) grid; an active-cell cursor with
keyboard navigation (arrows, Tab, Home) and rectangular selection (shift-move
/ shift-click); single-cell edit (Enter/F2/double-click/type; commit runs
``setcell`` + ``recalc``, re-renders, and advances the cursor); formula "point
mode" (while editing a formula, clicking or dragging the grid inserts a
reference -- ``=SUM(`` then dragging A1:A3 yields ``=SUM(A1:A3``); copy/cut/
paste (Ctrl/Cmd+C/X/V) with formula-preserving, reference-adjusting paste and
best-effort OS-clipboard export; fill down/right (Ctrl+D/Ctrl+R and a
drag-fill handle); undo/redo (Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y, via the shared
``gridcalc.undo.UndoManager``); save (Ctrl+S, to the loaded file or a native
save dialog); open a different workbook into the running window (Ctrl+O, via a
native open dialog); paste-in of external OS-clipboard text (Ctrl+V of a TSV
block from another app, written verbatim); Delete to blank a selection; a bar
chart from the selected range (``chart_data`` returns a renderer-agnostic
``{labels, series}`` shape, drawn as inline SVG); and the optimization surface
-- ``Solve`` runs ``:opt`` over the selection (``solve_selection`` -> infer +
solve) and renders objective, decision values, and sensitivity in a floating
panel; ``Goal`` opens a goal-seek dialog (``goal_seek``). A real charting
library (Plotly/ECharts) can replace the SVG renderer without touching ``Api``.
"""

from __future__ import annotations

import contextlib
import math
from typing import Any

from .. import goalseek, opt
from ..display import cell_clip_value, cell_right_aligned, cell_text
from ..engine import (
    EMPTY,
    FORMULA,
    LABEL,
    NCOL,
    NROW,
    NUM,
    SPILL,
    Grid,
    adjust_refs,
    col_name,
    ref,
)
from ..loader import demo_grid, load_workbook
from ..opt import parse_bounds, parse_cells
from ..undo import UndoManager


class Api:
    """The ``js_api`` bridge object exposed to the browser view.

    Every method returns JSON-serializable data (dicts / lists / scalars) so
    pywebview can marshal it to JS. Coordinates are zero-based ``(r, c)``;
    ``viewport`` returns only non-empty cells to keep payloads small.
    """

    def __init__(self, g: Grid) -> None:
        self._g = g
        self._clip: dict[str, Any] | None = None  # internal copy/cut buffer
        self._undo = UndoManager()
        self._window: Any = None  # set by run() for the native save dialog

    def dims(self) -> dict[str, Any]:
        """Sheet extent and the loaded filename (for the title)."""
        return {"ncol": NCOL, "nrow": NROW, "filename": getattr(self._g, "filename", "") or ""}

    def sheets(self) -> dict[str, Any]:
        """The sheet tab list and which one is active."""
        return {"active": self._g.active, "names": self._g.sheet_names()}

    def set_active(self, idx: int) -> dict[str, Any]:
        """Switch the active sheet by index; out-of-range is ignored."""
        with contextlib.suppress(ValueError, IndexError, KeyError):
            self._g.set_active(int(idx))
        return self.sheets()

    def viewport(self, r0: int, c0: int, rows: int, cols: int) -> dict[str, Any]:
        """Non-empty cells in the ``[r0, r0+rows) x [c0, c0+cols)`` rectangle.

        Each cell is ``{r, c, text, align}`` where ``align`` is ``"r"`` or
        ``"l"``. Empty cells are omitted; the client fills gaps as blank.
        """
        g = self._g
        r0 = max(0, int(r0))
        c0 = max(0, int(c0))
        r1 = min(NROW, r0 + max(0, int(rows)))
        c1 = min(NCOL, c0 + max(0, int(cols)))
        cells: list[dict[str, Any]] = []
        for r in range(r0, r1):
            for c in range(c0, c1):
                cl = g.cell(c, r)
                if cl is None or cl.type == EMPTY:
                    continue
                cells.append(
                    {
                        "r": r,
                        "c": c,
                        "text": cell_text(cl, g.fmt),
                        "align": "r" if cell_right_aligned(cl) else "l",
                    }
                )
        return {"r0": r0, "c0": c0, "rows": r1 - r0, "cols": c1 - c0, "cells": cells}

    def cell_source(self, r: int, c: int) -> str:
        """The editable source text of a cell (formula text / label / number)."""
        cl = self._g.cell(int(c), int(r))
        if cl is None or cl.type == EMPTY:
            return ""
        return cl.text

    def set_cell(self, r: int, c: int, text: str) -> dict[str, Any]:
        """Write a cell's source, recalc, and report success.

        The client re-requests its current viewport afterwards, since a recalc
        may change any number of dependent cells.
        """
        g = self._g
        self._undo.save_cell(g, int(c), int(r))
        g.setcell(int(c), int(r), text if text is not None else "")
        g.recalc()
        return {"ok": True}

    def undo(self) -> dict[str, Any]:
        """Undo the last mutation (recomputes derived cells)."""
        self._undo.undo(self._g)
        return {"ok": True}

    def redo(self) -> dict[str, Any]:
        """Redo the last undone mutation."""
        self._undo.redo(self._g)
        return {"ok": True}

    def clear_range(self, r0: int, c0: int, r1: int, c1: int) -> dict[str, Any]:
        """Blank every cell in a rectangle, then recalc once (Delete on a
        selection)."""
        g = self._g
        ra, rb = sorted((int(r0), int(r1)))
        ca, cb = sorted((int(c0), int(c1)))
        self._undo.save_region(g, ca, ra, cb, rb)
        for r in range(max(0, ra), min(NROW, rb + 1)):
            for c in range(max(0, ca), min(NCOL, cb + 1)):
                g.setcell(c, r, "")
        g.recalc()
        return {"ok": True}

    def copy(self, r0: int, c0: int, r1: int, c1: int, cut: bool = False) -> dict[str, Any]:
        """Snapshot a rectangle into the internal buffer and return its values
        as TSV (which the client can also push to the OS clipboard).

        The buffer keeps each non-empty cell's *source* text (formulas
        included) with offsets from the top-left, so paste can preserve
        formulas and adjust their references.
        """
        g = self._g
        r0, r1 = sorted((int(r0), int(r1)))
        c0, c1 = sorted((int(c0), int(c1)))
        cells: list[dict[str, Any]] = []
        tsv_rows: list[str] = []
        for r in range(r0, r1 + 1):
            row: list[str] = []
            for c in range(c0, c1 + 1):
                cl = g.cell(c, r)
                if cl is not None and cl.type != EMPTY:
                    cells.append({"dr": r - r0, "dc": c - c0, "text": cl.text})
                row.append(cell_clip_value(cl))
            tsv_rows.append("\t".join(row))
        self._clip = {"r0": r0, "c0": c0, "cells": cells, "cut": bool(cut)}
        return {"ok": True, "tsv": "\n".join(tsv_rows)}

    def paste(self, r: int, c: int) -> dict[str, Any]:
        """Paste the internal buffer with its top-left at ``(r, c)``.

        Formula references are shifted by the paste offset (absolute ``$``
        refs stay put), matching replicate/Excel. A cut clears the source
        cells that the paste did not overwrite.
        """
        clip = self._clip
        if not clip:
            return {"ok": False}
        r, c = int(r), int(c)
        dcol, drow = c - clip["c0"], r - clip["r0"]
        g = self._g
        self._undo.save_grid(g)  # paste (and cut's source clear) can touch scattered cells
        dest = {(c + cell["dc"], r + cell["dr"]) for cell in clip["cells"]}
        for cell in clip["cells"]:
            dc, dr, text = cell["dc"], cell["dr"], cell["text"]
            tc, tr = c + dc, r + dr
            if not (0 <= tc < NCOL and 0 <= tr < NROW):
                continue
            g.setcell(tc, tr, adjust_refs(text, dcol, drow) if text.startswith("=") else text)
        if clip["cut"]:
            for cell in clip["cells"]:
                sc, sr = clip["c0"] + cell["dc"], clip["r0"] + cell["dr"]
                if (sc, sr) not in dest:
                    g.setcell(sc, sr, "")
            self._clip = None
        g.recalc()
        return {"ok": True}

    def paste_text(self, r: int, c: int, text: str) -> dict[str, Any]:
        """Paste external clipboard text (a TSV block) with top-left at ``(r, c)``.

        This is the paste-in path from another application (Excel, a browser
        table): the client reads the OS clipboard and hands the raw text here.
        Rows split on newline, columns on tab; a single trailing newline is
        ignored. Values are written *verbatim* -- unlike :meth:`paste`, no
        reference adjustment happens, because this text originated outside
        gridcalc and carries no relative-reference intent to preserve (a leading
        ``=`` still becomes a formula, matching a spreadsheet paste). The written
        rectangle is snapshotted first, so the paste is a single undo step.
        """
        if not text:
            return {"ok": False}
        rows = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if rows and rows[-1] == "":
            rows.pop()  # a lone trailing newline is not an extra blank row
        if not rows:
            return {"ok": False}
        r, c = int(r), int(c)
        g = self._g
        ncols = max(len(row.split("\t")) for row in rows)
        self._undo.save_region(g, c, r, c + ncols - 1, r + len(rows) - 1)
        for dr, row in enumerate(rows):
            for dc, val in enumerate(row.split("\t")):
                tc, tr = c + dc, r + dr
                if 0 <= tc < NCOL and 0 <= tr < NROW:
                    g.setcell(tc, tr, val)
        g.recalc()
        return {"ok": True, "rows": len(rows), "cols": ncols}

    def fill(self, r0: int, c0: int, r1: int, c1: int, direction: str) -> dict[str, Any]:
        """Fill a selection from its leading edge (Ctrl+D down / Ctrl+R right).

        ``down`` copies the top row of the rectangle into the rows below;
        ``right`` copies the left column into the columns to its right.
        Formula references are shifted per destination (via ``adjust_refs``),
        so ``=A1`` filled down becomes ``=A2``, ``=A3``, ...
        """
        g = self._g
        r0, r1 = sorted((int(r0), int(r1)))
        c0, c1 = sorted((int(c0), int(c1)))
        if direction not in ("down", "right"):
            return {"ok": False}
        self._undo.save_region(g, c0, r0, c1, r1)
        if direction == "down":
            for c in range(c0, c1 + 1):
                src = g.cell(c, r0)
                text = src.text if src is not None and src.type != EMPTY else ""
                for r in range(r0 + 1, r1 + 1):
                    g.setcell(c, r, adjust_refs(text, 0, r - r0) if text.startswith("=") else text)
        elif direction == "right":
            for r in range(r0, r1 + 1):
                src = g.cell(c0, r)
                text = src.text if src is not None and src.type != EMPTY else ""
                for c in range(c0 + 1, c1 + 1):
                    g.setcell(c, r, adjust_refs(text, c - c0, 0) if text.startswith("=") else text)
        else:
            return {"ok": False}
        g.recalc()
        return {"ok": True}

    def save(self, path: str | None = None) -> dict[str, Any]:
        """Write the workbook to ``path`` or its current filename.

        Format follows the extension: ``.xlsx`` / ``.csv`` / otherwise JSON.
        Returns ``{"ok": True, "path": ...}`` on success, ``{"needs_path":
        True}`` when there is no filename to save to (the demo), so the client
        can prompt via :meth:`save_dialog`.
        """
        g = self._g
        target = path or (getattr(g, "filename", "") or "")
        if not target:
            return {"ok": False, "needs_path": True}
        low = target.lower()
        if low.endswith(".xlsx"):
            rc = g.xlsxsave(target)
        elif low.endswith(".csv"):
            rc = g.csvsave(target)
        else:
            rc = g.jsonsave(target)
        if rc < 0:
            return {"ok": False, "error": f"could not save: {target}"}
        g.filename = target
        return {"ok": True, "path": target}

    def save_dialog(self) -> dict[str, Any]:
        """Prompt for a path with the native save dialog, then save there."""
        win = self._window
        if win is None:
            return {"ok": False}
        import webview  # lazy: only for the SAVE_DIALOG constant

        default = getattr(self._g, "filename", "") or "workbook.json"
        result = win.create_file_dialog(webview.SAVE_DIALOG, save_filename=default)
        if not result:
            return {"ok": False, "cancelled": True}
        path = result if isinstance(result, str) else result[0]
        return self.save(path)

    def open_file(self, path: str) -> dict[str, Any]:
        """Load a different workbook into this window, replacing the current one.

        The engine model is swapped for the freshly loaded one and the
        per-workbook UI state that would otherwise dangle -- undo/redo history
        and the copy buffer -- is reset, since neither is meaningful against a
        different sheet. Returns ``{"ok": True, "filename": ...}`` so the client
        can re-fetch dimensions, redraw the tabs, and reset the cursor; a load
        failure comes back as ``{"ok": False, "error": ...}`` and leaves the
        current workbook untouched.
        """
        try:
            g = load_workbook(path)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        self._g = g
        self._undo = UndoManager()
        self._clip = None
        self._retitle()
        return {"ok": True, "filename": getattr(g, "filename", "") or ""}

    def open_dialog(self) -> dict[str, Any]:
        """Prompt for a workbook with the native open dialog, then load it."""
        win = self._window
        if win is None:
            return {"ok": False}
        import webview  # lazy: only for the OPEN_DIALOG constant

        result = win.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=("Workbook files (*.json;*.xlsx;*.csv)", "All files (*.*)"),
        )
        if not result:
            return {"ok": False, "cancelled": True}
        path = result if isinstance(result, str) else result[0]
        return self.open_file(path)

    def _retitle(self) -> None:
        """Best-effort window-title refresh after the workbook changes."""
        win = self._window
        if win is None:
            return
        name = getattr(self._g, "filename", "") or "(demo)"
        with contextlib.suppress(Exception):
            win.set_title(f"gridcalc - {name}")

    def chart_data(self, spec: str) -> dict[str, Any]:
        """Chart-ready data for an A1 range like ``A4:D6``.

        Frontend-agnostic shape -- ``{title, labels, series:[{name, values}]}``
        -- the same a Plotly/ECharts renderer would consume, so the current
        inline-SVG view can be swapped for a real charting library without the
        Python side changing. The leftmost column becomes the category labels
        when the range spans more than one column and that column holds text;
        otherwise labels are row numbers. Each remaining column is one numeric
        series (non-numeric cells become ``None``, i.e. a gap).
        """
        rect = self._parse_range(spec)
        if rect is None:
            return {"error": f"bad range: {spec}"}
        c0, r0, c1, r1 = rect
        rows = list(range(r0, r1 + 1))
        cols = list(range(c0, c1 + 1))

        label_col = None
        if len(cols) > 1 and any(self._is_label(c0, r) for r in rows):
            label_col = c0
        if label_col is not None:
            labels = [self._label_at(label_col, r) for r in rows]
            series_cols = [c for c in cols if c != label_col]
        else:
            labels = [str(r + 1) for r in rows]
            series_cols = cols

        series = [
            {"name": col_name(c), "values": [self._num_at(c, r) for r in rows]} for c in series_cols
        ]
        return {"title": spec.strip().upper(), "labels": labels, "series": series}

    # -- optimization -----------------------------------------------------

    def solve_selection(
        self, r0: int, c0: int, r1: int, c1: int, sense: str = "max"
    ) -> dict[str, Any]:
        """Infer an LP/MIP from a rectangular selection and solve it.

        Mirrors ``:opt max`` / ``:opt min`` over a visual selection: the
        objective, decision, and constraint cells are inferred from the block
        (``opt.infer_model``), then solved with sensitivity and diagnostics on.
        On success the decision cells are written and the grid recalculated.
        """
        g = self._g
        ra, rb = sorted((int(r0), int(r1)))
        ca, cb = sorted((int(c0), int(c1)))
        try:
            m = opt.infer_model(g, ca, ra, cb, rb)
        except opt.OptError as exc:
            return {"ok": False, "error": str(exc)}
        return self._run_solve(
            objective=m.objective,
            decision_vars=m.decision_vars,
            constraint_cells=m.constraint_cells,
            maximize=(sense != "min"),
        )

    def solve_model(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Solve an explicit A1-specified model.

        ``spec`` keys: ``sense`` ('max'|'min'), ``objective`` ('B2'), ``vars``
        ('A2:A3'), ``constraints`` ('C2:C4'), and optional ``bounds``
        ('A1=0:10'), ``integers`` / ``binaries`` (cell-list specs), and
        ``sensitivity`` / ``diagnose`` / ``apply`` (bools, default true/true/true).
        """
        try:
            objective = self._key(spec["objective"])
            decision_vars = parse_cells(spec["vars"])
            cons = spec.get("constraints", "")
            constraint_cells = parse_cells(cons) if cons else []
            bounds = parse_bounds(spec["bounds"]) if spec.get("bounds") else None
            integer_vars = set(parse_cells(spec["integers"])) if spec.get("integers") else None
            binary_vars = set(parse_cells(spec["binaries"])) if spec.get("binaries") else None
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": f"bad model spec: {exc}"}
        return self._run_solve(
            objective=objective,
            decision_vars=decision_vars,
            constraint_cells=constraint_cells,
            maximize=(spec.get("sense", "max") != "min"),
            bounds=bounds,
            integer_vars=integer_vars,
            binary_vars=binary_vars,
            sensitivity=bool(spec.get("sensitivity", True)),
            diagnose=bool(spec.get("diagnose", True)),
            apply=bool(spec.get("apply", True)),
        )

    def goal_seek(
        self,
        formula_ref: str,
        target: float,
        var_ref: str,
        lo: float | None = None,
        hi: float | None = None,
        apply: bool = True,
    ) -> dict[str, Any]:
        """Adjust ``var_ref`` so ``formula_ref`` evaluates to ``target``.

        Mirrors ``:goal <formula> = <target> by <var> [in lo:hi]``. An applied
        seek writes the variable cell and recalculates; it is undo-wrapped.
        """
        g = self._g
        try:
            fc = self._key(formula_ref)
            vc = self._key(var_ref)
            tgt = float(target)
            lo_f = None if lo is None else float(lo)
            hi_f = None if hi is None else float(hi)
        except (ValueError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}
        if apply:
            self._undo.save_grid(g)
        try:
            res = goalseek.seek(g, fc, tgt, vc, lo=lo_f, hi=hi_f, apply=apply)
        except goalseek.GoalSeekError as exc:
            if apply:
                self._undo.discard_last()
            return {"ok": False, "error": str(exc)}
        if apply and not res.applied:
            self._undo.discard_last()
        return {
            "ok": True,
            "converged": res.converged,
            "iterations": res.iterations,
            "var_value": res.var_value,
            "formula_value": res.formula_value,
            "residual": res.residual,
            "applied": res.applied,
        }

    def opt_sweep(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Parametric right-hand-side sweep -- what-if, never mutates the sheet.

        ``spec`` extends :meth:`solve_model`'s with ``constraint`` (the swept
        constraint cell), ``lo`` / ``hi`` (the RHS range), and ``steps``
        (default 10). Returns one point per RHS with objective, status, and the
        swept constraint's shadow price; ``breakpoint`` flags where the marginal
        value changed.
        """
        try:
            objective = self._key(spec["objective"])
            decision_vars = parse_cells(spec["vars"])
            cons = spec.get("constraints", "")
            constraint_cells = parse_cells(cons) if cons else []
            constraint = self._key(spec["constraint"])
            bounds = parse_bounds(spec["bounds"]) if spec.get("bounds") else None
            integer_vars = set(parse_cells(spec["integers"])) if spec.get("integers") else None
            binary_vars = set(parse_cells(spec["binaries"])) if spec.get("binaries") else None
            lo = float(spec["lo"])
            hi = float(spec["hi"])
            steps = int(spec.get("steps", 10))
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": f"bad sweep spec: {exc}"}
        try:
            pts = opt.sweep(
                self._g,
                objective,
                decision_vars,
                constraint_cells,
                constraint=constraint,
                lo=lo,
                hi=hi,
                steps=steps,
                maximize=(spec.get("sense", "max") != "min"),
                bounds=bounds,
                integer_vars=integer_vars,
                binary_vars=binary_vars,
            )
        except opt.OptError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "points": [
                {
                    "rhs": p.rhs,
                    "status": p.status_name,
                    "objective": self._num(p.objective),
                    "shadow_price": self._num(p.shadow_price),
                    "delta": self._num(p.delta),
                    "breakpoint": p.breakpoint,
                }
                for p in pts
            ],
        }

    def _run_solve(
        self,
        *,
        objective: tuple[int, int],
        decision_vars: list[tuple[int, int]],
        constraint_cells: list[tuple[int, int]],
        maximize: bool,
        bounds: dict[tuple[int, int], tuple[float, float]] | None = None,
        integer_vars: set[tuple[int, int]] | None = None,
        binary_vars: set[tuple[int, int]] | None = None,
        sensitivity: bool = True,
        diagnose: bool = True,
        apply: bool = True,
    ) -> dict[str, Any]:
        """Call ``opt.solve`` with undo wrapping and JSON-serialize the result.

        An applied solve overwrites decision cells and recalculates dependents,
        so the grid is snapshotted first. The snapshot is dropped again when the
        solve raised or came back non-optimal (nothing was written), keeping the
        undo history free of no-op entries.
        """
        g = self._g
        if apply:
            self._undo.save_grid(g)
        try:
            res = opt.solve(
                g,
                objective,
                decision_vars,
                constraint_cells,
                maximize=maximize,
                bounds=bounds,
                integer_vars=integer_vars,
                binary_vars=binary_vars,
                apply=apply,
                sensitivity=sensitivity,
                diagnose=diagnose,
            )
        except opt.OptError as exc:
            if apply:
                self._undo.discard_last()
            return {"ok": False, "error": str(exc)}
        if apply and not res.applied:
            self._undo.discard_last()
        return {"ok": True, **self._solve_json(res)}

    def _solve_json(self, res: opt.SolveResult) -> dict[str, Any]:
        """Serialize a ``SolveResult`` to JSON-safe, A1-keyed data."""
        out: dict[str, Any] = {
            "status": res.status_name,
            "optimal": res.status_name == "OPTIMAL",
            "objective": self._num(res.objective),
            "values": {self._a1(k): v for k, v in res.values.items()},
            "applied": res.applied,
            "quadratic": res.quadratic,
        }
        if res.sensitivity is not None:
            out["sensitivity"] = {
                "variables": [
                    {
                        "cell": self._a1(v.cell),
                        "value": v.value,
                        "reduced_cost": v.reduced_cost,
                        "obj_coef": v.obj_coef,
                        "obj_from": self._num(v.obj_from),
                        "obj_till": self._num(v.obj_till),
                    }
                    for v in res.sensitivity.variables
                ],
                "constraints": [
                    {
                        "cell": self._a1(c.cell),
                        "shadow_price": c.shadow_price,
                        "rhs": c.rhs,
                        "activity": c.activity,
                        "slack": c.slack,
                        "binding": c.binding,
                        "rhs_from": self._num(c.rhs_from),
                        "rhs_till": self._num(c.rhs_till),
                    }
                    for c in res.sensitivity.constraints
                ],
            }
        if res.conflict is not None:
            out["conflict"] = [self._a1(k) for k in res.conflict]
        if res.unbounded is not None:
            out["unbounded"] = [self._a1(k) for k in res.unbounded]
        return out

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _key(a1: str) -> tuple[int, int]:
        """Parse a single A1 ref to ``(col, row)``; reject trailing garbage."""
        s = (a1 or "").strip().replace("$", "")
        m = ref(s)
        if m is None or m[0] != len(s):
            raise ValueError(f"bad cell ref: {a1!r}")
        _, c, r = m
        return (c, r)

    @staticmethod
    def _a1(key: tuple[int, int]) -> str:
        """Render ``(col, row)`` as an A1 reference."""
        c, r = key
        return f"{col_name(c)}{r + 1}"

    @staticmethod
    def _num(x: Any) -> float | None:
        """inf/nan -> None; JSON (and the pywebview bridge) cannot carry them."""
        return x if isinstance(x, (int, float)) and math.isfinite(x) else None

    @staticmethod
    def _parse_range(spec: str) -> tuple[int, int, int, int] | None:
        """Parse ``A1`` or ``A1:B3`` into ``(c0, r0, c1, r1)``, normalized."""
        s = (spec or "").strip().replace("$", "")
        if not s:
            return None
        a, _, b = s.partition(":")
        b = b or a
        ra, rb = ref(a.strip()), ref(b.strip())
        if ra is None or rb is None:
            return None
        na, ca, rowa = ra
        nb, cb, rowb = rb
        if na != len(a.strip()) or nb != len(b.strip()):
            return None  # trailing garbage -> not a clean ref
        c0, c1 = sorted((ca, cb))
        r0, r1 = sorted((rowa, rowb))
        return c0, r0, c1, r1

    def _is_label(self, c: int, r: int) -> bool:
        cl = self._g.cell(c, r)
        return cl is not None and cl.type == LABEL

    def _label_at(self, c: int, r: int) -> str:
        cl = self._g.cell(c, r)
        if cl is None or cl.type == EMPTY:
            return ""
        return cell_text(cl, self._g.fmt)

    def _num_at(self, c: int, r: int) -> float | None:
        cl = self._g.cell(c, r)
        if cl is None or cl.type not in (NUM, FORMULA, SPILL):
            return None
        v = cl.val
        if not isinstance(v, (int, float)) or math.isnan(v) or math.isinf(v):
            return None
        return float(v)


def run(path: str | None = None) -> None:
    """Open the editable grid in a desktop webview window."""
    import webview  # lazy: only needed to open a window

    g = load_workbook(path) if path else demo_grid()
    api = Api(g)
    name = getattr(g, "filename", "") or "(demo)"
    api._window = webview.create_window(
        f"gridcalc - {name}",
        html=_HTML,
        js_api=api,
        width=1200,
        height=800,
        min_size=(640, 400),
    )
    webview.start()


def run_cli() -> None:
    """Console-script entry point (``gridcalc-web``)."""
    import sys

    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print("Usage: gridcalc-web [workbook.json | workbook.xlsx]")
        return
    run(args[0] if args else None)


# The view. Deliberately dependency-free (no framework, no build step): a
# single inline document that talks to the Python `Api` through
# `window.pywebview.api`. It virtualizes rendering -- only cells inside the
# scrolled viewport are put in the DOM -- so the full 256x1024 sheet scrolls
# without 260k nodes. Double-click a cell to edit; Enter commits, Esc cancels.
_HTML = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  :root { --cw: 90px; --ch: 22px; --gw: 52px; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; font: 13px/1.4 -apple-system, system-ui, sans-serif;
               background: #1e1e1e; color: #e6e6e6; overflow: hidden; }
  #topbar { height: 26px; display: flex; align-items: center; justify-content: space-between;
            padding: 0 6px; background: #252526; border-bottom: 1px solid #333; }
  #tabs { display: flex; align-items: center; gap: 2px; }
  #toolbar { display: flex; align-items: center; gap: 6px; }
  #cellref { color: #9cdcfe; min-width: 56px; font-weight: 600;
             font-variant-numeric: tabular-nums; }
  #saveStatus { color: #59a14f; min-width: 64px; text-align: right; }
  #chartRange { width: 92px; background: #1e1e1e; color: #e6e6e6; border: 1px solid #444;
                border-radius: 3px; padding: 1px 5px; font: inherit; }
  #chartBtn, #solveBtn { background: #0e639c; color: #fff; border: none; border-radius: 3px;
              padding: 2px 12px; cursor: pointer; font: inherit; }
  #optSense { background: #1e1e1e; color: #e6e6e6; border: 1px solid #444;
              border-radius: 3px; font: inherit; }
  #optStatus { color: #9cdcfe; min-width: 72px; font-variant-numeric: tabular-nums; }
  #chart { position: absolute; right: 16px; top: 40px; width: 480px; height: 320px;
           background: #252526; border: 1px solid #444; border-radius: 6px;
           box-shadow: 0 6px 24px rgba(0,0,0,.5); display: none; z-index: 20; }
  #chartClose { position: absolute; right: 6px; top: 3px; background: transparent;
                color: #bbb; border: none; cursor: pointer; font-size: 15px; }
  #chartSvg { width: 100%; height: 100%; }
  #goalBtn { background: #0e639c; color: #fff; border: none; border-radius: 3px;
             padding: 2px 12px; cursor: pointer; font: inherit; }
  .panel { position: absolute; right: 16px; top: 40px; background: #252526;
           border: 1px solid #444; border-radius: 6px; box-shadow: 0 6px 24px rgba(0,0,0,.5);
           display: none; z-index: 25; color: #e6e6e6; }
  #optPanel { width: 540px; max-height: 74vh; overflow: auto; padding: 8px 12px 12px; }
  #goalDialog { width: 320px; padding: 10px 12px 12px; }
  .panelClose { position: absolute; right: 6px; top: 3px; background: transparent;
                color: #bbb; border: none; cursor: pointer; font-size: 15px; }
  .panelTitle { font-weight: 600; margin: 8px 0 4px; }
  .panelTitle:first-child { margin-top: 0; }
  .badge { display: inline-block; padding: 0 6px; border-radius: 3px; font-size: 11px;
           font-weight: 600; margin-left: 8px; vertical-align: 1px; }
  .badge.ok { background: #2d5a2d; color: #b6f0b6; }
  .badge.bad { background: #5a2d2d; color: #f0b6b6; }
  .optObj { margin: 4px 0 8px; font-variant-numeric: tabular-nums; }
  table.sens { border-collapse: collapse; width: 100%; margin: 2px 0 6px;
               font-variant-numeric: tabular-nums; font-size: 12px; }
  table.sens th, table.sens td { border: 1px solid #3a3a3a; padding: 1px 6px; text-align: right; }
  table.sens th { background: #2d2d2d; color: #9cdcfe; font-weight: 600; }
  table.sens td.k, table.sens th.k { text-align: left; color: #9cdcfe; }
  .sensNote { color: #c8a24a; margin: 2px 0 8px; }
  .diag { color: #f0b6b6; margin: 2px 0 6px; }
  .goalRow { display: flex; align-items: center; gap: 6px; margin: 5px 0; }
  .goalRow label { width: 78px; color: #bbb; flex: none; }
  .goalRow input { flex: 1; min-width: 0; background: #1e1e1e; color: #e6e6e6;
                   border: 1px solid #444; border-radius: 3px; padding: 1px 5px; font: inherit; }
  #goalRun { background: #0e639c; color: #fff; border: none; border-radius: 3px;
             padding: 3px 14px; cursor: pointer; font: inherit; margin-top: 8px; }
  #goalResult { margin-top: 8px; font-variant-numeric: tabular-nums; color: #9cdcfe; }
  .tab { padding: 2px 10px; border-radius: 4px 4px 0 0; cursor: pointer; color: #bbb; }
  .tab.active { background: #0e639c; color: #fff; }
  #scroll { position: absolute; top: 27px; left: 0; right: 0; bottom: 0; overflow: auto; }
  #canvas { position: relative; }
  .cell, .hdr, .gut { position: absolute; height: var(--ch); line-height: var(--ch);
                      padding: 0 5px; overflow: hidden; white-space: nowrap;
                      border-right: 1px solid #333; border-bottom: 1px solid #333; }
  .cell.r { text-align: right; }
  /* headers/gutter stay absolute (like cells) and are re-pinned to the scroll
     offset each frame in JS; `position: sticky` here would drop them into
     normal flow and stagger them diagonally. */
  .selrect { position: absolute; background: rgba(14, 99, 156, .18);
             border: 1px solid rgba(14, 99, 156, .5); pointer-events: none; z-index: 3; }
  .cursor { position: absolute; border: 2px solid #0e639c; pointer-events: none; z-index: 4; }
  .fillhandle { position: absolute; width: 7px; height: 7px; background: #0e639c;
                border: 1px solid #fff; cursor: crosshair; z-index: 5; }
  /* frozen chrome sits above the selection/cursor overlays so they never paint
     over the header row or gutter when a selection scrolls under them. */
  .hdr { background: #2d2d2d; color: #9cdcfe; text-align: center; font-weight: 600; z-index: 9; }
  .gut { background: #2d2d2d; color: #888; text-align: right; z-index: 8; }
  #corner { position: absolute; z-index: 10; background: #2d2d2d;
            width: var(--gw); height: var(--ch); border-right: 1px solid #333;
            border-bottom: 1px solid #333; }
  #editor { position: absolute; height: var(--ch); border: 2px solid #0e639c; padding: 0 3px;
            font: inherit; background: #fff; color: #000; display: none; z-index: 15; }
</style>
</head>
<body>
<div id="topbar">
  <div id="tabs"></div>
  <div id="toolbar">
    <span id="saveStatus"></span>
    <span id="cellref">A1</span>
    <input id="chartRange" placeholder="A4:D6" spellcheck="false">
    <button id="chartBtn">Chart</button>
    <select id="optSense" title="objective sense">
      <option value="max">max</option>
      <option value="min">min</option>
    </select>
    <button id="solveBtn" title="optimize the selection (:opt)">Solve</button>
    <button id="goalBtn" title="goal seek (:goal)">Goal</button>
    <span id="optStatus"></span>
  </div>
</div>
<div id="scroll"><div id="canvas"><input id="editor"></div></div>
<div id="chart">
  <button id="chartClose" title="close">&times;</button><svg id="chartSvg"></svg>
</div>
<div id="optPanel" class="panel">
  <button class="panelClose" data-close="optPanel" title="close">&times;</button>
  <div id="optBody"></div>
</div>
<div id="goalDialog" class="panel">
  <button class="panelClose" data-close="goalDialog" title="close">&times;</button>
  <div class="panelTitle">Goal seek</div>
  <div class="goalRow"><label>Set cell</label>
    <input id="goalCell" placeholder="B1" spellcheck="false"></div>
  <div class="goalRow"><label>To value</label>
    <input id="goalTarget" placeholder="0" spellcheck="false"></div>
  <div class="goalRow"><label>By cell</label>
    <input id="goalVar" placeholder="A1" spellcheck="false"></div>
  <div class="goalRow"><label>Bracket</label>
    <input id="goalLo" placeholder="lo (opt)" spellcheck="false">
    <input id="goalHi" placeholder="hi (opt)" spellcheck="false"></div>
  <button id="goalRun">Run</button>
  <div id="goalResult"></div>
</div>
<script>
const CW = 90, CH = 22, GW = 52, PAD = 4;   // px; PAD = extra rows/cols rendered off-screen
let NCOL = 256, NROW = 1024, FMT = {};
const scroll = document.getElementById('scroll');
const canvas = document.getElementById('canvas');
const editor = document.getElementById('editor');
let editing = null;   // {r, c} currently being edited
let cur = { r: 0, c: 0 };      // active cell
let anchor = { r: 0, c: 0 };   // selection anchor (fixed end of a shift-extend)
// Formula "point mode": while editing a formula, clicking/dragging the grid
// inserts a reference into the editor instead of moving the selection.
let pointStart = null;   // editor caret index where the inserted ref begins
let pointLen = 0;        // length of the currently inserted ref
let pointAnchor = null;  // {r, c} anchor of the pointed range
let pointing = false;    // true while dragging out a pointed range
let fillFrom = null;     // selection rect when a fill-handle drag started
let filling = false;     // true while dragging the fill handle
let lastCopyTsv = null;  // TSV of the last in-app copy, to tell it apart from
                         // a paste-in of OS-clipboard text from another app

function colName(c) {              // 0 -> A, 26 -> AA (bijective base-26)
  let s = '';
  c += 1;
  while (c > 0) { c -= 1; s = String.fromCharCode(65 + (c % 26)) + s; c = Math.floor(c / 26); }
  return s;
}

async function renderTabs() {
  const info = await window.pywebview.api.sheets();
  const el = document.getElementById('tabs');
  el.innerHTML = '';
  info.names.forEach((name, i) => {
    const t = document.createElement('div');
    t.className = 'tab' + (i === info.active ? ' active' : '');
    t.textContent = name;
    t.onclick = async () => { await window.pywebview.api.set_active(i); renderTabs(); render(); };
    el.appendChild(t);
  });
}

// Open a different workbook into the running window (Ctrl+O). The Api swaps in
// the loaded model and resets its undo/clipboard; the view resets to the new
// sheet's top-left and redraws.
async function openFile() {
  const res = await window.pywebview.api.open_dialog();
  if (!res || !res.ok) {
    if (res && res.error) flashSave('open failed');
    return;
  }
  const d = await window.pywebview.api.dims();
  NCOL = d.ncol; NROW = d.nrow;
  editing = null; editor.style.display = 'none';
  scroll.scrollTop = 0; scroll.scrollLeft = 0;
  setCursor(0, 0, false);
  await renderTabs();
  render();
}

async function renderOnce() {
  const sx = scroll.scrollLeft, sy = scroll.scrollTop;
  const w = scroll.clientWidth, h = scroll.clientHeight;
  const c0 = Math.max(0, Math.floor((sx - GW) / CW) - PAD);
  const r0 = Math.max(0, Math.floor((sy - CH) / CH) - PAD);
  const cols = Math.ceil(w / CW) + 2 * PAD + 1;
  const rows = Math.ceil(h / CH) + 2 * PAD + 1;
  const c1 = Math.min(NCOL, c0 + cols), r1 = Math.min(NROW, r0 + rows);

  const vp = await window.pywebview.api.viewport(r0, c0, r1 - r0, c1 - c0);
  const frag = document.createDocumentFragment();

  // Column headers (sticky top) + row gutters (sticky left).
  for (let c = c0; c < c1; c++) {
    const hd = document.createElement('div');
    hd.className = 'hdr';
    hd.style.left = (GW + c * CW) + 'px'; hd.style.top = sy + 'px';
    hd.style.width = CW + 'px'; hd.textContent = colName(c);
    frag.appendChild(hd);
  }
  for (let r = r0; r < r1; r++) {
    const g = document.createElement('div');
    g.className = 'gut';
    g.style.left = sx + 'px'; g.style.top = (CH + r * CH) + 'px';
    g.style.width = GW + 'px'; g.textContent = (r + 1);
    frag.appendChild(g);
  }
  // Populated cells.
  for (const cell of vp.cells) {
    const d = document.createElement('div');
    d.className = 'cell' + (cell.align === 'r' ? ' r' : '');
    d.style.left = (GW + cell.c * CW) + 'px';
    d.style.top = (CH + cell.r * CH) + 'px';
    d.style.width = CW + 'px';
    d.textContent = cell.text;
    frag.appendChild(d);
  }

  // Rebuild the canvas (keep the editor node).
  [...canvas.querySelectorAll('.cell, .hdr, .gut')].forEach(n => n.remove());
  canvas.appendChild(frag);
  canvas.style.width = (GW + NCOL * CW) + 'px';
  canvas.style.height = (CH + NROW * CH) + 'px';

  const corner = document.getElementById('corner') || (() => {
    const el = document.createElement('div'); el.id = 'corner'; canvas.appendChild(el); return el;
  })();
  corner.style.left = sx + 'px'; corner.style.top = sy + 'px';

  positionOverlays();
}

// Position the selection rectangle (hidden when it is a single cell) and the
// active-cell cursor. Both live in canvas coordinates so they scroll with the
// content. Split out of renderOnce so a plain cursor move can reposition them
// *without* rebuilding the cell DOM -- rebuilding on mousedown would replace
// the element under the pointer and suppress the browser's dblclick.
function positionOverlays() {
  const s = selRect();
  const single = (s.r0 === s.r1 && s.c0 === s.c1);
  const selEl = ensureOverlay('selrect', 'selrect');
  selEl.style.display = single ? 'none' : 'block';
  selEl.style.left = (GW + s.c0 * CW) + 'px';
  selEl.style.top = (CH + s.r0 * CH) + 'px';
  selEl.style.width = ((s.c1 - s.c0 + 1) * CW) + 'px';
  selEl.style.height = ((s.r1 - s.r0 + 1) * CH) + 'px';
  const curEl = ensureOverlay('cursor', 'cursor');
  curEl.style.left = (GW + cur.c * CW) + 'px';
  curEl.style.top = (CH + cur.r * CH) + 'px';
  curEl.style.width = CW + 'px';
  curEl.style.height = CH + 'px';
  // Fill handle at the selection's bottom-right corner.
  const fh = ensureOverlay('fillhandle', 'fillhandle');
  fh.style.left = (GW + (s.c1 + 1) * CW - 4) + 'px';
  fh.style.top = (CH + (s.r1 + 1) * CH - 4) + 'px';
}

function ensureOverlay(id, cls) {
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement('div'); el.id = id; el.className = cls;
    canvas.appendChild(el);
  }
  return el;
}

// Coalesce bursts of scroll events: renders never overlap (an interleaved
// async rebuild would tear the DOM), and a scroll during a render queues one
// more pass so the final frame always matches the latest scroll position.
let rendering = false, dirty = false;
async function render() {
  dirty = true;
  if (rendering) return;
  rendering = true;
  while (dirty) { dirty = false; await renderOnce(); }
  rendering = false;
}

function cellAt(x, y) {
  const c = Math.floor((x + scroll.scrollLeft - GW) / CW);
  const r = Math.floor((y + scroll.scrollTop - CH) / CH);
  if (c < 0 || r < 0 || c >= NCOL || r >= NROW) return null;
  return { r, c };
}

// --- selection + active cell ---
function selRect() {
  return {
    r0: Math.min(cur.r, anchor.r), c0: Math.min(cur.c, anchor.c),
    r1: Math.max(cur.r, anchor.r), c1: Math.max(cur.c, anchor.c),
  };
}
function selRef() {          // A1 for a single cell, A1:B3 for a range
  const s = selRect();
  const a = colName(s.c0) + (s.r0 + 1);
  if (s.r0 === s.r1 && s.c0 === s.c1) return a;
  return a + ':' + colName(s.c1) + (s.r1 + 1);
}
function clamp(v, hi) { return Math.max(0, Math.min(hi - 1, v)); }

function setCursor(r, c, extend) {
  cur = { r: clamp(r, NROW), c: clamp(c, NCOL) };
  if (!extend) anchor = { ...cur };
  document.getElementById('cellref').textContent = selRef();
  document.getElementById('chartRange').value = selRef();   // selection drives the chart
  positionOverlays();          // move overlays only -- no cell rebuild
  scrollCursorIntoView();      // if this scrolls, the scroll handler re-renders
}
function scrollCursorIntoView() {
  const l = GW + cur.c * CW, t = CH + cur.r * CH;
  if (l < scroll.scrollLeft + GW) scroll.scrollLeft = l - GW;
  else if (l + CW > scroll.scrollLeft + scroll.clientWidth)
    scroll.scrollLeft = l + CW - scroll.clientWidth;
  if (t < scroll.scrollTop + CH) scroll.scrollTop = t - CH;
  else if (t + CH > scroll.scrollTop + scroll.clientHeight)
    scroll.scrollTop = t + CH - scroll.clientHeight;
}

async function beginEdit(r, c, initial) {
  editing = { r, c };
  cur = { r, c }; anchor = { r, c };
  pointStart = null; pointLen = 0; pointAnchor = null; pointing = false;
  const src = initial !== undefined ? initial : await window.pywebview.api.cell_source(r, c);
  editor.value = src;
  editor.style.left = (GW + c * CW) + 'px';
  editor.style.top = (CH + r * CH) + 'px';
  editor.style.width = CW + 'px';
  editor.style.display = 'block';
  editor.focus();
  if (initial === undefined) editor.select();
  else editor.setSelectionRange(src.length, src.length);
}

async function commitEdit(move) {
  if (!editing) return;
  const { r, c } = editing;
  editing = null;
  editor.style.display = 'none';
  await window.pywebview.api.set_cell(r, c, editor.value);
  if (move === 'down') setCursor(r + 1, c, false);
  else if (move === 'right') setCursor(r, c + 1, false);
  else if (move === 'left') setCursor(r, c - 1, false);
  else render();
}

// --- formula point mode ---
function inFormula() { return editing && editor.value.startsWith('='); }
function refBetween(a, b) {
  const r0 = Math.min(a.r, b.r), c0 = Math.min(a.c, b.c);
  const r1 = Math.max(a.r, b.r), c1 = Math.max(a.c, b.c);
  const A = colName(c0) + (r0 + 1);
  return (r0 === r1 && c0 === c1) ? A : A + ':' + colName(c1) + (r1 + 1);
}
function insertPointRef(text) {
  // Replace the previously inserted ref span (if this is a continued point,
  // e.g. a drag or shift-click) or insert a fresh one at the caret.
  if (pointStart === null) { pointStart = editor.selectionStart; pointLen = 0; }
  const v = editor.value;
  editor.value = v.slice(0, pointStart) + text + v.slice(pointStart + pointLen);
  pointLen = text.length;
  const caret = pointStart + pointLen;
  editor.setSelectionRange(caret, caret);
  editor.focus();
}
function pointAt(hit, extend) {
  if (extend && pointAnchor) {
    insertPointRef(refBetween(pointAnchor, hit));
  } else {
    pointAnchor = { ...hit };
    insertPointRef(refBetween(hit, hit));
  }
  cur = { ...hit }; anchor = { ...pointAnchor };
  positionOverlays();   // highlight the pointed range without a cell rebuild
}

scroll.addEventListener('scroll', () => { if (!editing) render(); });
scroll.addEventListener('mousedown', (e) => {
  if (e.target.id === 'fillhandle') {   // start a fill-handle drag
    e.preventDefault();
    fillFrom = selRect();
    filling = true;
    return;
  }
  if (e.target.closest('#chart')) return;
  const hit = cellAt(e.clientX, e.clientY - 27);
  if (!hit) return;
  if (inFormula()) {
    e.preventDefault();          // keep the editor focused; point, do not select
    pointAt(hit, e.shiftKey);
    pointing = true;
    return;
  }
  if (editing) commitEdit();     // clicking away from a non-formula edit commits it
  setCursor(hit.r, hit.c, e.shiftKey);
});
scroll.addEventListener('mousemove', (e) => {
  if (filling && e.buttons === 1) {   // extend the fill region, locked to one axis
    const hit = cellAt(e.clientX, e.clientY - 27);
    if (!hit) return;
    const dR = hit.r - fillFrom.r1, dC = hit.c - fillFrom.c1;
    if (Math.abs(dR) >= Math.abs(dC)) cur = { r: Math.max(fillFrom.r0, hit.r), c: fillFrom.c1 };
    else cur = { r: fillFrom.r1, c: Math.max(fillFrom.c0, hit.c) };
    anchor = { r: fillFrom.r0, c: fillFrom.c0 };
    positionOverlays();
    return;
  }
  if (!pointing || e.buttons !== 1 || !pointAnchor) return;
  const hit = cellAt(e.clientX, e.clientY - 27);
  if (hit) pointAt(hit, true);   // extend the pointed range as the drag moves
});
window.addEventListener('mouseup', async () => {
  if (filling) {
    filling = false;
    const s = selRect();
    const dir = s.r1 > fillFrom.r1 ? 'down' : (s.c1 > fillFrom.c1 ? 'right' : null);
    if (dir) { await window.pywebview.api.fill(s.r0, s.c0, s.r1, s.c1, dir); render(); }
    return;
  }
  pointing = false;
});
scroll.addEventListener('dblclick', (e) => {
  if (editing) return;
  const hit = cellAt(e.clientX, e.clientY - 27);
  if (hit) beginEdit(hit.r, hit.c);
});
editor.addEventListener('input', () => {
  // Typing finalizes any pointed ref, so the next click starts a fresh one.
  pointStart = null; pointLen = 0; pointAnchor = null;
});
editor.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); commitEdit('down'); }
  else if (e.key === 'Tab') { e.preventDefault(); commitEdit(e.shiftKey ? 'left' : 'right'); }
  else if (e.key === 'Escape') { editing = null; editor.style.display = 'none'; }
});

// True when focus is in a toolbar/dialog field (chart range, sense select, the
// goal-seek inputs) -- keystrokes there must not drive grid navigation or start
// a cell edit. The in-cell editor is excluded: its own `editing` guard handles it.
function _inField() {
  const ae = document.activeElement;
  return !!ae && (ae.tagName === 'INPUT' || ae.tagName === 'SELECT') && ae.id !== 'editor';
}

document.addEventListener('keydown', (e) => {
  if (editing) return;                                  // editor owns its keys
  if (_inField()) return;                               // typing in a field, not navigating
  const ext = e.shiftKey;
  switch (e.key) {
    case 'ArrowUp': setCursor(cur.r - 1, cur.c, ext); break;
    case 'ArrowDown': setCursor(cur.r + 1, cur.c, ext); break;
    case 'ArrowLeft': setCursor(cur.r, cur.c - 1, ext); break;
    case 'ArrowRight': setCursor(cur.r, cur.c + 1, ext); break;
    case 'Tab': setCursor(cur.r, cur.c + (ext ? -1 : 1), false); break;
    case 'Home': setCursor(cur.r, 0, ext); break;
    case 'Enter': case 'F2': beginEdit(cur.r, cur.c); break;
    case 'Delete': case 'Backspace': {
      const s = selRect();
      window.pywebview.api.clear_range(s.r0, s.c0, s.r1, s.c1).then(render);
      break;
    }
    default:
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        beginEdit(cur.r, cur.c, e.key);   // a printable key starts editing
      } else {
        return;   // let the browser handle anything we do not navigate on
      }
  }
  e.preventDefault();
});

// Copy / cut / paste over the selection (Ctrl/Cmd+C/X/V), when not editing.
// Copy also best-effort pushes the values as TSV to the OS clipboard so they
// can be pasted into other apps; paste uses the internal buffer, which keeps
// formulas and adjusts their references.
function flashSave(msg) {
  const el = document.getElementById('saveStatus');
  el.textContent = msg;
  if (msg === 'saved') setTimeout(() => {
    if (el.textContent === 'saved') el.textContent = '';
  }, 1500);
}

document.addEventListener('keydown', async (e) => {
  if (editing || _inField() || !(e.ctrlKey || e.metaKey)) return;
  const k = e.key.toLowerCase();
  if (!'cxvdrzyso'.includes(k)) return;
  e.preventDefault();
  const s = selRect();
  if (k === 'o') {                       // open a different workbook (Ctrl+O)
    await openFile();
  } else if (k === 's') {                // save (Ctrl+S)
    let res = await window.pywebview.api.save();
    if (!res.ok && res.needs_path) res = await window.pywebview.api.save_dialog();
    flashSave(res.ok ? 'saved' : (res.cancelled ? '' : 'save failed'));
  } else if (k === 'z') {                // undo (Ctrl+Z), redo (Ctrl+Shift+Z)
    await (e.shiftKey ? window.pywebview.api.redo() : window.pywebview.api.undo());
    render();
  } else if (k === 'y') {                // redo (Ctrl+Y)
    await window.pywebview.api.redo();
    render();
  } else if (k === 'v') {                // paste
    // Prefer the OS clipboard when it holds text we did not just copy in-app
    // -- that is a paste-in from another application, written verbatim. When it
    // matches our last copy (or is unreadable), fall back to the internal
    // buffer, which preserves formulas and adjusts their references.
    let ext = '';
    try { ext = await navigator.clipboard.readText(); } catch (_) { /* blocked */ }
    if (ext && ext !== lastCopyTsv) {
      await window.pywebview.api.paste_text(cur.r, cur.c, ext);
    } else {
      await window.pywebview.api.paste(cur.r, cur.c);
    }
    render();
  } else if (k === 'd' || k === 'r') {   // fill down / fill right over the selection
    await window.pywebview.api.fill(s.r0, s.c0, s.r1, s.c1, k === 'd' ? 'down' : 'right');
    render();
  } else {                               // copy / cut
    const res = await window.pywebview.api.copy(s.r0, s.c0, s.r1, s.c1, k === 'x');
    lastCopyTsv = res.tsv;
    try { await navigator.clipboard.writeText(res.tsv); } catch (_) { /* no OS clipboard */ }
  }
});

// --- charts: an inline-SVG bar chart from a range. The data shape returned by
// `chart_data` is what a real charting library (Plotly/ECharts) would consume,
// so only this renderer would change when one is dropped in. ---
const SVGNS = 'http://www.w3.org/2000/svg';
const CHART_COLORS = ['#4e79a7', '#f28e2b', '#59a14f', '#e15759', '#af7aa1', '#76b7b2'];
function svgEl(name, attrs) {
  const e = document.createElementNS(SVGNS, name);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}
function svgText(x, y, s, o) {
  o = o || {};
  const t = svgEl('text', { x, y, 'text-anchor': o.anchor || 'start',
    'font-size': o.size || 11, fill: o.fill || '#ddd', 'font-weight': o.weight || 'normal' });
  t.textContent = s;
  return t;
}

async function drawChart() {
  const spec = (document.getElementById('chartRange').value || 'A4:D6').trim();
  const data = await window.pywebview.api.chart_data(spec);
  const svg = document.getElementById('chartSvg');
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const W = 480, H = 320;
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  document.getElementById('chart').style.display = 'block';

  if (data.error) {
    svg.appendChild(svgText(W / 2, H / 2, data.error, { anchor: 'middle', fill: '#e15759' }));
    return;
  }
  const padL = 44, padR = 14, padT = 30, padB = 54;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const labels = data.labels, series = data.series;
  const groups = labels.length, ns = series.length;
  const vals = [];
  series.forEach(s => s.values.forEach(v => { if (v != null) vals.push(Math.abs(v)); }));
  const maxV = Math.max(1, ...vals);

  svg.appendChild(svgText(W / 2, 18, data.title, { anchor: 'middle', weight: 'bold', size: 13 }));
  svg.appendChild(svgEl('line',
    { x1: padL, y1: padT + plotH, x2: padL + plotW, y2: padT + plotH, stroke: '#555' }));
  svg.appendChild(svgText(padL - 6, padT + 8, '' + (+maxV.toFixed(2)),
    { anchor: 'end', size: 9, fill: '#999' }));

  const gw = plotW / Math.max(1, groups);
  const bw = (gw * 0.8) / Math.max(1, ns);
  labels.forEach((lab, gi) => {
    series.forEach((s, si) => {
      const v = s.values[gi];
      if (v == null) return;
      const h = (Math.abs(v) / maxV) * plotH;
      const rect = svgEl('rect', {
        x: padL + gi * gw + gw * 0.1 + si * bw, y: padT + plotH - h,
        width: Math.max(1, bw - 2), height: h, fill: CHART_COLORS[si % CHART_COLORS.length] });
      rect.setAttribute('data-series', s.name);
      svg.appendChild(rect);
    });
    svg.appendChild(svgText(padL + gi * gw + gw / 2, padT + plotH + 16, lab,
      { anchor: 'middle', size: 10 }));
  });
  if (ns > 1) series.forEach((s, si) => {
    const lx = padL + si * 70;
    svg.appendChild(svgEl('rect',
      { x: lx, y: H - 16, width: 9, height: 9, fill: CHART_COLORS[si % CHART_COLORS.length] }));
    svg.appendChild(svgText(lx + 13, H - 8, s.name, { size: 10 }));
  });
}
// --- optimization: infer + solve the current selection (`:opt`); the results
// and sensitivity render into a floating panel, with a compact status in the
// toolbar. Decision cells are written by the engine on success, so re-render. ---
async function solveSelection() {
  const s = selRect();
  const sense = document.getElementById('optSense').value;
  const st = document.getElementById('optStatus');
  st.textContent = '...';
  const res = await window.pywebview.api.solve_selection(s.r0, s.c0, s.r1, s.c1, sense);
  if (!res || !res.ok) {
    st.textContent = res && res.error ? 'err' : 'failed';
    st.title = res && res.error ? res.error : '';
    return;
  }
  st.title = '';
  st.textContent = res.optimal ? (sense + ' = ' + fnum(res.objective)) : res.status;
  renderOptPanel(res, sense);
  render();
}

// Small DOM + number helpers shared by the panels.
function mk(tag, attrs, text) {
  const e = document.createElement(tag);
  if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (text !== undefined) e.textContent = text;
  return e;
}
function fnum(x, d) {
  if (x === null || x === undefined) return 'inf';   // a non-finite value came back as null
  const n = +x;
  return Number.isInteger(n) ? String(n) : n.toFixed(d === undefined ? 4 : d);
}
function showPanel(id) {
  ['optPanel', 'goalDialog'].forEach(p => {
    if (p !== id) document.getElementById(p).style.display = 'none';
  });
  document.getElementById('chart').style.display = 'none';
  document.getElementById(id).style.display = 'block';
}
function hidePanel(id) { document.getElementById(id).style.display = 'none'; }

// cols: [{key, head, kind}] -- kind 'k' = left-aligned label, 'bool' = yes/no,
// anything else = a number formatted by fnum (null -> "inf").
function sensTable(rows, cols) {
  const t = mk('table', { class: 'sens' });
  const hr = mk('tr');
  cols.forEach(c => hr.appendChild(mk('th', c.kind === 'k' ? { class: 'k' } : null, c.head)));
  t.appendChild(hr);
  (rows || []).forEach(row => {
    const tr = mk('tr');
    cols.forEach(c => {
      let v = row[c.key];
      if (c.kind === 'k') v = String(v);
      else if (c.kind === 'bool') v = v ? 'yes' : 'no';
      else v = fnum(v);
      tr.appendChild(mk('td', c.kind === 'k' ? { class: 'k' } : null, v));
    });
    t.appendChild(tr);
  });
  return t;
}

function renderOptPanel(res, sense) {
  const body = document.getElementById('optBody');
  body.innerHTML = '';
  const title = mk('div', { class: 'panelTitle' }, 'Optimize');
  title.appendChild(mk('span', { class: 'badge ' + (res.optimal ? 'ok' : 'bad') }, res.status));
  body.appendChild(title);

  if (res.optimal) {
    body.appendChild(mk('div', { class: 'optObj' }, sense + ' objective = ' + fnum(res.objective)));
    const keys = Object.keys(res.values || {});
    if (keys.length) {
      body.appendChild(sensTable(keys.map(k => ({ cell: k, value: res.values[k] })),
        [{ key: 'cell', head: 'cell', kind: 'k' }, { key: 'value', head: 'value' }]));
    }
  }

  if (res.sensitivity) {
    body.appendChild(mk('div', { class: 'panelTitle' }, 'Variables'));
    body.appendChild(sensTable(res.sensitivity.variables, [
      { key: 'cell', head: 'cell', kind: 'k' }, { key: 'value', head: 'value' },
      { key: 'reduced_cost', head: 'reduced cost' }, { key: 'obj_coef', head: 'obj coef' },
      { key: 'obj_from', head: 'obj from' }, { key: 'obj_till', head: 'obj till' }]));
    body.appendChild(mk('div', { class: 'panelTitle' }, 'Constraints'));
    body.appendChild(sensTable(res.sensitivity.constraints, [
      { key: 'cell', head: 'cell', kind: 'k' }, { key: 'shadow_price', head: 'shadow price' },
      { key: 'rhs', head: 'rhs' }, { key: 'slack', head: 'slack' },
      { key: 'binding', head: 'binding', kind: 'bool' },
      { key: 'rhs_from', head: 'rhs from' }, { key: 'rhs_till', head: 'rhs till' }]));
  } else if (res.optimal) {
    body.appendChild(mk('div', { class: 'sensNote' }, 'No sensitivity for integer models.'));
  }

  if (res.conflict)
    body.appendChild(mk('div', { class: 'diag' },
      'Conflicting constraints: ' + res.conflict.join(', ')));
  if (res.unbounded)
    body.appendChild(mk('div', { class: 'diag' },
      'Unbounded variables: ' + (res.unbounded.join(', ') || '(unidentified)')));

  showPanel('optPanel');
}

// --- goal seek dialog (`:goal <cell> = <value> by <var>`) ---
function openGoalDialog() {
  document.getElementById('goalCell').value = selRef();   // prefill with the active cell
  document.getElementById('goalResult').textContent = '';
  showPanel('goalDialog');
  document.getElementById('goalTarget').focus();
}
async function runGoalSeek() {
  const cell = document.getElementById('goalCell').value.trim();
  const target = document.getElementById('goalTarget').value.trim();
  const varc = document.getElementById('goalVar').value.trim();
  const lo = document.getElementById('goalLo').value.trim();
  const hi = document.getElementById('goalHi').value.trim();
  const out = document.getElementById('goalResult');
  if (!cell || target === '' || !varc) { out.textContent = 'fill in set / to / by'; return; }
  const res = await window.pywebview.api.goal_seek(
    cell, parseFloat(target), varc,
    lo === '' ? null : parseFloat(lo), hi === '' ? null : parseFloat(hi));
  if (!res || !res.ok) { out.textContent = res && res.error ? res.error : 'failed'; return; }
  out.textContent = res.converged
    ? (varc + ' = ' + fnum(res.var_value) + '   (' + cell + ' = ' + fnum(res.formula_value) + ')')
    : ('did not converge (residual ' + fnum(res.residual) + ')');
  render();   // the variable cell and its dependents changed
}

document.getElementById('solveBtn').onclick = solveSelection;
document.getElementById('goalBtn').onclick = openGoalDialog;
document.getElementById('goalRun').onclick = runGoalSeek;
['goalCell', 'goalTarget', 'goalVar', 'goalLo', 'goalHi'].forEach(id =>
  document.getElementById(id).addEventListener('keydown', e => {
    if (e.key === 'Enter') runGoalSeek();
  }));
document.querySelectorAll('.panelClose').forEach(b =>
  b.onclick = () => hidePanel(b.dataset.close));
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !editing) {
    hidePanel('optPanel'); hidePanel('goalDialog');
    document.getElementById('chart').style.display = 'none';
  }
});
document.getElementById('chartBtn').onclick = drawChart;
document.getElementById('chartRange').addEventListener('keydown',
  e => { if (e.key === 'Enter') drawChart(); });
document.getElementById('chartClose').onclick =
  () => { document.getElementById('chart').style.display = 'none'; };

window.addEventListener('pywebviewready', async () => {
  const d = await window.pywebview.api.dims();
  NCOL = d.ncol; NROW = d.nrow;
  await renderTabs();
  render();
});
</script>
</body>
</html>
"""
