"""Import tests over the committed .xlsx corpus in ``tests/xlsx/``.

Each fixture targets a category of importer behaviour (scalar types,
formulas, multi-sheet, sparse layout, text-vs-number interpretation, dates,
unicode, empty, defined names, and a table+chart workbook). Unlike
``test_xlsx_io.py`` these load pre-built files rather than generating them
with openpyxl, so the OpenXLSX-backed reader is exercised without any
third-party dependency. See ``tests/xlsx/generate_fixtures.py`` for how the
files are produced.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from gridcalc.engine import EMPTY, FORMULA, LABEL, NUM, Grid
from gridcalc.formula.errors import ExcelError

XLSX = Path(__file__).resolve().parent / "xlsx"

ALL_FIXTURES = [
    "types.xlsx",
    "formulas.xlsx",
    "multisheet.xlsx",
    "sparse.xlsx",
    "text_and_numbers.xlsx",
    "dates.xlsx",
    "unicode.xlsx",
    "empty.xlsx",
    "named_ranges.xlsx",
    "table_and_chart.xlsx",
]


def _load(name: str) -> Grid:
    g = Grid()
    rc = g.xlsxload(str(XLSX / name))
    assert rc == 0, f"xlsxload({name}) returned {rc}"
    return g


@pytest.mark.parametrize("name", ALL_FIXTURES)
def test_fixture_present_and_loads(name: str) -> None:
    """Every fixture exists and imports cleanly, in EXCEL mode with the xlsx
    function library attached."""
    assert (XLSX / name).is_file(), f"missing fixture {name}"
    from gridcalc.engine import Mode

    g = _load(name)
    assert g.mode == Mode.EXCEL
    assert "xlsx" in g.libs


class TestScalarTypes:
    def test_numbers(self) -> None:
        g = _load("types.xlsx")
        assert g.cells[0][0].type == NUM and g.cells[0][0].val == 42.0
        assert g.cells[0][1].val == -7.0  # negative
        assert math.isclose(g.cells[0][2].val, 3.14159)  # float
        assert g.cells[0][3].val == 1000000.0  # large int
        assert g.cells[0][4].val == 0.0  # zero
        assert math.isclose(g.cells[0][5].val, 2.5e-9)  # small float

    def test_strings_and_bools(self) -> None:
        g = _load("types.xlsx")
        assert g.cells[1][0].type == LABEL and g.cells[1][0].text == "hello"
        # Booleans import as text labels, not 1/0.
        assert g.cells[1][2].type == LABEL and g.cells[1][2].text == "TRUE"
        assert g.cells[1][3].type == LABEL and g.cells[1][3].text == "FALSE"

    def test_gap_cell_is_empty(self) -> None:
        # B2 was intentionally left blank between B1 and B3.
        g = _load("types.xlsx")
        assert g.cells[1][1].type == EMPTY


class TestFormulas:
    def test_reevaluated(self) -> None:
        g = _load("formulas.xlsx")
        assert g.cells[1][0].type == FORMULA
        assert g.cells[1][0].text == "=SUM(A1:A5)"
        assert g.cells[1][0].val == 150.0
        assert g.cells[1][1].val == 30.0  # AVERAGE
        assert g.cells[1][2].val == 200.0  # A1*A2
        assert g.cells[1][4].val == 50.0  # MAX

    def test_text_returning_formula(self) -> None:
        g = _load("formulas.xlsx")
        assert g.cells[1][3].sval == "big"  # =IF(A1>5,"big","small")

    def test_formula_over_formulas(self) -> None:
        g = _load("formulas.xlsx")
        assert g.cells[2][0].val == 200.0  # =B1+B5 = 150 + 50

    def test_error_producing_formula(self) -> None:
        g = _load("formulas.xlsx")
        assert g.cells[1][5].err is ExcelError.DIV0  # =A1/0


class TestMultiSheet:
    def test_sheet_order_and_names(self) -> None:
        g = _load("multisheet.xlsx")
        assert g.sheet_names() == ["Q1", "Q2", "Summary Report"]
        assert g.active == 0  # first sheet active

    def test_per_sheet_values(self) -> None:
        g = _load("multisheet.xlsx")
        g.set_active("Q1")
        assert g.cells[0][0].val == 100.0
        g.set_active("Q2")
        assert g.cells[0][1].val == 250.0

    def test_cross_sheet_formula(self) -> None:
        g = _load("multisheet.xlsx")
        g.set_active("Summary Report")  # sheet name with a space
        assert g.cells[1][0].text == "=SUM(Q1!A1:A2)+SUM(Q2!A1:A2)"
        assert g.cells[1][0].val == 700.0  # 100+200+150+250


class TestSparse:
    def test_scattered_cells(self) -> None:
        g = _load("sparse.xlsx")
        assert g.cells[0][0].val == 1.0  # A1
        assert g.cells[4][4].val == 5.0  # E5
        assert g.cells[9][9].text == "deep"  # J10

    def test_bounds(self) -> None:
        # A cell on the last valid column/row survives; one past the bound
        # is silently dropped rather than crashing the import.
        g = _load("sparse.xlsx")
        assert g.cells[255][0].text == "col256"  # last column (0-based 255)
        assert (256, 0) not in g._active._cells  # column past the bound
        assert g.cells[0][1023].text == "row1024"  # last row (0-based 1023)
        assert (0, 1024) not in g._active._cells  # row past the bound


class TestTextAndNumbers:
    def test_numeric_text_becomes_number(self) -> None:
        g = _load("text_and_numbers.xlsx")
        assert g.cells[0][0].type == NUM and g.cells[0][0].val == 7.0  # "007"
        assert g.cells[0][1].val == 3.5  # "3.5"
        assert g.cells[0][4].val == -42.0  # "-42"

    def test_non_numeric_text_stays_label(self) -> None:
        g = _load("text_and_numbers.xlsx")
        assert g.cells[0][2].type == LABEL and g.cells[0][2].text == "  padded  "
        assert g.cells[0][3].type == LABEL and g.cells[0][3].text == "123abc"

    def test_large_int_and_float_precision(self) -> None:
        g = _load("text_and_numbers.xlsx")
        assert g.cells[0][5].val == 12345678901234.0
        assert math.isclose(g.cells[0][6].val, 0.1)


class TestDates:
    def test_dates_import_as_serials(self) -> None:
        g = _load("dates.xlsx")
        assert g.cells[0][0].val == 45292.0  # 2024-01-01
        assert g.cells[0][1].val == 45366.5  # 2024-03-15 12:00
        assert g.cells[0][2].val == 36526.0  # 2000-01-01

    def test_date_arithmetic_formula(self) -> None:
        g = _load("dates.xlsx")
        assert g.cells[1][0].val == 74.5  # =A2-A1 in days


class TestUnicode:
    def test_unicode_sheet_name(self) -> None:
        g = _load("unicode.xlsx")
        assert g.sheet_names() == ["café"]

    def test_unicode_content_preserved(self) -> None:
        g = _load("unicode.xlsx")
        assert g.cells[0][0].text == "café"
        assert g.cells[0][1].text == "日本語"
        assert g.cells[0][2].text == "Москва"
        assert g.cells[0][3].text == "naïve résumé"
        assert g.cells[0][5].text == "→ ↔ ≈ ∑"


class TestEmpty:
    def test_empty_workbook_loads_with_no_cells(self) -> None:
        g = _load("empty.xlsx")
        # An entirely empty workbook imports cleanly with zero cells. Its one
        # sheet keeps the default name -- the reader only reports sheets that
        # have data, so an all-empty sheet's name does not round-trip.
        assert sum(len(s._cells) for s in g.sheets) == 0
        assert len(g.sheets) == 1


class TestDefinedRefParser:
    """`_parse_defined_ref` turns an xlsx defined-name target into
    (sheet, c1, r1, c2, r2), skipping anything that is not a single-area
    cell/range on one sheet."""

    def test_range(self) -> None:
        from gridcalc.engine import _parse_defined_ref

        assert _parse_defined_ref("Data!$A$1:$C$3") == ("Data", 0, 0, 2, 2)

    def test_single_cell(self) -> None:
        from gridcalc.engine import _parse_defined_ref

        assert _parse_defined_ref("Data!$B$2") == ("Data", 1, 1, 1, 1)

    def test_quoted_sheet_name_with_space(self) -> None:
        from gridcalc.engine import _parse_defined_ref

        assert _parse_defined_ref("'My Sheet'!$A$1:$B$2") == ("My Sheet", 0, 0, 1, 1)

    def test_no_dollar_signs(self) -> None:
        from gridcalc.engine import _parse_defined_ref

        assert _parse_defined_ref("Sheet1!A1:B2") == ("Sheet1", 0, 0, 1, 1)

    def test_rejects_non_reference(self) -> None:
        from gridcalc.engine import _parse_defined_ref

        assert _parse_defined_ref("SUM(A1:A2)") is None  # no sheet / formula
        assert _parse_defined_ref("Data!A1,Data!B2") is None  # multi-area
        assert _parse_defined_ref("Data!$A$1:INDEX(x,1)") is None  # embedded call


class TestNamedRanges:
    def test_defined_names_imported(self) -> None:
        g = _load("named_ranges.xlsx")
        names = {n.name: n for n in g.names}
        # Simple cell/range names import; a formula-valued name (Total) does not.
        assert set(names) == {"Nums", "TaxRate", "Local"}
        nums = names["Nums"]
        assert nums.sheet == "Data"
        assert (nums.c1, nums.r1, nums.c2, nums.r2) == (0, 0, 0, 3)

    def test_cross_sheet_named_range_resolves(self) -> None:
        g = _load("named_ranges.xlsx")
        g.set_active("Report")
        assert g.cells[0][0].val == 100.0  # =SUM(Nums), Nums -> Data!A1:A4
        assert g.cells[0][1].val == 10.0  # =TaxRate*SUM(Nums), TaxRate -> Data!C1
        assert g.cells[0][2].val == 100.0  # =SUM(Data!A1:A4) plain-range control

    def test_same_sheet_named_range_resolves(self) -> None:
        g = _load("named_ranges.xlsx")
        g.set_active("Data")
        assert g.cells[1][0].val == 30.0  # =SUM(Local), Local -> Data!A1:A2

    def test_sheet_qualified_name_survives_json_roundtrip(self, tmp_path) -> None:
        g = _load("named_ranges.xlsx")
        f = tmp_path / "rt.json"
        assert g.jsonsave(str(f)) == 0
        g2 = Grid()
        assert g2.jsonload(str(f)) == 0
        names = {n.name: n.sheet for n in g2.names}
        assert names["Nums"] == "Data"
        g2.set_active("Report")
        assert g2.cells[0][0].val == 100.0  # still resolves after the round-trip


class TestTableAndChart:
    def test_import_does_not_choke_on_table_or_chart(self) -> None:
        # A table + an embedded chart must not break the import; the chart is
        # a drawing, not a sheet, so only the two worksheets appear.
        g = _load("table_and_chart.xlsx")
        assert g.sheet_names() == ["Sales", "Report"]

    def test_table_cells_import_as_plain_data(self) -> None:
        g = _load("table_and_chart.xlsx")
        g.set_active("Sales")
        assert g.cells[0][0].text == "Region"  # header
        assert g.cells[1][1].val == 100.0  # North amount
        assert g.cells[1][3].val == 150.0  # East amount

    def test_plain_range_formula_over_table_works(self) -> None:
        g = _load("table_and_chart.xlsx")
        g.set_active("Report")
        assert g.cells[0][0].val == 450.0  # =SUM(Sales!B2:B4)

    def test_structured_reference_is_unsupported(self) -> None:
        # =SUM(SalesTable[Amount]) -- structured references are not part of the
        # formula grammar; the cell keeps its text but evaluates to nan.
        g = _load("table_and_chart.xlsx")
        g.set_active("Report")
        cell = g.cells[0][1]
        assert cell.text == "=SUM(SalesTable[Amount])"
        assert isinstance(cell.val, float) and math.isnan(cell.val)
