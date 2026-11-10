"""`_recalc_topo` reuses its order for a repeated dirty set; a graph change discards it."""

from gridcalc.engine import Grid, Mode
from gridcalc.undo import UndoManager


def _grid() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcell(0, 0, "1")  # A1
    g.setcell(1, 0, "=A1*2")  # B1
    g.setcell(2, 0, "=B1+1")  # C1
    g.setcell(0, 0, "2")
    return g


def _val(g: Grid, c: int, r: int) -> object:
    return g._cell_lookup_value(c, r)


def test_a_repeated_edit_reuses_the_order() -> None:
    g = _grid()
    assert g._topo_cache  # the edit of A1 stored its order
    g.setcell(0, 0, "5")
    assert (_val(g, 1, 0), _val(g, 2, 0)) == (10.0, 11.0)


def test_a_new_reader_of_the_edited_cell_recalculates() -> None:
    g = _grid()
    g.setcell(3, 0, "=A1+100")  # D1 joins A1's closure
    g.setcell(0, 0, "7")
    assert (_val(g, 2, 0), _val(g, 3, 0)) == (15.0, 107.0)


def test_a_reader_that_stops_reading_is_left_alone() -> None:
    g = _grid()
    g.setcell(2, 0, "=1+1")  # C1 no longer reads B1
    g.setcell(0, 0, "7")
    assert (_val(g, 1, 0), _val(g, 2, 0)) == (14.0, 2.0)


def test_a_formula_without_references_in_the_edited_cell_runs() -> None:
    g = _grid()
    g.setcell(0, 0, "=1+2")  # A1 now a formula with no edge
    assert (_val(g, 0, 0), _val(g, 2, 0)) == (3.0, 7.0)
    g.setcell(0, 0, "4")
    assert _val(g, 2, 0) == 9.0


def test_a_row_insert_moves_the_cells_the_order_names() -> None:
    g = _grid()
    g.cr = 0
    g.insertrow(0)
    g.setcell(0, 1, "3")  # A1 is now A2
    assert (_val(g, 1, 1), _val(g, 2, 1)) == (6.0, 7.0)
    g.setcell(0, 0, "9")  # the old A1 position holds nothing that is read
    assert _val(g, 2, 1) == 7.0


def test_undo_of_a_formula_edit_restores_its_readers() -> None:
    g, u = _grid(), UndoManager()
    u.save_cell(g, 2, 0)
    g.setcell(2, 0, "=1")
    assert u.undo(g)
    g.setcell(0, 0, "6")
    assert _val(g, 2, 0) == 13.0


def test_a_cycle_found_once_is_still_reported_from_the_cache() -> None:
    g = _grid()
    g.setcell(0, 1, "=B2")  # A2
    g.setcell(1, 1, "=A2+A1")  # B2, a cycle with A2 that reads A1
    for v in ("3", "4"):
        g.setcell(0, 0, v)
        assert (1, 1) in g._circular
