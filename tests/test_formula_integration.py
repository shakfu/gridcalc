"""Integration tests for the formula evaluator wired into Grid.recalc()."""

import math

import pytest

from gridcalc.display import cell_text
from gridcalc.engine import Grid, Mode, NamedRange
from gridcalc.formula.errors import ExcelError


def make_excel_grid():
    g = Grid()
    g.mode = Mode.EXCEL
    return g


def make_hybrid_grid():
    g = Grid()
    g.mode = Mode.HYBRID
    return g


class TestExcelMode:
    def test_arithmetic(self):
        g = make_excel_grid()
        g.setcell(0, 0, "=1+2*3")
        assert g.cells[0][0].val == 7.0

    def test_cell_ref(self):
        g = make_excel_grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "=A1+5")
        assert g.cells[1][0].val == 15.0

    def test_range_sum(self):
        g = make_excel_grid()
        g.setcell(0, 0, "1")
        g.setcell(0, 1, "2")
        g.setcell(0, 2, "3")
        g.setcell(1, 0, "=SUM(A1:A3)")
        assert g.cells[1][0].val == 6.0

    def test_div_zero_yields_nan(self):
        g = make_excel_grid()
        g.setcell(0, 0, "=1/0")
        assert math.isnan(g.cells[0][0].val)

    def test_unknown_function_yields_nan(self):
        g = make_excel_grid()
        g.setcell(0, 0, "=NOPE()")
        assert math.isnan(g.cells[0][0].val)

    def test_pow_right_assoc(self):
        g = make_excel_grid()
        g.setcell(0, 0, "=2^3^2")
        assert g.cells[0][0].val == 512.0

    def test_string_concat(self):
        g = make_excel_grid()
        g.setcell(0, 0, '="x"&"y"')
        # string result; cell.val falls back to nan
        assert g.cells[0][0].arr is None
        # cell text or arr won't hold string; but it shouldn't crash

    def test_named_range(self):
        g = make_excel_grid()
        g.setcell(0, 0, "5")
        g.names.append(NamedRange(name="X", c1=0, r1=0, c2=0, r2=0))
        g.setcell(1, 0, "=X+1")
        # Force a recalc since names was appended after setcell
        g.recalc()
        assert g.cells[1][0].val == 6.0

    def test_dependent_recalc(self):
        g = make_excel_grid()
        g.setcell(0, 0, "1")
        g.setcell(1, 0, "=A1*2")
        g.setcell(2, 0, "=B1+10")
        assert g.cells[2][0].val == 12.0
        g.setcell(0, 0, "5")
        assert g.cells[1][0].val == 10.0
        assert g.cells[2][0].val == 20.0

    def test_self_reference_circular(self):
        g = make_excel_grid()
        g.setcell(0, 0, "=A1+1")
        assert (0, 0) in g._circular
        assert math.isnan(g.cells[0][0].val)

    def test_range_broadcast(self):
        g = make_excel_grid()
        g.setcell(0, 0, "1")
        g.setcell(0, 1, "2")
        g.setcell(0, 2, "3")
        g.setcell(1, 0, "=A1:A3+10")
        assert g.cells[1][0].arr == [11.0, 12.0, 13.0]


class TestHybridMode:
    def test_basic_formula_works(self):
        g = make_hybrid_grid()
        g.setcell(0, 0, "=1+2")
        assert g.cells[0][0].val == 3.0

    def test_py_call_unregistered_yields_nan(self):
        g = make_hybrid_grid()
        g.setcell(0, 0, "=py.foo(1)")
        assert math.isnan(g.cells[0][0].val)

    def test_py_call_registered(self):
        g = make_hybrid_grid()
        g.code = "def double(x):\n    return x * 2\n"
        g.setcell(0, 0, "=py.double(21)")
        g.recalc()
        assert g.cells[0][0].val == 42.0

    def test_py_call_with_cell_ref(self):
        g = make_hybrid_grid()
        g.code = "def inc(x):\n    return x + 1\n"
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "=py.inc(A1)")
        g.recalc()
        assert g.cells[1][0].val == 11.0


