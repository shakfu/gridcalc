"""MiniZinc models under `minizinc`: the static check, the JSON data, the stream, and full runs."""

from __future__ import annotations

import re
import shutil

import pytest

from gridcalc import minizinc
from gridcalc.dataitems import DataItem
from gridcalc.engine import Grid
from gridcalc.modelrun import ModelError, check_model, run_model, set_backend

needs_minizinc = pytest.mark.skipif(
    shutil.which("minizinc") is None, reason="minizinc not installed"
)

BEER_MZN = """\
% solver: cbc
enum Warehouses;
set of int: Bars;
array[Warehouses, Bars] of int: costs;
array[Warehouses] of int: supply;
array[Bars] of int: demand;
array[Warehouses, Bars] of var 0..10000: flow;
var int: cost ::output = sum(w in Warehouses, b in Bars)(costs[w, b] * flow[w, b]);
constraint forall(w in Warehouses)(sum(b in Bars)(flow[w, b]) <= supply[w]);
constraint forall(b in Bars)(sum(w in Warehouses)(flow[w, b]) >= demand[b]);
solve minimize cost;
"""


# --- the static check -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('include "globals.mzn";', []),
        ('include "/etc/hosts";', ["line 1: include only a library file by name"]),
        ('\ninclude "../x.mzn";', ["line 2: include only a library file by name"]),
        ('include "sub/x.mzn";', ["line 1: include only a library file by name"]),
        ('% include "/etc/hosts"\n/* include "/x" */', []),  # comments
        ('output ["include \\"/x\\""];', []),  # a string
        ("% solver: ../x.msc", ["'% solver: ../x.msc' must name"]),
    ],
)
def test_problems(text: str, expected: list[str]) -> None:
    got = minizinc.problems(text)
    assert len(got) == len(expected)
    assert all(g.startswith(e) for g, e in zip(got, expected, strict=True))


def test_solver_comment() -> None:
    assert minizinc.solver("var int: x;\n  %  solver: org.gecode.gecode\n") == "org.gecode.gecode"
    assert minizinc.solver("var int: x; % solver: cbc") is None  # not on its own line
    assert minizinc.solver("var int: x;") is None


def test_solver_known_by_id_suffix_or_tag() -> None:
    solvers = [{"id": "org.gecode.gecode", "tags": ["cp", "int"]}]
    assert all(minizinc.solver_known(n, solvers) for n in ["org.gecode.gecode", "gecode", "cp"])
    assert not minizinc.solver_known("/opt/x.msc", solvers)
    assert not minizinc.solver_known("chuffed", solvers)


def test_gui_solvers_are_not_known() -> None:
    solvers = [{"id": "org.gecode.gist", "tags": ["cp"], "isGUIApplication": True}]
    assert not minizinc.solver_known("cp", solvers)
    assert not minizinc.solver_known("gist", solvers)


# --- the data file ----------------------------------------------------------


def _items() -> dict[str, dict]:
    return {
        "W": {"kind": "plain", "value": ["Store 1", "B"]},
        "N": {"kind": "plain", "value": [3.0, 1.0, 2.0]},
        "c": {
            "kind": "indexed",
            "index": ["W", "N"],
            "keys": [],
            "values": [[["Store 1", 1], 1.0], [["Store 1", 2], 2.0], [["B", 3], 6.0]],
            "missing": [0],
        },
        "k": {"kind": "plain", "value": 4.0},
        "unused": {"kind": "plain", "value": 1},
    }


def test_data_sets_arrays_and_scalars() -> None:
    inputs = {n: {"type": "int"} for n in ("W", "N", "c", "k")}
    data, errors = minizinc.data(_items(), inputs)
    assert errors == []
    assert data == {
        "W": [{"e": "Store 1"}, {"e": "B"}],  # an enum, any string, in sheet order
        "N": {"set": [1, 2, 3]},  # an int set, ascending
        "c": [[1, 2, 0], [0, 0, 6]],  # missing=0 fills the gaps
        "k": 4,
    }


