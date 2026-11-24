"""Tests for the shared `:item` / `:items` / `:unitem` / `:solve` commands and their undo."""

from __future__ import annotations

from gridcalc import commands as shared
from gridcalc.dataitems import DataItem
from gridcalc.engine import Grid
from gridcalc.modelrun import check_workbook
from gridcalc.undo import UndoManager


def _run(g: Grid, undo: UndoManager, name: str, *args: str, sel=None) -> shared.Result:
    return shared.run(name, g, undo, list(args), sel)


def test_item_defines_name_from_selection(beer: Grid) -> None:
    undo = UndoManager()
    r = _run(beer, undo, "item", "price", sel=(2, 3, 6, 3))
    assert r.ok and r.changed
    assert any(nr.name == "price" for nr in beer.names)
    assert beer.data_items["price"] == DataItem()
    assert undo.undo(beer)
    assert "price" not in beer.data_items
    assert not any(nr.name == "price" for nr in beer.names)


def test_item_on_existing_name_keeps_its_range(beer: Grid) -> None:
    undo = UndoManager()
    before = [(nr.name, nr.c1, nr.r1, nr.c2, nr.r2) for nr in beer.names]
    r = _run(beer, undo, "item", "demand", "Bars", "missing=0", sel=(0, 0, 0, 0))
    assert r.ok
    assert beer.data_items["demand"] == DataItem(("Bars",), 0.0)
    assert [(nr.name, nr.c1, nr.r1, nr.c2, nr.r2) for nr in beer.names] == before


def test_item_indexes_in_one_field(beer: Grid) -> None:
    r = _run(beer, UndoManager(), "item", "costs", "Warehouses Bars")
    assert r.ok
    assert beer.data_items["costs"].index == ("Warehouses", "Bars")


def test_item_errors(beer: Grid) -> None:
    undo = UndoManager()
    assert not _run(beer, undo, "item").ok
    assert "at most two" in _run(beer, undo, "item", "costs", "a", "b", "c").message
    assert "not a usable name" in _run(beer, undo, "item", "A1").message
    assert not undo.undo_stack


def test_items_lists_and_reports_problems(beer: Grid) -> None:
    r = _run(beer, UndoManager(), "items")
    assert r.message == "7 data items, 0 problems"
    assert "costs = Sheet1!C4:G5  [Warehouses, Bars]" in r.lines
    beer.data_items["supply"] = DataItem(("Bars",))
    r = _run(beer, UndoManager(), "items")
    assert any(line.startswith("problem: supply:") for line in r.lines)


def test_unitem_keeps_name_and_undoes(beer: Grid) -> None:
    undo = UndoManager()
    assert _run(beer, undo, "unitem", "COSTS").ok
    assert "costs" not in beer.data_items
    assert any(nr.name == "costs" for nr in beer.names)
    assert not _run(beer, undo, "unitem", "costs").ok
    assert undo.undo(beer)
    assert "costs" in beer.data_items


def test_model_text_undo(beer: Grid) -> None:
    undo = UndoManager()
    undo.save_model(beer)
    beer._active.model_text = "x = 1\n"
    assert undo.undo(beer)
    assert beer._active.model_text == ""
    assert undo.redo(beer)
    assert beer._active.model_text == "x = 1\n"


def test_check_workbook_covers_every_sheet(beer: Grid) -> None:
    assert check_workbook(beer) == []
    beer.add_sheet("Other")
    beer.sheets[1].model_text = "import os\n"
    assert check_workbook(beer) == ["model on Other: import of 'os' is blocked"]


def test_check_workbook_empty_without_models() -> None:
    assert check_workbook(Grid()) == []


def test_commands_listed_for_the_web_palette() -> None:
    names = {c["name"] for c in shared.describe()}
    assert {"item", "items", "unitem"} <= names
    assert "solve" not in names  # each frontend runs it in the background its own way


def test_overlay_boxes(beer: Grid) -> None:
    from gridcalc.dataitems import boxes

    by_name = {b.name: b for b in boxes(beer)}
    costs = by_name["costs"]
    assert (costs.label, costs.sheet, costs.c1, costs.r1, costs.c2, costs.r2) == (
        "costs[Warehouses,Bars]",
        "Sheet1",
        2,
        3,
        6,
        4,
    )
    assert costs.problem == ""
    beer.data_items["supply"] = DataItem(("Bars",))
    assert by_name["supply"].problem == ""
    assert {b.name: b for b in boxes(beer)}["supply"].problem.startswith("supply: 2x1")
