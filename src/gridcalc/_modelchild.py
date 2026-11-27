"""Child process for :mod:`gridcalc.modelrun`: run one model, report its writes.

Reads one JSON request on stdin and writes one JSON reply on stdout. The
model's own ``print`` output goes to the reply's ``log``. See
``docs/dev/crosstab-model.md`` for the protocol.
"""

from __future__ import annotations

import _thread
import builtins
import contextlib
import io
import json
import os
import re
import shutil
import sys
from typing import Any

FILENAME = "<model>"
# Output kept and forwarded per run; past this the rest is dropped and noted.
MAX_LOG = 1 << 20


class _Log(io.TextIOBase):
    """The model's stdout: kept for the reply and sent to the parent as it is written.

    Each chunk goes out as one ``O <json string>`` line on the real stdout,
    ahead of the ``R <json>`` reply line, so the parent can show it live.
    """

    def __init__(self, out: Any) -> None:
        self._out = out
        self._parts: list[str] = []
        self._size = 0
        self._full = False

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if self._full or not text:
            return len(text)
        if self._size + len(text) > MAX_LOG:
            text = text[: MAX_LOG - self._size] + "\n[output truncated at 1 MB]\n"
            self._full = True
        self._parts.append(text)
        self._size += len(text)
        self._out.write("O " + json.dumps(text) + "\n")
        self._out.flush()
        return len(text)

    def getvalue(self) -> str:
        return "".join(self._parts)


# A C module with no submodules or module attributes, so it needs no facade.
_WHOLE_MODULES = frozenset({"math"})


def _limit(mem_mb: int, cpu_s: int) -> None:
    """Cap address space and CPU time where the OS enforces them (not on Windows)."""
    try:
        import resource
    except ImportError:
        return
    # The CPU hard limit sits a second past the soft one. At the soft limit the
    # process gets SIGXCPU; with the two equal, Linux sends SIGKILL with it.
    limits = (
        (resource.RLIMIT_AS, mem_mb << 20, mem_mb << 20),
        (resource.RLIMIT_CPU, cpu_s, cpu_s + 1),
    )
    for which, soft, hard in limits:
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(which, (soft, hard))


def _key(k: Any) -> Any:
    return tuple(k) if isinstance(k, list) else k


# Audit events a model may not cause (`sys.addaudithook`). The AST validator
# and the trimmed builtins stop the direct routes; this stops the ones they
# miss, such as a class reached through `__subclasses__`. Prefixes match
# CPython's audit event table.
_DENIED = (
    "subprocess.",
    "os.system",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
    "os.fork",
    "os.forkpty",
    "os.kill",
    "os.remove",
    "os.rename",
    "os.rmdir",
    "os.mkdir",
    "os.chmod",
    "os.chown",
    "os.chflags",
    "os.truncate",
    "os.symlink",
    "os.link",
    "os.utime",
    "os.chdir",
    "os.putenv",
    "os.unsetenv",
    "os.setxattr",
    "os.removexattr",
    "os.add_dll_directory",
    "shutil.",
    "socket.",
    "ctypes.",
    "pty.",
    "fcntl.",
    "resource.setrlimit",
    "resource.prlimit",
    "sys.addaudithook",
    "sys.settrace",
    "sys.setprofile",
    "sqlite3.",
    "webbrowser.",
    "urllib.",
    "http.client.",
    "ftplib.",
    "smtplib.",
    "poplib.",
    "imaplib.",
    "nntplib.",
    "winreg.",
    "_winapi.",
    "msvcrt.",
)
# Raised by an allowed module's own import: numpy loads a library with ctypes
# and sets environment variables; on Windows it adds DLL directories. Allowed
# only while `_import` runs.
_IMPORT_ONLY = frozenset(
    {"ctypes.dlopen", "ctypes.dlsym", "os.putenv", "os.unsetenv", "os.add_dll_directory"}
)
# Raised on Windows by `subprocess.Popen` itself, before its own event: an fd
# mapped to a handle, and the pipes for the solver's output.
_POPEN_WINDOWS = frozenset({"msvcrt.get_osfhandle", "_winapi.CreatePipe"})
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_importing = 0
_popen_thread: int | None = None  # see `_audit`

