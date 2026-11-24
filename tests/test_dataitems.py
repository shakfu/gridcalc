"""Tests for `gridcalc.dataitems`: cross-tab ranges read as model data and written back."""

from __future__ import annotations

import pytest

from gridcalc.dataitems import (
    DataItem,
    DataItemError,
    ItemDict,
    apply_writes,
    collect_writes,
    read_items,
    validate,
)
from gridcalc.engine import Grid
from gridcalc.undo import UndoManager


def test_reads_each_kind(beer: Grid) -> None:
    assert validate(beer) == []
    items = read_items(beer)
    assert items["Bars"] == [1, 2, 3, 4, 5]
    assert items["Warehouses"] == ["A", "B"]
    assert items["supply"] == {"A": 3100, "B": 4000}  # column orientation
    assert items["demand"] == {1: 500, 2: 900, 3: 1800, 4: 200, 5: 700}  # row orientation
    assert items["costs"][("A", 1)] == 2
    assert items["costs"][("B", 2)] == 1  # first index down, second across
    assert len(items["costs"]) == 10
    assert items["SolverResult"] is None


def test_whole_number_keys_are_ints(beer: Grid) -> None:
    keys = read_items(beer)["demand"].keys()
    assert all(type(k) is int for k in keys)


def test_blank_cells_are_absent_and_missing_policy_applies(beer: Grid) -> None:
    flow = read_items(beer)["flow"]
    assert len(flow) == 0
    with pytest.raises(KeyError, match="is blank"):
        flow["A", 1]
    with pytest.raises(KeyError, match="not in its index"):
        flow["C", 1]
    beer.data_items["flow"] = DataItem(("Warehouses", "Bars"), missing=0)
    flow = read_items(beer)["flow"]
    assert flow["A", 1] == 0.0
    with pytest.raises(KeyError, match="not in its index"):
        flow["C", 1]  # a default covers index keys only


def test_write_outside_index_is_refused(beer: Grid) -> None:
    flow = read_items(beer)["flow"]
    with pytest.raises(DataItemError, match="cannot grow"):
        flow["C", 1] = 5


def test_writes_land_by_key_as_one_undo_step(beer: Grid) -> None:
    items = read_items(beer)
    items["flow"]["A", 1] = 500
    items["flow"]["B", 5] = 700
    writes = collect_writes(items)
    writes["SolverResult"] = "Optimal"
    undo = UndoManager()
    assert apply_writes(beer, writes, undo) == 3
    assert beer.cells[2][8].val == 500  # C9
    assert beer.cells[6][9].val == 700  # G10
    assert beer.cells[1][13].text == "Optimal"  # B14
    assert undo.undo(beer)
    assert beer.cells[2][8] is None or beer.cells[2][8].val in (None, 0, "")
    assert beer.cells[1][13] is None or beer.cells[1][13].text == ""


def test_dependents_recalculate(beer: Grid) -> None:
    beer.setcell(2, 11, "=SUM(C9:G10)")
    apply_writes(beer, {"flow": {("A", 1): 500, ("B", 3): 1800}})
    assert beer.cells[2][11].val == 2300


def test_write_into_formula_is_refused_and_nothing_written(beer: Grid) -> None:
    beer.setcell(3, 8, "=1+1")  # D9 = flow["A", 2]
    with pytest.raises(DataItemError, match="holds a formula"):
        apply_writes(beer, {"flow": {("A", 1): 9, ("A", 2): 9}})
    c9 = beer.cells[2][8]
    assert c9 is None or c9.val in (None, 0, "")


def test_write_errors_are_collected(beer: Grid) -> None:
    with pytest.raises(DataItemError) as exc:
        apply_writes(beer, {"Bars": [1], "nope": 1, "flow": {("Z", 9): 1}, "costs": 3})
    msg = str(exc.value)
    assert "Bars: a set cannot be written" in msg
    assert "nope: not a data item" in msg
    assert "cannot grow" in msg
    assert "costs: write a {key: value} mapping" in msg


