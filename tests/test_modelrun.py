"""Tests for `gridcalc.modelrun`: a sheet's model run in a child process."""

from __future__ import annotations

import sys

import pytest

from gridcalc.engine import Grid
from gridcalc.loader import save_losses
from gridcalc.modelrun import ModelError, check_model, run_model
from gridcalc.sandbox import inspect_file
from gridcalc.undo import UndoManager
from tests.test_lpmodel import BEER_MODEL


def _flow(g: Grid) -> list[list[object]]:
    return [[g.cells[2 + j][8 + i].val for j in range(5)] for i in range(2)]


def test_beer_model_end_to_end(beer: Grid) -> None:
    beer._active.model_text = BEER_MODEL + 'print("done")\n'
    undo = UndoManager()
    res = run_model(beer, undo=undo)
    assert res.status == "Optimal"
    assert res.objective == pytest.approx(8400)
    assert res.written == 11
    assert res.log == "done\n"
    assert [sum(c) for c in zip(*_flow(beer), strict=True)] == [500, 900, 1800, 200, 700]
    assert beer.cells[1][13].text == "Optimal"
    assert undo.undo(beer)
    assert beer.cells[1][13] is None or beer.cells[1][13].text == ""


def test_no_model(beer: Grid) -> None:
    with pytest.raises(ModelError, match="has no model"):
        run_model(beer)


def test_untrusted_file_refused(beer: Grid) -> None:
    beer._active.model_text = BEER_MODEL
    beer.python_trusted = False
    with pytest.raises(ModelError, match="not trusted"):
        run_model(beer)


def test_blocked_import_caught_statically(beer: Grid) -> None:
    beer._active.model_text = "import os\n"
    assert any("import of 'os' is blocked" in p for p in check_model(beer))
    with pytest.raises(ModelError, match="blocked"):
        run_model(beer)


def test_unlisted_import_refused_at_run_time(beer: Grid) -> None:
    beer._active.model_text = "x = 1\nimport colorsys\n"
    with pytest.raises(ModelError, match=r"line 2: ImportError: import of 'colorsys'") as exc:
        run_model(beer)
    assert exc.value.line == 2


def test_safe_module_imports_as_facade(beer: Grid) -> None:
    beer._active.model_text = "import math\nSolverResult = math.sqrt(16)\n"
    assert run_model(beer).written == 1
    assert beer.cells[1][13].val == 4


def test_error_reports_line_and_log(beer: Grid) -> None:
    beer._active.model_text = 'print("before")\n\ncosts["Z", 1]\n'
    with pytest.raises(ModelError, match=r"line 3: KeyError") as exc:
        run_model(beer)
    assert exc.value.log == "before\n"


def test_failed_model_writes_nothing(beer: Grid) -> None:
    beer._active.model_text = 'flow["A", 1] = 5\nraise ValueError("late")\n'
    with pytest.raises(ModelError, match="late"):
        run_model(beer)
    assert _flow(beer)[0][0] in (None, 0, "")


def test_blocked_builtin_bound_by_the_model_is_its_own(beer: Grid) -> None:
    beer._active.model_text = "vars = 3\nSolverResult = vars\n"
    assert check_model(beer) == []
    assert run_model(beer).written == 1


def test_blocked_builtin_still_unreachable(beer: Grid) -> None:
    beer._active.model_text = "SolverResult = vars()\n"
    assert any("'vars' is not allowed" in p for p in check_model(beer))
    beer._active.model_text = "x = vars(costs)\nvars = 1\n"  # read before the binding
    with pytest.raises(ModelError, match="line 1: NameError"):
        run_model(beer)


def test_rebinding_an_indexed_item_is_refused(beer: Grid) -> None:
    beer._active.model_text = "flow = {('A', 1): 5}\n"
    with pytest.raises(ModelError, match="flow was rebound"):
        run_model(beer)


def test_set_cannot_be_written(beer: Grid) -> None:
    beer._active.model_text = "Bars = [9]\n"
    with pytest.raises(ModelError, match="Bars is a set"):
        run_model(beer)


def test_non_data_result_refused(beer: Grid) -> None:
    beer._active.model_text = "from pulp import *\nSolverResult = LpVariable('x')\n"
    with pytest.raises(ModelError, match="not plain data"):
        run_model(beer)


def test_write_into_formula_refused(beer: Grid) -> None:
    beer.setcell(2, 8, "=1")
    beer._active.model_text = 'flow["A", 1] = 5\n'
    with pytest.raises(ModelError, match="holds a formula"):
        run_model(beer)


