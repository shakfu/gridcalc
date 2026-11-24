"""Run a sheet's solver model in a child process and write its results back.

The model is the active sheet's ``model_text``. It reads data items
(:mod:`gridcalc.dataitems`) and calls the PuLP subset
(:mod:`gridcalc.lpmodel`). The child gets the items as JSON and returns the
writes; a hang or a memory blowup kills the child, not the workbook. Design
and measurements: ``docs/dev/crosstab-model.md``.
"""

from __future__ import annotations

import ast
import contextlib
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, cast

from . import dataitems
from .dataitems import DataItemError, ItemDict
from .engine import Grid, Sheet
from .sandbox import _BLOCKED_NAMES, validate_code

LANGS = ("pulp",)
# "builtin": the PuLP subset on the HiGHS extension, in the child alone.
# "pulp": the PuLP library (`gridcalc[pulp]`), which writes temp files and
# starts a solver program, so its child gets those two exceptions.
BACKENDS = ("builtin", "pulp")
# Solver programs PuLP may start from PATH, besides its own bundled CBC.
SOLVER_PROGRAMS = ("cbc", "glpsol", "highs", "scip", "cplex", "gurobi_cl")
TIMEOUT_S = 120.0
MEM_MB = 2048
_POLL_S = 0.2


class ModelError(Exception):
    """A model that cannot run, or that failed. ``line`` is 1-based in the model text."""

    def __init__(self, message: str, line: int | None = None, log: str = "") -> None:
        super().__init__(f"line {line}: {message}" if line else message)
        self.line = line
        self.log = log

    def lines(self) -> list[str]:
        """The message, then the model's output, for a pager or panel."""
        out = str(self).splitlines()
        if self.log:
            out += ["", "model output:", *self.log.splitlines()]
        return out


@dataclass
class ModelResult:
    status: str | None  # LpStatus text of the one solved problem, if there is exactly one
    objective: float | None
    written: int  # cells written back
    log: str  # the model's print output

    def summary(self) -> str:
        parts = [self.status or "model ran"]
        if self.objective is not None:
            parts.append(f"objective {self.objective:g}")
        parts.append(f"{self.written} cells written")
        return ", ".join(parts)


def _text_problems(sh: Sheet) -> list[str]:
    if not sh.model_text.strip():
        return []
    problems: list[str] = []
    if sh.model_lang not in LANGS:
        problems.append(f"model language {sh.model_lang!r} is not one of {', '.join(LANGS)}")
    if sh.model_backend not in BACKENDS:
        problems.append(f"model backend {sh.model_backend!r} is not one of {', '.join(BACKENDS)}")
    elif sh.model_backend == "pulp" and _pulp_dir() is None:
        problems.append("the pulp backend needs PuLP: pip install 'gridcalc[pulp]'")
    ok, why = validate_code(_rename_own_names(sh.model_text))
    if not ok:
        problems.append(f"model on {sh.name}: {why}")
    return problems


def check_model(g: Grid) -> list[str]:
    """Static problems with the active sheet's model and the data items. Runs no model code."""
    return _text_problems(g._active) + dataitems.validate(g)


def check_workbook(g: Grid) -> list[str]:
    """`check_model` over every sheet's model; empty when the workbook has neither."""
    problems = [p for sh in g.sheets for p in _text_problems(sh)]
    return problems + dataitems.validate(g) if g.data_items else problems


