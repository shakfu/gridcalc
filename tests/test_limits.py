"""Limits that keep a crafted formula from hanging or crashing a load."""

import pytest

from gridcalc import engine
from gridcalc.engine import Grid, Mode
from gridcalc.formula.errors import ExcelError


def _excel() -> Grid:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    return g


@pytest.mark.parametrize(
    ("formula", "message"),
    [
        ("=" + "(" * 65 + "1" + ")" * 65, "nested more than 64 levels deep"),
        ("=" + "ABS(" * 65 + "1" + ")" * 65, "nested more than 64 levels deep"),
        ("=" + "-" * 65 + "1", "more than 64 signs in a row"),
        ("=" + "1+" * 4100 + "1", "longer than 8192 characters"),
    ],
)
def test_formulas_past_excels_limits_are_refused(formula, message) -> None:
    g = _excel()
    g.setcell(0, 0, formula)
    assert g.cell(0, 0).err is ExcelError.NAME
    assert g.cell(0, 0).err_msg == f"syntax error: {message}"


def test_excels_limits_themselves_are_accepted() -> None:
    g = _excel()
    g.setcell(0, 0, "=" + "ABS(" * 64 + "-1" + ")" * 64)
    assert g.cell(0, 0).val == 1.0


def test_a_long_flat_sum_does_not_recurse() -> None:
    g = _excel()
    g.setcells_bulk([(1, r, "1") for r in range(1500)])
    g.setcell(0, 0, "=" + "+".join(f"B{r + 1}" for r in range(1500)))
    assert g.cell(0, 0).val == 1500.0
    g.setcell(1, 7, "10")
    assert g.cell(0, 0).val == 1509.0


def test_runaway_recursion_is_an_error_with_a_reason() -> None:
    g = _excel()
    g.setcell(0, 0, "=LET(f,LAMBDA(f,n,IF(n=0,0,1+f(f,n-1))),f(f,100000))")
    assert g.cell(0, 0).err is ExcelError.NUM
    assert g.cell(0, 0).err_msg == "nested or recursive too deeply"


def test_a_recalc_stops_at_its_time_limit(monkeypatch) -> None:
    monkeypatch.setattr(engine, "RECALC_TIME_LIMIT", 0.2)
    g = _excel()
    g.setcells_bulk(
        [
            (0, 0, "=SUM(MAKEARRAY(1000,1000,LAMBDA(r,c,SUM(SEQUENCE(1000)))))"),
            (1, 0, "=ISERROR(A1)"),  # runs after A1; TRUE were it evaluated
        ]
    )
    for pos in ((0, 0), (1, 0)):
        cl = g.cell(*pos)
        assert cl.err is ExcelError.CALC
        assert cl.err_msg == "calculation stopped after 0.2 s"
    monkeypatch.setattr(engine, "RECALC_TIME_LIMIT", 30.0)
    g.setcell(1, 0, "=1+2")
    assert g.cell(1, 0).val == 3.0


def test_a_column_lifted_against_a_row_is_capped() -> None:
    g = _excel()
    g.setcell(0, 0, "=SUM(ROUND(SEQUENCE(2000),TRANSPOSE(SEQUENCE(2000))))")
    assert g.cell(0, 0).err is ExcelError.NUM
    assert g.cell(0, 0).err_msg == "result over 1048576 cells"


@pytest.mark.parametrize(
    "formula", ["=WORKDAY(1,1E9)", "=WORKDAY.INTL(1,-1E9,1)", "=NETWORKDAYS(1,1E9)"]
)
def test_day_counts_past_excels_last_date_are_num(formula) -> None:
    g = _excel()
    g.setcell(0, 0, formula)
    assert g.cell(0, 0).err is ExcelError.NUM
