"""Excel date serials: classification, rendering, xlsx I/O, and criteria.

A date in a spreadsheet is a number wearing a number format, so every test
here is really about the pairing: the serial says *when*, the format code says
*that it is a when at all*. Losing either half turns a date column back into
five-digit floats, which is what `docs/reference/limitations.md` used to
promise.
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import pytest

from gridcalc.dates import (
    BUILTIN_DATE_FORMAT_IDS,
    format_serial,
    from_serial,
    has_time,
    is_date_format,
    normalise_format,
    parse_date,
    to_serial,
)
from gridcalc.display import cell_text, format_date
from gridcalc.engine import Grid, Mode

XLSX = Path(__file__).resolve().parent / "xlsx"


def _grid() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    return g


# --- serials ----------------------------------------------------------------


@pytest.mark.parametrize(
    "date, serial",
    [
        (dt.date(1900, 3, 1), 61.0),  # first day Excel and reality agree on
        (dt.date(2000, 1, 1), 36526.0),
        (dt.date(2024, 1, 1), 45292.0),
        (dt.date(2026, 5, 5), 46147.0),
    ],
)
def test_serials_match_excels_numbering(date, serial) -> None:
    assert to_serial(date) == serial
    assert from_serial(serial).date() == date


def test_a_time_of_day_is_the_fractional_part() -> None:
    assert to_serial(dt.datetime(2024, 3, 15, 12, 0, 0)) == 45366.5
    assert from_serial(45366.5) == dt.datetime(2024, 3, 15, 12, 0, 0)


def test_subtracting_two_dates_gives_days() -> None:
    """The reason serials are kept as plain numbers rather than a date type."""
    g = _grid()
    g.setcell(0, 0, str(to_serial(dt.date(2024, 1, 1))))
    g.setcell(0, 1, str(to_serial(dt.date(2024, 3, 15))))
    g.setcell(1, 0, "=A2-A1")
    g.recalc()
    assert g.cell(1, 0).val == 74.0


# --- classification ---------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    ["yyyy-mm-dd", "d-mmm-yy", "m/d/yyyy", "h:mm", "h:mm:ss AM/PM", "mm:ss", "[$-409]d/m/yyyy"],
)
def test_date_formats_are_recognised(code) -> None:
    assert is_date_format(code)


@pytest.mark.parametrize(
    "code",
    [
        "",
        "General",
        "0.00",
        "#,##0",
        "0.00%",
        "0.00E+00",
        "@",
        "$#,##0.00_);[Red]($#,##0.00)",
        '0" days"',  # a `d` that lives inside a literal, not a token
    ],
)
def test_numeric_formats_are_not_mistaken_for_dates(code) -> None:
    """The conservative direction: a misread here turns a price into a year."""
    assert not is_date_format(code)


def test_builtin_format_ids_resolve_without_a_code() -> None:
    """xlsx omits the format string for built-in ids, so the id is all there is."""
    assert normalise_format("", 14) == "yyyy-mm-dd"
    assert normalise_format("", 22) == "yyyy-mm-dd h:mm"
    assert all(normalise_format("", i) for i in BUILTIN_DATE_FORMAT_IDS)
    assert normalise_format("", 2) == ""  # 0.00, a numeric built-in
    assert normalise_format("0.00", None) == ""


def test_an_explicit_code_wins_over_the_id() -> None:
    assert normalise_format("dddd", 14) == "dddd"


def test_has_time_distinguishes_a_date_from_a_timestamp() -> None:
    assert not has_time("yyyy-mm-dd")
    assert has_time("yyyy-mm-dd h:mm")
    assert has_time("h:mm:ss")


# --- rendering --------------------------------------------------------------


@pytest.mark.parametrize(
    "code, want",
    [
        ("yyyy-mm-dd", "2026-05-05"),
        ("yy-m-d", "26-5-5"),
        ("d-mmm-yy", "5-May-26"),
        ("mmmm d, yyyy", "May 5, 2026"),
        ("dddd", "Tuesday"),
        ("ddd", "Tue"),
        ("m/d/yy", "5/5/26"),
        ("mmm-yy", "May-26"),
        ("yyyy-mm-dd h:mm", "2026-05-05 14:30"),
        ("h:mm:ss", "14:30:05"),
        ("h:mm AM/PM", "2:30 PM"),
    ],
)
def test_format_codes_render(code, want) -> None:
    serial = to_serial(dt.datetime(2026, 5, 5, 14, 30, 5))
    assert format_serial(serial, code) == want


def test_m_means_minutes_after_an_hour_token_and_months_before_one() -> None:
    """The one genuine ambiguity in the format language."""
    serial = to_serial(dt.datetime(2026, 5, 5, 14, 30, 5))
    assert format_serial(serial, "mm") == "05"  # month
    assert format_serial(serial, "h:mm") == "14:30"  # minutes


def test_a_quoted_literal_is_emitted_verbatim() -> None:
    serial = to_serial(dt.date(2026, 5, 5))
    assert format_serial(serial, 'yyyy" on the "d') == "2026 on the 5"


def test_a_serial_with_no_date_is_left_as_a_number() -> None:
    """Excel shows ##### for a negative serial; a number is more informative."""
    assert format_serial(-1.0, "yyyy-mm-dd") is None
    assert format_serial(1e12, "yyyy-mm-dd") is None


