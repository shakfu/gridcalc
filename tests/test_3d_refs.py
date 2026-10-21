"""3D references: `Jan:Mar!B2`, the same cells on a run of sheets."""

import pytest

from gridcalc.engine import Grid, Mode, adjust_refs
from gridcalc.formula.ast_nodes import RangeRef, Ref3D
from gridcalc.formula.errors import ExcelError
from gridcalc.formula.parser import parse


def _book() -> Grid:
    """Sum, Jan, Feb, Mar; B2 holds 10, 20, 30 on the months, B3 text."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.rename_sheet("Sheet1", "Sum")
    for i, name in enumerate(["Jan", "Feb", "Mar"], start=1):
        g.add_sheet(name)
        g.set_active(i)
        g.setcell(1, 1, str(10 * i))
        g.setcell(1, 2, "x")
    g.set_active(0)
    return g


def _value(g: Grid, formula: str) -> object:
    g.setcell(0, 9, formula)
    g.recalc()
    cl = g.cells[0][9]
    return cl.err if cl.err is not None else cl.val


@pytest.mark.parametrize(
    ("text", "first", "last"),
    [
        ("SUM(Jan:Mar!B2)", "Jan", "Mar"),
        ("SUM(Sheet1:Sheet3!B2:C3)", "Sheet1", "Sheet3"),
        ("SUM('Q1 a:Q4 b'!A1)", "Q1 a", "Q4 b"),
        ("SUM('Q1:Q4'!A1)", "Q1", "Q4"),
        ("SUM(Jan:Mar!B:B)", "Jan", "Mar"),
    ],
)
def test_a_sheet_span_parses_as_a_3d_reference(text, first, last) -> None:
    node = parse(text).args[0]
    assert isinstance(node, Ref3D) and (node.first, node.last) == (first, last)


def test_a_range_ending_on_another_sheet_is_not_a_span() -> None:
    # `A1:Sheet2!B5` is a range; a sheet named like a cell is quoted.
    with pytest.raises(Exception, match="cross-sheet"):
        parse("A1:Sheet2!B5")
    assert isinstance(parse("Sheet2!A1:Sheet2!B3"), RangeRef)


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=SUM(Jan:Mar!B2)", 60.0),
        ("=SUM(Mar:Jan!B2:B3)", 60.0),
        ("=COUNTA(Jan:Mar!B2:B3)", 6.0),
        ("=AVERAGE(Jan:Feb!B:B)", 15.0),
        ("=MAX(Jan:Mar!B2)", 30.0),
        ("=SUM(Jan:Nope!B2)", ExcelError.REF),
        ("=Jan:Mar!B2", ExcelError.VALUE),
        ("=VLOOKUP(10,Jan:Mar!B2,1)", ExcelError.VALUE),
    ],
)
def test_3d_references_evaluate_as_in_excel(formula, value) -> None:
    assert _value(_book(), formula) == value


def test_an_edit_on_a_spanned_sheet_recalculates() -> None:
    g = _book()
    g.setcell(0, 0, "=SUM(Jan:Mar!B2)")
    g.recalc()
    g.set_active(2)
    g.setcell(1, 1, "100")
    g.set_active(0)
    g.recalc()
    assert g.cells[0][0].val == 140.0


def test_the_span_follows_sheet_order() -> None:
    g = _book()
    g.setcell(0, 0, "=SUM(Jan:Mar!B2)")
    g.recalc()
    g.move_sheet("Mar", 1)  # Sum, Mar, Jan, Feb: Feb is outside Mar..Jan
    g.recalc()
    assert g.cells[0][0].val == 40.0
    g.add_sheet("Apr")
    g.move_sheet("Apr", 2)  # Sum, Mar, Apr, Jan, Feb
    g.set_active(2)
    g.setcell(1, 1, "5")
    g.set_active(0)
    g.recalc()
    assert g.cells[0][0].val == 45.0


def test_renaming_an_end_rewrites_the_span() -> None:
    g = _book()
    g.setcell(0, 0, "=SUM(Jan:Mar!B2)")
    g.rename_sheet("Mar", "March 2026")
    assert g.cells[0][0].text == "=SUM('Jan:March 2026'!B2)"
    g.recalc()
    assert g.cells[0][0].val == 60.0


def test_deleting_an_end_moves_it_inward() -> None:
    g = _book()
    g.setcell(0, 0, "=SUM(Jan:Mar!B2)")
    g.setcell(0, 1, "=SUM(Jan:Jan!B2)+1")
    g.remove_sheet("Jan")
    assert [g.cells[0][r].text for r in range(2)] == ["=SUM(Feb:Mar!B2)", "=SUM(#REF!)+1"]
    g.recalc()
    assert g.cells[0][0].val == 50.0


def test_copying_shifts_a_3d_reference_and_a_sheet_edit_does_not() -> None:
    assert adjust_refs("=SUM(Jan:Mar!B2)", 1, 1, True) == "=SUM(Jan:Mar!C3)"
    assert adjust_refs("=SUM(A1:Sheet2!B5)", 0, 1, True) == "=SUM(A2:Sheet2!B6)"
    g = _book()
    g.setcell(0, 0, "=SUM(Jan:Mar!B2)")
    g.set_active(1)
    g.insertrow(0)
    g.set_active(0)
    assert g.cells[0][0].text == "=SUM(Jan:Mar!B2)"


def test_3d_references_round_trip_through_xlsx(tmp_path) -> None:
    g = _book()
    g.setcell(0, 0, "=SUM(Jan:Mar!B2)")
    g.recalc()
    f = tmp_path / "3d.xlsx"
    assert g.xlsxsave(str(f)) == 0
    h = Grid()
    assert h.xlsxload(str(f)) == 0
    h.set_active(0)
    assert h.cells[0][0].text == "=SUM(Jan:Mar!B2)" and h.cells[0][0].val == 60.0
