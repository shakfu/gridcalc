"""Excel function semantics, evaluated through `Grid` in EXCEL mode.

Direct calls and PYTHON-mode grids bypass the evaluator's coercion and the
engine globals that EXCEL mode resolves names against, so they hid most of
the bugs these tests pin. Expected values come from the examples on the
Microsoft support page for each function unless a comment says otherwise.
"""

from __future__ import annotations

import math
from typing import Any

import pytest

from gridcalc.engine import Grid, Mode
from gridcalc.formula.errors import ExcelError

# A1:A3 = 1,2,3; B1:B3 = 4,5,6; C1:C3 = 7,8,9; D1:D2 text; E1:I1 = 10..50
BASE = {
    "A1": 1,
    "A2": 2,
    "A3": 3,
    "B1": 4,
    "B2": 5,
    "B3": 6,
    "C1": 7,
    "C2": 8,
    "C3": 9,
    "D1": "a",
    "D2": "b",
    "E1": 10,
    "F1": 20,
    "G1": 30,
    "H1": 40,
    "I1": 50,
    "A6": 12345,
    "A7": 100,
}


def _pos(ref: str) -> tuple[int, int]:
    col = ord(ref[0]) - ord("A")
    return col, int(ref[1:]) - 1


def ev(formula: str, cells: dict[str, Any] | None = None) -> Any:
    """Evaluate `formula` in an EXCEL-mode grid holding `cells` (default BASE).

    Returns the error, the spilled list, the string, or the number."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    for ref, v in (BASE if cells is None else cells).items():
        c, r = _pos(ref)
        g.setcell(c, r, v if isinstance(v, str) else repr(v))
    g.setcell(25, 99, formula)
    cell = g.cells[25][99]
    if cell.err is not None:
        return cell.err
    if cell.arr is not None:
        return list(cell.arr)
    if cell.sval is not None:
        return cell.sval
    return cell.val


def approx(x: float, rel: float = 1e-8) -> Any:
    return pytest.approx(x, rel=rel, abs=1e-12)


class TestRound:
    """L1, L8: half away from zero, 15-digit snap before rounding."""

    @pytest.mark.parametrize(
        ("formula", "expected"),
        [
            ("=ROUND(2.15, 1)", 2.2),
            ("=ROUND(2.149, 1)", 2.1),
            ("=ROUND(-1.475, 2)", -1.48),
            ("=ROUND(21.5, -1)", 20.0),
            ("=ROUND(626.3, -3)", 1000.0),
            ("=ROUND(1.98, -1)", 0.0),
            ("=ROUND(-50.55, -2)", -100.0),
            ("=ROUND(2.5, 0)", 3.0),
            ("=ROUND(-2.5, 0)", -3.0),
            ("=ROUND(2.675, 2)", 2.68),
            ("=ROUNDUP(3.2, 0)", 4.0),
            ("=ROUNDUP(76.9, 0)", 77.0),
            ("=ROUNDUP(3.14159, 3)", 3.142),
            ("=ROUNDUP(-3.14159, 1)", -3.2),
            ("=ROUNDUP(31415.92654, -2)", 31500.0),
            ("=ROUNDDOWN(3.2, 0)", 3.0),
            ("=ROUNDDOWN(76.9, 0)", 76.0),
            ("=ROUNDDOWN(3.14159, 3)", 3.141),
            ("=ROUNDDOWN(-3.14159, 1)", -3.1),
            ("=ROUNDDOWN(31415.92654, -2)", 31400.0),
            ("=ROUNDDOWN(4.35, 2)", 4.35),
            ("=TRUNC(4.35, 2)", 4.35),
            ("=TRUNC(8.9)", 8.0),
            ("=TRUNC(-8.9)", -8.0),
            ("=FLOOR(0.3, 0.1)", 0.3),
            ("=CEILING(0.7, 0.1)", 0.7),
        ],
    )
    def test_round_family(self, formula: str, expected: float) -> None:
        assert ev(formula) == expected

    def test_round_from_cell(self) -> None:
        assert ev("=ROUND(A1/3, 2)") == 0.33


class TestInt:
    """L2."""

    def test_int_rounds_down(self) -> None:
        assert ev("=INT(8.9)") == 8.0
        assert ev("=INT(-8.9)") == -9.0
        assert ev("=INT(-2.5)") == -3.0

    def test_python_mode_int_unchanged(self) -> None:
        g = Grid()
        g.setcell(0, 0, "=INT(-2.5)")
        assert g.cells[0][0].val == -2.0


class TestMathNames:
    """L3: engine math globals must resolve with Excel semantics."""

    @pytest.mark.parametrize(
        ("formula", "expected"),
        [
            ("=LOG(10)", 1.0),
            ("=LOG(100)", 2.0),
            ("=LOG(8, 2)", 3.0),
            ("=LOG(86, 2.7182818)", 4.4543473),
            ("=LN(86)", 4.4543473),
            ("=LN(EXP(3))", 3.0),
            ("=PI()", math.pi),
            ("=EXP(1)", math.e),
            ("=SQRT(16)", 4.0),
            ("=ABS(-4)", 4.0),
            ("=COS(1.047)", 0.5001711),
            ("=TAN(0.785)", 0.99920399),
            ("=ASIN(-0.5)", -0.523598776),
            ("=ACOS(-0.5)", 2.094395102),
            ("=ATAN(1)", 0.785398163),
        ],
    )
    def test_value(self, formula: str, expected: float) -> None:
        assert ev(formula) == approx(expected, rel=1e-7)

    @pytest.mark.parametrize(
        ("formula", "expected"),
        [
            ("=LOG(0)", ExcelError.NUM),
            ("=LN(0)", ExcelError.NUM),
            ("=SQRT(-16)", ExcelError.NUM),
            ("=LOG(10, 1)", ExcelError.DIV0),
        ],
    )
    def test_error(self, formula: str, expected: ExcelError) -> None:
        assert ev(formula) is expected

    def test_log10(self) -> None:
        assert ev("=LOG10(86)") == approx(1.934498451)
        assert ev("=LOG10(10^5)") == 5.0

    def test_atan2(self) -> None:
        # Excel's argument order is (x, y), the reverse of math.atan2.
        assert ev("=ATAN2(1, 1)") == approx(0.785398163)
        assert ev("=ATAN2(-1, -1)") == approx(-2.35619449)
        assert ev("=ATAN2(1, 2)") == approx(math.atan2(2, 1))
        assert ev("=ATAN2(0, 0)") is ExcelError.DIV0


class TestTextCoercion:
    """L4: numbers and logicals render as `&` renders them."""

    @pytest.mark.parametrize(
        ("formula", "expected"),
        [
            ("=LEN(A6)", 5.0),
            ("=RIGHT(A6, 2)", "45"),
            ("=LEFT(A6, 3)", "123"),
            ("=MID(A6, 2, 2)", "23"),
            ('=CONCATENATE("x", A7)', "x100"),
            ("=CONCAT(A1:A3)", "123"),
            ('=TEXTJOIN(",", TRUE, A1:A2)', "1,2"),
            ('=TEXTJOIN("-", TRUE, 1.5, 2)', "1.5-2"),
            ("=LEFT(TRUE, 2)", "TR"),
            ("=UPPER(TRUE)", "TRUE"),
            ('=SUBSTITUTE(A7, "0", "9")', "199"),
            ("=REPT(A1, 3)", "111"),
            ('=EXACT(A7, "100")', "TRUE"),
            ('=FIND("4", A6)', 4.0),
            ("=TRIM(A7)", "100"),
        ],
    )
    def test_text(self, formula: str, expected: Any) -> None:
        assert ev(formula) == expected


class TestDate:
    """L5: out-of-range month/day roll over; years below 1900 add 1900."""

    @pytest.mark.parametrize(
        ("formula", "expected"),
        [
            ("=DATE(2008, 1, 1)", 39448.0),
            ("=DATE(2008, 14, 2) = DATE(2009, 2, 2)", "TRUE"),
            ("=DATE(2008, -3, 2) = DATE(2007, 9, 2)", "TRUE"),
            ("=DATE(2008, 1, 35) = DATE(2008, 2, 4)", "TRUE"),
            ("=DATE(2008, 1, -15) = DATE(2007, 12, 16)", "TRUE"),
            ("=DATE(2026, 1, 0) = DATE(2025, 12, 31)", "TRUE"),
            ("=DATE(2026, 2, 30) = DATE(2026, 3, 2)", "TRUE"),
            ("=DATE(108, 1, 2) = DATE(2008, 1, 2)", "TRUE"),
            ("=DATE(-1, 1, 1)", ExcelError.NUM),
            ("=DATE(10000, 1, 1)", ExcelError.NUM),
        ],
    )
    def test_date(self, formula: str, expected: Any) -> None:
        assert ev(formula) == expected


class TestVariadicStats:
    """L6."""

    DATA = "1345,1301,1368,1322,1310,1370,1318,1350,1303,1299"

    @pytest.mark.parametrize(
        ("formula", "expected"),
        [
            ("=MEDIAN(1,2,3,4,5,6)", 3.5),
            ("=MEDIAN(A1:A3, 10)", 2.5),
            (f"=STDEV({DATA})", 27.46391572),
            (f"=STDEV.S({DATA})", 27.46391572),
            (f"=STDEVP({DATA})", 26.05455814),
            (f"=STDEV.P({DATA})", 26.05455814),
            (f"=VAR({DATA})", 754.2666667),
            (f"=VAR.S({DATA})", 754.2666667),
            (f"=VARP({DATA})", 678.84),
            (f"=VAR.P({DATA})", 678.84),
            ("=MODE(5.6,4,4,3,2,4)", 4.0),
            ("=MODE.SNGL(5.6,4,4,3,2,4)", 4.0),
            ("=GEOMEAN(4,5,8,7,11,4,3)", 5.476986969),
            ("=HARMEAN(4,5,8,7,11,4,3)", 5.028375962),
            ("=AVEDEV(4,5,6,7,5,4,3)", 1.020408163),
            ("=DEVSQ(4,5,8,7,11,4,3)", 48.0),
            ("=SKEW(3,4,5,2,3,4,5,6,4,7)", 0.359543071),
            ("=KURT(3,4,5,2,3,4,5,6,4,7)", -0.151799637),
            ("=STDEV(A1:A3, B1:B3)", 1.870828693),
        ],
    )
    def test_variadic(self, formula: str, expected: float) -> None:
        assert ev(formula) == approx(expected)


class TestSumproduct:
    """L7."""

    def test_single_array(self) -> None:
        assert ev("=SUMPRODUCT(A1:A3)") == 6.0

    def test_three_arrays(self) -> None:
        assert ev("=SUMPRODUCT(A1:A3, B1:B3, C1:C3)") == 270.0

    def test_mask_idiom(self) -> None:
        assert ev("=SUMPRODUCT((A1:A3>1)*B1:B3)") == 11.0

    def test_size_mismatch(self) -> None:
        assert ev("=SUMPRODUCT(A1:A3, B1:B2)") is ExcelError.VALUE


LOOKUP_CELLS = {
    "A1": "A",
    "A2": "B",
    "A3": "C",
    "B1": 1,
    "B2": 2,
    "B3": 3,
    "C1": 50,
    "C2": "5*",
    "D1": "first",
    "D2": "second",
    "E5": 1,
    "F5": 2,
    "G5": 3,
    "H5": 4,
    "I5": 5,
    "E6": "x1",
    "F6": "x2",
    "G6": "x3",
    "H6": "x4",
    "I6": "x5",
    "E7": "y1",
    "F7": "y2",
    "G7": "y3",
    "H7": "y4",
    "I7": "y5",
    "E9": "A",
    "F9": "B",
    "G9": "C",
    "E10": 1,
    "F10": 2,
    "G10": 3,
}


class TestXlookup:
    """L9."""

    def test_horizontal(self) -> None:
        assert ev("=XLOOKUP(3, E5:I5, E6:I6)", LOOKUP_CELLS) == "x3"

    def test_horizontal_returns_column(self) -> None:
        assert ev("=XLOOKUP(3, E5:I5, E6:I7)", LOOKUP_CELLS) == ["x3", "y3"]

    def test_horizontal_size_mismatch(self) -> None:
        assert ev("=XLOOKUP(3, E5:I5, E6:H6)", LOOKUP_CELLS) is ExcelError.VALUE

    def test_exact_mode_is_literal(self) -> None:
        assert ev('=XLOOKUP("5*", C1:C2, D1:D2)', LOOKUP_CELLS) == "second"
        assert ev('=XMATCH("5*", C1:C2)', LOOKUP_CELLS) == 2.0

    def test_wildcard_mode(self) -> None:
        assert ev('=XMATCH("s*", D1:D2, 2)', LOOKUP_CELLS) == 2.0


class TestApproximateLookupCase:
    """L11."""

    def test_vlookup(self) -> None:
        assert ev('=VLOOKUP("b", A1:B3, 2, TRUE)', LOOKUP_CELLS) == 2.0

    def test_hlookup(self) -> None:
        assert ev('=HLOOKUP("b", E9:G10, 2, TRUE)', LOOKUP_CELLS) == 2.0

    def test_match(self) -> None:
        assert ev('=MATCH("b", A1:A3, 1)', LOOKUP_CELLS) == 2.0


class TestEdgeCases:
    """L12."""

    def test_index_single_row(self) -> None:
        assert ev("=INDEX(E1:I1, 3)") == 30.0
        assert ev("=INDEX(E1:I1, 1, 3)") == 30.0

    @pytest.mark.parametrize(
        "formula",
        ["=LARGE(A1:A3, 0)", "=LARGE(A1:A3, 4)", "=SMALL(A1:A3, 0)", "=SMALL(A1:A3, 4)"],
    )
    def test_large_small_bounds(self, formula: str) -> None:
        assert ev(formula) is ExcelError.NUM

    def test_average_no_numbers(self) -> None:
        assert ev("=AVERAGE(D1:D2)") is ExcelError.DIV0

    def test_median_no_numbers(self) -> None:
        assert ev("=MEDIAN(D1:D2)") is ExcelError.NUM


class TestMultiples:
    """L13."""

    @pytest.mark.parametrize(
        ("formula", "expected"),
        [
            ("=MROUND(10, 3)", 9.0),
            ("=MROUND(-10, -3)", -9.0),
            ("=MROUND(1.3, 0.2)", 1.4),
            ("=MROUND(2.5, 1)", 3.0),
            ("=MROUND(5, -2)", ExcelError.NUM),
            ("=CEILING(2.5, 1)", 3.0),
            ("=CEILING(-2.5, -2)", -4.0),
            ("=CEILING(-2.5, 2)", -2.0),
            ("=CEILING(1.5, 0.1)", 1.5),
            ("=CEILING(0.234, 0.01)", 0.24),
            ("=CEILING(2.5, -2)", ExcelError.NUM),
            ("=FLOOR(3.7, 2)", 2.0),
            ("=FLOOR(-2.5, -2)", -2.0),
            ("=FLOOR(1.58, 0.1)", 1.5),
            ("=FLOOR(0.234, 0.01)", 0.23),
            ("=FLOOR(2.5, -2)", ExcelError.NUM),
        ],
    )
    def test_multiples(self, formula: str, expected: Any) -> None:
        assert ev(formula) == expected


class TestFormatting:
    """L14."""

    @pytest.mark.parametrize(
        ("formula", "expected"),
        [
            ('=TEXT(5, "00")', "05"),
            ('=TEXT(DATE(2026, 5, 5), "yyyy-mm-dd")', "2026-05-05"),
            ('=TEXT(1234.567, "$#,##0.00")', "$1,234.57"),
            ('=TEXT(0.285, "0.0%")', "28.5%"),
            ('=TEXT(2.5, "0")', "3"),
            ('=TEXT(-1234.5, "#,##0")', "-1,235"),
            ('=TEXT(1234.5, "0.00")', "1234.50"),
            ('=TEXT(0.5, "#.00")', ".50"),
            ('=TEXT(1.5, "0.##")', "1.5"),
            ("=FIXED(1234.567, 1)", "1,234.6"),
            ("=FIXED(1234.567, -1)", "1,230"),
            ("=FIXED(-1234.567, -1, TRUE)", "-1230"),
            ("=FIXED(44.332)", "44.33"),
            ("=FIXED(2.5, 0)", "3"),
            ("=DOLLAR(1234.567, 2)", "$1,234.57"),
            ("=DOLLAR(1234.567, -2)", "$1,200"),
            ("=DOLLAR(-1234.567, -2)", "($1,200)"),
            ("=DOLLAR(-0.123, 4)", "($0.1230)"),
            ("=DOLLAR(99.888)", "$99.89"),
            ("=DOLLAR(0.125, 2)", "$0.13"),
            ('=TRIM("  a  b   c ")', "a b c"),
            ('=SEARCH("l*o", "hello")', 3.0),
            ('=SEARCH("?l", "hello")', 2.0),
            ('=SEARCH("~*", "a*b")', 2.0),
            ('=VALUE("50%")', 0.5),
            ('=VALUE("$1,000")', 1000.0),
        ],
    )
    def test_formatting(self, formula: str, expected: Any) -> None:
        assert ev(formula) == expected


DAY_CELLS = {
    "A1": "=DATE(2012,10,1)",
    "A2": "=DATE(2013,3,1)",
    "A3": "=DATE(2012,11,22)",
    "A4": "=DATE(2012,12,4)",
    "A5": "=DATE(2013,1,21)",
    "B1": "=DATE(2008,10,1)",
    "B2": "=DATE(2008,11,26)",
    "B3": "=DATE(2008,12,4)",
    "B4": "=DATE(2009,1,21)",
}


class TestDateFunctions:
    """L15."""

    @pytest.mark.parametrize(
        ("rtype", "expected"),
        [(1, 3), (2, 2), (3, 1), (11, 2), (12, 1), (13, 7), (14, 6), (15, 5), (16, 4), (17, 3)],
    )
    def test_weekday_types(self, rtype: int, expected: int) -> None:
        # 2026-05-05 is a Tuesday.
        assert ev(f"=WEEKDAY(DATE(2026,5,5), {rtype})") == float(expected)

    def test_weekday_doc(self) -> None:
        assert ev("=WEEKDAY(DATE(2008,2,14))") == 5.0

    def test_weekday_invalid_type(self) -> None:
        assert ev("=WEEKDAY(DATE(2026,5,5), 4)") is ExcelError.NUM

    @pytest.mark.parametrize(
        ("rtype", "expected"),
        [(1, 10), (2, 11), (11, 11), (12, 11), (16, 10), (17, 10), (21, 10)],
    )
    def test_weeknum_types(self, rtype: int, expected: int) -> None:
        # 2012-03-09 is a Friday; 2012-01-01 a Sunday.
        assert ev(f"=WEEKNUM(DATE(2012,3,9), {rtype})") == float(expected)

    def test_weeknum_invalid_type(self) -> None:
        assert ev("=WEEKNUM(DATE(2012,3,9), 3)") is ExcelError.NUM

    @pytest.mark.parametrize(
        ("unit", "expected"), [("D", 440), ("YD", 75), ("MD", 14), ("YM", 2), ("M", 14)]
    )
    def test_datedif(self, unit: str, expected: int) -> None:
        assert ev(f'=DATEDIF(DATE(2001,6,1), DATE(2002,8,15), "{unit}")') == float(expected)

    def test_networkdays_holidays(self) -> None:
        assert ev("=NETWORKDAYS(A1, A2)", DAY_CELLS) == 110.0
        assert ev("=NETWORKDAYS(A1, A2, A3)", DAY_CELLS) == 109.0
        assert ev("=NETWORKDAYS(A1, A2, A3:A5)", DAY_CELLS) == 107.0

    def test_networkdays_reversed(self) -> None:
        assert ev("=NETWORKDAYS(A2, A1)", DAY_CELLS) == -110.0

    def test_workday_holidays(self) -> None:
        assert ev("=WORKDAY(B1, 151) = DATE(2009,4,30)", DAY_CELLS) == "TRUE"
        assert ev("=WORKDAY(B1, 151, B2:B4) = DATE(2009,5,5)", DAY_CELLS) == "TRUE"


class TestFinancialFractionalNper:
    """L16."""

    def test_pmt(self) -> None:
        assert ev("=PMT(0.08/12, 10, 10000)") == pytest.approx(-1037.03, abs=0.005)
        assert ev("=PMT(0.05, 10.5, 1000)") == approx(-1000 * 1.05**10.5 * 0.05 / (1.05**10.5 - 1))

    def test_pv(self) -> None:
        assert ev("=PV(0.08/12, 12*20, 500)") == pytest.approx(-59777.15, abs=0.005)
        assert ev("=PV(0.05, 2.5, -100)") == approx(100 * (1 - 1.05**-2.5) / 0.05)

    def test_rate_round_trips(self) -> None:
        assert ev("=PMT(RATE(10.5, -100, 800), 10.5, 800)") == approx(-100.0)

    def test_fv(self) -> None:
        assert ev("=FV(0.06/12, 10, -200, -500, 1)") == pytest.approx(2581.40, abs=0.005)
        assert ev("=FV(0.05, 2.5, -100)") == approx(100 * (1.05**2.5 - 1) / 0.05)


class TestTailsAndValidation:
    """L18."""

    def test_norm_s_dist_lower_tail(self) -> None:
        assert ev("=NORM.S.DIST(-10, TRUE)") == approx(7.61985302416047e-24, rel=1e-9)
        assert ev("=NORMSDIST(-10)") == approx(7.61985302416047e-24, rel=1e-9)
        assert ev("=NORM.S.DIST(1.333333, TRUE)") == approx(0.908788726, rel=1e-8)

    def test_norm_s_inv_refined(self) -> None:
        assert ev("=NORM.S.INV(0.908789)") == approx(1.3333347, rel=1e-7)
        for p in ("1E-10", "0.3", "0.999999"):
            assert ev(f"=NORM.S.DIST(NORM.S.INV({p}), TRUE)") == approx(float(p), rel=1e-12)

    @pytest.mark.parametrize(
        "formula",
        [
            '=LEFT("x", -1)',
            '=RIGHT("x", -1)',
            '=MID("hello", 0, 2)',
            '=MID("hello", 2, -1)',
            '=FIND("l", "hello", 0)',
            '=FIND("l", "hello", 10)',
            '=SEARCH("l", "hello", 0)',
            '=REPLACE("abc", 0, 1, "x")',
            '=REPT("a", -1)',
        ],
    )
    def test_text_argument_validation(self, formula: str) -> None:
        assert ev(formula) is ExcelError.VALUE

    def test_switch_case_insensitive(self) -> None:
        assert ev('=SWITCH("a", "A", 1, 2)') == 1.0

    @pytest.mark.parametrize(
        ("formula", "expected"),
        [
            ("=TIME(27, 0, 0)", 0.125),
            ("=TIME(25, 0, 0)", 1 / 24),
            ("=TIME(0, 750, 0)", 0.520833333),
            ("=TIME(0, 0, 2000)", 0.023148148),
        ],
    )
    def test_time_wraps(self, formula: str, expected: float) -> None:
        assert ev(formula) == approx(expected)

    def test_time_negative(self) -> None:
        assert ev("=TIME(0, 0, -1)") is ExcelError.NUM


class TestConditionalAggregatesOverErrors:
    """An error in the aggregated range propagates only from a matching row.

    An error in a criteria range fails ordinary criteria, so its row is skipped.
    `SUMIF(data,"<>#N/A")` still propagates a `#DIV/0!`, which matches `<>#N/A`
    (https://exceljet.net/formulas/sum-and-ignore-errors).
    """

    CELLS = {
        "A1": "a",
        "A2": "b",
        "A3": "c",
        "B1": 1,
        "B2": "=1/0",
        "B3": 3,
        "C1": 1,
        "C2": "=NA()",
        "C3": 3,
    }

    @pytest.mark.parametrize(
        ("formula", "expected"),
        [
            ('=SUMIF(A1:A3,"c",B1:B3)', 3.0),
            ('=SUMIF(A1:A3,"<>b",B1:B3)', 4.0),
            ('=SUMIF(A1:A3,"b",B1:B3)', ExcelError.DIV0),
            ('=SUMIF(B1:B3,">0")', 4.0),
            ('=SUMIF(B1:B3,">0",C1:C3)', 4.0),
            ('=SUMIF(B1:B3,"<>#N/A")', ExcelError.DIV0),
            ('=SUMIF(C1:C3,"<>#N/A")', 4.0),
            ('=SUMIFS(B1:B3,A1:A3,"<>b")', 4.0),
            ('=SUMIFS(B1:B3,A1:A3,"b")', ExcelError.DIV0),
            ('=SUMIFS(C1:C3,B1:B3,">0",A1:A3,"<>a")', 3.0),
            ('=AVERAGEIF(A1:A3,"<>b",C1:C3)', 2.0),
            ('=AVERAGEIF(A1:A3,"b",C1:C3)', ExcelError.NA),
            ('=AVERAGEIF(C1:C3,">0")', 2.0),
            ('=AVERAGEIFS(C1:C3,A1:A3,"<>b")', 2.0),
            ('=AVERAGEIFS(C1:C3,A1:A3,"b")', ExcelError.NA),
            ('=MAXIFS(B1:B3,A1:A3,"<>b")', 3.0),
            ('=MAXIFS(B1:B3,A1:A3,"b")', ExcelError.DIV0),
            ('=MINIFS(C1:C3,A1:A3,"<>b")', 1.0),
            ('=MINIFS(C1:C3,A1:A3,"b")', ExcelError.NA),
            ('=COUNTIF(B1:B3,">0")', 2.0),
            ('=COUNTIFS(B1:B3,">0",A1:A3,"<>a")', 1.0),
        ],
    )
    def test_formula(self, formula: str, expected: Any) -> None:
        assert ev(formula, self.CELLS) == expected
