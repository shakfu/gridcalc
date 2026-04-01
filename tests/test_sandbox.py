import json
import math

from pycalc.engine import Grid, NamedRange
from pycalc.sandbox import (
    LoadPolicy,
    classify_module,
    load_modules,
    validate_formula,
)

# -- validate_formula tests --


class TestValidateFormulaAllowed:
    """Patterns that MUST be allowed for spreadsheet formulas."""

    def test_constant(self):
        assert validate_formula("42")[0]

    def test_float(self):
        assert validate_formula("3.14")[0]

    def test_negative(self):
        assert validate_formula("-1")[0]

    def test_arithmetic(self):
        assert validate_formula("A1 + B2 * 3")[0]

    def test_comparison(self):
        assert validate_formula("A1 > 0")[0]

    def test_ternary(self):
        assert validate_formula("A1 if A1 > 0 else 0")[0]

    def test_function_call(self):
        assert validate_formula("SUM(Vec([A1, A2, A3]))")[0]

    def test_nested_calls(self):
        assert validate_formula("SUM(ABS(A1))")[0]

    def test_attribute_access(self):
        assert validate_formula("np.mean(x)")[0]

    def test_chained_attribute(self):
        assert validate_formula("np.linalg.norm(x)")[0]

    def test_list_comprehension(self):
        assert validate_formula("[x**2 for x in vals]")[0]

    def test_generator_expr(self):
        assert validate_formula("sum(x**2 for x in vals)")[0]

    def test_lambda(self):
        assert validate_formula("(lambda x: x + 1)(5)")[0]

    def test_subscript(self):
        assert validate_formula("vals[0]")[0]

    def test_slice(self):
        assert validate_formula("vals[1:3]")[0]

    def test_dict_literal(self):
        assert validate_formula("{'a': 1, 'b': 2}")[0]

    def test_tuple(self):
        assert validate_formula("(1, 2, 3)")[0]

    def test_boolean_ops(self):
        assert validate_formula("A1 > 0 and A2 < 10")[0]

    def test_string_literal(self):
        assert validate_formula("'hello'")[0]

    def test_method_call(self):
        assert validate_formula("df.groupby('col').mean()")[0]

    def test_math_attr(self):
        assert validate_formula("math.pi")[0]


class TestValidateFormulaBlocked:
    """Patterns that MUST be blocked for security."""

    def test_dunder_class(self):
        ok, msg = validate_formula("x.__class__")
        assert not ok
        assert "__class__" in msg

    def test_dunder_subclasses(self):
        ok, _ = validate_formula("().__class__.__subclasses__()")
        assert not ok

    def test_dunder_globals(self):
        ok, _ = validate_formula("f.__globals__")
        assert not ok

    def test_dunder_init(self):
        ok, _ = validate_formula("x.__init__")
        assert not ok

    def test_dunder_dict(self):
        ok, _ = validate_formula("x.__dict__")
        assert not ok

    def test_dunder_mro(self):
        ok, _ = validate_formula("x.__mro__")
        assert not ok

    def test_import_name(self):
        ok, msg = validate_formula("__import__('os')")
        assert not ok
        assert "__import__" in msg

    def test_eval_name(self):
        ok, _ = validate_formula("eval('1+1')")
        assert not ok

    def test_exec_name(self):
        ok, _ = validate_formula("exec('pass')")
        assert not ok

    def test_compile_name(self):
        ok, _ = validate_formula("compile('1', '', 'eval')")
        assert not ok

    def test_getattr_name(self):
        ok, _ = validate_formula("getattr(x, 'y')")
        assert not ok

    def test_setattr_name(self):
        ok, _ = validate_formula("setattr(x, 'y', 1)")
        assert not ok

    def test_open_name(self):
        ok, _ = validate_formula("open('/etc/passwd')")
        assert not ok

    def test_type_name(self):
        ok, _ = validate_formula("type(x)")
        assert not ok

    def test_globals_name(self):
        ok, _ = validate_formula("globals()")
        assert not ok

    def test_locals_name(self):
        ok, _ = validate_formula("locals()")
        assert not ok

    def test_breakpoint_name(self):
        ok, _ = validate_formula("breakpoint()")
        assert not ok

    def test_dunder_builtins_name(self):
        ok, _ = validate_formula("__builtins__")
        assert not ok

    def test_func_globals_attr(self):
        ok, _ = validate_formula("f.func_globals")
        assert not ok

    def test_f_globals_attr(self):
        ok, _ = validate_formula("frame.f_globals")
        assert not ok

    def test_co_code_attr(self):
        ok, _ = validate_formula("code.co_code")
        assert not ok

    def test_tb_frame_attr(self):
        ok, _ = validate_formula("tb.tb_frame")
        assert not ok

    def test_gi_frame_attr(self):
        ok, _ = validate_formula("gen.gi_frame")
        assert not ok

    def test_syntax_error(self):
        ok, msg = validate_formula("1 +")
        assert not ok
        assert "syntax" in msg.lower()

    def test_object_name(self):
        ok, _ = validate_formula("object()")
        assert not ok

    def test_super_name(self):
        ok, _ = validate_formula("super()")
        assert not ok

    def test_vars_name(self):
        ok, _ = validate_formula("vars(x)")
        assert not ok

    def test_dir_name(self):
        ok, _ = validate_formula("dir(x)")
        assert not ok