def test_hang_is_killed(beer: Grid) -> None:
    beer._active.model_text = "while True:\n    pass\n"
    with pytest.raises(ModelError, match=r"stopped after 1 s|killed by signal"):
        run_model(beer, timeout=1)


@pytest.mark.skipif(sys.platform != "darwin", reason="the parent's RSS poll is the macOS layer")
def test_memory_blowup_is_killed_by_the_parent(beer: Grid) -> None:
    # macOS ignores RLIMIT_AS, so the parent's RSS poll must stop this. The
    # model holds 300 MB and spins, so the poll sees it however fast it was
    # allocated; a model that finished between polls would race the check.
    beer._active.model_text = "x = [[i] * 125000 for i in range(300)]\nwhile True:\n    pass\n"
    with pytest.raises(ModelError, match=r"stopped past 100 MB of memory"):
        run_model(beer, mem_mb=100, timeout=20)


def _raw_child_proc(text: str, mem_mb: int, cpu_s: int):
    import json
    import subprocess

    from gridcalc.modelrun import _child_argv

    req = {"text": text, "items": {}, "mem_mb": mem_mb, "cpu_s": cpu_s}
    return subprocess.run(
        _child_argv(), input=json.dumps(req), capture_output=True, text=True, timeout=60
    )


@pytest.mark.skipif(sys.platform == "win32", reason="no RLIMIT_CPU on Windows")
def test_cpu_limit_kills_the_child_without_the_parent() -> None:
    import signal

    r = _raw_child_proc("while True:\n    pass\n", mem_mb=2048, cpu_s=1)
    assert r.returncode == -signal.SIGXCPU


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="only Linux enforces RLIMIT_AS")
def test_address_space_limit_stops_the_child_without_the_parent() -> None:
    import json

    # 1 GB in 1 MB steps against a 300 MB cap: RLIMIT_AS turns it into MemoryError.
    # A list of ints, since a model's builtins have no `bytes`.
    r = _raw_child_proc("x = []\nfor i in range(1000):\n    x.append([i] * 125000)\n", 300, 60)
    reply = json.loads(next(line for line in r.stdout.splitlines() if line.startswith("R "))[2:])
    assert not reply["ok"]
    assert reply["error"].startswith("MemoryError")


def test_model_saved_per_sheet_and_prompts_trust(beer: Grid, tmp_path) -> None:
    beer._active.model_text = BEER_MODEL
    path = str(tmp_path / "beer.json")
    assert beer.jsonsave(path) == 0
    info = inspect_file(path)
    assert info is not None and info.has_code and info.trust_needed
    assert "LpProblem" in info.code_preview
    g = Grid()
    assert g.jsonload(path) == 0
    assert g._active.model_text == BEER_MODEL
    assert g._active.model_lang == "pulp"
    assert run_model(g).status == "Optimal"


def test_untrusted_load_keeps_text_but_will_not_run(beer: Grid, tmp_path) -> None:
    from gridcalc.sandbox import LoadPolicy

    beer._active.model_text = BEER_MODEL
    path = str(tmp_path / "beer.json")
    beer.jsonsave(path)
    g = Grid()
    assert g.jsonload(path, LoadPolicy.formulas_only()) == 0
    assert g._active.model_text == BEER_MODEL
    with pytest.raises(ModelError, match="not trusted"):
        run_model(g)


def test_model_follows_sheet_rename(beer: Grid) -> None:
    beer._active.model_text = BEER_MODEL
    beer.rename_sheet(beer._active.name, "Transport")
    assert beer._active.model_text == BEER_MODEL


def test_xlsx_round_trip_keeps_models_and_items(beer: Grid, tmp_path) -> None:
    import zipfile

    from gridcalc.loader import load_workbook, save_workbook
    from gridcalc.sandbox import LoadPolicy, inspect_file

    beer.mode = __import__("gridcalc.engine", fromlist=["Mode"]).Mode.EXCEL
    beer._active.model_text = BEER_MODEL
    path = str(tmp_path / "beer.xlsx")
    assert "solver models" not in save_losses(beer, path)
    save_workbook(beer, path)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert "customXml/item1.xml" in names and "customXml/itemProps1.xml" in names
        assert b"customXml/item1.xml" in z.read("xl/_rels/workbook.xml.rels")

    info = inspect_file(path)
    assert info is not None and info.has_code and "LpProblem" in info.code_preview

    trusted = load_workbook(path, LoadPolicy.trust_all(digest=info.digest))
    assert trusted._active.model_text == BEER_MODEL
    assert trusted.data_items == beer.data_items
    assert run_model(trusted).status == "Optimal"

    untrusted = load_workbook(path)  # no prompt answered: formulas only
    assert untrusted._active.model_text == BEER_MODEL
    with pytest.raises(ModelError, match="not trusted"):
        run_model(untrusted)


