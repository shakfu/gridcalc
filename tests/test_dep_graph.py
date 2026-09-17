"""Dependency-graph invariant across every mutating operation.

The topo engine trusts `_dep_of`/`_subscribers`/`_volatile` while
`_dep_graph_built` is True. Each operation below is followed by two checks:
the graph, when marked built, equals a fresh `_rebuild_dep_graph()`; and after
bumping every number cell through `setcell`, each formula value equals the one
a new workbook built from the same text computes with a full recalc.
"""

from __future__ import annotations

import math

import pytest

from gridcalc import commands as C
from gridcalc.engine import FORMULA, NUM, Grid, Mode, NamedRange
from gridcalc.undo import UndoManager


def _workbook() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.add_sheet("S2")
    g.names.append(NamedRange("Tot", 0, 0, 0, 1))
    g.setcells_bulk(
        [
            (0, 0, "1"),
            (0, 1, "2"),
            (0, 2, "3"),
            (1, 0, "=A1*2"),
            (1, 1, "=SUM(A1:A2)"),
            (2, 0, "=B1+B2"),
            (3, 0, "=SUM(Tot)"),
            (4, 0, "=OFFSET(A1,1,0)"),
            (4, 1, "=E1*10"),
            (5, 0, "=SEQUENCE(2)"),
            (5, 3, "=F2+1"),
        ]
    )
    g.set_active("S2")
    g.setcells_bulk([(0, 0, "=Sheet1!A1+1"), (1, 0, "5"), (1, 1, "=B1*A1")])
    g.set_active(0)
    return g


def _graph(g: Grid) -> tuple[dict, dict, set]:
    return (
        {k: set(v) for k, v in g._dep_of.items() if v},
        {k: set(v) for k, v in g._subscribers.items() if v},
        set(g._volatile),
    )


def _fresh_graph(g: Grid) -> tuple[dict, dict, set]:
    saved = (g._dep_of, g._subscribers, g._volatile, g._spill_blocked, g._dep_graph_built)
    g._dep_of, g._subscribers, g._volatile, g._spill_blocked = {}, {}, set(), set(saved[3])
    try:
        g._rebuild_dep_graph()
        return _graph(g)
    finally:
        g._dep_of, g._subscribers, g._volatile, g._spill_blocked, g._dep_graph_built = saved


def _values(g: Grid) -> dict:
    out = {}
    for s in g.sheets:
        for (c, r), cl in s._cells.items():
            if cl.type == FORMULA:
                v = None if isinstance(cl.val, float) and math.isnan(cl.val) else cl.val
                out[(s.name, c, r)] = (v, cl.sval, cl.err)
    return out


def _oracle(g: Grid) -> dict:
    o = Grid()
    o.mode = g.mode
    o._apply_mode_libs()
    o.sheets[0].name = g.sheets[0].name
    for s in g.sheets[1:]:
        o.add_sheet(s.name)
    o.names = [NamedRange(n.name, n.c1, n.r1, n.c2, n.r2, n.sheet) for n in g.names]
    for i, s in enumerate(g.sheets):
        o.set_active(i)
        for (c, r), cl in s._cells.items():
            if cl.type in (NUM, FORMULA) or cl.text:
                o._setcell_no_recalc(c, r, cl.text)
    o.set_active(0)
    o.recalc()
    return _values(o)


def _check(g: Grid) -> None:
    if g._dep_graph_built:
        assert _graph(g) == _fresh_graph(g)
    if g.mode == Mode.PYTHON:
        return
    active = g.active
    for i, s in enumerate(g.sheets):
        g.set_active(i)
        for (c, r), cl in list(s._cells.items()):
            if cl.type == NUM:
                g.setcell(c, r, str(cl.val + 10))
    g.set_active(active)
    assert _values(g) == _oracle(g)


def _cmd(name: str, *args: str, sel=(0, 0, 0, 0)):
    def op(g: Grid, u: UndoManager) -> None:
        res = C.run(name, g, u, list(args), selection=sel)
        assert res.ok, res.message

    return op


def _setcell(g: Grid, u: UndoManager) -> None:
    u.save_cell(g, 1, 0)
    g.setcell(1, 0, "=A2*3")


def _setcell_clear(g: Grid, u: UndoManager) -> None:
    u.save_cell(g, 1, 1)
    g.setcell(1, 1, "")


def _clear_all(g: Grid, u: UndoManager) -> None:
    u.save_grid(g)
    g.clear_all()


def _clear_all_then_edit(g: Grid, u: UndoManager) -> None:
    _clear_all(g, u)
    g.setcell(0, 0, "7")
    g.setcell(1, 0, "=A1+1")