# The pulp backend's exceptions, set by `run`: PuLP writes its model and
# solution files in `_tmp`, and starts one of `_programs` (or a program under
# `_program_dirs`, PuLP's bundled solvers) to solve.
_tmp: str | None = None
_programs: frozenset[str] = frozenset()
_program_dirs: tuple[str, ...] = ()
_PULP: Any = None
_PYOMO: Any = None  # `pyomo.environ`, for the pyomo backend
_CPSAT: Any = None  # `ortools.sat.python.cp_model`, for the cpsat backend
_CP_FACADES: dict[str, Any] = {}  # the importable `ortools` names, set by `_setup_cpsat`
_CP_SOLVER: Any = None  # the model's one solved CpSolver, read for status and outputs
# CP-SAT's two ways of refusing a float: its own check, and pybind11 finding no overload.
_CP_INT_ERROR = re.compile(r"only accept integer|incompatible function arguments")
# What a cpsat model sees of `cp_model`. Left out: the modules it imported
# (`cmh`, `np`, `pd`, `threading`, ...), typing aliases and private helpers.
_CP_MODEL_NAMES = frozenset(
    {
        "CpModel",
        "CpSolver",
        "CpSolverSolutionCallback",
        "ObjectiveSolutionPrinter",
        "VarArraySolutionPrinter",
        "VarArrayAndObjectiveSolutionPrinter",
        "LinearExpr",
        "IntVar",
        "IntervalVar",
        "Constraint",
        "BoundedLinearExpression",
        "Domain",
        "UNKNOWN",
        "MODEL_INVALID",
        "FEASIBLE",
        "INFEASIBLE",
        "OPTIMAL",
        "INT_MIN",
        "INT_MAX",
        "INT32_MIN",
        "INT32_MAX",
        "CHOOSE_FIRST",
        "CHOOSE_LOWEST_MIN",
        "CHOOSE_HIGHEST_MAX",
        "CHOOSE_MIN_DOMAIN_SIZE",
        "CHOOSE_MAX_DOMAIN_SIZE",
        "SELECT_MIN_VALUE",
        "SELECT_MAX_VALUE",
        "SELECT_LOWER_HALF",
        "SELECT_UPPER_HALF",
        "SELECT_MEDIAN_VALUE",
        "SELECT_RANDOM_HALF",
        "AUTOMATIC_SEARCH",
        "FIXED_SEARCH",
        "PORTFOLIO_SEARCH",
        "LP_SEARCH",
        "PSEUDO_COST_SEARCH",
        "PORTFOLIO_WITH_QUICK_RESTART_SEARCH",
        "HINT_SEARCH",
        "PARTIAL_FIXED_SEARCH",
        "RANDOMIZED_SEARCH",
    }
)


def _inside(path: Any, root: str | None) -> bool:
    if root is None or not isinstance(path, (str, bytes, os.PathLike)):
        return False
    real = os.path.normcase(os.path.realpath(os.fsdecode(path)))
    return real == root or real.startswith(root + os.sep)


def _first_word(cmdline: str) -> str:
    """The program in a Windows command line, as `subprocess.list2cmdline` quotes it."""
    if cmdline.startswith('"'):
        return cmdline[1:].split('"', 1)[0]
    return cmdline.split(None, 1)[0] if cmdline.strip() else ""


def _allowed_program(args: tuple[Any, ...]) -> bool:
    exe = args[0] if args else None
    argv = args[1] if len(args) > 1 else None
    if exe is None and isinstance(argv, (list, tuple)) and argv:
        exe = argv[0]
    elif exe is None and isinstance(argv, str):
        exe = _first_word(argv)  # Windows joins argv before the event
    if not isinstance(exe, (str, bytes, os.PathLike)) or not exe:
        return False
    exe = os.fsdecode(exe)
    if os.path.basename(exe) == exe:
        # A bare name runs from PATH, as PuLP starts a `cbc` it found there.
        env = args[3] if len(args) > 3 and isinstance(args[3], dict) else None
        found = shutil.which(exe, path=(env or {}).get("PATH"))
        if found is None:
            return False
        exe = found
    real = os.path.normcase(os.path.realpath(exe))
    return real in _programs or any(_inside(real, d) for d in _program_dirs)