# -- classify_module tests --


class TestClassifyModule:
    def test_safe_numpy(self):
        assert classify_module("numpy") == "safe"

    def test_safe_scipy(self):
        assert classify_module("scipy") == "safe"

    def test_safe_decimal(self):
        assert classify_module("decimal") == "safe"

    def test_safe_submodule(self):
        assert classify_module("numpy.linalg") == "safe"

    def test_side_effect_matplotlib(self):
        assert classify_module("matplotlib") == "side_effect"

    def test_side_effect_pandas(self):
        assert classify_module("pandas") == "side_effect"

    def test_side_effect_pyplot(self):
        assert classify_module("matplotlib.pyplot") == "side_effect"

    def test_blocked_os(self):
        assert classify_module("os") == "blocked"

    def test_blocked_subprocess(self):
        assert classify_module("subprocess") == "blocked"

    def test_blocked_sys(self):
        assert classify_module("sys") == "blocked"

    def test_blocked_submodule(self):
        assert classify_module("os.path") == "blocked"

    def test_blocked_socket(self):
        assert classify_module("socket") == "blocked"

    def test_blocked_pickle(self):
        assert classify_module("pickle") == "blocked"

    def test_unknown(self):
        assert classify_module("some_random_lib") == "unknown"

    def test_unknown_custom(self):
        assert classify_module("my_custom_module") == "unknown"


# -- load_modules tests --


class TestLoadModules:
    def test_blocked_module_rejected(self):
        mods, errors = load_modules(["os"])
        assert "os" not in mods
        assert len(errors) == 1
        assert "blocked" in errors[0]

    def test_blocked_subprocess_rejected(self):
        mods, errors = load_modules(["subprocess"])
        assert len(mods) == 0
        assert len(errors) == 1

    def test_nonexistent_module(self):
        mods, errors = load_modules(["nonexistent_xyz_module_12345"])
        assert len(mods) == 0
        assert len(errors) == 1
        assert "not installed" in errors[0]

    def test_stdlib_safe_module(self):
        mods, errors = load_modules(["decimal"])
        assert "decimal" in mods
        assert len(errors) == 0

    def test_stdlib_fractions(self):
        mods, errors = load_modules(["fractions"])
        assert "fractions" in mods
        assert len(errors) == 0

    def test_mixed_modules(self):
        mods, errors = load_modules(["decimal", "os", "nonexistent_xyz_12345"])
        assert "decimal" in mods
        assert "os" not in mods
        assert len(errors) == 2

    def test_multiple_blocked(self):
        mods, errors = load_modules(["os", "subprocess", "sys"])
        assert len(mods) == 0
        assert len(errors) == 3


# -- LoadPolicy tests --


class TestLoadPolicy:
    def test_trust_all(self):
        p = LoadPolicy.trust_all(["numpy", "pandas"])
        assert p.load_code is True
        assert p.approved_modules == ["numpy", "pandas"]

    def test_trust_all_empty(self):
        p = LoadPolicy.trust_all()
        assert p.load_code is True
        assert p.approved_modules == []

    def test_formulas_only(self):
        p = LoadPolicy.formulas_only()
        assert p.load_code is False
        assert p.approved_modules == []

    def test_default(self):
        p = LoadPolicy()
        assert p.load_code is False
        assert p.approved_modules == []


# -- Grid integration: AST validation in recalc --


