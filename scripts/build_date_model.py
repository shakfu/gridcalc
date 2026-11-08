"""Build the date-logic financial model used as an Excel-saved test fixture.

    uv run python scripts/build_date_model.py tests/xlsx/date_model_excel.xlsx --excel

Five sheets over 60 monthly periods: a timeline (`EOMONTH`, `WORKDAY` with
holidays, `YEARFRAC`, `DAYS360`, `DATEDIF`, `ISOWEEKNUM`), a debt schedule, cash
flows with `XIRR`/`XNPV`, and fiscal-year totals (`SUMIFS`, `MINIFS`). openpyxl
saves no values, so ``--excel`` has Excel recalculate and save the file; the
values it stores are what `tests/test_excel_saved_models.py` checks. Functions
newer than Excel 2007 are written with `_xlfn.`, or Excel reads them as
user-defined and gives `#NAME?`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
from pathlib import Path

from openpyxl import Workbook
from openpyxl.workbook.defined_name import DefinedName

P = 60  # monthly periods
_EXCEL_SAVE = """
tell application id "com.microsoft.Excel"
    set display alerts to false
    open POSIX file "{path}"
    set wb to active workbook
    calculate full rebuild
    save wb
    close wb saving no
end tell
"""


def build(path: Path) -> int:
    """Write the model to ``path``; return its formula count."""
    wb = Workbook()
    a = wb.worksheets[0]
    a.title = "Assumptions"
    rows = [
        ("ModelStart", dt.date(2026, 1, 15)),
        ("Periods", P),
        ("FYEndMonth", 6),  # fiscal year ends June
        ("DrawDate", dt.date(2026, 2, 27)),
        ("OpsStart", dt.date(2027, 4, 1)),
        ("Principal", 25_000_000),
        ("Rate", 0.065),
        ("GraceMonths", 18),
        ("Tenor", 42),  # repayment months after grace
        ("BaseRevenue", 1_200_000),
        ("Escalation", 0.025),
        ("Opex", 0.35),
        ("DiscountRate", 0.09),
        ("Equity", 9_000_000),
    ]
    for i, (k, v) in enumerate(rows, start=1):
        a.cell(i, 1, k)
        c = a.cell(i, 2, v)
        if isinstance(v, dt.date):
            c.number_format = "yyyy-mm-dd"
        wb.defined_names[k] = DefinedName(k, attr_text=f"Assumptions!$B${i}")
    a["D1"] = "Holidays"
    hol = [
        dt.date(2026, 12, 25),
        dt.date(2027, 1, 1),
        dt.date(2027, 12, 24),
        dt.date(2028, 2, 29),
        dt.date(2029, 4, 30),
        dt.date(2030, 12, 31),
        dt.date(2026, 5, 29),
        dt.date(2028, 6, 30),
    ]
    for i, d in enumerate(hol, start=2):
        a.cell(i, 4, d).number_format = "yyyy-mm-dd"
    wb.defined_names["Holidays"] = DefinedName(
        "Holidays", attr_text=f"Assumptions!$D$2:$D${len(hol) + 1}"
    )

    t = wb.create_sheet("Timeline")
    head = [
        "n",
        "Start",
        "End",
        "Days",
        "DaysInMonth",
        "FiscalYear",
        "Quarter",
        "IsFYEnd",
        "PayDate",
        "PayWeekday",
        "BusDays",
        "YF_ActAct",
        "YF_30360",
        "Days360",
        "Anniversary",
        "YearsElapsed",
        "OpsFlag",
        "Label",
        "EDATEDraw",
        "ISOWeek",
    ]
    for j, h in enumerate(head, start=1):
        t.cell(1, j, h)
    for n in range(1, P + 1):
        r = n + 1
        t[f"A{r}"] = n
        t[f"B{r}"] = "=ModelStart" if n == 1 else f"=C{r - 1}+1"
        t[f"C{r}"] = f"=EOMONTH(ModelStart,A{r}-1)"
        t[f"D{r}"] = f"=C{r}-B{r}+1"
        t[f"E{r}"] = f"=DAY(EOMONTH(C{r},0))"
        t[f"F{r}"] = f"=YEAR(C{r})+(MONTH(C{r})>FYEndMonth)"
        t[f"G{r}"] = f'="Q"&ROUNDUP(MONTH(C{r})/3,0)'
        t[f"H{r}"] = f"=MONTH(C{r})=FYEndMonth"
        # modified following: next business day unless it leaves the month
        t[f"I{r}"] = (
            f"=IF(MONTH(WORKDAY(C{r}-1,1,Holidays))<>MONTH(C{r}),"
            f"WORKDAY(C{r}+1,-1,Holidays),WORKDAY(C{r}-1,1,Holidays))"
        )
        t[f"J{r}"] = f"=WEEKDAY(I{r},2)"
        t[f"K{r}"] = f"=NETWORKDAYS(B{r},C{r},Holidays)"
        t[f"L{r}"] = f"=YEARFRAC(B{r},C{r}+1,1)"
        t[f"M{r}"] = f"=YEARFRAC(B{r},C{r}+1,0)"
        t[f"N{r}"] = f"=DAYS360(B{r},C{r}+1)"
        t[f"O{r}"] = f'=EDATE(ModelStart,12*DATEDIF(ModelStart,C{r},"y"))'
        t[f"P{r}"] = f'=DATEDIF(ModelStart,C{r},"y")'
        t[f"Q{r}"] = f"=--(C{r}>=OpsStart)"
        t[f"R{r}"] = f'=TEXT(C{r},"mmm-yy")'
        t[f"S{r}"] = f"=EDATE(DrawDate,A{r})"
        t[f"T{r}"] = f"=_xlfn.ISOWEEKNUM(I{r})"
        for col in "BCIOS":
            t[f"{col}{r}"].number_format = "yyyy-mm-dd"

    d = wb.create_sheet("Debt")
    for j, h in enumerate(
        ["n", "Opening", "Interest", "Repay", "Closing", "MonthsFromDraw", "InRepay"], 1
    ):
        d.cell(1, j, h)
    for n in range(1, P + 1):
        r = n + 1
        d[f"A{r}"] = f"=Timeline!A{r}"
        d[f"B{r}"] = (
            f"=IF(Timeline!C{r}<DrawDate,0,IF(Timeline!B{r}<=DrawDate,Principal,E{r - 1}))"
            if n > 1
            else f"=IF(Timeline!C{r}<DrawDate,0,Principal)"
        )
        d[f"F{r}"] = f'=IF(Timeline!C{r}<DrawDate,0,DATEDIF(DrawDate,Timeline!C{r},"m"))'
        d[f"G{r}"] = f"=AND(F{r}>=GraceMonths,F{r}<GraceMonths+Tenor)"
        # act/360 interest on the days the debt was outstanding in the period
        d[f"C{r}"] = f"=B{r}*Rate*(Timeline!C{r}-MAX(Timeline!B{r},DrawDate)+1)/360"
        d[f"D{r}"] = f"=IF(G{r},MIN(B{r},Principal/Tenor),0)"
        d[f"E{r}"] = f"=B{r}-D{r}"

    c = wb.create_sheet("CashFlow")
    for j, h in enumerate(
        ["n", "PayDate", "Revenue", "Opex", "CFADS", "DebtService", "DSCR", "EquityCF"], 1
    ):
        c.cell(1, j, h)
    c["J1"], c["K1"] = "Date", "Flow"
    c["J2"], c["K2"] = "=ModelStart-30", "=-Equity"
    c["J2"].number_format = "yyyy-mm-dd"
    for n in range(1, P + 1):
        r = n + 1
        c[f"A{r}"] = f"=Timeline!A{r}"
        c[f"B{r}"] = f"=Timeline!I{r}"
        c[f"B{r}"].number_format = "yyyy-mm-dd"
        c[f"C{r}"] = (
            f"=Timeline!Q{r}*BaseRevenue*(1+Escalation)^Timeline!P{r}*Timeline!D{r}/Timeline!E{r}"
        )
        c[f"D{r}"] = f"=-C{r}*Opex"
        c[f"E{r}"] = f"=C{r}+D{r}"
        c[f"F{r}"] = f"=Debt!C{r}+Debt!D{r}"
        c[f"G{r}"] = f'=IF(F{r}>0,E{r}/F{r},"n/a")'
        c[f"H{r}"] = f"=E{r}-F{r}"
        c[f"J{r + 1}"] = f"=B{r}"
        c[f"J{r + 1}"].number_format = "yyyy-mm-dd"
        c[f"K{r + 1}"] = f"=H{r}"
    last = P + 2

    s = wb.create_sheet("Summary")
    s["A1"], s["B1"], s["C1"], s["D1"], s["E1"] = (
        "FiscalYear",
        "Revenue",
        "Interest",
        "MinDSCR",
        "Periods",
    )
    fys = range(2026, 2032)
    for i, fy in enumerate(fys, start=2):
        s[f"A{i}"] = fy
        s[f"B{i}"] = f"=SUMIFS(CashFlow!$C$2:$C${P + 1},Timeline!$F$2:$F${P + 1},A{i})"
        s[f"C{i}"] = f"=SUMIFS(Debt!$C$2:$C${P + 1},Timeline!$F$2:$F${P + 1},A{i})"
        s[f"D{i}"] = (
            f'=IFERROR(_xlfn.MINIFS(CashFlow!$G$2:$G${P + 1},Timeline!$F$2:$F${P + 1},A{i}),"-")'
        )
        s[f"E{i}"] = f"=COUNTIFS(Timeline!$F$2:$F${P + 1},A{i})"
    k = len(fys) + 3
    items = [
        ("EquityXIRR", f"=XIRR(CashFlow!K2:K{last},CashFlow!J2:J{last})"),
        ("EquityXNPV", f"=XNPV(DiscountRate,CashFlow!K2:K{last},CashFlow!J2:J{last})"),
        ("FirstRepayDate", f'=_xlfn.MINIFS(Timeline!I2:I{P + 1},Debt!D2:D{P + 1},">0")'),
        ("LastRepayDate", f'=_xlfn.MAXIFS(Timeline!I2:I{P + 1},Debt!D2:D{P + 1},">0")'),
        ("RepayMonths", '=DATEDIF(FirstRepayDate,LastRepayDate,"m")+1'),
        ("TotalInterest", f"=SUM(Debt!C2:C{P + 1})"),
        ("EndBalance", f"=Debt!E{P + 1}"),
        ("OpsFirstPeriod", f"=MATCH(1,Timeline!Q2:Q{P + 1},0)"),
        ("OpsFirstLabel", f"=INDEX(Timeline!R2:R{P + 1},OpsFirstPeriod)"),
        ("ModelEnd", f"=Timeline!C{P + 1}"),
        ("ModelYears", "=YEARFRAC(ModelStart,ModelEnd,1)"),
        ("BusDaysTotal", "=NETWORKDAYS(ModelStart,ModelEnd,Holidays)"),
        ("Q1Periods", f'=COUNTIF(Timeline!G2:G{P + 1},"Q1")'),
        ("FYEndPeriods", f"=SUMPRODUCT(--Timeline!H2:H{P + 1})"),
        ("WeekendPayDates", f"=SUMPRODUCT(--(Timeline!J2:J{P + 1}>5))"),
    ]
    for i, (name, f) in enumerate(items, start=k):
        s[f"A{i}"] = name
        s[f"B{i}"] = f
        wb.defined_names[name] = DefinedName(name, attr_text=f"Summary!$B${i}")
    wb.save(path)
    return sum(
        1
        for ws in wb.worksheets
        for row in ws.iter_rows()
        for x in row
        if isinstance(x.value, str) and x.value.startswith("=")
    )


def excel_save(path: Path) -> None:
    """Have Excel for Mac recalculate ``path`` and save it with its values."""
    script = _EXCEL_SAVE.format(path=str(path.resolve()))
    subprocess.run(["osascript", "-e", script], check=True, timeout=300)  # noqa: S603, S607


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--excel", action="store_true", help="recalculate and save in Excel")
    args = parser.parse_args()
    n = build(args.out)
    if args.excel:
        excel_save(args.out)
    print(f"{args.out}: {n} formulas" + (", saved by Excel" if args.excel else ""))


if __name__ == "__main__":
    main()
