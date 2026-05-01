"""Tests for swaprow/swapcol reference rewriting via _fixrefs.

Semantics: after a row/column swap, every formula's *value* must be
preserved. The physical cell move and the reference rewrite together
achieve this.
"""

from gridcalc.engine import Grid


def test_swaprow_preserves_value_inside_swap():
    g = Grid()
    g.setcell(0, 0, "10")
    g.setcell(0, 1, "20")
    g.setcell(1, 0, "=A1")
    g.setcell(1, 1, "=A2")
    g.swaprow(0, 1)
    g.recalc()
    # Both formulas should still compute their original values.
    # B1 was =A1 computing 10; it has physically moved to row 1 (B2 visually).
    # Its text rewrote to =A2, A2 now holds 10. Value preserved.
    assert g.cells[1][1].val == 10.0
    # B2 was =A2 computing 20; moved to row 0 (B1 visually). Text => =A1, A1=20.
    assert g.cells[1][0].val == 20.0


def test_swaprow_preserves_value_outside_swap():
    g = Grid()
    g.setcell(0, 0, "10")
    g.setcell(0, 1, "20")
    g.setcell(1, 2, "=A1*2+A2")  # formula at row 2, references rows 0 and 1
    assert g.cells[1][2].val == 40.0
    g.swaprow(0, 1)
    g.recalc()
    # Outside-swap formula still computes 40.
    assert g.cells[1][2].val == 40.0


def test_swaprow_complex_inside_formula():
    g = Grid()
    g.setcell(0, 0, "10")
    g.setcell(0, 1, "20")
    g.setcell(1, 0, "=A1*2+A2")  # at row 0, value = 40
    g.swaprow(0, 1)
    g.recalc()
    # Cell physically moved to row 1; value preserved.
    assert g.cells[1][1].val == 40.0


def test_swapcol_preserves_value():
    g = Grid()
    g.setcell(0, 0, "10")
    g.setcell(1, 0, "20")
    g.setcell(0, 1, "=A1+B1")  # value = 30
    g.swapcol(0, 1)
    g.recalc()
    # A1 column moved to B1 column and vice versa. Cell at (0,1) physically
    # moved to (1,1). Its formula referenced A1+B1; both adjusted.
    assert g.cells[1][1].val == 30.0


def test_swaprow_with_absolute_refs():
    g = Grid()
    g.setcell(0, 0, "10")
    g.setcell(0, 1, "20")
    g.setcell(1, 0, "=$A$1+$A$2")  # value = 30
    g.swaprow(0, 1)
    g.recalc()
    # Absolute refs adjust on swap so the value is preserved.
    assert g.cells[1][1].val == 30.0


def test_swaprow_unaffected_rows_unchanged():
    g = Grid()
    g.setcell(0, 0, "10")
    g.setcell(0, 1, "20")
    g.setcell(0, 5, "99")
    g.setcell(1, 5, "=A6 * 2")  # value = 198
    g.swaprow(0, 1)
    g.recalc()
    # A6 was untouched; formula stays correct.
    assert g.cells[1][5].val == 198.0
    assert g.cells[0][5].val == 99.0