def test_data_problems() -> None:
    items = _items()
    items["c"]["missing"] = []
    items["k"]["value"] = 2.5
    _, errors = minizinc.data(items, {"c": {"type": "int"}, "k": {"type": "int"}})
    assert "c[('Store 1', 3)] is blank; give the item missing=VALUE" in errors
    assert "k: the model declares int, the cell holds 2.5" in errors


def test_pairs_walks_the_index_orders() -> None:
    got = minizinc.pairs([["A", "B"], [1, 2]], [[1, {"e": "x"}], [True, 0]])
    assert got == [[["A", 1], 1], [["A", 2], "x"], [["B", 1], True], [["B", 2], 0]]
    with pytest.raises(ValueError, match="does not match"):
        minizinc.pairs([["A", "B"]], [1])
    with pytest.raises(ValueError, match="set value"):
        minizinc.plain({"set": [[1, 2]]})


def test_read_stream() -> None:
    text = (
        "hello trace\n"
        '{"type": "interface", "input": {"n": {"type": "int"}}}\n'
        '{"type": "warning", "message": "model inconsistency detected"}\n'
        '{"type": "solution", "output": {"json": {"x": 1, "_objective": 3}}}\n'
        '{"type": "status", "status": "OPTIMAL_SOLUTION"}\n'
    )
    r = minizinc.read_stream(text)
    assert r["solution"] == {"x": 1, "_objective": 3}
    assert r["inputs"] == {"n": {"type": "int"}}
    assert r["status"] == "Optimal"
    assert r["log"] == "hello trace\nmodel inconsistency detected"
    sat = minizinc.read_stream('{"type": "solution", "output": {"json": {"x": 1}}}\n')
    assert sat["status"] == "Feasible"  # no status message after a satisfaction solution


# --- full runs ---------------------------------------------------------------


@pytest.fixture
def mbeer(beer: Grid) -> Grid:
    set_backend(beer._active, "minizinc")
    beer.data_items["flow"] = DataItem(("Warehouses", "Bars"), output=True)
    beer._active.model_text = BEER_MZN
    return beer


@needs_minizinc
def test_beer_fills_output_items(mbeer: Grid) -> None:
    res = run_model(mbeer)
    assert (res.status, res.objective, res.written) == ("Optimal", 8400, 10)
    shipped = [[mbeer.cells[2 + j][8 + i].val for j in range(5)] for i in range(2)]
    assert [sum(c) for c in zip(*shipped, strict=True)] == [500, 900, 1800, 200, 700]
    assert res.log == ""


@needs_minizinc
def test_output_variable_fills_a_singleton(mbeer: Grid) -> None:
    mbeer.data_items["SolverResult"] = DataItem(output=True)
    mbeer._active.model_text = re.sub(r"\bcost\b", "SolverResult", BEER_MZN)
    run_model(mbeer)
    assert mbeer.cells[1][13].val == 8400


@needs_minizinc
def test_keys_with_spaces_are_enum_members(mbeer: Grid) -> None:
    mbeer.setcells_bulk([(1, 3, "Store 1")])  # Warehouses: "A" -> "Store 1"
    res = run_model(mbeer)
    assert res.objective == 8400


@needs_minizinc
def test_satisfaction_model(mbeer: Grid) -> None:
    mbeer.data_items["flow"] = DataItem(("Warehouses", "Bars"))
    mbeer.data_items["SolverResult"] = DataItem(output=True)
    mbeer._active.model_text = (
        '% solver: gecode\ninclude "alldifferent.mzn";\n'
        "var 1..3: SolverResult; var 1..3: b;\n"
        "constraint alldifferent([SolverResult, b]) /\\ SolverResult > b /\\ b > 1;\n"
        'constraint trace("traced\\n", true);\n'
    )
    res = run_model(mbeer)
    assert (res.status, res.objective) == ("Feasible", None)
    assert mbeer.cells[1][13].val == 3
    assert "traced" in res.log


