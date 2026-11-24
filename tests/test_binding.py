"""Output data items, filled from the model variable bound to their name."""

from __future__ import annotations

import pytest

from gridcalc import commands as shared
from gridcalc.dataitems import DataItem, validate
from gridcalc.engine import Grid
from gridcalc.modelrun import ModelError, run_model
from gridcalc.undo import UndoManager

# The beer model with no copy loop: `flow` is bound to the variables.
BOUND_MODEL = """\
from pulp import *

prob = LpProblem("Beer", LpMinimize)
flow = LpVariable.dicts("Route", (Warehouses, Bars), 0, None, LpInteger)
prob += lpSum(flow[w][b] * costs[w, b] for w in Warehouses for b in Bars)
for w in Warehouses:
    prob += lpSum(flow[w][b] for b in Bars) <= supply[w]
for b in Bars:
    prob += lpSum(flow[w][b] for w in Warehouses) >= demand[b]
prob.solve()
SolverResult = prob.objective
"""


@pytest.fixture
def bound(beer: Grid) -> Grid:
    beer.data_items["flow"] = DataItem(("Warehouses", "Bars"), output=True)
    beer.data_items["SolverResult"] = DataItem(output=True)
    beer._active.model_text = BOUND_MODEL
    return beer


def _flow(g: Grid) -> list[list[object]]:
    return [[g.cells[2 + j][8 + i].val for j in range(5)] for i in range(2)]


def test_nested_dict_and_expression_bind(bound: Grid) -> None:
    res = run_model(bound)
    assert res.written == 11
    assert [sum(c) for c in zip(*_flow(bound), strict=True)] == [500, 900, 1800, 200, 700]
    assert bound.cells[1][13].val == pytest.approx(8400)


def test_flat_tuple_keyed_dict_binds(bound: Grid) -> None:
    bound._active.model_text = BOUND_MODEL.replace(
        'LpVariable.dicts("Route", (Warehouses, Bars), 0, None, LpInteger)',
        "{(w, b): LpVariable(f'r_{w}_{b}', 0) for w in Warehouses for b in Bars}",
    ).replace("flow[w][b]", "flow[w, b]")
    assert "flow[w, b]" in bound._active.model_text
    assert run_model(bound).written == 11


def test_a_missing_key_refuses_the_write(bound: Grid) -> None:
    bound._active.model_text = (
        "from pulp import *\nx = LpVariable('x', 0)\np = LpProblem()\np += x\np.solve()\n"
        "flow = {('A', 1): x}\n"
    )
    with pytest.raises(ModelError, match=r"flow: no value for key \('A', 2\)"):
        run_model(bound)
    assert _flow(bound)[0][0] in (None, 0, "")


def test_an_unsolved_variable_refuses_the_write(bound: Grid) -> None:
    cap = "prob += lpSum(flow[w][b] for w in Warehouses for b in Bars) <= 1\n"  # infeasible
    bound._active.model_text = BOUND_MODEL.replace("prob.solve()", cap + "prob.solve()")
    with pytest.raises(ModelError, match=r"has no value; the solve did not find one"):
        run_model(bound)


def test_binding_to_a_non_dict_is_refused(bound: Grid) -> None:
    bound._active.model_text = "flow = 3\n"
    with pytest.raises(ModelError, match="bind it to a dict of variables, not int"):
        run_model(bound)


def test_plain_numbers_bind_too(bound: Grid) -> None:
    bound._active.model_text = "flow = {(w, b): 1 for w in Warehouses for b in Bars}\n"
    assert run_model(bound).written == 10
    assert _flow(bound) == [[1] * 5, [1] * 5]


def test_explicit_assignment_still_works_on_an_output(bound: Grid) -> None:
    bound._active.model_text = "flow['A', 1] = 7\n"
    assert run_model(bound).written == 1


def test_rebinding_a_non_output_item_points_at_output(beer: Grid) -> None:
    beer._active.model_text = "flow = {}\n"
    with pytest.raises(ModelError, match="or make it an output item"):
        run_model(beer)


def test_a_set_cannot_be_an_output(beer: Grid) -> None:
    beer.data_items["Bars"] = DataItem(output=True)
    assert any(p.startswith("Bars: a set cannot be an output") for p in validate(beer))


def test_output_flag_round_trips() -> None:
    item = DataItem(("W",), output=True)
    assert item.to_json() == {"index": ["W"], "output": True}
    assert DataItem.from_json(item.to_json()) == item
    assert DataItem().to_json() == {}
    with pytest.raises(Exception, match="output is not true or false"):
        DataItem.from_json({"output": "yes"})


def test_item_command_sets_output(beer: Grid) -> None:
    r = shared.run("item", beer, UndoManager(), ["flow", "Warehouses", "Bars", "output"])
    assert r.ok and r.message == "data item flow[Warehouses, Bars] (output)"
    assert beer.data_items["flow"].output is True


def test_output_shown_in_listing_and_overlay(bound: Grid) -> None:
    from gridcalc.dataitems import boxes

    lines = shared.run("items", bound, UndoManager()).lines
    assert "flow = Sheet1!C9:G10  [Warehouses, Bars]  output" in lines
    labels = {b.name: b.label for b in boxes(bound)}
    assert labels["flow"] == "flow[Warehouses,Bars] out"
    assert labels["costs"] == "costs[Warehouses,Bars]"
