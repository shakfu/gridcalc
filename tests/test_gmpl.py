"""GMPL models under glpsol: the static check, the data file, the report, and full runs."""

from __future__ import annotations

import shutil
import sys

import pytest

from gridcalc import gmpl
from gridcalc.dataitems import DataItem
from gridcalc.engine import Grid, NamedRange
from gridcalc.modelrun import ModelError, check_model, run_model, set_backend

needs_glpsol = pytest.mark.skipif(shutil.which("glpsol") is None, reason="glpsol not installed")

BEER_GMPL = """\
set Warehouses; set Bars;
param costs{Warehouses, Bars}; param supply{Warehouses}; param demand{Bars};
var flow{Warehouses, Bars} >= 0, integer;
minimize cost: sum{w in Warehouses, b in Bars} costs[w,b] * flow[w,b];
s.t. sup{w in Warehouses}: sum{b in Bars} flow[w,b] <= supply[w];
s.t. dem{b in Bars}: sum{w in Warehouses} flow[w,b] >= demand[b];
solve;
printf "flow out of A: %g\\n", sum{b in Bars} flow['A',b];
end;
"""


# --- the static check -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            'table t OUT "CSV" "out.csv": W -> [w];',
            ["line 1: a model may not use table statements"],
        ),
        ('printf "x" > "f.txt";', ["line 1: a model may not send output to a file"]),
        ('display x >> "f.txt";', ["line 1: a model may not send output to a file"]),
        ("s.t. c: x > 3;\nvar x;", []),  # a comparison, not a redirect
        ('/* table */ # table\nprintf "> table";', []),  # comments and strings
    ],
)
def test_problems(text: str, expected: list[str]) -> None:
    assert gmpl.problems(text) == expected


def test_declared_names() -> None:
    assert gmpl.declared(BEER_GMPL) == {
        "Warehouses": "set",
        "Bars": "set",
        "costs": "param",
        "supply": "param",
        "demand": "param",
    }


# --- the data file ----------------------------------------------------------


def test_data_file() -> None:
    items = {
        "W": {"kind": "plain", "value": ["A", "New York"], "output": False},
        "rate": {"kind": "plain", "value": 0.5, "output": False},
        "c": {
            "kind": "indexed",
            "keys": [["A", 1]],
            "values": [[["A", 1], 2.0], [["New York", 1], 3.5]],
            "missing": [0.0],
            "output": False,
        },
        "flow": {"kind": "indexed", "keys": [], "values": [], "missing": [], "output": True},
        "unused": {"kind": "plain", "value": 1, "output": False},
    }
    decl = {"W": "set", "rate": "param", "c": "param", "flow": "param"}
    text, errors = gmpl.data_file(items, decl)
    assert errors == []
    assert text == (
        "data;\n"
        "set W := 'A' 'New York';\n"
        "param rate := 0.5;\n"
        "param c default 0 :=\n  'A' 1 2\n  'New York' 1 3.5;\n"
        "end;\n"
    )


def test_data_file_mismatches() -> None:
    items = {
        "s": {"kind": "plain", "value": 3, "output": False},
        "p": {"kind": "plain", "value": [1, 2], "output": False},
        "i": {"kind": "indexed", "keys": [], "values": [], "missing": [], "output": False},
    }
    _, errors = gmpl.data_file(items, {"s": "set", "p": "param", "i": "set"})
    assert errors == [
        "s: a set must come from a row or column of values",
        "p: declared as a param, but it is a set of values",
        "i: an indexed data item must be declared as a param",
    ]


def test_symbols() -> None:
    assert [gmpl.symbol(v) for v in (1, 2.0, 2.5, "it's", True)] == [
        "1",
        "2",
        "2.5",
        "'it''s'",
        "1",
    ]


# --- the report -------------------------------------------------------------

REPORT = """\
Status:     INTEGER OPTIMAL
Objective:  total_cost = 6 (MINimum)

   No.   Row name        Activity     Lower bound   Upper bound
------ ------------    ------------- ------------- -------------
     1 total_cost                  6

   No. Column name       Activity     Lower bound   Upper bound
------ ------------    ------------- ------------- -------------
     1 shipment_quantity['New York',1]
                                   1             0
     2 x['a b']                  2.5             0
     3 y            *              3             0

Integer feasibility conditions:
"""


def test_read_report() -> None:
    r = gmpl.read_report(REPORT)
    assert r["status"] == "INTEGER OPTIMAL"
    assert r["objective"] == ("total_cost", 6.0)
    assert r["columns"] == {"shipment_quantity['New York',1]": 1.0, "x['a b']": 2.5, "y": 3.0}


def test_parse_name() -> None:
    assert gmpl.parse_name("shipment_quantity['New York',1]") == (
        "shipment_quantity",
        ("New York", 1),
    )
    assert gmpl.parse_name("flow[A,1]") == ("flow", ("A", 1))
    assert gmpl.parse_name("d[2]") == ("d", 2)
    assert gmpl.parse_name("y") == ("y", None)
    assert gmpl.parse_name("q['it''s']") == ("q", "it's")


@pytest.mark.parametrize(
    ("status", "text"),
    [
        ("OPTIMAL", "Optimal"),
        ("INTEGER OPTIMAL", "Optimal"),
        ("INFEASIBLE (FINAL)", "Infeasible"),
        ("INTEGER EMPTY", "Infeasible"),
        ("UNBOUNDED", "Unbounded"),
        ("UNDEFINED", "Undefined"),
    ],
)
def test_status_text(status: str, text: str) -> None:
    assert gmpl.status_text(status) == text