class TestLegacyUnchanged:
    def test_legacy_still_uses_eval(self):
        g = Grid()
        assert g.mode == Mode.PYTHON
        g.setcell(0, 0, "=1+2")
        assert g.cells[0][0].val == 3.0

    def test_legacy_python_only_features(self):
        # legacy supports list comprehensions; excel mode would not
        g = Grid()
        g.setcell(0, 0, "=sum([1,2,3])")
        assert g.cells[0][0].val == 6.0


class TestAstCache:
    def test_ast_populated_after_recalc(self):
        g = make_excel_grid()
        g.setcell(0, 0, "=1+2")
        cl = g.cells[0][0]
        assert cl.ast is not None
        assert cl.ast_text == "1+2"

    def test_ast_invalidated_on_text_change(self):
        g = make_excel_grid()
        g.setcell(0, 0, "=1+2")
        first_ast = g.cells[0][0].ast
        g.setcell(0, 0, "=3+4")
        cl = g.cells[0][0]
        assert cl.ast is not first_ast
        assert cl.val == 7.0

    def test_invalid_formula_clears_ast(self):
        g = make_excel_grid()
        g.setcell(0, 0, "=(1+")
        cl = g.cells[0][0]
        assert cl.ast is None
        assert math.isnan(cl.val)


class TestModePersistence:
    def test_excel_mode_roundtrips(self, tmp_path):
        g = make_excel_grid()
        g.setcell(0, 0, "1")
        g.setcell(1, 0, "=A1*2")
        f = tmp_path / "x.json"
        assert g.jsonsave(str(f)) == 0
        g2 = Grid()
        assert g2.jsonload(str(f)) == 0
        assert g2.mode == Mode.EXCEL
        assert g2.cells[1][0].val == 2.0

    def test_hybrid_with_code_roundtrips(self, tmp_path):
        g = make_hybrid_grid()
        g.code = "def triple(x):\n    return x * 3\n"
        g.setcell(0, 0, "=py.triple(7)")
        g.recalc()
        f = tmp_path / "h.json"
        assert g.jsonsave(str(f)) == 0
        g2 = Grid()
        # load in hybrid mode (must trust the code block via policy.load_code)
        from gridcalc.sandbox import LoadPolicy

        assert g2.jsonload(str(f), policy=LoadPolicy(load_code=True, approved_modules=[])) == 0
        assert g2.mode == Mode.HYBRID
        assert g2.cells[0][0].val == 21.0


class TestAutoLoadXlsx:
    def test_excel_mode_auto_loads_xlsx(self):
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        assert "xlsx" in g.libs
        # IF should be available
        g.setcell(0, 0, "=IF(1=1, 10, 20)")
        assert g.cells[0][0].val == 10.0

    def test_hybrid_mode_auto_loads_xlsx(self):
        g = Grid()
        g.mode = Mode.HYBRID
        g._apply_mode_libs()
        assert "xlsx" in g.libs

    def test_legacy_mode_does_not_auto_load(self):
        g = Grid()
        g._apply_mode_libs()
        assert "xlsx" not in g.libs

    def test_jsonload_excel_auto_loads(self, tmp_path):
        f = tmp_path / "x.json"
        f.write_text('{"version": 1, "mode": "EXCEL", "cells": [["=IF(1=1,5,9)"]]}')
        g = Grid()
        assert g.jsonload(str(f)) == 0
        assert "xlsx" in g.libs
        assert g.cells[0][0].val == 5.0


class TestValidateForMode:
    def test_legacy_target_no_errors(self):
        g = Grid()
        g.setcell(0, 0, "=[x for x in range(3)]")
        assert g.validate_for_mode(Mode.PYTHON) == []

    def test_excel_target_rejects_python_only(self):
        g = Grid()
        g.setcell(0, 0, "=[x*2 for x in range(3)]")
        errs = g.validate_for_mode(Mode.EXCEL)
        assert len(errs) == 1
        assert "A1" in errs[0]

    def test_excel_target_rejects_pycall(self):
        g = Grid()
        g.mode = Mode.HYBRID
        g.setcell(0, 0, "=py.foo(1)")
        errs = g.validate_for_mode(Mode.EXCEL)
        assert any("py.* calls not allowed" in e for e in errs)

    def test_excel_target_rejects_code_block(self):
        g = Grid()
        g.code = "def f(): pass"
        errs = g.validate_for_mode(Mode.EXCEL)
        assert any("code block" in e for e in errs)

    def test_hybrid_target_accepts_pycall(self):
        g = Grid()
        g.setcell(0, 0, "=py.foo(1)")
        assert g.validate_for_mode(Mode.HYBRID) == []

    def test_hybrid_target_rejects_python_only(self):
        g = Grid()
        g.setcell(0, 0, "=[x for x in range(3)]")
        errs = g.validate_for_mode(Mode.HYBRID)
        assert len(errs) == 1