def test_xlsx_changed_after_approval_does_not_load(beer: Grid, tmp_path) -> None:
    from gridcalc.loader import load_workbook, save_workbook
    from gridcalc.sandbox import LoadPolicy

    beer._active.model_text = BEER_MODEL
    path = str(tmp_path / "beer.xlsx")
    save_workbook(beer, path)
    with pytest.raises(OSError, match="changed after it was approved"):
        load_workbook(path, LoadPolicy.trust_all(digest="0" * 64))


def test_xlsx_without_models_needs_no_prompt(beer: Grid, tmp_path) -> None:
    from gridcalc.loader import needs_trust, save_workbook

    beer.data_items = {}
    path = str(tmp_path / "plain.xlsx")
    save_workbook(beer, path)
    assert needs_trust(path) is None
    beer._active.model_text = "x = 1\n"
    save_workbook(beer, path)
    assert needs_trust(path) is not None


def test_malformed_part_is_ignored(beer: Grid, tmp_path) -> None:
    import zipfile

    from gridcalc import xlsxmodel
    from gridcalc.loader import load_workbook, save_workbook

    path = tmp_path / "bad.xlsx"
    beer._active.model_text = "x = 1\n"
    save_workbook(beer, str(path))
    with zipfile.ZipFile(path) as z:
        members = [(i, z.read(i)) for i in z.infolist()]
    bad = f'<gridcalc xmlns="{xlsxmodel.NS}">{{"models": [1], "data_items": {{"a": 5}}}}</gridcalc>'
    members = [(i, bad.encode() if i.filename == "customXml/item1.xml" else d) for i, d in members]
    with zipfile.ZipFile(path, "w") as z:
        for i, d in members:
            z.writestr(i, d)
    g = load_workbook(str(path))
    assert g._active.model_text == ""
    assert g.data_items == {}
    assert any("data item a dropped" in w for w in g.load_warnings)


def test_job_steps_allow_edits_in_between(beer: Grid) -> None:
    from gridcalc.modelrun import ModelJob

    beer._active.model_text = BEER_MODEL
    job = ModelJob(beer)
    beer.setcell(10, 20, "unrelated")  # not a data item
    job.run()
    assert job.done and job.error is None
    assert job.apply(beer).status == "Optimal"


def test_job_refuses_when_data_changed(beer: Grid) -> None:
    from gridcalc.modelrun import ModelJob

    beer._active.model_text = BEER_MODEL
    job = ModelJob(beer)
    job.run()
    beer.setcell(2, 3, "99")  # costs["A", 1]
    with pytest.raises(ModelError, match="changed while the model ran"):
        job.apply(beer)
    assert _flow(beer)[0][0] in (None, 0, "")


def test_job_writes_to_its_own_sheet(beer: Grid) -> None:
    from gridcalc.modelrun import ModelJob

    beer._active.model_text = BEER_MODEL
    home = beer._active
    job = ModelJob(beer)
    job.run()
    beer.add_sheet("Other")
    beer.set_active("Other")
    job.apply(beer)
    assert beer._active.name == "Other"
    assert home._cells[(1, 13)].text == "Optimal"
    assert not beer._active._cells


def test_job_sheet_deleted(beer: Grid) -> None:
    from gridcalc.modelrun import ModelJob

    beer._active.model_text = BEER_MODEL
    job = ModelJob(beer)
    job.run()
    beer.add_sheet("Other")
    beer.remove_sheet("Sheet1")
    with pytest.raises(ModelError, match="was deleted"):
        job.apply(beer)


def test_job_cancel(beer: Grid) -> None:
    import threading
    import time

    from gridcalc.modelrun import ModelJob

    beer._active.model_text = "while True:\n    pass\n"
    job = ModelJob(beer, timeout=30)
    t = threading.Thread(target=job.run)
    t.start()
    time.sleep(0.3)
    started = time.monotonic()
    job.cancel()
    t.join(5)
    assert not t.is_alive()
    assert time.monotonic() - started < 2
    with pytest.raises(ModelError, match="cancelled"):
        job.apply(beer)


