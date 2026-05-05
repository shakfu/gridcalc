"""Tests for formula libs (xlsx compatibility functions)."""

from __future__ import annotations

import math
from pathlib import Path

from gridcalc.engine import Grid, Mode, Vec
from gridcalc.formula.errors import ExcelError
from gridcalc.libs import get_lib_builtins
from gridcalc.libs.xlsx import (
    AND,
    AVERAGE,
    AVERAGEIF,
    CONCAT,
    CONCATENATE,
    COUNTIF,
    EXACT,
    IF,
    IFERROR,
    INDEX,
    LARGE,
    LEFT,
    LOWER,
    MATCH,
    MEDIAN,
    MID,
    MOD,
    NOT,
    OR,
    POWER,
    PROPER,
    REPT,
    RIGHT,
    ROUND,
    ROUNDDOWN,
    ROUNDUP,
    SIGN,
    SMALL,
    SUBSTITUTE,
    SUMIF,
    SUMPRODUCT,
    TRIM,
    UPPER,
    VLOOKUP,
)

# -- Unit tests for individual functions --


class TestLogical:
    def test_if_true(self) -> None:
        assert IF(True, 10, 20) == 10

    def test_if_false(self) -> None:
        assert IF(False, 10, 20) == 20

    def test_if_default_false(self) -> None:
        assert IF(False, 10) == 0

    def test_if_numeric_condition(self) -> None:
        assert IF(5 > 3, "yes", "no") == "yes"

    def test_and_all_true(self) -> None:
        assert AND(True, True, True) is True

    def test_and_one_false(self) -> None:
        assert AND(True, False, True) is False

    def test_or_one_true(self) -> None:
        assert OR(False, True, False) is True

    def test_or_all_false(self) -> None:
        assert OR(False, False) is False

    def test_not_true(self) -> None:
        assert NOT(True) is False

    def test_not_false(self) -> None:
        assert NOT(False) is True

    def test_iferror_normal(self) -> None:
        assert IFERROR(42, 0) == 42

    def test_iferror_nan(self) -> None:
        assert IFERROR(float("nan"), -1) == -1

    def test_iferror_inf(self) -> None:
        assert IFERROR(float("inf"), 0) == 0


class TestMathFunctions:
    def test_round(self) -> None:
        assert ROUND(3.14159, 2) == 3.14

    def test_round_default(self) -> None:
        assert ROUND(3.7) == 4

    def test_roundup(self) -> None:
        assert ROUNDUP(2.121, 2) == 2.13

    def test_rounddown(self) -> None:
        assert ROUNDDOWN(2.129, 2) == 2.12

    def test_mod(self) -> None:
        assert MOD(10, 3) == 1

    def test_power(self) -> None:
        assert POWER(2, 10) == 1024

    def test_sign_positive(self) -> None:
        assert SIGN(5) == 1

    def test_sign_negative(self) -> None:
        assert SIGN(-3) == -1

    def test_sign_zero(self) -> None:
        assert SIGN(0) == 0


class TestAggregates:
    def test_average_vec(self) -> None:
        assert AVERAGE(Vec([10, 20, 30])) == 20.0

    def test_average_scalar(self) -> None:
        assert AVERAGE(5.0) == 5.0

    def test_median_odd(self) -> None:
        assert MEDIAN(Vec([3, 1, 2])) == 2.0

    def test_median_even(self) -> None:
        assert MEDIAN(Vec([1, 2, 3, 4])) == 2.5

    def test_sumproduct(self) -> None:
        assert SUMPRODUCT(Vec([1, 2, 3]), Vec([4, 5, 6])) == 32.0

    def test_large(self) -> None:
        assert LARGE(Vec([10, 30, 20, 50, 40]), 2) == 40.0

    def test_small(self) -> None:
        assert SMALL(Vec([10, 30, 20, 50, 40]), 2) == 20.0


class TestConditionalAggregates:
    def test_sumif_gt(self) -> None:
        assert SUMIF(Vec([1, 5, 10, 15, 20]), ">10") == 35.0

    def test_sumif_eq(self) -> None:
        assert SUMIF(Vec([1, 2, 3, 2, 1]), "2") == 4.0

    def test_sumif_with_sum_range(self) -> None:
        assert SUMIF(Vec([1, 2, 3]), ">1", Vec([10, 20, 30])) == 50.0

    def test_countif_gt(self) -> None:
        assert COUNTIF(Vec([1, 5, 10, 15, 20]), ">10") == 2

    def test_countif_eq(self) -> None:
        assert COUNTIF(Vec([1, 2, 3, 2, 1]), "=2") == 2

    def test_countif_ne(self) -> None:
        assert COUNTIF(Vec([1, 2, 3]), "<>2") == 2

    def test_averageif(self) -> None:
        assert AVERAGEIF(Vec([10, 20, 30, 40]), ">15") == 30.0

    def test_averageif_with_range(self) -> None:
        result = AVERAGEIF(Vec([1, 2, 3]), ">1", Vec([100, 200, 300]))
        assert result == 250.0