def _rename_own_names(text: str) -> str:
    """``text`` with each blocked builtin the model assigns itself renamed.

    PuLP's examples name a variable dict ``vars``. Once the model binds the
    name it is the model's own; the child has no ``vars`` builtin to reach
    before that, so a read ahead of the binding is a NameError there.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    bound = {
        n.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id in _BLOCKED_NAMES
    }
    bound.discard("__builtins__")
    bound = {b for b in bound if not b.startswith("__")}
    if not bound:
        return text
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in bound:
            n.id = "_own_" + n.id
    return ast.unparse(tree)


def _request_items(items: dict[str, Any], g: Grid) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, v in items.items():
        output = g.data_items[name].output
        if isinstance(v, ItemDict):
            missing = g.data_items[name].missing
            out[name] = {
                "kind": "indexed",
                "keys": sorted(v.index_keys, key=repr),
                "values": [[k, x] for k, x in v.items()],
                "missing": [] if missing is dataitems._RAISE else [missing],
                "output": output,
            }
        else:
            out[name] = {"kind": "plain", "value": v, "output": output}
    return out


# macOS only: the OS refuses the child network access, file writes and forks,
# whatever route Python code finds. Linux has no unprivileged equivalent that
# needs no extra library; there the child's audit hook is the last layer.
_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_SANDBOX_PROFILE = """(version 1)
(allow default)
(deny network*)
(deny process-fork)
(deny file-write* (require-not (literal "/dev/null")))
"""


def _pulp_dir() -> str | None:
    """The installed PuLP package's directory, found without importing it."""
    import importlib.util

    try:
        spec = importlib.util.find_spec("pulp")
    except (ImportError, ValueError):
        return None
    locs = list(spec.submodule_search_locations or []) if spec else []
    return os.path.realpath(locs[0]) if locs else None


def solver_programs() -> tuple[list[str], list[str]]:
    """Programs the pulp backend may start: (paths, directories), resolved."""
    files = {os.path.realpath(p) for name in SOLVER_PROGRAMS if (p := shutil.which(name))}
    pulp = _pulp_dir()
    dirs = [os.path.join(pulp, "solverdir")] if pulp else []
    return sorted(files), dirs


def _pulp_profile(n_files: int, n_dirs: int) -> str:
    """The pulp backend's profile: also writes in TMP and runs listed programs.

    Paths arrive as `-D` parameters, so no path text is ever profile syntax.
    """
    allowed = ['(literal (param "PY"))', '(literal (param "PYREAL"))']
    allowed += [f'(literal (param "F{i}"))' for i in range(n_files)]
    allowed += [f'(subpath (param "D{i}"))' for i in range(n_dirs)]
    return (
        "(version 1)\n(allow default)\n(deny network*)\n"
        '(deny file-write* (require-not (require-any (literal "/dev/null")'
        ' (subpath (param "TMP")))))\n'
        f"(deny process-exec (require-not (require-any {' '.join(allowed)})))\n"
    )


def _child_argv(backend: str = "builtin", tmp: str | None = None) -> list[str]:
    # -B: no .pyc writes, which the sandbox would refuse anyway.
    argv = [sys.executable, "-I", "-B", "-m", "gridcalc._modelchild"]
    if sys.platform != "darwin" or not os.path.exists(_SANDBOX_EXEC):
        return argv
    if backend != "pulp" or tmp is None:
        return [_SANDBOX_EXEC, "-p", _SANDBOX_PROFILE, *argv]
    files, dirs = solver_programs()
    params = ["-D", f"TMP={os.path.realpath(tmp)}", "-D", f"PY={sys.executable}"]
    params += ["-D", f"PYREAL={os.path.realpath(sys.executable)}"]
    params += [x for i, f in enumerate(files) for x in ("-D", f"F{i}={f}")]
    params += [x for i, d in enumerate(dirs) for x in ("-D", f"D{i}={d}")]
    return [_SANDBOX_EXEC, *params, "-p", _pulp_profile(len(files), len(dirs)), *argv]


def _rss_mb(pgid: int) -> int:
    """Resident memory of process group ``pgid`` in MB, or 0 where ``ps`` is unavailable.

    The group, so a solver the model started counts against the cap too.
    """
    ps = shutil.which("ps")
    if ps is None:
        return 0
    out = subprocess.run(  # noqa: S603
        [ps, "-A", "-o", "pgid=,rss="], capture_output=True, text=True, check=False
    ).stdout
    kb = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] == str(pgid) and parts[1].isdigit():
            kb += int(parts[1])
    return kb // 1024


