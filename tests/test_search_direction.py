from gridcalc.engine import Grid
from gridcalc.tui import _search_grid, search_next


def test_forward_search_across_same_row():
    g = Grid()
    g.setcell(0, 0, "hit")
    g.setcell(1, 0, "hit")
    g.setcell(2, 0, "hit")
    matches = _search_grid(g, "hit")
    assert matches == [(0, 0), (1, 0), (2, 0)]
    g.cc, g.cr = 0, 0
    search_next(g, matches, forward=True)
    assert (g.cc, g.cr) == (1, 0)
    search_next(g, matches, forward=True)
    assert (g.cc, g.cr) == (2, 0)
    search_next(g, matches, forward=True)
    assert (g.cc, g.cr) == (0, 0)


def test_backward_search_across_same_row():
    g = Grid()
    g.setcell(0, 0, "hit")
    g.setcell(1, 0, "hit")
    g.setcell(2, 0, "hit")
    matches = _search_grid(g, "hit")
    g.cc, g.cr = 2, 0
    search_next(g, matches, forward=False)
    assert (g.cc, g.cr) == (1, 0)
    search_next(g, matches, forward=False)
    assert (g.cc, g.cr) == (0, 0)
    search_next(g, matches, forward=False)
    assert (g.cc, g.cr) == (2, 0)


def test_forward_search_row_major_order():
    g = Grid()
    g.setcell(0, 0, "hit")
    g.setcell(0, 1, "hit")
    g.setcell(1, 0, "hit")
    g.setcell(1, 1, "hit")
    matches = _search_grid(g, "hit")
    # sorted by (row, col): A1, B1, A2, B2
    assert matches == [(0, 0), (1, 0), (0, 1), (1, 1)]
    g.cc, g.cr = 0, 0
    search_next(g, matches, forward=True)
    assert (g.cc, g.cr) == (1, 0)
    search_next(g, matches, forward=True)
    assert (g.cc, g.cr) == (0, 1)
    search_next(g, matches, forward=True)
    assert (g.cc, g.cr) == (1, 1)


def test_search_no_matches_is_noop():
    g = Grid()
    g.setcell(0, 0, "hit")
    matches = _search_grid(g, "miss")
    assert matches == []
    g.cc, g.cr = 0, 0
    search_next(g, matches, forward=True)
    assert (g.cc, g.cr) == (0, 0)


def test_search_from_unanchored_cell():
    g = Grid()
    g.setcell(0, 0, "hit")
    g.setcell(2, 2, "hit")
    matches = _search_grid(g, "hit")
    g.cc, g.cr = 1, 1
    search_next(g, matches, forward=True)
    assert (g.cc, g.cr) == (2, 2)
    search_next(g, matches, forward=False)
    # backward from (2,2): first match strictly less than (2,2) row-major is (0,0)
    assert (g.cc, g.cr) == (0, 0)
