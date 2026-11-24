"""Child process for :mod:`gridcalc.modelrun`: run one model, report its writes.

Reads one JSON request on stdin and writes one JSON reply on stdout. The
model's own ``print`` output goes to the reply's ``log``. See
``docs/dev/crosstab-model.md`` for the protocol.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
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
    for which, value in ((resource.RLIMIT_AS, mem_mb << 20), (resource.RLIMIT_CPU, cpu_s)):
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(which, (value, value))


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
# and sets environment variables. Allowed only while `_import` runs.
_IMPORT_ONLY = frozenset({"ctypes.dlopen", "ctypes.dlsym", "os.putenv", "os.unsetenv"})
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_importing = 0

# The pulp backend's exceptions, set by `run`: PuLP writes its model and
# solution files in `_tmp`, and starts one of `_programs` (or a program under
# `_program_dirs`, PuLP's bundled solvers) to solve.
_tmp: str | None = None
_programs: frozenset[str] = frozenset()
_program_dirs: tuple[str, ...] = ()
_PULP: Any = None


def _inside(path: Any, root: str | None) -> bool:
    if root is None or not isinstance(path, (str, bytes, os.PathLike)):
        return False
    real = os.path.realpath(os.fsdecode(path))
    return real == root or real.startswith(root + os.sep)


def _allowed_program(args: tuple[Any, ...]) -> bool:
    exe = args[0] if args else None
    argv = args[1] if len(args) > 1 else None
    if exe is None and isinstance(argv, (list, tuple)) and argv:
        exe = argv[0]
    if not isinstance(exe, (str, bytes, os.PathLike)):
        return False
    real = os.path.realpath(os.fsdecode(exe))
    return real in _programs or any(_inside(real, d) for d in _program_dirs)


def _audit(event: str, args: tuple[Any, ...]) -> None:
    """Refuse writes, processes, sockets and native calls once the model runs."""
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
        return
    if _importing and event in _IMPORT_ONLY:
        return
    if event.startswith(_DENIED):
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


def _items(spec: dict[str, Any]) -> dict[str, Any]:
    from .itemdict import _RAISE, ItemDict

    out: dict[str, Any] = {}
    for name, it in spec.items():
        if it["kind"] == "indexed":
            keys = [_key(k) for k in it["keys"]]
            values = {_key(k): v for k, v in it["values"]}
            missing = it["missing"][0] if it["missing"] else _RAISE
            out[name] = ItemDict(name, keys, values, missing)
        else:
            out[name] = it["value"]
    return out


def _value(name: str, key: Any, x: Any) -> Any:
    """A bound entry's value: a variable's or expression's after the solve, or a number."""
    from . import lpmodel

    lib = _PULP if _PULP is not None else lpmodel
    v = lib.value(x)
    if v is None:
        where = f"{name}[{key!r}]" if key is not None else name
        raise ValueError(f"{where} has no value; the solve did not find one")
    return v


def _lookup(d: Any, key: Any) -> Any:
    """``d[key]``, or ``d[k0][k1]`` for the nested dicts `LpVariable.dicts` makes."""
    if isinstance(d, dict) and key in d:
        return d[key]
    if isinstance(key, tuple) and isinstance(d, dict) and key and key[0] in d:
        return _lookup(d[key[0]], key[1:] if len(key) > 2 else key[1])
    raise KeyError(key)


def _bound(name: str, original: Any, now: Any) -> dict[str, Any]:
    """The writes for an output item the model rebound to its variables."""
    from .itemdict import ItemDict

    if not isinstance(original, ItemDict):
        return {"value": _value(name, None, now)}
    if not isinstance(now, dict):
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


def _problem_summary(ns: dict[str, Any]) -> tuple[str | None, float | None]:
    """Status and objective of the one solved LpProblem in ``ns``, if exactly one."""
    from . import lpmodel

    lib = _PULP if _PULP is not None else lpmodel
    LpProblem, LpStatus, value = lib.LpProblem, lib.LpStatus, lib.value  # noqa: N806
    LpStatusNotSolved = lib.LpStatusNotSolved  # noqa: N806

    solved = [v for v in ns.values() if isinstance(v, LpProblem) and v.status != LpStatusNotSolved]
    if len(solved) != 1:
        return None, None
    p = solved[0]
    obj = value(p.objective) if p.objective is not None else None
    return LpStatus[p.status], obj


def _setup_pulp(req: dict[str, Any]) -> None:
    """Import the PuLP library and record what it may write and run. Before the hook."""
    global _PULP, _tmp, _programs, _program_dirs
    import pulp  # type: ignore[import-untyped]

    major = int(str(getattr(pulp, "__version__", "0")).split(".")[0] or 0)
    if major >= 4:
        raise ImportError(
            f"PuLP {pulp.__version__} is a different API; the pulp backend needs PuLP 2 or 3"
        )
    _PULP = pulp
    _tmp = os.path.realpath(req["tmp"])
    _programs = frozenset(os.path.realpath(p) for p in req.get("programs", []))
    _program_dirs = tuple(os.path.realpath(d) for d in req.get("program_dirs", []))


def run(req: dict[str, Any], out: Any = None) -> dict[str, Any]:
    from .itemdict import ItemDict
    from .sandbox import _BLOCKED_NAMES

    items = _items(req["items"])
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
        return {"ok": False, "error": msg, "line": line, "log": log.getvalue()}

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
        return {"ok": False, "error": "; ".join(errors), "line": None, "log": log.getvalue()}
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