def test_job_cancel_before_run(beer: Grid) -> None:
    from gridcalc.modelrun import ModelJob

    beer._active.model_text = BEER_MODEL
    job = ModelJob(beer)
    job.cancel()
    job.run()
    assert job.error is not None and "cancelled" in str(job.error)


def test_output_streams_while_the_model_runs(beer: Grid) -> None:
    import threading
    import time

    from gridcalc.modelrun import ModelJob

    beer._active.model_text = "print('first')\nwhile True:\n    pass\n"
    job = ModelJob(beer, timeout=20)
    t = threading.Thread(target=job.run)
    t.start()
    deadline = time.monotonic() + 10
    while "first" not in job.output() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert job.output() == "first\n"  # seen before the model ends
    assert job.output(3) == "st\n"
    job.cancel()
    t.join(5)
    with pytest.raises(ModelError) as exc:
        job.apply(beer)
    assert exc.value.log == "first\n"  # kept on a cancelled run


def test_output_is_capped(beer: Grid) -> None:
    beer._active.model_text = "for i in range(200_000):\n    print('x' * 20)\n"
    res = run_model(beer)
    assert len(res.log) < (1 << 20) + 100
    assert res.log.endswith("[output truncated at 1 MB]\n")


# --- confinement: routes the AST validator would refuse, sent to the child directly ---


def _raw_child(text: str) -> dict:
    import json
    import subprocess

    from gridcalc.modelrun import _child_argv

    req = {"text": text, "items": {}, "mem_mb": 1024, "cpu_s": 20}
    out = subprocess.run(
        _child_argv(), input=json.dumps(req), capture_output=True, text=True, timeout=30
    ).stdout
    reply = [line for line in out.splitlines() if line.startswith("R ")]
    return json.loads(reply[0][2:])


# `print.__self__` is the real builtins module: the real `open` and `__import__`.
_OPEN = "print.__self__.open"
_IMPORT = "print.__self__.__import__"


def test_child_refuses_a_file_write_through_the_real_builtins(tmp_path) -> None:
    target = tmp_path / "escape.txt"
    reply = _raw_child(f"{_OPEN}({str(target)!r}, 'w')\n")
    assert not reply["ok"]
    assert "may not write files" in reply["error"]
    assert not target.exists()


def test_child_still_reads_and_imports(tmp_path) -> None:
    src = tmp_path / "in.txt"
    src.write_text("hello")
    text = f"import numpy as np\nimport statistics\nx = {_OPEN}({str(src)!r}).read()\n"
    pytest.importorskip("numpy")
    assert _raw_child(text)["ok"]


def test_child_refuses_a_process_through_the_real_import(tmp_path) -> None:
    target = tmp_path / "ran.txt"
    # repr, so a Windows path's backslashes stay a valid string literal.
    reply = _raw_child(f"{_IMPORT}('os').system({'touch ' + str(target)!r})\n")
    assert not reply["ok"]
    assert "may not use os.system" in reply["error"]
    assert not target.exists()


def test_child_refuses_a_socket_through_the_real_import() -> None:
    reply = _raw_child(f"{_IMPORT}('socket').create_connection(('127.0.0.1', 9), 2)\n")
    assert not reply["ok"]
    assert "may not use socket" in reply["error"]


def test_audit_hook_rules() -> None:
    import os

    from gridcalc import _modelchild as ch

    for event, args in [
        ("open", ("/x", "w", 0)),
        ("open", ("/x", None, os.O_WRONLY | os.O_CREAT)),
        ("subprocess.Popen", ("ls", [], None, None)),
        ("os.system", ("ls",)),
        ("socket.connect", (None, ("1.1.1.1", 80))),
        ("ctypes.dlopen", ("libc",)),
        ("os.remove", ("/x", -1)),
        ("sys.addaudithook", ()),
    ]:
        with pytest.raises(PermissionError):
            ch._audit(event, args)
    ch._audit("open", ("/x", "r", os.O_RDONLY))
    ch._audit("import", ("math", None, None, None, None))
    ch._importing += 1
    try:
        ch._audit("ctypes.dlopen", ("libc",))  # an allowed module's own import
        ch._audit("os.add_dll_directory", ("C:/numpy",))
    finally:
        ch._importing -= 1


