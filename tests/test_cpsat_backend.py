"""The cpsat backend: a sheet's model written with OR-Tools CP-SAT (`gridcalc[ortools]`)."""

from __future__ import annotations

import os

import pytest

from gridcalc.dataitems import DataItem
from gridcalc.engine import Grid
from gridcalc.modelrun import ModelError, ModelJob, check_model, run_model, set_backend

pytest.importorskip("ortools.sat.python.cp_model")

BEER_CPSAT = """\
from ortools.sat.python import cp_model

m = cp_model.CpModel()
x = {(w, b): m.new_int_var(0, 10000, f"x_{w}_{b}") for w in Warehouses for b in Bars}
m.minimize(sum(costs[w, b] * x[w, b] for w in Warehouses for b in Bars))
for w in Warehouses:
    m.add(sum(x[w, b] for b in Bars) <= supply[w])
for b in Bars:
    m.add(sum(x[w, b] for w in Warehouses) >= demand[b])
solver = cp_model.CpSolver()
solver.solve(m)
"""


@pytest.fixture
def cbeer(beer: Grid) -> Grid:
    set_backend(beer._active, "cpsat")
    return beer


def test_explicit_write_back(cbeer: Grid) -> None:
    cbeer._active.model_text = BEER_CPSAT + (
        "for w in Warehouses:\n"
        "    for b in Bars:\n"
        "        flow[w, b] = solver.value(x[w, b])\n"
        "SolverResult = solver.objective_value\n"
    )
    res = run_model(cbeer)
    assert (res.status, res.objective, res.written) == ("Optimal", 8400, 11)
    assert cbeer.cells[1][13].val == 8400


def test_output_bound_to_a_dict_of_vars(cbeer: Grid) -> None:
    cbeer.data_items["flow"] = DataItem(("Warehouses", "Bars"), output=True)
    cbeer.data_items["SolverResult"] = DataItem(output=True)
    cbeer._active.model_text = (
        BEER_CPSAT + "flow = x\nSolverResult = sum(costs[k] * x[k] for k in x)\n"
    )
    res = run_model(cbeer)
    assert res.written == 11
    shipped = [[cbeer.cells[2 + j][8 + i].val for j in range(5)] for i in range(2)]
    assert [sum(c) for c in zip(*shipped, strict=True)] == [500, 900, 1800, 200, 700]
    assert cbeer.cells[1][13].val == 8400


def test_infeasible_binding_writes_nothing(cbeer: Grid) -> None:
    # After INFEASIBLE, CpSolver.value returns junk rather than raising.
    cbeer.data_items["flow"] = DataItem(("Warehouses", "Bars"), output=True)
    cbeer._active.model_text = (
        BEER_CPSAT.replace("solver =", "m.add(sum(x.values()) <= 1)\nsolver =") + "flow = x\n"
    )
    with pytest.raises(ModelError, match="has no value"):
        run_model(cbeer)
    assert cbeer.cells[2][8].text == ""


def test_satisfaction_model_has_no_objective(cbeer: Grid) -> None:
    cbeer.data_items["SolverResult"] = DataItem(output=True)
    cbeer._active.model_text = (
        "from ortools.sat.python import cp_model\n"
        "m = cp_model.CpModel()\n"
        "SolverResult = m.new_int_var(0, 9, 'v')\n"
        "m.add(SolverResult * 3 == 12)\n"
        "solver = cp_model.CpSolver()\n"
        "solver.solve(m)\n"
    )
    res = run_model(cbeer)
    assert (res.status, res.objective) == ("Optimal", None)
    assert cbeer.cells[1][13].val == 4


def test_whole_cell_numbers_reach_the_model_as_ints(cbeer: Grid) -> None:
    cbeer._active.model_text = "SolverResult = repr((costs['A', 1], supply['A'], Bars[0]))\n"
    run_model(cbeer)
    assert cbeer.cells[1][13].text == "(2, 3100, 1)"


def test_fractional_objective_is_allowed(cbeer: Grid) -> None:
    cbeer.setcells_bulk([(2, 3, "2.5")])  # costs['A', 1]
    cbeer._active.model_text = BEER_CPSAT
    assert run_model(cbeer).status == "Optimal"


