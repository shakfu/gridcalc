"""Evaluate every formula cell of one workbook in one engine; write JSON.

    python foreign_engine.py {pycel|formulas|gridcalc} BOOK.xlsx OUT.json

Runs inside that engine's environment, so it imports gridcalc only for
``gridcalc``, which lets gridcalc run under the same memory cap.
`engine_compare.py` starts it; see `docs/dev/comparison.md`.
Output: {"seconds": float, "values": {"Sheet\\tcol\\trow": value}}, 0-based,
where a value is a number, text, bool, None, or ["error", "#X!"].
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
from typing import Any

import openpyxl

ERRORS = {
    "#NULL!",
    "#DIV/0!",
    "#VALUE!",
    "#REF!",
    "#NAME?",
    "#NUM!",
    "#N/A",
    "#SPILL!",
    "#CALC!",
    "#GETTING_DATA",
}

Key = tuple[str, int, int, str]  # sheet, col, row, A1


def _norm(v: Any) -> Any:
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):  # numpy scalar
        with contextlib.suppress(TypeError, ValueError):
            v = v.item()
    if isinstance(v, float) and v != v:
        return ["error", "#NUM!"]
    if v is None or isinstance(v, (bool, int, float)):
        return v
    s = str(v)
    return ["error", s] if s in ERRORS else s


def formula_cells(path: str) -> list[Key]:
    wb = openpyxl.load_workbook(path, data_only=False)
    return [
        (ws.title, c.column - 1, c.row - 1, c.coordinate)
        for ws in wb.worksheets
        for c in list(ws._cells.values())
        if c.data_type == "f"
    ]


def run_pycel(path: str, keys: list[Key]) -> dict[str, Any]:
    from pycel import ExcelCompiler

    xc = ExcelCompiler(filename=path)
    # pycel returns a formula's cached value until an input changes. Evaluate
    # once to build the cell map, then clear every formula and recompute.
    for s, _c, _r, a in keys:
        with contextlib.suppress(Exception):  # per-cell errors are recorded below
            xc.evaluate(f"'{s}'!{a}")
    with contextlib.suppress(Exception):
        xc.recalculate()
    res = {}
    for s, c, r, a in keys:
        try:
            v = xc.evaluate(f"'{s}'!{a}")
        except Exception as e:  # noqa: BLE001
            v = ("engine", "ENGINE:" + type(e).__name__)
        if isinstance(v, tuple) and v and v[0] == "engine":
            res[f"{s}\t{c}\t{r}"] = ["error", v[1]]
            continue
        if isinstance(v, tuple):  # a range result: its top-left
            v = v[0][0] if v and isinstance(v[0], tuple) else (v[0] if v else None)
        res[f"{s}\t{c}\t{r}"] = _norm(v)
    return res


def run_formulas(path: str, keys: list[Key]) -> dict[str, Any]:
    import formulas

    sol = formulas.ExcelModel().loads(path).finish().calculate()
    by = {k.upper(): v for k, v in sol.items()}
    book = os.path.basename(path).upper()
    res: dict[str, Any] = {}
    for s, c, r, a in keys:
        v = by.get(f"'[{book}]{s.upper()}'!{a}".upper())
        try:
            x = v.value[0, 0]
        except (AttributeError, IndexError, TypeError):
            x = v
        if type(x).__name__ == "XlError" or str(x) in ERRORS:
            res[f"{s}\t{c}\t{r}"] = ["error", str(x)]
        elif type(x).__name__ == "EmptyValue" or str(x) == "empty":
            res[f"{s}\t{c}\t{r}"] = 0
        else:
            res[f"{s}\t{c}\t{r}"] = _norm(x)
    return res


def run_gridcalc(path: str, keys: list[Key]) -> dict[str, Any]:
    from gridcalc.engine import EMPTY
    from gridcalc.loader import load_workbook

    g = load_workbook(path)
    sheets = {sh.name: sh for sh in g.sheets}
    res: dict[str, Any] = {}
    for s, c, r, _a in keys:
        cl = sheets[s]._cells.get((c, r)) if s in sheets else None
        if cl is None or cl.type == EMPTY:
            v: Any = None
        elif cl.err is not None:
            v = ["error", str(cl.err)]
        elif cl.sval is not None and not isinstance(cl.val, bool):
            v = cl.sval
        elif isinstance(cl.val, float) and cl.val != cl.val:
            v = ["error", "ERROR"]  # as `excel_corpus.gridcalc_value`
        else:
            v = _norm(cl.val)
        res[f"{s}\t{c}\t{r}"] = v
    return res


def main() -> None:
    eng, path, out = sys.argv[1:4]
    t = time.monotonic()
    keys = formula_cells(path)
    run = {"pycel": run_pycel, "formulas": run_formulas, "gridcalc": run_gridcalc}[eng]
    vals = run(path, keys)
    with open(out, "w") as f:
        json.dump({"seconds": time.monotonic() - t, "values": vals}, f)


if __name__ == "__main__":
    main()
