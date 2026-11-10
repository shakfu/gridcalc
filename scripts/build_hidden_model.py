"""Build the hidden-row fixtures, the input and its Excel-saved copy.

    uv run python scripts/build_hidden_model.py tests/xlsx/hidden_input.xlsx --excel

Each sheet holds the same values in A2:A9 with rows 3 and 5 hidden, and the
same `SUBTOTAL` and `AGGREGATE` formulas in column C; the sheets differ in what
hid the rows. ``--excel`` copies the input to ``*_excel.xlsx`` beside it and
has Excel recalculate and save that; `tests/test_hidden_rows.py` checks
gridcalc's load of the input against it.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from build_date_model import excel_save
from openpyxl import Workbook
from openpyxl.worksheet.filters import AutoFilter, FilterColumn, Filters
from openpyxl.worksheet.table import Table

VALUES = [1, 2, 4, 8, 16, 32, 64, "#N/A"]  # A2:A9; A9 is an error
HIDDEN = (3, 5, 9)  # 1-based rows

FORMULAS = [
    "=SUBTOTAL(9,A2:A8)",
    "=SUBTOTAL(109,A2:A8)",
    "=SUBTOTAL(9,A2:A9)",
    "=SUBTOTAL(109,A2:A9)",
    "=SUBTOTAL(3,A1:A9)",
    "=SUBTOTAL(103,A1:A9)",
    "=_xlfn.AGGREGATE(9,4,A2:A8)",
    "=_xlfn.AGGREGATE(9,5,A2:A8)",
    "=_xlfn.AGGREGATE(9,1,A2:A8)",
    "=_xlfn.AGGREGATE(9,7,A2:A9)",
    "=_xlfn.AGGREGATE(9,3,A2:A9)",
    "=_xlfn.AGGREGATE(15,5,A2:A8,2)",
    "=_xlfn.AGGREGATE(15,7,A2:A9,2)",
    "=_xlfn.AGGREGATE(15,5,A2:A8*1,2)",
    "=SUBTOTAL(109,A2:A4,A5:A8)",
    "=SUBTOTAL(109,E1:G1)",  # across hidden column F: columns are never skipped
    "=SUBTOTAL(9,A:A)",
    "=SUBTOTAL(109,A:A)",
]


def _filter() -> FilterColumn:
    return FilterColumn(colId=0, filters=Filters(filter=["1", "4", "16", "32", "64"]))


def build(path: Path) -> int:
    wb = Workbook()
    wb.remove(wb.active)
    kinds = ["manual", "sheet filter", "sheet filter, no criterion", "table filter", "table"]
    for kind in kinds:
        ws = wb.create_sheet(kind.replace(",", "").replace(" ", "_"))
        ws["A1"] = "v"
        for i, v in enumerate(VALUES, start=2):
            ws.cell(i, 1, v if v != "#N/A" else "=NA()")
        for i, f in enumerate(FORMULAS, start=1):
            ws.cell(i, 3, f)
        ws["E1"], ws["F1"], ws["G1"] = 1, 10, 100
        ws.column_dimensions["F"].hidden = True
        for r in HIDDEN:
            ws.row_dimensions[r].hidden = True
        if kind.startswith("sheet filter"):
            ws.auto_filter = AutoFilter(ref="A1:A9")
            if kind == "sheet filter":
                ws.auto_filter.filterColumn.append(_filter())
        elif kind.startswith("table"):
            t = Table(displayName=ws.title.title().replace("_", ""), ref="A1:A9")
            t.autoFilter = AutoFilter(ref="A1:A9")
            if kind == "table filter":
                t.autoFilter.filterColumn.append(_filter())
            ws.add_table(t)
    wb.save(path)
    return len(kinds) * len(FORMULAS)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--excel", action="store_true", help="recalculate and save in Excel")
    args = parser.parse_args()
    n = build(args.out)
    print(f"{args.out}: {n} formulas")
    if args.excel:
        saved = args.out.with_name(args.out.stem.removesuffix("_input") + "_excel.xlsx")
        shutil.copyfile(args.out, saved)
        excel_save(saved)
        print(f"{saved}: saved by Excel")


if __name__ == "__main__":
    main()
