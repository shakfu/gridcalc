"""Iterative calculation of circular references, against Excel for Mac 16.114.

`tests/xlsx/iterate_input.xlsx` is built by `scripts/build_iterate_model.py`;
`iterate_excel.xlsx` is the same file recalculated and saved by Excel. The
probe values below were measured by entering the formulas in Excel
(`docs/dev/iteration.md`).
"""

import importlib.util
import json
import math
import zipfile
from pathlib import Path

import pytest

from gridcalc.engine import Grid, Mode
from gridcalc.formula.errors import ExcelError

_ROOT = Path(__file__).resolve().parent.parent
INPUT = _ROOT / "tests" / "xlsx" / "iterate_input.xlsx"
SAVED = _ROOT / "tests" / "xlsx" / "iterate_excel.xlsx"
COUNTER = ("Cycles", 1, 0)  # Cycles!B1, `=B1+1`: one per sweep


def _excel_corpus():
    pytest.importorskip("openpyxl")
    spec = importlib.util.spec_from_file_location(
        "excel_corpus", _ROOT / "scripts" / "excel_corpus.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _grid(cells: dict[str, str], iterate: tuple[int, float] | None = (50, 1e-4)) -> Grid:
    from gridcalc.engine import ref

    g = Grid()
    g.mode = Mode.EXCEL
    g.iterate = iterate
    for name, text in cells.items():
        _, c, r = ref(name)
        g._setcell_no_recalc(c, r, text)
    g.recalc()
    return g


def _val(g: Grid, name: str):
    from gridcalc.engine import ref

    _, c, r = ref(name)
    cl = g._cells[(c, r)]
    return cl.err if cl.err is not None else cl.sval if cl.sval is not None else cl.val


def test_every_cell_matches_excel_after_as_many_recalcs() -> None:
    from gridcalc.loader import load_workbook

    ec = _excel_corpus()
    formulas, saved = ec.excel_values(SAVED)
    assert "Excel" in ec.application(SAVED)
    assert set(saved) == set(formulas) and len(formulas) == 24
    # Excel recalculated more than once while saving; the counter says how often.
    calcs, rest = divmod(saved[COUNTER], 50)
    assert rest == 0 and calcs >= 1
    g = load_workbook(str(INPUT))
    assert g.iterate == (50, 1e-4)
    for _ in range(int(calcs) - 1):
        g.recalc()
    wrong = [
        (k, formulas[k], saved[k], got)
        for k in formulas
        if not ec.same(saved[k], got := ec.gridcalc_value(g, k), 0)
    ]
    assert wrong == []


def test_a_load_iterates_from_the_values_excel_saved() -> None:
    from gridcalc.loader import load_workbook

    ec = _excel_corpus()
    _, saved = ec.excel_values(SAVED)
    g = load_workbook(str(SAVED))
    assert ec.gridcalc_value(g, COUNTER) == saved[COUNTER] + 50


def test_without_iteration_a_cycle_is_circ() -> None:
    g = _grid({"A1": "=B1+1", "B1": "=A1", "C1": "=B1*2"}, iterate=None)
    assert [_val(g, n) for n in ("A1", "B1", "C1")] == [ExcelError.CIRC] * 3
    assert (0, 0) in g._circular


def test_iteration_stops_after_the_count() -> None:
    assert _val(_grid({"B1": "=B1+1"}), "B1") == 50.0


def test_every_recalc_sweeps_the_cycle_again() -> None:
    g = _grid({"B1": "=B1+1"})
    g.setcell(5, 5, "7")  # unrelated: Excel still sweeps, 50 -> 100
    assert _val(g, "B1") == 100.0


def test_iteration_stops_when_no_cell_moves_by_the_delta() -> None:
    assert math.isclose(_val(_grid({"B2": "=COS(B2)"}), "B2"), 0.739054790747, rel_tol=1e-11)


def test_the_stop_is_over_every_cycle_together() -> None:
    # B1 never settles, so COS runs all 50 sweeps.
    g = _grid({"B1": "=B1+1", "B2": "=COS(B2)"})
    assert math.isclose(_val(g, "B2"), 0.7390851321663374, rel_tol=1e-15)


def test_a_cell_reading_a_cycle_counts_toward_the_stop() -> None:
    g = _grid({"B5": "=0.5*B5+1", "C5": "=1000000*B5"})
    assert math.isclose(_val(g, "B5"), 1.999999999942, rel_tol=1e-12)


def test_sweeps_run_in_row_order_ignoring_dependencies() -> None:
    g = _grid({"C7": "=0.7*B8+1", "B8": "=0.7*C7+1"})
    assert math.isclose(_val(g, "C7"), 3.333280741539, rel_tol=1e-12)
    assert math.isclose(_val(g, "B8"), 3.333296519078, rel_tol=1e-12)
    # The B1:C1 cycle reads B5:C5 but runs first; D1 sees the previous sweep's C5.
    # Excel's B1 differs: entering a formula there evaluates it once first.
    g = _grid(
        {
            "B5": "=0.5*C5+1",
            "C5": "=0.5*B5+1",
            "B1": "=0.5*C1+C5",
            "C1": "=0.5*B1",
            "D1": "=C5*1000",
        }
    )
    assert math.isclose(_val(g, "B5"), 1.999999985099, rel_tol=1e-12)
    assert math.isclose(_val(g, "D1"), 1999.999970197678, rel_tol=1e-15)


def test_a_broken_cycle_recalculates_normally() -> None:
    g = _grid({"A1": "=B1+1", "B1": "=A1"})
    g.setcell(1, 0, "5")
    assert _val(g, "A1") == 6.0


def test_the_setting_round_trips_through_xlsx_and_json(tmp_path: Path) -> None:
    g = _grid({"A1": "=0.5*A1+1"}, iterate=(7, 0.25))
    g.xlsxsave(str(tmp_path / "w.xlsx"))
    with zipfile.ZipFile(tmp_path / "w.xlsx") as z:
        wb = z.read("xl/workbook.xml").decode()
    assert 'iterate="1" iterateCount="7" iterateDelta="0.25"' in wb
    g.jsonsave(str(tmp_path / "w.json"))
    assert json.loads((tmp_path / "w.json").read_text())["iterate"] == {"count": 7, "delta": 0.25}
    for name, load in (("w.xlsx", Grid.xlsxload), ("w.json", Grid.jsonload)):
        h = Grid()
        load(h, str(tmp_path / name))
        assert h.iterate == (7, 0.25)
    g.iterate = None
    g.jsonsave(str(tmp_path / "off.json"))
    assert "iterate" not in json.loads((tmp_path / "off.json").read_text())


@pytest.mark.parametrize(
    "setting", [{"count": 0, "delta": 0.1}, {"count": 5, "delta": -1}, {"count": "x"}]
)
def test_an_invalid_json_setting_warns_and_leaves_iteration_off(
    tmp_path: Path, setting: dict
) -> None:
    p = tmp_path / "w.json"
    p.write_text(json.dumps({"version": 2, "mode": "EXCEL", "iterate": setting}))
    g = Grid()
    g.jsonload(str(p))
    assert g.iterate is None
    assert any("iterate" in w for w in g.load_warnings)