# The solver library variables Pyomo clears before starting an AMPL solver
# such as ipopt. A non-empty value names a shared library the solver loads,
# so only clearing them is allowed: setting one would load the model's code.
_AMPLFUNC = (b"AMPLFUNC", b"PYOMO_AMPLFUNC")


def _cleared_amplfunc(args: tuple[Any, ...]) -> bool:
    key = os.fsencode(args[0]) if args and isinstance(args[0], (str, bytes)) else b""
    value = args[1] if len(args) > 1 else b""
    return key in _AMPLFUNC and value in (b"", "")


def _audit(event: str, args: tuple[Any, ...]) -> None:
    """Refuse writes, processes, sockets and native calls once the model runs."""
    global _popen_thread
    if event == "open" and isinstance(args[0], int):
        return  # an already open descriptor: no new file, as Pyomo's mkstemp files
    if event == "open":
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        writes = isinstance(mode, str) and any(ch in mode for ch in "wax+")
        # `os.devnull` takes discarded output, such as a solver's with msg=0.
        sink = args[0] == os.devnull or _inside(args[0], _tmp)
        if (writes or (isinstance(flags, int) and flags & _WRITE_FLAGS)) and not sink:
            raise PermissionError(f"a model may not write files ({args[0]!r})")
        return
    if event in ("os.remove", "os.rename") and args and _inside(args[0], _tmp):
        return
    if event == "subprocess.Popen" and _allowed_program(args):
        _popen_thread = _thread.get_ident()
        return
    # Windows follows Popen's event with this one. CPython passes its command
    # line object as a C string, so its args are unreadable: it is allowed only
    # once, on the thread of a Popen just allowed.
    if event == "_winapi.CreateProcess" and _popen_thread == _thread.get_ident():
        _popen_thread = None
        return
    if _tmp is not None and event in _POPEN_WINDOWS:
        return
    if _importing and event in _IMPORT_ONLY:
        return
    if event in ("os.putenv", "os.unsetenv") and _tmp is not None and _cleared_amplfunc(args):
        return
    if event.startswith(_DENIED):
        if event == "subprocess.Popen":
            # The program, so a refused solver can be told from a refused command.
            raise PermissionError(f"a model may not use {event} ({args[:2]!r})")
        raise PermissionError(f"a model may not use {event}")


def _import(
    name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0
) -> Any:
    from . import lpmodel
    from ._module_names import NAMES
    from .sandbox import classify_module, module_facade

    global _importing
    if level == 0 and name == "pulp":
        return _PULP if _PULP is not None else lpmodel
    if level == 0 and _PYOMO is not None and name.split(".")[0] == "pyomo":
        import importlib

        _importing += 1
        try:
            mod = importlib.import_module(name)
        finally:
            _importing -= 1
        # As `__import__`: `import pyomo.environ as pyo` gets the package back.
        return mod if fromlist else sys.modules["pyomo"]
    if level == 0 and _CPSAT is not None and name.split(".")[0] == "ortools":
        if name not in _CP_FACADES:
            raise ImportError(
                f"import of {name!r} is not allowed in a model; use ortools.sat.python.cp_model"
            )
        return _CP_FACADES[name] if fromlist else _CP_FACADES["ortools"]
    whole = name in _WHOLE_MODULES
    if level != 0 or not (whole or (classify_module(name) == "safe" and name in NAMES)):
        raise ImportError(f"import of {name!r} is not allowed in a model")
    import importlib

    _importing += 1
    try:
        mod = importlib.import_module(name)
        return mod if whole else module_facade(name, mod)
    finally:
        _importing -= 1