def test_non_finite_write_refused(beer: Grid) -> None:
    with pytest.raises(DataItemError, match="not a number"):
        apply_writes(beer, {"flow": {("A", 1): float("nan")}})


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda g: g.setcell(3, 2, "1"), "Bars: duplicate index value 1 at Sheet1!D3"),
        (lambda g: g.setcell(3, 2, ""), "Bars: blank index value at Sheet1!D3"),
        (lambda g: g.setcell(3, 2, "=1/0"), "Bars: #DIV/0! at Sheet1!D3"),
        (
            lambda g: g.data_items.update(costs=DataItem(("Bars", "Warehouses"))),
            "costs: 2x5 does not match indexes Bars x Warehouses (5x2)",
        ),
        (
            lambda g: g.data_items.update(supply=DataItem(("Bars",))),
            "supply: 2x1 does not match index Bars of 5",
        ),
        (lambda g: g.data_items.update(costs=DataItem()), "costs: a 2x5 range needs two indexes"),
        (
            lambda g: g.data_items.update(costs=DataItem(("Nope", "Bars"))),
            "costs: index Nope is not a data item",
        ),
        (
            lambda g: g.data_items.update(demand=DataItem(("supply",))),
            "demand: index supply is itself indexed",
        ),
        (
            lambda g: g.data_items.update(costs=DataItem(("Bars", "Bars", "Bars"))),
            "costs: at most two indexes, got 3",
        ),
        (lambda g: g.data_items.update(gone=DataItem()), "gone: no defined name or cell"),
        (lambda g: g.data_items.update({"class": DataItem()}), "class: not a Python identifier"),
    ],
)
def test_validation_problems(beer: Grid, mutate, expected: str) -> None:
    beer.setcell(1, 0, "x")  # keep Sheet1 named as the default
    mutate(beer)
    problems = validate(beer)
    assert any(p.startswith(expected) for p in problems), problems
    with pytest.raises(DataItemError):
        read_items(beer)


def test_index_shape_must_be_one_dimensional(beer: Grid) -> None:
    beer.data_items["costs"] = DataItem()  # silence the costs shape problem
    beer.data_items["demand"] = DataItem(("costs",))
    assert any(
        p.startswith("costs: an index must be one row or one column") for p in validate(beer)
    )


def test_error_in_value_cell_refuses_read(beer: Grid) -> None:
    beer.setcell(2, 3, "=1/0")  # C4 = costs["A", 1]
    with pytest.raises(DataItemError, match=r"costs: #DIV/0! at Sheet1!C4"):
        read_items(beer)


def test_index_names_match_case_insensitively(beer: Grid) -> None:
    beer.data_items["costs"] = DataItem(("warehouses", "BARS"))
    assert validate(beer) == []
    assert read_items(beer)["costs"]["B", 5] == 3


def test_item_dict_is_a_dict(beer: Grid) -> None:
    costs = read_items(beer)["costs"]
    assert isinstance(costs, dict) and isinstance(costs, ItemDict)
    assert sum(costs.values()) == 26


def test_json_round_trip(beer: Grid, tmp_path) -> None:
    beer.data_items["flow"] = DataItem(("Warehouses", "Bars"), missing=0)
    path = str(tmp_path / "beer.json")
    assert beer.jsonsave(path) == 0
    g = Grid()
    assert g.jsonload(path) == 0
    assert g.data_items == beer.data_items
    assert g.data_items["flow"].missing == 0.0
    assert read_items(g)["costs"]["B", 1] == 3


def test_malformed_entries_dropped_with_warning(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        '{"cells": [], "data_items": {"a": [], "b": {"index": "x"},'
        ' "c": {"missing": [1]}, "d": {"index": ["e"]}}}'
    )
    g = Grid()
    assert g.jsonload(str(path)) == 0
    assert list(g.data_items) == ["d"]
    assert len([w for w in g.load_warnings if w.startswith("data item ")]) == 3


def test_csv_save_reports_data_items_lost(beer: Grid, tmp_path) -> None:
    from gridcalc.loader import save_losses

    assert "data items" in save_losses(beer, str(tmp_path / "x.csv"))
    assert "data items" not in save_losses(beer, str(tmp_path / "x.xlsx"))


def test_write_undo_snapshots_only_the_written_region(beer: Grid) -> None:
    for r in range(100, 600):
        beer.setcell(0, r, str(r))  # cells far from the writes
    undo = UndoManager()
    apply_writes(beer, {"flow": {("A", 1): 5}, "SolverResult": "ok"}, undo)
    e = undo.undo_stack[-1]
    assert e.book is None  # no workbook copy
    assert e.rect == (1, 8, 2, 13)  # B9:C14 covers C9 and B14
    assert undo.undo(beer)
    assert beer.cells[1][13] is None or beer.cells[1][13].text == ""


def test_write_undo_from_another_active_sheet(beer: Grid) -> None:
    beer.add_sheet("Other")
    beer.set_active("Other")
    undo = UndoManager()
    beer.set_active("Sheet1")
    apply_writes(beer, {"SolverResult": "ok"}, undo)
    beer.set_active("Other")
    assert undo.undo(beer)  # goes back to Sheet1 to restore
    assert beer._active.name == "Sheet1"
    assert beer.cells[1][13] is None or beer.cells[1][13].text == ""