class TestLookup:
    def test_vlookup_exact(self) -> None:
        # 3 rows x 2 cols: [1,10, 2,20, 3,30]
        table = Vec([1, 10, 2, 20, 3, 30])
        assert VLOOKUP(2, table, 2, 0) == 20.0

    def test_vlookup_approx(self) -> None:
        table = Vec([1, 10, 2, 20, 3, 30])
        assert VLOOKUP(2.5, table, 2, 1) == 20.0

    def test_vlookup_not_found(self) -> None:
        table = Vec([1, 10, 2, 20])
        assert math.isnan(VLOOKUP(5, table, 2, 0))

    def test_index(self) -> None:
        assert INDEX(Vec([10, 20, 30, 40]), 3) == 30.0

    def test_match_exact(self) -> None:
        assert MATCH(20, Vec([10, 20, 30]), 0) == 2

    def test_match_not_found(self) -> None:
        assert MATCH(99, Vec([10, 20, 30]), 0) == 0

    def test_match_approx(self) -> None:
        assert MATCH(25, Vec([10, 20, 30]), 1) == 2


class TestText:
    def test_concatenate(self) -> None:
        assert CONCATENATE("hello", " ", "world") == "hello world"

    def test_concat(self) -> None:
        assert CONCAT("a", "b", "c") == "abc"

    def test_left(self) -> None:
        assert LEFT("hello", 3) == "hel"

    def test_right(self) -> None:
        assert RIGHT("hello", 3) == "llo"

    def test_mid(self) -> None:
        assert MID("hello", 2, 3) == "ell"

    def test_trim(self) -> None:
        assert TRIM("  hello  ") == "hello"

    def test_upper(self) -> None:
        assert UPPER("hello") == "HELLO"

    def test_lower(self) -> None:
        assert LOWER("HELLO") == "hello"

    def test_proper(self) -> None:
        assert PROPER("hello world") == "Hello World"

    def test_substitute(self) -> None:
        assert SUBSTITUTE("abab", "a", "x") == "xbxb"

    def test_substitute_instance(self) -> None:
        assert SUBSTITUTE("abab", "a", "x", 1) == "xbab"

    def test_rept(self) -> None:
        assert REPT("*", 5) == "*****"

    def test_exact_true(self) -> None:
        assert EXACT("hello", "hello") is True

    def test_exact_false(self) -> None:
        assert EXACT("hello", "Hello") is False


# -- Lib registry --


class TestLibRegistry:
    def test_xlsx_lib_exists(self) -> None:
        builtins = get_lib_builtins("xlsx")
        assert "IF" in builtins
        assert "VLOOKUP" in builtins
        assert "CONCATENATE" in builtins

    def test_unknown_lib(self) -> None:
        builtins = get_lib_builtins("nonexistent")
        assert builtins == {}

    def test_builtins_are_copies(self) -> None:
        a = get_lib_builtins("xlsx")
        b = get_lib_builtins("xlsx")
        assert a is not b


# -- Grid integration --


