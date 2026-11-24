"""Shared fixtures."""

from __future__ import annotations

import pytest

from gridcalc.dataitems import DataItem
from gridcalc.engine import Grid, Mode, NamedRange


def _name(g: Grid, name: str, c1: int, r1: int, c2: int, r2: int) -> None:
    g.names.append(NamedRange(name=name, c1=c1, r1=r1, c2=c2, r2=r2, sheet=g._active.name))


@pytest.fixture
def beer() -> Grid:
    """SolverStudio's transportation example (TransportationData.png), same cells."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    cells = [(1, 2, "Warehouses\\Bars"), (1, 3, "A"), (1, 4, "B")]
    cells += [(2 + j, 2, str(j + 1)) for j in range(5)]  # C3:G3
    costs = [[2, 4, 5, 2, 1], [3, 1, 3, 2, 3]]
    cells += [(2 + j, 3 + i, str(v)) for i, row in enumerate(costs) for j, v in enumerate(row)]
    cells += [(7, 8, "3100"), (7, 9, "4000")]  # H9:H10 supply
    cells += [(2 + j, 10, str(v)) for j, v in enumerate([500, 900, 1800, 200, 700])]  # C11:G11
    g.setcells_bulk(cells)
    _name(g, "Bars", 2, 2, 6, 2)
    _name(g, "Warehouses", 1, 3, 1, 4)
    _name(g, "costs", 2, 3, 6, 4)
    _name(g, "flow", 2, 8, 6, 9)
    _name(g, "supply", 7, 8, 7, 9)
    _name(g, "demand", 2, 10, 6, 10)
    _name(g, "SolverResult", 1, 13, 1, 13)
    g.data_items = {
        "Bars": DataItem(),
        "Warehouses": DataItem(),
        "costs": DataItem(("Warehouses", "Bars")),
        "flow": DataItem(("Warehouses", "Bars")),
        "supply": DataItem(("Warehouses",)),
        "demand": DataItem(("Bars",)),
        "SolverResult": DataItem(),
    }
    return g