@needs_minizinc
def test_infeasible_writes_nothing(mbeer: Grid) -> None:
    mbeer._active.model_text = BEER_MZN.replace(
        "solve minimize", "constraint sum(flow) <= 1;\nsolve minimize"
    )
    with pytest.raises(ModelError, match=r"flow has no value; the solve did not find one") as exc:
        run_model(mbeer)
    assert exc.value.status == "Infeasible"
    assert mbeer.cells[2][8].text == ""


@needs_minizinc
def test_syntax_error_reports_the_line(mbeer: Grid) -> None:
    mbeer._active.model_text = BEER_MZN.replace("solve minimize cost;", "constraint x > ;")
    with pytest.raises(ModelError, match="syntax error") as exc:
        run_model(mbeer)
    assert exc.value.line == 11


@needs_minizinc
def test_unknown_solver_refused(mbeer: Grid) -> None:
    mbeer._active.model_text = BEER_MZN.replace("% solver: cbc", "% solver: nosuch")
    with pytest.raises(ModelError, match="'% solver: nosuch' is not an installed"):
        run_model(mbeer)


def test_path_include_is_a_problem(mbeer: Grid) -> None:
    mbeer._active.model_text = 'include "/etc/hosts";\n' + BEER_MZN
    assert any("include only a library file" in p for p in check_model(mbeer))


def test_missing_minizinc_is_a_problem(mbeer: Grid, monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert "the minizinc backend needs the minizinc program on PATH" in check_model(mbeer)


def test_backend_sets_the_language(beer: Grid) -> None:
    set_backend(beer._active, "minizinc")
    assert (beer._active.model_backend, beer._active.model_lang) == ("minizinc", "minizinc")


@needs_minizinc
def test_time_limit_writes_the_best_solution_found(mbeer: Grid) -> None:
    # Gecode takes about 70 s to prove this optimal; MiniZinc stops 3 s before the timeout.
    mbeer._active.model_text = BEER_MZN.replace("% solver: cbc", "% solver: gecode")
    res = run_model(mbeer, timeout=5)
    assert res.status == "Feasible"
    assert res.written == 10
    assert res.objective is not None and res.objective >= 8400


# --- the examples ------------------------------------------------------------


def _example(name: str) -> Grid:
    from pathlib import Path

    from gridcalc.loader import load_workbook

    g = load_workbook(Path(__file__).parent.parent / "examples" / name)
    g.python_trusted = True  # trusted fixtures, as the integration tests treat them
    return g


@needs_minizinc
def test_example_transport() -> None:
    g = _example("example_minizinc_transport.json")
    res = run_model(g)
    assert (res.status, res.objective, res.written) == ("Optimal", 8400, 11)
    assert [g.cells[8][9 + i].val for i in range(2)] == [1400, 2700]  # Shipped


@needs_minizinc
def test_example_sudoku() -> None:
    g = _example("example_minizinc_sudoku.json")
    res = run_model(g)
    assert (res.status, res.written) == ("Feasible", 81)
    rows = [[int(g.cells[2 + c][15 + r].val) for c in range(9)] for r in range(9)]
    assert rows[0] == [5, 3, 4, 6, 7, 8, 9, 1, 2]
    assert all(sorted(row) == list(range(1, 10)) for row in rows)
    assert all(sorted(col) == list(range(1, 10)) for col in zip(*rows, strict=True))


@needs_minizinc
def test_example_roster() -> None:
    g = _example("example_minizinc_roster.json")
    res = run_model(g)
    assert (res.status, res.objective) == ("Optimal", 1030)
    staffed = [g.cells[2 + j][17].val for j in range(6)]
    needed = [g.cells[2 + j][8].val for j in range(6)]
    assert all(s >= n for s, n in zip(staffed, needed, strict=True))


def test_trust_preview_names_the_model_language() -> None:
    from pathlib import Path

    from gridcalc.sandbox import inspect_file

    info = inspect_file(
        str(Path(__file__).parent.parent / "examples" / "example_minizinc_sudoku.json")
    )
    assert info is not None
    [(title, lang, text)] = info.code_parts
    assert (title, lang) == ("model on sheet Sudoku", "minizinc")
    assert text.startswith("% Sudoku")
