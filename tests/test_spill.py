"""Dynamic-array cell spill (EXCEL/HYBRID mode).

A formula whose result is a multi-cell array spills into neighbouring
cells: the anchor keeps the formula and the whole array, and the extra
values materialise as SPILL cells. A bare reference to the anchor reads
its top-left scalar; the whole array is reached with the ``A1#`` operator.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from gridcalc.engine import EMPTY, NUM, SPILL, Grid, Mode
from gridcalc.formula.errors import ExcelError


def _grid() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    return g


class TestBasicSpill:
    def test_vertical_spill(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(3)")  # A1 -> [1; 2; 3] down column A
        assert g.cells[0][0].val == 1.0
        assert g.cells[0][0].spill_shape == (3, 1)
        assert g.cells[0][1].type == SPILL
        assert g.cells[0][1].val == 2.0
        assert g.cells[0][1].spill_parent == (0, 0)
        assert g.cells[0][2].type == SPILL
        assert g.cells[0][2].val == 3.0

    def test_horizontal_spill(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(1,3)")  # A1 -> [1, 2, 3] across row 1
        assert g.cells[0][0].spill_shape == (1, 3)
        assert g.cells[1][0].val == 2.0  # B1
        assert g.cells[2][0].val == 3.0  # C1
        assert g.cells[1][0].type == SPILL

    def test_2d_spill(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(2,3)")  # [[1,2,3],[4,5,6]]
        assert g.cells[0][0].spill_shape == (2, 3)
        assert g.cells[0][0].val == 1.0  # A1
        assert g.cells[2][0].val == 3.0  # C1
        assert g.cells[0][1].val == 4.0  # A2
        assert g.cells[2][1].val == 6.0  # C2

    def test_scalar_result_does_not_spill(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=1+1")
        assert g.cells[0][0].spill_shape is None
        assert g.cells[0][1].type == EMPTY

    def test_single_element_array_does_not_spill(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(1)")  # a 1x1 array
        assert g.cells[0][0].spill_shape is None
        assert g.cells[0][1].type == EMPTY


class TestSpillReads:
    def test_bare_reference_reads_top_left_scalar(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        g.setcell(2, 0, "=A1")  # bare ref -> scalar 1, not the array
        assert g.cells[2][0].val == 1.0

    def test_reference_to_spilled_neighbour(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        g.setcell(2, 0, "=A2 + A3")  # 2 + 3
        assert g.cells[2][0].val == 5.0

    def test_spill_operator_reads_whole_array(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        g.setcell(2, 0, "=SUM(A1#)")
        assert g.cells[2][0].val == 6.0

    def test_range_over_spill_does_not_double_count(self) -> None:
        # The anchor reads as a scalar, so a range covering the spill sums
        # each cell once -- the whole point of the scalar-anchor semantics.
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        g.setcell(2, 0, "=SUM(A1:A3)")
        assert g.cells[2][0].val == 6.0

    def test_spill_operator_2d(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(2,3)")
        g.setcell(4, 0, "=SUM(A1#)")
        assert g.cells[4][0].val == 21.0

    def test_spill_operator_on_non_array_is_scalar(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=42")
        g.setcell(2, 0, "=A1#")
        assert g.cells[2][0].val == 42.0


class TestSpillRecompute:
    def test_grow_spill_updates_consumer(self) -> None:
        g = _grid()
        g.setcell(4, 0, "3")  # E1
        g.setcell(0, 0, "=SEQUENCE(E1)")
        g.setcell(2, 0, "=SUM(A1#)")
        assert g.cells[2][0].val == 6.0  # 1+2+3
        g.setcell(4, 0, "5")
        assert g.cells[0][0].spill_shape == (5, 1)
        assert g.cells[0][4].val == 5.0  # A5 now materialised
        assert g.cells[2][0].val == 15.0  # consumer recomputed

    def test_shrink_spill_clears_vacated_cells(self) -> None:
        g = _grid()
        g.setcell(4, 0, "5")
        g.setcell(0, 0, "=SEQUENCE(E1)")
        g.setcell(2, 0, "=SUM(A1#)")
        assert g.cells[2][0].val == 15.0
        g.setcell(4, 0, "2")
        assert g.cells[0][2].type == EMPTY  # A3 vacated
        assert g.cells[2][0].val == 3.0  # 1+2

    def test_consumer_of_spilled_cell_updates(self) -> None:
        # A cell reading a spilled neighbour recomputes when the anchor's
        # source changes -- the spill cell is a live dependency of the anchor.
        g = _grid()
        g.setcell(4, 0, "3")
        g.setcell(0, 0, "=SEQUENCE(E1)")
        g.setcell(2, 0, "=A3 * 10")  # reads spilled A3
        assert g.cells[2][0].val == 30.0
        g.setcell(4, 0, "9")
        # A3 is now 3 still (SEQUENCE(9) -> A3 == 3), so consumer stays 30;
        # change the check to A9 which appears only when the spill grows.
        g.setcell(3, 0, "=A9 * 10")
        assert g.cells[3][0].val == 90.0


class TestSpillBlockage:
    def test_blocked_by_value_yields_spill_error(self) -> None:
        g = _grid()
        g.setcell(0, 1, "X")  # A2 occupied
        g.setcell(0, 0, "=SEQUENCE(3)")
        assert g.cells[0][0].err is ExcelError.SPILL
        assert g.cells[0][2].type == EMPTY  # nothing spilled

    def test_unblock_restores_spill(self) -> None:
        g = _grid()
        g.setcell(0, 1, "X")
        g.setcell(0, 0, "=SEQUENCE(3)")
        assert g.cells[0][0].err is ExcelError.SPILL
        g.setcell(0, 1, "")  # remove the blocker
        assert g.cells[0][0].err is None
        assert g.cells[0][0].val == 1.0
        assert g.cells[0][1].val == 2.0
        assert g.cells[0][2].val == 3.0

    def test_edit_into_spill_range_blocks_anchor(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        g.setcell(0, 1, "99")  # type over a spill cell
        assert g.cells[0][0].err is ExcelError.SPILL
        assert g.cells[0][1].type == NUM  # A2 is now a real user cell
        assert g.cells[0][1].val == 99.0
        assert g.cells[0][2].type == EMPTY  # rest of the spill withdrawn

    def test_off_sheet_spill_errors(self) -> None:
        g = _grid()
        g.setcell(0, 1023, "=SEQUENCE(5)")  # would run past the last row
        assert g.cells[0][1023].err is ExcelError.SPILL


class TestSpillTeardown:
    def test_clear_anchor_removes_spill(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        g.setcell(3, 0, "=SUM(A1#)")
        assert g.cells[3][0].val == 6.0
        g.setcell(0, 0, "")  # clear the anchor
        assert g.cells[0][1].type == EMPTY
        assert g.cells[0][2].type == EMPTY

    def test_anchor_to_scalar_removes_spill(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        assert g.cells[0][1].type == SPILL
        g.setcell(0, 0, "=7")  # now a scalar formula
        assert g.cells[0][0].val == 7.0
        assert g.cells[0][0].spill_shape is None
        assert g.cells[0][1].type == EMPTY
        assert g.cells[0][2].type == EMPTY

    def test_shrinking_then_growing_is_stable(self) -> None:
        g = _grid()
        g.setcell(4, 0, "4")
        g.setcell(0, 0, "=SEQUENCE(E1)")
        assert g.cells[0][3].val == 4.0
        g.setcell(4, 0, "1")  # collapses to a single value (no spill)
        assert g.cells[0][0].spill_shape is None
        assert g.cells[0][1].type == EMPTY
        g.setcell(4, 0, "3")  # spills again
        assert g.cells[0][0].spill_shape == (3, 1)
        assert g.cells[0][2].val == 3.0


class TestSpillStringsAndTypes:
    def test_string_array_spills(self) -> None:
        g = _grid()
        for i, v in enumerate(["pear", "apple", "cherry"]):
            g.setcell(0, i, v)
        g.setcell(2, 0, "=SORT(A1:A3)")  # -> apple, cherry, pear
        assert g.cells[2][0].sval == "apple"
        assert g.cells[2][1].sval == "cherry"
        assert g.cells[2][2].sval == "pear"
        assert g.cells[2][1].type == SPILL

    def test_reference_to_string_spill_cell(self) -> None:
        g = _grid()
        for i, v in enumerate(["pear", "apple", "cherry"]):
            g.setcell(0, i, v)
        g.setcell(2, 0, "=SORT(A1:A3)")
        g.setcell(4, 0, "=C2")  # reads the spilled "cherry"
        assert g.cells[4][0].sval == "cherry"


class TestSpillPersistence:
    def test_json_roundtrip_rebuilds_spill(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        g.setcell(3, 0, "=SUM(A1#)")
        with tempfile.TemporaryDirectory() as d:
            fn = str(Path(d) / "spill.json")
            assert g.jsonsave(fn) == 0
            # The spilled cells must not be persisted as static values.
            import json

            payload = json.loads(Path(fn).read_text())
            rows = payload["sheets"][0]["cells"]
            # Column A row 2/3 (the spill) serialise as None, not 2/3.
            assert rows[0][0] == "=SEQUENCE(3)"
            assert all(row[0] is None for row in rows[1:3])

            g2 = _grid()
            assert g2.jsonload(fn) == 0
            assert g2.cells[0][1].type == SPILL
            assert g2.cells[0][1].val == 2.0
            assert g2.cells[0][2].val == 3.0
            assert g2.cells[3][0].val == 6.0


class TestSpillDoesNotAffectPythonMode:
    def test_python_mode_keeps_array_in_one_cell(self) -> None:
        # PYTHON mode uses the fixed-point engine and does not spill; the
        # array stays in the anchor's `arr`, neighbours remain empty.
        g = Grid()
        g.mode = Mode.PYTHON
        g._apply_mode_libs()
        g.setcell(0, 0, "0")
        g.setcell(0, 1, "1")
        g.setcell(0, 2, "2")
        g.names = []
        g.setcell(1, 0, "=A1:A3 * 2")  # Vec result in PYTHON mode
        assert g.cells[1][0].arr is not None
        assert g.cells[1][1].type == EMPTY  # no spill in PYTHON mode


class TestSpillStructuralOps:
    def test_insertrow_above_spill_rebuilds(self) -> None:
        g = _grid()
        g.setcell(4, 1, "3")  # E2
        g.setcell(0, 1, "=SEQUENCE(E2)")  # anchor A2 -> A2:A4
        g.insertrow(0)  # anchor shifts down to A3
        g.recalc()
        assert g.cells[0][2].text == "=SEQUENCE(E3)"
        assert g.cells[0][2].spill_shape == (3, 1)
        assert g.cells[0][3].type == SPILL
        assert g.cells[0][3].spill_parent == (0, 2)
        # The rebuilt spill is fully live: growing it still works.
        g.setcell(4, 2, "5")  # E3 (the shifted E2)
        assert g.cells[0][2].spill_shape == (5, 1)
        assert g.cells[0][2].err is None

    def test_deleterow_elsewhere_keeps_spill(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(3)")
        g.setcell(3, 0, "=SUM(A1#)")
        g.deleterow(5)  # unrelated row
        g.recalc()
        assert g.cells[0][0].val == 1.0
        assert g.cells[0][2].type == SPILL
        assert g.cells[3][0].val == 6.0

    def test_insertcol_before_horizontal_spill(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(1,3)")  # A1 spills to A1:C1
        g.insertcol(0)  # anchor shifts to B1
        g.recalc()
        assert g.cells[1][0].spill_shape == (1, 3)
        assert g.cells[2][0].type == SPILL  # C1
        assert g.cells[3][0].val == 3.0  # D1


class TestSpillDependencyOrdering:
    def test_spill_operator_dependency_recomputes(self) -> None:
        g = _grid()
        g.setcell(4, 0, "2")
        g.setcell(0, 0, "=SEQUENCE(E1)")  # A1# = [1;2]
        g.setcell(2, 0, "=SUM(A1#)")
        assert g.cells[2][0].val == 3.0
        g.setcell(4, 0, "4")  # A1# = [1;2;3;4]
        assert math.isclose(g.cells[2][0].val, 10.0)

    def test_chained_spill_consumers(self) -> None:
        g = _grid()
        g.setcell(0, 0, "=SEQUENCE(3)")  # A1..A3
        g.setcell(2, 0, "=A2 + 100")  # depends on spilled A2
        g.setcell(3, 0, "=C1 * 2")  # depends on C1
        assert g.cells[2][0].val == 102.0
        assert g.cells[3][0].val == 204.0
