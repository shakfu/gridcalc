"""Security sandbox for formula evaluation and module loading."""

from __future__ import annotations

import ast
import importlib
import os
from dataclasses import dataclass, field

# Global kill switch. During development, sandbox is off by default.
# Set PYCALC_SANDBOX=1 to enable all sandbox checks (AST validation, trust prompt).
# Can also be enabled via sandbox = true in pycalc.toml.
_SANDBOX_ENV = os.environ.get("PYCALC_SANDBOX")
SANDBOX_ENABLED = _SANDBOX_ENV in ("1", "true", "yes") if _SANDBOX_ENV is not None else False


def configure_sandbox(enabled: bool):
    """Set sandbox state from config. Env var PYCALC_SANDBOX takes precedence."""
    global SANDBOX_ENABLED
    if _SANDBOX_ENV is None:
        SANDBOX_ENABLED = enabled


# -- Module classification --

SAFE_MODULES: frozenset[str] = frozenset({
    "numpy",
    "scipy",
    "sympy",
    "decimal",
    "fractions",
    "statistics",
    "cmath",
    "itertools",
    "functools",
    "operator",
    "collections",
})

SIDE_EFFECT_MODULES: frozenset[str] = frozenset({
    "matplotlib",
    "matplotlib.pyplot",
    "pandas",
    "csv",
    "openpyxl",
    "xlsxwriter",
})

BLOCKED_MODULES: frozenset[str] = frozenset({
    "os",
    "sys",
    "subprocess",
    "shutil",
    "pathlib",
    "socket",
    "http",
    "importlib",
    "ctypes",
    "code",
    "pickle",
    "shelve",
    "signal",
    "multiprocessing",
    "webbrowser",
    "urllib",
    "xmlrpc",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "nntplib",
    "tempfile",
    "io",
    "builtins",
})

MODULE_ALIASES: dict[str, str] = {
    "numpy": "np",
    "pandas": "pd",
    "matplotlib.pyplot": "plt",
}


def classify_module(name: str) -> str:
    """Classify a module as 'safe', 'side_effect', 'blocked', or 'unknown'."""
    base = name.split(".")[0]
    if name in BLOCKED_MODULES or base in BLOCKED_MODULES:
        return "blocked"
    if name in SAFE_MODULES or base in SAFE_MODULES:
        return "safe"
    if name in SIDE_EFFECT_MODULES or base in SIDE_EFFECT_MODULES:
        return "side_effect"
    return "unknown"


def load_modules(names: list[str]) -> tuple[dict[str, object], list[str]]:
    """Import modules by name. Returns (alias_to_module, error_messages)."""
    result: dict[str, object] = {}
    errors: list[str] = []
    for name in names:
        cls = classify_module(name)
        if cls == "blocked":
            errors.append(f"'{name}' is blocked (security)")
            continue
        try:
            mod = importlib.import_module(name)
            alias = MODULE_ALIASES.get(name, name.split(".")[-1])
            result[alias] = mod
        except ImportError:
            errors.append(f"'{name}' is not installed")
    return result, errors


# -- AST formula validation --

_BLOCKED_NAMES: frozenset[str] = frozenset({
    "__import__",
    "__builtins__",
    "__loader__",
    "__spec__",
    "__build_class__",
    "__name__",
    "eval",
    "exec",
    "compile",
    "breakpoint",
    "exit",
    "quit",
    "open",
    "input",
    "getattr",
    "setattr",
    "delattr",
    "vars",
    "dir",
    "globals",
    "locals",
    "type",
    "super",
    "object",
    "classmethod",
    "staticmethod",
    "property",
    "memoryview",
    "bytearray",
    "bytes",
})

_DANGEROUS_ATTRS: frozenset[str] = frozenset({
    # Function/method internals
    "func_globals",
    "func_code",
    "func_defaults",
    # Generator/coroutine internals
    "gi_frame",
    "gi_code",
    "cr_frame",
    "cr_code",
    "ag_frame",
    "ag_code",
    # Frame internals
    "f_globals",
    "f_locals",
    "f_builtins",
    "f_code",
    # Code object internals
    "co_consts",
    "co_code",
    "co_filename",
    "co_names",
    "co_varnames",
    "co_freevars",
    "co_cellvars",
    # Traceback internals
    "tb_frame",
    "tb_next",
    "tb_lineno",
    # Bound method internals
    "im_func",
    "im_self",
})


def validate_formula(source: str) -> tuple[bool, str]:
    """Validate a formula expression against security rules.

    Returns (is_valid, error_message). Blocks dunder attribute access,
    dangerous names, and known internal attributes used in sandbox escapes.
    """
    if not SANDBOX_ENABLED:
        return True, ""

    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as e:
        return False, f"syntax error: {e}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("__") and attr.endswith("__"):
                return False, f"dunder attribute '{attr}' is not allowed"
            if attr in _DANGEROUS_ATTRS:
                return False, f"attribute '{attr}' is not allowed"
        elif isinstance(node, ast.Name):
            name = node.id
            if name in _BLOCKED_NAMES:
                return False, f"name '{name}' is not allowed"
            if name.startswith("__") and name.endswith("__"):
                return False, f"dunder name '{name}' is not allowed"

    return True, ""


# -- File inspection and load policy --


@dataclass
class FileInfo:
    """Metadata extracted from a spreadsheet file without executing it."""

    has_code: bool = False
    code_preview: str = ""
    code_lines: int = 0
    requires: list[str] = field(default_factory=list)
    formula_count: int = 0
    cell_count: int = 0
    blocked_modules: list[str] = field(default_factory=list)
    side_effect_modules: list[str] = field(default_factory=list)


@dataclass
class LoadPolicy:
    """Controls what gets loaded from a spreadsheet file."""

    load_code: bool = False
    approved_modules: list[str] = field(default_factory=list)

    @staticmethod
    def trust_all(requires: list[str] | None = None) -> LoadPolicy:
        """Approve everything -- code block and all requested modules."""
        return LoadPolicy(load_code=True, approved_modules=list(requires or []))

    @staticmethod
    def formulas_only() -> LoadPolicy:
        """Load cell data and formulas only, skip code and modules."""
        return LoadPolicy(load_code=False, approved_modules=[])
