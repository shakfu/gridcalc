from gridcalc.engine import Vec
from gridcalc.formula import Env, evaluate, parse
from gridcalc.formula.errors import ExcelError


def make_env(cells=None, builtins=None, named=None, py=None, sheets=None):
    """Build an Env. ``cells`` is the active sheet's cell store
    keyed by ``(c, r)``; ``sheets`` is an optional dict of
    ``{sheet_name: {(c, r): value}}`` for cross-sheet tests.
    """
    cells = cells or {}
    sheets = sheets or {}

    def cell_value(c, r, sheet=None):
        if sheet is None:
            return cells.get((c, r))
        return sheets.get(sheet, {}).get((c, r))

    return Env(
        cell_value=cell_value,
        builtins=builtins or {},
        named_ranges=named or {},
        py_registry=py or {},
    )


def ev(text, env=None):
    return evaluate(parse(text), env or make_env())


class TestLiterals:
    def test_number(self):
        assert ev("42") == 42.0

    def test_string(self):
        assert ev('"hi"') == "hi"

    def test_bool(self):
        assert ev("TRUE") is True

    def test_error_lit(self):
        assert ev("#DIV/0!") == ExcelError.DIV0


class TestArithmetic:
    def test_add(self):
        assert ev("1+2") == 3.0

    def test_sub(self):
        assert ev("5-3") == 2.0

    def test_mul(self):
        assert ev("4*3") == 12.0

    def test_div(self):
        assert ev("10/4") == 2.5

    def test_div_by_zero(self):
        assert ev("1/0") == ExcelError.DIV0

    def test_pow(self):
        assert ev("2^10") == 1024.0

    def test_pow_right_assoc(self):
        # 2^3^2 = 2^(3^2) = 2^9 = 512
        assert ev("2^3^2") == 512.0

    def test_pow_negative_root(self):
        # (-1)^0.5 -> #NUM!
        assert ev("(-1)^0.5") == ExcelError.NUM

    def test_unary_minus(self):
        assert ev("-5") == -5.0

    def test_percent(self):
        assert ev("50%") == 0.5

    def test_precedence(self):
        assert ev("1+2*3") == 7.0
        assert ev("(1+2)*3") == 9.0
        assert ev("2+3*4-1") == 13.0


class TestStrings:
    def test_concat(self):
        assert ev('"foo"&"bar"') == "foobar"

    def test_concat_number(self):
        assert ev('"x"&42') == "x42"

    def test_string_to_number(self):
        assert ev('"3"+4') == 7.0

    def test_unparseable_string(self):
        assert ev('"abc"+1') == ExcelError.VALUE


class TestCompare:
    def test_eq(self):
        assert ev("1=1") is True
        assert ev("1=2") is False

    def test_ne(self):
        assert ev("1<>2") is True
        assert ev("1<>1") is False

    def test_lt(self):
        assert ev("1<2") is True

    def test_ge(self):
        assert ev("3>=3") is True

    def test_string_compare(self):
        assert ev('"a"<"b"') is True


class TestErrorPropagation:
    def test_arith(self):
        assert ev("1 + #N/A") == ExcelError.NA

    def test_div_zero_propagates(self):
        assert ev("(1/0) + 1") == ExcelError.DIV0

    def test_concat(self):
        assert ev('"x" & #REF!') == ExcelError.REF


class TestCellRefs:
    def test_basic(self):
        env = make_env(cells={(0, 0): 5.0})
        assert ev("A1", env) == 5.0
        assert env.refs_used == {(None, 0, 0)}

    def test_empty_cell_is_zero(self):
        env = make_env()
        assert ev("A1+1", env) == 1.0

    def test_string_cell_in_arith(self):
        env = make_env(cells={(0, 0): "hello"})
        assert ev("A1+1", env) == ExcelError.VALUE

    def test_sheet_qualified_ref_resolves(self):
        env = make_env(
            cells={(0, 0): 5.0},
            sheets={"Sheet2": {(0, 0): 99.0}},
        )
        assert ev("Sheet2!A1", env) == 99.0
        assert env.refs_used == {("Sheet2", 0, 0)}

    def test_sheet_qualified_range_resolves(self):
        env = make_env(
            sheets={"Sheet2": {(0, 0): 1.0, (0, 1): 2.0, (0, 2): 3.0}},
            builtins={"sum": lambda v: sum(v.data) if hasattr(v, "data") else v},
        )
        assert ev("SUM(Sheet2!A1:A3)", env) == 6.0

    def test_unknown_sheet_resolves_to_empty(self):
        env = make_env()
        # Phase 2b: unknown sheet acts like empty (matches an unset
        # cell). Phase 3 will surface sheet management; #REF! for
        # missing sheets can come then if needed.
        assert ev("Bogus!A1+1", env) == 1.0


class TestRanges:
    def test_range_with_sum(self):
        env = make_env(
            cells={(0, 0): 1.0, (0, 1): 2.0, (0, 2): 3.0},
            builtins={"sum": lambda v: sum(v.data) if isinstance(v, Vec) else v},
        )
        assert ev("SUM(A1:A3)", env) == 6.0

    def test_range_broadcast_add(self):
        env = make_env(cells={(0, 0): 1.0, (0, 1): 2.0, (0, 2): 3.0})
        result = ev("A1:A3 + 10", env)
        assert isinstance(result, Vec)
        assert result.data == [11.0, 12.0, 13.0]

    def test_range_error_propagates(self):
        env = make_env(
            cells={(0, 0): 1.0, (0, 1): ExcelError.NA, (0, 2): 3.0},
            builtins={"sum": lambda v: sum(v.data) if isinstance(v, Vec) else v},
        )
        assert ev("SUM(A1:A3)", env) == ExcelError.NA


class TestFunctionCalls:
    def test_known_function(self):
        env = make_env(builtins={"abs": abs})
        assert ev("ABS(-5)", env) == 5

    def test_case_insensitive(self):
        env = make_env(builtins={"abs": abs})
        assert ev("Abs(-5)", env) == 5
        assert ev("aBs(-5)", env) == 5

    def test_unknown_function(self):
        assert ev("FROOB(1)") == ExcelError.NAME

    def test_function_div_zero(self):
        env = make_env(builtins={"reciprocal": lambda x: 1 / x})
        assert ev("RECIPROCAL(0)", env) == ExcelError.DIV0


class TestNamedRanges:
    def test_lookup(self):
        from gridcalc.formula.ast_nodes import CellRef

        env = make_env(
            cells={(0, 0): 42.0},
            named={"answer": CellRef(0, 0, False, False)},
        )
        assert ev("answer + 1", env) == 43.0

    def test_unknown_name(self):
        assert ev("noname") == ExcelError.NAME


class TestPyCall:
    def test_registered(self):
        env = make_env(py={"double": lambda x: x * 2})
        assert ev("py.double(21)", env) == 42

    def test_unregistered(self):
        assert ev("py.nope()") == ExcelError.NAME


class TestVecBroadcast:
    def test_unary_minus(self):
        env = make_env(cells={(0, 0): 1.0, (0, 1): 2.0})
        result = ev("-A1:A2", env)
        assert isinstance(result, Vec)
        assert result.data == [-1.0, -2.0]

    def test_percent_on_vec(self):
        env = make_env(cells={(0, 0): 50.0, (0, 1): 100.0})
        result = ev("A1:A2 %", env)
        assert isinstance(result, Vec)
        assert result.data == [0.5, 1.0]
