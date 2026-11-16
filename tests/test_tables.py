"""Excel tables and structured references (`Sales[Amount]`)."""

import json
import zipfile

import pytest

openpyxl = pytest.importorskip("openpyxl")

from openpyxl.worksheet.table import Table as XTable  # noqa: E402

from gridcalc.engine import Grid  # noqa: E402
from gridcalc.formula.errors import ExcelError  # noqa: E402
from gridcalc.undo import UndoManager  # noqa: E402


def _book(tmp_path, totals: bool = False):
    """Sheet `Data`: table `Sales` on A1:C4 (Item, Qty, Price), D a calculated
    column outside it, and formulas on sheet `Report`."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    rows = [("Item", "Qty", "Price"), ("a", 2, 10), ("b", 3, 20), ("c", 5, 30)]
    for r, row in enumerate(rows, 1):
        for c, v in enumerate(row, 1):
            ws.cell(row=r, column=c, value=v)
    ref = "A1:C4"
    if totals:
        ws["A5"] = "Total"
        ws["B5"] = "=SUBTOTAL(109,Sales[Qty])"
        ref = "A1:C5"
    t = XTable(displayName="Sales", ref=ref)
    if totals:
        t.totalsRowCount = 1
    ws.add_table(t)
    for r in range(2, 5):
        ws.cell(row=r, column=5, value="=Sales[[#This Row],[Qty]]*Sales[[#This Row],[Price]]")
    rep = wb.create_sheet("Report")
    rep["A1"] = "=SUM(Sales[Qty])"
    path = tmp_path / "t.xlsx"
    wb.save(str(path))
    g = Grid()
    assert g.xlsxload(str(path)) == 0
    return g, path


def _val(g, sheet, c, r):
    cl = g._sheet_cells(sheet).get((c, r))
    if cl.err is not None:
        return cl.err
    return cl.sval if cl.sval is not None else cl.val


def test_tables_are_read(tmp_path):
    g, _ = _book(tmp_path, totals=True)
    (t,) = g.tables
    assert (t.name, t.sheet, t.c1, t.r1, t.c2, t.r2) == ("Sales", "Data", 0, 0, 2, 4)
    assert t.columns == ["Item", "Qty", "Price"] and (t.header, t.totals) == (1, 1)


@pytest.mark.parametrize(
    ("formula", "value"),
    [
        ("=SUM(Sales[Qty])", 10.0),
        ("=SUM(Sales[[Qty]:[Price]])", 70.0),
        ("=SUM(Sales[])", 70.0),
        ("=SUM(Sales)", 70.0),  # the bare name is the data rows
        ("=ROWS(Sales[#All])", 5.0),
        ("=ROWS(Sales[[#Headers],[#Data]])", 4.0),
        ("=INDEX(Sales[#Headers],2)", "Qty"),
        ("=Sales[[#Totals],[Qty]]", 10.0),
        ("=SUM(sales[qty])", 10.0),  # names fold case
        ("=SUM(Sales[Weight])", ExcelError.REF),
        ("=SUM(Nosuch[Qty])", ExcelError.REF),
        ("=Sales[[#This Row],[Qty]]", ExcelError.VALUE),  # Report!B1 is no table row
        ("=SUM(Sales[Qty]:Sales[Price])", 70.0),
    ],
)
def test_structured_references(tmp_path, formula, value):
    g, _ = _book(tmp_path, totals=True)
    g.set_active("Report")
    g.setcell(1, 0, formula)
    assert _val(g, "Report", 1, 0) == value


def test_this_row_reads_the_formulas_own_row(tmp_path):
    g, _ = _book(tmp_path)
    assert [_val(g, "Data", 4, r) for r in (1, 2, 3)] == [20.0, 60.0, 150.0]
    g.set_active("Data")
    g.setcell(3, 2, "=[@Qty]+1")  # bare form, D3 beside row 3 of the table
    assert _val(g, "Data", 3, 2) == ExcelError.REF  # D is outside the table
    g.setcell(2, 2, "=[@Qty]+1")  # C3 is inside it
    assert _val(g, "Data", 2, 2) == 4.0


def test_a_calculated_column_is_not_circular_and_follows_edits(tmp_path):
    g, _ = _book(tmp_path)
    g.set_active("Data")
    # A column inside the table that reads another column of its own row.
    g.setcell(2, 1, "=Sales[[#This Row],[Qty]]*100")
    assert _val(g, "Data", 2, 1) == 200.0
    g.setcell(1, 1, "7")
    assert _val(g, "Data", 2, 1) == 700.0
    assert _val(g, "Report", 0, 0) == 15.0


def test_an_inserted_row_grows_the_table_and_undo_restores_it(tmp_path):
    g, _ = _book(tmp_path)
    g.set_active("Data")
    undo = UndoManager()
    undo.save_grid(g)
    g.insertrow(2)
    g.setcell(1, 2, "100")
    g.recalc()
    assert (g.tables[0].r1, g.tables[0].r2) == (0, 4)
    assert _val(g, "Report", 0, 0) == 110.0
    undo.undo(g)
    assert (g.tables[0].r1, g.tables[0].r2) == (0, 3)
    assert _val(g, "Report", 0, 0) == 10.0


def test_deleting_the_header_row_drops_the_table(tmp_path):
    g, _ = _book(tmp_path)
    g.set_active("Data")
    g.deleterow(0)
    g.recalc()
    assert g.tables == []
    assert _val(g, "Report", 0, 0) == ExcelError.REF


def test_an_inserted_column_gets_a_new_name(tmp_path):
    g, _ = _book(tmp_path)
    g.set_active("Data")
    g.insertcol(1)
    g.recalc()
    assert g.tables[0].columns == ["Item", "Column1", "Qty", "Price"]
    assert _val(g, "Report", 0, 0) == 10.0


def test_xlsx_save_keeps_tables_and_their_filters(tmp_path):
    g, src = _book(tmp_path)
    g.set_active("Data")
    g.insertrow(2)
    g.recalc()
    out = tmp_path / "out.xlsx"
    assert g.xlsxsave(str(out)) == 0
    wb = openpyxl.load_workbook(str(out))
    t = wb["Data"].tables["Sales"]
    assert t.ref == "A1:C5"
    assert t.autoFilter.ref == "A1:C5"
    with zipfile.ZipFile(out) as z:
        ct = z.read("[Content_Types].xml")
    assert b"spreadsheetml.table+xml" in ct
    g2 = Grid()
    assert g2.xlsxload(str(out)) == 0
    assert [_val(g2, "Data", 4, r) for r in (1, 3, 4)] == [20.0, 60.0, 150.0]
    assert _val(g2, "Report", 0, 0) == 10.0


def test_json_round_trip_and_bad_entries(tmp_path):
    g, _ = _book(tmp_path, totals=True)
    f = tmp_path / "t.json"
    assert g.jsonsave(str(f)) == 0
    g2 = Grid()
    assert g2.jsonload(str(f)) == 0
    (t,) = g2.tables
    assert (t.name, t.c2, t.r2, t.columns, t.totals) == ("Sales", 2, 4, ["Item", "Qty", "Price"], 1)
    assert _val(g2, "Report", 0, 0) == 10.0

    d = json.loads(f.read_text())
    good = d["tables"][0]
    d["tables"] = [
        good,
        {**good, "name": "Dup", "sheet": "Nosuch"},  # no such sheet
        {**good, "name": "Two", "columns": ["a"]},  # width mismatch
        {**good, "name": "Three", "columns": ["a", "A", "b"]},  # duplicate columns
        {**good, "name": "4bad"},  # not a name
        {**good, "name": "Five", "style": "<x/>"},
        "junk",
    ]
    f.write_text(json.dumps(d))
    g3 = Grid()
    assert g3.jsonload(str(f)) == 0
    assert [t.name for t in g3.tables] == ["Sales"]


def test_python_list_comprehensions_are_not_structured_references():
    from gridcalc.formula.errors import FormulaError
    from gridcalc.formula.parser import parse

    with pytest.raises(FormulaError):
        parse("=[x*2 for x in range(3)]")


def test_column_names_keep_their_spaces():
    """IronCalc `tables.xlsx` names a column `the two ` (trailing space)."""
    from gridcalc.formula.parser import parse

    assert parse("=T[[#Totals],[the two ]]").col1 == "the two "
    assert parse("=T[the two ]").col1 == "the two "
    assert parse("=T[ @Qty]").areas == ("#this row",)
    assert parse("=SUM(T[ ])").args[0].col1 is None


# Header edits, as Excel 16.114 makes them (probed 2026-11-16).


def _grid():
    """Table `T` on A1:D3 (Item, Qty, Price, Cost) with `Cost` calculated by a
    bare and a `@` reference, and formulas outside it on a second sheet."""
    from gridcalc.engine import Mode, Table

    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    rows = [
        ("Item", "Qty", "Price", "Cost"),
        ("a", "2", "10", "=[@Qty]*[@Price]"),
        ("b", "3", "20", "=[@Qty]*[@[Price]]"),
    ]
    g.setcells_bulk([(c, r, v) for r, row in enumerate(rows) for c, v in enumerate(row)])
    g.tables.append(Table("T", g._active.name, 0, 0, 3, 2, ["Item", "Qty", "Price", "Cost"]))
    g.setcell(5, 0, "=SUM(T[Qty])")
    g.setcell(5, 1, "=SUM(T[[#Headers],[Qty]:[Price]])")
    g.setcell(5, 2, '="T[Qty]"')
    g.recalc()
    return g


def _text(g, c, r):
    return g.cell(c, r).text


def test_editing_a_header_renames_the_column_and_its_references():
    g = _grid()
    g.setcell(1, 0, "Amount")
    assert g.tables[0].columns == ["Item", "Amount", "Price", "Cost"]
    assert _text(g, 5, 0) == "=SUM(T[Amount])"
    assert _text(g, 5, 1) == "=SUM(T[[#Headers],[Amount]:[Price]])"
    assert _text(g, 3, 1) == "=[@Amount]*[@Price]"
    assert _text(g, 5, 2) == '="T[Qty]"'  # text is not a reference
    assert g.cell(5, 0).val == 5.0 and g.cell(3, 2).val == 60.0


@pytest.mark.parametrize(
    ("col", "typed", "columns"),
    [
        (2, "qty", ["Item", "Qty", "qty2", "Cost"]),  # the right-hand duplicate takes the suffix
        (0, "Price", ["Price", "Qty", "Price2", "Cost"]),
        (2, "", ["Item", "Qty", "Column1", "Cost"]),
        (2, "5", ["Item", "Qty", "5", "Cost"]),
    ],
)
def test_header_names_stay_unique(col, typed, columns):
    g = _grid()
    g.setcell(col, 0, typed)
    assert g.tables[0].columns == columns
    assert [g.cell(c, 0).text.lstrip('"') for c in range(4)] == columns
    assert g.cell(2, 0).type == 2  # LABEL: a number typed into a header becomes text
    price = columns[2]
    assert _text(g, 5, 1) == f"=SUM(T[[#Headers],[Qty]:[{price}]])"
    assert g.cell(3, 2).val == 60.0


@pytest.mark.parametrize(
    ("name", "qualified", "at"),
    [
        ("a*b", "T[a*b]", "[@[a*b]]"),
        ("two words", "T[two words]", "[@[two words]]"),
        ("x [y] #z 'q", "T[x '[y'] '#z ''q]", "[@[x '[y'] '#z ''q]]"),
    ],
)
def test_renamed_columns_are_spelled_as_excel_writes_them(name, qualified, at):
    g = _grid()
    g.setcell(1, 0, name)
    assert _text(g, 5, 0) == f"=SUM({qualified})"
    assert _text(g, 3, 1) == f"={at}*[@Price]"
    assert g.cell(5, 0).val == 5.0 and g.cell(3, 1).val == 20.0


def test_a_header_rename_rewrites_names_and_other_sheets_and_undoes():
    from gridcalc.engine import NamedRange

    g = _grid()
    g.names.append(NamedRange("TotalQty", 0, 0, 0, 0, formula="=SUM(T[Qty])"))
    g.add_sheet("Other")
    g.set_active("Other")
    g.setcell(0, 0, "=T[[#Headers],[Qty]]&TotalQty")
    g.set_active(g.sheets[0].name)
    undo = UndoManager()
    undo.save_cell(g, 1, 0)
    g.setcell(1, 0, "Units")
    assert g.names[0].formula == "=SUM(T[Units])"
    assert g.sheets[1]._cells[(0, 0)].text == "=T[[#Headers],[Units]]&TotalQty"
    assert g.sheets[1]._cells[(0, 0)].sval == "Units5"
    undo.undo(g)
    assert g.tables[0].columns == ["Item", "Qty", "Price", "Cost"]
    assert g.names[0].formula == "=SUM(T[Qty])"
    assert g.sheets[1]._cells[(0, 0)].text == "=T[[#Headers],[Qty]]&TotalQty"


def test_a_header_rename_reaches_the_saved_table_part(tmp_path):
    g, _ = _book(tmp_path, totals=True)
    g.set_active("Data")
    g.setcell(1, 0, "Units")
    out = tmp_path / "renamed.xlsx"
    assert g.xlsxsave(str(out)) == 0
    wb = openpyxl.load_workbook(str(out))
    t = wb["Data"].tables["Sales"]
    assert [c.name for c in t.tableColumns] == ["Item", "Units", "Price"]
    assert wb["Report"]["A1"].value == "=SUM(Sales[Units])"
    assert wb["Data"]["B5"].value == "=SUBTOTAL(109,Sales[Units])"


def test_loading_a_file_renames_nothing(tmp_path):
    g, _ = _book(tmp_path)
    assert g.tables[0].columns == ["Item", "Qty", "Price"]
    assert g._sheet_cells("Report")[(0, 0)].text == "=SUM(Sales[Qty])"


def test_a_bare_column_reference_reads_its_own_table():
    g = _grid()
    g.setcell(3, 1, "=SUM([Qty])")
    assert g.cell(3, 1).val == 5.0
    g.setcell(7, 0, "=SUM([Qty])")  # outside any table
    assert g.cell(7, 0).err == ExcelError.REF


def test_a_header_rename_rewrites_the_formulas_kept_in_the_table_part():
    g = _grid()
    g.tables[0].xml = (
        '<table><tableColumns count="4"><tableColumn id="1" name="Item"/>'
        '<tableColumn id="2" name="Qty"/><tableColumn id="3" name="Price"/>'
        '<tableColumn id="4" name="Cost"><calculatedColumnFormula>T[[#This Row],[Qty]]&amp;"&lt;"'
        "</calculatedColumnFormula></tableColumn></tableColumns></table>"
    )
    g.setcell(1, 0, "Units")
    assert '<calculatedColumnFormula>T[[#This Row],[Units]]&amp;"&lt;"<' in g.tables[0].xml


def test_a_mode_switch_flags_a_bare_column_that_names_no_table():
    """`[x for x in xs]` lexes as a bare column; outside a table it is Python."""
    from gridcalc.engine import Mode

    g = _grid()
    g.setcell(3, 1, "=SUM([Qty])")
    g.setcell(7, 0, "=[x for x in xs]")
    errs = g.validate_for_mode(Mode.HYBRID)
    assert errs == ["H1: [x for x in xs] is not a column of a table here"]


def test_python_mode_has_no_table_syntax():
    """`T[Qty]` is a Python subscript in PYTHON mode: no switch, no rewrite."""
    from gridcalc.engine import Mode

    g = _grid()
    errs = g.validate_for_mode(Mode.PYTHON)
    assert errs[0] == "Sheet1!D2: table references have no meaning in PYTHON"
    assert len(errs) == 4  # D2, D3, F1, F2; `="T[Qty]"` is text
    g.mode = Mode.PYTHON
    g.setcell(5, 0, "=T[Qty]")
    g.setcell(1, 0, "Units")
    assert g.tables[0].columns == ["Item", "Qty", "Price", "Cost"]
    assert g.cell(5, 0).text == "=T[Qty]"


def test_mode_python_refuses_table_references_and_offers_to_convert():
    from gridcalc import commands
    from gridcalc.engine import Mode

    g = _grid()
    undo = UndoManager()
    res = commands.run("mode", g, undo, ["python"])
    assert not res.ok and g.mode == Mode.EXCEL
    assert "`:mode python convert`" in res.message and "4 formulas" in res.message

    res = commands.run("mode", g, undo, ["python", "convert"])
    assert res.ok and g.mode == Mode.PYTHON
    assert res.message == "mode: python; 4 formulas now read ranges"
    assert [g.cell(c, r).text for c, r in ((3, 1), (3, 2), (5, 0), (5, 1))] == [
        "=B2*C2",
        "=B3*C3",
        "=SUM($B$2:$B$3)",
        "=SUM($B$1:$C$1)",
    ]
    assert g.cell(3, 2).val == 60.0 and g.cell(5, 0).val == 5.0
    assert g.cell(5, 2).text == '="T[Qty]"'

    undo.undo(g)
    assert g.mode == Mode.EXCEL and g.cell(5, 0).text == "=SUM(T[Qty])"


def test_converting_a_reference_to_another_sheet_says_python_cannot_read_it():
    from gridcalc import commands

    g = _grid()
    g.add_sheet("Other")
    g.set_active("Other")
    g.setcell(0, 0, "=SUM(T[Price])")
    res = commands.run("mode", g, UndoManager(), ["python", "convert"])
    assert res.message.endswith("1 from another sheet, which PYTHON mode cannot read")
    assert g.sheets[1]._cells[(0, 0)].text == "=SUM(Sheet1!$C$2:$C$3)"