class TestStringResults:
    def test_if_returns_string_excel(self):
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, '=IF(1=1, "yes", "no")')
        cl = g.cells[0][0]
        assert cl.sval == "yes"
        assert cl.val == 0.0

    def test_if_returns_string_false_branch(self):
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, '=IF(1=2, "yes", "no")')
        assert g.cells[0][0].sval == "no"

    def test_concatenate(self):
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, '="foo" & "bar"')
        assert g.cells[0][0].sval == "foobar"

    def test_bool_compare_stores_truefalse(self):
        g = Grid()
        g.mode = Mode.EXCEL
        g.setcell(0, 0, "=1=1")
        cl = g.cells[0][0]
        assert cl.sval == "TRUE"
        assert cl.val == 1.0

    def test_sval_cleared_on_text_change(self):
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, '=IF(1=1, "yes", "no")')
        assert g.cells[0][0].sval == "yes"
        g.setcell(0, 0, "=1+2")
        cl = g.cells[0][0]
        assert cl.sval is None
        assert cl.val == 3.0

    def test_sval_cleared_when_result_becomes_numeric(self):
        # IF where condition cell changes such that branch swaps from str to int
        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, "1")
        g.setcell(1, 0, '=IF(A1=1, "yes", 99)')
        assert g.cells[1][0].sval == "yes"
        g.setcell(0, 0, "2")
        cl = g.cells[1][0]
        assert cl.sval is None
        assert cl.val == 99.0

    def test_fmtcell_renders_sval(self):
        from gridcalc.tui import fmtcell

        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.setcell(0, 0, '="hi"')
        rendered = fmtcell(g.cells[0][0], 8)
        assert "hi" in rendered