class TestGridSandboxIntegration:
    def test_blocked_import_formula(self):
        g = Grid()
        g.setcell(0, 0, "=__import__('os')")
        assert math.isnan(g.cells[0][0].val)

    def test_blocked_eval_formula(self):
        g = Grid()
        g.setcell(0, 0, "=eval('1+1')")
        assert math.isnan(g.cells[0][0].val)

    def test_blocked_dunder_formula(self):
        g = Grid()
        g.setcell(0, 0, "=(1).__class__")
        assert math.isnan(g.cells[0][0].val)

    def test_blocked_getattr_formula(self):
        g = Grid()
        g.setcell(0, 0, "=getattr(A1, 'real')")
        assert math.isnan(g.cells[0][0].val)

    def test_normal_formula_still_works(self):
        g = Grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(1, 0, "=A1+A2")
        assert g.cells[1][0].val == 30.0

    def test_range_formula_still_works(self):
        g = Grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.setcell(1, 0, "=SUM(A1:A3)")
        assert g.cells[1][0].val == 60.0

    def test_comprehension_still_works(self):
        g = Grid()
        g.setcell(0, 0, "10")
        g.setcell(0, 1, "20")
        g.setcell(0, 2, "30")
        g.names = [NamedRange("vals", 0, 0, 0, 2)]
        g.recalc()
        g.setcell(1, 0, "=sum([x**2 for x in vals])")
        assert g.cells[1][0].val == 1400.0

    def test_math_functions_still_work(self):
        g = Grid()
        g.setcell(0, 0, "=sin(pi/2)")
        assert abs(g.cells[0][0].val - 1.0) < 1e-5

    def test_code_block_still_works(self):
        g = Grid()
        g.code = "def double(x): return x * 2"
        g.setcell(0, 0, "5")
        g.setcell(1, 0, "=double(A1)")
        assert g.cells[1][0].val == 10.0


# -- Grid.jsoninspect tests --


class TestJsonInspect:
    def test_simple_file(self, tmp_path):
        f = tmp_path / "simple.json"
        f.write_text('{"cells": [[1, 2, 3]]}')
        info = Grid.jsoninspect(str(f))
        assert info is not None
        assert not info.has_code
        assert info.requires == []
        assert info.cell_count == 3
        assert info.formula_count == 0

    def test_with_formulas(self, tmp_path):
        f = tmp_path / "formulas.json"
        f.write_text('{"cells": [[1, "=A1+1", "hello"]]}')
        info = Grid.jsoninspect(str(f))
        assert info.cell_count == 3
        assert info.formula_count == 1

    def test_with_code(self, tmp_path):
        f = tmp_path / "code.json"
        f.write_text('{"code": "def foo():\\n    return 1", "cells": [[1]]}')
        info = Grid.jsoninspect(str(f))
        assert info.has_code
        assert info.code_lines == 2
        assert "def foo" in info.code_preview

    def test_with_requires(self, tmp_path):
        f = tmp_path / "requires.json"
        f.write_text('{"requires": ["numpy", "os", "matplotlib"], "cells": [[1]]}')
        info = Grid.jsoninspect(str(f))
        assert info.requires == ["numpy", "os", "matplotlib"]
        assert info.blocked_modules == ["os"]
        assert info.side_effect_modules == ["matplotlib"]

    def test_nonexistent_file(self, tmp_path):
        info = Grid.jsoninspect(str(tmp_path / "nope.json"))
        assert info is None

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json at all")
        info = Grid.jsoninspect(str(f))
        assert info is None

    def test_empty_code_not_flagged(self, tmp_path):
        f = tmp_path / "empty_code.json"
        f.write_text('{"code": "", "cells": [[1]]}')
        info = Grid.jsoninspect(str(f))
        assert not info.has_code

    def test_whitespace_code_not_flagged(self, tmp_path):
        f = tmp_path / "ws_code.json"
        f.write_text('{"code": "   \\n  ", "cells": [[1]]}')
        info = Grid.jsoninspect(str(f))
        assert not info.has_code

    def test_styled_cell_counted(self, tmp_path):
        f = tmp_path / "styled.json"
        f.write_text('{"cells": [[{"v": 42, "bold": true}, {"v": "=A1"}]]}')
        info = Grid.jsoninspect(str(f))
        assert info.cell_count == 2
        assert info.formula_count == 1

    def test_null_cells_not_counted(self, tmp_path):
        f = tmp_path / "nulls.json"
        f.write_text('{"cells": [[1, null, 3, null]]}')
        info = Grid.jsoninspect(str(f))
        assert info.cell_count == 2


