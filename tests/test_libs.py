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
        assert VLOOKUP(5, table, 2, 0) is ExcelError.NA

    def test_index(self) -> None:
        assert INDEX(Vec([10, 20, 30, 40]), 3) == 30.0

    def test_match_exact(self) -> None:
        assert MATCH(20, Vec([10, 20, 30]), 0) == 2

    def test_match_not_found(self) -> None:
        assert MATCH(99, Vec([10, 20, 30]), 0) is ExcelError.NA

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


class TestTier3Aggregates:
    def test_counta_countblank(self) -> None:
        from gridcalc.libs.xlsx import COUNTA, COUNTBLANK

        assert COUNTA(Vec([1.0, 2.0, 3.0])) == 3
        assert COUNTA(1, "x", None, "", 5) == 3
        assert COUNTBLANK(1, None, "", "x") == 2

    def test_product(self) -> None:
        from gridcalc.libs.xlsx import PRODUCT

        assert PRODUCT(Vec([2.0, 3.0, 4.0])) == 24.0
        assert PRODUCT(2, 3, 4) == 24.0

    def test_averagea_maxa_mina(self) -> None:
        from gridcalc.libs.xlsx import AVERAGEA, MAXA, MINA

        # text counts as 0
        assert AVERAGEA(2, "abc", 4) == 2.0  # (2+0+4)/3
        assert MAXA(2, "abc", 4) == 4.0
        assert MINA(2, "abc", 4) == 0.0
        # bool: TRUE=1
        assert MAXA(0, True) == 1.0


class TestTier3StatsAliases:
    """Stats modern dot-name aliases must be reachable through the
    parser/lexer path; this also verifies BUILTINS lookup is case-insensitive."""

    def _grid(self) -> Grid:
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        return g

    def test_stdev_dotted(self) -> None:
        g = self._grid()
        for i, v in enumerate([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]):
            g.setcell(0, i, str(v))
        g.setcell(1, 0, "=STDEV.S(A1:A8)")
        g.setcell(1, 1, "=STDEV.P(A1:A8)")
        assert abs(g.cells[1][0].val - 2.138089935) < 1e-6
        assert abs(g.cells[1][1].val - 2.0) < 1e-6

    def test_var_dotted(self) -> None:
        g = self._grid()
        for i, v in enumerate([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]):
            g.setcell(0, i, str(v))
        g.setcell(1, 0, "=VAR.S(A1:A8)")
        g.setcell(1, 1, "=VAR.P(A1:A8)")
        assert abs(g.cells[1][0].val - 4.571428571) < 1e-6
        assert abs(g.cells[1][1].val - 4.0) < 1e-6

    def test_percentile_quartile_dotted(self) -> None:
        g = self._grid()
        for i, v in enumerate([1.0, 2.0, 3.0, 4.0, 5.0]):
            g.setcell(0, i, str(v))
        g.setcell(1, 0, "=PERCENTILE.INC(A1:A5, 0.5)")
        g.setcell(1, 1, "=QUARTILE.INC(A1:A5, 2)")
        assert g.cells[1][0].val == 3.0
        assert g.cells[1][1].val == 3.0

    def test_rank_eq_avg(self) -> None:
        from gridcalc.libs.xlsx import RANK_AVG

        v = Vec([10.0, 20.0, 20.0, 30.0])
        # RANK.AVG of 20 (descending default): positions 2 and 3 -> 2.5
        assert RANK_AVG(20.0, v) == 2.5

    def test_mode_mult(self) -> None:
        from gridcalc.libs.xlsx import MODE_MULT

        result = MODE_MULT(Vec([1.0, 2.0, 2.0, 3.0, 3.0, 4.0]))
        assert isinstance(result, Vec)
        assert sorted(result.data) == [2.0, 3.0]

    def test_covariance_p_s(self) -> None:
        from gridcalc.libs.xlsx import COVARIANCE_P, COVARIANCE_S

        x = Vec([1.0, 2.0, 3.0, 4.0])
        y = Vec([2.0, 4.0, 6.0, 8.0])
        # population covariance = 2.5 (matches existing COVAR test)
        assert abs(COVARIANCE_P(x, y) - 2.5) < 1e-9
        # sample covariance: divisor n-1=3
        assert abs(COVARIANCE_S(x, y) - 10.0 / 3) < 1e-9


class TestTier3StatsAdditional:
    def test_avedev_devsq(self) -> None:
        from gridcalc.libs.xlsx import AVEDEV, DEVSQ

        v = Vec([2.0, 4.0, 6.0])  # mean=4
        assert AVEDEV(v) == (2 + 0 + 2) / 3
        assert DEVSQ(v) == 4 + 0 + 4

    def test_slope_intercept_rsq(self) -> None:
        from gridcalc.libs.xlsx import INTERCEPT, RSQ, SLOPE

        x = Vec([1.0, 2.0, 3.0, 4.0])
        y = Vec([3.0, 5.0, 7.0, 9.0])  # y = 2x + 1
        assert abs(SLOPE(y, x) - 2.0) < 1e-9
        assert abs(INTERCEPT(y, x) - 1.0) < 1e-9
        assert abs(RSQ(y, x) - 1.0) < 1e-9

    def test_steyx(self) -> None:
        from gridcalc.libs.xlsx import STEYX

        x = Vec([1.0, 2.0, 3.0, 4.0])
        y = Vec([3.0, 5.0, 7.0, 9.0])
        # Perfect fit -> standard error 0
        assert abs(STEYX(y, x)) < 1e-9

    def test_skew_kurt(self) -> None:
        from gridcalc.libs.xlsx import KURT, SKEW

        # Symmetric data -> skew ~ 0
        v = Vec([1.0, 2.0, 3.0, 4.0, 5.0])
        s = SKEW(v)
        assert isinstance(s, float) and abs(s) < 1e-9
        # KURT defined for n >= 4
        k = KURT(v)
        assert isinstance(k, float)

    def test_percentrank(self) -> None:
        from gridcalc.libs.xlsx import PERCENTRANK

        v = Vec([1.0, 2.0, 3.0, 4.0, 5.0])
        # 3 is at position index 2 of 5 -> rank 2/(5-1)=0.5
        assert PERCENTRANK(v, 3.0) == 0.5
        assert PERCENTRANK(v, 1.0) == 0.0
        assert PERCENTRANK(v, 5.0) == 1.0


class TestTier3Dates:
    def test_days(self) -> None:
        from gridcalc.libs.xlsx import DATE, DAYS

        assert DAYS(DATE(2026, 1, 11), DATE(2026, 1, 1)) == 10

    def test_days360(self) -> None:
        from gridcalc.libs.xlsx import DATE, DAYS360

        # Whole year on the 30/360 calendar
        assert DAYS360(DATE(2026, 1, 1), DATE(2027, 1, 1)) == 360

    def test_weeknum_isoweeknum(self) -> None:
        from gridcalc.libs.xlsx import DATE, ISOWEEKNUM, WEEKNUM

        # 2026-01-01 is a Thursday
        s = DATE(2026, 1, 1)
        # Default type (1, week starts Sunday) -> week 1
        assert WEEKNUM(s) == 1
        assert ISOWEEKNUM(s) == 1

    def test_yearfrac(self) -> None:
        from gridcalc.libs.xlsx import DATE, YEARFRAC

        # Full year, basis 4 (European 30/360) -> 1.0
        assert abs(YEARFRAC(DATE(2026, 1, 1), DATE(2027, 1, 1), 4) - 1.0) < 1e-9
        # Basis 3 (actual/365): non-leap 2026 -> 365/365 = 1.0
        assert abs(YEARFRAC(DATE(2026, 1, 1), DATE(2027, 1, 1), 3) - 1.0) < 1e-9


class TestTier3Information:
    def test_error_type(self) -> None:
        from gridcalc.libs.xlsx import ERROR_TYPE

        assert ERROR_TYPE(ExcelError.DIV0) == 2
        assert ERROR_TYPE(ExcelError.NA) == 7
        assert ERROR_TYPE(123) is ExcelError.NA

    def test_type(self) -> None:
        from gridcalc.libs.xlsx import TYPE

        assert TYPE(1) == 1
        assert TYPE("x") == 2
        assert TYPE(True) == 4
        assert TYPE(ExcelError.NA) == 16
        assert TYPE(Vec([1.0, 2.0])) == 64

    def test_isnontext(self) -> None:
        from gridcalc.libs.xlsx import ISNONTEXT

        assert ISNONTEXT(1) is True
        assert ISNONTEXT("x") is False

    def test_isref_isformula(self) -> None:
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, "5")  # A1 = number
        g.setcell(0, 1, "=A1+1")  # A2 = formula
        g.setcell(1, 0, "=ISREF(A1)")
        g.setcell(1, 1, "=ISFORMULA(A1)")
        g.setcell(1, 2, "=ISFORMULA(A2)")
        assert g.cells[1][0].val == 1.0  # ISREF(A1) -> True
        assert g.cells[1][1].val == 0.0
        assert g.cells[1][2].val == 1.0


class TestTier3Text:
    def test_clean(self) -> None:
        from gridcalc.libs.xlsx import CLEAN

        assert CLEAN("ab\tcd\n") == "abcd"

    def test_numbervalue(self) -> None:
        from gridcalc.libs.xlsx import NUMBERVALUE

        assert NUMBERVALUE("1,234.5") == 1234.5
        assert NUMBERVALUE("50%") == 0.5
        assert NUMBERVALUE("1.234,56", ",", ".") == 1234.56

    def test_fixed_dollar(self) -> None:
        from gridcalc.libs.xlsx import DOLLAR, FIXED

        assert FIXED(1234.5, 2) == "1,234.50"
        assert FIXED(1234.5, 2, True) == "1234.50"
        assert DOLLAR(1234.5, 2) == "$1,234.50"

    def test_t(self) -> None:
        from gridcalc.libs.xlsx import T

        assert T("hello") == "hello"
        assert T(1.0) == ""

    def test_unichar_unicode(self) -> None:
        from gridcalc.libs.xlsx import UNICHAR, UNICODE

        assert UNICHAR(65) == "A"
        assert UNICODE("A") == 65


