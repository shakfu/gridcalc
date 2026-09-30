"""Security sandbox for formula evaluation and module loading."""

from __future__ import annotations

import ast
import importlib
import importlib.metadata
import json
import os
import re
import string
import warnings
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from ._module_names import NAMES

# Sandbox is on by default. Set GRIDCALC_SANDBOX=0 to disable.
# Can also be controlled via sandbox = true/false in gridcalc.toml.
_SANDBOX_ENV = os.environ.get("GRIDCALC_SANDBOX")
SANDBOX_ENABLED = _SANDBOX_ENV not in ("0", "false", "no") if _SANDBOX_ENV is not None else True


def configure_sandbox(enabled: bool) -> None:
    """Set sandbox state from config. Env var GRIDCALC_SANDBOX takes precedence."""
    global SANDBOX_ENABLED
    if _SANDBOX_ENV is None:
        SANDBOX_ENABLED = enabled


# Whether a safe module reaches a workbook as a `ModuleFacade`. Set from
# `module_facades` in the user config; off hands over the whole module.
FACADES_ENABLED = True


def configure_facades(enabled: bool) -> None:
    """Set facade use from config."""
    global FACADES_ENABLED
    FACADES_ENABLED = enabled


def _use_facades() -> bool:
    # With validation off, a facade restricts names and protects nothing.
    return SANDBOX_ENABLED and FACADES_ENABLED


# -- Module classification --

# A module is safe when it is handed to the workbook as a `ModuleFacade`: the
# reviewed names in `_module_names.NAMES` and nothing else.
SAFE_MODULES: frozenset[str] = frozenset(NAMES)

# Handed over whole, and flagged at the trust prompt. A module object reaches
# every module it imported, so these are unrestricted.
SIDE_EFFECT_MODULES: frozenset[str] = frozenset(
    {
        "matplotlib",
        "matplotlib.pyplot",
        "pandas",
        "csv",
        "xlsxwriter",
        # No facade yet. Most `sympy` functions `eval` a string argument.
        "sympy",
        "scipy",
        "scipy.cluster",
        "scipy.constants",
        "scipy.fft",
        "scipy.integrate",
        "scipy.interpolate",
        "scipy.linalg",
        "scipy.ndimage",
        "scipy.optimize",
        "scipy.signal",
        "scipy.sparse",
        "scipy.spatial",
        "scipy.special",
        "scipy.stats",
    }
)

BLOCKED_MODULES: frozenset[str] = frozenset(
    {
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
    }
)

MODULE_ALIASES: dict[str, str] = {
    "numpy": "np",
    "pandas": "pd",
    "matplotlib.pyplot": "plt",
}


def classify_module(name: str) -> str:
    """Classify a module as 'safe', 'side_effect', 'blocked', or 'unknown'.

    A submodule is classified by its own dotted name. Only 'blocked' passes
    down from a package: `numpy.ctypeslib` is not safe because `numpy` is.
    'safe' means a facade; 'side_effect' and an approved 'unknown' are whole
    modules. With facades off, a module that has one is 'side_effect'.
    """
    if name in BLOCKED_MODULES or name.split(".")[0] in BLOCKED_MODULES:
        return "blocked"
    if name in SAFE_MODULES:
        return "safe" if _use_facades() else "side_effect"
    if name in SIDE_EFFECT_MODULES:
        return "side_effect"
    return "unknown"


_SPEC_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.]*)\s*(==|>=|<=|>|<|~=)?\s*(.*)$")


class ModuleFacade:
    """The reviewed names of one approved module, and nothing else.

    A module object reaches every module it imported: `numpy.f2py.os` is `os`.
    The facade holds the listed functions, classes and constants, and a facade
    for each listed submodule. It keeps no reference to the module.
    """

    def __init__(self, name: str, members: dict[str, Any]) -> None:
        self.__dict__.update(members)
        self.__dict__["__name__"] = name

    def __getattr__(self, attr: str) -> Any:
        raise AttributeError(f"'{self.__dict__['__name__']}' has no '{attr}' in a workbook")

    def __setattr__(self, attr: str, value: Any) -> None:
        raise AttributeError("a module facade is read-only")

    def __delattr__(self, attr: str) -> None:
        raise AttributeError("a module facade is read-only")

    def __repr__(self) -> str:
        return f"<facade '{self.__dict__['__name__']}'>"


