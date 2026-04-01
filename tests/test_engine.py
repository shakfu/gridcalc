import math

from pycalc.engine import (
    CW_DEFAULT,
    EMPTY,
    FORMULA,
    LABEL,
    MAXIN,
    NCOL,
    NROW,
    NUM,
    Cell,
    Grid,
    NamedRange,
    col_name,
    ref,
)


def make_grid():
    return Grid()


class TestExpr:
    def test_literal_int(self):
        g = make_grid()
        g.setcell(0, 0, "3")
        g.setcell(0, 1, "5")
        g.setcell(0, 2, "11")
        g.setcell(0, 3, "-13.5")

        g.setcell(1, 0, "=42")
        assert g.cells[1][0].val == 42.0

        g.setcell(1, 0, "=1.5")
        assert g.cells[1][0].val == 1.5

        g.setcell(1, 0, "=-123")
        assert g.cells[1][0].val == -123.0

        g.setcell(1, 0, "=(123)")
        assert g.cells[1][0].val == 123.0

    def test_cell_refs(self):
        g = make_grid()
        g.setcell(0, 0, "3")
        g.setcell(0, 1, "5")
        g.setcell(0, 2, "11")

        g.setcell(1, 0, "=A1")
        assert g.cells[1][0].val == 3.0

        g.setcell(1, 0, "=A2")
        assert g.cells[1][0].val == 5.0

        g.setcell(1, 0, "=A3")
        assert g.cells[1][0].val == 11.0

    def test_arithmetic(self):
        g = make_grid()
        g.setcell(0, 0, "3")
        g.setcell(0, 1, "5")
        g.setcell(0, 2, "11")
        g.setcell(0, 3, "-13.5")

        g.setcell(1, 0, "=A1*A2")
        assert g.cells[1][0].val == 15.0

        g.setcell(1, 0, "=A1*10/A2")
        assert g.cells[1][0].val == 6.0

        g.setcell(1, 0, "=A1+A2")
        assert g.cells[1][0].val == 8.0

        g.setcell(1, 0, "=A1+A2-A3")
        assert g.cells[1][0].val == -3.0

        g.setcell(1, 0, "=A1+A2*A3")
        assert g.cells[1][0].val == 58.0

        g.setcell(1, 0, "=(A1+A2)*A3")
        assert g.cells[1][0].val == 88.0

        g.setcell(1, 0, "=A1**2")
        assert g.cells[1][0].val == 9.0

    def test_functions(self):
        g = make_grid()
        g.setcell(0, 0, "3")
        g.setcell(0, 1, "5")
        g.setcell(0, 2, "11")
        g.setcell(0, 3, "-13.5")

        g.setcell(1, 0, "=ABS(A1)")
        assert g.cells[1][0].val == 3.0

        g.setcell(1, 0, "=ABS(A4)")
        assert g.cells[1][0].val == 13.5

        g.setcell(1, 0, "=INT(A4)")
        assert g.cells[1][0].val == -13.0

        g.setcell(1, 0, "=INT(ABS(A4))")
        assert g.cells[1][0].val == 13.0

        g.setcell(1, 0, "=SQRT(A3+A2)")
        assert g.cells[1][0].val == 4.0

        g.setcell(1, 0, "=max(A1, A2, A3)")
        assert g.cells[1][0].val == 11.0

        g.setcell(1, 0, "=min(A1, A2)")
        assert g.cells[1][0].val == 3.0


class TestRecalc:
    def test_chain(self):
        g = make_grid()
        g.setcell(0, 0, "5")
        g.setcell(0, 1, "7")
        g.setcell(0, 2, "11")
        g.setcell(0, 3, "=A1+A2+A3")
        assert g.cells[0][3].val == 23.0

    def test_chain_update(self):
        g = make_grid()
        g.setcell(0, 0, "5")
        g.setcell(0, 1, "=A1+5")
        g.setcell(0, 2, "=A2+A1")
        g.setcell(0, 3, "=A1+A2+A3")
        assert g.cells[0][3].val == 5.0 + 10.0 + 15.0

        g.setcell(0, 0, "7")
        assert g.cells[0][3].val == 7.0 + 12.0 + 19.0


