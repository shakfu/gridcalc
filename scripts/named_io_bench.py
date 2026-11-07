"""Time named-input/output runs of one workbook in five engines.

    uv run python scripts/named_io_bench.py --out /tmp/nio --engine path/to/gridcraft-cli

Builds an amortization model at two sizes (1 and 10 blocks of 360 rows),
then runs 20 cases in each engine and prints load time, time per case and
the largest difference from gridcalc's outputs. pycel and formulas run in
their own `uv` environments. Each engine runs under `proc_guard.py`'s time
limit and memory cap. ``--one ENGINE MODEL CASES`` runs a single engine
and prints JSON; the driver uses it. Results: `docs/dev/comparison.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

N = 360  # rows per block
INPUTS = ("Rate", "Principal")
OUTPUTS = ("Payment", "TotalInterest", "EndBalance")
_TIMEOUT = 1200  # seconds per engine and model
ROW = "{:6} {:>8}  {:17} {:>8} {:>12}  {}"
UV_ENV = {
    "pycel": ["--python", "3.11", "--with", "pycel", "--with", "openpyxl==3.0.10"],
    "formulas": ["--with", "formulas", "--with", "openpyxl"],
}


def build_model(path: Path, blocks: int) -> int:
    """Write the model; return its formula count. Block k runs at Rate + k/1000."""
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
    from openpyxl.workbook.defined_name import DefinedName

    wb = Workbook()
    inp = wb.worksheets[0]
    inp.title = "Inputs"
    inp["A1"], inp["B1"] = "Rate", 0.05
    inp["A2"], inp["B2"] = "Principal", 300000
    m = wb.create_sheet("Model")
    interest = []
    for k in range(blocks):
        a, b, c, d, e = (get_column_letter(1 + k * 6 + i) for i in range(5))
        m[f"{a}1"] = f"=Rate+{k}/1000"
        m[f"{b}1"] = f"={a}1/12*Principal/(1-(1+{a}1/12)^-{N})"  # closed form: pycel has no PMT
        m[f"{e}1"] = "=Principal"
        for r in range(2, N + 2):
            m[f"{a}{r}"] = f"={a}{r - 1}"
            m[f"{b}{r}"] = f"=${b}$1"
            m[f"{c}{r}"] = f"={e}{r - 1}*{a}{r}/12"
            m[f"{d}{r}"] = f"={b}{r}-{c}{r}"
            m[f"{e}{r}"] = f"={e}{r - 1}-{d}{r}"
        interest.append(f"SUM(Model!{c}2:{c}{N + 1})")
    out = wb.create_sheet("Out")
    out["A1"], out["B1"] = "Payment", "=Model!B1"
    out["A2"], out["B2"] = "TotalInterest", "=" + "+".join(interest)
    out["A3"], out["B3"] = "EndBalance", f"=Model!E{N + 1}"
    refs = ["Inputs!$B$1", "Inputs!$B$2", "Out!$B$1", "Out!$B$2", "Out!$B$3"]
    for name, ref in zip(INPUTS + OUTPUTS, refs, strict=True):
        wb.defined_names[name] = DefinedName(name, attr_text=ref)
    wb.save(path)
    return blocks * (N * 5 + 3) + 3


def _gridcraft_cmds(case: dict[str, float]) -> list[str]:
    # `cell.set` ignores a name and writes the active cell, so inputs are addresses.
    cmds = []
    for cell, name in (("Inputs!B1", "Rate"), ("Inputs!B2", "Principal")):
        cmds += ["--cmd", "cell.set=" + json.dumps({"cell": cell, "input": str(case[name])})]
    for o in OUTPUTS:
        cmds += ["--cmd", "formulas.evaluate=" + json.dumps({"formula": "=" + o})]
    return cmds


def _gridcraft_parse(stdout: str) -> list[list[float]]:
    vals = [json.loads(ln)["result"] for ln in stdout.splitlines() if '"formulas.evaluate"' in ln]
    return [vals[i : i + len(OUTPUTS)] for i in range(0, len(vals), len(OUTPUTS))]


def run_one(
    eng: str, model: str, cases: list[dict[str, float]], gridcraft: str | None
) -> dict[str, Any]:
    """Load ``model`` in ``eng`` and run every case. Times are seconds."""
    t0 = time.perf_counter()
    load = None
    if eng == "gridcalc":
        from gridcalc.book import Book

        book = Book.open(model)
        t1 = time.perf_counter()
        outs = [[r[o] for o in OUTPUTS] for r in book.run_many(cases, list(OUTPUTS))]
    elif eng == "gridcalc-cli":  # one process for all cases: per case includes load
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cases, f)
        argv = ["gridcalc", model, "--inputs", f.name] + [x for o in OUTPUTS for x in ("--get", o)]
        p = subprocess.run(argv, capture_output=True, text=True, check=True)  # noqa: S603
        os.unlink(f.name)
        t1 = t0
        outs = [[r["outputs"][o] for o in OUTPUTS] for r in json.loads(p.stdout)["runs"]]
    elif eng == "formulas":
        import formulas

        xm = formulas.ExcelModel().loads(model).finish()
        bk = "'[" + os.path.basename(model) + "]'!"  # the book part is case-sensitive
        fn = xm.compile(
            inputs=[bk + i.upper() for i in INPUTS], outputs=[bk + o.upper() for o in OUTPUTS]
        )
        t1 = time.perf_counter()
        outs = [[float(x.value[0, 0]) for x in fn(*(c[i] for i in INPUTS))] for c in cases]
    elif eng == "pycel":
        from pycel import ExcelCompiler

        xc = ExcelCompiler(filename=model)
        addr = {}  # pycel takes addresses only
        for name, d in xc.excel.defined_names.items():
            ((cell, sheet),) = d
            addr[name] = f"{sheet}!{cell.replace('$', '')}"
        for o in OUTPUTS:
            xc.evaluate(addr[o])  # builds the cell map `set_value` needs
        t1 = time.perf_counter()
        outs = []
        for c in cases:
            for i in INPUTS:
                xc.set_value(addr[i], c[i])
            outs.append([xc.evaluate(addr[o]) for o in OUTPUTS])
    elif eng in ("gridcraft-script", "gridcraft-proc"):
        if gridcraft is None:
            raise SystemExit("GridCraft needs --engine")
        with tempfile.TemporaryDirectory() as cwd:

            def run(extra: list[str]) -> str:
                argv = [gridcraft, "run", "--in", model, *extra]
                return subprocess.run(
                    argv, capture_output=True, text=True, cwd=cwd, check=True
                ).stdout  # noqa: S603

            if eng == "gridcraft-proc":  # one process per case
                t1 = t0
                outs = [row for c in cases for row in _gridcraft_parse(run(_gridcraft_cmds(c)))]
            else:  # one process, cases in sequence; every case sets every input
                run([])
                load = time.perf_counter() - t0
                t1 = time.perf_counter()
                outs = _gridcraft_parse(run([x for c in cases for x in _gridcraft_cmds(c)]))
    else:
        raise SystemExit(f"unknown engine {eng}")
    t2 = time.perf_counter()
    return {
        "engine": eng,
        "load_s": load if load is not None else t1 - t0,
        "case_s": (t2 - t1) / len(cases),
        "outputs": outs,
    }


def _sub(
    eng: str, model: Path, casef: Path, gridcraft: str | None, mem_mb: int
) -> dict[str, Any] | str:
    """One engine's `run_one` result, or why it was stopped."""
    # Here, not at the top: `--one` runs under `python -I`, which leaves this
    # directory off `sys.path`.
    from proc_guard import run_guarded

    if eng in UV_ENV:
        pre = ["uv", "run", "--no-project", *UV_ENV[eng], "python", "-I", "-W", "ignore"]
    else:
        pre = [sys.executable, "-I"]
    argv = [*pre, __file__, "--one", eng, str(model), str(casef)]
    if gridcraft:
        argv += ["--engine", gridcraft]
    p = run_guarded(argv, timeout=_TIMEOUT, mem_mb=mem_mb)
    if p.killed:
        return p.killed
    if p.returncode != 0:
        return (p.stderr.strip().splitlines() or [f"exit {p.returncode}"])[-1][:120]
    return json.loads(p.stdout.strip().splitlines()[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, help="directory for the models and cases")
    parser.add_argument(
        "--engine",
        default=os.environ.get("GRIDCRAFT_CLI") or shutil.which("gridcraft-cli"),
        help="GridCraft's CLI; GridCraft is skipped without it",
    )
    parser.add_argument("--cases", type=int, default=20)
    parser.add_argument(
        "--skip", default="", help="engines to leave out, comma-separated (e.g. formulas)"
    )
    parser.add_argument("--mem-mb", type=int, default=2048, help="memory cap per engine process")
    parser.add_argument(
        "--one", nargs=3, metavar=("ENGINE", "MODEL", "CASES"), help=argparse.SUPPRESS
    )
    args = parser.parse_args()
    if args.one:
        eng, model, casef = args.one
        print(json.dumps(run_one(eng, model, json.loads(Path(casef).read_text()), args.engine)))
        return
    if not args.out:
        parser.error("--out is required")
    args.out.mkdir(parents=True, exist_ok=True)
    casef = args.out / "cases.json"
    cases = [{"Rate": 0.02 + i * 0.003, "Principal": 100000 + i * 25000} for i in range(args.cases)]
    casef.write_text(json.dumps(cases))
    engines = ["gridcalc", "gridcalc-cli"]
    engines += ["gridcraft-script", "gridcraft-proc"] if args.engine else []
    engines += ["pycel", "formulas"]
    engines = [e for e in engines if e not in args.skip.split(",")]
    print(ROW.format("model", "formulas", "engine", "load s", "per case ms", "max rel diff"))
    for blocks, label in ((1, "small"), (10, "big")):
        model = args.out / f"{label}.xlsx"
        nf = build_model(model, blocks)
        ref = None
        for eng in engines:
            r = _sub(eng, model, casef, args.engine, args.mem_mb)
            if isinstance(r, str):
                print(ROW.format(label, nf, eng, "-", "-", f"stopped: {r}"))
                continue
            ref = ref or r["outputs"]
            diff = max(
                abs(a - b) / max(1.0, abs(b))
                for x, y in zip(r["outputs"], ref, strict=True)
                for a, b in zip(x, y, strict=True)
            )
            ms = f"{r['case_s'] * 1000:.1f}"
            print(ROW.format(label, nf, eng, f"{r['load_s']:.3f}", ms, f"{diff:.0e}"))


if __name__ == "__main__":
    main()