def _integral(v: Any) -> Any:
    """``v`` as an int if it is a whole float: cells hold floats, and CP-SAT takes ints only."""
    if isinstance(v, list):
        return [_integral(x) for x in v]
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _items(spec: dict[str, Any], ints: bool = False) -> dict[str, Any]:
    from .itemdict import _RAISE, ItemDict

    num = _integral if ints else (lambda v: v)
    out: dict[str, Any] = {}
    for name, it in spec.items():
        if it["kind"] == "indexed":
            keys = [_key(k) for k in it["keys"]]
            values = {_key(k): num(v) for k, v in it["values"]}
            missing = num(it["missing"][0]) if it["missing"] else _RAISE
            out[name] = ItemDict(name, keys, values, missing)
        else:
            out[name] = num(it["value"])
    return out


def _cp_found() -> bool:
    """Whether the model's CpSolver found a solution; after any other status its values are junk."""
    s = _CP_SOLVER
    return s is not None and s.response_proto.status in (_CPSAT.OPTIMAL, _CPSAT.FEASIBLE)


def _cp_value(where: str, x: Any) -> Any:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return x
    if _CP_SOLVER is None:
        raise ValueError(f"{where}: an output needs exactly one solved CpSolver as a global")
    if not _cp_found():
        return None
    try:
        return _CP_SOLVER.value(x)
    except TypeError:
        raise ValueError(f"{where} is not a CP-SAT variable or expression") from None


def _value(name: str, key: Any, x: Any) -> Any:
    """A bound entry's value: a variable's or expression's after the solve, or a number."""
    from . import lpmodel

    where = f"{name}[{key!r}]" if key is not None else name
    if _CPSAT is not None:
        v = _cp_value(where, x)
    elif _PYOMO is not None:
        v = _PYOMO.value(x, exception=False)
    else:
        lib = _PULP if _PULP is not None else lpmodel
        v = lib.value(x)
    if v is None:
        raise ValueError(f"{where} has no value; the solve did not find one")
    return v


def _lookup(d: Any, key: Any) -> Any:
    """``d[key]``, or ``d[k0][k1]`` for the nested dicts `LpVariable.dicts` makes."""
    if not isinstance(d, (str, bytes)) and hasattr(d, "__getitem__") and key in d:
        return d[key]  # a dict, or a mapping such as Pyomo's indexed variable
    if isinstance(key, tuple) and isinstance(d, dict) and key and key[0] in d:
        return _lookup(d[key[0]], key[1:] if len(key) > 2 else key[1])
    raise KeyError(key)


def _bound(name: str, original: Any, now: Any) -> dict[str, Any]:
    """The writes for an output item the model rebound to its variables."""
    from .itemdict import ItemDict

    if not isinstance(original, ItemDict):
        return {"value": _value(name, None, now)}
    if isinstance(now, (str, bytes)) or not hasattr(now, "__contains__"):
        raise ValueError(
            f"{name} is an output; bind it to a dict of variables, not {type(now).__name__}"
        )
    pairs = []
    for key in sorted(original.index_keys, key=repr):
        try:
            x = _lookup(now, key)
        except KeyError:
            raise ValueError(f"{name}: no value for key {key!r} in the dict bound to it") from None
        pairs.append([key, _value(name, key, x)])
    return {"pairs": pairs}


def _pyomo_summary(ns: dict[str, Any]) -> tuple[str | None, float | None]:
    """Status from the one solver result in ``ns``; objective from the one model's objective."""
    from pyomo.opt import SolverResults, TerminationCondition  # type: ignore[import-untyped]

    pyo = _PYOMO
    results = [v for v in ns.values() if isinstance(v, SolverResults)]
    status = None
    if len(results) == 1:
        tc = results[0].solver.termination_condition
        status = {
            TerminationCondition.optimal: "Optimal",
            TerminationCondition.infeasible: "Infeasible",
            TerminationCondition.unbounded: "Unbounded",
        }.get(tc, str(tc).capitalize())
    models = [v for v in ns.values() if isinstance(v, pyo.ConcreteModel)]
    objective = None
    if len(models) == 1:
        objs = list(models[0].component_data_objects(pyo.Objective, active=True))
        if len(objs) == 1:
            objective = pyo.value(objs[0], exception=False)
    return status, objective