class TestConditionalsEvaluateOnlyTheSelectedBranch:
    """Excel evaluates only the branch a conditional selects. Evaluating both
    made `=IF(A1=0, "n/a", B1/A1)` -- the standard guard against dividing by
    zero -- report the very error it exists to prevent."""

    @staticmethod
    def _grid():
        # These functions live in the xlsx library, which `Grid()` does not
        # load until a mode is applied; `make_excel_grid` only sets the mode.
        g = make_excel_grid()
        g._apply_mode_libs()
        return g

    def test_if_skips_erroring_false_branch(self):
        g = self._grid()
        g.setcell(0, 0, "=IF(1=1,10,1/0)")
        assert g.cells[0][0].val == 10.0
        assert g.cells[0][0].err is None

    def test_if_skips_erroring_true_branch(self):
        g = self._grid()
        g.setcell(0, 0, "=IF(1=2,1/0,20)")
        assert g.cells[0][0].val == 20.0
        assert g.cells[0][0].err is None

    def test_if_guards_division_by_zero(self):
        g = self._grid()
        g.setcell(0, 0, "0")
        g.setcell(1, 0, "5")
        g.setcell(2, 0, '=IF(A1=0,"n/a",B1/A1)')
        assert g.cells[2][0].sval == "n/a"

    def test_if_still_propagates_an_error_in_the_condition(self):
        g = self._grid()
        g.setcell(0, 0, "=IF(1/0,1,2)")
        assert g.cells[0][0].err.value == "#DIV/0!"

    def test_if_two_argument_form_unchanged(self):
        g = self._grid()
        g.setcell(0, 0, "=IF(1=1,5)")
        g.setcell(0, 1, "=IF(1=2,5)")
        assert g.cells[0][0].val == 5.0
        assert g.cells[0][1].val == 0.0

    def test_iferror_skips_fallback_when_value_is_fine(self):
        g = self._grid()
        g.setcell(0, 0, "=IFERROR(5,1/0)")
        assert g.cells[0][0].val == 5.0
        assert g.cells[0][0].err is None

    def test_iferror_still_catches(self):
        g = self._grid()
        g.setcell(0, 0, "=IFERROR(1/0,99)")
        assert g.cells[0][0].val == 99.0

    def test_ifna_skips_fallback_when_value_is_fine(self):
        g = self._grid()
        g.setcell(0, 0, "=IFNA(4,1/0)")
        assert g.cells[0][0].val == 4.0
        assert g.cells[0][0].err is None

    def test_ifs_skips_unmatched_branches(self):
        g = self._grid()
        g.setcell(0, 0, "=IFS(1=2,1/0,1=1,42)")
        assert g.cells[0][0].val == 42.0
        assert g.cells[0][0].err is None

    def test_switch_skips_unmatched_results(self):
        g = self._grid()
        g.setcell(0, 0, "=SWITCH(2,1,1/0,2,77)")
        assert g.cells[0][0].val == 77.0
        assert g.cells[0][0].err is None

    def test_switch_default_branch(self):
        g = self._grid()
        g.setcell(0, 0, "=SWITCH(9,1,2,55)")
        assert g.cells[0][0].val == 55.0

    def test_choose_skips_unselected_arguments(self):
        g = self._grid()
        g.setcell(0, 0, "=CHOOSE(2,1/0,88)")
        assert g.cells[0][0].val == 88.0
        assert g.cells[0][0].err is None

    def test_choose_out_of_range(self):
        g = self._grid()
        g.setcell(0, 0, "=CHOOSE(5,1,2)")
        assert g.cells[0][0].err.value == "#VALUE!"

    def test_untaken_branch_is_still_a_dependency(self):
        """Laziness changes evaluation, not the dependency graph: the branch
        not taken is still recalculated when the condition flips to it."""
        g = self._grid()
        g.setcell(0, 0, "1")  # A1 condition source
        g.setcell(0, 1, "50")  # A2, read only by the false branch
        g.setcell(1, 0, "=IF(A1=1,10,A2)")
        assert g.cells[1][0].val == 10.0
        g.setcell(0, 0, "0")
        assert g.cells[1][0].val == 50.0
        g.setcell(0, 1, "60")
        assert g.cells[1][0].val == 60.0


class TestEmptyCellComparisons:
    """An empty cell takes the type of what it is compared against and that
    type's zero. It reaches the evaluator as `None`, which compares with
    nothing: ordering two empty cells raised a TypeError that surfaced as a
    bare NaN with no error set, and `=A1=0` answered FALSE."""

    @staticmethod
    def _grid():
        g = make_excel_grid()
        g._apply_mode_libs()
        g.setcell(5, 0, "7")  # F1
        g.setcell(5, 1, "txt")  # F2
        return g

    def _val(self, formula):
        g = self._grid()
        g.setcell(3, 0, formula)
        c = g.cells[3][0]
        assert c.err is None, f"{formula} -> {c.err}"
        return c.sval

    @pytest.mark.parametrize(
        "formula,expected",
        [
            # A1 and A2 are both empty.
            ("=A1=A2", "TRUE"),
            ("=A1<>A2", "FALSE"),
            ("=A1<A2", "FALSE"),
            ("=A1>A2", "FALSE"),
            ("=A1<=A2", "TRUE"),
            ("=A1>=A2", "TRUE"),
            # Against a number, an empty cell reads as 0 -- as it already did
            # in arithmetic.
            ("=A1=0", "TRUE"),
            ("=A1<1", "TRUE"),
            ("=A1>-1", "TRUE"),
            ("=A1<F1", "TRUE"),
            # Against text, as the empty string.
            ('=A1=""', "TRUE"),
            ('=A1<>""', "FALSE"),
            ("=A1=F2", "FALSE"),
            ("=A1<F2", "TRUE"),
            # Against a boolean, as FALSE.
            ("=A1=FALSE", "TRUE"),
            ("=A1=TRUE", "FALSE"),
        ],
    )
    def test_empty_cell_comparison(self, formula, expected):
        assert self._val(formula) == expected

    def test_ordering_two_empties_sets_no_error(self):
        """The old failure was silent: a NaN value with `err` unset, which
        reads as a number rather than as a refusal."""
        g = self._grid()
        g.setcell(3, 0, "=A1<A2")
        assert g.cells[3][0].err is None
        assert not math.isnan(g.cells[3][0].val)