class TestTier3Math:
    def test_combin_permut(self) -> None:
        from gridcalc.libs.xlsx import COMBIN, COMBINA, PERMUT, PERMUTATIONA

        assert COMBIN(5, 2) == 10
        assert PERMUT(5, 2) == 20
        assert COMBINA(3, 2) == 6  # C(4,2)
        assert PERMUTATIONA(3, 2) == 9  # 3^2

    def test_multinomial(self) -> None:
        from gridcalc.libs.xlsx import MULTINOMIAL

        # 4! / (2! * 2!) = 6
        assert MULTINOMIAL(2, 2) == 6

    def test_quotient(self) -> None:
        from gridcalc.libs.xlsx import QUOTIENT

        assert QUOTIENT(10, 3) == 3
        assert QUOTIENT(10, 0) is ExcelError.DIV0

    def test_ceiling_floor_math(self) -> None:
        from gridcalc.libs.xlsx import CEILING_MATH, FLOOR_MATH

        assert CEILING_MATH(2.3) == 3.0
        assert CEILING_MATH(-2.3, 1, 0) == -2.0  # toward +inf
        assert CEILING_MATH(-2.3, 1, 1) == -3.0  # away from zero
        assert FLOOR_MATH(2.7) == 2.0
        assert FLOOR_MATH(-2.7, 1, 1) == -2.0  # toward zero

    def test_radians_degrees_uppercase(self) -> None:
        from gridcalc.libs.xlsx import DEGREES, RADIANS

        assert abs(RADIANS(180) - math.pi) < 1e-9
        assert abs(DEGREES(math.pi) - 180.0) < 1e-9


class TestTier3PairedSums:
    def test_sumsq(self) -> None:
        from gridcalc.libs.xlsx import SUMSQ

        assert SUMSQ(Vec([1.0, 2.0, 3.0])) == 14.0
        assert SUMSQ(1, 2, 3) == 14.0

    def test_paired_sums(self) -> None:
        from gridcalc.libs.xlsx import SUMX2MY2, SUMX2PY2, SUMXMY2

        x = Vec([1.0, 2.0, 3.0])
        y = Vec([4.0, 5.0, 6.0])
        assert SUMX2MY2(x, y) == (1 - 16) + (4 - 25) + (9 - 36)
        assert SUMX2PY2(x, y) == (1 + 16) + (4 + 25) + (9 + 36)
        assert SUMXMY2(x, y) == 9 + 9 + 9


class TestTier3Hyperbolic:
    def test_hyperbolic(self) -> None:
        from gridcalc.libs.xlsx import ACOSH, ASINH, ATANH, COSH, SINH, TANH

        assert abs(SINH(0)) < 1e-12
        assert abs(COSH(0) - 1.0) < 1e-12
        assert abs(TANH(0)) < 1e-12
        assert abs(ASINH(0)) < 1e-12
        assert abs(ACOSH(1)) < 1e-12
        assert abs(ATANH(0)) < 1e-12
        assert ACOSH(0.5) is ExcelError.NUM
        assert ATANH(2.0) is ExcelError.NUM


class TestTier3Bitwise:
    def test_bitwise(self) -> None:
        from gridcalc.libs.xlsx import BITAND, BITLSHIFT, BITOR, BITRSHIFT, BITXOR

        assert BITAND(13, 11) == 9
        assert BITOR(13, 11) == 15
        assert BITXOR(13, 11) == 6
        assert BITLSHIFT(1, 4) == 16
        assert BITRSHIFT(16, 4) == 1
        assert BITAND(-1, 1) is ExcelError.NUM


class TestTier3Random:
    def test_rand_in_range(self) -> None:
        from gridcalc.libs.xlsx import RAND, RANDBETWEEN

        for _ in range(20):
            r = RAND()
            assert 0.0 <= r < 1.0
            n = RANDBETWEEN(1, 10)
            assert 1 <= n <= 10

    def test_rand_volatile_marks_cell(self) -> None:
        """RAND-using cells must be added to the volatile set so they
        recompute on every recalc."""
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, "=RAND()")
        # Cell should be flagged as volatile in topo recalc bookkeeping.
        assert (0, 0) in g._volatile


class TestCriteriaAuditFixes:
    def test_numeric_criteria_argument(self) -> None:
        from gridcalc.libs.xlsx import COUNTIF, SUMIF

        # SUMIF/COUNTIF must accept a number directly, not just a string
        rng = Vec([1.0, 2.0, 2.0, 3.0])
        assert COUNTIF(rng, 2) == 2
        assert SUMIF(rng, 2) == 4.0

    def test_text_comparison_criteria(self) -> None:
        from gridcalc.libs.xlsx import _parse_criteria

        # ">m" with a text range should compare strings, not flatten to wildcard
        pred = _parse_criteria(">m")
        assert pred("z") is True
        assert pred("a") is False
        # Numbers don't satisfy a text comparison
        assert pred(5) is False

    def test_wildcard_escape(self) -> None:
        from gridcalc.libs.xlsx import _parse_criteria

        pred = _parse_criteria("a~*b")  # literal "a*b"
        assert pred("a*b") is True
        assert pred("axb") is False

    def test_blank_criteria(self) -> None:
        from gridcalc.libs.xlsx import COUNTIF

        assert COUNTIF(Vec([1.0, None, "", 2.0]), "") == 2  # type: ignore[list-item]


class TestLookupAuditFixes:
    def test_index_2d_via_range(self) -> None:
        """INDEX must use the row,col arguments correctly with a 2D range."""
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        # 3x3 block of values
        for r in range(3):
            for c in range(3):
                g.setcell(c, r, str(r * 10 + c + 1))
        # B2 = INDEX(A1:C3, 2, 3) -> row 2 col 3 -> value 13
        g.setcell(4, 0, "=INDEX(A1:C3, 2, 3)")
        assert g.cells[4][0].val == 13.0
        # Whole row: INDEX(A1:C3, 1, 0) -> Vec of row 1
        g.setcell(4, 1, "=SUM(INDEX(A1:C3, 1, 0))")
        assert g.cells[4][1].val == 1 + 2 + 3
        # Whole column: INDEX(A1:C3, 0, 2) -> Vec of col 2
        g.setcell(4, 2, "=SUM(INDEX(A1:C3, 0, 2))")
        assert g.cells[4][2].val == 2 + 12 + 22

    def test_match_returns_na(self) -> None:
        from gridcalc.libs.xlsx import MATCH

        assert MATCH(99, Vec([10, 20, 30]), 0) is ExcelError.NA

    def test_match_text_wildcard(self) -> None:
        rng = Vec(["alpha", "beta", "gamma"])
        assert MATCH("be*", rng, 0) == 2
        assert MATCH("?amma", rng, 0) == 3
        # Tilde escape: literal "*" in pattern.
        assert MATCH("a~*", Vec(["a*", "ab"]), 0) == 1


class TestAddress:
    def test_address_styles(self) -> None:
        from gridcalc.libs.xlsx import ADDRESS

        assert ADDRESS(1, 1) == "$A$1"
        assert ADDRESS(2, 3, 4) == "C2"
        assert ADDRESS(2, 3, 2) == "C$2"
        assert ADDRESS(2, 3, 3) == "$C2"
        # R1C1
        assert ADDRESS(2, 3, 1, False) == "R2C3"
        assert ADDRESS(2, 3, 4, False) == "R[2]C[3]"
        # With sheet
        assert ADDRESS(1, 1, 1, True, "Sheet1") == "Sheet1!$A$1"

    def test_address_multichar_column(self) -> None:
        from gridcalc.libs.xlsx import ADDRESS

        assert ADDRESS(1, 27, 4) == "AA1"
        assert ADDRESS(1, 702, 4) == "ZZ1"


class TestXLookupXMatch:
    def test_xlookup_exact(self) -> None:
        from gridcalc.libs.xlsx import XLOOKUP

        keys = Vec([10.0, 20.0, 30.0])
        vals = Vec([100.0, 200.0, 300.0])
        assert XLOOKUP(20, keys, vals) == 200.0
        # not found
        assert XLOOKUP(99, keys, vals) is ExcelError.NA
        # if_not_found fallback
        assert XLOOKUP(99, keys, vals, "missing") == "missing"

    def test_xlookup_next_smaller_larger(self) -> None:
        from gridcalc.libs.xlsx import XLOOKUP

        keys = Vec([10.0, 20.0, 30.0])
        vals = Vec([100.0, 200.0, 300.0])
        # next-smaller
        assert XLOOKUP(25, keys, vals, None, -1) == 200.0
        # next-larger
        assert XLOOKUP(25, keys, vals, None, 1) == 300.0

    def test_xlookup_reverse_search(self) -> None:
        from gridcalc.libs.xlsx import XLOOKUP

        keys = Vec([1.0, 2.0, 1.0])
        vals = Vec([10.0, 20.0, 30.0])
        # Last-to-first finds the trailing 1 first.
        assert XLOOKUP(1, keys, vals, None, 0, -1) == 30.0
        assert XLOOKUP(1, keys, vals) == 10.0

    def test_xlookup_wildcard(self) -> None:
        from gridcalc.libs.xlsx import XLOOKUP

        keys = Vec(["alpha", "beta", "gamma"])  # type: ignore[list-item]
        vals = Vec([1.0, 2.0, 3.0])
        assert XLOOKUP("be*", keys, vals, None, 2) == 2.0

    def test_xmatch(self) -> None:
        from gridcalc.libs.xlsx import XMATCH

        keys = Vec([10.0, 20.0, 30.0])
        assert XMATCH(20, keys) == 2
        assert XMATCH(99, keys) is ExcelError.NA
        assert XMATCH(25, keys, -1) == 2
        assert XMATCH(25, keys, 1) == 3


