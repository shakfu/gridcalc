"""The pyomo backend: a sheet's model written with Pyomo (`gridcalc[pyomo]`)."""

from __future__ import annotations

import shutil

import pytest

from gridcalc.dataitems import DataItem
from gridcalc.engine import Grid
from gridcalc.modelrun import ModelError, ModelJob, check_model, run_model, set_backend

pyo = pytest.importorskip("pyomo.environ")
needs_glpsol = pytest.mark.skipif(shutil.which("glpsol") is None, reason="glpsol not installed")

BEER_PYOMO = """\
import pyomo.environ as pyo

m = pyo.ConcreteModel()
m.x = pyo.Var(Warehouses, Bars, within=pyo.NonNegativeIntegers)
m.cost = pyo.Objective(expr=sum(costs[w, b] * m.x[w, b] for w in Warehouses for b in Bars))
m.sup = pyo.Constraint(Warehouses, rule=lambda m, w: sum(m.x[w, b] for b in Bars) <= supply[w])
m.dem = pyo.Constraint(Bars, rule=lambda m, b: sum(m.x[w, b] for w in Warehouses) >= demand[b])
results = pyo.SolverFactory("glpk").solve(m)
"""


@pytest.fixture
def ybeer(beer: Grid) -> Grid:
    set_backend(beer._active, "pyomo")
    return beer


@needs_glpsol
def test_explicit_write_back(ybeer: Grid) -> None:
    ybeer._active.model_text = BEER_PYOMO + (
        "for w in Warehouses:\n"
        "    for b in Bars:\n"
        "        flow[w, b] = pyo.value(m.x[w, b])\n"
        "SolverResult = str(results.solver.termination_condition)\n"
    )
    res = run_model(ybeer)
    assert (res.status, res.objective, res.written) == ("Optimal", 8400, 11)
    assert ybeer.cells[1][13].text == "optimal"


@needs_glpsol
def test_output_bound_to_an_indexed_var(ybeer: Grid) -> None:
    ybeer.data_items["flow"] = DataItem(("Warehouses", "Bars"), output=True)
    ybeer.data_items["SolverResult"] = DataItem(output=True)
    ybeer._active.model_text = BEER_PYOMO + "flow = m.x\nSolverResult = m.cost\n"
    res = run_model(ybeer)
    assert res.written == 11
    shipped = [[ybeer.cells[2 + j][8 + i].val for j in range(5)] for i in range(2)]
    assert [sum(c) for c in zip(*shipped, strict=True)] == [500, 900, 1800, 200, 700]
    assert ybeer.cells[1][13].val == 8400


@needs_glpsol
def test_infeasible_binding_writes_nothing(ybeer: Grid) -> None:
    ybeer.data_items["flow"] = DataItem(("Warehouses", "Bars"), output=True)
    ybeer._active.model_text = (
        BEER_PYOMO.replace(
            "results =",
            "m.none = pyo.Constraint(expr=sum(m.x[w, b] for w in Warehouses for b in Bars) <= 1)\n"
            "results =",
        )
        + "flow = m.x\n"
    )
    with pytest.raises(ModelError, match="has no value"):
        run_model(ybeer)


def test_only_the_pyomo_namespace_is_admitted(ybeer: Grid) -> None:
    ybeer._active.model_text = "import pyomo.environ as pyo\nimport json\n"
    with pytest.raises(ModelError, match="line 2: ImportError: import of 'json'"):
        run_model(ybeer)


def test_writes_outside_the_temp_dir_refused(ybeer: Grid, tmp_path) -> None:
    target = tmp_path / "escape.txt"
    ybeer._active.model_text = "x = 1\n"
    job = ModelJob(ybeer)
    job._request["text"] = f"print.__self__.open({str(target)!r}, 'w')\n"
    job.run()
    with pytest.raises(ModelError, match="may not write files"):
        job.apply(ybeer)
    assert not target.exists()


def test_missing_pyomo_is_a_problem(ybeer: Grid, monkeypatch) -> None:
    from gridcalc import modelrun

    ybeer._active.model_text = "x = 1\n"
    monkeypatch.setattr(modelrun, "_installed", lambda name: False)
    assert "the pyomo backend needs Pyomo: pip install 'gridcalc[pyomo]'" in check_model(ybeer)


def test_backend_sets_the_language(beer: Grid) -> None:
    set_backend(beer._active, "pyomo")
    assert (beer._active.model_backend, beer._active.model_lang) == ("pyomo", "pyomo")


def test_nonlinear_solvers_are_allowed() -> None:
    from gridcalc.modelrun import SOLVER_PROGRAMS

    assert {"ipopt", "bonmin", "couenne"} <= set(SOLVER_PROGRAMS)


@pytest.mark.skipif(shutil.which("ipopt") is None, reason="ipopt not installed")
def test_nonlinear_model_with_ipopt(beer: Grid) -> None:
    set_backend(beer._active, "pyomo")
    beer.data_items["SolverResult"] = DataItem(output=True)
    beer._active.model_text = (
        "import pyomo.environ as pyo\n"
        "m = pyo.ConcreteModel()\n"
        "m.x = pyo.Var(initialize=-1.2)\n"
        "m.y = pyo.Var(initialize=1.0)\n"
        "m.o = pyo.Objective(expr=(1 - m.x) ** 2 + 100 * (m.y - m.x**2) ** 2)  # Rosenbrock\n"
        "results = pyo.SolverFactory('ipopt').solve(m)\n"
        "SolverResult = m.x\n"
    )
    res = run_model(beer)
    assert res.status == "Optimal"
    assert beer.cells[1][13].val == pytest.approx(1.0, abs=1e-5)


def test_only_clearing_the_solver_library_variable_is_allowed() -> None:
    from gridcalc import _modelchild as ch

    old = ch._tmp
    ch._tmp = "/tmp/run"  # a program backend
    try:
        ch._audit("os.putenv", (b"PYOMO_AMPLFUNC", b""))
        ch._audit("os.unsetenv", (b"AMPLFUNC",))
        for args in [
            (b"PYOMO_AMPLFUNC", b"/tmp/run/evil.so"),
            (b"LD_PRELOAD", b"x.so"),
            (b"DYLD_INSERT_LIBRARIES", b"x.dylib"),
            (b"PATH", b"/tmp/run"),
        ]:
            with pytest.raises(PermissionError, match="os.putenv"):
                ch._audit("os.putenv", args)
    finally:
        ch._tmp = old
    with pytest.raises(PermissionError):  # the builtin backend allows none
        ch._audit("os.putenv", (b"PYOMO_AMPLFUNC", b""))
