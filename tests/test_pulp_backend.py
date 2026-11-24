"""The pulp backend: a sheet's model run under the PuLP library (`gridcalc[pulp]`)."""

from __future__ import annotations

import os
import sys

import pytest

from gridcalc.engine import Grid
from gridcalc.modelrun import ModelError, ModelJob, check_model, run_model
from gridcalc.undo import UndoManager
from tests.test_lpmodel import BEER_MODEL

pulp = pytest.importorskip("pulp")


@pytest.fixture
def pbeer(beer: Grid) -> Grid:
    beer._active.model_backend = "pulp"
    return beer


def test_beer_model_solves_with_cbc(pbeer: Grid) -> None:
    pbeer._active.model_text = BEER_MODEL + "print(prob.solver.name)\n"
    res = run_model(pbeer)
    assert res.status == "Optimal"
    assert res.objective == pytest.approx(8400)
    assert res.written == 11
    assert res.log == "PULP_CBC_CMD\n"


def test_duals_come_from_pulp(pbeer: Grid) -> None:
    pbeer._active.model_text = (
        "from pulp import *\n"
        "x = LpVariable('x', 0)\n"
        "p = LpProblem('p', LpMaximize)\n"
        "p += 3 * x\n"
        "p += x <= 4, 'cap'\n"
        "p.solve(PULP_CBC_CMD(msg=0))\n"
        "SolverResult = p.constraints['cap'].pi\n"
    )
    run_model(pbeer)
    assert pbeer.cells[1][13].val == pytest.approx(3.0)


def test_temp_dir_is_removed(pbeer: Grid) -> None:
    pbeer._active.model_text = BEER_MODEL
    job = ModelJob(pbeer)
    job.run()
    tmp = job._request["tmp"]
    assert job.apply(pbeer).status == "Optimal"
    assert not os.path.exists(tmp)


# --- confinement with the pulp backend's exceptions -----------------------

_OPEN = "print.__self__.open"
_IMPORT = "print.__self__.__import__"


def test_writes_outside_its_temp_dir_are_refused(pbeer: Grid, tmp_path) -> None:
    target = tmp_path / "escape.txt"
    pbeer._active.model_text = "x = 1\n"
    # The parent's validator would stop the dunder first, so swap the text in
    # after the checks: this is what the child's own layers must stop.
    job = ModelJob(pbeer)
    job._request["text"] = f"{_OPEN}({str(target)!r}, 'w')\n"
    job.run()
    with pytest.raises(ModelError, match="may not write files"):
        job.apply(pbeer)
    assert not target.exists()


def test_unlisted_programs_are_refused(pbeer: Grid, tmp_path) -> None:
    target = tmp_path / "ran.txt"
    pbeer._active.model_text = "x = 1\n"
    job = ModelJob(pbeer)
    job._request["text"] = f"{_IMPORT}('subprocess').run(['/usr/bin/touch', {str(target)!r}])\n"
    job.run()
    with pytest.raises(ModelError, match="may not use subprocess.Popen"):
        job.apply(pbeer)
    assert not target.exists()


def test_network_still_refused(pbeer: Grid) -> None:
    pbeer._active.model_text = "x = 1\n"
    job = ModelJob(pbeer)
    job._request["text"] = f"{_IMPORT}('socket').create_connection(('127.0.0.1', 9), 2)\n"
    job.run()
    with pytest.raises(ModelError, match="may not use socket"):
        job.apply(pbeer)


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS only")
def test_macos_pulp_profile(tmp_path) -> None:
    import subprocess

    from gridcalc.modelrun import _child_argv

    tmp = tmp_path / "run"
    tmp.mkdir()
    argv = _child_argv("pulp", str(tmp))
    head = argv[: argv.index(sys.executable)]

    def py(code: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*head, sys.executable, "-I", "-B", "-c", code], capture_output=True, text=True
        )

    assert py(f"open({str(tmp / 'ok.txt')!r}, 'w').write('x')").returncode == 0
    assert (tmp / "ok.txt").exists()
    assert py(f"open({str(tmp_path / 'no.txt')!r}, 'w')").returncode != 0
    assert not (tmp_path / "no.txt").exists()
    assert py("import subprocess; subprocess.run(['/bin/echo'])").returncode != 0
    cbc = pulp.PULP_CBC_CMD().path
    assert py(f"import subprocess; subprocess.run([{cbc!r}, '-quit'], check=True)").returncode == 0


# --- checks, storage, undo ------------------------------------------------


def test_unknown_backend_and_missing_pulp(beer: Grid, monkeypatch) -> None:
    from gridcalc import modelrun

    beer._active.model_text = "x = 1\n"
    beer._active.model_backend = "gurobi"
    assert any("backend 'gurobi' is not one of" in p for p in check_model(beer))
    beer._active.model_backend = "pulp"
    monkeypatch.setattr(modelrun, "_pulp_dir", lambda: None)
    assert "the pulp backend needs PuLP: pip install 'gridcalc[pulp]'" in check_model(beer)


def test_pulp_4_is_refused(monkeypatch) -> None:
    import types

    from gridcalc import _modelchild

    monkeypatch.setitem(sys.modules, "pulp", types.SimpleNamespace(__version__="4.3.1"))
    with pytest.raises(ImportError, match="PuLP 4.3.1 is a different API"):
        _modelchild._setup_pulp({"tmp": "/tmp"})


def test_backend_saved_and_undone(pbeer: Grid, tmp_path) -> None:
    from gridcalc.loader import load_workbook, save_workbook
    from gridcalc.sandbox import LoadPolicy, inspect_file

    pbeer._active.model_text = "x = 1\n"
    for name in ("m.json", "m.xlsx"):
        path = str(tmp_path / name)
        save_workbook(pbeer, path)
        info = inspect_file(path)
        assert info is not None
        g = load_workbook(path, LoadPolicy.trust_all(digest=info.digest))
        assert g._active.model_backend == "pulp", name
    undo = UndoManager()
    undo.save_model(pbeer)
    pbeer._active.model_backend = "builtin"
    assert undo.undo(pbeer)
    assert pbeer._active.model_backend == "pulp"


def test_builtin_backend_is_not_saved(beer: Grid) -> None:
    beer._active.model_text = "x = 1\n"
    assert beer._active.model_json() == {"lang": "pulp", "text": "x = 1\n"}


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="no process groups")
def test_kill_reaches_a_grandchild() -> None:
    import subprocess
    import time

    from gridcalc.modelrun import _kill

    proc = subprocess.Popen(
        ["/bin/sh", "-c", "sleep 30 & echo $!; wait"],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    grandchild = int(proc.stdout.readline())  # type: ignore[union-attr]
    _kill(proc)
    proc.wait(5)
    for _ in range(50):
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("the grandchild outlived the kill")


def test_binding_with_the_pulp_library(pbeer: Grid) -> None:
    from gridcalc.dataitems import DataItem
    from tests.test_binding import BOUND_MODEL

    pbeer.data_items["flow"] = DataItem(("Warehouses", "Bars"), output=True)
    pbeer.data_items["SolverResult"] = DataItem(output=True)
    pbeer._active.model_text = BOUND_MODEL.replace(
        "prob.solve()", "prob.solve(PULP_CBC_CMD(msg=0))"
    )
    assert run_model(pbeer).written == 11
    assert pbeer.cells[1][13].val == pytest.approx(8400)
