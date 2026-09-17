"""Every registered Excel function is reachable from EXCEL-mode formula text.

Each function is swapped for a stub so the test proves the lexer, parser and
name lookup deliver the call, independent of what the function computes.
"""

from __future__ import annotations

import pytest

from gridcalc.engine import Grid, Mode
from gridcalc.formula import parse
from gridcalc.formula.ast_nodes import Call
from gridcalc.formula.evaluator import LAZY_FUNCS
from gridcalc.libs.xlsx import BUILTINS

# Evaluated by the evaluator itself, never through the registered function.
_LAZY_ARGS = {
    "if": "1,2,3",
    "ifs": "TRUE,1",
    "switch": "1,1,2",
    "iferror": "1,2",
    "ifna": "1,2",
    "choose": "1,2",
}


@pytest.mark.parametrize("name", sorted(BUILTINS))
def test_builtin_is_callable_from_formula(name):
    assert parse(f"{name}(1)") == Call(name.lower(), (parse("1"),))
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    calls = []

    def stub(*args):
        calls.append(args)
        return 42.0

    g._eval_globals[name] = stub
    if name.lower() in LAZY_FUNCS:
        g.setcell(0, 0, f"={name}({_LAZY_ARGS[name.lower()]})")
        assert g.cell(0, 0).err is None
    else:
        g.setcell(0, 0, f"={name}(1)")
        assert calls, f"{name} never reached its implementation (err={g.cell(0, 0).err})"
        assert g.cell(0, 0).val == 42.0
