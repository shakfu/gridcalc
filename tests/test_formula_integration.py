"""Integration tests for the formula evaluator wired into Grid.recalc()."""

import math

from gridcalc.engine import Grid, Mode, NamedRange


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
        assert g.mode == Mode.LEGACY
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
        assert g.validate_for_mode(Mode.LEGACY) == []

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