_ABSENT: Any = object()


def module_facade(name: str, mod: ModuleType) -> ModuleFacade:
    """Build the facade for ``mod``, a module with an entry in ``NAMES``."""
    members: dict[str, Any] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # reading a deprecated name warns
        for attr in NAMES[name]:
            # A name from another version is absent; a module is never a member.
            value = getattr(mod, attr, _ABSENT)
            if value is not _ABSENT and not isinstance(value, ModuleType):
                members[attr] = value
    prefix = name + "."
    for sub in NAMES:
        if sub.startswith(prefix) and "." not in sub[len(prefix) :]:
            members[sub[len(prefix) :]] = module_facade(sub, importlib.import_module(sub))
    return ModuleFacade(name, members)


def _parse_requirement(spec: str) -> tuple[str, str | None, str | None]:
    """Parse a requirement spec into (name, op, version).

    Accepts ``name``, ``name==1.2.3``, ``name>=1.0``, etc. Returns
    (name, None, None) when no version is pinned.
    """
    m = _SPEC_RE.match(spec)
    if not m:
        return spec.strip(), None, None
    name, op, ver = m.group(1), m.group(2), (m.group(3) or "").strip()
    if not op or not ver:
        return name, None, None
    return name, op, ver


def _version_tuple(v: str) -> tuple[int, ...]:
    """Best-effort conversion of a version string to a tuple of ints.

    Splits on ``.``; non-integer leading portions (e.g. ``2`` in ``2rc1``)
    are kept, the rest of the segment is dropped. Truncated comparison
    is good enough for the version-pinning use case here.
    """
    parts: list[int] = []
    for seg in v.split("."):
        m = re.match(r"\d+", seg)
        if m:
            parts.append(int(m.group()))
        else:
            break
    return tuple(parts)


def _check_version(installed: str, op: str, required: str) -> bool:
    a = _version_tuple(installed)
    b = _version_tuple(required)
    if op == "==":
        return a == b
    if op == ">=":
        return a >= b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == "<":
        return a < b
    if op == "~=":
        if len(b) < 2:
            return a >= b
        upper = b[:-1]
        upper = upper[:-1] + (upper[-1] + 1,)
        return a >= b and a[: len(upper)] < upper
    return True


def load_modules(
    specs: list[str], allow_unknown: bool = False
) -> tuple[dict[str, object], list[str]]:
    """Import modules by spec. Returns (alias_to_module, error_messages).

    Each spec is either a bare module name (``numpy``) or a name with a
    version specifier (``numpy>=1.24``, ``pandas==2.0.3``). Supported
    operators: ``==``, ``>=``, ``<=``, ``>``, ``<``, ``~=``.

    A safe module is returned as a ``ModuleFacade``; any other approved module
    is returned whole, and so is every module when facades are off.

    A module that no list classifies is refused unless ``allow_unknown``.
    The blocklist cannot be the only gate: it names the dangerous modules
    known when it was written, so anything omitted -- ``runpy``, which runs
    a Python file, or ``sqlite3``, which writes one -- was loaded on a
    workbook's say-so. Refusing happens before the import, so a module with
    import-time side effects does not get to run either.
    """
    result: dict[str, object] = {}
    errors: list[str] = []
    for spec in specs:
        name, op, ver = _parse_requirement(spec)
        cls = classify_module(name)
        if cls == "blocked":
            errors.append(f"'{name}' is blocked (security)")
            continue
        if cls == "unknown" and not allow_unknown:
            errors.append(f"'{name}' is not a recognised module and was not approved")
            continue
        try:
            mod = importlib.import_module(name)
        except ImportError:
            errors.append(f"'{name}' is not installed")
            continue
        if op is not None and ver is not None:
            try:
                installed = importlib.metadata.version(name.split(".")[0])
            except importlib.metadata.PackageNotFoundError:
                errors.append(f"'{name}': installed but version metadata not found")
                continue
            if not _check_version(installed, op, ver):
                errors.append(f"'{name}': installed {installed} does not satisfy {op}{ver}")
                continue
        alias = MODULE_ALIASES.get(name, name.split(".")[-1])
        result[alias] = module_facade(name, mod) if name in NAMES and _use_facades() else mod
    return result, errors


