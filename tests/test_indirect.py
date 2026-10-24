"""INDIRECT, and volatile formulas reading cells the graph cannot see."""

import pytest

from gridcalc.engine import NROW, Grid, Mode, NamedRange
from gridcalc.formula.errors import ExcelError


def _grid() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk([(0, 0, "5"), (0, 1, "=C1*2"), (2, 0, "3"), (1, 0, '="A"&2')])
    g.add_sheet("Two")
    g.set_active("Two")
    g.setcell(1, 2, "42")
    g.set_active(0)
    g.names.append(NamedRange("Rng", 0, 0, 0, 1))
    return g


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ('=INDIRECT("A1")', 5.0),
        ("=INDIRECT(B1)", 6.0),
        ('=SUM(INDIRECT("A1:A2"))', 11.0),
        ('=INDIRECT("Two!B3")', 42.0),
        ("=INDIRECT(\"'Two'!B3\")", 42.0),
        ('=SUM(INDIRECT("Rng"))', 11.0),
        ('=INDIRECT("R1C1",FALSE)', 5.0),
        ('=INDIRECT("R[-11]C[-4]",FALSE)', 6.0),  # from E13: A2
        ('=ROWS(INDIRECT("A:A"))', float(NROW)),
        ('=INDIRECT("1+2")', ExcelError.REF),
        ('=INDIRECT("Nope!A1")', ExcelError.REF),
        ('=INDIRECT("")', ExcelError.REF),
        ('=INDIRECT("E13")', ExcelError.CIRC),  # itself
    ],
)
def test_indirect(formula, value) -> None:
    g = _grid()
    g.setcell(4, 12, formula)
    cl = g.cells[4][12]
    assert (cl.err if isinstance(value, ExcelError) else cl.val) == value


def test_indirect_follows_edits_to_the_cell_it_names() -> None:
    g = _grid()
    g.setcell(4, 0, "=INDIRECT(B1)")
    g.setcell(2, 0, "100")
    assert g.cells[4][0].val == 200.0
    g.setcell(1, 0, '="A"&1')
    assert g.cells[4][0].val == 5.0


@pytest.mark.parametrize("first", [True, False])
def test_a_volatile_formula_reads_the_current_value(first) -> None:
    """The cell OFFSET names is not in the graph, so it may come later in
    the order; reading it runs it first."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    reader = (4, 0, "=OFFSET(A1,1,0)")
    rest = [(0, 0, "0"), (0, 1, "=C1*2"), (2, 0, "1")]
    g.setcells_bulk([reader, *rest] if first else [*rest, reader])
    for v in (10, 11, 12):
        g.setcell(2, 0, str(v))
        assert g.cells[4][0].val == g.cells[0][1].val == 2.0 * v


@pytest.mark.parametrize("order", range(6))
def test_a_cell_run_early_for_indirect_reads_current_inputs(order) -> None:
    import itertools

    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    cells = [(0, 0, "1"), (1, 0, "=A1+1"), (2, 0, "=B1*2"), (3, 0, '=INDIRECT("C1")')]
    first, *rest = cells
    g.setcells_bulk([first, *list(itertools.permutations(rest))[order]])
    g.setcell(0, 0, "5")
    assert [g.cells[c][0].val for c in (1, 2, 3)] == [6.0, 12.0, 12.0]


def test_a_cycle_through_indirect_is_circular() -> None:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcells_bulk([(0, 0, '=INDIRECT("B1")'), (1, 0, "=A1+1")])
    assert ExcelError.CIRC in (g.cells[0][0].err, g.cells[1][0].err)