class TestErrorsPropagateThroughReferences:
    """A cell holding an error reads as that error, not as the NaN standing in
    for the value it does not have.

    The engine's cell reader returned `cl.val` and never looked at `cl.err`, so
    the code was dropped at the reference boundary: `=1-A1` over a `#NAME?`
    produced an untyped NaN that rendered as the string `ERROR`, and every
    function that reports on an error could only see a number.
    """

    @staticmethod
    def _grid():
        g = make_excel_grid()
        g._apply_mode_libs()
        g.setcell(0, 0, "=NOSUCHFN(1)")  # A1 -> #NAME?
        g.setcell(0, 1, "=1/0")  # A2 -> #DIV/0!
        g.setcell(0, 2, "=NA()")  # A3 -> #N/A
        return g

    def _err(self, formula):
        g = self._grid()
        g.setcell(3, 0, formula)
        return g.cells[3][0].err

    def _text(self, formula):
        g = self._grid()
        g.setcell(3, 0, formula)
        return cell_text(g.cells[3][0])

    @pytest.mark.parametrize(
        "formula,expected",
        [
            ("=1 - A1", ExcelError.NAME),
            ("=A1 + 0", ExcelError.NAME),
            ("=A1 * 2", ExcelError.NAME),
            ("=-A1", ExcelError.NAME),
            ('=A2 & "x"', ExcelError.DIV0),
            ("=A2 = 1", ExcelError.DIV0),
            # Through an aggregate over a range, and through a second hop.
            ("=SUM(A1:A3)", ExcelError.NAME),
            ("=AVERAGE(A2:A2)", ExcelError.DIV0),
            ("=MAX(A2:A2)", ExcelError.DIV0),
        ],
    )
    def test_error_reaches_the_dependent_cell(self, formula, expected):
        assert self._err(formula) is expected

    def test_the_error_code_survives_two_hops(self):
        g = self._grid()
        g.setcell(3, 0, "=A2 + 1")
        g.setcell(3, 1, "=D1 + 1")
        assert g.cells[3][1].err is ExcelError.DIV0

    @pytest.mark.parametrize(
        "formula,expected",
        [
            # The reporters exist to describe an error; they must see it.
            ("=ERROR.TYPE(A1)", "5"),
            ("=ERROR.TYPE(A2)", "2"),
            ("=ERROR.TYPE(A3)", "7"),
            ("=TYPE(A2)", "16"),
            ("=ISNA(A3)", "TRUE"),
            ("=ISNA(A2)", "FALSE"),
            ("=IFNA(A3, 42)", "42"),
            ("=IFERROR(A2, 42)", "42"),
            ("=ISERROR(A2)", "TRUE"),
            ("=ISERR(A2)", "TRUE"),
            # Excel's IS-predicates answer FALSE for an error, not the error.
            ("=ISBLANK(A2)", "FALSE"),
            ("=ISNUMBER(A2)", "FALSE"),
            ("=ISTEXT(A2)", "FALSE"),
            ("=ISLOGICAL(A2)", "FALSE"),
        ],
    )
    def test_error_reporting_functions(self, formula, expected):
        assert self._text(formula) == expected

    def test_a_spilled_reference_reads_its_error(self):
        """`A1#` reads through the same gap as a bare reference did."""
        g = self._grid()
        g.setcell(3, 0, "=A1#")
        assert g.cells[3][0].err is ExcelError.NAME


