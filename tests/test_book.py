"""Tests for `gridcalc.book` and the CLI's `--set` / `--inputs` / `--get`."""

from __future__ import annotations

import io
import json
import math

import pytest

from gridcalc import cli
from gridcalc.book import Book, BookError
from gridcalc.engine import Grid, Mode, NamedRange
from gridcalc.loader import load_workbook
from gridcalc.tui import cli_parser


@pytest.fixture
def loan(tmp_path) -> str:
    """A loan model saved as xlsx: inputs on one sheet, outputs on another."""
    g = Grid()
    g.mode = Mode.EXCEL
    g._apply_mode_libs()
    g.sheets[0].name = "Inputs"
    g.setcells_bulk([(1, 0, "0.05"), (1, 1, "30"), (1, 2, "300000"), (1, 3, "North")])
    g.add_sheet("Out")
    g.set_active("Out")
    g.setcells_bulk(
        [
            (1, 0, "=PMT(Inputs!B1/12,Inputs!B2*12,Inputs!B3)"),
            (1, 1, '=IF(Inputs!B4="North","N","other")'),
            (3, 0, "1"),
            (3, 1, "2"),
            (3, 2, "3"),
            (4, 0, "=SUM(D1:D3)"),
            (6, 0, "=SEQUENCE(Inputs!B2/10)"),
            (7, 0, "=1/(Inputs!B1-0.05)"),
        ]
    )
    g.set_active("Inputs")
    for name, sheet, c, r, c2, r2 in [
        ("Rate", "Inputs", 1, 0, 1, 0),
        ("Years", "Inputs", 1, 1, 1, 1),
        ("Principal", "Inputs", 1, 2, 1, 2),
        ("Region", "Inputs", 1, 3, 1, 3),
        ("Payment", "Out", 1, 0, 1, 0),
        ("Tag", "Out", 1, 1, 1, 1),
        ("Weights", "Out", 3, 0, 3, 2),
        ("Total", "Out", 4, 0, 4, 0),
        ("Seq", "Out", 6, 0, 6, 0),
        ("Spread", "Out", 7, 0, 7, 0),
    ]:
        g.names.append(NamedRange(name, c, r, c2, r2, sheet=sheet))
    g.names.append(NamedRange("TaxRate", formula="=0.2"))
    g.recalc()
    path = str(tmp_path / "loan.xlsx")
    assert g.xlsxsave(path) == 0
    return path


def _pmt(rate: float, years: float, principal: float) -> float:
    i, n = rate / 12, years * 12
    return -principal * i / (1 - (1 + i) ** -n)


def test_names_lists_each_target(loan) -> None:
    names = Book.open(loan).names()
    assert names["Rate"] == "Inputs!$B$1"
    assert names["Weights"] == "Out!$D$1:$D$3"
    assert names["TaxRate"] == "=0.2"


def test_run_reads_outputs_after_the_inputs_are_written(loan) -> None:
    book = Book.open(loan)
    out = book.run(
        {"Rate": 0.04, "Years": 40, "Region": "South", "Weights": [10, 20, 30]},
        ["Payment", "Tag", "Total", "Seq#", "TaxRate", "Out!E1"],
    )
    assert out["Payment"] == pytest.approx(_pmt(0.04, 40, 300000))
    assert out["Tag"] == "other"
    assert out["Total"] == 60.0 == out["Out!E1"]
    assert out["Seq#"] == [[1.0], [2.0], [3.0], [4.0]]  # `#` reads the whole spill
    assert out["TaxRate"] == 0.2  # a formula name is evaluated


def test_run_restores_the_inputs(loan) -> None:
    book = Book.open(loan)
    before = book.get()
    book.run({"Rate": 0.09, "Weights": [[7], [8], [9]]}, ["Payment"])
    assert book.get() == before
    assert book.get(["Seq#"]) == {"Seq#": [[1.0], [2.0], [3.0]]}


def test_set_keeps_the_inputs_for_save(loan, tmp_path) -> None:
    book = Book.open(loan)
    book.set({"Rate": 0.07})
    out = str(tmp_path / "filled.xlsx")
    book.save(out)
    again = Book.open(out).get(["Rate", "Payment"])
    assert again["Rate"] == 0.07
    assert again["Payment"] == pytest.approx(_pmt(0.07, 30, 300000))


def test_an_error_result_reads_as_its_code(loan) -> None:
    assert Book.open(loan).get(["Spread"]) == {"Spread": {"error": "#DIV/0!"}}


def test_text_inputs_stay_text(loan) -> None:
    book = Book.open(loan)
    assert book.run({"Region": "=1+1"}, ["Region"]) == {"Region": "=1+1"}
    assert book.run({"Region": "12"}, ["Region"]) == {"Region": "12"}
    assert book.run({"Region": "TRUE"}, ["Region"]) == {"Region": "TRUE"}
    assert book.run({"Region": True, "Rate": None}, ["Region", "Rate"]) == {
        "Region": True,
        "Rate": None,
    }


