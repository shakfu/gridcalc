"""Build the iterative-calculation fixtures, the input and its Excel-saved copy.

    uv run python scripts/build_iterate_model.py tests/xlsx/iterate_input.xlsx --excel

Each row of `Cycles` probes one rule: the iteration count, the stop on a small
change, sweep order, ranges and sheets inside a cycle, errors and text. Count
and change are not Excel's defaults, so a reader that ignores them fails.
Every formula saves the value 0, which Excel iterates from. ``--excel`` copies
the input to ``*_excel.xlsx`` beside it and has Excel recalculate and save that;
`tests/test_iterate.py` checks gridcalc's load of the input against it.
"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

from build_date_model import excel_save
from openpyxl import Workbook
from openpyxl.workbook.properties import CalcProperties

COUNT, DELTA = 50, 0.0001

PROBES: list[tuple[str, dict[str, object]]] = [
    ("count: +1 each sweep", {"B1": "=B1+1"}),
    ("stop on small change", {"B2": "=COS(B2)"}),
    ("order: same row", {"B3": "=0.9*C3+0.1", "C3": "=0.9*B3+0.1"}),
    ("order: reader above", {"B4": "=0.8*C5+1"}),
    ("order: source below", {"C5": "=0.8*B4+1"}),
    ("order: reader right", {"E6": "=0.7*B6+1", "B6": "=0.7*E6+1"}),
    (
        "interest on average balance",
        {"A7": 1000, "B7": "=0.05*(A7+C7)/2", "C7": "=A7+B7-D7", "D7": "=0.1*C7"},
    ),
    ("downstream of a cycle", {"B8": "=C7*2", "C8": "=SUM(B7:D7)", "D8": "=AVERAGE(B3:C3)"}),
    ("cross-sheet", {"B9": "=Other!A1*0.5+1"}),
    ("range in a cycle", {"B10": "=SUM(B11:B12)/4+1"}),
    ("range member", {"B11": "=B10/2"}),
    ("range member", {"B12": "=B10/3"}),
    ("diverges", {"B13": "=B13*2+1"}),
    ("error from start value", {"B14": "=1/B14"}),
    ("breaker", {"B15": "=IF(B15>10,B15,B15+3)"}),
    ("text alternates", {"B16": '=IF(B16="x","y","x")'}),
    ("start value 0", {"B17": "=B17+A17", "A17": 5}),
]


def build(path: Path) -> int:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cycles"
    other = wb.create_sheet("Other")
    other["A1"] = "=Cycles!B9*0.5+1"
    n = 1
    for row, (label, cells) in enumerate(PROBES, start=1):
        ws[f"H{row}"] = label
        for ref, v in cells.items():
            ws[ref] = v
            n += isinstance(v, str)
    wb.calculation = CalcProperties(
        iterate=True, iterateCount=COUNT, iterateDelta=DELTA, fullCalcOnLoad=False
    )
    wb.save(path)
    _zero_values(path)
    return n


def _zero_values(path: Path) -> None:
    """Save 0 as each formula's value in place of openpyxl's empty ``<v />``.

    Excel iterates from a cell's saved value and reads an empty one as text,
    so `=B1+1` gives `#VALUE!`.
    """
    with zipfile.ZipFile(path) as z:
        members = [(i, z.read(i)) for i in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in members:
            if info.filename.startswith("xl/worksheets/"):
                data = data.replace(b"<v />", b"<v>0</v>")
            z.writestr(info, data)


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