def _problem_summary(ns: dict[str, Any]) -> tuple[str | None, float | None]:
    """Status and objective of the one solved LpProblem in ``ns``, if exactly one."""
    from . import lpmodel

    if _PYOMO is not None:
        return _pyomo_summary(ns)
    if _CPSAT is not None:
        return _cpsat_summary(ns)

    lib = _PULP if _PULP is not None else lpmodel
    LpProblem, LpStatus, value = lib.LpProblem, lib.LpStatus, lib.value  # noqa: N806
    LpStatusNotSolved = lib.LpStatusNotSolved  # noqa: N806

    solved = [v for v in ns.values() if isinstance(v, LpProblem) and v.status != LpStatusNotSolved]
    if len(solved) != 1:
        return None, None
    p = solved[0]
    obj = value(p.objective) if p.objective is not None else None
    return LpStatus[p.status], obj


def _cpsat_summary(ns: dict[str, Any]) -> tuple[str | None, float | None]:
    """Status of the one solved CpSolver; objective if the one CpModel has one and it was found."""
    if _CP_SOLVER is None:
        return None, None
    status = _CP_SOLVER.response_proto.status.name.replace("_", " ").capitalize()
    models = [v for v in ns.values() if isinstance(v, _CPSAT.CpModel)]
    if _cp_found() and len(models) == 1 and models[0].has_objective():
        return status, _CP_SOLVER.objective_value
    return status, None


def _one_cp_solver(ns: dict[str, Any]) -> Any:
    solvers = [v for v in ns.values() if isinstance(v, _CPSAT.CpSolver)]
    if len(solvers) != 1:
        return None
    try:
        solvers[0].response_proto  # noqa: B018  (raises RuntimeError before a solve)
    except RuntimeError:
        return None
    return solvers[0]


def _setup_cpsat() -> None:
    """Import CP-SAT, refuse its one native file write, and build the facades. Before the hook.

    The audit hook cannot see a write from C++, so ``export_to_file`` is
    replaced at the helper both its spellings call.
    """
    global _CPSAT
    from ortools.sat.python import cp_model, cp_model_helper

    from .sandbox import ModuleFacade

    def refused(*_args: Any) -> bool:
        raise PermissionError("a model may not write files (CpModel.export_to_file)")

    cp_model_helper.CpSatHelper.write_model_to_file = staticmethod(refused)  # type: ignore[method-assign,assignment]
    solve = cp_model.CpSolver.solve

    def logged_solve(self: Any, model: Any, solution_callback: Any = None) -> Any:
        # CP-SAT logs from C++ to the real stdout, past the model output.
        if self.parameters.log_search_progress and self.log_callback is None:
            self.parameters.log_to_stdout = False
            self.log_callback = print
        return solve(self, model, solution_callback)

    cp_model.CpSolver.solve = cp_model.CpSolver.Solve = logged_solve  # type: ignore[method-assign]
    members = {n: getattr(cp_model, n) for n in _CP_MODEL_NAMES if hasattr(cp_model, n)}
    leaf = ModuleFacade("ortools.sat.python.cp_model", members)
    python = ModuleFacade("ortools.sat.python", {"cp_model": leaf})
    sat = ModuleFacade("ortools.sat", {"python": python})
    _CP_FACADES.update(
        {
            "ortools": ModuleFacade("ortools", {"sat": sat}),
            "ortools.sat": sat,
            "ortools.sat.python": python,
            "ortools.sat.python.cp_model": leaf,
        }
    )
    _CPSAT = cp_model


def _setup_pyomo(req: dict[str, Any]) -> None:
    """Import Pyomo and record what its solvers may write and run. Before the hook."""
    global _PYOMO
    import pyomo.environ  # type: ignore[import-untyped]
    import pyomo.opt  # noqa: F401  (`_pyomo_summary` reads its result types)

    _PYOMO = pyomo.environ
    _confine_programs(req)