class TestArrayFunctions:
    def test_filter(self) -> None:
        from gridcalc.libs.xlsx import FILTER

        rng = Vec([10.0, 20.0, 30.0, 40.0])
        include = Vec([1.0, 0.0, 1.0, 0.0])
        out = FILTER(rng, include)
        assert isinstance(out, Vec)
        assert out.data == [10.0, 30.0]
        # Empty -> if_empty fallback
        assert FILTER(rng, Vec([0.0, 0.0, 0.0, 0.0]), "none") == "none"
        assert FILTER(rng, Vec([0.0, 0.0, 0.0, 0.0])) is ExcelError.NA

    def test_sort(self) -> None:
        from gridcalc.libs.xlsx import SORT

        v = Vec([3.0, 1.0, 2.0])
        assert SORT(v).data == [1.0, 2.0, 3.0]
        assert SORT(v, 1, -1).data == [3.0, 2.0, 1.0]

    def test_unique(self) -> None:
        from gridcalc.libs.xlsx import UNIQUE

        v = Vec([1.0, 2.0, 2.0, 3.0, 1.0, 4.0])
        assert UNIQUE(v).data == [1.0, 2.0, 3.0, 4.0]
        # exactly_once
        assert UNIQUE(v, False, True).data == [3.0, 4.0]

    def test_sequence(self) -> None:
        from gridcalc.libs.xlsx import SEQUENCE

        s = SEQUENCE(3)
        assert s.data == [1.0, 2.0, 3.0]
        s2 = SEQUENCE(2, 3, 10, 5)
        assert s2.data == [10.0, 15.0, 20.0, 25.0, 30.0, 35.0]
        assert s2.cols == 3

    def test_sequence_into_index(self) -> None:
        """SEQUENCE preserves cols so INDEX can address it as 2D."""
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        # 2x3 sequence: 1 2 3 / 4 5 6, INDEX row 2 col 3 -> 6
        g.setcell(0, 0, "=INDEX(SEQUENCE(2, 3), 2, 3)")
        assert g.cells[0][0].val == 6.0

    def test_randarray_volatile(self) -> None:
        from gridcalc.libs.xlsx import RANDARRAY

        v = RANDARRAY(2, 3, 0, 1, False)
        assert isinstance(v, Vec)
        assert len(v.data) == 6
        assert v.cols == 3
        assert all(0.0 <= x <= 1.0 for x in v.data)
        # Volatility wired through deps
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, "=SUM(RANDARRAY(3))")
        assert (0, 0) in g._volatile

    def test_filter_in_pipeline(self) -> None:
        """FILTER result feeds SUM, exercising Vec consumption."""
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        for i, v in enumerate([10.0, 20.0, 30.0, 40.0]):
            g.setcell(0, i, str(v))
        for i, v in enumerate([1.0, 0.0, 1.0, 0.0]):
            g.setcell(1, i, str(v))
        g.setcell(2, 0, "=SUM(FILTER(A1:A4, B1:B4))")
        assert g.cells[2][0].val == 40.0


class TestRangeTextBool:
    """Text and bools must survive range materialization, so functions
    operating on real Grid ranges (MATCH/VLOOKUP/COUNTIF/SUMIF/...) see
    the original cell values, not text-flattened-to-0."""

    def _g(self) -> Grid:
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        return g

    def test_match_text_via_grid_range(self) -> None:
        g = self._g()
        for i, v in enumerate(["alpha", "beta", "gamma"]):
            g.setcell(0, i, v)
        g.setcell(1, 0, '=MATCH("be*", A1:A3, 0)')
        assert g.cells[1][0].val == 2.0

    def test_vlookup_text_key_via_grid_range(self) -> None:
        g = self._g()
        for i, key in enumerate(["alpha", "beta", "gamma"]):
            g.setcell(0, i, key)
            g.setcell(1, i, str((i + 1) * 10))
        g.setcell(2, 0, '=VLOOKUP("beta", A1:B3, 2, 0)')
        assert g.cells[2][0].val == 20.0

    def test_countif_text_via_grid_range(self) -> None:
        g = self._g()
        for i, v in enumerate(["red", "blue", "red", "green"]):
            g.setcell(0, i, v)
        g.setcell(1, 0, '=COUNTIF(A1:A4, "red")')
        assert g.cells[1][0].val == 2.0

    def test_sumif_text_criteria_numeric_sum(self) -> None:
        g = self._g()
        for i, v in enumerate(["a", "b", "a", "b"]):
            g.setcell(0, i, v)
        for i, v in enumerate([1, 2, 3, 4]):
            g.setcell(1, i, str(v))
        g.setcell(2, 0, '=SUMIF(A1:A4, "a", B1:B4)')
        assert g.cells[2][0].val == 4.0

    def test_sum_skips_text_in_mixed_range(self) -> None:
        g = self._g()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "hello")
        g.setcell(0, 2, "20")
        g.setcell(1, 0, "=SUM(A1:A3)")
        assert g.cells[1][0].val == 30.0

    def test_average_skips_text_in_mixed_range(self) -> None:
        g = self._g()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "hello")
        g.setcell(0, 2, "20")
        g.setcell(1, 0, "=AVERAGE(A1:A3)")
        assert g.cells[1][0].val == 15.0

    def test_count_only_numerics(self) -> None:
        g = self._g()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "hello")
        g.setcell(0, 2, "20")
        g.setcell(1, 0, "=COUNT(A1:A3)")
        assert g.cells[1][0].val == 2.0

    def test_empty_cell_still_zero_in_sum(self) -> None:
        g = self._g()
        g.setcell(0, 0, "5")
        # A2 stays empty
        g.setcell(0, 2, "7")
        g.setcell(1, 0, "=SUM(A1:A3)")
        assert g.cells[1][0].val == 12.0

    def test_vec_arithmetic_text_yields_value_error(self) -> None:
        """=SUM(A1:A3+1) with text in A2: per-element #VALUE!. SUM then
        propagates because first_error sees the ExcelError in the Vec."""
        g = self._g()
        g.setcell(0, 0, "1")
        g.setcell(0, 1, "hello")
        g.setcell(0, 2, "3")
        # Direct check: build Vec via range and add 1 -> middle slot is #VALUE!.
        v = Vec([1.0, "hello", 3.0]) + 1
        assert v.data[0] == 2.0
        assert v.data[1] is ExcelError.VALUE
        assert v.data[2] == 4.0

    def test_abs_per_element_value_error_for_text(self) -> None:
        from gridcalc.engine import ABS as ENGINE_ABS

        v = ENGINE_ABS(Vec([-1.0, "x", 2.0]))
        assert isinstance(v, Vec)
        assert v.data[0] == 1.0
        assert v.data[1] is ExcelError.VALUE
        assert v.data[2] == 2.0


class TestStatDistributions:
    """Reference values cross-checked against Excel."""

    def test_norm_s_dist(self) -> None:
        from gridcalc.libs.xlsx import NORM_S_DIST

        assert NORM_S_DIST(0, True) == 0.5
        assert math.isclose(NORM_S_DIST(1.96, True), 0.9750021048517796, rel_tol=1e-12)
        # PDF at 0 = 1/sqrt(2*pi)
        assert math.isclose(NORM_S_DIST(0, False), 1 / math.sqrt(2 * math.pi), rel_tol=1e-15)

    def test_norm_s_inv_inverse_of_dist(self) -> None:
        from gridcalc.libs.xlsx import NORM_S_DIST, NORM_S_INV

        for p in (0.001, 0.025, 0.5, 0.975, 0.999):
            z = NORM_S_INV(p)
            assert isinstance(z, float)
            assert math.isclose(NORM_S_DIST(z, True), p, abs_tol=1e-9)

    def test_norm_s_inv_matches_excel(self) -> None:
        from gridcalc.libs.xlsx import NORM_S_INV

        # Excel NORM.S.INV(0.975) = 1.95996398454005
        assert math.isclose(NORM_S_INV(0.975), 1.959963984540054, abs_tol=1e-6)

    def test_norm_dist(self) -> None:
        from gridcalc.libs.xlsx import NORM_DIST

        assert math.isclose(NORM_DIST(0, 0, 1, False), 0.3989422804014327, rel_tol=1e-12)
        assert math.isclose(NORM_DIST(1, 0, 1, True), 0.8413447460685429, rel_tol=1e-12)
        # CDF at the mean is always 0.5.
        assert NORM_DIST(10, 10, 2, True) == 0.5

    def test_norm_dist_invalid_sd(self) -> None:
        from gridcalc.libs.xlsx import NORM_DIST

        assert NORM_DIST(0, 0, 0, True) is ExcelError.NUM
        assert NORM_DIST(0, 0, -1, True) is ExcelError.NUM

    def test_norm_inv(self) -> None:
        from gridcalc.libs.xlsx import NORM_INV

        assert NORM_INV(0.5, 10, 2) == 10.0
        # Excel NORM.INV(0.975, 0, 1) ≈ 1.95996
        assert math.isclose(NORM_INV(0.975, 0, 1), 1.959963984540054, abs_tol=1e-6)
        assert NORM_INV(0, 0, 1) is ExcelError.NUM
        assert NORM_INV(1, 0, 1) is ExcelError.NUM

    def test_t_dist(self) -> None:
        from gridcalc.libs.xlsx import T_DIST, T_DIST_2T, T_DIST_RT

        assert math.isclose(T_DIST(0, 10, True), 0.5, abs_tol=1e-12)
        assert math.isclose(T_DIST(2, 10, True), 0.9633059826146312, abs_tol=1e-9)
        assert math.isclose(T_DIST_2T(2, 10), 0.07338803477073763, abs_tol=1e-9)
        assert math.isclose(T_DIST_RT(2, 10), 0.036694017385368816, abs_tol=1e-9)
        # PDF: f_T(0; v) = gamma((v+1)/2) / (sqrt(v*pi)*gamma(v/2))
        v = 10
        expected_pdf = math.exp(
            math.lgamma((v + 1) / 2) - 0.5 * math.log(v * math.pi) - math.lgamma(v / 2)
        )
        assert math.isclose(T_DIST(0, v, False), expected_pdf, rel_tol=1e-12)

    def test_t_inv_round_trip(self) -> None:
        from gridcalc.libs.xlsx import T_DIST, T_INV, T_INV_2T

        for p in (0.025, 0.5, 0.95, 0.975):
            x = T_INV(p, 10)
            assert isinstance(x, float)
            assert math.isclose(T_DIST(x, 10, True), p, abs_tol=1e-9)
        # Two-tailed: T.INV.2T(0.05, 10) ≈ 2.22814
        assert math.isclose(T_INV_2T(0.05, 10), 2.2281388519784784, abs_tol=1e-6)

    def test_t_dist_invalid(self) -> None:
        from gridcalc.libs.xlsx import T_DIST, T_DIST_2T, T_INV

        assert T_DIST(0, 0, True) is ExcelError.NUM
        assert T_DIST_2T(-1, 10) is ExcelError.NUM
        assert T_INV(0, 10) is ExcelError.NUM

    def test_binom_dist(self) -> None:
        from gridcalc.libs.xlsx import BINOM_DIST

        assert math.isclose(BINOM_DIST(2, 5, 0.5, False), 0.3125, rel_tol=1e-12)
        assert math.isclose(BINOM_DIST(2, 5, 0.5, True), 0.5, rel_tol=1e-12)
        # Sum over support = 1.
        total = sum(BINOM_DIST(k, 10, 0.3, False) for k in range(11))  # type: ignore[misc]
        assert math.isclose(total, 1.0, abs_tol=1e-12)

    def test_binom_dist_invalid(self) -> None:
        from gridcalc.libs.xlsx import BINOM_DIST

        assert BINOM_DIST(-1, 5, 0.5, False) is ExcelError.NUM
        assert BINOM_DIST(6, 5, 0.5, False) is ExcelError.NUM
        assert BINOM_DIST(0, 5, 1.5, False) is ExcelError.NUM

    def test_poisson_dist(self) -> None:
        from gridcalc.libs.xlsx import POISSON_DIST

        # Excel POISSON.DIST(3, 2, FALSE) = 0.18044704431548...
        assert math.isclose(POISSON_DIST(3, 2, False), 0.18044704431548356, rel_tol=1e-12)
        assert math.isclose(POISSON_DIST(3, 2, True), 0.8571234604985472, rel_tol=1e-12)

    def test_poisson_dist_invalid(self) -> None:
        from gridcalc.libs.xlsx import POISSON_DIST

        assert POISSON_DIST(-1, 2, False) is ExcelError.NUM
        assert POISSON_DIST(3, -1, False) is ExcelError.NUM

    def test_expon_dist(self) -> None:
        from gridcalc.libs.xlsx import EXPON_DIST

        # PDF at x=1, lambda=2: 2*e^-2
        assert math.isclose(EXPON_DIST(1, 2, False), 2 * math.exp(-2), rel_tol=1e-15)
        # CDF at x=1, lambda=2: 1 - e^-2
        assert math.isclose(EXPON_DIST(1, 2, True), 1 - math.exp(-2), rel_tol=1e-15)
        assert EXPON_DIST(-1, 2, True) is ExcelError.NUM
        assert EXPON_DIST(1, 0, True) is ExcelError.NUM

    def test_confidence_norm(self) -> None:
        from gridcalc.libs.xlsx import CONFIDENCE_NORM, NORM_S_INV

        # Excel CONFIDENCE.NORM(0.05, 2.5, 50) ≈ 0.6929519
        assert math.isclose(CONFIDENCE_NORM(0.05, 2.5, 50), 0.6929519127335031, abs_tol=1e-6)
        # Definition: NORM.S.INV(1 - alpha/2) * sd / sqrt(n)
        result = CONFIDENCE_NORM(0.10, 1.0, 25)
        assert isinstance(result, float)
        assert math.isclose(result, NORM_S_INV(0.95) * 1.0 / 5.0, rel_tol=1e-12)
        assert CONFIDENCE_NORM(0, 1, 10) is ExcelError.NUM

    def test_via_grid_excel_mode(self) -> None:
        """Round-trip through formula evaluation: NORM.DIST and friends
        must be callable as EXCEL-mode formulas (dotted names)."""
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, "=NORM.S.DIST(0, TRUE)")
        g.setcell(0, 1, "=BINOM.DIST(2, 5, 0.5, FALSE)")
        g.setcell(0, 2, "=POISSON.DIST(3, 2, FALSE)")
        g.setcell(0, 3, "=EXPON.DIST(1, 2, TRUE)")
        assert g.cells[0][0].val == 0.5
        assert math.isclose(g.cells[0][1].val, 0.3125, rel_tol=1e-12)
        assert math.isclose(g.cells[0][2].val, 0.18044704431548356, rel_tol=1e-12)
        assert math.isclose(g.cells[0][3].val, 1 - math.exp(-2), rel_tol=1e-12)

    def test_legacy_aliases(self) -> None:
        """Pre-2010 aliases: NORMSDIST, BINOMDIST, POISSON, etc."""
        from gridcalc.libs.xlsx import BUILTINS

        assert math.isclose(BUILTINS["NORMSDIST"](0), 0.5, abs_tol=1e-15)
        assert math.isclose(BUILTINS["NORMSINV"](0.975), 1.959963984540054, abs_tol=1e-6)
        # Legacy TDIST(x, df, tails): tails=1 right-tail, tails=2 two-tailed.
        assert math.isclose(BUILTINS["TDIST"](2, 10, 1), 0.036694017385368816, abs_tol=1e-9)
        assert math.isclose(BUILTINS["TDIST"](2, 10, 2), 0.07338803477073763, abs_tol=1e-9)
        # Legacy TINV is two-tailed inverse.
        assert math.isclose(BUILTINS["TINV"](0.05, 10), 2.2281388519784784, abs_tol=1e-6)
        assert math.isclose(BUILTINS["BINOMDIST"](2, 5, 0.5, False), 0.3125, rel_tol=1e-12)
        assert math.isclose(BUILTINS["POISSON"](3, 2, False), 0.18044704431548356, rel_tol=1e-12)
        assert math.isclose(BUILTINS["EXPONDIST"](1, 2, False), 2 * math.exp(-2), rel_tol=1e-15)


