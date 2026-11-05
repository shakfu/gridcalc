"""A workbook as a function: write inputs by defined name, recalculate, read outputs.

    from gridcalc.book import Book

    book = Book.open("loan.xlsx")
    book.run({"Rate": 0.05, "Years": 30}, ["Payment", "Schedule#"])
    # {'Payment': -1610.46, 'Schedule#': [[...], ...]}

A target is a defined name, a sheet-qualified local name (`Inputs!Rate`), or
a cell or range (`B2`, `Inputs!B2:C5`). `Name#` reads the whole array a
formula at `Name` spills, as Excel's `#` operator does. `run` restores the
inputs afterwards, so each call starts from the workbook as loaded; `set`
keeps them, for a later `save`.

Values follow JSON: a number, a bool, a string (always text, never a formula),
None (a blank), or a list of rows for a range. A one-row or one-column range
also takes a flat list. A result cell holding an error reads as
``{"error": "#DIV/0!"}``. The CLI is `gridcalc FILE --set NAME=VALUE --get NAME`
(`docs/reference/cli.md`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .engine import Cell, Grid, cellname, ref
from .formula.errors import ExcelError
from .loader import load_workbook, save_workbook
from .sandbox import LoadPolicy, inspect_file


class BookError(Exception):
    """An unknown name, a value of the wrong shape, or a target that cannot take input."""


@dataclass(frozen=True)
class Target:
    """A rectangle on a sheet, or a formula name (``formula`` set, rectangle unused)."""

    sheet: str
    c1: int
    r1: int
    c2: int
    r2: int
    formula: str | None = None
    spill: bool = False

    @property
    def shape(self) -> tuple[int, int]:
        return self.r2 - self.r1 + 1, self.c2 - self.c1 + 1

    def cells(self) -> list[tuple[int, int]]:
        return [(c, r) for r in range(self.r1, self.r2 + 1) for c in range(self.c1, self.c2 + 1)]


class Book:
    """A loaded workbook driven through its defined names."""

    def __init__(self, grid: Grid) -> None:
        self.grid = grid

    @classmethod
    def open(cls, path: str, *, trust: bool = False) -> Book:
        """Load ``path``. Its Python (code block, PYTHON-mode cells) runs only with ``trust``."""
        policy = None
        if trust:
            info = inspect_file(path)
            policy = LoadPolicy.trust_all(info.requires if info else None)
        return cls(load_workbook(path, policy))

    def names(self) -> dict[str, str]:
        """Each defined name and what it refers to: ``Sheet!$A$1:$B$2`` or ``=formula``."""
        out: dict[str, str] = {}
        for nr in self.grid.names:
            if nr.formula is not None:
                where = nr.formula
            else:
                rect = _abs(nr.c1, nr.r1)
                if (nr.c1, nr.r1) != (nr.c2, nr.r2):
                    rect += ":" + _abs(nr.c2, nr.r2)
                where = f"{_quote(nr.sheet)}!{rect}" if nr.sheet else rect
            key = nr.name if nr.name not in out else f"{_quote(nr.sheet or '')}!{nr.name}"
            out[key] = where
        return out

    # --- resolution -------------------------------------------------------

    def resolve(self, target: str) -> Target:
        """The rectangle or formula ``target`` names. Raises :class:`BookError`."""
        text = target.strip()
        spill = text.endswith("#")
        if spill:
            text = text[:-1]
        sheet, _, local = text.rpartition("!")
        sheet = _unquote(sheet)
        key = local.casefold()
        found = [
            nr
            for nr in self.grid.names
            if nr.name.casefold() == key and (not sheet or (nr.sheet or "") == sheet)
        ]
        if len(found) > 1:
            found = [nr for nr in found if nr.sheet is None] or found
        if len(found) > 1:
            where = ", ".join(f"{_quote(nr.sheet or '')}!{nr.name}" for nr in found)
            raise BookError(f"{target!r} is defined on several sheets; qualify it: {where}")
        default = self.grid.sheets[self.grid.active].name
        if found:
            nr = found[0]
            home = nr.sheet or sheet or default
            if nr.formula is not None:
                return Target(home, 0, 0, 0, 0, formula=nr.formula, spill=spill)
            return Target(home, nr.c1, nr.r1, nr.c2, nr.r2, spill=spill)
        rect = _rect(local)
        home = sheet or default
        if rect is None or home not in self.grid.sheet_names():
            known = ", ".join(sorted(self.names())) or "none"
            raise BookError(f"no defined name or cell {target!r} (names: {known})")
        return Target(home, *rect, spill=spill)

    # --- inputs -----------------------------------------------------------

    def set(self, inputs: Mapping[str, Any]) -> None:
        """Write each value to its target and recalculate once per sheet."""
        writes: dict[str, dict[tuple[int, int], Any]] = {}
        for name, value in inputs.items():
            t = self.resolve(name)
            if t.formula is not None or t.spill:
                raise BookError(f"{name!r} is not a cell or range, so it cannot take input")
            cells = t.cells()
            for (c, r), v in zip(cells, _cells_of(name, value, t.shape), strict=True):
                writes.setdefault(t.sheet, {})[(c, r)] = v
        self._write(writes)

    def _write(self, writes: Mapping[str, Mapping[tuple[int, int], Any]]) -> None:
        g = self.grid
        active = g.active
        try:
            for sheet, cells in writes.items():
                g.set_active(sheet)
                dirty: set[tuple[int, int]] = set()
                for (c, r), v in cells.items():
                    dirty |= g._spill_predirty(c, r)
                    _put(g, c, r, v)
                    dirty.add((c, r))
                g.recalc(dirty | g._blocked_anchors_active())
        finally:
            g.active = active

    def _snapshot(self, names: Iterable[str]) -> dict[str, dict[tuple[int, int], Cell | None]]:
        snap: dict[str, dict[tuple[int, int], Cell | None]] = {}
        for name in names:
            t = self.resolve(name)
            if t.formula is not None or t.spill:
                continue  # `set` rejects it before anything is written
            cells = self.grid._sheet_by_name(t.sheet)._cells  # type: ignore[union-attr]
            for key in t.cells():
                cl = cells.get(key)
                snap.setdefault(t.sheet, {})[key] = cl.snapshot() if cl is not None else None
        return snap

    # --- outputs ----------------------------------------------------------

    def get(self, outputs: Iterable[str] | None = None) -> dict[str, Any]:
        """Each output's value: a scalar for one cell, rows for a range or a spill.

        With no outputs, every defined name is read.
        """
        names = list(self.names()) if outputs is None else list(outputs)
        return {name: self._read(self.resolve(name)) for name in names}

    def _read(self, t: Target) -> Any:
        g = self.grid
        if t.formula is not None:
            return _json(_eval_on(g, t.sheet, "=" + t.formula.removeprefix("=")))
        if t.spill:
            v = g._cell_spill_value(t.c1, t.r1, t.sheet)
            if hasattr(v, "data"):
                cols = getattr(v, "cols", None) or 1
                data = [_json(x) for x in v.data]
                return [data[i : i + cols] for i in range(0, len(data), cols)]
            return [[_json(v)]]
        rows, cols = t.shape
        vals = [_json(g._cell_lookup_value(c, r, t.sheet)) for c, r in t.cells()]
        if rows == cols == 1:
            return vals[0]
        return [vals[i : i + cols] for i in range(0, len(vals), cols)]

    # --- the round trip ---------------------------------------------------

    def run(
        self, inputs: Mapping[str, Any], outputs: Iterable[str] | None = None
    ) -> dict[str, Any]:
        """Set ``inputs``, read ``outputs``, then put the inputs back as they were."""
        snap = self._snapshot(inputs)
        try:
            self.set(inputs)
            return self.get(outputs)
        finally:
            self._restore(snap)

    def _restore(self, snap: Mapping[str, Mapping[tuple[int, int], Cell | None]]) -> None:
        g = self.grid
        active = g.active
        try:
            for sheet, cells in snap.items():
                g.set_active(sheet)
                dirty: set[tuple[int, int]] = set()
                for (c, r), cl in cells.items():
                    dirty |= g._spill_predirty(c, r)
                    if cl is None:
                        g._setcell_no_recalc(c, r, "")
                    else:
                        live = g._ensure_cell(c, r)
                        live.copy_from(cl)
                        if g._dep_graph_built:
                            g._refresh_deps(c, r, live)
                    dirty.add((c, r))
                g.recalc(dirty | g._blocked_anchors_active())
        finally:
            g.active = active

    def save(self, path: str) -> str:
        """Write the workbook; the format follows the extension. Returns it."""
        return save_workbook(self.grid, path)


# --- helpers ----------------------------------------------------------------


def _cells_of(name: str, value: Any, shape: tuple[int, int]) -> list[Any]:
    """``value`` as one entry per cell of a ``shape`` target, row by row."""
    rows, cols = shape
    if not isinstance(value, (list, tuple)):
        if rows == cols == 1:
            return [_scalar(name, value)]
        raise BookError(f"{name!r} is {rows}x{cols}; give a list of rows, not one value")
    if value and all(isinstance(row, (list, tuple)) for row in value):
        grid = [list(row) for row in value]
    elif rows == 1 or cols == 1:
        grid = [list(value)] if rows == 1 else [[v] for v in value]
    else:
        raise BookError(f"{name!r} is {rows}x{cols}; give a list of rows")
    if len(grid) != rows or any(len(row) != cols for row in grid):
        got = f"{len(grid)}x{len(grid[0]) if grid else 0}"
        raise BookError(f"{name!r} is {rows}x{cols}; the value given is {got}")
    return [_scalar(name, v) for row in grid for v in row]


def _scalar(name: str, v: Any) -> Any:
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, (int, float)) and math.isfinite(v):
        return float(v)
    raise BookError(f"{name!r}: {v!r} is not a number, bool, string or null")


def _put(g: Grid, c: int, r: int, v: Any) -> None:
    """Write a typed value to the active sheet without recalculating."""
    if v is None:
        g._setcell_no_recalc(c, r, "")
    elif isinstance(v, bool):
        g._setcell_no_recalc(c, r, "TRUE" if v else "FALSE")
    elif isinstance(v, float):
        g._setcell_no_recalc(c, r, repr(v))
    elif not v:
        g._setcell_no_recalc(c, r, "")
    else:
        # Text stays text, even "=1+1", "12" or "TRUE": a label first, then its text.
        g._setcell_no_recalc(c, r, '"' + v)
        g._cells[(c, r)].text = v


def _json(v: Any) -> Any:
    """A cell value in the module's JSON form."""
    if isinstance(v, ExcelError):
        return {"error": str(v)}
    if isinstance(v, float) and not math.isfinite(v):
        return {"error": "#NUM!"}
    if hasattr(v, "data"):  # a matrix cell or an array result: its top-left value
        return _json(v.data[0]) if v.data else None
    return v