# -- AST formula validation --

_BLOCKED_NAMES: frozenset[str] = frozenset(
    {
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
        # `getattr` under another name, from `operator`.
        "attrgetter",
        "methodcaller",
    }
)

_DANGEROUS_ATTRS: frozenset[str] = frozenset(
    {
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
        # Attribute access named by a string: `operator` and `string.Formatter`.
        "attrgetter",
        "methodcaller",
        "vformat",
        "get_field",
    }
)


def _plain_fields(template: str) -> bool:
    """True if no replacement field in ``template`` reads an attribute or an item."""
    try:
        for _, name, spec, _ in string.Formatter().parse(template):
            if name and not (name.isidentifier() or name.isdigit()):
                return False
            if spec and not _plain_fields(spec):
                return False
    except ValueError:
        return False
    return True


def _node_error(node: ast.AST) -> str:
    """Why ``node`` is refused, or "" when it is allowed."""
    if isinstance(node, ast.Attribute):
        attr = node.attr
        if attr.startswith("__") and attr.endswith("__"):
            return f"dunder attribute '{attr}' is not allowed"
        if attr in _DANGEROUS_ATTRS:
            return f"attribute '{attr}' is not allowed"
        # `str.format` reads whatever attributes and items its template names:
        # `"{0.__globals__}".format(f)` is `f.__globals__` with no Attribute
        # node to refuse. A template built at run time cannot be checked here.
        if attr in ("format", "format_map"):
            template = node.value
            if not (
                isinstance(template, ast.Constant)
                and isinstance(template.value, str)
                and _plain_fields(template.value)
            ):
                return (
                    f"'{attr}' is allowed only on a string literal with plain "
                    "fields such as {}, {0} or {name}; use an f-string"
                )
    elif isinstance(node, ast.Name):
        name = node.id
        if name in _BLOCKED_NAMES:
            return f"name '{name}' is not allowed"
        if name.startswith("__") and name.endswith("__"):
            return f"dunder name '{name}' is not allowed"
    return ""


def validate_formula(source: str) -> tuple[bool, str]:
    """Validate a formula expression against security rules.

    Returns (is_valid, error_message). Blocks dunder attribute access,
    dangerous names, known internal attributes used in sandbox escapes, and
    `str.format` templates that read attributes or items.
    """
    if not SANDBOX_ENABLED:
        return True, ""

    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as e:
        return False, f"syntax error: {e}"

    for node in ast.walk(tree):
        error = _node_error(node)
        if error:
            return False, error

    return True, ""


def validate_code(source: str) -> tuple[bool, str]:
    """Validate a code block (statements) against security rules.

    Applies the same AST checks as validate_formula (dunder access,
    dangerous names/attrs) plus blocks import of blocked modules and
    dangerous builtins used as statements (eval/exec/open calls).
    """
    if not SANDBOX_ENABLED:
        return True, ""

    if not source or not source.strip():
        return True, ""

    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as e:
        return False, f"syntax error: {e}"

    for node in ast.walk(tree):
        # Block imports of blocked modules
        if isinstance(node, ast.Import):
            for alias in node.names:
                base = alias.name.split(".")[0]
                if alias.name in BLOCKED_MODULES or base in BLOCKED_MODULES:
                    return False, f"import of '{alias.name}' is blocked"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                base = node.module.split(".")[0]
                if node.module in BLOCKED_MODULES or base in BLOCKED_MODULES:
                    return False, f"import from '{node.module}' is blocked"
            # `from operator import attrgetter as g` would rename a blocked name.
            for alias in node.names:
                if alias.name in _BLOCKED_NAMES:
                    return False, f"import of '{alias.name}' is not allowed"
        # Same attribute and name checks as formulas
        else:
            error = _node_error(node)
            if error:
                return False, error

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
    unknown_modules: list[str] = field(default_factory=list)
    # PYTHON mode (declared, missing or unparseable) with at least one formula.
    python_formulas: bool = False

    @property
    def trust_needed(self) -> bool:
        """Whether loading the file runs Python: code, modules, or PYTHON-mode formulas."""
        return self.has_code or bool(self.requires) or self.python_formulas