class TestFinancialTier4:
    """Reference values cross-checked against Excel."""

    def test_sln(self) -> None:
        from gridcalc.libs.xlsx import SLN

        assert SLN(10000, 1000, 5) == 1800.0
        assert SLN(0, 0, 5) == 0.0
        assert SLN(10000, 1000, 0) is ExcelError.NUM

    def test_syd(self) -> None:
        from gridcalc.libs.xlsx import SYD

        assert SYD(10000, 1000, 5, 1) == 3000.0
        assert SYD(10000, 1000, 5, 5) == 600.0
        # Sum over the life equals total depreciable amount.
        total = sum(SYD(10000, 1000, 5, p) for p in range(1, 6))  # type: ignore[misc]
        assert math.isclose(total, 9000.0, rel_tol=1e-12)
        assert SYD(10000, 1000, 5, 6) is ExcelError.NUM
        assert SYD(10000, 1000, 0, 1) is ExcelError.NUM

    def test_db(self) -> None:
        from gridcalc.libs.xlsx import DB

        # Excel: =DB(1000000, 100000, 6, 1, 7) -> 186083.33
        assert math.isclose(DB(1_000_000, 100_000, 6, 1, 7), 186083.3333333333, rel_tol=1e-9)
        # Sum across periods approximates (cost - salvage); not exact
        # because Excel rounds the depreciation rate to 3 decimals.
        total = sum(DB(1_000_000, 100_000, 6, p, 7) for p in range(1, 8))  # type: ignore[misc]
        assert math.isclose(total, 900_000.0, rel_tol=0.01)
        assert DB(1_000_000, 100_000, 6, 0, 7) is ExcelError.NUM
        assert DB(1_000_000, 100_000, 6, 1, 0) is ExcelError.NUM

    def test_ddb(self) -> None:
        from gridcalc.libs.xlsx import DDB

        # Classic Excel example: cost 2400, salvage 300, life 10.
        assert math.isclose(DDB(2400, 300, 10, 1), 480.0, rel_tol=1e-12)
        assert math.isclose(DDB(2400, 300, 10, 2), 384.0, rel_tol=1e-12)
        # Custom factor.
        assert math.isclose(DDB(2400, 300, 10, 1, 1.5), 360.0, rel_tol=1e-12)
        # Below-salvage clamp: cumulative depreciation never drops book below salvage.
        cum = sum(DDB(2400, 300, 10, p) for p in range(1, 11))  # type: ignore[misc]
        assert cum <= 2400 - 300 + 1e-9
        assert DDB(2400, 300, 10, 11) is ExcelError.NUM

    def test_vdb_no_switch_matches_summed_ddb(self) -> None:
        from gridcalc.libs.xlsx import DDB, VDB

        # With no_switch=True, VDB(0, k) should equal sum DDB(1..k).
        manual = sum(DDB(2400, 300, 10, p) for p in range(1, 4))  # type: ignore[misc]
        assert math.isclose(VDB(2400, 300, 10, 0, 3, 2.0, True), manual, rel_tol=1e-12)

    def test_vdb_switch_to_sl(self) -> None:
        from gridcalc.libs.xlsx import VDB

        # When SL > DDB on remaining book, VDB switches; total over full life
        # always reaches (cost - salvage).
        full = VDB(2400, 300, 10, 0, 10, 2.0, False)
        assert isinstance(full, float)
        assert math.isclose(full, 2400 - 300, abs_tol=1e-6)

    def test_vdb_invalid(self) -> None:
        from gridcalc.libs.xlsx import VDB

        assert VDB(2400, 300, 10, -1, 5) is ExcelError.NUM
        assert VDB(2400, 300, 10, 5, 11) is ExcelError.NUM
        # Fractional periods unsupported.
        assert VDB(2400, 300, 10, 0.5, 5) is ExcelError.NUM

    def test_effect_nominal_round_trip(self) -> None:
        from gridcalc.libs.xlsx import EFFECT, NOMINAL

        # Excel: =EFFECT(0.0525, 4) -> 0.05354266...
        assert math.isclose(EFFECT(0.0525, 4), 0.05354266737075819, rel_tol=1e-12)
        # NOMINAL is the inverse.
        e = EFFECT(0.0525, 4)
        assert isinstance(e, float)
        n = NOMINAL(e, 4)
        assert isinstance(n, float)
        assert math.isclose(n, 0.0525, rel_tol=1e-12)
        assert EFFECT(0.05, 0) is ExcelError.NUM
        assert NOMINAL(0.05, 0) is ExcelError.NUM

    def test_cumipmt_cumprinc_partition_total(self) -> None:
        from gridcalc.libs.xlsx import CUMIPMT, CUMPRINC, PMT

        rate = 0.05 / 12
        n = 60
        pv = 10000
        ip_total = CUMIPMT(rate, n, pv, 1, n, 0)
        pp_total = CUMPRINC(rate, n, pv, 1, n, 0)
        # Sum of all periodic payments equals nper * PMT.
        full_pmt = PMT(rate, n, pv) * n
        assert isinstance(ip_total, float)
        assert isinstance(pp_total, float)
        assert math.isclose(ip_total + pp_total, full_pmt, rel_tol=1e-9)
        # Principal repaid over full schedule equals -pv.
        assert math.isclose(pp_total, -pv, rel_tol=1e-9)
        # Excel sign: CUMIPMT(.05/12, 60, 10000, 1, 12, 0) ≈ -458.99
        first_year = CUMIPMT(rate, n, pv, 1, 12, 0)
        assert isinstance(first_year, float)
        assert math.isclose(first_year, -458.9955074653277, rel_tol=1e-9)

    def test_cumipmt_invalid(self) -> None:
        from gridcalc.libs.xlsx import CUMIPMT, CUMPRINC

        assert CUMIPMT(0.05 / 12, 60, 10000, 0, 12, 0) is ExcelError.NUM
        assert CUMIPMT(0.05 / 12, 60, 10000, 12, 1, 0) is ExcelError.NUM
        assert CUMPRINC(-0.01, 60, 10000, 1, 12, 0) is ExcelError.NUM

    def test_mirr(self) -> None:
        from gridcalc.libs.xlsx import MIRR

        # Excel docs: =MIRR({-120000;39000;30000;21000;37000;46000}, 0.10, 0.12)
        # = 0.126094.
        flows = Vec([-120000.0, 39000.0, 30000.0, 21000.0, 37000.0, 46000.0])
        result = MIRR(flows, 0.10, 0.12)
        assert isinstance(result, float)
        assert math.isclose(result, 0.12609413036590503, rel_tol=1e-9)

    def test_mirr_invalid(self) -> None:
        from gridcalc.libs.xlsx import MIRR

        # All-positive cash flows have no PV(neg); divide-by-zero -> #DIV/0!.
        assert MIRR(Vec([100.0, 200.0]), 0.10, 0.12) is ExcelError.DIV0
        # Single cash flow.
        assert MIRR(Vec([100.0]), 0.10, 0.12) is ExcelError.DIV0

    def test_xnpv_xirr_excel_example(self) -> None:
        import datetime as _dt

        from gridcalc.libs.xlsx import XIRR, XNPV, _to_serial

        dates = [
            _dt.date(2008, 1, 1),
            _dt.date(2008, 3, 1),
            _dt.date(2008, 10, 30),
            _dt.date(2009, 2, 15),
            _dt.date(2009, 4, 1),
        ]
        flows = Vec([-10000.0, 2750.0, 4250.0, 3250.0, 2750.0])
        serials = Vec([_to_serial(d) for d in dates])
        # Excel docs reference values: XNPV(0.09,...) ≈ 2086.65;
        # XIRR(...) ≈ 0.373362535.
        xnpv = XNPV(0.09, flows, serials)
        xirr = XIRR(flows, serials)
        assert isinstance(xnpv, float)
        assert isinstance(xirr, float)
        assert math.isclose(xnpv, 2086.6476020315354, rel_tol=1e-9)
        assert math.isclose(xirr, 0.37336253351883164, rel_tol=1e-9)

    def test_xirr_invalid(self) -> None:
        from gridcalc.libs.xlsx import XIRR, XNPV

        # All positive flows have no IRR.
        assert XIRR(Vec([100.0, 200.0]), Vec([39448.0, 39500.0])) is ExcelError.NUM
        # Mismatched lengths.
        assert XNPV(0.1, Vec([1.0, 2.0]), Vec([39448.0])) is ExcelError.NUM
        assert XIRR(Vec([1.0]), Vec([39448.0])) is ExcelError.NUM

    def test_via_grid_excel_mode(self) -> None:
        """Confirm Tier 4 financial functions work through the formula evaluator."""
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, "=SLN(10000, 1000, 5)")
        g.setcell(0, 1, "=DDB(2400, 300, 10, 1)")
        g.setcell(0, 2, "=EFFECT(0.0525, 4)")
        assert g.cells[0][0].val == 1800.0
        assert g.cells[0][1].val == 480.0
        assert math.isclose(g.cells[0][2].val, 0.05354266737075819, rel_tol=1e-12)