def _mode_round_trip(g: Grid, u: UndoManager) -> None:
    _cmd("mode", "python")(g, u)
    g.setcell(6, 0, "=B1+1")
    _cmd("mode", "excel")(g, u)


def _mode_attr_round_trip(g: Grid, u: UndoManager) -> None:
    g.mode = Mode.PYTHON
    g.setcell(6, 0, "=B1+1")
    g.mode = Mode.EXCEL
    g.setcell(6, 1, "=G1+1")


def _add_sheet(g: Grid, u: UndoManager) -> None:
    g.add_sheet("S3")
    g.set_active("S3")
    g.setcell(0, 0, "=S2!B2+Sheet1!A2")
    g.set_active(0)


def _rename_sheet(g: Grid, u: UndoManager) -> None:
    g.rename_sheet("S2", "Data")


def _sheet_op(fn):
    """A sheet operation recorded the way both frontends record it."""

    def op(g: Grid, u: UndoManager) -> None:
        u.save_grid(g)
        fn(g)
        g.recalc()

    return op


def _sheet_sequence(g: Grid, u: UndoManager) -> None:
    _sheet_op(lambda g: g.add_sheet("S3"))(g, u)
    g.set_active("S3")
    u.save_cell(g, 0, 0)
    g.setcell(0, 0, "=S2!B2+Sheet1!A2")
    _sheet_op(lambda g: g.rename_sheet("S2", "Data"))(g, u)
    _sheet_op(lambda g: g.add_sheet("S2"))(g, u)
    g.set_active("S2")
    u.save_cell(g, 1, 1)
    g.setcell(1, 1, "=Data!B2*2")
    _sheet_op(lambda g: g.move_sheet("S3", 0))(g, u)
    _cmd("name", "Tot", "A1:A3")(g, u)
    _cmd("mode", "hybrid")(g, u)
    _sheet_op(lambda g: g.remove_sheet("Data"))(g, u)


def _add_name_attr(g: Grid, u: UndoManager) -> None:
    g.names.append(NamedRange("Extra", 0, 1, 0, 2))
    g.setcell(6, 0, "=SUM(Extra)")


OPS = {
    "setcell": _setcell,
    "setcell_clear": _setcell_clear,
    "insrow": _cmd("insrow", sel=(0, 1, 0, 1)),
    "inscol": _cmd("inscol", sel=(1, 0, 1, 0)),
    "delrow": _cmd("delrow", sel=(0, 2, 0, 2)),
    "delcol": _cmd("delcol", sel=(2, 0, 2, 0)),
    "sort": _cmd("sort", "A", "desc", sel=(0, 0, 2, 2)),
    "clear_all": _clear_all,
    "clear_all_then_edit": _clear_all_then_edit,
    "name": _cmd("name", "Tot", "A2:A3"),
    "name_new": _cmd("name", "Other", "A1:A3"),
    "unname": _cmd("unname", "Tot"),
    "name_attr": _add_name_attr,
    "mode_round_trip": _mode_round_trip,
    "mode_attr_round_trip": _mode_attr_round_trip,
    "add_sheet": _add_sheet,
    "rename_sheet": _rename_sheet,
    "add_sheet_undoable": _sheet_op(lambda g: g.add_sheet("S3")),
    "remove_sheet": _sheet_op(lambda g: g.remove_sheet("S2")),
    "remove_active_sheet": _sheet_op(lambda g: g.remove_sheet("Sheet1")),
    "move_sheet": _sheet_op(lambda g: g.move_sheet("S2", 0)),
    "rename_sheet_undoable": _sheet_op(lambda g: g.rename_sheet("Sheet1", "Main")),
    "mode_hybrid": _cmd("mode", "hybrid"),
    "sheet_sequence": _sheet_sequence,
}


@pytest.mark.parametrize("op", OPS.values(), ids=OPS.keys())
def test_graph_matches_rebuild_after_op_undo_redo(op):
    g = _workbook()
    u = UndoManager()
    _check(g)
    op(g, u)
    _check(g)
    while u.undo(g):
        _check(g)
    while u.redo(g):
        _check(g)


def test_clear_all_keeps_other_sheets_deps():
    g = _workbook()
    g.set_active("S2")
    g.setcell(1, 0, "50")
    g.set_active(0)
    g.clear_all()
    g.set_active("S2")
    g.setcell(1, 0, "60")
    assert g.cell(1, 1).val == 60.0 * g.cell(0, 0).val


def test_loaded_workbook_name_then_edit(tmp_path):
    g = _workbook()
    p = tmp_path / "wb.json"
    assert g.jsonsave(str(p)) == 0
    h = Grid()
    assert h.jsonload(str(p)) == 0
    u = UndoManager()
    assert C.run("name", h, u, ["Tot", "A1:A3"]).ok
    _check(h)