def test_windows_popen_events_only_for_program_backends(tmp_path, monkeypatch) -> None:
    from gridcalc import _modelchild as ch

    events = [("msvcrt.get_osfhandle", (1,)), ("_winapi.CreatePipe", (None, 0))]
    for event, args in events:
        with pytest.raises(PermissionError):
            ch._audit(event, args)  # builtin backend: no process to start
    monkeypatch.setattr(ch, "_tmp", str(tmp_path))
    for event, args in events:
        ch._audit(event, args)
    with pytest.raises(PermissionError):
        ch._audit("_winapi.CreateProcess", (None, "cmd /c del x", None))


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS only")
@pytest.mark.parametrize(
    "code",
    [
        "import socket; socket.create_connection(('127.0.0.1', 9), 2)",
        "open({path!r}, 'w')",
        "import os; os.fork()",
    ],
)
def test_macos_profile_denies_without_the_audit_hook(code, tmp_path) -> None:
    import subprocess

    from gridcalc.modelrun import _SANDBOX_EXEC, _SANDBOX_PROFILE

    path = str(tmp_path / "w.txt")
    r = subprocess.run(
        [
            _SANDBOX_EXEC,
            "-p",
            _SANDBOX_PROFILE,
            sys.executable,
            "-I",
            "-B",
            "-c",
            code.format(path=path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode != 0
    assert "not permitted" in r.stderr or "Permission" in r.stderr or "denied" in r.stderr.lower()
    assert not (tmp_path / "w.txt").exists()


def test_child_does_not_import_the_engine_or_metadata() -> None:
    # Most of a model run's start-up was these imports (docs/dev/crosstab-model.md).
    import json
    import subprocess

    code = (
        "import sys, gridcalc._modelchild as c\n"
        "c.run({'text': 'x = 1\\n', 'items': {}})\n"
        "print(json.dumps([m for m in ('gridcalc.engine', 'importlib.metadata', 'traceback')"
        " if m in sys.modules]))"
    )
    out = subprocess.run(
        [sys.executable, "-I", "-c", "import json\n" + code],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert json.loads(out.splitlines()[-1]) == []


def test_quadratic_model_from_a_sheet() -> None:
    """Least squares through the builtin backend: fit y = a*x + b to five points."""
    from gridcalc.dataitems import DataItem
    from gridcalc.engine import NamedRange

    g = Grid()
    xs, ys = [1, 2, 3, 4, 5], [2.1, 3.9, 6.2, 7.8, 10.1]
    g.setcells_bulk(
        [(0, r, str(v)) for r, v in enumerate(xs)] + [(1, r, str(v)) for r, v in enumerate(ys)]
    )
    g.setcells_bulk([(3, 0, "1"), (3, 1, "2"), (3, 2, "3"), (3, 3, "4"), (3, 4, "5")])
    sheet = g._active.name
    for name, c1, r1, c2, r2 in [
        ("P", 3, 0, 3, 4),
        ("X", 0, 0, 0, 4),
        ("Y", 1, 0, 1, 4),
        ("slope", 5, 0, 5, 0),
        ("intercept", 5, 1, 5, 1),
    ]:
        g.names.append(NamedRange(name, c1, r1, c2, r2, sheet=sheet))
    g.data_items = {
        "P": DataItem(),
        "X": DataItem(("P",)),
        "Y": DataItem(("P",)),
        "slope": DataItem(output=True),
        "intercept": DataItem(output=True),
    }
    g._active.model_text = (
        "from pulp import *\n"
        "a, b = LpVariable('a'), LpVariable('b')\n"
        "prob = LpProblem('fit', LpMinimize)\n"
        "prob += lpSum((Y[p] - a * X[p] - b) ** 2 for p in P)\n"
        "prob.solve()\n"
        "slope, intercept = a, b\n"
    )
    res = run_model(g)
    assert res.status == "Optimal" and res.written == 2
    assert g.cells[5][0].val == pytest.approx(1.99, abs=1e-4)  # numpy.polyfit gives 1.99, 0.05
    assert g.cells[5][1].val == pytest.approx(0.05, abs=1e-4)


def test_popen_with_a_windows_command_line(tmp_path, monkeypatch) -> None:
    import os

    from gridcalc import _modelchild as ch

    prog = tmp_path / "solver dir" / "cbc.exe"
    prog.parent.mkdir()
    prog.write_text("")
    real = os.path.normcase(os.path.realpath(prog))
    monkeypatch.setattr(ch, "_programs", frozenset({real}))
    # As Windows raises it: no executable, argv joined by list2cmdline.
    for event in ("subprocess.Popen", "_winapi.CreateProcess"):
        ch._audit(event, (None, f'"{prog}" model.mps', None, None))
        for cmdline in (f'"{prog}x" model.mps', "cmd /c del x", "", "   "):
            with pytest.raises(PermissionError):
                ch._audit(event, (None, cmdline, None, None))