@pytest.mark.parametrize(
    ("inputs", "message"),
    [
        ({"Weights": 5}, "3x1; give a list of rows"),
        ({"Weights": [[1, 2]]}, "3x1; the value given is 1x2"),
        ({"Nope": 1}, "no defined name or cell 'Nope'"),
        ({"TaxRate": 1}, "cannot take input"),
        ({"Seq#": 1}, "cannot take input"),
        ({"Rate": math.nan}, "is not a number"),
        ({"Rate": {"a": 1}}, "is not a number"),
    ],
)
def test_bad_inputs_are_refused_before_any_write(loan, inputs, message) -> None:
    book = Book.open(loan)
    before = book.get()
    with pytest.raises(BookError, match=message):
        book.run(inputs, ["Payment"])
    assert book.get() == before


def test_names_are_case_insensitive_and_cells_resolve(loan) -> None:
    book = Book.open(loan)
    assert book.run({"rate": 0.05}, ["PAYMENT", "Inputs!B2", "Out!D1:D2"]) == {
        "PAYMENT": pytest.approx(_pmt(0.05, 30, 300000)),
        "Inputs!B2": 30.0,
        "Out!D1:D2": [[1.0], [2.0]],
    }


def test_a_local_name_on_several_sheets_must_be_qualified() -> None:
    g = Grid()
    g.add_sheet("B")
    g.names += [NamedRange("X", 0, 0, 0, 0, sheet=s) for s in ("Sheet1", "B")]
    book = Book(g)
    with pytest.raises(BookError, match="several sheets"):
        book.resolve("X")
    assert book.resolve("B!X").sheet == "B"


# --- CLI --------------------------------------------------------------------


def _cli(*argv: str) -> tuple[int, dict, str]:
    args = cli_parser().parse_args(list(argv))
    out, err = io.StringIO(), io.StringIO()
    code = cli.run(args, out=out, err=err)
    text = out.getvalue()
    return (
        code,
        (json.loads(text) if text.strip() and args.format == "json" else {}),
        err.getvalue(),
    )


def test_cli_set_and_get(loan) -> None:
    code, out, _ = _cli(
        loan, "--set", "Rate=0.04", "--set", "Region=South", "--get", "Payment", "--get", "Tag"
    )
    assert code == cli.EXIT_OK
    assert out["inputs"] == {"Rate": 0.04, "Region": "South"}
    assert out["outputs"]["Payment"] == pytest.approx(_pmt(0.04, 30, 300000))
    assert out["outputs"]["Tag"] == "other"


def test_cli_set_reads_json_values(loan) -> None:
    code, out, _ = _cli(
        loan,
        "--set",
        'Region="12"',
        "--set",
        "Weights=[4,5,6]",
        "--get",
        "Region",
        "--get",
        "Total",
    )
    assert code == cli.EXIT_OK
    assert out["outputs"] == {"Region": "12", "Total": 15.0}


def test_cli_inputs_file_runs_each_case(loan, tmp_path) -> None:
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([{"Rate": 0.03}, {"Rate": 0.06}, {}]))
    code, out, _ = _cli(loan, "--inputs", str(cases), "--get", "Payment")
    assert code == cli.EXIT_OK
    pays = [r["outputs"]["Payment"] for r in out["runs"]]
    assert pays == [
        pytest.approx(_pmt(0.03, 30, 300000)),
        pytest.approx(_pmt(0.06, 30, 300000)),
        pytest.approx(_pmt(0.05, 30, 300000)),  # each case starts from the file
    ]


def test_cli_without_get_reports_every_name(loan) -> None:
    code, out, _ = _cli(loan, "--set", "Years=10")
    assert code == cli.EXIT_OK
    assert set(out["outputs"]) >= {"Rate", "Payment", "Weights", "TaxRate"}
    assert out["outputs"]["Seq"] == 1.0


def test_cli_unknown_name_is_a_usage_error(loan) -> None:
    code, out, err = _cli(loan, "--set", "Nope=1")
    assert code == cli.EXIT_ERROR and out == {}
    assert "no defined name or cell 'Nope'" in err


def test_cli_set_with_convert_writes_the_inputs(loan, tmp_path) -> None:
    dest = str(tmp_path / "out.xlsx")
    code, _, _ = _cli(loan, "--set", "Rate=0.07", "--convert", dest)
    assert code == cli.EXIT_OK
    g = load_workbook(dest)
    assert Book(g).get(["Rate"]) == {"Rate": 0.07}


def test_cli_set_needs_name_equals_value(loan) -> None:
    code, _, err = _cli(loan, "--set", "Rate")
    assert code == cli.EXIT_ERROR
    assert "NAME=VALUE" in err


@pytest.mark.parametrize("argv", [["--set", "Rate=1"], ["--get", "Rate"], ["--inputs", "x.json"]])
def test_new_flags_are_headless(loan, argv) -> None:
    assert cli.is_headless(cli_parser().parse_args([loan, *argv]))