def test_fractional_constraint_data_is_cp_sats_error(cbeer: Grid) -> None:
    cbeer.setcells_bulk([(7, 8, "3100.5")])  # supply['A']
    cbeer._active.model_text = BEER_CPSAT
    with pytest.raises(ModelError, match="line 7: TypeError: .*integers only") as exc:
        run_model(cbeer)
    assert "\n" not in str(exc.value)


def test_two_solvers_make_an_output_ambiguous(cbeer: Grid) -> None:
    cbeer.data_items["flow"] = DataItem(("Warehouses", "Bars"), output=True)
    cbeer._active.model_text = BEER_CPSAT + "other = cp_model.CpSolver()\nflow = x\n"
    with pytest.raises(ModelError, match="exactly one solved CpSolver"):
        run_model(cbeer)


def test_search_log_goes_to_the_model_output(cbeer: Grid) -> None:
    cbeer._active.model_text = BEER_CPSAT.replace(
        "solver.solve(m)", "solver.parameters.log_search_progress = True\nsolver.solve(m)"
    )
    res = run_model(cbeer)
    assert "Starting CP-SAT solver" in res.log


@pytest.mark.parametrize("name", ["export_to_file", "ExportToFile"])
def test_export_to_file_refused(cbeer: Grid, tmp_path, name: str) -> None:
    target = tmp_path / "model.pb"
    cbeer._active.model_text = (
        f"from ortools.sat.python import cp_model\ncp_model.CpModel().{name}({str(target)!r})\n"
    )
    with pytest.raises(ModelError, match="line 2: PermissionError: a model may not write files"):
        run_model(cbeer)
    assert not target.exists()


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("import ortools.init\n", "import of 'ortools.init' is not allowed"),
        (
            "from ortools.sat.python import cp_model_helper\n",
            "cannot import name 'cp_model_helper'",
        ),
        ("from ortools.sat.python import cp_model\ncp_model.np\n", "has no 'np'"),
        ("from ortools.sat.python import cp_model\ncp_model.cmh\n", "has no 'cmh'"),
    ],
)
def test_only_the_cp_model_names_are_admitted(cbeer: Grid, text: str, match: str) -> None:
    cbeer._active.model_text = text
    with pytest.raises(ModelError, match=match):
        run_model(cbeer)


def test_import_spellings(cbeer: Grid) -> None:
    cbeer._active.model_text = (
        "import ortools.sat.python.cp_model as a\n"
        "from ortools.sat.python.cp_model import CpModel\n"
        "SolverResult = a.CpModel is CpModel\n"
    )
    run_model(cbeer)
    assert cbeer.cells[1][13].val is True or cbeer.cells[1][13].text.upper() == "TRUE"


def test_writes_refused(cbeer: Grid, tmp_path) -> None:
    target = tmp_path / "escape.txt"
    cbeer._active.model_text = "x = 1\n"
    job = ModelJob(cbeer)
    job._request["text"] = f"print.__self__.open({str(target)!r}, 'w')\n"
    job.run()
    with pytest.raises(ModelError, match="may not write files"):
        job.apply(cbeer)
    assert not target.exists()


def test_cpu_limit_covers_every_core(cbeer: Grid) -> None:
    cbeer._active.model_text = "x = 1\n"
    assert ModelJob(cbeer, timeout=10)._request["cpu_s"] == 10 * (os.cpu_count() or 1)


def test_missing_ortools_is_a_problem(cbeer: Grid, monkeypatch) -> None:
    from gridcalc import modelrun

    cbeer._active.model_text = "x = 1\n"
    monkeypatch.setattr(modelrun, "_installed", lambda name: False)
    assert "the cpsat backend needs OR-Tools: pip install 'gridcalc[ortools]'" in check_model(cbeer)


def test_backend_sets_the_language(beer: Grid) -> None:
    set_backend(beer._active, "cpsat")
    assert (beer._active.model_backend, beer._active.model_lang) == ("cpsat", "cpsat")