def _setup_pulp(req: dict[str, Any]) -> None:
    """Import the PuLP library and record what it may write and run. Before the hook."""
    global _PULP
    import pulp  # type: ignore[import-untyped]

    major = int(str(getattr(pulp, "__version__", "0")).split(".")[0] or 0)
    if major >= 4:
        raise ImportError(
            f"PuLP {pulp.__version__} is a different API; the pulp backend needs PuLP 2 or 3"
        )
    _PULP = pulp
    _confine_programs(req)


def _confine_programs(req: dict[str, Any]) -> None:
    """Record the temp dir and solver programs a program backend may use."""
    global _tmp, _programs, _program_dirs
    _tmp = os.path.normcase(os.path.realpath(req["tmp"]))
    _programs = frozenset(os.path.normcase(os.path.realpath(p)) for p in req.get("programs", []))
    _program_dirs = tuple(
        os.path.normcase(os.path.realpath(d)) for d in req.get("program_dirs", [])
    )


def run_gmpl(req: dict[str, Any], log: Any) -> dict[str, Any]:
    """Run a GMPL model under glpsol and fill output items from its report."""
    import shutil
    import subprocess

    from . import gmpl

    _confine_programs(req)
    glpsol = shutil.which("glpsol")
    if glpsol is None:
        return {"ok": False, "error": "glpsol from GLPK is not on PATH", "line": None, "log": ""}
    text = req["text"]
    data, errors = gmpl.data_file(req["items"], gmpl.declared(text))
    if errors:
        return {"ok": False, "error": "; ".join(errors), "line": None, "log": ""}
    tmp = _tmp or ""
    mod, dat, report = (os.path.join(tmp, n) for n in ("model.mod", "data.dat", "report.txt"))
    with open(mod, "w", encoding="utf-8") as f:
        f.write(text)
    with open(dat, "w", encoding="utf-8") as f:
        f.write(data)
    sys.addaudithook(_audit)
    proc = subprocess.Popen(  # noqa: S603  (allowlisted by the audit hook)
        [glpsol, "--math", mod, "-d", dat, "-o", report],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=tmp,
    )
    for line in proc.stdout or []:
        log.write(line)
    proc.wait()
    if proc.returncode != 0 or not os.path.exists(report):
        out = log.getvalue()
        # glpsol names the file and line: `model.mod:4: syntax error`.
        m = re.search(r"model\.mod:(\d+):\s*(.*)", out)
        if m:
            return {"ok": False, "error": m.group(2), "line": int(m.group(1)), "log": out}
        return {"ok": False, "error": "glpsol failed", "line": None, "log": out}
    with open(report, encoding="utf-8") as f:
        result = gmpl.read_report(f.read())
    status = gmpl.status_text(result["status"])
    objective = result["objective"]
    values: dict[str, dict[Any, float]] = {}
    for name, v in result["columns"].items():
        base, key = gmpl.parse_name(name)
        values.setdefault(base, {})[key] = v
    writes: dict[str, Any] = {}
    problems: list[str] = []
    for name, spec in req["items"].items():
        if not spec.get("output"):
            continue
        if status != "Optimal":
            problems.append(f"{name} has no value; the solve did not find one ({status})")
            continue
        if spec["kind"] != "indexed":
            if objective is not None and objective[0] == name:
                writes[name] = {"value": objective[1]}
            elif None in values.get(name, {}):
                writes[name] = {"value": values[name][None]}
            else:
                problems.append(f"{name}: the model has no variable or objective of that name")
            continue
        found = values.get(name)
        if found is None:
            problems.append(f"{name}: the model has no variable of that name")
            continue
        pairs = []
        for k in spec["keys"]:
            key = tuple(k) if isinstance(k, list) else k
            if key not in found:
                problems.append(f"{name}: the model's {name} has no entry for key {key!r}")
                break
            pairs.append([k, found[key]])
        else:
            writes[name] = {"pairs": pairs}
    if problems:
        return _fail("; ".join(problems), log.getvalue(), status=status)
    return {
        "ok": True,
        "writes": writes,
        "status": status,
        "objective": objective[1] if objective else None,
        "log": log.getvalue(),
    }


_OMP_TMP_WARNING = re.compile(r"^OMP: Warning #179: .*/tmp file failed:\n?", re.MULTILINE)