class TestErfFamily:
    def test_erf(self) -> None:
        from gridcalc.libs.xlsx import ERF, ERFC

        assert math.isclose(ERF(1), 0.8427007929497149, rel_tol=1e-12)
        # Two-arg: erf(b) - erf(a).
        assert math.isclose(ERF(0, 1), 0.8427007929497149, rel_tol=1e-12)
        assert math.isclose(ERFC(1), 1 - 0.8427007929497149, rel_tol=1e-12)
        # ERF + ERFC = 1.
        for x in (-2.0, -0.5, 0.0, 0.5, 2.0):
            assert math.isclose(ERF(x) + ERFC(x), 1.0, abs_tol=1e-15)


class TestTextParse:
    def test_textbefore_basic(self) -> None:
        from gridcalc.libs.xlsx import TEXTBEFORE

        assert TEXTBEFORE("a-b-c", "-") == "a"
        assert TEXTBEFORE("a-b-c", "-", 2) == "a-b"
        # Negative instance counts from the right.
        assert TEXTBEFORE("a-b-c", "-", -1) == "a-b"
        # Not found.
        assert TEXTBEFORE("abc", "-") is ExcelError.NA
        assert TEXTBEFORE("abc", "-", if_not_found="missing") == "missing"

    def test_textbefore_case_insensitive(self) -> None:
        from gridcalc.libs.xlsx import TEXTBEFORE

        assert TEXTBEFORE("HelloWORLD", "world", 1, 1) == "Hello"
        # Default case-sensitive does not match.
        assert TEXTBEFORE("HelloWORLD", "world") is ExcelError.NA

    def test_textafter_basic(self) -> None:
        from gridcalc.libs.xlsx import TEXTAFTER

        assert TEXTAFTER("a-b-c", "-") == "b-c"
        assert TEXTAFTER("a-b-c", "-", 2) == "c"
        assert TEXTAFTER("abc", "-") is ExcelError.NA
        assert TEXTAFTER("abc", "-", if_not_found="") == ""

    def test_textsplit_1d(self) -> None:
        from gridcalc.libs.xlsx import TEXTSPLIT

        result = TEXTSPLIT("a,b,c", ",")
        assert isinstance(result, Vec)
        assert result.data == ["a", "b", "c"]
        assert result.cols == 3

    def test_textsplit_ignore_empty(self) -> None:
        from gridcalc.libs.xlsx import TEXTSPLIT

        # Default keeps empties.
        kept = TEXTSPLIT("a,,b", ",")
        assert isinstance(kept, Vec)
        assert kept.data == ["a", "", "b"]
        # ignore_empty=1 strips them.
        skipped = TEXTSPLIT("a,,b", ",", None, 1)
        assert isinstance(skipped, Vec)
        assert skipped.data == ["a", "b"]

    def test_textsplit_2d(self) -> None:
        from gridcalc.libs.xlsx import TEXTSPLIT

        result = TEXTSPLIT("a,b;c,d", ",", ";")
        assert isinstance(result, Vec)
        assert result.data == ["a", "b", "c", "d"]
        assert result.cols == 2


class TestNumberBase:
    def test_dec_to_base(self) -> None:
        from gridcalc.libs.xlsx import DEC2BIN, DEC2HEX, DEC2OCT

        assert DEC2BIN(9) == "1001"
        assert DEC2BIN(0) == "0"
        assert DEC2BIN(-1) == "1111111111"  # Two's-complement 10-digit.
        assert DEC2HEX(255) == "FF"
        assert DEC2HEX(-1) == "FFFFFFFFFF"
        assert DEC2OCT(8) == "10"
        # Padding.
        assert DEC2BIN(9, 8) == "00001001"
        # Out-of-range.
        assert DEC2BIN(512) is ExcelError.NUM
        assert DEC2BIN(-513) is ExcelError.NUM
        # Padding too small.
        assert DEC2BIN(9, 2) is ExcelError.NUM

    def test_base_to_dec(self) -> None:
        from gridcalc.libs.xlsx import BIN2DEC, HEX2DEC, OCT2DEC

        assert BIN2DEC("1010") == 10
        assert BIN2DEC("0") == 0
        assert BIN2DEC("1111111111") == -1  # Two's-complement.
        assert BIN2DEC("1111111110") == -2
        assert HEX2DEC("FF") == 255
        assert HEX2DEC("FFFFFFFFFF") == -1
        assert OCT2DEC("10") == 8
        # Invalid digits.
        assert BIN2DEC("12") is ExcelError.NUM
        assert HEX2DEC("XYZ") is ExcelError.NUM
        # Too long.
        assert BIN2DEC("11111111111") is ExcelError.NUM

    def test_cross_base(self) -> None:
        from gridcalc.libs.xlsx import BIN2HEX, HEX2BIN, HEX2OCT, OCT2HEX

        assert BIN2HEX("11111111") == "FF"
        assert HEX2BIN("F") == "1111"
        assert HEX2OCT("FF") == "377"
        assert OCT2HEX("377") == "FF"
        # Negative cross-conversion.
        assert BIN2HEX("1111111110") == "FFFFFFFFFE"

    def test_round_trip(self) -> None:
        from gridcalc.libs.xlsx import BIN2DEC, DEC2BIN, DEC2HEX, HEX2DEC

        for n in (0, 1, 100, 511, -1, -100, -512):
            assert BIN2DEC(DEC2BIN(n)) == n
            assert HEX2DEC(DEC2HEX(n)) == n


class TestForecastScalar:
    def test_forecast(self) -> None:
        from gridcalc.libs.xlsx import FORECAST, FORECAST_LINEAR

        x = Vec([1.0, 2.0, 3.0, 4.0, 5.0])
        y = Vec([3.0, 5.0, 7.0, 9.0, 11.0])  # y = 2x + 1
        assert math.isclose(FORECAST(6, y, x), 13.0, abs_tol=1e-12)  # type: ignore[arg-type]
        assert FORECAST_LINEAR(6, y, x) == FORECAST(6, y, x)
        # Forecast at known x is exact.
        assert math.isclose(FORECAST(3, y, x), 7.0, abs_tol=1e-12)  # type: ignore[arg-type]

    def test_trend_scalar_and_vec(self) -> None:
        from gridcalc.libs.xlsx import TREND as TREND_SCALAR

        x = Vec([1.0, 2.0, 3.0, 4.0])
        y = Vec([2.0, 4.0, 6.0, 8.0])  # y = 2x
        single = TREND_SCALAR(y, x, 5)
        assert math.isclose(single, 10.0, abs_tol=1e-12)
        multi = TREND_SCALAR(y, x, Vec([5.0, 6.0]))
        assert isinstance(multi, Vec)
        assert math.isclose(multi.data[0], 10.0, abs_tol=1e-12)
        assert math.isclose(multi.data[1], 12.0, abs_tol=1e-12)

    def test_trend_default_x(self) -> None:
        from gridcalc.libs.xlsx import TREND as TREND_SCALAR

        # known_x defaults to {1, 2, 3, ...}.
        y = Vec([2.0, 4.0, 6.0])
        # y = 2x; predicting at x=4 gives 8.
        result = TREND_SCALAR(y, None, 4)
        assert math.isclose(result, 8.0, abs_tol=1e-12)


