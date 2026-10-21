"""Whole-column (`B:B`) and whole-row (`1:1`) references."""

import pytest

from gridcalc.engine import NCOL, NROW, Grid, Mode, adjust_refs
from gridcalc.formula.lexer import COLRANGE, ROWRANGE, tokenize


def _excel() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    return g


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("=B:B", COLRANGE, (1, 1, False, False)),
        ("=$A:$C", COLRANGE, (0, 2, True, True)),
        ("=1:1", ROWRANGE, (0, 0, False, False)),
        ("=$2:5", ROWRANGE, (1, 4, True, False)),
    ],
)
def test_whole_references_lex_as_one_token(text, kind, value) -> None:
    tok = tokenize(text)[0]
    assert (tok.kind, tok.value) == (kind, value)


def test_a_cell_range_and_a_function_name_are_not_whole_references() -> None:
    kinds = [t.kind for t in tokenize("=SUM(A1:B2)+LOG10(2)")]
    assert COLRANGE not in kinds and ROWRANGE not in kinds


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=SUM(B:B)", 11.0),
        ("=SUM($B:$B)", 11.0),
        ("=SUM(C:B)", 11.0),
        ("=SUM(2:2)", 6.0),
        ("=SUM(Sheet1!B:B)", 11.0),
        ("=VLOOKUP(6,B:C,2,0)", "y"),
        ("=ROWS(B:B)", float(NROW)),
        ("=COLUMNS(1:1)", float(NCOL)),
    ],
)
def test_whole_references_cover_the_grid(formula, value) -> None:
    g = _excel()
    g.setcell(1, 0, "5")
    g.setcell(1, 1, "6")
    g.setcell(2, 1, "y")
    g.setcell(0, 9, formula)
    g.recalc()
    cl = g.cells[0][9]
    assert (cl.sval if isinstance(value, str) else cl.val) == value


def test_an_edit_anywhere_in_the_column_recalculates() -> None:
    g = _excel()
    g.setcell(0, 0, "=SUM(B:B)")
    g.recalc()
    g.setcell(1, NROW - 1, "7")
    g.recalc()
    assert g.cells[0][0].val == 7.0


@pytest.mark.parametrize(
    ("text", "dcol", "drow", "shifted"),
    [
        ("=SUM(B:B)+B1", 1, 1, "=SUM(C:C)+C2"),
        ("=SUM($B:C)", 1, 0, "=SUM($B:D)"),
        ("=SUM(1:1)", 1, 1, "=SUM(2:2)"),
        ("=SUM($1:$1)", 0, 3, "=SUM($1:$1)"),
        ("=SUM(Data!B:B)", 1, 0, "=SUM(Data!C:C)"),
        ('="B:B"&1', 1, 0, '="B:B"&1'),
        ("=SUM(IV:IV)", 1, 0, "=SUM(#REF!)"),  # IV is the last column
    ],
)
def test_copying_shifts_whole_references(text, dcol, drow, shifted) -> None:
    assert adjust_refs(text, dcol, drow, whole_refs=True) == shifted


def test_python_slices_are_not_whole_references() -> None:
    assert adjust_refs("=[1,2,3][1:2]", 0, 1) == "=[1,2,3][1:2]"
    g = Grid()
    g.mode = Mode.PYTHON
    g.setcell(0, 0, "=(lambda x:x)(4)")
    g.insertcol(0)
    assert g.cells[1][0].text == "=(lambda x:x)(4)"


def test_inserting_and_deleting_moves_whole_references() -> None:
    g = _excel()
    g.setcell(0, 0, "=SUM(C:C)")
    g.setcell(0, 1, "=SUM(C:D)")
    g.setcell(0, 4, "=SUM(3:4)")
    g.insertcol(1)
    g.insertrow(2)
    assert [g.cells[0][r].text for r in (0, 1, 5)] == ["=SUM(D:D)", "=SUM(D:E)", "=SUM(4:5)"]
    g.deletecol(3)
    assert [g.cells[0][r].text for r in (0, 1)] == ["=SUM(#REF!)", "=SUM(D:D)"]


def test_removing_a_sheet_breaks_its_whole_references() -> None:
    g = _excel()
    g.add_sheet("Data")
    g.setcell(0, 0, "=SUM(Data!B:B)")
    g.remove_sheet("Data")
    assert g.cells[0][0].text == "=SUM(#REF!)"