def _fail(
    error: str, log: str = "", line: int | None = None, status: str | None = None
) -> dict[str, Any]:
    """A failure reply; ``status`` is the solve's, when one ran, so a caller can tell infeasible."""
    return {"ok": False, "error": error, "line": line, "log": log, "status": status}


def _mzn_error(errors: list[dict[str, Any]], model: str) -> tuple[str, int | None]:
    """The first MiniZinc error as text, with its line when it is in the model file."""
    e = errors[0]
    loc = e.get("location") or {}
    line = loc.get("firstLine") if str(loc.get("filename", "")).endswith(model) else None
    what = str(e.get("what", "error"))
    return f"{what}: {e.get('message', '')}", line if isinstance(line, int) else None


def run_minizinc(req: dict[str, Any], log: Any) -> dict[str, Any]:
    """Run a MiniZinc model under `minizinc` and fill output items from its last solution."""
    import shutil
    import subprocess

    from . import minizinc

    _confine_programs(req)
    exe = shutil.which("minizinc")
    if exe is None:
        return _fail("the minizinc program is not on PATH")
    text = req["text"]
    tmp = _tmp or ""
    solver = minizinc.solver(text)
    if solver is not None and not minizinc.solver_known(solver, req.get("solvers", [])):
        return _fail(f"'% solver: {solver}' is not an installed MiniZinc solver's id or tag")
    flags = ["--solver", solver] if solver else []
    mod, dat = os.path.join(tmp, "model.mzn"), os.path.join(tmp, "data.json")
    with open(mod, "w", encoding="utf-8") as f:
        f.write(text)
    sys.addaudithook(_audit)

    def mzn(*args: str) -> str:
        proc = subprocess.run(  # noqa: S603  (allowlisted by the audit hook)
            [exe, *flags, *args], capture_output=True, text=True, check=False, cwd=tmp
        )
        # CBC's OpenMP runtime warns, as it loads, that the sandbox refused its file in /tmp.
        return _OMP_TMP_WARNING.sub("", proc.stdout + proc.stderr)

    iface = minizinc.read_stream(mzn("--json-stream", "--model-interface-only", mod))
    if iface["errors"]:
        error, line = _mzn_error(iface["errors"], "model.mzn")
        return _fail(error, iface["log"], line)
    data, errors = minizinc.data(req["items"], iface["inputs"])
    if errors:
        return _fail("; ".join(errors))
    if data:  # MiniZinc refuses `{}` as a data file
        with open(dat, "w", encoding="utf-8") as f:
            json.dump(data, f)
    # Past MiniZinc's own limit it stops and reports its best solution; the parent kills.
    limit_ms = max(1000, int((float(req.get("timeout_s", 120)) - 3) * 1000))
    args = ["--json-stream", "--output-mode", "json", "--output-objective"]
    files = [mod, dat] if data else [mod]
    result = minizinc.read_stream(mzn(*args, "--time-limit", str(limit_ms), *files))
    if result["log"]:
        log.write(result["log"] + "\n")
    if result["errors"]:
        error, line = _mzn_error(result["errors"], "model.mzn")
        return _fail(error, log.getvalue(), line)
    solution, status = result["solution"], result["status"]
    writes: dict[str, Any] = {}
    problems: list[str] = []
    for name, spec in req["items"].items():
        if not spec.get("output"):
            continue
        if solution is None:
            problems.append(f"{name} has no value; the solve did not find one ({status})")
            continue
        if name not in solution:
            problems.append(f"{name}: the model has no output variable of that name")
            continue
        try:
            if spec["kind"] != "indexed":
                writes[name] = {"value": minizinc.plain(solution[name])}
                continue
            orders = minizinc.index_orders(name, spec, req["items"])
            if isinstance(orders, str):
                problems.append(orders)
                continue
            writes[name] = {"pairs": minizinc.pairs(orders, solution[name])}
        except ValueError as exc:
            problems.append(f"{name}: {exc}")
    if problems:
        return _fail("; ".join(problems), log.getvalue(), status=status)
    objective = solution.get("_objective") if solution else None
    return {
        "ok": True,
        "writes": writes,
        "status": status,
        "objective": objective if isinstance(objective, (int, float)) else None,
        "log": log.getvalue(),
    }


