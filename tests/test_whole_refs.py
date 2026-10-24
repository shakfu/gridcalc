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
        ("=SUM(XFD:XFD)", 1, 0, "=SUM(#REF!)"),  # XFD is the last column
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


# -- Excel's grid: 16384 x 1048576 ------------------------------------------


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=COUNTBLANK(B:B)", float(NROW - 2)),
        ('=COUNTIF(B:B,"")', float(NROW - 2)),
        ('=COUNTIF(B:B,"<>5")', float(NROW - 1)),
        ('=COUNTIF(B:B,">0")', 2.0),
        ('=COUNTIFS(B:B,"",C:C,"")', float(NROW - 2)),
        ("=INDEX(B:B,5000)", None),
        ("=INDEX(B:B,2)", 6.0),
        ("=MATCH(6,B:B,0)", 2.0),
        ("=SUMPRODUCT(B:B,B:B)", 61.0),
        ("=SUM(B:XFD)", 11.0),
    ],
)
def test_a_trimmed_range_answers_as_the_whole_column(formula, value) -> None:
    g = _excel()
    g.setcell(1, 0, "5")
    g.setcell(1, 1, "6")
    g.setcell(0, 9, formula)
    g.recalc()
    cl = g.cells[0][9]
    if value is None:
        assert cl.val in (0.0, None) and cl.err is None
    else:
        assert cl.val == value


def test_whole_column_lookups_find_every_row() -> None:
    g = _excel()
    rows = 2000
    g.setcells_bulk([(0, r, str(r)) for r in range(rows)] + [(1, r, f"k{r}") for r in range(rows)])
    g.setcells_bulk([(2, r, f"=VLOOKUP({r},A:B,2,0)") for r in range(rows)])
    assert g.cells[2][rows - 1].sval == f"k{rows - 1}"


def test_a_large_range_is_read_to_the_used_extent() -> None:
    from gridcalc.formula import Env, evaluate, parse

    env = Env(cell_value=lambda c, r, s=None: 1.0 if (c, r) == (1, 9) else None, builtins={})
    env.used_extent = lambda: (3, 9)
    vec = evaluate(parse("A:B"), env)
    assert (len(vec.data), vec.cols, vec.full, vec.tail) == (20, 2, (NROW, 2), 2 * NROW - 20)
    small = evaluate(parse("A1:B300"), env)  # under TRIM_CELLS: read whole
    assert (len(small.data), small.full) == (600, None)


def test_three_letter_columns() -> None:
    g = _excel()
    g.setcell(NCOL - 1, 0, "4")  # XFD1
    g.setcell(702, 0, "3")  # AAA1
    g.setcell(0, 0, "=XFD1+AAA1")
    assert g.cells[0][0].val == 7.0
    assert adjust_refs("=AAZ1", 1, 0) == "=ABA1"
    assert adjust_refs("=XFD1", 1, 0) == "=#REF!"


def test_python_mode_reads_a_large_range_to_the_used_extent() -> None:
    from gridcalc.engine import _expand_ranges

    assert _expand_ranges("sum(A1:A1048576)", lambda: (0, 2)) == "sum(Vec([A1,A2,A3]))"
    assert _expand_ranges("sum(A1:A3)", lambda: (0, 0)) == "sum(Vec([A1,A2,A3]))"  # small
    g = Grid()
    g.setcell(0, 0, "2")
    g.setcell(0, 1, "3")
    g.setcell(1, 0, "=sum(A1:A1048576)")
    g.recalc()
    assert g.cells[1][0].val == 5.0
