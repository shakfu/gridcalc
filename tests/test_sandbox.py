import importlib
import importlib.util
import json
import math
import warnings

import pytest

from gridcalc._module_names import EXCLUDED, NAMES
from gridcalc.engine import Grid, NamedRange
from gridcalc.sandbox import (
    SAFE_MODULES,
    LoadPolicy,
    ModuleFacade,
    classify_module,
    inspect_file,
    load_modules,
    module_facade,
    validate_code,
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


class TestStringBorneAttributeAccess:
    """`str.format` reads the attributes and items its template names, and
    `operator.attrgetter` is `getattr`. Neither shows as an Attribute node."""

    REFUSED = [
        '"{0.__globals__[os].environ[HOME]}".format(SUM)',
        '"{f.__globals__}".format_map({"f": SUM})',
        '"{0[key]}".format(x)',
        '"{0.real}".format(x)',
        '"{0:{1.__class__}}".format(1, SUM)',  # a field nested in the format spec
        '"{".format(x)',  # unparseable template
        # A template that is not a literal cannot be checked.
        'str.format("{0.__globals__}", SUM)',
        '("{0.__glo" + "bals__}").format(SUM)',
        'f"{{0.__globals__}}".format(SUM)',
        '"{0}".format("{0.__globals__}").format(SUM)',
        '(lambda t: t.format(SUM))("{0.__globals__}")',
        "A1.format(SUM)",
        # `getattr` by other names.
        'operator.attrgetter("__globals__")(SUM)',
        'operator.methodcaller("format", SUM)("{0.__globals__}")',
        'attrgetter("__globals__")(SUM)',
        'string.Formatter().vformat("{0.__globals__}", (SUM,), {})',
        'string.Formatter().get_field("0.__globals__", (SUM,), {})',
    ]
    ALLOWED = [
        '"{:.2f}".format(A1)',
        '"{} {}".format(A1, B1)',
        '"{0}-{1:>{2}}".format(1, 2, 3)',
        '"{name!r}".format(name=A1)',
        '"{a}".format_map({"a": 1})',
        '"{{braces}}".format()',
        'f"{A1:.2f}"',
        '"%s" % A1',
        '"abc".upper()',
        "np.format_float_positional(1.5)",
    ]

    def test_refused_in_formulas(self):
        for source in self.REFUSED:
            assert not validate_formula(source)[0], source

    def test_refused_in_code(self):
        for source in self.REFUSED:
            assert not validate_code(f"x = {source}")[0], source

    def test_plain_templates_allowed(self):
        for source in self.ALLOWED:
            assert validate_formula(source) == (True, ""), source
            assert validate_code(f"x = {source}") == (True, ""), source

    def test_import_cannot_rename_a_blocked_name(self):
        assert not validate_code("from operator import attrgetter as g")[0]
        assert not validate_code("from operator import methodcaller")[0]
        assert validate_code("from operator import itemgetter")[0]

    def test_the_read_does_not_reach_a_cell(self, monkeypatch):
        from gridcalc.formula.errors import ExcelError

        monkeypatch.setenv("HOME", "/secret/home")
        g = Grid()
        g.setcell(0, 0, '=len("{0.__globals__[os].environ[HOME]}".format(SUM))')
        cl = g.cells[0][0]
        assert cl.err == ExcelError.NAME
        assert math.isnan(cl.val)
        assert "secret" not in (cl.err_msg or "")
        g.setcell(0, 1, '=len("{:.2f}".format(3.14159))')
        assert g.cells[0][1].val == 4


# -- validate_code tests --


class TestValidateCodeAllowed:
    """Code block patterns that MUST be allowed."""

    def test_empty(self):
        assert validate_code("")[0]

    def test_whitespace_only(self):
        assert validate_code("   \n  ")[0]

    def test_function_def(self):
        assert validate_code("def double(x):\n    return x * 2")[0]

    def test_safe_import(self):
        assert validate_code("import statistics")[0]

    def test_safe_from_import(self):
        assert validate_code("from decimal import Decimal")[0]

    def test_assignment(self):
        assert validate_code("TAX_RATE = 0.21")[0]

    def test_class_def(self):
        assert validate_code("class Helper:\n    pass")[0]

    def test_safe_module_attribute(self):
        assert validate_code("import statistics\nx = statistics.mean([1,2,3])")[0]

    def test_multiple_functions(self):
        code = "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n"
        assert validate_code(code)[0]


class TestValidateCodeBlocked:
    """Code block patterns that MUST be blocked for security."""

    def test_import_os(self):
        ok, msg = validate_code("import os")
        assert not ok
        assert "os" in msg

    def test_import_subprocess(self):
        ok, _ = validate_code("import subprocess")
        assert not ok

    def test_import_sys(self):
        ok, _ = validate_code("import sys")
        assert not ok

    def test_from_os_import(self):
        ok, msg = validate_code("from os import system")
        assert not ok
        assert "os" in msg

    def test_from_subprocess_import(self):
        ok, _ = validate_code("from subprocess import run")
        assert not ok

    def test_import_socket(self):
        ok, _ = validate_code("import socket")
        assert not ok

    def test_import_pickle(self):
        ok, _ = validate_code("import pickle")
        assert not ok

    def test_import_shutil(self):
        ok, _ = validate_code("import shutil")
        assert not ok

    def test_import_os_path(self):
        ok, _ = validate_code("import os.path")
        assert not ok

    def test_dunder_in_code(self):
        ok, _ = validate_code("x = ().__class__.__subclasses__()")
        assert not ok

    def test_eval_in_code(self):
        ok, _ = validate_code("x = eval('1+1')")
        assert not ok

    def test_exec_in_code(self):
        ok, _ = validate_code("exec('import os')")
        assert not ok

    def test_open_in_code(self):
        ok, _ = validate_code("f = open('/etc/passwd')")
        assert not ok

    def test_getattr_in_code(self):
        ok, _ = validate_code("x = getattr(obj, 'secret')")
        assert not ok

    def test_dangerous_attr_in_code(self):
        ok, _ = validate_code("x = f.func_globals")
        assert not ok

    def test_syntax_error(self):
        ok, msg = validate_code("def (broken")
        assert not ok
        assert "syntax" in msg.lower()

    def test_import_builtins(self):
        ok, _ = validate_code("import builtins")
        assert not ok

    def test_import_ctypes(self):
        ok, _ = validate_code("import ctypes")
        assert not ok


class TestCodeBlockIntegration:
    """Integration tests: code blocks with sandbox validation in Grid.recalc."""

    def test_safe_code_block_executes(self):
        g = Grid()
        g.code = "def double(x): return x * 2"
        g.setcell(0, 0, "5")
        g.setcell(1, 0, "=double(A1)")
        assert g.cells[1][0].val == 10.0

    def test_blocked_import_code_block_skipped(self):
        g = Grid()
        g.code = "import os\ndef pwned(): return os.getcwd()"
        g.setcell(0, 0, "=pwned()")
        assert math.isnan(g.cells[0][0].val)

    def test_blocked_eval_code_block_skipped(self):
        g = Grid()
        g.code = "result = eval('1+1')"
        g.setcell(0, 0, "=result")
        assert math.isnan(g.cells[0][0].val)

    def test_blocked_open_code_block_skipped(self):
        g = Grid()
        g.code = "f = open('/etc/passwd')"
        g.setcell(0, 0, "1")
        g.recalc()
        # Code didn't execute, formula still works
        assert g.cells[0][0].val == 1.0

    def test_blocked_dunder_code_block_skipped(self):
        g = Grid()
        g.code = "x = ().__class__.__subclasses__()"
        g.setcell(0, 0, "1")
        g.recalc()
        assert g.cells[0][0].val == 1.0

    def test_safe_code_with_constants(self):
        g = Grid()
        g.code = "avg = (10 + 20 + 30) / 3"
        g.setcell(0, 0, "=avg")
        assert g.cells[0][0].val == 20.0

    def test_mixed_safe_code_with_formula(self):
        g = Grid()
        g.code = "RATE = 0.05\ndef compound(p, n): return p * (1 + RATE) ** n"
        g.setcell(0, 0, "1000")
        g.setcell(1, 0, "=compound(A1, 10)")
        assert abs(g.cells[1][0].val - 1000 * 1.05**10) < 0.01


# -- classify_module tests --


class TestClassifyModule:
    def test_safe_numpy(self):
        assert classify_module("numpy") == "safe"

    def test_scipy_and_sympy_are_handed_over_whole(self):
        # No facade yet, so they are flagged rather than called safe.
        for name in ("scipy", "scipy.optimize", "sympy"):
            assert classify_module(name) == "side_effect", name

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

    def test_submodule_does_not_inherit_safe(self):
        # `numpy.ctypeslib` holds `ctypes`; `numpy.f2py` holds `os` and `subprocess`.
        for name in ("numpy.ctypeslib", "numpy.f2py", "numpy.testing", "scipy.io", "pandas.io"):
            assert classify_module(name) == "unknown", name

    def test_unlisted_submodule_needs_the_unknown_approval(self):
        mods, errors = load_modules(["numpy.ctypeslib"])
        assert mods == {}
        assert "not approved" in errors[0]

    def test_submodule_of_blocked_package_stays_blocked(self):
        assert classify_module("urllib.request") == "blocked"
        assert classify_module("http.server") == "blocked"


# -- ModuleFacade tests --


def _public_names(mod):
    names = getattr(mod, "__all__", None) or dir(mod)
    return {n for n in names if not n.startswith("_")}


class TestModuleFacade:
    """A safe module reaches the workbook as its reviewed names only."""

    def test_numpy_is_a_facade_of_the_real_functions(self):
        np = pytest.importorskip("numpy")
        facade = load_modules(["numpy"])[0]["np"]
        assert isinstance(facade, ModuleFacade)
        assert facade.array is np.array
        assert facade.ndarray is np.ndarray
        assert facade.newaxis is None  # a listed constant that happens to be None
        assert facade.linalg.det(facade.array([[1.0, 2.0], [3.0, 4.0]])) == pytest.approx(-2.0)

    def test_unlisted_names_are_absent(self):
        pytest.importorskip("numpy")
        facade = load_modules(["numpy"])[0]["np"]
        for name in ("f2py", "ctypeslib", "testing", "lib", "core", "_core", "savetxt", "load"):
            with pytest.raises(AttributeError, match="in a workbook"):
                getattr(facade, name)

    def test_facade_is_read_only(self):
        facade = load_modules(["decimal"])[0]["decimal"]
        with pytest.raises(AttributeError):
            facade.Decimal = int
        with pytest.raises(AttributeError):
            del facade.Decimal

    def test_no_facade_holds_a_module(self):
        import types

        def walk(facade, path):
            for name, value in vars(facade).items():
                assert not isinstance(value, types.ModuleType), f"{path}.{name}"
                if isinstance(value, ModuleFacade):
                    walk(value, f"{path}.{name}")

        for name in NAMES:
            if "." not in name and importlib.util.find_spec(name):
                walk(module_facade(name, importlib.import_module(name)), name)

    def test_submodule_can_be_required_by_name(self):
        np = pytest.importorskip("numpy")
        facade = load_modules(["numpy.linalg"])[0]["linalg"]
        assert isinstance(facade, ModuleFacade)
        assert facade.solve is np.linalg.solve

    def test_operator_has_no_attribute_readers(self):
        facade = load_modules(["operator"])[0]["operator"]
        assert facade.itemgetter(1)([10, 20]) == 20
        assert not hasattr(facade, "attrgetter")
        assert not hasattr(facade, "methodcaller")

    def test_module_without_a_list_is_handed_over_whole(self):
        import csv

        assert load_modules(["csv"])[0]["csv"] is csv

    def test_every_public_name_is_reviewed(self):
        """Fails when an installed module gains a public name: add it to
        `NAMES` or `EXCLUDED` in `_module_names.py` after reading what it does."""
        import types

        for name, listed in NAMES.items():
            if not importlib.util.find_spec(name.split(".")[0]):
                continue
            mod = importlib.import_module(name)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                public = {
                    n
                    for n in _public_names(mod)
                    if not isinstance(getattr(mod, n, None), types.ModuleType)
                }
            assert public - listed - EXCLUDED.get(name, frozenset()) == set(), name

    def test_listed_and_excluded_are_disjoint(self):
        for name, excluded in EXCLUDED.items():
            assert not (NAMES[name] & excluded), name

    def test_safe_means_facade(self):
        assert frozenset(NAMES) == SAFE_MODULES

    def test_formulas_use_the_facade(self):
        pytest.importorskip("numpy")
        from gridcalc.engine import Mode

        g = Grid()
        g.mode = Mode.PYTHON
        g.load_requires(["numpy"])
        g.setcell(0, 0, "=np.sum(np.array([1, 2, 3]))")
        assert g.cells[0][0].val == 6
        for formula in ("=np.f2py", "=np.ctypeslib", "=np.lib", "=np.testing"):
            g.setcell(0, 1, formula)
            assert math.isnan(g.cells[0][1].val), formula
            assert "in a workbook" in g.cells[0][1].err_msg, formula

    def test_facades_off_hands_over_the_module_and_says_so(self, monkeypatch, tmp_path):
        import decimal

        from gridcalc import sandbox

        monkeypatch.setattr(sandbox, "FACADES_ENABLED", False)
        assert load_modules(["decimal"])[0]["decimal"] is decimal
        # The prompt reads the class, so the module must not be called safe.
        assert classify_module("decimal") == "side_effect"
        path = tmp_path / "w.json"
        path.write_text(json.dumps({"requires": ["decimal"], "cells": [[1]]}))
        assert inspect_file(str(path)).side_effect_modules == ["decimal"]

    def test_sandbox_off_implies_whole_modules(self, monkeypatch):
        import decimal

        from gridcalc import sandbox

        monkeypatch.setattr(sandbox, "SANDBOX_ENABLED", False)
        assert load_modules(["decimal"])[0]["decimal"] is decimal

    def test_facade_is_not_a_formula_function(self):
        pytest.importorskip("numpy")
        from gridcalc.engine import Mode
        from gridcalc.formula.errors import ExcelError

        g = Grid()
        g.mode = Mode.EXCEL
        g._apply_mode_libs()
        g.load_requires(["numpy"])
        g.setcell(0, 0, "=NP()")
        assert g.cells[0][0].err == ExcelError.NAME


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
        # allow_unknown: this test is about the "not installed" report, not
        # about the classification gate that now precedes it.
        mods, errors = load_modules(["nonexistent_xyz_module_12345"], allow_unknown=True)
        assert len(mods) == 0
        assert len(errors) == 1
        assert "not installed" in errors[0]

    def test_unknown_module_is_refused_by_default(self):
        """Not on the blocklist is not the same claim as safe. `runpy` runs a
        Python file and `sqlite3` writes one; neither is blocked, so both were
        imported on a workbook's say-so."""
        for name in ("runpy", "sqlite3", "glob", "posixpath"):
            mods, errors = load_modules([name])
            assert mods == {}, name
            assert len(errors) == 1
            assert "not a recognised module" in errors[0]

    def test_unknown_module_loads_when_explicitly_allowed(self):
        mods, errors = load_modules(["sqlite3"], allow_unknown=True)
        assert "sqlite3" in mods
        assert errors == []

    def test_unknown_module_is_refused_without_importing_it(self, monkeypatch):
        """The refusal has to precede the import, or a module with an
        import-time side effect gets to run before being turned down."""
        import importlib

        called: list[str] = []

        def spy(name):
            called.append(name)
            raise AssertionError(f"imported {name} despite refusing it")

        monkeypatch.setattr(importlib, "import_module", spy)
        mods, errors = load_modules(["runpy"])
        assert called == []
        assert mods == {}
        assert len(errors) == 1

    def test_safe_module_still_loads_when_unknown_are_refused(self):
        mods, errors = load_modules(["decimal", "runpy"])
        assert "decimal" in mods
        assert "runpy" not in mods
        assert len(errors) == 1

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

    def test_version_pin_stdlib_metadata_missing(self):
        # stdlib modules have no distribution metadata; pinning a version
        # on one is rejected with a 'metadata not found' error.
        mods, errors = load_modules(["decimal>=0.0"])
        assert "decimal" not in mods
        assert len(errors) == 1
        assert "metadata not found" in errors[0]

    def test_version_pin_eq_known_dist(self):
        # pytest is always installed in the test env; pin to its version.
        import importlib.metadata as md

        v = md.version("pytest")
        mods, errors = load_modules([f"pytest=={v}"], allow_unknown=True)
        assert "pytest" in mods
        assert errors == []

    def test_version_pin_mismatch_known_dist(self):
        mods, errors = load_modules(["pytest==0.0.1"], allow_unknown=True)
        assert "pytest" not in mods
        assert len(errors) == 1
        assert "does not satisfy" in errors[0]


# -- _parse_requirement tests --


class TestParseRequirement:
    def test_bare_name(self):
        from gridcalc.sandbox import _parse_requirement

        assert _parse_requirement("numpy") == ("numpy", None, None)

    def test_with_eq(self):
        from gridcalc.sandbox import _parse_requirement

        assert _parse_requirement("numpy==1.24.0") == ("numpy", "==", "1.24.0")

    def test_with_ge(self):
        from gridcalc.sandbox import _parse_requirement

        assert _parse_requirement("pandas>=2.0") == ("pandas", ">=", "2.0")

    def test_with_compat(self):
        from gridcalc.sandbox import _parse_requirement

        assert _parse_requirement("numpy~=1.24") == ("numpy", "~=", "1.24")


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
        info = inspect_file(str(f))
        assert info is not None
        assert not info.has_code
        assert info.requires == []
        assert info.cell_count == 3
        assert info.formula_count == 0

    def test_with_formulas(self, tmp_path):
        f = tmp_path / "formulas.json"
        f.write_text('{"cells": [[1, "=A1+1", "hello"]]}')
        info = inspect_file(str(f))
        assert info.cell_count == 3
        assert info.formula_count == 1

    def test_with_code(self, tmp_path):
        f = tmp_path / "code.json"
        f.write_text('{"code": "def foo():\\n    return 1", "cells": [[1]]}')
        info = inspect_file(str(f))
        assert info.has_code
        assert info.code_lines == 2
        assert "def foo" in info.code_preview

    def test_with_requires(self, tmp_path):
        f = tmp_path / "requires.json"
        f.write_text('{"requires": ["numpy", "os", "matplotlib"], "cells": [[1]]}')
        info = inspect_file(str(f))
        assert info.requires == ["numpy", "os", "matplotlib"]
        assert info.blocked_modules == ["os"]
        assert info.side_effect_modules == ["matplotlib"]

    def test_nonexistent_file(self, tmp_path):
        info = inspect_file(str(tmp_path / "nope.json"))
        assert info is None

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json at all")
        info = inspect_file(str(f))
        assert info is None

    def test_integer_past_the_int_string_limit(self, tmp_path):
        f = tmp_path / "big.json"
        f.write_text('{"cells": [[' + "9" * 5000 + "]]}")
        assert inspect_file(str(f)) is None
        g = Grid()
        assert g.jsonload(str(f)) == -1
        assert g.io_error

    def test_empty_code_not_flagged(self, tmp_path):
        f = tmp_path / "empty_code.json"
        f.write_text('{"code": "", "cells": [[1]]}')
        info = inspect_file(str(f))
        assert not info.has_code

    def test_whitespace_code_not_flagged(self, tmp_path):
        f = tmp_path / "ws_code.json"
        f.write_text('{"code": "   \\n  ", "cells": [[1]]}')
        info = inspect_file(str(f))
        assert not info.has_code

    def test_styled_cell_counted(self, tmp_path):
        f = tmp_path / "styled.json"
        f.write_text('{"cells": [[{"v": 42, "bold": true}, {"v": "=A1"}]]}')
        info = inspect_file(str(f))
        assert info.cell_count == 2
        assert info.formula_count == 1

    def test_null_cells_not_counted(self, tmp_path):
        f = tmp_path / "nulls.json"
        f.write_text('{"cells": [[1, null, 3, null]]}')
        info = inspect_file(str(f))
        assert info.cell_count == 2

    def test_v2_sheets_counted(self, tmp_path):
        """v2 stores cells under `sheets[].cells`. Counting only the
        top-level `cells` key reported 0 for every v2 file, which made the
        trust prompt lie about what it was about to load."""
        f = tmp_path / "v2.json"
        f.write_text(
            '{"version": 2, "sheets": ['
            '{"name": "Sheet1", "cells": [[1, "=A1+1"]]},'
            '{"name": "Sheet2", "cells": [[2, 3, "=B1*2"]]}'
            "]}"
        )
        info = inspect_file(str(f))
        assert info is not None
        assert info.cell_count == 5
        assert info.formula_count == 2

    def test_v2_sheets_with_code_and_requires(self, tmp_path):
        f = tmp_path / "v2_code.json"
        f.write_text(
            '{"version": 2, "code": "x = 1", "requires": ["os"], '
            '"sheets": [{"name": "Sheet1", "cells": [[1, "=A1"]]}]}'
        )
        info = inspect_file(str(f))
        assert info.has_code
        assert info.blocked_modules == ["os"]
        assert info.cell_count == 2
        assert info.formula_count == 1

    def test_v2_styled_cells_counted(self, tmp_path):
        f = tmp_path / "v2_styled.json"
        f.write_text(
            '{"version": 2, "sheets": [{"name": "Sheet1", '
            '"cells": [[{"v": 42, "bold": true}, {"v": "=A1"}, null]]}]}'
        )
        info = inspect_file(str(f))
        assert info.cell_count == 2
        assert info.formula_count == 1

    def test_v1_still_counted_when_sheets_absent(self, tmp_path):
        f = tmp_path / "v1.json"
        f.write_text('{"version": 1, "cells": [[1, "=A1+1", 3]]}')
        info = inspect_file(str(f))
        assert info.cell_count == 3
        assert info.formula_count == 1

    def test_empty_sheets_list_falls_back_to_top_level(self, tmp_path):
        f = tmp_path / "empty_sheets.json"
        f.write_text('{"sheets": [], "cells": [[1, 2]]}')
        info = inspect_file(str(f))
        assert info.cell_count == 2

    def test_malformed_sheet_entries_skipped(self, tmp_path):
        f = tmp_path / "malformed.json"
        f.write_text('{"sheets": ["not a dict", {"name": "S", "cells": [[1]]}, {"cells": "bad"}]}')
        info = inspect_file(str(f))
        assert info is not None
        assert info.cell_count == 1


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

        info = inspect_file(str(f))
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


class TestPythonFormulaTrust:
    """PYTHON-mode formulas are `eval()`ed, so opening one is a trust decision."""

    def _write(self, tmp_path, d, name="w.json"):
        f = tmp_path / name
        f.write_text(json.dumps(d))
        return str(f)

    def test_mode_decides_python_formulas(self, tmp_path):
        # A missing or unparseable mode loads as PYTHON, so it is flagged too.
        cases = [
            ({}, True),
            ({"mode": "PYTHON"}, True),
            ({"mode": "bogus"}, True),
            ({"mode": "EXCEL"}, False),
            ({"mode": "HYBRID"}, False),
        ]
        for extra, expected in cases:
            info = inspect_file(self._write(tmp_path, {"cells": [["=1+1"]], **extra}))
            assert info.python_formulas is expected, extra
            assert info.trust_needed is expected, extra

    def test_no_formulas_needs_no_trust(self, tmp_path):
        info = inspect_file(self._write(tmp_path, {"cells": [[1, "x"]]}))
        assert not info.python_formulas
        assert not info.trust_needed

    def test_formulas_only_does_not_eval(self, tmp_path):
        from gridcalc.engine import UNTRUSTED_MSG
        from gridcalc.formula.errors import ExcelError

        # Would read $HOME if it were evaluated without validation.
        leak = '="{0.__globals__[os].environ[HOME]}".format(SUM)'
        path = self._write(tmp_path, {"cells": [[leak]]})
        g = Grid()
        assert g.jsonload(path, policy=LoadPolicy.formulas_only()) == 0
        cl = g.cell(0, 0)
        assert cl.err == ExcelError.NA
        assert cl.err_msg == UNTRUSTED_MSG

    def test_formulas_only_does_not_hang(self, tmp_path):
        path = self._write(tmp_path, {"cells": [["=sum(1 for _ in range(10**100))"]]})
        assert Grid().jsonload(path, policy=LoadPolicy.formulas_only()) == 0

    def test_approved_formulas_evaluate(self, tmp_path):
        path = self._write(tmp_path, {"cells": [[2, "=A1*3"]]})
        for policy in (LoadPolicy.trust_all(), None):
            g = Grid()
            assert g.jsonload(path, policy=policy) == 0
            assert g.cell(1, 0).val == 6

    def test_edits_stay_unevaluated_until_approved_reload(self, tmp_path):
        path = self._write(tmp_path, {"cells": [[2, "=A1*3"]]})
        g = Grid()
        g.jsonload(path, policy=LoadPolicy.formulas_only())
        g.setcell(2, 0, "=1+1")
        assert math.isnan(g.cell(2, 0).val)
        g.jsonload(path, policy=LoadPolicy.trust_all())
        assert g.cell(1, 0).val == 6

    def test_withheld_python_does_not_leak_into_next_load(self, tmp_path):
        untrusted = self._write(tmp_path, {"cells": [["=1"]]}, "a.json")
        other = self._write(tmp_path, {"cells": [["=2"]]}, "b.json")
        g = Grid()
        g.jsonload(untrusted, policy=LoadPolicy.formulas_only())
        g.jsonload(other, policy=None)
        assert g.cell(0, 0).val == 2