def run(req: dict[str, Any], out: Any = None) -> dict[str, Any]:
    global _CP_SOLVER
    from .itemdict import ItemDict
    from .sandbox import _BLOCKED_NAMES

    if req.get("backend") == "gmpl":
        return run_gmpl(req, _Log(out if out is not None else io.StringIO()))
    if req.get("backend") == "minizinc":
        return run_minizinc(req, _Log(out if out is not None else io.StringIO()))

    items = _items(req["items"], ints=req.get("backend") == "cpsat")
    # The names `validate_code` refuses, removed again in case one is reached
    # by a route it did not see. A model may bind such a name for itself.
    safe_builtins = {k: v for k, v in vars(builtins).items() if k not in _BLOCKED_NAMES}
    safe_builtins["__import__"] = _import
    ns: dict[str, Any] = {"__builtins__": safe_builtins, "__name__": "__model__", **items}
    log = _Log(out if out is not None else io.StringIO())
    try:
        code = compile(req["text"], FILENAME, "exec")
        if req.get("backend") == "pulp":
            _setup_pulp(req)
        elif req.get("backend") == "pyomo":
            _setup_pyomo(req)
        elif req.get("backend") == "cpsat":
            _setup_cpsat()
        from . import _module_names, lpmodel, sandbox  # noqa: F401  (before the hook)

        sys.addaudithook(_audit)
        with contextlib.redirect_stdout(log):
            exec(code, ns)  # noqa: S102  (the runner's job; trust checked by the parent)
    except BaseException as exc:  # noqa: BLE001  (report every failure, including SystemExit)
        line = None
        if isinstance(exc, SyntaxError) and exc.filename == FILENAME:
            line = exc.lineno
        # The deepest frame in the model text. `traceback` would cost 11 ms to import.
        tb = exc.__traceback__
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == FILENAME:
                line = tb.tb_lineno
            tb = tb.tb_next
        msg = f"{type(exc).__name__}: {exc}"
        if _CPSAT is not None and isinstance(exc, TypeError) and _CP_INT_ERROR.search(msg):
            # pybind11 lists every overload; the first line names the call.
            msg = msg.splitlines()[0] + " -- CP-SAT constraints take integers only; scale the data"
        return {"ok": False, "error": msg, "line": line, "log": log.getvalue()}

    if _CPSAT is not None:
        _CP_SOLVER = _one_cp_solver(ns)
    writes: dict[str, Any] = {}
    errors: list[str] = []
    for name, original in items.items():
        now = ns.get(name)
        output = bool(req["items"][name].get("output"))
        if output and now is not original:
            try:
                writes[name] = _bound(name, original, now)
            except ValueError as exc:
                errors.append(str(exc))
            continue
        if isinstance(original, ItemDict):
            if now is not original:
                errors.append(
                    f"{name} was rebound; assign its keys, as {name}[key] = value,"
                    " or make it an output item"
                )
            elif original.writes:
                writes[name] = {"pairs": [[k, v] for k, v in original.writes.items()]}
        elif isinstance(original, list):
            if now is not original:
                errors.append(f"{name} is a set and cannot be written")
        elif now is not original:
            writes[name] = {"value": now}
    status, objective = _problem_summary(ns)
    if errors:
        return _fail("; ".join(errors), log.getvalue(), status=status)
    return {
        "ok": True,
        "writes": writes,
        "status": status,
        "objective": objective,
        "log": log.getvalue(),
    }


def main() -> None:
    req = json.load(sys.stdin)
    _limit(int(req["mem_mb"]), int(req["cpu_s"]))
    reply = run(req, sys.stdout)
    try:
        text = json.dumps(reply)
    except (TypeError, ValueError) as exc:
        text = json.dumps(
            {
                "ok": False,
                "error": f"a result is not plain data: {exc}",
                "line": None,
                "log": reply.get("log", ""),
            }
        )
    sys.stdout.write("R " + text + "\n")


if __name__ == "__main__":
    main()