@dataclass
class LoadPolicy:
    """Controls what gets loaded from a spreadsheet file."""

    load_code: bool = False
    approved_modules: list[str] = field(default_factory=list)
    # Whether modules no list classifies may be imported. Separate from
    # `approved_modules` because approval is per-file but this is a judgement
    # about a whole class of module, and the default has to be "no".
    allow_unknown: bool = False

    @staticmethod
    def trust_all(requires: list[str] | None = None) -> LoadPolicy:
        """Approve everything -- code block and all requested modules."""
        return LoadPolicy(load_code=True, approved_modules=list(requires or []), allow_unknown=True)

    @staticmethod
    def formulas_only() -> LoadPolicy:
        """Load cell data and formulas only, skip code and modules.

        PYTHON-mode formulas are Python, so they are loaded but not evaluated.
        """
        return LoadPolicy(load_code=False, approved_modules=[])


def inspect_file(filename: str) -> FileInfo | None:
    """Inspect a spreadsheet file without executing anything.

    Returns a FileInfo with metadata about code blocks, required modules,
    and cell/formula counts, or None if the file cannot be parsed.
    """
    # ValueError covers bad JSON, bad UTF-8 and an int over 4300 digits.
    try:
        with open(filename, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError, RecursionError):
        return None

    # This runs on a file chosen precisely because it is not yet trusted, so
    # every field it reads is checked before use. `[]` and `42` are valid JSON
    # and decode without error; a number in `code` or `requires` reaches
    # `.strip()` and the requirement regex. Either one raised out of a
    # function whose contract is to report failure by returning None -- and it
    # raised inside `:open`, before the load, taking curses down with it.
    if not isinstance(d, dict):
        return None

    info = FileInfo()

    code = d.get("code", "")
    if not isinstance(code, str):
        return None
    if code.strip():
        info.has_code = True
        info.code_lines = len(code.strip().splitlines())
        info.code_preview = code.strip()

    requires = d.get("requires", [])
    if isinstance(requires, list):
        if not all(isinstance(m, str) for m in requires):
            return None
        info.requires = list(requires)
        info.blocked_modules = [
            m for m in requires if classify_module(_parse_requirement(m)[0]) == "blocked"
        ]
        info.side_effect_modules = [
            m for m in requires if classify_module(_parse_requirement(m)[0]) == "side_effect"
        ]
        info.unknown_modules = [
            m for m in requires if classify_module(_parse_requirement(m)[0]) == "unknown"
        ]

    # v2 nests cells under `sheets[].cells`; v1 has them at top level.
    # Count across every sheet -- a prompt that under-reports cells on
    # multi-sheet files trains the user to ignore it.
    sheets = d.get("sheets")
    if isinstance(sheets, list) and sheets:
        for entry in sheets:
            if isinstance(entry, dict):
                _count_cells(entry.get("cells", []), info)
    else:
        _count_cells(d.get("cells", []), info)

    from .engine import Mode  # lazy: engine imports this module

    # The same rule `jsonload` applies, so the two cannot disagree.
    mode = Mode.parse(d["mode"]) if "mode" in d else None
    info.python_formulas = (mode or Mode.PYTHON) == Mode.PYTHON and info.formula_count > 0

    return info


def _count_cells(rows: Any, info: FileInfo) -> None:
    """Accumulate cell and formula counts from one sheet's rows list."""
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, list):
            continue
        for v in row:
            cell_val = v
            if isinstance(v, dict):
                cell_val = v.get("v", None)
            if cell_val is None or (isinstance(cell_val, str) and cell_val == ""):
                continue
            info.cell_count += 1
            if isinstance(cell_val, str) and cell_val.startswith("="):
                info.formula_count += 1