# --- full runs --------------------------------------------------------------


@pytest.fixture
def gbeer(beer: Grid) -> Grid:
    set_backend(beer._active, "gmpl")
    beer._active.model_text = BEER_GMPL
    beer.data_items["flow"] = DataItem(("Warehouses", "Bars"), output=True)
    beer.names.append(NamedRange("cost", 1, 14, 1, 14, sheet=beer._active.name))
    beer.data_items["cost"] = DataItem(output=True)
    return beer


@needs_glpsol
def test_beer_model_in_gmpl(gbeer: Grid) -> None:
    res = run_model(gbeer)
    assert (res.status, res.objective, res.written) == ("Optimal", 8400, 11)
    assert "flow out of A: 1200" in res.log  # printf output reaches the log
    shipped = [[gbeer.cells[2 + j][8 + i].val for j in range(5)] for i in range(2)]
    assert [sum(c) for c in zip(*shipped, strict=True)] == [500, 900, 1800, 200, 700]
    assert gbeer.cells[1][14].val == 8400  # the objective, by name


@needs_glpsol
def test_syntax_error_reports_its_line(gbeer: Grid) -> None:
    gbeer._active.model_text = "set Warehouses;\nparam x := ;\nend;\n"
    with pytest.raises(ModelError) as exc:
        run_model(gbeer)
    assert exc.value.line == 2


@needs_glpsol
def test_infeasible_writes_nothing(gbeer: Grid) -> None:
    cap = "s.t. none: sum{w in Warehouses, b in Bars} flow[w,b] <= 1;\n"
    gbeer._active.model_text = BEER_GMPL.replace("solve;", cap + "solve;")
    with pytest.raises(
        ModelError, match=r"flow has no value; the solve did not find one \(Infeasible\)"
    ):
        run_model(gbeer)


@needs_glpsol
def test_output_without_a_matching_variable(gbeer: Grid) -> None:
    gbeer.data_items["SolverResult"] = DataItem(output=True)
    with pytest.raises(ModelError, match="SolverResult: the model has no variable or objective"):
        run_model(gbeer)


@needs_glpsol
def test_three_dimensional_table_item() -> None:
    from gridcalc import commands as shared
    from gridcalc.undo import UndoManager

    g = Grid()
    rows = [("w", "b", "m", "cap")] + [
        (w, str(b), m, str(b * 10)) for w in "AB" for b in (1, 2) for m in ("jan", "feb")
    ]
    rows[0] = ("w", "b", "m", "cap")
    g.setcells_bulk([(c, r, v) for r, row in enumerate(rows) for c, v in enumerate(row)])
    assert shared.run("table", g, UndoManager(), ["Caps"], (0, 0, 3, len(rows) - 1)).ok
    g.setcells_bulk([(5, 0, "w"), (6, 0, "b"), (7, 0, "m"), (8, 0, "x")])
    g.setcells_bulk(
        [(5 + c, 1 + r, v) for r, row in enumerate(rows[1:]) for c, v in enumerate(row[:3])]
    )
    assert shared.run("table", g, UndoManager(), ["Plan"], (5, 0, 8, len(rows) - 1)).ok
    g.data_items = {"cap": DataItem(table="Caps"), "x": DataItem(table="Plan", output=True)}
    set_backend(g._active, "gmpl")
    g._active.model_text = """\
set W := {'A', 'B'}; set B := {1, 2}; set M := {'jan', 'feb'};
param cap{W, B, M};
var x{w in W, b in B, m in M} >= 0, <= cap[w, b, m];
maximize total: sum{w in W, b in B, m in M} x[w, b, m];
end;
"""
    res = run_model(g)
    assert res.written == 8
    assert g.cells[8][2].val == 10  # (A, 1, feb)


def test_static_check_and_missing_glpsol(gbeer: Grid, monkeypatch) -> None:
    gbeer._active.model_text = 'printf "x" > "/tmp/out.txt";\nend;\n'
    assert "model on Sheet1: line 1: a model may not send output to a file" in check_model(gbeer)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert "the gmpl backend needs glpsol from GLPK on PATH" in check_model(gbeer)


def test_backend_sets_the_language(beer: Grid) -> None:
    set_backend(beer._active, "gmpl")
    assert beer._active.model_lang == "gmpl"
    beer._active.model_text = "this is not python\nend;\n"
    assert check_model(beer) == [] or all("glpsol" in p for p in check_model(beer))
    set_backend(beer._active, "builtin")
    assert beer._active.model_lang == "pulp"


@needs_glpsol
@pytest.mark.skipif(sys.platform != "darwin", reason="the OS layer is macOS only")
def test_macos_stops_a_redirect_the_check_missed(gbeer: Grid, tmp_path) -> None:
    from gridcalc.modelrun import ModelJob

    target = tmp_path / "escaped.txt"
    gbeer._active.model_text = "end;\n"
    job = ModelJob(gbeer)
    job._request["text"] = f'printf "x" > "{target}";\nend;\n'  # after the static check
    job.run()
    with pytest.raises(ModelError):
        job.apply(gbeer)
    assert not target.exists()