class TestDFunctions:
    """Database functions over a 2D Vec with header row."""

    def _table(self) -> Vec:
        # Fields: Name, Region, Sales, Active
        rows = [
            "Name",
            "Region",
            "Sales",
            "Active",
            "Alice",
            "East",
            100.0,
            True,
            "Bob",
            "West",
            250.0,
            True,
            "Carol",
            "East",
            175.0,
            False,
            "Dave",
            "West",
            300.0,
            True,
            "Eve",
            "East",
            50.0,
            True,
        ]
        return Vec(rows, cols=4)

    def test_dsum_simple(self) -> None:
        from gridcalc.libs.xlsx import DSUM

        db = self._table()
        crit = Vec(["Region", "East"], cols=1)
        assert DSUM(db, "Sales", crit) == 100 + 175 + 50

    def test_daverage(self) -> None:
        from gridcalc.libs.xlsx import DAVERAGE

        db = self._table()
        crit = Vec(["Sales", ">100"], cols=1)
        result = DAVERAGE(db, "Sales", crit)
        assert isinstance(result, float)
        assert math.isclose(result, (250 + 175 + 300) / 3, rel_tol=1e-12)

    def test_dcount_and_dcounta(self) -> None:
        from gridcalc.libs.xlsx import DCOUNT, DCOUNTA

        db = self._table()
        crit = Vec(["Region", "East"], cols=1)
        # DCOUNT counts numerics in Sales for matching rows.
        assert DCOUNT(db, "Sales", crit) == 3
        # DCOUNTA on Name counts non-empty.
        assert DCOUNTA(db, "Name", crit) == 3

    def test_dget_unique(self) -> None:
        from gridcalc.libs.xlsx import DGET

        db = self._table()
        crit = Vec(["Name", "Bob"], cols=1)
        assert DGET(db, "Sales", crit) == 250.0
        # Multi-match -> #NUM!.
        crit_multi = Vec(["Region", "East"], cols=1)
        assert DGET(db, "Sales", crit_multi) is ExcelError.NUM
        # No match -> #VALUE!.
        crit_none = Vec(["Name", "Zelda"], cols=1)
        assert DGET(db, "Sales", crit_none) is ExcelError.VALUE

    def test_dmax_dmin_dproduct(self) -> None:
        from gridcalc.libs.xlsx import DMAX, DMIN, DPRODUCT

        db = self._table()
        crit = Vec(["Region", "West"], cols=1)
        assert DMAX(db, "Sales", crit) == 300.0
        assert DMIN(db, "Sales", crit) == 250.0
        assert DPRODUCT(db, "Sales", crit) == 250.0 * 300.0

    def test_dstdev_dvar(self) -> None:
        import statistics as _st

        from gridcalc.libs.xlsx import DSTDEV, DSTDEVP, DVAR, DVARP

        db = self._table()
        crit = Vec(["Region", "East"], cols=1)
        east_sales = [100.0, 175.0, 50.0]
        assert math.isclose(DSTDEV(db, "Sales", crit), _st.stdev(east_sales), rel_tol=1e-12)
        assert math.isclose(DSTDEVP(db, "Sales", crit), _st.pstdev(east_sales), rel_tol=1e-12)
        assert math.isclose(DVAR(db, "Sales", crit), _st.variance(east_sales), rel_tol=1e-12)
        assert math.isclose(DVARP(db, "Sales", crit), _st.pvariance(east_sales), rel_tol=1e-12)

    def test_d_or_clauses(self) -> None:
        from gridcalc.libs.xlsx import DSUM

        db = self._table()
        # Two clause rows: Region=East OR Sales>=300.
        crit = Vec(["Region", "Sales", "East", None, None, ">=300"], cols=2)
        # East: 100+175+50 = 325; plus Sales>=300 (Dave 300, not in East).
        assert DSUM(db, "Sales", crit) == 100 + 175 + 50 + 300

    def test_d_and_within_row(self) -> None:
        from gridcalc.libs.xlsx import DSUM

        db = self._table()
        # AND across columns in same row: Region=East AND Sales>100.
        crit = Vec(["Region", "Sales", "East", ">100"], cols=2)
        assert DSUM(db, "Sales", crit) == 175

    def test_d_field_by_index(self) -> None:
        from gridcalc.libs.xlsx import DSUM

        db = self._table()
        # Sales is column 3 (1-based).
        crit = Vec(["Region", "East"], cols=1)
        assert DSUM(db, 3, crit) == 100 + 175 + 50

    def test_d_invalid_field(self) -> None:
        from gridcalc.libs.xlsx import DSUM

        db = self._table()
        crit = Vec(["Region", "East"], cols=1)
        assert DSUM(db, "NoSuchField", crit) is ExcelError.VALUE

    def test_via_grid_excel_mode(self) -> None:
        """End-to-end DSUM evaluated from a formula on a real Grid range."""
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        # Database in A1:B5
        rows = [("Region", "Sales"), ("East", 100), ("West", 200), ("East", 150), ("West", 50)]
        for r, (region, sales) in enumerate(rows):
            g.setcell(0, r, region)
            g.setcell(1, r, str(sales) if isinstance(sales, int) else sales)
        # Criteria in D1:D2
        g.setcell(3, 0, "Region")
        g.setcell(3, 1, "East")
        # Result
        g.setcell(5, 0, '=DSUM(A1:B5, "Sales", D1:D2)')
        assert g.cells[5][0].val == 250.0