class TestGridXlsxLib:
    def test_load_lib(self) -> None:
        g = Grid()
        g.load_lib("xlsx")
        assert "IF" in g._eval_globals
        assert "VLOOKUP" in g._eval_globals

    def test_if_formula(self) -> None:
        g = Grid()
        g.load_lib("xlsx")
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "=IF(A1>5, A1*2, 0)")
        assert g.cells[1][0].val == 20.0

    def test_if_false_path(self) -> None:
        g = Grid()
        g.load_lib("xlsx")
        g.setcell(0, 0, "3")
        g.setcell(1, 0, "=IF(A1>5, A1*2, 0)")
        assert g.cells[1][0].val == 0.0

    def test_sumif_formula(self) -> None:
        g = Grid()
        g.load_lib("xlsx")
        g.setcell(0, 0, "5")
        g.setcell(0, 1, "10")
        g.setcell(0, 2, "15")
        g.setcell(0, 3, "20")
        g.setcell(1, 0, '=SUMIF(A1:A4, ">10")')
        assert g.cells[1][0].val == 35.0

    def test_countif_formula(self) -> None:
        g = Grid()
        g.load_lib("xlsx")
        g.setcell(0, 0, "5")
        g.setcell(0, 1, "10")
        g.setcell(0, 2, "15")
        g.setcell(1, 0, '=COUNTIF(A1:A3, ">5")')
        assert g.cells[1][0].val == 2.0

    def test_average_formula(self) -> None:
        g = Grid()
        g.load_lib("xlsx")
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.setcell(1, 0, "=AVERAGE(A1:A3)")
        assert g.cells[1][0].val == 20.0

    def test_nested_if_and(self) -> None:
        g = Grid()
        g.load_lib("xlsx")
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(1, 0, "=IF(AND(A1>5, A2>15), A1+A2, 0)")
        assert g.cells[1][0].val == 30.0

    def test_round_formula(self) -> None:
        g = Grid()
        g.load_lib("xlsx")
        g.setcell(0, 0, "3.14159")
        g.setcell(1, 0, "=ROUND(A1, 2)")
        assert g.cells[1][0].val == 3.14

    def test_libs_persist_in_json(self, tmp_path: Path) -> None:
        g = Grid()
        g.libs = ["xlsx"]
        g.load_lib("xlsx")
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "=IF(A1>5, 1, 0)")

        f = tmp_path / "libs.json"
        assert g.jsonsave(str(f)) == 0

        g2 = Grid()
        assert g2.jsonload(str(f)) == 0
        assert g2.libs == ["xlsx"]
        assert g2.cells[1][0].val == 1.0

    def test_no_lib_no_if(self) -> None:
        """Without xlsx lib, IF is not available."""
        g = Grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "=IF(A1>5, 1, 0)")
        assert math.isnan(g.cells[1][0].val)


class TestTextExtras:
    def test_find_case_sensitive(self) -> None:
        from gridcalc.libs.xlsx import FIND

        assert FIND("o", "hello") == 5
        assert FIND("O", "hello").value == "#VALUE!"

    def test_search_case_insensitive(self) -> None:
        from gridcalc.libs.xlsx import SEARCH

        assert SEARCH("O", "hello") == 5
        assert SEARCH("z", "hello").value == "#VALUE!"

    def test_replace(self) -> None:
        from gridcalc.libs.xlsx import REPLACE

        assert REPLACE("abcdef", 2, 3, "X") == "aXef"

    def test_textjoin(self) -> None:
        from gridcalc.libs.xlsx import TEXTJOIN

        assert TEXTJOIN(",", True, "a", "", "b") == "a,b"
        assert TEXTJOIN(",", False, "a", "", "b") == "a,,b"
        assert TEXTJOIN("-", True, Vec([1.0, 2.0, 3.0])) == "1.0-2.0-3.0"

    def test_char_code(self) -> None:
        from gridcalc.libs.xlsx import CHAR, CODE

        assert CHAR(65) == "A"
        assert CODE("A") == 65

    def test_value(self) -> None:
        from gridcalc.libs.xlsx import VALUE

        assert VALUE("3.14") == 3.14
        assert VALUE("1,234.5") == 1234.5
        assert VALUE("abc").value == "#VALUE!"

    def test_text_format(self) -> None:
        from gridcalc.libs.xlsx import TEXT

        assert TEXT(1234.5, "0.00") == "1234.50"
        assert TEXT(0.5, "0.0%") == "50.0%"
        assert TEXT(1234.5, "#,##0.00") == "1,234.50"