def test_format_date_ignores_a_numeric_spec() -> None:
    """`fmtstr` holds two languages; neither may claim the other's specs."""
    assert format_date(45292.0, ",.2f") is None
    assert format_date(45292.0, "yyyy-mm-dd") == "2024-01-01"


# --- display ----------------------------------------------------------------


def test_a_cell_with_a_date_format_displays_as_a_date() -> None:
    g = _grid()
    g.setcell(0, 0, "45292")
    assert cell_text(g.cell(0, 0)) == "45292"
    g.cell(0, 0).fmtstr = "yyyy-mm-dd"
    assert cell_text(g.cell(0, 0)) == "2024-01-01"


def test_a_numeric_fmtstr_still_formats_as_a_number() -> None:
    g = _grid()
    g.setcell(0, 0, "1234.5")
    g.cell(0, 0).fmtstr = ",.2f"
    assert cell_text(g.cell(0, 0)) == "1,234.50"


def test_a_formula_result_can_carry_a_date_format() -> None:
    g = _grid()
    g.setcell(0, 0, "=DATE(2026,5,5)")
    g.recalc()
    g.cell(0, 0).fmtstr = "yyyy-mm-dd"
    assert cell_text(g.cell(0, 0)) == "2026-05-05"


# --- xlsx I/O ---------------------------------------------------------------


def test_reading_an_xlsx_recovers_the_date_format() -> None:
    g = Grid()
    assert g.xlsxload(str(XLSX / "dates.xlsx")) == 0
    assert g.cell(0, 0).fmtstr == "yyyy-mm-dd"
    assert g.cell(0, 0).val == 45292.0
    assert cell_text(g.cell(0, 0)) == "2024-01-01"
    assert cell_text(g.cell(0, 1)) == "2024-03-15 12:00:00"


def test_a_computed_day_count_does_not_inherit_a_date_format() -> None:
    """`=A2-A1` is 74.5 days, not a date in 1900.

    Only cells the file actually styled as dates get a format, so a computed
    difference stays a number. That is the safe direction: a day count shown
    as a date is a wrong answer, where a date shown as a serial is merely an
    ugly one.
    """
    g = Grid()
    g.xlsxload(str(XLSX / "dates.xlsx"))
    assert g.cell(1, 0).fmtstr == ""
    assert cell_text(g.cell(1, 0)) == "74.5"


def test_dates_survive_an_xlsx_round_trip(tmp_path) -> None:
    src = Grid()
    src.xlsxload(str(XLSX / "dates.xlsx"))
    dest = tmp_path / "rt.xlsx"
    assert src.xlsxsave(str(dest)) == 0
    back = Grid()
    assert back.xlsxload(str(dest)) == 0
    for r in range(3):
        assert back.cell(0, r).val == src.cell(0, r).val
        assert back.cell(0, r).fmtstr == src.cell(0, r).fmtstr
        assert cell_text(back.cell(0, r)) == cell_text(src.cell(0, r))