class TestStatDistributionsHeavier:
    """F/CHISQ/GAMMA/BETA/LOGNORM/WEIBULL/HYPGEOM/NEGBINOM/BINOM.INV
    plus hypothesis tests. Reference values cross-checked against Excel."""

    def test_f_dist_round_trip(self) -> None:
        from gridcalc.libs.xlsx import F_DIST, F_DIST_RT, F_INV, F_INV_RT

        x = F_INV_RT(0.01, 6, 4)
        assert isinstance(x, float)
        assert math.isclose(x, 15.20674856, rel_tol=1e-5)
        assert math.isclose(F_DIST(x, 6, 4, True), 0.99, abs_tol=1e-5)
        assert math.isclose(F_DIST_RT(x, 6, 4), 0.01, abs_tol=1e-5)
        assert math.isclose(F_INV(0.99, 6, 4), x, rel_tol=1e-9)

    def test_f_dist_invalid(self) -> None:
        from gridcalc.libs.xlsx import F_DIST, F_INV

        assert F_DIST(-1, 6, 4, True) is ExcelError.NUM
        assert F_DIST(1, 0, 4, True) is ExcelError.NUM
        assert F_INV(-0.1, 6, 4) is ExcelError.NUM

    def test_chisq_dist_round_trip(self) -> None:
        from gridcalc.libs.xlsx import CHISQ_DIST, CHISQ_DIST_RT, CHISQ_INV, CHISQ_INV_RT

        x = CHISQ_INV_RT(0.05, 10)
        assert isinstance(x, float)
        assert math.isclose(x, 18.30703805, rel_tol=1e-6)
        assert math.isclose(CHISQ_DIST(x, 10, True), 0.95, abs_tol=1e-6)
        assert math.isclose(CHISQ_DIST_RT(x, 10), 0.05, abs_tol=1e-6)
        pdf = CHISQ_DIST(10, 10, False)
        assert isinstance(pdf, float)
        assert pdf > 0
        assert math.isclose(CHISQ_INV(0.95, 10), x, rel_tol=1e-9)

    def test_chisq_test(self) -> None:
        from gridcalc.libs.xlsx import CHISQ_TEST

        assert math.isclose(
            CHISQ_TEST(Vec([10.0, 20.0, 30.0]), Vec([10.0, 20.0, 30.0])), 1.0, abs_tol=1e-12
        )
        actual = Vec([58.0, 11.0, 10.0, 12.0, 9.0])
        expected = Vec([20.0, 20.0, 20.0, 20.0, 20.0])
        result = CHISQ_TEST(actual, expected)
        assert isinstance(result, float)
        # chi2 ≈ 90.5 with df=4 underflows to ~0; tolerate very small p.
        assert 0 <= result < 1e-15

    def test_gamma_family(self) -> None:
        from gridcalc.libs.xlsx import GAMMA, GAMMA_DIST, GAMMA_INV, GAMMALN

        assert GAMMA(5) == 24.0
        assert math.isclose(GAMMA(0.5), math.sqrt(math.pi), rel_tol=1e-15)
        assert GAMMA(0) is ExcelError.NUM
        assert GAMMA(-2) is ExcelError.NUM
        assert math.isclose(GAMMALN(10), math.log(math.factorial(9)), rel_tol=1e-12)
        assert GAMMALN(-1) is ExcelError.NUM
        assert math.isclose(GAMMA_DIST(5, 3, 2, True), 0.4561868841166707, rel_tol=1e-9)
        x = GAMMA_INV(0.5, 3, 2)
        assert isinstance(x, float)
        assert math.isclose(GAMMA_DIST(x, 3, 2, True), 0.5, abs_tol=1e-9)

    def test_beta_dist(self) -> None:
        from gridcalc.libs.xlsx import BETA_DIST, BETA_INV

        assert math.isclose(BETA_DIST(0.4, 2, 3, True), 0.5248, rel_tol=1e-9)
        x = BETA_INV(0.5, 2, 3)
        assert isinstance(x, float)
        assert math.isclose(BETA_DIST(x, 2, 3, True), 0.5, abs_tol=1e-9)
        cdf_scaled = BETA_DIST(2, 2, 3, True, 0, 5)
        cdf_std = BETA_DIST(2 / 5, 2, 3, True)
        assert isinstance(cdf_scaled, float)
        assert isinstance(cdf_std, float)
        assert math.isclose(cdf_scaled, cdf_std, rel_tol=1e-12)

    def test_lognorm(self) -> None:
        from gridcalc.libs.xlsx import LOGNORM_DIST, LOGNORM_INV

        assert math.isclose(LOGNORM_DIST(4, 3.5, 1.2, True), 0.0390835557068005, rel_tol=1e-9)
        x = LOGNORM_INV(0.5, 3.5, 1.2)
        assert isinstance(x, float)
        assert math.isclose(LOGNORM_DIST(x, 3.5, 1.2, True), 0.5, abs_tol=1e-9)
        assert LOGNORM_DIST(0, 3.5, 1.2, True) is ExcelError.NUM
        assert LOGNORM_INV(0, 3.5, 1.2) is ExcelError.NUM

    def test_weibull(self) -> None:
        from gridcalc.libs.xlsx import WEIBULL_DIST

        assert math.isclose(WEIBULL_DIST(105, 20, 100, True), 0.9295813900692769, rel_tol=1e-9)
        assert WEIBULL_DIST(0, 2, 1, False) == 0.0
        assert WEIBULL_DIST(-1, 2, 1, True) is ExcelError.NUM

    def test_hypgeom(self) -> None:
        from gridcalc.libs.xlsx import HYPGEOM_DIST

        assert math.isclose(HYPGEOM_DIST(1, 4, 8, 20, False), 0.3632610939112508, rel_tol=1e-9)
        total = sum(HYPGEOM_DIST(k, 4, 8, 20, False) for k in range(5))  # type: ignore[misc]
        assert math.isclose(total, 1.0, abs_tol=1e-12)
        cum = HYPGEOM_DIST(2, 4, 8, 20, True)
        assert isinstance(cum, float)
        assert 0 < cum < 1

    def test_negbinom(self) -> None:
        from gridcalc.libs.xlsx import NEGBINOM_DIST

        assert math.isclose(NEGBINOM_DIST(10, 5, 0.25, False), 0.055048660375178124, rel_tol=1e-9)

    def test_binom_inv(self) -> None:
        from gridcalc.libs.xlsx import BINOM_DIST, BINOM_INV

        k = BINOM_INV(6, 0.5, 0.75)
        assert k == 4
        assert BINOM_DIST(4, 6, 0.5, True) >= 0.75  # type: ignore[operator]
        assert BINOM_DIST(3, 6, 0.5, True) < 0.75  # type: ignore[operator]

    def test_t_test_paired(self) -> None:
        from gridcalc.libs.xlsx import T_TEST

        a = Vec([3.0, 4.0, 5.0, 8.0, 9.0, 1.0, 2.0, 4.0, 5.0])
        b = Vec([6.0, 19.0, 3.0, 2.0, 14.0, 4.0, 5.0, 17.0, 1.0])
        result = T_TEST(a, b, 2, 1)
        assert isinstance(result, float)
        assert math.isclose(result, 0.196015785, abs_tol=1e-5)

    def test_t_test_two_sample(self) -> None:
        from gridcalc.libs.xlsx import T_TEST

        a = Vec([3.0, 4.0, 5.0, 8.0, 9.0, 1.0, 2.0, 4.0, 5.0])
        b = Vec([6.0, 19.0, 3.0, 2.0, 14.0, 4.0, 5.0, 17.0, 1.0])
        eq = T_TEST(a, b, 2, 2)
        welch = T_TEST(a, b, 2, 3)
        assert isinstance(eq, float)
        assert isinstance(welch, float)
        assert 0 < eq < 1
        assert 0 < welch < 1

    def test_z_test(self) -> None:
        from gridcalc.libs.xlsx import Z_TEST

        result = Z_TEST(Vec([3.0, 6.0, 7.0, 8.0, 6.0, 5.0, 4.0, 2.0, 1.0, 9.0]), 4)
        assert isinstance(result, float)
        assert math.isclose(result, 0.0905741968, abs_tol=1e-5)

    def test_confidence_t(self) -> None:
        from gridcalc.libs.xlsx import CONFIDENCE_T, T_INV_2T

        result = CONFIDENCE_T(0.05, 1.0, 50)
        expected = T_INV_2T(0.05, 49) * 1.0 / math.sqrt(50)  # type: ignore[operator]
        assert isinstance(result, float)
        assert math.isclose(result, expected, rel_tol=1e-12)
        assert CONFIDENCE_T(0.05, 1.0, 1) is ExcelError.NUM

    def test_standardize_phi(self) -> None:
        from gridcalc.libs.xlsx import PHI, STANDARDIZE

        assert STANDARDIZE(42, 40, 1.5) == (42 - 40) / 1.5
        assert STANDARDIZE(0, 0, 0) is ExcelError.NUM
        assert math.isclose(PHI(0), 1 / math.sqrt(2 * math.pi), rel_tol=1e-15)

    def test_prob(self) -> None:
        from gridcalc.libs.xlsx import PROB

        xs = Vec([0.0, 1.0, 2.0, 3.0, 4.0])
        ps = Vec([0.2, 0.3, 0.1, 0.1, 0.3])
        assert math.isclose(PROB(xs, ps, 1, 3), 0.5, abs_tol=1e-12)
        assert math.isclose(PROB(xs, ps, 2), 0.1, abs_tol=1e-12)
        bad = Vec([0.1, 0.1, 0.1])
        assert PROB(Vec([1.0, 2.0, 3.0]), bad, 1) is ExcelError.NUM

    def test_legacy_aliases(self) -> None:
        from gridcalc.libs.xlsx import BUILTINS

        assert math.isclose(BUILTINS["FDIST"](15.20675, 6, 4), 0.01, abs_tol=1e-5)
        assert math.isclose(BUILTINS["CHIDIST"](18.307, 10), 0.05, abs_tol=1e-5)
        assert math.isclose(BUILTINS["FINV"](0.01, 6, 4), 15.2068, rel_tol=1e-4)
        assert math.isclose(BUILTINS["CHIINV"](0.05, 10), 18.307, rel_tol=1e-5)
        assert BUILTINS["CRITBINOM"](6, 0.5, 0.75) == 4
        assert math.isclose(
            BUILTINS["WEIBULL"](105, 20, 100, True), 0.9295813900692769, rel_tol=1e-9
        )

    def test_via_grid_excel_mode(self) -> None:
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, "=GAMMA(5)")
        g.setcell(0, 1, "=CHISQ.INV(0.95, 10)")
        g.setcell(0, 2, "=BETA.DIST(0.4, 2, 3, TRUE)")
        g.setcell(0, 3, "=STANDARDIZE(42, 40, 1.5)")
        assert g.cells[0][0].val == 24.0
        assert math.isclose(g.cells[0][1].val, 18.30703805329528, rel_tol=1e-9)
        assert math.isclose(g.cells[0][2].val, 0.5248, rel_tol=1e-9)
        assert math.isclose(g.cells[0][3].val, 4 / 3, rel_tol=1e-12)


class TestReshape2D:
    """Phase 3 of 2D-Vec: TRANSPOSE + reshape consumers."""

    def test_transpose_2d(self) -> None:
        from gridcalc.libs.xlsx import TRANSPOSE

        m = Vec([1, 2, 3, 4, 5, 6], cols=3)  # 2x3
        t = TRANSPOSE(m)
        assert t.shape == (3, 2)
        assert t.data == [1, 4, 2, 5, 3, 6]

    def test_transpose_round_trip(self) -> None:
        from gridcalc.libs.xlsx import TRANSPOSE

        m = Vec([1, 2, 3, 4, 5, 6, 7, 8], cols=4)
        assert TRANSPOSE(TRANSPOSE(m)).data == list(m.data)

    def test_transpose_1d_to_row(self) -> None:
        from gridcalc.libs.xlsx import TRANSPOSE

        v = Vec([10, 20, 30])  # column vector (3, 1)
        t = TRANSPOSE(v)
        assert t.shape == (1, 3)
        assert t.data == [10, 20, 30]

    def test_chooserows(self) -> None:
        from gridcalc.libs.xlsx import CHOOSEROWS

        m = Vec([1, 2, 3, 4, 5, 6], cols=2)  # 3x2
        result = CHOOSEROWS(m, 1, 3)
        assert isinstance(result, Vec)
        assert result.data == [1, 2, 5, 6]
        assert result.cols == 2
        assert CHOOSEROWS(m, -1).data == [5, 6]
        assert CHOOSEROWS(m, 1, 1, 2).data == [1, 2, 1, 2, 3, 4]

    def test_chooserows_invalid(self) -> None:
        from gridcalc.libs.xlsx import CHOOSEROWS

        m = Vec([1, 2, 3, 4], cols=2)
        assert CHOOSEROWS(m, 0) is ExcelError.VALUE
        assert CHOOSEROWS(m, 5) is ExcelError.VALUE

    def test_choosecols(self) -> None:
        from gridcalc.libs.xlsx import CHOOSECOLS

        m = Vec([1, 2, 3, 4, 5, 6, 7, 8, 9], cols=3)  # 3x3
        result = CHOOSECOLS(m, 2)
        assert isinstance(result, Vec)
        assert result.data == [2, 5, 8]
        result2 = CHOOSECOLS(m, 3, 1)
        assert isinstance(result2, Vec)
        assert result2.data == [3, 1, 6, 4, 9, 7]
        assert result2.cols == 2

    def test_torow_skip_blanks(self) -> None:
        from gridcalc.libs.xlsx import TOROW

        v = Vec([1, None, 2, "", 3], cols=5)
        assert TOROW(v, 1).data == [1, 2, 3]

    def test_torow_scan_by_column(self) -> None:
        from gridcalc.libs.xlsx import TOROW

        m = Vec([1, 2, 3, 4, 5, 6], cols=3)
        assert TOROW(m, 0, 0).data == [1, 2, 3, 4, 5, 6]
        assert TOROW(m, 0, 1).data == [1, 4, 2, 5, 3, 6]

    def test_tocol_returns_column(self) -> None:
        from gridcalc.libs.xlsx import TOCOL

        result = TOCOL(Vec([1, 2, 3, 4], cols=2))
        assert result.cols is None
        assert result.data == [1, 2, 3, 4]

    def test_wraprows(self) -> None:
        from gridcalc.libs.xlsx import WRAPROWS

        result = WRAPROWS(Vec([1, 2, 3, 4, 5, 6]), 2)
        assert isinstance(result, Vec)
        assert result.shape == (3, 2)
        assert result.data == [1, 2, 3, 4, 5, 6]
        padded = WRAPROWS(Vec([1, 2, 3, 4, 5]), 2, 0)
        assert isinstance(padded, Vec)
        assert padded.data == [1, 2, 3, 4, 5, 0]

    def test_wrapcols(self) -> None:
        from gridcalc.libs.xlsx import WRAPCOLS

        result = WRAPCOLS(Vec([1, 2, 3, 4, 5, 6]), 2)
        assert isinstance(result, Vec)
        assert result.shape == (2, 3)
        # Element k goes to row=k%2, col=k//2.
        assert result.data == [1, 3, 5, 2, 4, 6]

    def test_expand(self) -> None:
        from gridcalc.libs.xlsx import EXPAND

        m = Vec([1, 2, 3, 4], cols=2)  # 2x2
        result = EXPAND(m, 3, 3, 0)
        assert isinstance(result, Vec)
        assert result.shape == (3, 3)
        assert result.data == [1, 2, 0, 3, 4, 0, 0, 0, 0]

    def test_expand_smaller_target_errors(self) -> None:
        from gridcalc.libs.xlsx import EXPAND

        m = Vec([1, 2, 3, 4], cols=2)
        assert EXPAND(m, 1, 1, 0) is ExcelError.VALUE

    def test_take_positive_negative(self) -> None:
        from gridcalc.libs.xlsx import TAKE

        m = Vec([1, 2, 3, 4, 5, 6], cols=2)  # 3x2
        first = TAKE(m, 2)
        assert isinstance(first, Vec)
        assert first.data == [1, 2, 3, 4]
        last = TAKE(m, -2)
        assert isinstance(last, Vec)
        assert last.data == [3, 4, 5, 6]
        first_col = TAKE(m, 3, 1)
        assert isinstance(first_col, Vec)
        assert first_col.data == [1, 3, 5]

    def test_drop_positive_negative(self) -> None:
        from gridcalc.libs.xlsx import DROP

        m = Vec([1, 2, 3, 4, 5, 6], cols=2)  # 3x2
        assert DROP(m, 1).data == [3, 4, 5, 6]  # type: ignore[union-attr]
        assert DROP(m, -1).data == [1, 2, 3, 4]  # type: ignore[union-attr]

    def test_vstack(self) -> None:
        from gridcalc.libs.xlsx import VSTACK

        a = Vec([1, 2, 3, 4], cols=2)
        b = Vec([5, 6], cols=2)
        result = VSTACK(a, b)
        assert isinstance(result, Vec)
        assert result.shape == (3, 2)
        assert result.data == [1, 2, 3, 4, 5, 6]

    def test_vstack_pads_widths(self) -> None:
        from gridcalc.libs.xlsx import VSTACK

        a = Vec([1, 2, 3, 4], cols=2)
        b = Vec([5, 6, 7], cols=3)
        result = VSTACK(a, b)
        assert isinstance(result, Vec)
        assert result.shape == (3, 3)
        assert result.data[0:3] == [1, 2, ExcelError.NA]
        assert result.data[3:6] == [3, 4, ExcelError.NA]
        assert result.data[6:9] == [5, 6, 7]

    def test_hstack(self) -> None:
        from gridcalc.libs.xlsx import HSTACK

        a = Vec([1, 2, 3, 4], cols=2)
        b = Vec([5, 6], cols=1)
        result = HSTACK(a, b)
        assert isinstance(result, Vec)
        assert result.shape == (2, 3)
        assert result.data == [1, 2, 5, 3, 4, 6]

    def test_hstack_pads_heights(self) -> None:
        from gridcalc.libs.xlsx import HSTACK

        a = Vec([1, 2, 3, 4], cols=2)
        b = Vec([5, 6, 7], cols=1)
        result = HSTACK(a, b)
        assert isinstance(result, Vec)
        assert result.shape == (3, 3)
        assert result.data[0:3] == [1, 2, 5]
        assert result.data[3:6] == [3, 4, 6]
        assert result.data[6:9] == [ExcelError.NA, ExcelError.NA, 7]

    def test_via_grid_excel_mode(self) -> None:
        """End-to-end TRANSPOSE picked via INDEX."""
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        for c in range(3):
            g.setcell(c, 0, str(c + 1))
            g.setcell(c, 1, str(c + 4))
        # TRANSPOSE(A1:C2) is 3x2; INDEX(.., 1, 2) reads row=1, col=2.
        # Original (1,2) value (1-based) = the col=2 cell of row 1 in the
        # transposed = row=1 of transposed = (1, c=1 of transposed) which
        # is the *original* (col=1 of transposed src, so col=1 row=2),
        # i.e. A2 = 4.
        g.setcell(0, 3, "=INDEX(TRANSPOSE(A1:C2), 1, 2)")
        assert g.cells[0][3].val == 4.0


