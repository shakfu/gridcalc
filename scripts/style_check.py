"""Write an xlsx through gridcalc's own writer, one cell format per row.

Column A says what column B should show. Open it in Excel: it must open
without a repair prompt, and each B cell must look as A says.
Procedure: `docs/dev/excel-check.md`.

    uv run python scripts/style_check.py build/style-check.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path

from gridcalc.cellstyle import Side, XStyle
from gridcalc.engine import Grid, Mode

# (what B shows, B's value, number format, XStyle)
ROWS: list[tuple[str, str, str, XStyle | None]] = [
    (
        "Arial 14, red, struck through",
        "text",
        "",
        XStyle(font="Arial", size=14, color="FF0000", strike=True),
    ),
    ("yellow fill", "5", "", XStyle(fill="FFFF00")),
    (
        "thin blue top, double bottom border",
        "",
        "",
        XStyle(top=Side("thin", "0000FF"), bottom=Side("double")),
    ),
    (
        "thick red border on all sides",
        "1",
        "",
        XStyle(**{s: Side("thick", "FF0000") for s in ("left", "right", "top", "bottom")}),
    ),
    ("centred horizontally, top-aligned", "centre", "", XStyle(halign="center", valign="top")),
    ("wrapped text over two lines", "a long line of text that wraps", "", XStyle(wrap=True)),
    ("indented twice", "indent", "", XStyle(indent=2)),
    ("rotated 45 degrees", "rotated", "", XStyle(rotation=45)),
    ("$1,234.50", "1234.5", '"$"#,##0.00', None),
    ("(2.00) in red", "-2", "#,##0.00;[Red](#,##0.00)", None),
    ("1 1/2", "1.5", "# ?/?", None),
    ("2.5M", "2500000", '0.0,,"M"', None),
    ("green fill, no value: a styled blank", "", "", XStyle(fill="00FF00")),
]


def build() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.font = ("Aptos", 11.0)
    g.setcell(0, 0, '"B should show')
    g.setcell(1, 0, '"B')
    for i, (desc, value, code, style) in enumerate(ROWS, start=1):
        g.setcell(0, i, '"' + desc)
        if value:
            g.setcell(1, i, value if value[0].isdigit() or value[0] == "-" else '"' + value)
        cl = g._ensure_cell(1, i)
        cl.fmtstr = code
        cl.xstyle = style
    n = len(ROWS) + 2
    g.setcell(0, n, '"B..D merged, centred')
    g.setcell(1, n, '"merged')
    g.cell(1, n).xstyle = XStyle(halign="center")
    g._active.merges = [(1, n, 3, n)]
    g.setcell(0, n + 1, '"this row 40pt tall')
    g._active.heights = {n + 1: 40.0}
    g._active.widths = {0: 260, 1: 140}
    g.recalc()
    return g


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    g = build()
    if g.xlsxsave(str(args.out)) != 0:
        raise SystemExit(g.io_error)


if __name__ == "__main__":
    main()