def test_distinct_formats_do_not_collide_in_the_written_style_table(tmp_path) -> None:
    """Two different date formats must come back as two different formats.

    They did not: the writer took a *copy* of the style table, so the second
    format's index pointed at the first one's entry in the saved file and
    every timestamp came back as a bare date.
    """
    g = _grid()
    serial = to_serial(dt.datetime(2024, 3, 15, 12, 0, 0))
    for i, code in enumerate(["yyyy-mm-dd", "yyyy-mm-dd h:mm:ss", "d-mmm-yy", "mmmm yyyy"]):
        g.setcell(0, i, str(serial))
        g.cell(0, i).fmtstr = code
    dest = tmp_path / "many.xlsx"
    assert g.xlsxsave(str(dest)) == 0
    back = Grid()
    back.xlsxload(str(dest))
    assert [back.cell(0, i).fmtstr for i in range(4)] == [
        "yyyy-mm-dd",
        "yyyy-mm-dd h:mm:ss",
        "d-mmm-yy",
        "mmmm yyyy",
    ]
    assert cell_text(back.cell(0, 1)) == "2024-03-15 12:00:00"
    assert cell_text(back.cell(0, 3)) == "March 2024"


def test_a_date_format_survives_a_json_round_trip(tmp_path) -> None:
    g = _grid()
    g.setcell(0, 0, "45292")
    g.cell(0, 0).fmtstr = "yyyy-mm-dd"
    dest = tmp_path / "book.json"
    g.jsonsave(str(dest))
    back = Grid()
    back.jsonload(str(dest))
    assert back.cell(0, 0).fmtstr == "yyyy-mm-dd"
    assert cell_text(back.cell(0, 0)) == "2024-01-01"


def test_a_plain_number_gets_no_format_on_export(tmp_path) -> None:
    g = _grid()
    g.setcell(0, 0, "42")
    dest = tmp_path / "plain.xlsx"
    g.xlsxsave(str(dest))
    back = Grid()
    back.xlsxload(str(dest))
    assert back.cell(0, 0).fmtstr == ""
    assert cell_text(back.cell(0, 0)) == "42"


# --- criteria ---------------------------------------------------------------


def _date_column() -> Grid:
    g = _grid()
    for i, d in enumerate(
        [dt.date(2019, 6, 1), dt.date(2020, 3, 15), dt.date(2021, 1, 1), dt.date(2019, 12, 31)]
    ):
        g.setcell(0, i, str(to_serial(d)))
        g.cell(0, i).fmtstr = "yyyy-mm-dd"
    return g


@pytest.mark.parametrize(
    "criteria, want",
    [
        ('">1/1/2020"', 2.0),
        ('"<2020-01-01"', 2.0),
        ('">=2019-12-31"', 3.0),
        ('"2021-01-01"', 1.0),
        ('"<>2021-01-01"', 3.0),
    ],
)
def test_countif_understands_date_criteria(criteria, want) -> None:
    """Without date parsing these compared strings, where "9/1" sorts after
    "10/1" and the answer is quietly wrong rather than an error."""
    g = _date_column()
    g.setcell(2, 0, f"=COUNTIF(A1:A4, {criteria})")
    g.recalc()
    assert g.cell(2, 0).val == want


def test_sumif_understands_date_criteria() -> None:
    g = _date_column()
    g.setcell(2, 0, '=SUMIF(A1:A4, ">1/1/2020", A1:A4)')
    g.recalc()
    expected = to_serial(dt.date(2020, 3, 15)) + to_serial(dt.date(2021, 1, 1))
    assert g.cell(2, 0).val == expected


def test_text_criteria_still_behave_as_text() -> None:
    """Date parsing must not swallow ordinary string comparisons."""
    g = _grid()
    for i, name in enumerate(["apple", "banana", "apricot"]):
        g.setcell(0, i, name)
    g.setcell(2, 0, '=COUNTIF(A1:A3, "ap*")')
    g.setcell(2, 1, '=COUNTIF(A1:A3, ">b")')
    g.recalc()
    assert g.cell(2, 0).val == 2.0
    assert g.cell(2, 1).val == 1.0


