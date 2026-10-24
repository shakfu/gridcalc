"""Excel number-format codes (`gridcalc.numfmt`)."""

import pytest

from gridcalc.numfmt import format_value, split_sections

ACCOUNTING = '_($* #,##0.00_);_($* (#,##0.00);_($* "-"??_);_(@_)'


@pytest.mark.parametrize(
    ("code", "value", "text"),
    [
        ("$#,##0.00_);($#,##0.00)", 1234.567, "$1,234.57 "),
        ("$#,##0.00_);($#,##0.00)", -1234.567, "($1,234.57)"),
        (ACCOUNTING, 1234.567, " $1,234.57 "),
        (ACCOUNTING, 0, " $-   "),
        (ACCOUNTING, "x", " x "),
        ('0.0,,"M"', 1234567, "1.2M"),
        ("#,##0,", 1234567, "1,235"),
        ("# ?/?", 1.25, "1 1/4"),
        ("?/4", 0.75, "3/4"),
        ("# ??/100", 2.5, "2 50/100"),
        ("00000", 123, "00123"),
        ("0.00E+00", 1234.567, "1.23E+03"),
        ("0.00E+00", 0.000123, "1.23E-04"),
        ("##0.0E+0", 12345, "12.3E+3"),
        ("[>=1000]#,##0;0", 1234, "1,234"),
        ("[>=1000]#,##0;0", 5, "5"),
        ("[Red]0.00", 1234.567, "1234.57"),
        ("#,##0;[Red]-#,##0", -1234.567, "-1,235"),
        ("0%", 0.256, "26%"),
        ("0.0%", -0.0123, "-1.2%"),
        ("#.##", 0, "."),
        ("0.###", 2, "2."),
        ("0.###", 1.5, "1.5"),
        ("#,##0", 1234567, "1,234,567"),
        ("#,###", 0, ""),
        ("#", 0.4, ""),
        (".00", 5.25, "5.25"),
        (".00", 0.25, ".25"),
        ("#,##0.00", 0.5, "0.50"),
        ('"Total: "0', 5, "Total: 5"),
        ("0;-0;;@", 0, ""),
        ("0.00", "abc", "abc"),
        ('"Name: "@', "Bo", "Name: Bo"),
        ("[$€-2] #,##0.00", 1234.5, "€ 1,234.50"),
        ("0.00", -0.001, "0.00"),
        ("0", 2.5, "3"),
        ("0", -2.5, "-3"),
        ("0.00;(0.00)", -3, "(3.00)"),
        ("yyyy-mm-dd", 45000, "2023-03-15"),
        ("General;General", -5, "5"),  # a negative section shows no minus of its own
    ],
)
def test_format_value(code, value, text) -> None:
    assert format_value(value, code).text == text


def test_a_section_colour_is_returned_not_printed() -> None:
    assert format_value(-1, "#,##0;[Red]-#,##0") == ("-1", "red")
    assert format_value(1, "#,##0;[Red]-#,##0") == ("1", None)


def test_sections_split_outside_quotes_and_brackets() -> None:
    assert split_sections('0;"a;b";[<0]0') == ["0", '"a;b"', "[<0]0"]