# -- jsonload with policy --


class TestJsonLoadPolicy:
    def test_skip_code(self, tmp_path):
        f = tmp_path / "code.json"
        f.write_text('{"code": "x = 42", "cells": [[1, 2]]}')
        g = Grid()
        policy = LoadPolicy(load_code=False)
        assert g.jsonload(str(f), policy=policy) == 0
        assert g.code == ""
        assert g.cells[0][0].val == 1.0

    def test_approve_code(self, tmp_path):
        f = tmp_path / "code.json"
        f.write_text('{"code": "def triple(x): return x * 3", "cells": [[5, "=triple(A1)"]]}')
        g = Grid()
        policy = LoadPolicy(load_code=True)
        assert g.jsonload(str(f), policy=policy) == 0
        assert "def triple" in g.code
        assert g.cells[1][0].val == 15.0

    def test_skip_requires(self, tmp_path):
        f = tmp_path / "req.json"
        f.write_text('{"requires": ["decimal"], "cells": [[1]]}')
        g = Grid()
        policy = LoadPolicy(load_code=False, approved_modules=[])
        assert g.jsonload(str(f), policy=policy) == 0
        assert g.requires == ["decimal"]
        # Module not loaded into eval globals
        assert "decimal" not in g._eval_globals

    def test_approve_requires(self, tmp_path):
        f = tmp_path / "req.json"
        f.write_text('{"requires": ["decimal"], "cells": [[1]]}')
        g = Grid()
        policy = LoadPolicy(load_code=False, approved_modules=["decimal"])
        assert g.jsonload(str(f), policy=policy) == 0
        assert "decimal" in g._eval_globals

    def test_policy_none_trusts_all(self, tmp_path):
        f = tmp_path / "all.json"
        f.write_text('{"code": "x = 1", "requires": ["decimal"], "cells": [[1]]}')
        g = Grid()
        assert g.jsonload(str(f), policy=None) == 0
        assert g.code == "x = 1"
        assert "decimal" in g._eval_globals

    def test_blocked_module_in_requires(self, tmp_path):
        f = tmp_path / "blocked.json"
        f.write_text('{"requires": ["os"], "cells": [[1]]}')
        g = Grid()
        policy = LoadPolicy(load_code=False, approved_modules=["os"])
        assert g.jsonload(str(f), policy=policy) == 0
        # os is blocked at the load_modules level
        assert "os" not in g._eval_globals
        assert len(g._module_errors) == 1


# -- requires roundtrip --


class TestRequiresRoundtrip:
    def test_save_and_inspect(self, tmp_path):
        g = Grid()
        g.requires = ["numpy", "pandas"]
        g.setcell(0, 0, "10")
        f = tmp_path / "rt.json"
        assert g.jsonsave(str(f)) == 0

        info = Grid.jsoninspect(str(f))
        assert info is not None
        assert info.requires == ["numpy", "pandas"]

    def test_save_and_load(self, tmp_path):
        g = Grid()
        g.requires = ["decimal", "fractions"]
        g.setcell(0, 0, "42")
        f = tmp_path / "rt2.json"
        assert g.jsonsave(str(f)) == 0

        g2 = Grid()
        assert g2.jsonload(str(f)) == 0
        assert g2.requires == ["decimal", "fractions"]
        assert g2.cells[0][0].val == 42.0

    def test_no_requires_not_saved(self, tmp_path):
        g = Grid()
        g.setcell(0, 0, "1")
        f = tmp_path / "no_req.json"
        assert g.jsonsave(str(f)) == 0

        with open(str(f)) as fh:
            d = json.load(fh)
        assert "requires" not in d


# -- Grid.load_requires --


class TestGridLoadRequires:
    def test_load_stdlib_module(self):
        g = Grid()
        g.load_requires(["decimal"])
        assert "decimal" in g._eval_globals

    def test_load_blocked_module(self):
        g = Grid()
        g.load_requires(["os"])
        assert "os" not in g._eval_globals
        assert len(g._module_errors) == 1

    def test_load_empty(self):
        g = Grid()
        g.load_requires([])
        assert len(g._module_errors) == 0

    def test_formula_uses_loaded_module(self):
        g = Grid()
        g.load_requires(["decimal"])
        g.setcell(0, 0, "=decimal.Decimal('3.14')")
        # decimal.Decimal returns a Decimal, float() conversion
        assert abs(g.cells[0][0].val - 3.14) < 1e-10
