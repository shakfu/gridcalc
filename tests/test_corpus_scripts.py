"""Tests for the untuned-corpus scripts: sheetpedia_sample.py and excel_gaps.py."""

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("openpyxl")

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))  # excel_gaps imports excel_corpus


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sheetpedia_sample = _module("sheetpedia_sample")
excel_gaps = _module("excel_gaps")


def _book(path: Path, formulas: int) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    for r in range(1, formulas + 1):
        wb.active.cell(row=r, column=1, value=f"={r}+1")
    wb.active["B1"] = "text"
    wb.save(path)


def test_sample_is_repeatable_and_skips_files_with_few_formulas(tmp_path):
    for i in range(6):
        _book(tmp_path / f"f{i}.xlsx", 12 if i % 2 else 3)
    (tmp_path / "bad.xlsx").write_bytes(b"not a zip")
    first = sheetpedia_sample.sample(tmp_path, 2)
    assert first == sheetpedia_sample.sample(tmp_path, 2)
    assert len(first) == 2
    assert all(sheetpedia_sample.formula_count(f) == 12 for f in first)
    assert sheetpedia_sample.formula_count(tmp_path / "bad.xlsx") == -1


@pytest.mark.parametrize(
    ("formula", "excel", "got", "label"),
    [
        ("=RAND()", 0.1, 0.2, "volatile RAND/NOW"),
        ("=VLOOKUP(A1,'[1]D'!A:B,2)", 3.0, ["error", "#N/A"], "external workbook ref"),
        ("=A1-B1", 2.0, ["error", "#VALUE!"], "gridcalc #VALUE!"),
        ("=A1", 1.0, 1.0 + 1e-9, "number, rel diff < 1e-6"),
        ("=A1", 1.0, 2.0, "number, wrong"),
        ("=A1", ["error", "#N/A"], ["error", "#VALUE!"], "gridcalc #VALUE!"),
        ("=A1", 1.0, "", "excel num, gridcalc text"),
    ],
)
def test_cause(formula, excel, got, label):
    assert excel_gaps.cause(formula, excel, got) == label


def test_render_counts_roots_by_cause():
    reps = [
        {
            "file": "a.xlsx",
            "compared": 3,
            "agree": 1,
            "roots": [
                {"cell": "S!A1", "formula": "=RAND()", "excel": 0.1, "gridcalc": 0.2},
                {"cell": "S!A2", "formula": "=NOW()", "excel": 1.0, "gridcalc": 2.0},
            ],
        },
        {"file": "b.xlsx", "compared": 2, "agree": 2, "roots": []},
    ]
    out = excel_gaps.render(reps, ["volatile RAND/NOW"])
    assert "2 files, 5 cells, 2 wrong, 1 files with a wrong cell" in out
    assert "     2    1 files  volatile RAND/NOW" in out
    assert out.count("a.xlsx S!A") == 1  # one example per file
