"""Date/time and database functions against Excel's saved results.

Expected values come from the IronCalc calc_tests workbooks (DATE_AND_TIME,
DATABASE) and pycel's yearfrac.xlsx; the data below copies their cells.
"""

import pytest

from gridcalc.engine import Grid, Mode
from gridcalc.formula.errors import ExcelError


def _ev(formula: str, cells: dict[tuple[int, int], str] | None = None):
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk([(c, r, t) for (c, r), t in (cells or {}).items()])
    g.setcell(19, 19, formula)
    cl = g.cell(19, 19)
    if cl.err is not None:
        return cl.err
    return cl.sval if cl.sval is not None and not isinstance(cl.val, bool) else cl.val


def _check(got, want) -> None:
    if isinstance(want, ExcelError):
        assert got is want
    else:
        assert got == pytest.approx(want)


# DCOUNT_DCOUNTA_DGET_DPRODUCT.xlsx columns Region, Salesperson, Revenue, 1,
# One, One, Numbers (A, B, F, K, N, O, Q there) as A:G here.
_COLS = [
    ["Region", "East", "West", "East", "South", "West", "East", "North", "West", "East", "South"],
    ["Salesperson", "Alice", "Bob", "Cara", "Dan", "Ella", "Frank", "Gina", "Hank", "Ivy", "Jake"],
    ["Revenue", "12000", "9600", "20000", "15000", "6000", "30000", "11000", "38000", "24000",
     "19800"],
    ["1", "", "b", "B", "", "BB", "balpha", "", "", "23", ""],
    ["One", "a", "", "a", "a", "aa", "", "", "Aa", '=" aa"', "aaa"],
    ["One", "", "a", "", "", "", "a", "", "a", "a", ""],
    ["Numbers", "TRUE", "FALSE", "7", "1", "=NA()", '="42"', "", "", "-2", ""],
]  # fmt: skip
DB: dict[tuple[int, int], str] = {
    (c, r): v for c, col in enumerate(_COLS) for r, v in enumerate(col) if v != ""
}
DB.update(
    {
        (8, 0): "1", (8, 1): "b",  # I1:I2, a number header
        (9, 0): "One", (9, 1): "aa",  # J1:J2, the first of two "One" columns
        (10, 0): "Salesperson", (10, 1): "*",  # K1:K2, every row
        (11, 0): "Region", (11, 1): "Central",  # L1:L2, no row
        (12, 0): "#VALUE!", (12, 1): "East",  # M1:M2, an error header
    }
)  # fmt: skip


@pytest.mark.parametrize(
    ("formula", "want"),
    [
        # Plain text criteria match by prefix: "b" takes b, B, BB and balpha.
        ('=DCOUNT(A1:G11,"Revenue",I1:I2)', 4),
        ("=DPRODUCT(A1:G11,C1,I1:I2)", 3.456e16),
        ("=DSUM(A1:G11,C1,I1:I2)", 65600),
        ("=DCOUNT(A1:G11,C1,J1:J2)", 3),
        ("=DSUM(A1:G11,C1,J1:J2)", 63800),
        # A field names a header by its text; an error in a matched row counts
        # for DCOUNTA. A logical field is an index.
        ('=DCOUNT(A1:G11,"Numbers",K1:K2)', 3),
        ('=DCOUNTA(A1:G11,"Numbers",K1:K2)', 7),
        ('=DCOUNT(A1:G11,"1",K1:K2)', 1),
        ('=DCOUNTA(A1:G11,"1",K1:K2)', 5),
        ("=DCOUNT(A1:G11,TRUE,K1:K2)", 0),
        ("=DCOUNTA(A1:G11,TRUE,K1:K2)", 10),
        ("=DCOUNT(A1:G11,1/3,K1:K2)", ExcelError.VALUE),
        # A header row with no records.
        ("=DSUM(A1:G1,C1,K1:K2)", ExcelError.VALUE),
        ("=DCOUNT(A1:G1,C1,K1:K2)", ExcelError.VALUE),
        ("=DPRODUCT(A1:G1,C1,K1:K2)", ExcelError.VALUE),
        ("=DVAR(A1:G1,C1,K1:K2)", ExcelError.VALUE),
        ("=DMIN(A1:G1,C1,K1:K2)", ExcelError.VALUE),
        # No matching number, and an error criteria header that matches nothing.
        ("=DPRODUCT(A1:G11,C1,L1:L2)", 0),
        ("=DPRODUCT(A1:G11,C1,M1:M2)", 0),
    ],
)
def test_database(formula, want) -> None:
    _check(_ev(formula, DB), want)