class TestVec:
    def test_named_range_sum(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.names = [NamedRange("vals", 0, 0, 0, 2)]
        g.recalc()

        g.setcell(1, 0, "=SUM(vals)")
        assert g.cells[1][0].val == 60.0

    def test_named_range_avg(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.names = [NamedRange("vals", 0, 0, 0, 2)]
        g.recalc()

        g.setcell(1, 0, "=AVG(vals)")
        assert g.cells[1][0].val == 20.0

    def test_named_range_min_max(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.names = [NamedRange("vals", 0, 0, 0, 2)]
        g.recalc()

        g.setcell(1, 0, "=MIN(vals)")
        assert g.cells[1][0].val == 10.0
        g.setcell(1, 0, "=MAX(vals)")
        assert g.cells[1][0].val == 30.0

    def test_named_range_count(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.names = [NamedRange("vals", 0, 0, 0, 2)]
        g.recalc()

        g.setcell(1, 0, "=COUNT(vals)")
        assert g.cells[1][0].val == 3.0

    def test_vec_arithmetic(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.names = [NamedRange("vals", 0, 0, 0, 2)]
        g.recalc()

        g.setcell(1, 0, "=vals * 2")
        assert g.cells[1][0].arr is not None
        assert len(g.cells[1][0].arr) == 3
        assert g.cells[1][0].arr[0] == 20.0
        assert g.cells[1][0].arr[1] == 40.0
        assert g.cells[1][0].arr[2] == 60.0

    def test_vec_sum_expr(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.names = [NamedRange("vals", 0, 0, 0, 2)]
        g.recalc()

        g.setcell(1, 0, "=SUM(vals * 2)")
        assert g.cells[1][0].val == 120.0

    def test_two_named_ranges(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.setcell(1, 0, "100")
        g.setcell(1, 1, "200")
        g.setcell(1, 2, "300")
        g.names = [
            NamedRange("vals", 0, 0, 0, 2),
            NamedRange("costs", 1, 0, 1, 2),
        ]
        g.recalc()

        g.setcell(2, 0, "=SUM(vals + costs)")
        assert g.cells[2][0].val == 660.0

    def test_list_comprehension(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.names = [NamedRange("vals", 0, 0, 0, 2)]
        g.recalc()

        g.setcell(2, 0, "=sum([x**2 for x in vals])")
        assert g.cells[2][0].val == 1400.0


class TestMath:
    def test_pi(self):
        g = make_grid()
        g.setcell(0, 0, "=pi")
        assert abs(g.cells[0][0].val - 3.14159) < 1e-4

    def test_sin(self):
        g = make_grid()
        g.setcell(0, 0, "=sin(pi/2)")
        assert abs(g.cells[0][0].val - 1.0) < 1e-5

    def test_cos(self):
        g = make_grid()
        g.setcell(0, 0, "=cos(0)")
        assert abs(g.cells[0][0].val - 1.0) < 1e-5

    def test_log(self):
        g = make_grid()
        g.setcell(0, 0, "=log(e)")
        assert abs(g.cells[0][0].val - 1.0) < 1e-5

    def test_exp(self):
        g = make_grid()
        g.setcell(0, 0, "=exp(0)")
        assert abs(g.cells[0][0].val - 1.0) < 1e-5

    def test_floor(self):
        g = make_grid()
        g.setcell(0, 0, "=floor(3.7)")
        assert g.cells[0][0].val == 3.0

    def test_ceil(self):
        g = make_grid()
        g.setcell(0, 0, "=ceil(3.2)")
        assert g.cells[0][0].val == 4.0


class TestRangeSyntax:
    def test_sum_range(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")

        g.setcell(1, 0, "=SUM(A1:A3)")
        assert g.cells[1][0].val == 60.0

    def test_min_max_range(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")

        g.setcell(1, 0, "=MIN(A1:A3)")
        assert g.cells[1][0].val == 10.0
        g.setcell(1, 0, "=MAX(A1:A3)")
        assert g.cells[1][0].val == 30.0

    def test_avg_range(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")

        g.setcell(1, 0, "=AVG(A1:A3)")
        assert g.cells[1][0].val == 20.0

    def test_range_expr(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")

        g.setcell(1, 0, "=SUM(A1:A3 * 2)")
        assert g.cells[1][0].val == 120.0

    def test_2d_range(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(1, 0, "100")
        g.setcell(1, 1, "200")

        g.setcell(2, 0, "=SUM(A1:B2)")
        assert g.cells[2][0].val == 330.0

    def test_column_range(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.setcell(1, 0, "5")
        g.setcell(1, 1, "15")
        g.setcell(1, 2, "25")

        g.setcell(2, 0, "=SUM(B1:B3)")
        assert g.cells[2][0].val == 45.0

    def test_combined_ranges(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.setcell(1, 0, "5")
        g.setcell(1, 1, "15")
        g.setcell(1, 2, "25")

        g.setcell(2, 0, "=SUM(A1:A3) + SUM(B1:B3)")
        assert g.cells[2][0].val == 105.0

    def test_reverse_range(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")

        g.setcell(2, 0, "=SUM(A3:A1)")
        assert g.cells[2][0].val == 60.0


class TestRef:
    def test_basic(self):
        r = ref("A1")
        assert r == (2, 0, 0)

    def test_z(self):
        r = ref("Z50")
        assert r == (3, 25, 49)

    def test_double_letter(self):
        r = ref("AA10")
        assert r == (4, 26, 9)

    def test_az(self):
        r = ref("AZ99")
        assert r == (4, 51, 98)

    def test_ba(self):
        r = ref("BA1")
        assert r == (3, 52, 0)


class TestCol:
    def test_single_letter(self):
        assert col_name(0) == "A"
        assert col_name(25) == "Z"

    def test_double_letter(self):
        assert col_name(26) == "AA"
        assert col_name(51) == "AZ"
        assert col_name(52) == "BA"


class TestJsonLoad:
    def test_basic(self, tmp_path):
        g = make_grid()
        f = tmp_path / "basic.json"
        f.write_text('{"cells": [[10, 20, 30], ["hello", "world", "=A1+B1"]]}')
        assert g.jsonload(str(f)) == 0
        assert g.cells[0][0].type == NUM and g.cells[0][0].val == 10.0
        assert g.cells[1][0].type == NUM and g.cells[1][0].val == 20.0
        assert g.cells[2][0].type == NUM and g.cells[2][0].val == 30.0
        assert g.cells[0][1].type == LABEL
        assert g.cells[0][1].text == "hello"
        assert g.cells[2][1].type == FORMULA
        assert g.cells[2][1].val == 30.0

    def test_nulls(self, tmp_path):
        g = make_grid()
        f = tmp_path / "empty.json"
        f.write_text('{"cells": [[1, null, 3], [null, 5, null]]}')
        assert g.jsonload(str(f)) == 0
        assert g.cells[0][0].val == 1.0
        assert g.cells[1][0].type == EMPTY
        assert g.cells[2][0].val == 3.0
        assert g.cells[0][1].type == EMPTY
        assert g.cells[1][1].val == 5.0

    def test_code(self, tmp_path):
        g = make_grid()
        f = tmp_path / "code.json"
        f.write_text('{"code": "def double(x): return x * 2", "cells": [[5, "=double(A1)"]]}')
        assert g.jsonload(str(f)) == 0
        assert g.code == "def double(x): return x * 2"
        assert g.cells[0][0].val == 5.0
        assert g.cells[1][0].type == FORMULA
        assert g.cells[1][0].val == 10.0

    def test_names(self, tmp_path):
        g = make_grid()
        f = tmp_path / "names.json"
        f.write_text('{"names": {"revenue": "A1:A3"}, "cells": [[10], [20], [30]]}')
        assert g.jsonload(str(f)) == 0
        assert len(g.names) == 1
        assert g.names[0].name == "revenue"
        assert g.names[0].c1 == 0 and g.names[0].r1 == 0
        assert g.names[0].c2 == 0 and g.names[0].r2 == 2
        assert g.cells[0][0].val == 10.0

    def test_nonexistent(self, tmp_path):
        g = make_grid()
        assert g.jsonload(str(tmp_path / "nonexistent.json")) == -1


class TestJsonSave:
    def test_basic(self, tmp_path):
        g = make_grid()
        g.setcell(0, 0, "100")
        g.setcell(1, 0, "200")
        g.setcell(2, 0, "=A1+B1")
        g.setcell(0, 1, "hello")
        g.setcell(1, 1, "has,comma")

        f = tmp_path / "save.json"
        assert g.jsonsave(str(f)) == 0

        g2 = make_grid()
        assert g2.jsonload(str(f)) == 0
        assert g2.cells[0][0].val == 100.0
        assert g2.cells[1][0].val == 200.0
        assert g2.cells[2][0].type == FORMULA
        assert g2.cells[2][0].val == 300.0
        assert g2.cells[0][1].text == "hello"
        assert g2.cells[1][1].text == "has,comma"


class TestJsonRoundtrip:
    def test_quotes(self, tmp_path):
        g = make_grid()
        g.setcell(0, 0, 'say "hello"')
        g.setcell(1, 0, "normal")
        g.setcell(0, 1, "42.5")

        f = tmp_path / "rt.json"
        assert g.jsonsave(str(f)) == 0
        g2 = make_grid()
        assert g2.jsonload(str(f)) == 0
        assert g2.cells[0][0].text == 'say "hello"'
        assert g2.cells[1][0].text == "normal"
        assert g2.cells[0][1].val == 42.5

    def test_full(self, tmp_path):
        g = make_grid()
        g.code = "def triple(x): return x * 3"
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.setcell(1, 0, "=triple(A1)")
        g.names = [NamedRange("revenue", 0, 0, 0, 2)]

        f = tmp_path / "full.json"
        assert g.jsonsave(str(f)) == 0
        g2 = make_grid()
        assert g2.jsonload(str(f)) == 0

        assert "def triple" in g2.code
        assert len(g2.names) == 1
        assert g2.names[0].name == "revenue"
        assert g2.names[0].c1 == 0 and g2.names[0].r1 == 0
        assert g2.names[0].c2 == 0 and g2.names[0].r2 == 2
        assert g2.cells[0][0].val == 10.0
        assert g2.cells[0][1].val == 20.0
        assert g2.cells[0][2].val == 30.0
        assert g2.cells[1][0].type == FORMULA
        assert g2.cells[1][0].val == 30.0


class TestSwap:
    def test_swap_rows(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.setcell(1, 0, "100")
        g.setcell(1, 1, "200")
        g.setcell(1, 2, "300")

        g.swaprow(0, 1)
        assert g.cells[0][0].val == 20.0
        assert g.cells[0][1].val == 10.0
        assert g.cells[1][0].val == 200.0
        assert g.cells[1][1].val == 100.0
        assert g.cells[0][2].val == 30.0

        g.swaprow(0, 1)
        assert g.cells[0][0].val == 10.0
        assert g.cells[0][1].val == 20.0

    def test_swap_cols(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.setcell(1, 0, "100")
        g.setcell(1, 1, "200")
        g.setcell(1, 2, "300")

        g.swapcol(0, 1)
        assert g.cells[0][0].val == 100.0
        assert g.cells[1][0].val == 10.0
        assert g.cells[0][1].val == 200.0
        assert g.cells[1][1].val == 20.0

        g.swapcol(0, 1)
        assert g.cells[0][0].val == 10.0
        assert g.cells[1][0].val == 100.0


class TestFixrefs:
    def test_swap_row_refs(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(1, 0, "=A1+A2")
        assert g.cells[1][0].val == 30.0

        g.swaprow(0, 1)
        g.recalc()
        assert g.cells[1][1].val == 30.0
        assert g.cells[1][1].text == "=A2+A1"
        assert g.cells[0][0].val == 20.0
        assert g.cells[0][1].val == 10.0

        g.swaprow(0, 1)
        g.recalc()
        assert g.cells[1][0].val == 30.0
        assert g.cells[1][0].text == "=A1+A2"

    def test_swap_col_refs(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "100")
        g.setcell(2, 0, "=A1+B1")
        assert g.cells[2][0].val == 110.0

        g.swapcol(0, 1)
        g.recalc()
        assert g.cells[0][0].val == 100.0
        assert g.cells[1][0].val == 10.0
        assert g.cells[2][0].text == "=B1+A1"
        assert g.cells[2][0].val == 110.0

        g.swapcol(0, 1)
        g.recalc()
        assert g.cells[2][0].text == "=A1+B1"
        assert g.cells[2][0].val == 110.0

    def test_swap_non_adjacent(self):
        g = make_grid()
        g.setcell(0, 0, "1")
        g.setcell(0, 1, "2")
        g.setcell(0, 2, "3")
        g.setcell(1, 0, "=A3")
        assert g.cells[1][0].val == 3.0
        g.swaprow(0, 1)
        g.recalc()
        assert g.cells[1][1].text == "=A3"
        assert g.cells[1][1].val == 3.0

    def test_double_swap(self):
        g = make_grid()
        g.setcell(0, 0, "1")
        g.setcell(0, 1, "2")
        g.setcell(0, 2, "3")
        g.setcell(1, 0, "=A1")
        g.swaprow(0, 1)
        g.swaprow(1, 2)
        g.recalc()
        assert g.cells[0][2].val == 1.0
        assert g.cells[1][2].val == 1.0
        assert g.cells[1][2].text == "=A3"

    def test_swap_row_formula_update(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "=A1+A2")
        g.swaprow(0, 1)
        g.recalc()
        assert g.cells[0][2].text == "=A2+A1"
        assert g.cells[0][2].val == 30.0


class TestInsertDelete:
    def test_insert_row(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.setcell(1, 0, "=A2")
        assert g.cells[1][0].val == 20.0

        g.insertrow(1)
        g.recalc()
        assert g.cells[0][0].val == 10.0
        assert g.cells[0][1].type == EMPTY
        assert g.cells[0][2].val == 20.0
        assert g.cells[0][3].val == 30.0
        assert g.cells[1][0].text == "=A3"
        assert g.cells[1][0].val == 20.0

    def test_delete_row(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.setcell(1, 0, "=A2")

        g.insertrow(1)
        g.recalc()
        g.deleterow(1)
        g.recalc()
        assert g.cells[0][0].val == 10.0
        assert g.cells[0][1].val == 20.0
        assert g.cells[0][2].val == 30.0
        assert g.cells[1][0].text == "=A2"
        assert g.cells[1][0].val == 20.0

    def test_insert_col(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "20")
        g.setcell(2, 0, "=A1+B1")
        assert g.cells[2][0].val == 30.0

        g.insertcol(1)
        g.recalc()
        assert g.cells[0][0].val == 10.0
        assert g.cells[1][0].type == EMPTY
        assert g.cells[2][0].val == 20.0
        assert g.cells[3][0].text == "=A1+C1"
        assert g.cells[3][0].val == 30.0

    def test_delete_col(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "20")
        g.setcell(2, 0, "=A1+B1")

        g.insertcol(1)
        g.recalc()
        g.deletecol(1)
        g.recalc()
        assert g.cells[0][0].val == 10.0
        assert g.cells[1][0].val == 20.0
        assert g.cells[2][0].text == "=A1+B1"
        assert g.cells[2][0].val == 30.0

    def test_delete_row_shifts_ref(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.setcell(1, 0, "=A3")
        assert g.cells[1][0].val == 30.0

        g.deleterow(1)
        g.recalc()
        assert g.cells[0][0].val == 10.0
        assert g.cells[0][1].val == 30.0
        assert g.cells[1][0].text == "=A2"
        assert g.cells[1][0].val == 30.0

    def test_insert_row_at_zero(self):
        g = make_grid()
        g.setcell(0, 0, "5")
        g.setcell(0, 1, "10")
        g.setcell(1, 1, "=A1")
        assert g.cells[1][1].val == 5.0

        g.insertrow(0)
        g.recalc()
        assert g.cells[0][0].type == EMPTY
        assert g.cells[0][1].val == 5.0
        assert g.cells[0][2].val == 10.0
        assert g.cells[1][2].text == "=A2"
        assert g.cells[1][2].val == 5.0

    def test_delete_col_shifts_ref(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "20")
        g.setcell(2, 0, "30")
        g.setcell(3, 0, "=C1")
        assert g.cells[3][0].val == 30.0

        g.deletecol(1)
        g.recalc()
        assert g.cells[0][0].val == 10.0
        assert g.cells[1][0].val == 30.0
        assert g.cells[2][0].text == "=B1"
        assert g.cells[2][0].val == 30.0

    def test_double_insert(self):
        g = make_grid()
        g.setcell(0, 0, "42")
        g.setcell(1, 0, "=A1")
        g.insertrow(0)
        g.insertrow(0)
        g.recalc()
        assert g.cells[0][2].val == 42.0
        assert g.cells[1][2].text == "=A3"
        assert g.cells[1][2].val == 42.0


class TestReplicate:
    def test_number(self):
        g = make_grid()
        g.setcell(0, 0, "42")
        g.replicatecell(0, 0, 1, 0)
        g.recalc()
        assert g.cells[1][0].type == NUM
        assert g.cells[1][0].val == 42.0

    def test_label(self):
        g = make_grid()
        g.setcell(0, 0, "hello")
        g.replicatecell(0, 0, 1, 0)
        assert g.cells[1][0].type == LABEL
        assert g.cells[1][0].text == "hello"

    def test_formula_row(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(1, 0, "=A1")
        g.replicatecell(1, 0, 1, 1)
        g.recalc()
        assert g.cells[1][1].text == "=A2"
        assert g.cells[1][1].val == 20.0

    def test_formula_col(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "20")
        g.setcell(0, 1, "=A1")
        g.replicatecell(0, 1, 1, 1)
        g.recalc()
        assert g.cells[1][1].text == "=B1"
        assert g.cells[1][1].val == 20.0

    def test_absolute_ref(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "=$A$1")
        g.replicatecell(1, 0, 1, 1)
        g.recalc()
        assert g.cells[1][1].text == "=$A$1"
        assert g.cells[1][1].val == 10.0

    def test_abs_col(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(1, 0, "=$A1")
        g.replicatecell(1, 0, 1, 1)
        g.recalc()
        assert g.cells[1][1].text == "=$A2"
        assert g.cells[1][1].val == 20.0

    def test_abs_row(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(1, 0, "20")
        g.setcell(0, 1, "=A$1")
        g.replicatecell(0, 1, 1, 1)
        g.recalc()
        assert g.cells[1][1].text == "=B$1"
        assert g.cells[1][1].val == 20.0

    def test_multi_row(self):
        g = make_grid()
        g.setcell(0, 0, "1")
        g.setcell(0, 1, "2")
        g.setcell(0, 2, "3")
        g.setcell(0, 3, "4")
        g.setcell(1, 0, "=A1")
        for r in range(1, 4):
            g.replicatecell(1, 0, 1, r)
        g.recalc()
        assert g.cells[1][1].text == "=A2"
        assert g.cells[1][1].val == 2.0
        assert g.cells[1][2].text == "=A3"
        assert g.cells[1][2].val == 3.0
        assert g.cells[1][3].text == "=A4"
        assert g.cells[1][3].val == 4.0

    def test_empty_overwrites(self):
        g = make_grid()
        g.setcell(1, 0, "999")
        g.replicatecell(0, 0, 1, 0)
        assert g.cells[1][0].type == EMPTY

    def test_abs_formula_eval(self):
        g = make_grid()
        g.setcell(0, 0, "7")
        g.setcell(1, 0, "=$A$1*2")
        g.recalc()
        assert g.cells[1][0].val == 14.0

    def test_block_replicate(self):
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "=A1+A2")
        assert g.cells[0][2].val == 30.0
        sc1, sr1, sc2, sr2 = 0, 0, 0, 2
        tc1, tr1 = 1, 0
        sw = sc2 - sc1 + 1
        sh = sr2 - sr1 + 1
        for r in range(sh):
            for c in range(sw):
                g.replicatecell(sc1 + c, sr1 + r, tc1 + c, tr1 + r)
        g.recalc()
        assert g.cells[1][0].val == 10.0
        assert g.cells[1][1].val == 20.0
        assert g.cells[1][2].text == "=B1+B2"
        assert g.cells[1][2].val == 30.0


class TestFmtcell:
    def test_null_cell(self):
        g = make_grid()
        assert g.fmtcell(None, 8) == "        "
        assert len(g.fmtcell(None, 8)) == 8

    def test_empty_cell(self):
        g = make_grid()
        cl = Cell()
        assert g.fmtcell(cl, 6) == "      "

    def test_label(self):
        g = make_grid()
        cl = Cell()
        cl.type = LABEL
        cl.text = "hello"
        assert g.fmtcell(cl, 8) == "hello   "

    def test_label_quote(self):
        g = make_grid()
        cl = Cell()
        cl.type = LABEL
        cl.text = '"quoted'
        assert g.fmtcell(cl, 8) == "quoted  "

    def test_label_truncated(self):
        g = make_grid()
        cl = Cell()
        cl.type = LABEL
        cl.text = "longstring"
        result = g.fmtcell(cl, 4)
        assert len(result) == 4
        assert result[:4] == "long"

    def test_error(self):
        g = make_grid()
        cl = Cell()
        cl.type = FORMULA
        cl.val = float("nan")
        assert g.fmtcell(cl, 8) == "   ERROR"

    def test_integer(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 42.0
        assert g.fmtcell(cl, 8) == "      42"

    def test_float(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 3.14159
        result = g.fmtcell(cl, 10)
        assert len(result) == 10
        assert "3.14" in result

    def test_dollar(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 99.5
        cl.fmt = "$"
        result = g.fmtcell(cl, 10)
        assert "99.50" in result

    def test_percent(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 0.25
        cl.fmt = "%"
        result = g.fmtcell(cl, 10)
        assert "25.00%" in result

    def test_integer_format(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 3.7
        cl.fmt = "I"
        result = g.fmtcell(cl, 8)
        assert "3" in result
        assert "." not in result

    def test_bar(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 5.0
        cl.fmt = "*"
        assert g.fmtcell(cl, 8) == "*****   "

    def test_bar_clamped(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 100.0
        cl.fmt = "*"
        assert g.fmtcell(cl, 6) == "******"

    def test_array(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 3.0
        cl.arr = [3.0, 6.0, 9.0]
        result = g.fmtcell(cl, 10)
        assert "3[3]" in result

    def test_global_dollar(self):
        g = make_grid()
        g.fmt = "$"
        cl = Cell()
        cl.type = NUM
        cl.val = 7.0
        result = g.fmtcell(cl, 10)
        assert "7.00" in result

    def test_left_align(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 42.0
        cl.fmt = "L"
        result = g.fmtcell(cl, 8)
        assert result[:2] == "42"
        assert result[7] == " "

    def test_right_align(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 42.0
        cl.fmt = "R"
        assert g.fmtcell(cl, 8) == "      42"

    def test_negative(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = -123.0
        result = g.fmtcell(cl, 8)
        assert "-123" in result

    def test_zero(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 0.0
        result = g.fmtcell(cl, 8)
        assert "0" in result


class TestFmtrange:
    def test_single_cell(self):
        g = make_grid()
        assert g.fmtrange(0, 0, 0, 0) == "A1"

    def test_range(self):
        g = make_grid()
        assert g.fmtrange(0, 0, 2, 4) == "A1...C5"

    def test_large_coord(self):
        g = make_grid()
        assert g.fmtrange(25, 99, 25, 99) == "Z100"

    def test_double_letter(self):
        g = make_grid()
        assert g.fmtrange(26, 0, 26, 0) == "AA1"


class TestErrorConditions:
    def test_undefined_var(self):
        g = make_grid()
        g.setcell(0, 0, "=undefined_var")
        assert math.isnan(g.cells[0][0].val)

    def test_syntax_error(self):
        g = make_grid()
        g.setcell(0, 0, "=1 +* 2")
        assert math.isnan(g.cells[0][0].val)

    def test_division_by_zero(self):
        g = make_grid()
        g.setcell(0, 0, "=1/0")
        assert math.isinf(g.cells[0][0].val) or math.isnan(g.cells[0][0].val)

    def test_out_of_bounds(self):
        g = make_grid()
        assert g.cell(-1, 0) is None
        assert g.cell(0, -1) is None
        assert g.cell(NCOL, 0) is None
        assert g.cell(0, NROW) is None

    def test_setcell_out_of_bounds(self):
        g = make_grid()
        g.setcell(NCOL, 0, "42")
        g.setcell(0, NROW, "42")

    def test_empty_clears(self):
        g = make_grid()
        g.setcell(0, 0, "100")
        assert g.cells[0][0].type == NUM
        g.setcell(0, 0, "")
        assert g.cells[0][0].type == EMPTY


class TestCellclearCellcopy:
    def test_clear_empty(self):
        a = Cell()
        a.clear()
        assert a.type == EMPTY
        assert a.arr is None

    def test_copy_array(self):
        a = Cell()
        a.type = NUM
        a.val = 1.0
        a.arr = [10.0, 20.0, 30.0]

        b = Cell()
        b.copy_from(a)
        assert b.type == NUM
        assert b.val == 1.0
        assert len(b.arr) == 3
        assert b.arr is not a.arr
        assert b.arr[0] == 10.0
        assert b.arr[1] == 20.0
        assert b.arr[2] == 30.0

        a.arr[0] = 99.0
        assert b.arr[0] == 10.0

    def test_clear_frees(self):
        a = Cell()
        a.type = NUM
        a.val = 1.0
        a.arr = [10.0, 20.0, 30.0]
        a.clear()
        assert a.arr is None
        assert a.type == EMPTY

    def test_copy_scalar(self):
        c = Cell()
        c.type = NUM
        c.val = 42.0

        d = Cell()
        d.copy_from(c)
        assert d.val == 42.0
        assert d.arr is None


class TestBoundary:
    def test_max_col(self):
        g = make_grid()
        g.setcell(NCOL - 1, 0, "99")
        assert g.cells[NCOL - 1][0].type == NUM
        assert g.cells[NCOL - 1][0].val == 99.0

    def test_max_row(self):
        g = make_grid()
        g.setcell(0, NROW - 1, "77")
        assert g.cells[0][NROW - 1].type == NUM
        assert g.cells[0][NROW - 1].val == 77.0

    def test_max_corner(self):
        g = make_grid()
        g.setcell(NCOL - 1, NROW - 1, "=1+1")
        assert g.cells[NCOL - 1][NROW - 1].type == FORMULA
        assert g.cells[NCOL - 1][NROW - 1].val == 2.0

    def test_formula_ref_max_col(self):
        g = make_grid()
        g.setcell(NCOL - 1, 0, "99")
        ref_formula = f"={col_name(NCOL - 1)}1"
        g.setcell(0, 0, ref_formula)
        assert g.cells[0][0].val == 99.0

    def test_long_label(self):
        g = make_grid()
        longtext = "x" * (MAXIN - 1)
        g.setcell(0, 0, longtext)
        assert g.cells[0][0].type == LABEL

    def test_insert_at_boundary(self):
        g = make_grid()
        g.setcell(0, NROW - 1, "end")
        g.insertrow(NROW - 1)
        assert g.cells[0][NROW - 1].type == EMPTY

    def test_insertcol_at_boundary(self):
        g = make_grid()
        g.setcell(NCOL - 1, 0, "end")
        g.insertcol(NCOL - 1)
        assert g.cells[NCOL - 1][0].type == EMPTY

    def test_clear_at_boundary(self):
        g = make_grid()
        g.setcell(NCOL - 1, NROW - 1, "42")
        g.setcell(NCOL - 1, NROW - 1, "")
        assert g.cells[NCOL - 1][NROW - 1].type == EMPTY


class TestBoldRoundtrip:
    def test_bold(self, tmp_path):
        g = make_grid()
        g.setcell(0, 0, "hello")
        g.cells[0][0].bold = 1
        g.setcell(1, 0, "42")
        g.cells[1][0].bold = 1
        g.setcell(2, 0, "=A1")
        g.setcell(0, 1, "normal")

        f = tmp_path / "bold.json"
        assert g.jsonsave(str(f)) == 0
        g2 = make_grid()
        assert g2.jsonload(str(f)) == 0

        assert g2.cells[0][0].bold == 1
        assert g2.cells[0][0].text == "hello"
        assert g2.cells[1][0].bold == 1
        assert g2.cells[1][0].val == 42.0
        assert g2.cells[2][0].bold == 0
        assert g2.cells[0][1].bold == 0


class TestFmtstr:
    def test_comma_thousands(self):
        g = make_grid()
        g.cw = CW_DEFAULT
        cl = Cell()
        cl.type = NUM
        cl.val = 1234567.0
        cl.fmtstr = ",.0f"
        result = g.fmtcell(cl, 12)
        assert "1,234,567" in result

    def test_comma_shorthand(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 1234567.0
        cl.fmtstr = ","
        result = g.fmtcell(cl, 12)
        assert "1,234,567" in result
        assert "." not in result

    def test_comma_decimal(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 1234.5
        cl.fmtstr = ",.2f"
        result = g.fmtcell(cl, 12)
        assert "1,234.50" in result

    def test_percentage(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 0.157
        cl.fmtstr = ".1%"
        result = g.fmtcell(cl, 12)
        assert "15.7%" in result

    def test_fixed_decimal(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 3.14159
        cl.fmtstr = ".4f"
        result = g.fmtcell(cl, 12)
        assert "3.1416" in result

    def test_no_fmtstr(self):
        g = make_grid()
        cl = Cell()
        cl.type = NUM
        cl.val = 42.0
        result = g.fmtcell(cl, 8)
        assert "42" in result


class TestFmtstrRoundtrip:
    def test_roundtrip(self, tmp_path):
        g = make_grid()
        g.setcell(0, 0, "1234567")
        g.cells[0][0].fmtstr = ",.0f"
        g.setcell(1, 0, "0.05")
        g.cells[1][0].fmtstr = ".1%"
        g.setcell(2, 0, "plain")

        f = tmp_path / "fmtstr.json"
        assert g.jsonsave(str(f)) == 0
        g2 = make_grid()
        assert g2.jsonload(str(f)) == 0

        assert g2.cells[0][0].fmtstr == ",.0f"
        assert g2.cells[1][0].fmtstr == ".1%"
        assert g2.cells[2][0].fmtstr == ""


class TestStyleRoundtrip:
    def test_styles(self, tmp_path):
        g = make_grid()
        g.setcell(0, 0, "bold")
        g.cells[0][0].bold = 1
        g.setcell(1, 0, "underline")
        g.cells[1][0].underline = 1
        g.setcell(2, 0, "italic")
        g.cells[2][0].italic = 1
        g.setcell(3, 0, "all three")
        g.cells[3][0].bold = 1
        g.cells[3][0].underline = 1
        g.cells[3][0].italic = 1
        g.setcell(0, 1, "plain")

        f = tmp_path / "style.json"
        assert g.jsonsave(str(f)) == 0
        g2 = make_grid()
        assert g2.jsonload(str(f)) == 0

        assert g2.cells[0][0].bold == 1
        assert g2.cells[0][0].underline == 0
        assert g2.cells[0][0].italic == 0
        assert g2.cells[1][0].underline == 1
        assert g2.cells[1][0].bold == 0
        assert g2.cells[2][0].italic == 1
        assert g2.cells[2][0].bold == 0
        assert g2.cells[3][0].bold == 1
        assert g2.cells[3][0].underline == 1
        assert g2.cells[3][0].italic == 1
        assert g2.cells[0][1].bold == 0
        assert g2.cells[0][1].underline == 0
        assert g2.cells[0][1].italic == 0


class TestFmtRoundtrip:
    def test_fmt(self, tmp_path):
        g = make_grid()
        g.setcell(0, 0, "100.5")
        g.cells[0][0].fmt = "$"
        g.setcell(1, 0, "0.15")
        g.cells[1][0].fmt = "%"
        g.setcell(2, 0, "3.7")
        g.cells[2][0].fmt = "I"
        g.setcell(3, 0, "plain")
        g.setcell(0, 1, "42")
        g.cells[0][1].fmt = "$"
        g.cells[0][1].bold = 1

        f = tmp_path / "fmt.json"
        assert g.jsonsave(str(f)) == 0
        g2 = make_grid()
        assert g2.jsonload(str(f)) == 0

        assert g2.cells[0][0].fmt == "$"
        assert g2.cells[1][0].fmt == "%"
        assert g2.cells[2][0].fmt == "I"
        assert g2.cells[3][0].fmt == ""
        assert g2.cells[0][1].fmt == "$"
        assert g2.cells[0][1].bold == 1


class TestCircularReference:
    def test_direct_self_ref(self):
        g = make_grid()
        g.setcell(0, 0, "=A1")
        assert math.isnan(g.cells[0][0].val)
        assert (0, 0) in g._circular

    def test_mutual_ref(self):
        g = make_grid()
        g.setcell(0, 0, "=B1")
        g.setcell(1, 0, "=A1")
        assert math.isnan(g.cells[0][0].val)
        assert math.isnan(g.cells[1][0].val)
        assert (0, 0) in g._circular or (1, 0) in g._circular

    def test_chain_cycle(self):
        g = make_grid()
        g.setcell(0, 0, "=C1")
        g.setcell(1, 0, "=A1")
        g.setcell(2, 0, "=B1")
        assert math.isnan(g.cells[0][0].val)
        assert math.isnan(g.cells[1][0].val)
        assert math.isnan(g.cells[2][0].val)
        assert len(g._circular) > 0

    def test_no_false_positive(self):
        g = make_grid()
        g.setcell(0, 0, "5")
        g.setcell(0, 1, "=A1+1")
        g.setcell(0, 2, "=A2+1")
        assert g.cells[0][1].val == 6.0
        assert g.cells[0][2].val == 7.0
        assert len(g._circular) == 0

    def test_cleared_after_fix(self):
        g = make_grid()
        g.setcell(0, 0, "=B1")
        g.setcell(1, 0, "=A1")
        assert len(g._circular) > 0
        # Break the cycle
        g.setcell(0, 0, "10")
        assert g.cells[1][0].val == 10.0
        assert len(g._circular) == 0

    def test_self_ref_plus_constant(self):
        g = make_grid()
        g.setcell(0, 0, "=A1+1")
        assert math.isnan(g.cells[0][0].val)
        assert (0, 0) in g._circular

    def test_partial_cycle(self):
        """Only cells in the cycle are marked, not innocent bystanders."""
        g = make_grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "=A1")  # not circular
        g.setcell(1, 0, "=B1")  # self-referential
        assert g.cells[0][1].val == 10.0
        assert math.isnan(g.cells[1][0].val)
        assert (0, 1) not in g._circular
        assert (1, 0) in g._circular
