"""Long-format data items: rows of an Excel table, keyed by its key columns."""

from __future__ import annotations

import pytest

from gridcalc import commands as shared
from gridcalc.dataitems import DataItem, DataItemError, apply_writes, boxes, read_items, validate
from gridcalc.engine import Grid, Mode
from gridcalc.modelrun import run_model
from gridcalc.undo import UndoManager

COSTS = [[2, 4, 5, 2, 1], [3, 1, 3, 2, 3]]

# The beer model over long-format tables: sets come from table columns.
LONG_MODEL = """\
from pulp import *

prob = LpProblem("Beer", LpMinimize)
flow = {(w, b): LpVariable(f"r_{w}_{b}", 0) for (w, b) in cost}
prob += lpSum(flow[k] * cost[k] for k in cost)
for w in Warehouses:
    prob += lpSum(flow[w, b] for b in Bars) <= supply[w]
for b in Bars:
    prob += lpSum(flow[w, b] for w in Warehouses) >= demand[b]
prob.solve()
"""


def _run(g: Grid, name: str, *args: str, sel=None) -> shared.Result:
    return shared.run(name, g, UndoManager(), list(args), sel)


@pytest.fixture
def long() -> Grid:
    """Routes in A1:D11 (Warehouse, Bar, cost, flow), supply F1:G3, demand I1:J6."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    cells = [(0, 0, "Warehouse"), (1, 0, "Bar"), (2, 0, "cost"), (3, 0, "flow")]
    r = 1
    for i, w in enumerate("AB"):
        for j in range(5):
            cells += [(0, r, w), (1, r, str(j + 1)), (2, r, str(COSTS[i][j]))]
            r += 1
    cells += [(5, 0, "Warehouse"), (6, 0, "supply"), (5, 1, "A"), (6, 1, "3100")]
    cells += [(5, 2, "B"), (6, 2, "4000"), (8, 0, "Bar"), (9, 0, "demand")]
    cells += [(8, 1 + j, str(j + 1)) for j in range(5)]
    cells += [(9, 1 + j, str(d)) for j, d in enumerate([500, 900, 1800, 200, 700])]
    g.setcells_bulk(cells)
    assert _run(g, "table", "Routes", sel=(0, 0, 3, 10)).ok
    assert _run(g, "table", "Supply", sel=(5, 0, 6, 2)).ok
    assert _run(g, "table", "Demand", sel=(8, 0, 9, 5)).ok
    g.data_items = {
        "cost": DataItem(table="Routes", keys=("Warehouse", "Bar"), value="cost"),
        "flow": DataItem(table="Routes", keys=("Warehouse", "Bar"), value="flow", output=True),
        "Warehouses": DataItem(table="Routes", column="Warehouse"),
        "Bars": DataItem(table="Demand", column="Bar"),
        "supply": DataItem(table="Supply"),
        "demand": DataItem(table="Demand"),
    }
    return g


# --- :table -----------------------------------------------------------------


def test_table_command_makes_a_table() -> None:
    g = Grid()
    g.setcells_bulk([(0, 0, "a"), (1, 0, ""), (2, 0, "a"), (3, 0, "7"), (0, 1, "1")])
    undo = UndoManager()
    r = shared.run("table", g, undo, ["Sales"], (0, 0, 3, 2))
    assert r.ok and r.message == "table Sales: a, Column1, a2, 7"
    t = g.tables[0]
    assert (t.name, t.c1, t.r1, t.c2, t.r2, t.columns) == (
        "Sales",
        0,
        0,
        3,
        2,
        ["a", "Column1", "a2", "7"],
    )
    assert g.cells[1][0].text == '"Column1'  # a blank header gets its name, as text
    assert g.cells[3][0].text == '"7'  # a number header becomes text
    assert undo.undo(g)
    assert g.tables == []
    assert g.cells[1][0] is None or g.cells[1][0].text == ""


@pytest.mark.parametrize(
    ("args", "sel", "message"),
    [
        (["1x"], (0, 0, 1, 1), "not a usable table name"),
        (["A1"], (0, 0, 1, 1), "not a usable table name"),
        (["T"], (0, 0, 1, 0), "header row and at least one row"),
        (["Routes"], (12, 0, 13, 3), "already a table or a defined name"),
        (["T"], (2, 5, 4, 12), "overlaps table Routes"),
    ],
)
def test_table_command_refusals(long: Grid, args, sel, message) -> None:
    r = shared.run("table", long, UndoManager(), args, sel)
    assert not r.ok and message in r.message


# --- reading ----------------------------------------------------------------


def test_reads_keys_values_and_column_sets(long: Grid) -> None:
    assert validate(long) == []
    items = read_items(long)
    assert items["cost"][("A", 1)] == 2 and items["cost"][("B", 2)] == 1
    assert len(items["cost"]) == 10
    assert items["Warehouses"] == ["A", "B"]  # distinct, in row order
    assert items["Bars"] == [1, 2, 3, 4, 5]
    assert items["supply"] == {"A": 3100, "B": 4000}  # one key column: scalar keys
    assert len(items["flow"]) == 0  # blank values are absent
    with pytest.raises(KeyError, match="is blank"):
        items["flow"]["A", 1]


def test_default_keys_are_all_but_the_last_column(long: Grid) -> None:
    long.data_items["three"] = DataItem(table="Routes")  # keys W, Bar, cost; value flow
    keys = read_items(long)["three"].index_keys
    assert ("A", 1, 2) in keys


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (DataItem(table="Nope"), "x: no table Nope"),
        (DataItem(table="Routes", value="price"), "x: table Routes has no column price"),
        (DataItem(table="Routes", keys=("Bar",), value="Bar"), "x: column Bar is both a key"),
        (DataItem(table="Routes", column="Warehouse", output=True), "x: a set cannot be an output"),
        (DataItem(table="Routes", keys=("Bar",)), "x: duplicate key 1 in rows 2 and 7"),
    ],
)
def test_table_item_problems(long: Grid, item, expected) -> None:
    long.data_items["x"] = item
    assert any(p.startswith(expected) for p in validate(long)), validate(long)


def test_blank_key_is_a_problem(long: Grid) -> None:
    long.setcell(1, 3, "")  # B4: Bar of the third route
    assert any("blank or error key in row 4" in p for p in validate(long))


def test_table_item_cannot_index_a_range(long: Grid) -> None:
    from gridcalc.engine import NamedRange

    long.names.append(NamedRange("dem", 9, 1, 9, 5, sheet=long._active.name))
    long.data_items["dem"] = DataItem(("Bars",))
    assert any("index Bars is a table item; use a range" in p for p in validate(long))


def test_case_insensitive_names(long: Grid) -> None:
    long.data_items["cost"] = DataItem(table="ROUTES", keys=("warehouse", "BAR"), value="Cost")
    assert validate(long) == []


# --- writing ----------------------------------------------------------------


def test_writes_land_in_the_rows_value_cell(long: Grid) -> None:
    undo = UndoManager()
    assert apply_writes(long, {"flow": {("A", 2): 9, ("B", 5): 4}}, undo) == 2
    assert long.cells[3][2].val == 9  # D3: row of (A, 2)
    assert long.cells[3][10].val == 4  # D11: row of (B, 5)
    assert undo.undo(long)
    assert long.cells[3][2] is None or long.cells[3][2].val in (None, 0, "")


def test_write_refusals(long: Grid) -> None:
    with pytest.raises(DataItemError) as exc:
        apply_writes(long, {"flow": {("C", 1): 1}, "Warehouses": {"A": 1}, "cost": 3})
    msg = str(exc.value)
    assert "flow[('C', 1)] is not a row of table Routes" in msg
    assert "Warehouses: a set cannot be written" in msg
    assert "cost: write a {key: value} mapping to a table item" in msg


def test_long_format_model_solves_and_binds(long: Grid) -> None:
    long.data_items["Bars"] = DataItem(table="Demand", column="Bar")
    long._active.model_text = LONG_MODEL
    res = run_model(long)
    assert res.status == "Optimal" and res.objective == pytest.approx(8400)
    assert res.written == 10
    shipped = sum(long.cells[3][r].val for r in range(1, 11))
    assert shipped == 4100


def test_three_dimensions() -> None:
    g = Grid()
    rows = [("W", "B", "M", "x")] + [
        (w, str(b), m, "") for w in "AB" for b in (1, 2) for m in ("jan", "feb")
    ]
    g.setcells_bulk([(c, r, v) for r, row in enumerate(rows) for c, v in enumerate(row)])
    assert _run(g, "table", "T", sel=(0, 0, 3, len(rows) - 1)).ok
    g.data_items = {"x": DataItem(table="T", output=True)}
    g._active.model_text = (
        "x = {(w, b, m): b * 2.0 for w in 'AB' for b in (1, 2) for m in ('jan', 'feb')}\n"
    )
    assert run_model(g).written == 8
    assert g.cells[3][2].val == 2.0  # (A, 1, feb)


# --- command, storage, overlay ------------------------------------------------


def test_item_command_with_a_table(long: Grid) -> None:
    r = _run(long, "item", "c2", 'table=Routes keys="Warehouse,Bar" value=cost output')
    assert r.ok and r.message == "data item c2 from table Routes"
    assert long.data_items["c2"] == DataItem(
        table="Routes", keys=("Warehouse", "Bar"), value="cost", output=True
    )
    assert not _run(long, "item", "c3", "Bars", "table=Routes").ok  # index and table
    assert "need a table" in _run(long, "item", "c4", "keys=a").message
    assert "takes no keys or value" in _run(long, "item", "c5", "table=T column=a value=b").message


def test_table_items_round_trip(long: Grid, tmp_path) -> None:
    from gridcalc.loader import load_workbook, save_workbook

    for name in ("t.json", "t.xlsx"):
        path = str(tmp_path / name)
        save_workbook(long, path)
        g = load_workbook(path)
        assert g.data_items == long.data_items, name
        assert read_items(g)["cost"][("B", 3)] == 3


def test_overlay_covers_the_table(long: Grid) -> None:
    by = {b.name: b for b in boxes(long)}
    flow = by["flow"]
    assert flow.label == "flow[Warehouse,Bar] out"
    assert (flow.c1, flow.r1, flow.c2, flow.r2) == (0, 0, 3, 10)
    assert by["Warehouses"].label == "Warehouses"


def test_quoted_column_names_with_spaces() -> None:
    g = Grid()
    g.setcells_bulk([(0, 0, "From WH"), (1, 0, "unit cost"), (0, 1, "A"), (1, 1, "2")])
    assert _run(g, "table", "R", sel=(0, 0, 1, 1)).ok
    # As the desktop dialog sends it: one field per argument, quoted where needed.
    r = _run(g, "item", "c", "table=R", 'keys="From WH"', 'value="unit cost"')
    assert r.ok, r.message
    assert g.data_items["c"] == DataItem(table="R", keys=("From WH",), value="unit cost")
    assert read_items(g)["c"] == {"A": 2}