@pytest.mark.parametrize(
    ("formula", "cells", "want"),
    [
        # US method: a start on the last day of February is the 30th.
        ("=DAYS360(DATE(2024,2,29),DATE(2025,2,28))", {}, 358),
        ("=DAYS360(DATE(2025,2,28),DATE(2025,3,1))", {}, 1),
        ("=DAYS360(DATE(2025,2,28),DATE(2025,3,31))", {}, 30),
        ("=DAYS360(DATE(2025,2,28),DATE(2025,2,28))", {}, -2),
        # Each date is read to the nearest second; serial 0 is 1900-01-00.
        ("=DAYS360(45992.000001,46000.999999)", {}, 9),
        ("=DAYS360(DATE(2025,1,2)+0.0000001,DATE(2025,1,1)+0.9999999)", {}, 0),
        ("=DAYS360(10,A1)", {}, -10),
        ("=DAYS360(DATE(2025,1,10),)", {}, -45010),
        # DAYS drops each time part and rejects dates outside 1900..9999.
        ("=DAYS(DATE(2025,1,13),DATE(2025,1,10)+TIME(16,30,0))", {}, 3),
        ("=DAYS(DATE(2025,1,14)+TIME(0,1,0),DATE(2025,1,13)+TIME(23,59,0))", {}, 1),
        ("=DAYS(-5,-10)", {}, ExcelError.NUM),
        ("=DAYS(2958466,DATE(9999,12,31))", {}, ExcelError.NUM),
        # Two-digit years 30-99 are 19xx.
        ("=DAYS(A1,B1)", {(0, 0): '="1/1/30"', (1, 0): '="1/1/29"'}, -36160),
        ("=NETWORKDAYS(B1,A1)", {(0, 0): '="1/1/30"', (1, 0): '="1/1/29"'}, -25829),
    ],
)
def test_day_counts(formula, cells, want) -> None:
    _check(_ev(formula, cells), want)


@pytest.mark.parametrize(
    ("formula", "cells", "want"),
    [
        ("=WORKDAY.INTL(DATE(2025,1,10),10,)", {}, 45681),
        ("=WORKDAY.INTL(DATE(2025,1,10),3,,A1)", {(0, 0): "=DATE(2025,1,13)"}, 45673),
        ("=WORKDAY(DATE(2025,1,10),-0.9999999)", {}, 45666),
        ("=WORKDAY(DATE(2025,1,10),-1e-09)", {}, 45666),
        ("=WORKDAY(A1,10)", {(0, 0): "TRUE"}, ExcelError.VALUE),
        ("=WORKDAY(DATE(2025,12,13),A1)", {(0, 0): "TRUE"}, ExcelError.VALUE),
        ("=WORKDAY(DATE(2025,1,10),10,A1)", {(0, 0): "abc"}, ExcelError.VALUE),
        ("=WORKDAY(DATE(2025,1,10),10,A1)", {(0, 0): "TRUE"}, ExcelError.VALUE),
        ("=WORKDAY(DATE(2025,1,10),10,A1)", {(0, 0): "-2"}, ExcelError.NUM),
        ("=WORKDAY(DATE(2025,1,10),1E+15)", {}, ExcelError.NUM),
        ('=NETWORKDAYS.INTL(DATE(2025,1,1),DATE(2026,12,31),"1111111")', {}, 0),
        ("=NETWORKDAYS(A1,B1)", {(0, 0): "FALSE", (1, 0): "TRUE"}, ExcelError.VALUE),
        ("=NETWORKDAYS(DATE(2025,1,1),DATE(2026,1,1),A1)", {(0, 0): "abc"}, ExcelError.VALUE),
        ("=NETWORKDAYS(DATE(2025,1,1),DATE(2026,1,1),A1)", {(0, 0): "-2"}, ExcelError.NUM),
    ],
)
def test_workdays(formula, cells, want) -> None:
    _check(_ev(formula, cells), want)


@pytest.mark.parametrize(
    ("formula", "cells", "want"),
    [
        ("=DATE(0,0,0)", {}, ExcelError.NUM),
        ("=DATE(1900,0,1)", {}, ExcelError.NUM),
        ("=DATE(1900,-1,1)", {}, ExcelError.NUM),
        ("=DATE(2025,1,-1)", {}, 45656),
        ('=DATEVALUE("29-Feb-1900")', {}, 60),
        ('=DATEVALUE("1-Mar-1900")', {}, 61),
        ('=DATEVALUE("2024-02-29 06:00")', {}, 45351),
        ('=DATEVALUE("2026-07-16 4:35 PM")', {}, 46219),
        ('=DATEVALUE("1789-05-05")', {}, ExcelError.VALUE),
        ("=YEARFRAC(1,200,A1)", {(0, 0): "TRUE"}, ExcelError.VALUE),
        ("=WEEKNUM(A1,1)", {(0, 0): "TRUE"}, ExcelError.VALUE),
        ("=WEEKNUM(44561,A1)", {(0, 0): "TRUE"}, ExcelError.VALUE),
        ("=WEEKNUM(-1,A1)", {(0, 0): "TRUE"}, ExcelError.NUM),
        # Serial 1 is a Sunday in Excel, so it ends ISO week 52 of 1899.
        ("=ISOWEEKNUM(A1)", {(0, 0): "TRUE"}, 52),
        ("=ISOWEEKNUM(444)", {}, 12),
    ],
)
def test_dates(formula, cells, want) -> None:
    _check(_ev(formula, cells), want)
