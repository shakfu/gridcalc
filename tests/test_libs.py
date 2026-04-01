"""Tests for formula libs (xlsx compatibility functions)."""

from __future__ import annotations

import math
from pathlib import Path

from gridcalc.engine import Grid, Vec
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