class TestDates:
    def test_date_components(self) -> None:
        from gridcalc.libs.xlsx import DATE, DAY, MONTH, YEAR

        s = DATE(2026, 5, 5)
        assert YEAR(s) == 2026
        assert MONTH(s) == 5
        assert DAY(s) == 5

    def test_today_now(self) -> None:
        from gridcalc.libs.xlsx import NOW, TODAY, YEAR

        # We can't pin a specific date but the year should be sensible.
        assert YEAR(TODAY()) >= 2025
        assert NOW() >= TODAY()

    def test_weekday(self) -> None:
        from gridcalc.libs.xlsx import DATE, WEEKDAY

        # 2026-01-04 is a Sunday.
        s = DATE(2026, 1, 4)
        assert WEEKDAY(s, 1) == 1  # Sun=1
        assert WEEKDAY(s, 2) == 7  # Sun=7 (Mon=1 type)
        assert WEEKDAY(s, 3) == 6  # Sun=6 (Mon=0 type)

    def test_edate_eomonth(self) -> None:
        from gridcalc.libs.xlsx import DATE, DAY, EDATE, EOMONTH, MONTH, YEAR

        s = DATE(2026, 1, 31)
        # EDATE +1 month from Jan 31 -> Feb 28 (clamps to last day).
        e = EDATE(s, 1)
        assert (YEAR(e), MONTH(e), DAY(e)) == (2026, 2, 28)
        # EOMONTH +0 -> last day of January.
        m = EOMONTH(DATE(2026, 1, 15), 0)
        assert DAY(m) == 31

    def test_datedif(self) -> None:
        from gridcalc.libs.xlsx import DATE, DATEDIF

        a = DATE(2024, 1, 1)
        b = DATE(2026, 6, 15)
        assert DATEDIF(a, b, "Y") == 2
        assert DATEDIF(a, b, "M") == 29
        assert DATEDIF(a, b, "D") == (b - a)

    def test_networkdays(self) -> None:
        from gridcalc.libs.xlsx import DATE, NETWORKDAYS

        # 2026-05-04 (Mon) to 2026-05-08 (Fri) = 5 weekdays.
        n = NETWORKDAYS(DATE(2026, 5, 4), DATE(2026, 5, 8))
        assert n == 5

    def test_datevalue_timevalue(self) -> None:
        from gridcalc.libs.xlsx import DATEVALUE, TIME, TIMEVALUE, YEAR

        assert YEAR(DATEVALUE("2026-05-05")) == 2026
        # 14:30:00 -> 0.6041666...
        assert abs(TIMEVALUE("14:30:00") - TIME(14, 30, 0)) < 1e-9


class TestInformation:
    def test_isnumber(self) -> None:
        from gridcalc.libs.xlsx import ISNUMBER

        assert ISNUMBER(3.14) is True
        assert ISNUMBER(0) is True
        assert ISNUMBER("3") is False
        assert ISNUMBER(True) is False
        assert ISNUMBER(float("nan")) is False

    def test_istext_isblank(self) -> None:
        from gridcalc.libs.xlsx import ISBLANK, ISTEXT

        assert ISTEXT("hi") is True
        assert ISTEXT(5) is False
        assert ISBLANK(None) is True
        assert ISBLANK("") is True
        assert ISBLANK(0) is False

    def test_iserror_family(self) -> None:
        from gridcalc.libs.xlsx import ISERR, ISERROR, ISNA

        assert ISERROR(ExcelError.DIV0) is True
        assert ISERROR(float("nan")) is True
        assert ISNA(ExcelError.NA) is True
        assert ISNA(ExcelError.DIV0) is False
        assert ISERR(ExcelError.NA) is False
        assert ISERR(ExcelError.DIV0) is True

    def test_islogical_iseven_isodd(self) -> None:
        from gridcalc.libs.xlsx import ISEVEN, ISLOGICAL, ISODD

        assert ISLOGICAL(True) is True
        assert ISLOGICAL(1) is False
        assert ISEVEN(4) is True
        assert ISODD(7) is True

    def test_n_na(self) -> None:
        from gridcalc.libs.xlsx import NA, N

        assert NA() is ExcelError.NA
        assert N(5.5) == 5.5
        assert N(True) == 1.0
        assert N("abc") == 0.0


class TestMultiCriteriaAggregates:
    def test_sumifs(self) -> None:
        from gridcalc.libs.xlsx import SUMIFS

        a = Vec([1.0, 2.0, 3.0, 4.0])
        b = Vec([10.0, 20.0, 30.0, 40.0])
        # Sum a where b > 15.
        assert SUMIFS(a, b, ">15") == 9.0
        # Sum a where b > 15 AND a < 4.
        assert SUMIFS(a, b, ">15", a, "<4") == 5.0

    def test_countifs(self) -> None:
        from gridcalc.libs.xlsx import COUNTIFS

        a = Vec([1.0, 2.0, 3.0, 4.0])
        b = Vec([10.0, 20.0, 30.0, 40.0])
        assert COUNTIFS(b, ">15") == 3
        assert COUNTIFS(b, ">15", a, "<4") == 2

    def test_maxifs_minifs(self) -> None:
        from gridcalc.libs.xlsx import MAXIFS, MINIFS

        a = Vec([1.0, 2.0, 3.0, 4.0])
        b = Vec([10.0, 20.0, 30.0, 40.0])
        assert MAXIFS(a, b, ">15") == 4.0
        assert MINIFS(a, b, ">15") == 2.0

    def test_averageifs_empty(self) -> None:
        from gridcalc.libs.xlsx import AVERAGEIFS

        a = Vec([1.0, 2.0])
        b = Vec([1.0, 1.0])
        # No matches -> #DIV/0!
        assert AVERAGEIFS(a, b, ">100") is ExcelError.DIV0


