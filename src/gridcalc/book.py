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
import multiprocessing as mp
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .engine import Cell, Grid, Mode, cellname, ref
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
            policy = (
                LoadPolicy.trust_all(info.requires, info.digest) if info else LoadPolicy.trust_all()
            )
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
        self._apply(self._plan(inputs))

    def _plan(self, inputs: Mapping[str, Any]) -> dict[Key, Any]:
        """Each cell ``inputs`` writes and its value. Raises before anything is written."""
        plan: dict[Key, Any] = {}
        for name, value in inputs.items():
            t = self.resolve(name)
            if t.formula is not None or t.spill:
                raise BookError(f"{name!r} is not a cell or range, so it cannot take input")
            for (c, r), v in zip(t.cells(), _cells_of(name, value, t.shape), strict=True):
                plan[(t.sheet, c, r)] = v
        return plan

    def _apply(self, writes: Mapping[Key, Any]) -> None:
        """Write values, or `_Orig` snapshots, then recalculate once per sheet."""
        g = self.grid
        by_sheet: dict[str, list[tuple[int, int, Any]]] = {}
        for (sheet, c, r), v in writes.items():
            by_sheet.setdefault(sheet, []).append((c, r, v))
        active = g.active
        try:
            for sheet, cells in by_sheet.items():
                g.set_active(sheet)
                dirty: set[tuple[int, int]] = set()
                for c, r, v in cells:
                    dirty |= g._spill_predirty(c, r)
                    if isinstance(v, _Orig):
                        _restore_cell(g, c, r, v.cell)
                    else:
                        _put(g, c, r, v)
                    dirty.add((c, r))
                g.recalc(dirty | g._blocked_anchors_active())
        finally:
            g.active = active

    def _originals(self, keys: Iterable[Key]) -> dict[Key, _Orig]:
        out: dict[Key, _Orig] = {}
        for key in keys:
            cl = self.grid._sheet_by_name(key[0])._cells.get(key[1:])  # type: ignore[union-attr]
            out[key] = _Orig(cl.snapshot() if cl is not None else None)
        return out

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
            if g.mode == Mode.PYTHON:
                return _eval_on(g, t.sheet, "=" + t.formula.removeprefix("="))
            v = g.evaluate(t.formula, t.sheet)  # no cell write, no recalc
            return _rows(v) if hasattr(v, "data") else _json(v)
        if t.spill:
            v = g._cell_spill_value(t.c1, t.r1, t.sheet)
            return _rows(v) if hasattr(v, "data") else [[_json(v)]]
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
        return self.run_many([inputs], outputs)[0]

    def run_many(
        self,
        cases: Iterable[Mapping[str, Any]],
        outputs: Iterable[str] | None = None,
        *,
        workers: int = 1,
    ) -> list[dict[str, Any]]:
        """`run` each case in turn, each from the workbook as loaded.

        Every case is checked before the first is written. Between cases only
        the cells whose value changes are written, so a case costs one recalc;
        the inputs are put back once, at the end.

        ``workers`` above 1 splits the cases across that many forked processes,
        each starting from the workbook as it is now. The cases run in this
        process instead where fork is unavailable (Windows), and when the
        workbook iterates, since an iterated case starts from the last one's values.
        """
        if workers < 1:
            raise BookError(f"workers must be 1 or more, not {workers}")
        plans = [self._plan(c) for c in cases]
        outs = None if outputs is None else list(outputs)
        n = min(workers, len(plans))
        if n > 1 and self.grid.iterate is None and "fork" in mp.get_all_start_methods():
            return self._run_forked(plans, outs, n)
        return self._run_plans(plans, outs)

    def _run_forked(
        self, plans: list[dict[Key, Any]], outs: list[str] | None, n: int
    ) -> list[dict[str, Any]]:
        global _FORKED
        size = -(-len(plans) // n)
        chunks = [plans[i : i + size] for i in range(0, len(plans), size)]
        _FORKED = self
        try:
            with mp.get_context("fork").Pool(len(chunks)) as pool:
                parts = pool.map(_run_chunk, [(chunk, outs) for chunk in chunks])
        finally:
            _FORKED = None
        return [r for part in parts for r in part]

    def _run_plans(
        self, plans: list[dict[Key, Any]], outs: list[str] | None
    ) -> list[dict[str, Any]]:
        orig = self._originals({k for p in plans for k in p})
        live: dict[Key, Any] = dict(orig)
        results = []
        try:
            for plan in plans:
                want = {k: plan.get(k, o) for k, o in orig.items()}
                diff = {k: v for k, v in want.items() if not _same(live[k], v)}
                if diff:
                    self._apply(diff)
                    live.update(diff)
                results.append(self.get(outs))
        finally:
            back = {k: o for k, o in orig.items() if live[k] is not o}
            if back:
                self._apply(back)
        return results

    def save(self, path: str) -> str:
        """Write the workbook; the format follows the extension. Returns it."""
        return save_workbook(self.grid, path)


# --- helpers ----------------------------------------------------------------


Key = tuple[str, int, int]  # (sheet, col, row)

# The book a forked worker runs; set only while `Book._run_forked` runs.
_FORKED: Book | None = None


def _run_chunk(job: tuple[list[dict[Key, Any]], list[str] | None]) -> list[dict[str, Any]]:
    if _FORKED is None:
        raise RuntimeError("no workbook in this worker")
    return _FORKED._run_plans(*job)


@dataclass(frozen=True)
class _Orig:
    """A cell as loaded, to write back; None for one that was not stored."""

    cell: Cell | None


def _same(a: Any, b: Any) -> bool:
    """Whether writing ``b`` over ``a`` would change nothing (1.0 is not TRUE)."""
    if isinstance(a, _Orig) or isinstance(b, _Orig):
        return a is b
    return type(a) is type(b) and a == b


def _restore_cell(g: Grid, c: int, r: int, cl: Cell | None) -> None:
    if cl is None:
        g._setcell_no_recalc(c, r, "")
        return
    live = g._ensure_cell(c, r)
    live.copy_from(cl)
    if g._dep_graph_built:
        g._refresh_deps(c, r, live)


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


def _rows(v: Any) -> list[list[Any]]:
    """An array value as JSON rows."""
    cols = getattr(v, "cols", None) or 1
    data = [_json(x) for x in v.data]
    return [data[i : i + cols] for i in range(0, len(data), cols)]


def errors(outputs: Mapping[str, Any]) -> list[str]:
    """The outputs whose value is, or holds, an error, in order."""

    def bad(v: Any) -> bool:
        if isinstance(v, list):
            return any(bad(x) for x in v)
        return isinstance(v, dict) and "error" in v

    return [k for k, v in outputs.items() if bad(v)]


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


__all__ = ["Book", "BookError", "Target", "errors"]