def _kill(proc: subprocess.Popen[str]) -> None:
    """Kill the child and anything it started (its process group, where there is one)."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, 9)
        else:
            proc.kill()


class ModelJob:
    """One model run in three steps, so a frontend can keep working during the middle one.

    ``__init__`` reads the grid, ``run`` talks only to the child (call it from
    a worker thread), and ``apply`` writes. ``apply`` refuses if a data item
    changed in between: the solution would answer a different question.
    """

    def __init__(self, g: Grid, *, timeout: float = TIMEOUT_S, mem_mb: int = MEM_MB) -> None:
        sh = g._active
        if not sh.model_text.strip():
            raise ModelError(f"sheet {sh.name} has no model")
        if not g.python_trusted:
            raise ModelError(
                "this file's code was not trusted when it was opened, so its model will not run"
            )
        problems = check_model(g)
        if problems:
            raise ModelError("\n".join(problems))
        self.sheet = sh
        self.timeout = timeout
        self.mem_mb = mem_mb
        self.started = time.monotonic()
        self._items = self._read(g)
        self.backend = sh.model_backend
        self._request = {
            "text": sh.model_text,
            "items": self._items,
            "mem_mb": mem_mb,
            "cpu_s": max(1, math.ceil(timeout)),
            "backend": self.backend,
        }
        self._proc: subprocess.Popen[str] | None = None
        self._out: list[str] = []
        self._out_lock = threading.Lock()
        self._reply_line = ""
        self._cancelled = False
        self.reply: dict[str, Any] | None = None
        self.error: ModelError | None = None

    def _read(self, g: Grid) -> dict[str, Any]:
        try:
            return _request_items(dataitems.read_items(g), g)
        except DataItemError as exc:
            raise ModelError(str(exc)) from exc

    @property
    def done(self) -> bool:
        return self.reply is not None or self.error is not None

    def run(self) -> None:
        """Run the child to completion. Never raises; the outcome is in ``reply`` or ``error``."""
        try:
            self.reply = self._run_child()
        except ModelError as exc:
            self.error = exc

    def cancel(self) -> None:
        """Stop the child; ``run`` then ends with a "cancelled" error."""
        self._cancelled = True
        if self._proc is not None:
            _kill(self._proc)

    def output(self, start: int = 0) -> str:
        """The model's output so far, from character ``start``. Safe from any thread."""
        with self._out_lock:
            return "".join(self._out)[start:]

    def _collect(self, stream: Any) -> None:
        """Collect ``O`` output lines live and keep the ``R`` reply line."""
        for line in stream:
            if line.startswith("O "):
                with contextlib.suppress(ValueError):
                    chunk = json.loads(line[2:])
                    if isinstance(chunk, str):
                        with self._out_lock:
                            self._out.append(chunk)
            elif line.startswith("R "):
                self._reply_line = line[2:]

    def _run_child(self) -> dict[str, Any]:
        """Send the request to a child and return its reply; kill it past the limits.

        The child sets RLIMIT_AS itself, but macOS does not enforce it, so the
        parent also polls the child's resident memory.
        """
        if self._cancelled:
            raise ModelError("model cancelled")
        if self.backend != "pulp":
            return self._spawn(None)
        import tempfile

        tmp = tempfile.mkdtemp(prefix="gridcalc-model-")
        try:
            return self._spawn(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _spawn(self, tmp: str | None) -> dict[str, Any]:
        env = None
        if tmp is not None:
            files, dirs = solver_programs()
            self._request.update(tmp=os.path.realpath(tmp), programs=files, program_dirs=dirs)
            # PuLP writes its model and solution files in `tempfile.gettempdir()`.
            env = {**os.environ, "TMPDIR": tmp, "TEMP": tmp, "TMP": tmp}
        proc = subprocess.Popen(  # noqa: S603
            _child_argv(self.backend, tmp),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            # Its own process group, so the memory cap and a kill cover a solver it starts.
            start_new_session=hasattr(os, "killpg"),
        )
        self._proc = proc
        if self._cancelled:  # cancel() ran before _proc was set
            _kill(proc)
        # Popen with PIPE sets all three; the casts only tell the type checker.
        stdin = cast(Any, proc.stdin)
        stdout = cast(Any, proc.stdout)
        stderr = cast(Any, proc.stderr)
        err: list[str] = []

        def feed() -> None:
            with contextlib.suppress(OSError):  # BrokenPipe if the child died early
                stdin.write(json.dumps(self._request))
                stdin.close()

        threads = [
            threading.Thread(target=feed, daemon=True),
            threading.Thread(target=self._collect, args=(stdout,), daemon=True),
            threading.Thread(target=lambda: err.append(stderr.read()), daemon=True),
        ]
        for t in threads:
            t.start()
        deadline = self.started + self.timeout
        killed = ""
        while proc.poll() is None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(_POLL_S)
            if proc.poll() is not None:
                break
            if time.monotonic() > deadline:
                killed = f"stopped after {self.timeout:g} s"
            elif _rss_mb(proc.pid) > self.mem_mb:
                killed = f"stopped past {self.mem_mb} MB of memory"
            if killed:
                _kill(proc)
                proc.wait()
        _kill(proc)  # a solver the model left running
        for t in threads[1:]:
            t.join(5)
        log = self.output()
        if self._cancelled:
            raise ModelError("model cancelled", log=log)
        if killed:
            raise ModelError(f"model {killed}", log=log)
        try:
            reply = json.loads(self._reply_line)
        except ValueError:
            tail = "".join(err).strip().splitlines()[-1:] or [f"exit code {proc.returncode}"]
            if proc.returncode is not None and proc.returncode < 0:
                tail = [f"killed by signal {-proc.returncode} (CPU or memory limit)"]
            raise ModelError(f"model process failed: {tail[0]}", log=log) from None
        if not isinstance(reply, dict):
            raise ModelError("model process sent a malformed reply", log=log)
        return reply

    def apply(self, g: Grid, undo: Any = None) -> ModelResult:
        """Write the finished run's results as one undo step, or raise :class:`ModelError`."""
        if self.error is not None:
            raise self.error
        reply = self.reply
        if reply is None:
            raise ModelError("model has not finished")
        log = str(reply.get("log", ""))
        if not reply.get("ok"):
            line = reply.get("line")
            raise ModelError(str(reply.get("error")), line if isinstance(line, int) else None, log)
        if self.sheet not in g.sheets:
            raise ModelError(f"sheet {self.sheet.name} was deleted while the model ran", log=log)
        active = g.active
        g.active = g.sheets.index(self.sheet)
        try:
            return self._write(g, reply, log, undo)
        finally:
            if active < len(g.sheets):
                g.active = active

    def _write(self, g: Grid, reply: dict[str, Any], log: str, undo: Any) -> ModelResult:
        try:
            same = self._read(g) == self._items
        except ModelError:
            same = False
        if not same:
            raise ModelError(
                "data items changed while the model ran; nothing written, solve again", log=log
            )
        writes: dict[str, Any] = {}
        for name, w in reply.get("writes", {}).items():
            if "pairs" in w:
                writes[name] = {(tuple(k) if isinstance(k, list) else k): v for k, v in w["pairs"]}
            else:
                writes[name] = w.get("value")
        try:
            written = dataitems.apply_writes(g, writes, undo)
        except DataItemError as exc:
            raise ModelError(str(exc), log=log) from exc
        objective = reply.get("objective")
        return ModelResult(
            status=reply.get("status"),
            objective=float(objective) if isinstance(objective, (int, float)) else None,
            written=written,
            log=log,
        )


def run_model(
    g: Grid, *, undo: Any = None, timeout: float = TIMEOUT_S, mem_mb: int = MEM_MB
) -> ModelResult:
    """Run the active sheet's model to completion and write its results as one undo step.

    Raises :class:`ModelError` before anything is written if the model is
    untrusted, invalid, fails, or writes a value its data item cannot take.
    """
    job = ModelJob(g, timeout=timeout, mem_mb=mem_mb)
    job.run()
    return job.apply(g, undo)
