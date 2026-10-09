"""Tests for scripts/excel_corpus.py, which compares gridcalc with values Excel saved."""

import importlib.util
import re
import zipfile
from pathlib import Path

import pytest

from gridcalc.engine import Grid, Mode

pytest.importorskip("openpyxl")

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "excel_corpus.py"
_spec = importlib.util.spec_from_file_location("excel_corpus", _SCRIPT)
excel_corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(excel_corpus)


def _book(tmp_path: Path) -> Path:
    """A1=3, B1=A1*2, C1=B1+1, D1="x"&A1, saved with each number result."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.setcell(0, 0, "3")
    g.setcell(1, 0, "=A1*2")
    g.setcell(2, 0, "=B1+1")
    g.setcell(3, 0, '="x"&A1')
    g.recalc()
    path = tmp_path / "book.xlsx"
    assert g.xlsxsave(str(path)) == 0
    return path


def _set_saved_value(path: Path, ref: str, value: str) -> None:
    """Replace the value saved for ``ref``, as if Excel had computed another."""
    with zipfile.ZipFile(path) as z:
        parts = {n: z.read(n) for n in z.namelist()}
    name = next(n for n in parts if n.startswith("xl/worksheets/sheet"))
    xml = parts[name].decode()
    xml, n = re.subn(
        rf'(<c r="{ref}"[^>]*>.*?<v>)[^<]*(</v>)', rf"\g<1>{value}\g<2>", xml, flags=re.S
    )
    assert n == 1
    parts[name] = xml.encode()
    with zipfile.ZipFile(path, "w") as z:
        for k, v in parts.items():
            z.writestr(k, v)


def test_a_workbook_gridcalc_saved_agrees_with_itself(tmp_path) -> None:
    rep = excel_corpus.compare(_book(tmp_path))
    assert (rep["compared"], rep["agree"], rep["roots"]) == (2, 2, [])
    # gridcalc saves no value for a text result, so D1 is not compared.
    assert rep["no_saved_value"] == 1


def test_a_mismatch_is_a_root_and_its_reader_is_downstream(tmp_path) -> None:
    path = _book(tmp_path)
    _set_saved_value(path, "B1", "7")
    _set_saved_value(path, "C1", "8")
    rep = excel_corpus.compare(path)
    assert [m["cell"] for m in rep["roots"]] == ["Sheet1!B1"]
    assert rep["downstream"] == 1
    assert rep["by_function"] == {}  # `=A1*2` calls no function


def test_formula_text_in_a_text_cell_is_not_a_formula(tmp_path) -> None:
    g = Grid()
    g._put_label(0, 0, "=1+1")
    path = tmp_path / "text.xlsx"
    assert g.xlsxsave(str(path)) == 0
    assert excel_corpus.compare(path)["formulas"] == 0


def test_functions_drop_the_newer_function_prefix() -> None:
    assert excel_corpus.functions("=_xlfn.XLOOKUP(A1,B:B,C:C)+SUM(D1)") == {"XLOOKUP", "SUM"}
