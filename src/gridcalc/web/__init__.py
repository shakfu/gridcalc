"""Experimental web frontend -- an editable grid in a desktop webview.

The chosen GUI direction from ``docs/gui.md`` / ``docs/web.md``: the headless
engine runs in-process on CPython (C++ extensions intact) and a browser view
renders a JSON viewport over it. Unlike a server + fetch design, the view runs
inside a **pywebview** window and calls Python directly through the ``js_api``
bridge -- so the network/serialization boundary collapses to in-process method
calls, which suits a single-user, offline desktop app.

Design:

* **All engine<->view logic is in :class:`Api`**, a plain Python object with no
  ``webview`` import, so every method is unit-testable without a display. This
  module is the whole backend; the view is a React app.
* **The view is a React/TypeScript app** under ``web/frontend/`` (menubar,
  toolbar, virtualized grid, feature dialogs; Radix primitives), built by Vite
  into a single self-contained ``static/index.html`` that :func:`run` reads and
  hands to pywebview. See ``web/frontend/README`` and ``make web-build``.
* **The heavy dependency is optional and lazy.** ``pywebview`` (the ``web``
  extra) is imported only inside :func:`run`; ``import gridcalc.web`` stays
  cheap.
* **Cell formatting is shared**, not reinvented: ``Api`` uses the
  frontend-neutral ``gridcalc.display.cell_text`` / ``cell_right_aligned``, so
  the web view and the curses TUI format cells identically.

The ``Api`` methods cover the workbook (dims/sheets/open/save/undo and the
sheet-management set add/delete/rename/move), the grid
(viewport/cell_source/set_cell/clear_range/copy/paste/fill/stats plus the
structural edits insert_rows/insert_cols/delete_rows/delete_cols), and
optimization (solve_selection/solve_model/goal_seek/opt_sweep/chart_data). The
React client wires them to a menubar, a virtualized grid, and the feature
dialogs.

Every mutating method routes its result through :meth:`Api._touch`, so the
workbook's unsaved-changes state is tracked in one place: it marks the window
title with a ``*`` and rides back to the client on the call that caused it.
"""

from __future__ import annotations

