"""Write an xlsx of formulas whose Excel result is unconfirmed, with gridcalc's answers.

A:H hold the inputs every case reads; each case row holds the formula as text,
the live formula, the gridcalc result and a match flag. Open it in Excel 365.
Procedure: `docs/dev/excel-check.md`.

    uv run python scripts/excel_check.py docs/dev/excel-check.xlsx
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.worksheet.formula import ArrayFormula

from gridcalc.cli import run_eval
from gridcalc.engine import Grid, Mode

# (cell, entry). A leading `'` marks text, as typing it in Excel does.
INPUTS = [
    ("A1", "5"), ("A3", "7"), ("A4", "-2.5"),  # A2 blank
    ("B1", "1"), ("B2", "2"), ("B3", "'3"), ("B4", "'a"),
    ("C1", "10"), ("C2", "20"), ("C3", "30"), ("C4", "40"),
    ("D1", "'a"), ("D2", "'b"), ("D3", "'a"), ("D4", "'c"),
    ("F1", "'Name"), ("G1", "'Val"),
    ("F2", "'x"), ("G2", "1"),
    ("F3", "'y"), ("G3", "=NA()"),
    ("F4", "'x"), ("G4", "3"),
    ("H1", "'Name"), ("H2", "'x"),
]  # fmt: skip

# (id, formula, what is in doubt). Array results are joined to one cell, so
# nothing spills into the next case.
CASES = [
    ("setup", "=AND(ISTEXT(B3),ISBLANK(A2),ISNA(G3))", "TRUE means the inputs pasted as intended"),
    ("pow-1", "=2^3^2", "gridcalc is right-associative (512); Excel documents left to right (64)"),
    ("pow-2", "=-2^2", "negation binds tighter than ^ in Excel (4)"),
    ("pow-3", "=-2^0.5", "(-2)^0.5 in Excel: #NUM!"),
    ("text-1", '=0.00001&""', "gridcalc formats with %g"),
    ("text-2", '=1E-10&""', ""),
    ("text-3", '=-0.0000123&""', ""),
    ("text-4", '=1/3&""', "15 significant digits"),
    ("text-5", '=(0.1+0.2)&""', ""),
    ("text-6", '=123456789012&""', ""),
    ("text-7", '=12345678901234567&""', "past 15 digits"),
    ("text-8", '=1E+20&""', ""),
    ("blank-1", "=ROUND(2.5,)", "omitted number argument reads as 0"),
    ("blank-2", "=ROUND(2.5,Z9)", "blank cell reads as 0"),
    ("blank-3", '=LEFT("abc",)', "omitted count reads as 0"),
    ("blank-4", '=SUBSTITUTE("abc","b",)', "omitted text reads as empty"),
    ("blank-5", '=CONCAT("a",,"b")', ""),
    ("blank-6", "=IF(FALSE,1,)", ""),
    ("lift-1", '=TEXTJOIN(",",FALSE,LEN(A1:A3))', "scalar function over a range"),
    ("lift-2", '=TEXTJOIN(",",FALSE,ROUND(A1:A4,0))', "ROUND(-2.5,0) rounds away from zero"),
    ("lift-3", '=TEXTJOIN(",",FALSE,MOD(C1:C4,3))', ""),
    ("lift-4", '=TEXTJOIN(",",FALSE,UPPER(D1:D4))', ""),
    ("lift-5", '=TEXTJOIN(",",FALSE,TEXT(C1:C3,"0.0"))', ""),
    ("lift-6", "=SUM(LEN(A1:A3))", ""),
    ("crit-1", "=COUNTIF(B1:B3,3)", "does the text '3 count?"),
    ("crit-2", '=COUNTIF(B1:B3,"3")', ""),
    ("crit-3", '=COUNTIF(B1:B3,">1")', ""),
    ("crit-4", '=SUMIF(B1:B4,">0")', ""),
    ("crit-5", '=SUMIF(C1:C4,">15",A1:A2)', "Excel resizes sum_range from its top-left"),
    ("crit-6", '=TEXTJOIN(",",FALSE,SUMIF(D1:D4,{"a","b"},C1:C4))', "array criteria"),
    ("crit-7", '=SUM(COUNTIF(D1:D4,{"a","c"}))', ""),
    ("arr-1", "=ROWS(FILTER(C1:C4,C1:C4>15))", ""),
    ("arr-2", '=TEXTJOIN(",",FALSE,FREQUENCY({1,2,3,4,5},{4,2}))', "unsorted bins"),
    ("arr-3", '=TEXTJOIN(",",FALSE,ISFORMULA(G1:G3))', "ISFORMULA over a range"),
    ("db-1", '=DSUM(F1:G4,"Val",H1:H2)', "an error in an unmatched row"),
    ("db-2", '=DCOUNT(F1:G4,"Val",H1:H2)', ""),
    ("date-1", "=EOMONTH(DATE(1900,1,15),1)", "phantom 1900-02-29"),
    ("date-2", "=DAYS(10.9,1.1)", "fractional serials"),
    ("yf-1", "=YEARFRAC(DATE(2023,12,31),DATE(2024,3,1),0)", ""),
    ("yf-2", "=YEARFRAC(DATE(2023,12,31),DATE(2024,3,1),1)", ""),
    ("yf-3", "=YEARFRAC(DATE(2023,6,15),DATE(2025,2,28),0)", ""),
    ("yf-4", "=YEARFRAC(DATE(2023,6,15),DATE(2025,2,28),1)", ""),
    ("yf-5", "=YEARFRAC(DATE(2024,2,29),DATE(2025,2,28),0)", ""),
    ("yf-6", "=YEARFRAC(DATE(2024,2,29),DATE(2025,2,28),1)", ""),
    ("yf-7", "=YEARFRAC(DATE(2023,2,28),DATE(2024,2,29),0)", ""),
    ("yf-8", "=YEARFRAC(DATE(2023,2,28),DATE(2024,2,29),1)", ""),
    ("misc-1", "=MOD(3,0.1)", "float residue"),
    ("misc-2", '=IMSQRT("-4")', ""),
    ("misc-3", '=OR("a",TRUE)', "text literal in OR"),
    ("misc-4", '=XOR(TRUE,"a")', ""),
    ("misc-5", "=MATCH(3,{5,1,4,2},1)", "approximate match over unsorted data"),
    ("misc-6", "=TEXT(3,1)", ""),
]

# I id, J formula as text, K live formula, L gridcalc, M match, N note.
MATCH = "=IFERROR(K{r}=L{r},IFERROR(ERROR.TYPE(K{r})=ERROR.TYPE(L{r}),FALSE))"


def _cell(ref: str) -> tuple[int, int]:
    return ord(ref[0]) - ord("A"), int(ref[1:]) - 1


# Functions newer than Excel 2007 are stored under a prefix; without it Excel
# reads the name as unknown and shows #NAME?.
_XLFN = {
    "TEXTJOIN": "_xlfn.TEXTJOIN",
    "CONCAT": "_xlfn.CONCAT",
    "XOR": "_xlfn.XOR",
    "DAYS": "_xlfn.DAYS",
    "ISFORMULA": "_xlfn.ISFORMULA",
    "FILTER": "_xlfn._xlws.FILTER",
}


def _stored(formula: str) -> str:
    """``formula`` as an xlsx file stores it."""
    return re.sub(r"\b([A-Z]+)\(", lambda m: _XLFN.get(m[1], m[1]) + "(", formula)


def _result(entry: dict[str, object]) -> object:
    """gridcalc's answer as an xlsx value; openpyxl stores an error code as an error."""
    if entry["error"]:
        return str(entry["error"])
    v = entry["value"]
    if v in ("TRUE", "FALSE"):  # how run_eval reports a logical; no case returns that text
        return v == "TRUE"
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def evaluate() -> list[object]:
    """gridcalc's result for each case, in ``CASES`` order."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    for ref, entry in INPUTS:
        c, r = _cell(ref)
        if entry.startswith("'"):
            g._put_label(c, r, entry[1:])
        else:
            g.setcell(c, r, entry)
    g.recalc()
    return [_result(e) for e in run_eval(g, [f for _, f, _ in CASES])]


def build() -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "check"
    for ref, entry in INPUTS:
        ws[ref] = entry[1:] if entry.startswith("'") else _number_or_formula(entry)
    heads = ["id", "formula", "Excel", "gridcalc", "match", "in doubt"]
    for col, head in zip("IJKLMN", heads, strict=True):
        ws[f"{col}1"] = head
    for r, ((cid, formula, note), res) in enumerate(zip(CASES, evaluate(), strict=True), start=2):
        ws[f"I{r}"] = cid
        ws[f"J{r}"] = formula
        ws[f"J{r}"].data_type = "s"  # shown as text, not computed
        # An array formula, so a range reaching a one-value parameter is not
        # reduced to one cell by implicit intersection.
        ws[f"K{r}"] = ArrayFormula(f"K{r}", _stored(formula))
        ws[f"L{r}"] = res
        ws[f"M{r}"] = MATCH.format(r=r)
        ws[f"N{r}"] = note
    wb.calculation.fullCalcOnLoad = True  # openpyxl writes no cached values
    return wb


def _number_or_formula(entry: str) -> object:
    return entry if entry.startswith("=") else float(entry)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    build().save(args.out)


if __name__ == "__main__":
    main()