class TestCountFamilyIgnoresCellErrors:
    """Excel's COUNT family ignores error values inside a reference where
    every other aggregate propagates them. COUNTA counts the error cell."""

    @staticmethod
    def _grid():
        g = make_excel_grid()
        g._apply_mode_libs()
        g.setcell(0, 0, "1")
        g.setcell(0, 1, "=1/0")
        g.setcell(0, 2, "3")
        return g

    @pytest.mark.parametrize(
        "formula,expected",
        [
            ("=COUNT(A1:A3)", "2"),
            ("=COUNTA(A1:A3)", "3"),
            ("=COUNTBLANK(A1:A3)", "0"),
            ('=COUNTIF(A1:A3, ">0")', "2"),
            ('=COUNTIFS(A1:A3, ">0")', "2"),
            # Unchanged: everything else still propagates.
            ("=SUM(A1:A3)", "#DIV/0!"),
            ("=AVERAGE(A1:A3)", "#DIV/0!"),
            ('=SUMIF(A1:A3, ">0")', "#DIV/0!"),
        ],
    )
    def test_count_over_a_range_holding_an_error(self, formula, expected):
        g = self._grid()
        g.setcell(3, 0, formula)
        assert cell_text(g.cells[3][0]) == expected

    def test_a_scalar_error_argument_still_short_circuits(self):
        """Only the range read tolerates errors. `=COUNT(A2)` names the
        errored cell itself, which is an error argument, not a range."""
        g = self._grid()
        g.setcell(3, 0, "=COUNT(A2)")
        assert g.cells[3][0].err is ExcelError.DIV0


class TestOverwriteClearsTheStaleError:
    """A literal replacing a formula does not inherit its error.

    `_setcell_no_recalc` reset every other result field and left `err`, which
    was invisible while nothing read it -- and became a poison pill the moment
    references started reporting errors.
    """

    def test_literal_over_a_circular_formula(self):
        g = make_excel_grid()
        g._apply_mode_libs()
        g.setcell(0, 0, "=B1")
        g.setcell(1, 0, "=A1")
        assert g.cells[1][0].err is ExcelError.CIRC
        g.setcell(1, 0, "42")
        assert g.cells[1][0].err is None
        assert g.cells[0][0].val == 42.0

    def test_label_over_an_errored_formula(self):
        g = make_excel_grid()
        g._apply_mode_libs()
        g.setcell(0, 0, "=1/0")
        g.setcell(0, 1, "=ISERROR(A1)")
        assert g.cells[0][1].sval == "TRUE"
        g.setcell(0, 0, "hello")
        assert g.cells[0][0].err is None
        assert g.cells[0][1].sval == "FALSE"


class TestMetadataFormulasTrackTheirReference:
    """`ISFORMULA` reports a cell's *kind*, so its answer changes when that
    cell is edited. It was classed address-only alongside `ROW`, whose answer
    cannot, so its argument never entered the dependency graph and the result
    kept its old value until something forced a full recalc."""

    @staticmethod
    def _grid():
        g = make_excel_grid()
        g._apply_mode_libs()
        return g

    def test_literal_to_formula(self):
        g = self._grid()
        g.setcell(0, 0, "5")
        g.setcell(1, 0, "=ISFORMULA(A1)")
        assert g.cells[1][0].val == 0.0
        g.setcell(0, 0, "=1+1")
        assert g.cells[1][0].val == 1.0

    def test_formula_to_literal(self):
        g = self._grid()
        g.setcell(0, 0, "=1+1")
        g.setcell(1, 0, "=ISFORMULA(A1)")
        assert g.cells[1][0].val == 1.0
        g.setcell(0, 0, "9")
        assert g.cells[1][0].val == 0.0

    def test_formula_to_empty(self):
        g = self._grid()
        g.setcell(0, 0, "=1+1")
        g.setcell(1, 0, "=ISFORMULA(A1)")
        assert g.cells[1][0].val == 1.0
        g.setcell(0, 0, "")
        assert g.cells[1][0].val == 0.0

    def test_formulatext_tracks_its_reference(self):
        g = self._grid()
        g.setcell(0, 0, "=1+1")
        g.setcell(1, 0, "=FORMULATEXT(A1)")
        assert g.cells[1][0].sval == "=1+1"
        g.setcell(0, 0, "=2+2")
        assert g.cells[1][0].sval == "=2+2"

    def test_positional_functions_stay_address_only(self):
        """`ROW` and `ISREF` answer from the reference's shape, not the cell's
        contents, so editing the cell must not make them dependents."""
        from gridcalc.formula import parse
        from gridcalc.formula.deps import extract_refs

        assert extract_refs(parse("ROW(A1)")) == set()
        assert extract_refs(parse("ROWS(A1:B10)")) == set()
        assert extract_refs(parse("ISREF(A1)")) == set()
        assert extract_refs(parse("ISFORMULA(A1)")) == {(None, 0, 0)}
