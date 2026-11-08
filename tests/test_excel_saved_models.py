"""Whole workbooks against the values Excel saved in them.

`tests/xlsx/date_model_excel.xlsx` is built by `scripts/build_date_model.py` and
recalculated and saved by Excel for Mac 16.114, so every formula cell carries
Excel's own result. gridcalc was not tuned on it.
"""

import importlib.util
import math
from pathlib import Path

import pytest

pytest.importorskip("openpyxl")

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "excel_corpus.py"
_spec = importlib.util.spec_from_file_location("excel_corpus", _SCRIPT)
excel_corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(excel_corpus)

MODEL = _ROOT / "tests" / "xlsx" / "date_model_excel.xlsx"
XIRR_CELL = ("Summary", 1, 8)  # Summary!B9


@pytest.fixture(scope="module")
def model():
    from gridcalc.loader import load_workbook

    formulas, saved = excel_corpus.excel_values(MODEL)
    return formulas, saved, load_workbook(str(MODEL))


def test_the_fixture_is_excel_saved_and_complete(model) -> None:
    formulas, saved, _ = model
    assert "Excel" in excel_corpus.application(MODEL)
    assert len(formulas) == 2201 and set(saved) == set(formulas)
    # Without `_xlfn.`, Excel reads a newer function as user-defined: `#NAME?`.
    assert not any("_xludf" in f.lower() for f in formulas.values())
    assert not any(v == ("error", "#NAME?") for v in saved.values())


def test_every_cell_matches_excel(model) -> None:
    formulas, saved, g = model
    wrong = [
        (f"{k[0]}!{excel_corpus._a1(k[1], k[2])}", formulas[k], saved[k], got)
        for k in formulas
        if k != XIRR_CELL
        and not excel_corpus.same(saved[k], got := excel_corpus.gridcalc_value(g, k), 1e-9)
    ]
    assert wrong == []


def test_xirr_matches_excel_to_its_solver_tolerance(model) -> None:
    _, saved, g = model
    got = excel_corpus.gridcalc_value(g, XIRR_CELL)
    assert math.isclose(got, saved[XIRR_CELL], rel_tol=1e-7)


@pytest.mark.xfail(strict=True, reason="XIRR stops where Excel's solver does not (TODO.md)")
def test_xirr_matches_excel_to_1e9(model) -> None:
    _, saved, g = model
    got = excel_corpus.gridcalc_value(g, XIRR_CELL)
    assert math.isclose(got, saved[XIRR_CELL], rel_tol=1e-9)
