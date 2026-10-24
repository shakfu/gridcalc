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