def test_numeric_criteria_are_unaffected() -> None:
    g = _grid()
    for i, n in enumerate([1, 5, 10, 20]):
        g.setcell(0, i, str(n))
    g.setcell(2, 0, '=COUNTIF(A1:A4, ">5")')
    g.recalc()
    assert g.cell(2, 0).val == 2.0


@pytest.mark.parametrize(
    "text, date",
    [
        ("2020-01-01", dt.date(2020, 1, 1)),
        ("1/1/2020", dt.date(2020, 1, 1)),
        ("2020/06/15", dt.date(2020, 6, 15)),
        ("15-Jun-2020", dt.date(2020, 6, 15)),
    ],
)
def test_parse_date_accepts_the_common_spellings(text, date) -> None:
    assert parse_date(text) == to_serial(date)


@pytest.mark.parametrize("text", ["", "not a date", "banana", "5", "1.5"])
def test_parse_date_rejects_everything_else(text) -> None:
    assert parse_date(text) is None


# --- the library and the display agree on the epoch -------------------------


def test_the_function_library_uses_the_shared_epoch() -> None:
    """`DATE()` and the display layer must produce and read the same serial,
    which is why the conversions moved into one module."""
    g = _grid()
    g.setcell(0, 0, "=DATE(2024,1,1)")
    g.recalc()
    assert g.cell(0, 0).val == to_serial(dt.date(2024, 1, 1))
    g.cell(0, 0).fmtstr = "yyyy-mm-dd"
    assert cell_text(g.cell(0, 0)) == "2024-01-01"


def test_year_month_day_round_trip_through_the_shared_conversion() -> None:
    g = _grid()
    g.setcell(0, 0, "=DATE(2026,5,5)")
    g.setcell(1, 0, "=YEAR(A1)")
    g.setcell(2, 0, "=MONTH(A1)")
    g.setcell(3, 0, "=DAY(A1)")
    g.recalc()
    assert (g.cell(1, 0).val, g.cell(2, 0).val, g.cell(3, 0).val) == (2026.0, 5.0, 5.0)
    assert not math.isnan(g.cell(0, 0).val)


# --- both frontends set a date format through the shared registry -----------


def test_the_format_command_accepts_a_date_code() -> None:
    """`:f yyyy-mm-dd` needed no new code path: `apply_format` already routed
    an unrecognised spec to `fmtstr`, and the display layer now reads it as a
    date. The test pins that, since the routing is what makes it work."""
    from gridcalc.commands import apply_format
    from gridcalc.undo import UndoManager

    g = _grid()
    g.setcell(0, 0, str(to_serial(dt.date(2026, 5, 5))))
    assert apply_format(g, UndoManager(), 0, 0, 0, 0, "yyyy-mm-dd")
    assert g.cell(0, 0).fmtstr == "yyyy-mm-dd"
    assert cell_text(g.cell(0, 0)) == "2026-05-05"


def test_a_numeric_format_char_clears_a_date_format() -> None:
    from gridcalc.commands import apply_format
    from gridcalc.undo import UndoManager

    g = _grid()
    g.setcell(0, 0, "45292")
    apply_format(g, UndoManager(), 0, 0, 0, 0, "yyyy-mm-dd")
    apply_format(g, UndoManager(), 0, 0, 0, 0, "I")
    assert g.cell(0, 0).fmtstr == ""
    assert cell_text(g.cell(0, 0)) == "45292"


def test_the_web_view_renders_dates_identically_to_the_tui() -> None:
    """Both frontends format through `display.cell_text`, so dates reached the
    desktop app with no web-side change. Asserted rather than assumed."""
    from gridcalc.web import Api

    g = _grid()
    g.setcell(0, 0, str(to_serial(dt.date(2026, 5, 5))))
    api = Api(g)
    assert api.set_format(0, 0, 0, 0, "yyyy-mm-dd")["ok"]
    cells = api.viewport(0, 0, 2, 2)["cells"]
    shown = [c for c in cells if c["r"] == 0 and c["c"] == 0]
    assert shown and shown[0]["text"] == cell_text(g.cell(0, 0)) == "2026-05-05"