class TestStatistical:
    def test_stdev_var(self) -> None:
        from gridcalc.libs.xlsx import STDEV, STDEVP, VAR, VARP

        v = Vec([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        assert abs(STDEV(v) - 2.138089935) < 1e-6
        assert abs(VAR(v) - 4.571428571) < 1e-6
        assert abs(STDEVP(v) - 2.0) < 1e-6
        assert abs(VARP(v) - 4.0) < 1e-6

    def test_correl_covar(self) -> None:
        from gridcalc.libs.xlsx import CORREL, COVAR

        x = Vec([1.0, 2.0, 3.0, 4.0])
        y = Vec([2.0, 4.0, 6.0, 8.0])  # perfectly correlated
        assert abs(CORREL(x, y) - 1.0) < 1e-9
        # Population covariance of these two sequences.
        assert abs(COVAR(x, y) - 2.5) < 1e-9

    def test_rank(self) -> None:
        from gridcalc.libs.xlsx import RANK

        v = Vec([10.0, 30.0, 20.0, 40.0])
        assert RANK(40.0, v) == 1  # descending default
        assert RANK(10.0, v, 1) == 1  # ascending

    def test_percentile_quartile(self) -> None:
        from gridcalc.libs.xlsx import PERCENTILE, QUARTILE

        v = Vec([1.0, 2.0, 3.0, 4.0, 5.0])
        assert PERCENTILE(v, 0.5) == 3.0
        assert QUARTILE(v, 2) == 3.0

    def test_mode_geomean(self) -> None:
        from gridcalc.libs.xlsx import GEOMEAN, MODE

        assert MODE(Vec([1.0, 2.0, 2.0, 3.0])) == 2.0
        assert MODE(Vec([1.0, 2.0, 3.0])) is ExcelError.NA
        assert abs(GEOMEAN(Vec([1.0, 4.0])) - 2.0) < 1e-9


class TestFinancial:
    def test_pmt_round_trip(self) -> None:
        from gridcalc.libs.xlsx import FV, PMT, PV

        # 5% annual rate, 30-year mortgage of 200k.
        rate = 0.05 / 12
        nper = 30 * 12
        pv = 200000
        pmt = PMT(rate, nper, pv)
        # Should be ~-1073.64
        assert abs(pmt - -1073.6435) < 0.01
        # PV with that PMT recovers the original loan amount.
        assert abs(PV(rate, nper, pmt) - pv) < 0.01
        # FV at end of schedule should be ~ 0 (loan paid off).
        assert abs(FV(rate, nper, pmt, pv)) < 0.01

    def test_npv(self) -> None:
        from gridcalc.libs.xlsx import NPV

        # Standard textbook: 10% rate, cashflows [-1000, 200, 300, 400, 500].
        result = NPV(0.10, -1000, 200, 300, 400, 500)
        # NPV from time 0 (note: Excel NPV treats first arg as period 1).
        assert abs(result - 65.2591) < 0.01

    def test_irr(self) -> None:
        from gridcalc.libs.xlsx import IRR

        flows = Vec([-1000.0, 300.0, 400.0, 500.0])
        rate = IRR(flows)
        # Verify rate makes NPV ~ 0.
        npv = sum(cf / (1 + rate) ** i for i, cf in enumerate(flows.data))
        assert abs(npv) < 1e-6


class TestMathExtras:
    def test_ceiling_floor_mround(self) -> None:
        from gridcalc.libs.xlsx import CEILING, FLOOR, MROUND

        assert CEILING(2.3, 1) == 3.0
        assert CEILING(2.3, 0.5) == 2.5
        assert FLOOR(2.7, 1) == 2.0
        assert FLOOR(2.7, 0.5) == 2.5
        assert MROUND(10, 3) == 9
        assert MROUND(11, 3) == 12

    def test_odd_even(self) -> None:
        from gridcalc.libs.xlsx import EVEN, ODD

        assert ODD(3) == 3
        assert ODD(2.5) == 3
        assert ODD(-3.5) == -5
        assert EVEN(3) == 4
        assert EVEN(2) == 2

    def test_fact_gcd_lcm(self) -> None:
        from gridcalc.libs.xlsx import FACT, GCD, LCM

        assert FACT(5) == 120
        assert FACT(-1) is ExcelError.NUM
        assert GCD(12, 8, 4) == 4
        assert LCM(4, 6) == 12

    def test_trunc(self) -> None:
        from gridcalc.libs.xlsx import TRUNC

        assert TRUNC(3.789, 1) == 3.7
        assert TRUNC(-3.789, 1) == -3.7
        assert TRUNC(3.789) == 3


class TestLogicalExtras:
    def test_ifs(self) -> None:
        from gridcalc.libs.xlsx import IFS

        assert IFS(False, "a", True, "b", False, "c") == "b"
        assert IFS(False, "a", False, "b") is ExcelError.NA

    def test_switch(self) -> None:
        from gridcalc.libs.xlsx import SWITCH

        assert SWITCH(2, 1, "one", 2, "two", 3, "three") == "two"
        assert SWITCH(99, 1, "one", "default") == "default"
        assert SWITCH(99, 1, "one") is ExcelError.NA

    def test_ifna_xor(self) -> None:
        from gridcalc.libs.xlsx import IFNA, XOR

        assert IFNA(ExcelError.NA, "fallback") == "fallback"
        assert IFNA(5, "fallback") == 5
        assert XOR(True, False, False) is True
        assert XOR(True, True, False) is False


class TestChoose:
    def test_choose(self) -> None:
        from gridcalc.libs.xlsx import CHOOSE

        assert CHOOSE(2, "a", "b", "c") == "b"
        assert CHOOSE(99, "a", "b").value == "#VALUE!"


class TestRowColumnFunctions:
    """ROW/COLUMN/ROWS/COLUMNS go through the raw-args path: they receive
    AST CellRef/RangeRef nodes plus the Env, not evaluated values."""

    def _excel_grid(self) -> Grid:
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        return g

    def test_row_no_args(self) -> None:
        g = self._excel_grid()
        g.setcell(0, 0, "=ROW()")
        g.setcell(0, 4, "=ROW()")
        assert g.cells[0][0].val == 1.0  # A1 -> row 1
        assert g.cells[0][4].val == 5.0  # A5 -> row 5

    def test_row_with_ref(self) -> None:
        g = self._excel_grid()
        g.setcell(0, 0, "=ROW(D17)")
        assert g.cells[0][0].val == 17.0

    def test_column_no_args(self) -> None:
        g = self._excel_grid()
        g.setcell(2, 3, "=COLUMN()")
        assert g.cells[2][3].val == 3.0  # C -> 3

    def test_column_with_ref(self) -> None:
        g = self._excel_grid()
        g.setcell(0, 0, "=COLUMN(E1)")
        assert g.cells[0][0].val == 5.0

    def test_rows(self) -> None:
        g = self._excel_grid()
        g.setcell(0, 0, "=ROWS(A1:B10)")
        g.setcell(0, 1, "=ROWS(A1)")
        assert g.cells[0][0].val == 10.0
        assert g.cells[0][1].val == 1.0

    def test_columns(self) -> None:
        g = self._excel_grid()
        g.setcell(0, 0, "=COLUMNS(A1:E3)")
        g.setcell(0, 1, "=COLUMNS(A1)")
        assert g.cells[0][0].val == 5.0
        assert g.cells[0][1].val == 1.0

    def test_address_only_no_dep_pollution(self) -> None:
        """ROWS(A1:B10) at (0,5) must not register A1..B10 as deps,
        which would create a self-cycle since (0,5) is in the range."""
        g = self._excel_grid()
        g._use_topo_recalc = True
        g.setcell(0, 5, "=ROWS(A1:B10)")
        assert g.cells[0][5].val == 10.0
        assert (0, 5) not in g._circular
        # No cell in A1:B10 should subscribe to (0,5).
        for c in range(2):
            for r in range(10):
                assert (0, 5) not in g._subscribers.get((c, r), set())

    def test_row_combined_with_arithmetic(self) -> None:
        g = self._excel_grid()
        g.setcell(0, 0, "=ROW()*10")
        g.setcell(0, 9, "=ROW()*10")
        assert g.cells[0][0].val == 10.0
        assert g.cells[0][9].val == 100.0
