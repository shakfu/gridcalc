"""Tests for scripts/excel_check.py, which writes the Excel comparison workbook."""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("openpyxl")

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "excel_check.py"
_spec = importlib.util.spec_from_file_location("excel_check", _SCRIPT)
excel_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(excel_check)


def test_every_case_has_a_row_and_the_inputs_load_as_intended() -> None:
    ws = excel_check.build().active
    assert ws.max_row == len(excel_check.CASES) + 1
    assert ws["I2"].value == "setup" and ws["L2"].value is True


def test_results_keep_their_excel_type() -> None:
    ws = excel_check.build().active
    by_id = {ws[f"I{r}"].value: ws[f"L{r}"] for r in range(2, ws.max_row + 1)}
    assert (by_id["pow-1"].value, by_id["pow-1"].data_type) == (64, "n")
    assert (by_id["text-1"].value, by_id["text-1"].data_type) == ("0.00001", "s")
    assert (by_id["misc-5"].value, by_id["misc-5"].data_type) == ("#N/A", "e")


def test_newer_functions_are_stored_with_their_prefix() -> None:
    assert excel_check._stored("=ROWS(FILTER(A1:A2,A1:A2>0))") == (
        "=ROWS(_xlfn._xlws.FILTER(A1:A2,A1:A2>0))"
    )
    assert excel_check._stored('=TEXTJOIN(",",FALSE,LEN(A1:A3))').startswith("=_xlfn.TEXTJOIN(")


def test_plain_cases_are_not_array_formulas() -> None:
    ws = excel_check.build().active
    by_id = {ws[f"I{r}"].value: ws[f"K{r}"].value for r in range(2, ws.max_row + 1)}
    assert by_id["misc-7"] == '=OR("a",TRUE)'
    assert isinstance(by_id["misc-3"], excel_check.ArrayFormula)