def _eval_on(g: Grid, sheet: str, formula: str) -> Any:
    """The value of ``formula`` evaluated on ``sheet``; the workbook is left unchanged."""
    from .cli import run_eval

    active = g.active
    try:
        g.set_active(sheet)
        entry = run_eval(g, [formula])[0]
    finally:
        g.active = active
    return {"error": entry["error"]} if entry["error"] is not None else entry["value"]


def _rect(text: str) -> tuple[int, int, int, int] | None:
    lo, _, hi = text.replace("$", "").partition(":")
    hi = hi or lo
    a, b = ref(lo), ref(hi)
    if a is None or b is None or a[0] != len(lo) or b[0] != len(hi):
        return None
    return min(a[1], b[1]), min(a[2], b[2]), max(a[1], b[1]), max(a[2], b[2])


def _abs(c: int, r: int) -> str:
    name = cellname(c, r)
    col = name.rstrip("0123456789")
    return f"${col}${name[len(col) :]}"


def _quote(sheet: str | None) -> str:
    if not sheet:
        return ""
    if sheet.replace("_", "").isalnum() and not sheet[0].isdigit():
        return sheet
    return "'" + sheet.replace("'", "''") + "'"


def _unquote(sheet: str) -> str:
    s = sheet.strip()
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    return s


__all__ = ["Book", "BookError", "Target"]
