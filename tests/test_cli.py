"""Tests for headless mode (`gridcalc FILE --solve ...`, `gridcalc.cli`).

The CLI's whole purpose is being driven by something that is not a person, so
these lean on the two things a script actually depends on: the JSON schema and
the exit code. The example workbooks carry their own expected answers in cell
text ("Expected: A4=2, A5=6, B4=36"), which makes them the right fixtures --
if the engine and the documented answer ever disagree, that is worth failing
over here too.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from gridcalc import cli
from gridcalc.engine import Grid, Mode
from gridcalc.loader import load_workbook
from gridcalc.tui import cli_parser

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
LP = str(EXAMPLES / "example_lp.json")
GOAL = str(EXAMPLES / "example_goal.json")
EXCEL = str(EXAMPLES / "example_excel.json")


def _run(*argv: str) -> tuple[int, dict, str]:
    """Parse ``argv`` the way the console script does and run it.

    Goes through the real parser rather than building a Namespace by hand, so
    a flag that is renamed or dropped fails these tests instead of silently
    becoming untested.
    """
    args = cli_parser().parse_args(list(argv))
    out, err = io.StringIO(), io.StringIO()
    code = cli.run(args, out=out, err=err)
    text = out.getvalue()
    payload = json.loads(text) if text.strip() and args.format == "json" else {}
    return code, payload, err.getvalue()


# --- dispatch ---------------------------------------------------------------


def test_a_bare_file_argument_is_not_headless() -> None:
    """The editor must still open when no operation is asked for."""
    assert not cli.is_headless(cli_parser().parse_args([LP]))


@pytest.mark.parametrize(
    "argv",
    [
        [LP, "--solve"],
        [LP, "--eval", "=1+1"],
        [LP, "--sweep", "D5 6:12"],
        [GOAL, "--goal", "B1 = 11 by A1"],
        [LP, "--convert", "out.json"],
    ],
)
def test_any_operation_flag_makes_the_run_headless(argv) -> None:
    assert cli.is_headless(cli_parser().parse_args(argv))


# --- solve ------------------------------------------------------------------


def test_solve_runs_the_workbooks_saved_default_model() -> None:
    code, out, _ = _run(LP, "--solve")
    d = out["solve"]
    # The values the workbook itself advertises in A1.
    assert d["status"] == "OPTIMAL"
    assert d["optimal"] is True
    assert d["objective"] == pytest.approx(36.0)
    assert d["values"] == {"A4": pytest.approx(2.0), "A5": pytest.approx(6.0)}
    assert code == cli.EXIT_OK


def test_solve_accepts_an_inline_spec_in_the_opt_grammar() -> None:
    code, out, _ = _run(LP, "--solve", "max B4 vars A4:A5 st D4:D6")
    assert out["solve"]["objective"] == pytest.approx(36.0)
    assert code == cli.EXIT_OK


def test_solve_accepts_a_saved_model_by_name() -> None:
    _, out, _ = _run(LP, "--solve", "with_caps")
    # `with_caps` bounds A4 to 3, so it cannot reach the unbounded-case 36.
    assert out["solve"]["objective"] == pytest.approx(33.0)
    assert out["solve"]["model"]["bounds"] == "A4=0:3,A5=0:5"


def test_solve_does_not_touch_the_grid_without_apply(tmp_path) -> None:
    """The safe default: asking a question must not rewrite the workbook."""
    dest = tmp_path / "out.json"
    code, out, _ = _run(LP, "--solve", "--convert", str(dest))
    assert out["solve"]["applied"] is False
    g = load_workbook(dest)
    assert g.cell(0, 3).val == 0.0  # A4 still the file's original 0
    assert code == cli.EXIT_OK


def test_apply_plus_convert_writes_the_solution_to_disk(tmp_path) -> None:
    dest = tmp_path / "solved.json"
    _, out, _ = _run(LP, "--solve", "--apply", "--convert", str(dest))
    assert out["solve"]["applied"] is True
    g = load_workbook(dest)
    assert g.cell(0, 3).val == pytest.approx(2.0)  # A4
    assert g.cell(0, 4).val == pytest.approx(6.0)  # A5


def test_sensitivity_is_absent_unless_requested() -> None:
    _, plain, _ = _run(LP, "--solve")
    assert "sensitivity" not in plain["solve"]
    _, sens, _ = _run(LP, "--solve", "--sens")
    s = sens["solve"]["sensitivity"]
    assert {v["cell"] for v in s["variables"]} == {"A4", "A5"}
    assert {c["cell"] for c in s["constraints"]} == {"D4", "D5", "D6"}
    assert any(c["binding"] for c in s["constraints"])


# --- failure is a result, not an error --------------------------------------


def _write(tmp_path: Path, name: str, cells: list[tuple[int, int, str]]) -> str:
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    for c, r, text in cells:
        g.setcell(c, r, text)
    path = tmp_path / name
    g.jsonsave(str(path))
    return str(path)


def test_an_infeasible_model_exits_2_and_names_the_conflict(tmp_path) -> None:
    path = _write(
        tmp_path,
        "infeasible.json",
        [(0, 0, "0"), (1, 0, "=A1"), (3, 0, "=A1>=10"), (3, 1, "=A1<=5")],
    )
    code, out, err = _run(path, "--solve", "max B1 vars A1 st D1:D2", "--diagnose")
    assert out["solve"]["status"] == "INFEASIBLE"
    assert out["solve"]["optimal"] is False
    assert set(out["solve"]["conflict"]) == {"D1", "D2"}
    # Exit 2, not 1: the run worked and the answer is "no such plan exists",
    # which a caller should act on rather than treat as a broken job.
    assert code == cli.EXIT_FAILED
    assert err == ""


def test_an_unbounded_model_exits_2_and_names_the_variable(tmp_path) -> None:
    path = _write(tmp_path, "unbounded.json", [(0, 0, "0"), (1, 0, "=A1"), (3, 0, "=A1>=1")])
    code, out, _ = _run(path, "--solve", "max B1 vars A1 st D1", "--diagnose")
    assert out["solve"]["status"] == "UNBOUNDED"
    assert out["solve"]["unbounded"] == ["A1"]
    assert code == cli.EXIT_FAILED


@pytest.mark.parametrize(
    "argv, fragment",
    [
        (["/no/such/file.json", "--solve"], "could not load"),
        ([LP, "--solve", "nosuchmodel"], "no model named"),
        ([LP, "--solve", "max B4 vars A4:A5"], "usage:"),
        ([GOAL, "--goal", "nonsense"], "usage:"),
        ([LP, "--sweep", "D5"], "usage:"),
        ([LP, "--sheet", "NoSuchSheet", "--solve"], "no such sheet"),
    ],
)
def test_a_run_that_never_started_exits_1_with_stderr_and_no_stdout(argv, fragment) -> None:
    args = cli_parser().parse_args(argv)
    out, err = io.StringIO(), io.StringIO()
    assert cli.run(args, out=out, err=err) == cli.EXIT_ERROR
    assert fragment in err.getvalue()
    # Nothing on stdout: a caller parsing JSON must not get half an object.
    assert out.getvalue() == ""


# --- goal seek --------------------------------------------------------------


def test_goal_reaches_the_value_the_example_advertises() -> None:
    code, out, _ = _run(GOAL, "--goal", "B1 = 11 by A1")
    d = out["goal"]
    assert d["converged"] is True
    assert d["var_value"] == pytest.approx(4.0)  # the file says "A1 becomes 4"
    assert d["formula_value"] == pytest.approx(11.0)
    assert d["formula_cell"] == "B1"
    assert d["var_cell"] == "A1"
    assert code == cli.EXIT_OK


def test_goal_accepts_an_explicit_bracket() -> None:
    _, out, _ = _run(GOAL, "--goal", "B1 = 100 by A1 in 0:1000")
    assert out["goal"]["var_value"] == pytest.approx(48.5)


# --- eval -------------------------------------------------------------------


def test_eval_reports_each_formula_in_order() -> None:
    _, out, _ = _run(EXCEL, "--eval", "=1+2*3", "--eval", "=SUM(B4:B7)")
    entries = out["eval"]
    assert [e["formula"] for e in entries] == ["=1+2*3", "=SUM(B4:B7)"]
    assert entries[0]["value"] == pytest.approx(7.0)
    assert entries[1]["value"] == pytest.approx(70600.0)


def test_eval_accepts_a_formula_without_the_leading_equals() -> None:
    _, out, _ = _run(EXCEL, "--eval", "1+1")
    assert out["eval"][0]["value"] == pytest.approx(2.0)


def test_eval_reports_an_error_rather_than_a_value() -> None:
    _, out, _ = _run(EXCEL, "--eval", "=NOSUCHFUNC()")
    entry = out["eval"][0]
    assert entry["value"] is None
    assert entry["error"]


def test_eval_leaves_the_workbook_byte_for_byte_unchanged(tmp_path) -> None:
    """`--eval` borrows a real cell to evaluate in, and must give it back.

    The scratch cell is what makes a relative reference mean the same thing it
    would if typed into the sheet; the cost is that the sheet is mutated
    mid-run, so the restore is load-bearing rather than tidiness.
    """
    baseline = tmp_path / "baseline.json"
    after = tmp_path / "after.json"
    _run(EXCEL, "--convert", str(baseline))
    _run(EXCEL, "--eval", "=SUM(B4:B7)", "--eval", "=A1", "--convert", str(after))
    assert after.read_text(encoding="utf-8") == baseline.read_text(encoding="utf-8")


# --- sweep ------------------------------------------------------------------


def test_sweep_reports_a_point_per_step_and_flags_breakpoints() -> None:
    _, out, _ = _run(LP, "--sweep", "D5 6:24 6")
    d = out["sweep"]
    assert d["constraint"] == "D5"
    assert len(d["points"]) == 7  # steps + 1, inclusive of both ends
    assert [p["rhs"] for p in d["points"]] == [6, 9, 12, 15, 18, 21, 24]
    # The marginal value of the resource does change somewhere in this range;
    # that is the entire reason to sweep rather than read one shadow price.
    assert d["breakpoints"]
    assert all(p["status"] == "OPTIMAL" for p in d["points"])


def test_sweep_never_writes_to_the_sheet(tmp_path) -> None:
    dest = tmp_path / "swept.json"
    _run(LP, "--sweep", "D5 6:24 6", "--convert", str(dest))
    assert load_workbook(dest).cell(0, 3).val == 0.0


# --- convert ----------------------------------------------------------------


@pytest.mark.parametrize("name, fmt", [("o.json", "json"), ("o.csv", "csv"), ("o.xlsx", "xlsx")])
def test_convert_picks_the_format_from_the_extension(tmp_path, name, fmt) -> None:
    dest = tmp_path / name
    _, out, _ = _run(EXCEL, "--convert", str(dest))
    assert out["convert"]["format"] == fmt
    assert dest.exists() and dest.stat().st_size > 0


def test_convert_round_trips_a_workbook_through_xlsx(tmp_path) -> None:
    dest = tmp_path / "book.xlsx"
    _run(EXCEL, "--convert", str(dest))
    g = load_workbook(dest)
    assert g.cell(1, 3).val == pytest.approx(load_workbook(EXCEL).cell(1, 3).val)


# --- output contract --------------------------------------------------------


def test_json_is_the_default_and_is_strictly_conforming() -> None:
    """No `Infinity`/`NaN` tokens, which `json.loads` accepts but other
    languages' parsers reject. `--sens` is the case that produces infinite
    ranging limits, and they have to come out as null."""
    args = cli_parser().parse_args([LP, "--solve", "--sens"])
    out = io.StringIO()
    cli.run(args, out=out, err=io.StringIO())
    text = out.getvalue()
    assert "Infinity" not in text and "NaN" not in text
    json.loads(text)
    sens = json.loads(text)["solve"]["sensitivity"]
    assert any(v["obj_till"] is None for v in sens["variables"])


def test_several_operations_share_one_result_object() -> None:
    _, out, _ = _run(LP, "--eval", "=1+1", "--solve", "--sweep", "D5 6:12 2")
    assert set(out) == {"eval", "solve", "sweep"}


def test_text_format_renders_without_json() -> None:
    args = cli_parser().parse_args([LP, "--solve", "--format", "text"])
    out = io.StringIO()
    assert cli.run(args, out=out, err=io.StringIO()) == cli.EXIT_OK
    text = out.getvalue()
    assert "OPTIMAL" in text and "A4" in text
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)


# --- the grammar is shared, not copied --------------------------------------


def test_the_cli_and_the_opt_command_parse_the_same_spec_identically() -> None:
    """`--solve 'max ...'` and `:opt max ...` must mean the same thing.

    They do because both call `optspec.parse_inline_model`; this fails if
    either grows its own copy, which is the drift the shared module exists to
    prevent.
    """
    from gridcalc.optspec import parse_inline_model
    from gridcalc.tui import solve as tui_solve

    spec = "max B4 vars A4:A5 st D4:D6 bounds A4=0:3 int A5"
    assert tui_solve._parse_opt_inline is parse_inline_model
    model = parse_inline_model(spec.split())
    assert model.sense == "max"
    assert model.bounds == "A4=0:3"
    assert model.integers == "A5"

    g = load_workbook(LP)
    from_cli = cli._model_for(g, spec)
    assert from_cli.to_json() == model.to_json()


def test_goal_and_sweep_parsers_are_shared_with_the_tui() -> None:
    from gridcalc import optspec
    from gridcalc.tui import solve as tui_solve

    assert tui_solve._parse_goal is optspec.parse_goal
    assert tui_solve._parse_sweep is optspec.parse_sweep
    assert tui_solve._resolve_model is optspec.resolve_model