class TestRegressionFamily:
    """Phase 4: LINEST/LOGEST/TREND/GROWTH with multi-regressor support."""

    def test_solver_2x2(self) -> None:
        from gridcalc.libs.xlsx import _solve_linear_system

        # 2x + y = 5; x + 3y = 10  ->  x=1, y=3.
        result = _solve_linear_system([[2.0, 1.0], [1.0, 3.0]], [5.0, 10.0])
        assert isinstance(result, list)
        assert math.isclose(result[0], 1.0, abs_tol=1e-12)
        assert math.isclose(result[1], 3.0, abs_tol=1e-12)

    def test_solver_singular(self) -> None:
        from gridcalc.libs.xlsx import _solve_linear_system

        # Linearly dependent rows -> singular.
        result = _solve_linear_system([[1.0, 2.0], [2.0, 4.0]], [3.0, 6.0])
        assert result is ExcelError.NUM

    def test_linest_single_regressor(self) -> None:
        from gridcalc.libs.xlsx import LINEST

        # y = 2x + 1
        x = Vec([1.0, 2.0, 3.0, 4.0, 5.0])
        y = Vec([3.0, 5.0, 7.0, 9.0, 11.0])
        result = LINEST(y, x)
        assert isinstance(result, Vec)
        # Excel order: m, b.
        assert math.isclose(result.data[0], 2.0, abs_tol=1e-9)
        assert math.isclose(result.data[1], 1.0, abs_tol=1e-9)

    def test_linest_multi_regressor(self) -> None:
        from gridcalc.libs.xlsx import LINEST

        # y = 1 + 2*x1 + 3*x2 (no noise)
        pairs = [(1, 1), (2, 1), (1, 2), (3, 2), (2, 3), (4, 5)]
        ys = Vec([float(1 + 2 * a + 3 * b) for a, b in pairs])
        xs = Vec([float(v) for pair in pairs for v in pair], cols=2)
        result = LINEST(ys, xs)
        assert isinstance(result, Vec)
        # Excel order: m_k (last regressor's slope first), ..., m_1, b.
        # So: [m2=3, m1=2, b=1].
        assert math.isclose(result.data[0], 3.0, abs_tol=1e-9)
        assert math.isclose(result.data[1], 2.0, abs_tol=1e-9)
        assert math.isclose(result.data[2], 1.0, abs_tol=1e-9)

    def test_linest_no_constant(self) -> None:
        from gridcalc.libs.xlsx import LINEST

        # y = 2x without intercept; force through origin.
        x = Vec([1.0, 2.0, 3.0])
        y = Vec([2.0, 4.0, 6.0])
        result = LINEST(y, x, False)
        assert isinstance(result, Vec)
        # No intercept reported.
        assert len(result.data) == 1
        assert math.isclose(result.data[0], 2.0, abs_tol=1e-9)

    def test_linest_stats_matrix(self) -> None:
        from gridcalc.libs.xlsx import LINEST

        # Perfect linear fit -> r²=1, ss_residual=0.
        x = Vec([1.0, 2.0, 3.0, 4.0, 5.0])
        y = Vec([3.0, 5.0, 7.0, 9.0, 11.0])
        result = LINEST(y, x, True, True)
        assert isinstance(result, Vec)
        assert result.shape == (5, 2)
        # Row 1 = coefficients; row 3 col 1 = r².
        assert math.isclose(result.at(1, 1), 2.0, abs_tol=1e-9)
        assert math.isclose(result.at(1, 2), 1.0, abs_tol=1e-9)
        assert math.isclose(result.at(3, 1), 1.0, abs_tol=1e-9)  # r² = 1

    def test_logest(self) -> None:
        from gridcalc.libs.xlsx import LOGEST

        # y = 2 * 3^x  ->  ln(y) = ln(2) + ln(3)*x
        x = Vec([0.0, 1.0, 2.0, 3.0, 4.0])
        y = Vec([2.0 * 3**i for i in range(5)])
        result = LOGEST(y, x)
        assert isinstance(result, Vec)
        # Excel order: [m=3, b=2] (multiplicative).
        assert math.isclose(result.data[0], 3.0, abs_tol=1e-9)
        assert math.isclose(result.data[1], 2.0, abs_tol=1e-9)

    def test_logest_invalid_y(self) -> None:
        from gridcalc.libs.xlsx import LOGEST

        # ln of non-positive -> #NUM!.
        assert LOGEST(Vec([1.0, 0.0, 4.0]), Vec([1.0, 2.0, 3.0])) is ExcelError.NUM

    def test_trend_array(self) -> None:
        from gridcalc.libs.xlsx import TREND

        # y = 2x + 1; predict at new x = [6, 7].
        x = Vec([1.0, 2.0, 3.0, 4.0, 5.0])
        y = Vec([3.0, 5.0, 7.0, 9.0, 11.0])
        result = TREND(y, x, Vec([6.0, 7.0]))
        assert isinstance(result, Vec)
        assert math.isclose(result.data[0], 13.0, abs_tol=1e-9)
        assert math.isclose(result.data[1], 15.0, abs_tol=1e-9)

    def test_trend_multi_regressor(self) -> None:
        from gridcalc.libs.xlsx import TREND

        # y = 1 + 2*x1 + 3*x2
        pairs = [(1, 1), (2, 1), (1, 2), (3, 2), (2, 3), (4, 5)]
        ys = Vec([float(1 + 2 * a + 3 * b) for a, b in pairs])
        xs = Vec([float(v) for pair in pairs for v in pair], cols=2)
        # Predict at (5, 5) and (10, 1) -> [1+10+15, 1+20+3] = [26, 24].
        new_x = Vec([5.0, 5.0, 10.0, 1.0], cols=2)
        result = TREND(ys, xs, new_x)
        assert isinstance(result, Vec)
        assert math.isclose(result.data[0], 26.0, abs_tol=1e-9)
        assert math.isclose(result.data[1], 24.0, abs_tol=1e-9)

    def test_growth(self) -> None:
        from gridcalc.libs.xlsx import GROWTH

        # y = 2 * 3^x; predict at x=5 -> 2 * 243 = 486.
        x = Vec([0.0, 1.0, 2.0, 3.0, 4.0])
        y = Vec([2.0 * 3**i for i in range(5)])
        result = GROWTH(y, x, 5)
        assert isinstance(result, float)
        assert math.isclose(result, 486.0, rel_tol=1e-9)

    def test_via_grid_excel_mode(self) -> None:
        """End-to-end LINEST through the formula evaluator."""
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        # y = 2x + 1 in A1:A5 (y) and B1:B5 (x).
        for i in range(5):
            g.setcell(0, i, str(2 * (i + 1) + 1))
            g.setcell(1, i, str(i + 1))
        # LINEST returns a 1×2 row [slope, intercept].
        g.setcell(3, 0, "=INDEX(LINEST(A1:A5, B1:B5), 1, 1)")
        g.setcell(3, 1, "=INDEX(LINEST(A1:A5, B1:B5), 1, 2)")
        assert math.isclose(g.cells[3][0].val, 2.0, abs_tol=1e-9)
        assert math.isclose(g.cells[3][1].val, 1.0, abs_tol=1e-9)