import contextlib
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .. import commands as shared
from .. import goalseek, opt
from ..display import cell_clip_value, cell_right_aligned, cell_text
from ..engine import (
    COL_PX_MAX,
    COL_PX_MIN,
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
from ..opt import OptError, OptModel, cells_to_spec, parse_bounds, parse_cells
from ..search import find_matches
from ..undo import UndoManager

# Cap on how many search hits cross the bridge in one call. A pattern like
# `1` can match most of a populated sheet; the client only ever shows one at
# a time, and the true count rides along separately.
MAX_SEARCH_MATCHES = 1000


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
        self._dirty = False
        g.dirty = 0  # a freshly loaded (or demo) workbook is not user-modified

    def dims(self) -> dict[str, Any]:
        """Sheet extent, the loaded filename, and the unsaved-changes flag."""
        return {
            "ncol": NCOL,
            "nrow": NROW,
            "filename": getattr(self._g, "filename", "") or "",
            "dirty": self._dirty,
        }

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

        Each cell is ``{r, c, text, align}`` plus ``bold`` / ``italic`` /
        ``underline`` when those styles are set (omitted otherwise, to keep the
        payload small). Number formats are already baked into ``text`` by
        ``cell_text``; the style flags are what the view cannot derive itself.
        Empty cells are omitted; the client fills gaps as blank.
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
                cell: dict[str, Any] = {
                    "r": r,
                    "c": c,
                    "text": cell_text(cl, g.fmt),
                    "align": "r" if cell_right_aligned(cl) else "l",
                }
                if cl.bold:
                    cell["bold"] = True
                if cl.italic:
                    cell["italic"] = True
                if cl.underline:
                    cell["underline"] = True
                cells.append(cell)
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
        return self._touch()

    def undo(self) -> dict[str, Any]:
        """Undo the last mutation (recomputes derived cells).

        An empty history is a no-op that must not dirty the workbook -- the
        stack is checked first, since `UndoManager.undo` reports nothing back.
        """
        if not self._undo.undo_stack:
            return {"ok": True, "dirty": self._dirty}
        self._undo.undo(self._g)
        return self._touch()

    def redo(self) -> dict[str, Any]:
        """Redo the last undone mutation; an empty history is a no-op."""
        if not self._undo.redo_stack:
            return {"ok": True, "dirty": self._dirty}
        self._undo.redo(self._g)
        return self._touch()

    def clear_range(self, r0: int, c0: int, r1: int, c1: int) -> dict[str, Any]:
        """Blank every cell in a rectangle (Delete on a selection).

        A thin wrapper over the shared ``blank`` command rather than its own
        loop: this is the keyboard's entry point, which carries an explicit
        rectangle instead of the current selection, but the work is the same
        work.
        """
        return self._run_shared_rect("blank", (), r0, c0, r1, c1)

    def set_format(self, r0: int, c0: int, r1: int, c1: int, spec: str) -> dict[str, Any]:
        """Apply a format ``spec`` to every non-empty cell in a rectangle.

        ``spec`` is the same one ``:format`` takes -- style toggles from
        ``bui``, a single number-format char from ``LRIGD$%*``, or a Python
        spec like ``,.2f`` -- because it runs the same shared command. Number
        formats bake into the displayed text via ``cell_text``; the style flags
        come back in ``viewport``. Formatting changes no values, so no recalc.
        """
        return self._run_shared_rect("format", (spec or "",), r0, c0, r1, c1)

    def _run_shared_rect(
        self, name: str, args: Iterable[str], r0: int, c0: int, r1: int, c1: int
    ) -> dict[str, Any]:
        """Run a shared command against an explicit rectangle.

        The toolbar and keyboard act on a rectangle they already know, rather
        than on "the selection" -- so they get a normalized, clamped rect built
        here instead of each call site repeating it.
        """
        ra, rb = sorted((int(r0), int(r1)))
        ca, cb = sorted((int(c0), int(c1)))
        rect = (
            max(0, min(NCOL - 1, ca)),
            max(0, min(NROW - 1, ra)),
            max(0, min(NCOL - 1, cb)),
            max(0, min(NROW - 1, rb)),
        )
        result = shared.run(name, self._g, self._undo, list(args), rect)
        if not result.ok:
            return {"ok": False, "error": result.message}
        return self._touch() if result.changed else {"ok": True, "dirty": self._dirty}

    def set_global_format(self, fmt: str) -> dict[str, Any]:
        """Set the workbook's default number format (the TUI's ``:gformat``).

        A single char in ``LRIGD$%*`` becomes the default; anything else clears
        it. Cells with no explicit format render with this default -- ``viewport``
        already passes ``g.fmt`` to ``cell_text`` as the global format, so the
        change shows on the next fetch. The change touches no cell, so it is
        snapshotted with ``save_global`` (grid-level state) rather than
        ``save_region``; without that, undo would silently skip it.
        """
        f = (fmt or "").upper()
        self._undo.save_global(self._g)
        self._g.fmt = f if len(f) == 1 and f in "LRIGD$%*" else ""
        return {**self._touch(), "global_format": self._g.fmt}

    def stats(self, r0: int, c0: int, r1: int, c1: int) -> dict[str, Any]:
        """Aggregate the numeric cells in a rectangle, for the status bar.

        ``count`` is every non-empty cell (labels included), ``numeric`` only
        those carrying a finite number; the aggregates are over the numeric
        ones and come back ``None`` when there are none. This is the
        selection-summary a spreadsheet shows in its status bar, computed
        engine-side so the client never has to re-derive values it only ever
        received as formatted text.
        """
        g = self._g
        ra, rb = sorted((int(r0), int(r1)))
        ca, cb = sorted((int(c0), int(c1)))
        count = 0
        nums: list[float] = []
        for r in range(max(0, ra), min(NROW, rb + 1)):
            for c in range(max(0, ca), min(NCOL, cb + 1)):
                cl = g.cell(c, r)
                if cl is None or cl.type == EMPTY:
                    continue
                count += 1
                v = self._num_at(c, r)
                if v is not None:
                    nums.append(v)
        total = math.fsum(nums) if nums else None
        return {
            "count": count,
            "numeric": len(nums),
            "sum": total,
            "avg": (total / len(nums)) if nums and total is not None else None,
            "min": min(nums) if nums else None,
            "max": max(nums) if nums else None,
        }

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
        return self._touch()

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
        return {**self._touch(), "rows": len(rows), "cols": ncols}

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
        return self._touch()

    # -- shared commands ----------------------------------------------------

    def list_commands(self) -> dict[str, Any]:
        """The shared command registry as data, for building the palette.

        The client renders whatever this returns, so a command registered in
        `gridcalc.commands` appears in the palette without a second edit here
        or in the TypeScript -- which is the point of the registry.
        """
        return {"commands": shared.describe()}

    def run_command(
        self,
        name: str,
        args: list[str] | None = None,
        selection: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        """Run a shared command by name (the same one ``:``-dispatch runs).

        ``selection`` arrives row-first (``{r0, c0, r1, c1}``) like the rest of
        this bridge and is converted to the registry's column-first tuple here
        -- one place, because that mismatch has caused bugs before.

        A command that reports ``changed`` dirties the workbook; one that only
        answers a question (``names``, ``mode`` with no argument) does not, so
        listing named ranges cannot make a saved file look modified.
        """
        rect: tuple[int, int, int, int] | None = None
        if selection is not None:
            with contextlib.suppress(KeyError, TypeError, ValueError):
                rect = (
                    int(selection["c0"]),
                    int(selection["r0"]),
                    int(selection["c1"]),
                    int(selection["r1"]),
                )
        result = shared.run(name, self._g, self._undo, list(args or ()), rect)
        out: dict[str, Any] = {
            "ok": result.ok,
            "message": result.message,
            "changed": result.changed,
            "lines": list(result.lines),
        }
        if result.changed:
            out.update(self._touch())
            out["ok"] = result.ok  # `_touch` reports ok=True unconditionally
        return out

    def search(self, pattern: str) -> dict[str, Any]:
        """Cells on the active sheet matching ``pattern`` (the TUI's ``/``).

        Case-insensitive substring over both a cell's source text and a
        formula's computed value, in reading order. Read-only -- it moves
        nothing and does not dirty the workbook; the client drives its own
        cursor from the returned refs.

        Long result lists are truncated, and say so rather than quietly
        handing back a short list: a pattern like ``1`` can match most of a
        populated sheet, and shipping every hit across the bridge to render a
        counter nobody reads is waste. ``total`` is always the true count.
        """
        hits = find_matches(self._g, pattern or "")
        return {
            "matches": [
                {"r": r, "c": c, "ref": self._a1((c, r))} for c, r in hits[:MAX_SEARCH_MATCHES]
            ],
            "total": len(hits),
            "truncated": len(hits) > MAX_SEARCH_MATCHES,
        }

    def col_widths(self) -> dict[str, Any]:
        """The active sheet's saved per-column pixel widths.

        Keys come back as strings because that is what they are in the JSON
        and what a JS object gives back anyway; the client parses them. A
        column with no entry uses the view's own default.
        """
        return {"widths": {str(c): w for c, w in self._g._active.widths.items()}}

    def set_col_width(self, col: int, px: int) -> dict[str, Any]:
        """Record a column's width after the user drags its edge.

        Widths are per-sheet display state that the curses renderer has no way
        to use (it lays columns out from the single uniform ``Grid.cw``), so
        this is deliberately a view-level preference the workbook carries
        rather than a shared setting. It changes no value, so no recalc -- but
        it is a change to the file, hence the dirty mark.
        """
        c = int(col)
        w = int(px)
        if not (0 <= c < NCOL):
            return {"ok": False, "error": f"no such column: {col}"}
        if not (COL_PX_MIN <= w <= COL_PX_MAX):
            return {"ok": False, "error": f"width out of range: {px}"}
        self._g._active.widths[c] = w
        return self._touch()

    # -- sheet management -------------------------------------------------

    def add_sheet(self, name: str) -> dict[str, Any]:
        """Append a new empty sheet and switch to it.

        The TUI's ``:sheet add`` deliberately does not switch; here the user
        asked for a tab through the tab strip, so landing on it is the expected
        outcome of the click.
        """
        new_name = (name or "").strip()
        if not new_name:
            return {"ok": False, "error": "a sheet needs a name", **self.sheets()}
        try:
            self._g.add_sheet(new_name)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), **self.sheets()}
        self._g.set_active(len(self._g.sheets) - 1)
        return {**self._touch(), **self.sheets()}

    def delete_sheet(self, name: str) -> dict[str, Any]:
        """Remove a sheet by name; the last remaining sheet cannot be removed."""
        try:
            self._g.remove_sheet(name)
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": self._sheet_error(exc, name), **self.sheets()}
        self._g.recalc()
        return {**self._touch(), **self.sheets()}

    def rename_sheet(self, old: str, new: str) -> dict[str, Any]:
        """Rename a sheet, rewriting formula text that references the old name.

        Sheet identity is part of the dependency-graph keys, so the graph is
        rebuilt before recalculating -- otherwise edges still pointing at the
        old name would go stale. This mirrors ``cmd_sheet``'s rename path.
        """
        new_name = (new or "").strip()
        if not new_name:
            return {"ok": False, "error": "a sheet needs a name", **self.sheets()}
        try:
            self._g.rename_sheet(old, new_name)
        except (ValueError, KeyError) as exc:
            return {"ok": False, "error": self._sheet_error(exc, old), **self.sheets()}
        self._g._dep_graph_built = False
        self._g._rebuild_dep_graph()
        self._g.recalc()
        return {**self._touch(), **self.sheets()}

    def move_sheet(self, name: str, index: int) -> dict[str, Any]:
        """Reorder a sheet to zero-based ``index``; the active sheet follows."""
        try:
            self._g.move_sheet(name, int(index))
        except (IndexError, KeyError, ValueError) as exc:
            return {"ok": False, "error": self._sheet_error(exc, name), **self.sheets()}
        return {**self._touch(), **self.sheets()}

    @staticmethod
    def _sheet_error(exc: Exception, name: str) -> str:
        """``KeyError``/``IndexError`` carry only the bad key; say what failed."""
        if isinstance(exc, KeyError):
            return f"no such sheet: {name}"
        if isinstance(exc, IndexError):
            return f"index out of range: {exc}"
        return str(exc)

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
        self._mark_clean()
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
        self._mark_clean()
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

    def _sync_close_guard(self) -> None:
        """Arm or disarm pywebview's own close confirmation to match the
        unsaved state, so closing a dirty workbook asks first.

        The window carries a ``confirm_close`` flag that its close handler
        reads *at close time*, and the prompt it produces runs modally on the
        UI thread -- which is the only safe way to ask from there.

        The obvious-looking alternative, subscribing to the ``closing`` event
        and calling ``create_confirmation_dialog``, deadlocks: ``closing``
        subscribers run synchronously on the UI thread, and that method
        schedules its dialog *onto* the UI thread and then blocks waiting for
        it. The thread ends up waiting on work only it can run, so the whole
        application freezes with no way out but a force quit. Toggling the flag
        hands the asking back to the toolkit, which does it on the right thread.

        The message is customized through the window's localization table
        (read at close time too) so the prompt names the workbook rather than
        asking a generic "really quit?".
        """
        win = self._window
        if win is None:
            return  # headless (tests): nothing to guard
        # The flag is what actually gates the close, so it is set on its own:
        # the message is a nicety, and a window that will not take one must not
        # cost us the guard.
        with contextlib.suppress(Exception):
            win.confirm_close = self._dirty
        if not self._dirty:
            return
        name = getattr(self._g, "filename", "") or "This workbook"
        # `localization` only exists once the GUI has initialized the window,
        # which it has by the time a user can edit anything -- but a failure
        # here just leaves the generic message set at creation.
        with contextlib.suppress(Exception):
            win.localization["global.quitConfirmation"] = (
                f"{name} has unsaved changes. Close anyway and lose them?"
            )

    def _retitle(self) -> None:
        """Best-effort window-title refresh; a trailing ``*`` means unsaved."""
        win = self._window
        if win is None:
            return
        name = getattr(self._g, "filename", "") or "(demo)"
        mark = " *" if self._dirty else ""
        with contextlib.suppress(Exception):
            win.set_title(f"gridcalc - {name}{mark}")

    def _touch(self) -> dict[str, Any]:
        """Record that the workbook now differs from what is on disk.

        Retitles and arms the close guard only on the clean->dirty
        transition: every cell edit calls this, and a native ``set_title`` per
        keystroke would be a bridge round trip for nothing. Returned by the
        mutating methods so the client learns the dirty state from the call it
        already made.
        """
        self._g.dirty = 1
        if not self._dirty:
            self._dirty = True
            self._retitle()
            self._sync_close_guard()
        return {"ok": True, "dirty": True}

    def _mark_clean(self) -> None:
        """The workbook now matches disk (saved, or freshly opened)."""
        self._g.dirty = 0
        self._dirty = False
        self._retitle()
        self._sync_close_guard()

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
        # Store what was inferred as `default`, matching `:opt max` in the TUI:
        # the block only has to be selected once, and the model is then a
        # workbook object the user can re-run, edit, or rename.
        g.models["default"] = OptModel(
            sense="min" if sense == "min" else "max",
            objective=self._a1(m.objective),
            vars=cells_to_spec(m.decision_vars),
            constraints=cells_to_spec(m.constraint_cells),
        )
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

    # -- persisted models (the `:opt def/run/list/undef` surface) ----------

    def list_models(self) -> dict[str, Any]:
        """Every model definition saved in the workbook.

        Models are workbook state (`grid.models`, persisted under ``models`` in
        the JSON), so they outlive a session and are shared with the TUI's
        ``:opt run <name>``. Each is returned as the spec strings the user
        typed -- cell refs are resolved at solve time, not here, so a model
        naming a cell that has since been deleted still lists (and reports its
        error when run) rather than breaking the whole listing.
        """
        return {
            "models": [
                {"name": name, **model.to_json()} for name, model in sorted(self._g.models.items())
            ]
        }

    def save_model(self, name: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Create or replace a named model. Validates before storing."""
        key = (name or "").strip()
        if not key:
            return {"ok": False, "error": "a model needs a name"}
        try:
            model = OptModel.from_json(
                {
                    "sense": "min" if spec.get("sense") == "min" else "max",
                    "objective": str(spec.get("objective", "")),
                    "vars": str(spec.get("vars", "")),
                    "constraints": str(spec.get("constraints", "")),
                    "bounds": str(spec.get("bounds", "") or ""),
                    "integers": str(spec.get("integers", "") or ""),
                    "binaries": str(spec.get("binaries", "") or ""),
                }
            )
        except OptError as exc:
            return {"ok": False, "error": str(exc)}
        self._g.models[key] = model
        return {**self._touch(), "name": key}

    def delete_model(self, name: str) -> dict[str, Any]:
        """Remove a named model (the TUI's ``:opt undef``)."""
        if name not in self._g.models:
            return {"ok": False, "error": f"no such model: {name}"}
        del self._g.models[name]
        return self._touch()

    def run_model(self, name: str, spec: dict[str, Any] | None = None) -> dict[str, Any]:
        """Solve a saved model by name (the TUI's ``:opt run <name>``).

        ``spec`` may carry the run-time switches ``sensitivity`` / ``diagnose``
        / ``apply``; the model itself supplies the cells. Its spec strings are
        resolved here rather than at save time, so a model saved against a
        sheet that later changed reports a useful error instead of having been
        rejected when it was still valid.
        """
        model = self._g.models.get(name)
        if model is None:
            return {"ok": False, "error": f"no such model: {name}"}
        run = dict(model.to_json())
        for switch in ("sensitivity", "diagnose", "apply"):
            if spec and switch in spec:
                run[switch] = spec[switch]
        return self.solve_model(run)

    def infer_model_spec(
        self, r0: int, c0: int, r1: int, c1: int, sense: str = "max"
    ) -> dict[str, Any]:
        """What ``solve_selection`` would build from this selection, unsolved.

        Lets the client prefill a model editor from a block on the sheet
        without committing to running it -- the user can see and correct the
        inference before anything is written to the grid.
        """
        ra, rb = sorted((int(r0), int(r1)))
        ca, cb = sorted((int(c0), int(c1)))
        try:
            m = opt.infer_model(self._g, ca, ra, cb, rb)
        except opt.OptError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": True,
            "sense": "min" if sense == "min" else "max",
            "objective": self._a1(m.objective),
            "vars": cells_to_spec(m.decision_vars),
            "constraints": cells_to_spec(m.constraint_cells),
        }

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
        elif res.applied:
            self._touch()
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
        elif res.applied:
            self._touch()
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


def _load_html() -> str:
    """Read the built React bundle (``static/index.html``).

    The frontend under ``web/frontend`` compiles to a single self-contained file
    via ``make web-build``. A source checkout that has not run the build has no
    bundle, so this raises a directive error rather than opening a blank window.
    """
    bundle = Path(__file__).resolve().parent / "static" / "index.html"
    try:
        return bundle.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise OSError(
            f"web UI bundle not found at {bundle}; build it with `make web-build` "
            "(compiles web/frontend into static/index.html)"
        ) from None


def run(path: str | None = None) -> None:
    """Open the editable grid in a desktop webview window."""
    import webview  # lazy: only needed to open a window

    g = load_workbook(path) if path else demo_grid()
    api = Api(g)
    name = getattr(g, "filename", "") or "(demo)"
    window = webview.create_window(
        f"gridcalc - {name}",
        html=_load_html(),
        js_api=api,
        width=1200,
        height=800,
        min_size=(640, 400),
        # Off until there is unsaved work; `Api._sync_close_guard` turns it on
        # and off as the workbook is edited and saved. The override is the
        # fallback wording, replaced with one naming the file once the window
        # is live.
        confirm_close=False,
        localization={
            "global.quitConfirmation": "This workbook has unsaved changes. Close anyway?"
        },
    )
    if window is None:
        raise OSError("could not create the webview window")
    api._window = window
    webview.start()


def run_cli() -> None:
    """Console-script entry point (``gridcalc-web``)."""
    import sys

    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print("Usage: gridcalc-web [workbook.json | workbook.xlsx]")
        return
    run(args[0] if args else None)
