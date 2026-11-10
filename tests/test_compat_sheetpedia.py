"""Cases where gridcalc disagreed with Excel on untuned Sheetpedia workbooks.

Expected values are Excel for Mac's saved results (`docs/dev/comparison.md`).
"""

import pytest

from gridcalc.dates import format_serial
from gridcalc.engine import Grid, Mode
from gridcalc.formula.errors import ExcelError


def _ev(formula: str, cells: dict[tuple[int, int], str] | None = None):
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk([(c, r, t) for (c, r), t in (cells or {}).items()])
    g.setcell(9, 9, formula)
    cl = g.cell(9, 9)
    if cl.err is not None:
        return cl.err
    return cl.sval if cl.sval is not None and not isinstance(cl.val, bool) else cl.val


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=IF(1=2,5)", False),
        ("=IF(1=2,5,)", 0),
        ("=IF(1=1,,5)", 0),
        ("=IF(1=2,5)+1", 1),
    ],
)
def test_if_with_an_omitted_false_branch_is_false(formula, value):
    got = _ev(formula)
    assert got == value
    assert isinstance(got, bool) is isinstance(value, bool)


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ('=TEXT(1,"dddd")', "Sunday"),
        ('=TEXT(4,"ddd")', "Wed"),  # WEEKDAY of 2014-01-01, read as a serial
        ('=TEXT(59,"ddd dd-mmm")', "Tue 28-Feb"),
        ('=TEXT(60,"ddd dd-mmm-yyyy")', "Wed 29-Feb-1900"),
        ('=TEXT(61,"ddd dd-mmm")', "Thu 01-Mar"),
        ('=TEXT(0,"dd-mmm-yyyy")', "00-Jan-1900"),
        ('=TEXT(0.25,"hh")', "06"),
        ('=TEXT(0.0875,"HH")&"h"', "02h"),
    ],
)
def test_text_follows_excels_1900_calendar(formula, value):
    assert _ev(formula) == value


def test_a_date_format_shows_the_phantom_leap_day():
    assert format_serial(60, "d-mmm-yyyy") == "29-Feb-1900"


# A1 blank; B1:B3 = 1, blank, 3; C1:C3 = a, b, c.
_TABLE = {(1, 0): "1", (1, 2): "3", (2, 0): "a", (2, 1): "b", (2, 2): "c"}


@pytest.mark.parametrize(
    "formula",
    ["=VLOOKUP(A1,B1:C3,2,FALSE)", "=MATCH(A1,B1:B3,0)", "=HLOOKUP(A1,B5:D6,2,FALSE)"],
)
def test_an_exact_lookup_of_a_blank_matches_no_blank_cell(formula):
    cells = {**_TABLE, (1, 4): "1", (3, 4): "3", (1, 5): "a", (2, 5): "b", (3, 5): "c"}
    assert _ev(formula, cells) is ExcelError.NA


def test_an_exact_lookup_of_a_value_still_matches():
    assert _ev("=VLOOKUP(3,B1:C3,2,FALSE)", _TABLE) == "c"


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ('="09/07/2022 12:38"-"06/24/2022 00:00"', 75.5263888888876),
        ('="06/24/2022 2:30 PM"+0', 44736.604166666664),
        ('="5-February-2024"*1', 45327),
        ('=DATEVALUE("06/24/2022 12:38")', 44736),
    ],
)
def test_date_time_text_reads_as_a_serial(formula, value):
    assert _ev(formula) == pytest.approx(value, rel=1e-12)


@pytest.mark.parametrize("formula", ['="abc 12:00"+0', '="06/24/2022 25:00"+0'])
def test_text_that_is_not_a_date_time_stays_an_error(formula):
    assert _ev(formula) is ExcelError.VALUE
