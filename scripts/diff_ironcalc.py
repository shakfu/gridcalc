"""Evaluate the same formulas in gridcalc and IronCalc and report disagreements.

    uv run --with ironcalc python scripts/diff_ironcalc.py
    uv run --with ironcalc python scripts/diff_ironcalc.py --json out.json

Two corpora:

* calls:    every function gridcalc registers, applied to each argument
            pattern in `ARGS` over the fixed grid in `GRID`.
* fixtures: every formula cell in `tests/xlsx/*.xlsx` and `examples/*.xlsx`.

Neither engine is ground truth. A disagreement marks a candidate bug in one of
them; Excel decides which. Results and triage: `docs/dev/ironcalc.md`.
"""

from __future__ import annotations

import argparse
import json
import math
import select
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from gridcalc.engine import FORMULA, Grid, Mode, _make_eval_globals
from gridcalc.formula.errors import ExcelError
from gridcalc.libs import xlsx

ROOT = Path(__file__).resolve().parent.parent

# (col, row, text), zero-based. Columns: A numbers, B text, C fractions,
# D date serials (2024-01-01 onward), E signed integers.
GRID: list[tuple[int, int, str]] = (
    [(0, r, v) for r, v in enumerate(["3", "1", "4", "1", "5", "9", "2", "6", "5", "3.5"])]
    + [
        (1, r, v)
        for r, v in enumerate(
            [
                "apple",
                "Banana",
                "cherry",
                "apple",
                "date",
                "elder fig",
                "",
                "Grape",
                "apple",
                "kiwi",
            ]
        )
        if v
    ]
    + [(2, r, f"{(r + 1) / 10:g}") for r in range(10)]
    + [(3, r, str(45292 + 31 * r)) for r in range(10)]
    + [(4, r, str(r - 4)) for r in range(10)]
)

ARGS: list[str] = [
    "()",
    "(A1)",
    "(A10)",
    "(C3)",
    "(E1)",
    "(E5)",
    "(-A2)",
    "(A1,A2)",
    "(A1,C1)",
    "(C1,A2)",
    "(A2,A1)",
    "(A1,A2,A3)",
    "(A1:A10)",
    "(A1:A10,2)",
    "(A1:A10,C1)",
    "(A1:A10,C1:C10)",
    "(A1:A10,A1:A10)",
    '(A1:A10,">3")',
    '(A1:A10,">3",C1:C10)',
    "(A1,A1:A10)",
    "(C1,A1:A10)",
    "(2,A1:A10)",
    "(A1:A10,A1:A10,C1:C10)",
    "(C5,A1,A2)",
    "(C5,A1,A2,TRUE)",
    "(B1)",
    "(B1,2)",
    "(B1,2,3)",
    "(B1,B2)",
    '(B1:B10,"apple")',
    '("apple",B1:B10,0)',
    "(D1)",
    "(D1,D5)",
    "(D1,A1)",
    "(D1,D5,1)",
]

# Different answers by design: random numbers and the clock.
SKIP = {"RAND", "RANDBETWEEN", "RANDARRAY", "NOW", "TODAY"}

OUT_COL, OUT_ROW = 25, 0  # Z1, clear of GRID

# A formula that exceeds either limit kills the worker and is recorded as a crash.
MAX_RSS_KB = 2 * 1024 * 1024
MAX_SECONDS = 30.0


def norm(v: Any) -> Any:
    """Collapse an engine value to None, bool, float, str, or ('err', code)."""
    if isinstance(v, ExcelError):
        return ("err", v.value)
    if isinstance(v, str) and v.startswith("#") and v.upper() == v and len(v) <= 8:
        return ("err", v)
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return ("err", "NaN") if math.isnan(v) else float(v)
    data = getattr(v, "data", None)  # a Vec: compare its top-left element
    if data:
        return norm(data[0])
    return repr(v)


def same(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if a is None or b is None:  # an empty result reads as 0 in IronCalc
        return (a or 0.0) == (b or 0.0)
    return bool(type(a) is type(b) and a == b)


def classify(g: Any, i: Any) -> str:
    if isinstance(g, list | tuple) and g[0] == "crash":
        return "gridcalc-crash"
    if isinstance(i, list | tuple) and i[0] == "crash":
        return "ironcalc-crash"
    g = tuple(g) if isinstance(g, list) else g  # JSON turns tuples into lists
    i = tuple(i) if isinstance(i, list) else i
    g_err = isinstance(g, tuple)
    i_err = isinstance(i, tuple)
    if g_err and i_err:
        if g == i:
            return "agree-error"
        if i[1] == "#NAME?":
            return "ironcalc-unsupported"
        if g[1] == "#NAME?":
            return "gridcalc-unsupported"
        return "error-kind"
    if same(g, i):
        return "agree"
    if i_err:
        return "ironcalc-unsupported" if i[1] == "#NAME?" else "ironcalc-error"
    if g_err:
        return "gridcalc-unsupported" if g[1] == "#NAME?" else "gridcalc-error"
    return "value"


class Gridcalc:
    def __init__(self) -> None:
        self.g = Grid()
        self.g.mode = Mode.EXCEL
        self.g._apply_mode_libs()
        self.g.setcells_bulk(GRID)

    def eval(self, formula: str) -> Any:
        try:
            self.g.setcell(OUT_COL, OUT_ROW, formula)
        except Exception as exc:  # noqa: BLE001 -- a crash is a finding
            self.__init__()  # type: ignore[misc]
            return ("crash", type(exc).__name__)
        v = self.g._cell_lookup_value(OUT_COL, OUT_ROW)
        self.g.setcell(OUT_COL, OUT_ROW, "")
        return norm(v)


class Ironcalc:
    def __init__(self) -> None:
        import ironcalc  # type: ignore[import-not-found]

        self.m = ironcalc.create("diff", "en", "UTC")
        for c, r, text in GRID:
            self.m.set_user_input(0, r + 1, c + 1, text)

    def eval(self, formula: str) -> Any:
        try:
            self.m.set_user_input(0, OUT_ROW + 1, OUT_COL + 1, formula)
            self.m.evaluate()
        except BaseException as exc:  # noqa: BLE001 -- a Rust panic is a BaseException
            self.__init__()  # type: ignore[misc]
            return ("crash", type(exc).__name__)
        v = self.m.get_cell_value(0, OUT_ROW + 1, OUT_COL + 1)
        self.m.range_clear_contents(0, OUT_ROW + 1, OUT_COL + 1, OUT_ROW + 1, OUT_COL + 1)
        return norm(v)


def function_names() -> list[str]:
    names = {k.upper() for k in xlsx.BUILTINS}
    names |= {k.upper() for k in _make_eval_globals() if k.isidentifier() and not k.startswith("_")}
    return sorted(names - SKIP)


def call_corpus() -> list[tuple[str, str]]:
    return [(name, f"={name}{args}") for name in function_names() for args in ARGS]


def worker(start: int) -> None:
    """Evaluate `call_corpus()[start:]`, one JSON line per event, flushed."""
    gc, ic = Gridcalc(), Ironcalc()
    for idx, (_fn, formula) in enumerate(call_corpus()[start:], start):
        print(json.dumps({"idx": idx, "engine": "gridcalc"}), flush=True)
        g = gc.eval(formula)
        print(json.dumps({"idx": idx, "engine": "ironcalc", "gridcalc": g}), flush=True)
        i = ic.eval(formula)
        print(json.dumps({"idx": idx, "gridcalc": g, "ironcalc": i}), flush=True)


def rss_kb(pid: int) -> int:
    cmd = ["/bin/ps", "-o", "rss=", "-p", str(pid)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return int(out.stdout.strip() or 0)


def diff_calls() -> list[dict[str, Any]]:
    """Run `worker` in a subprocess, restarting it past any formula that kills it."""
    corpus = call_corpus()
    results: dict[int, tuple[Any, Any]] = {}
    start = 0
    while start < len(corpus):
        proc = subprocess.Popen(
            [sys.executable, __file__, "--worker", str(start)],
            stdout=subprocess.PIPE,
            text=True,
        )
        if proc.stdout is None:
            raise RuntimeError("worker has no stdout")
        pending: dict[str, Any] = {"idx": start, "engine": "gridcalc"}
        since = time.monotonic()
        reason = None
        while True:
            ready, _, _ = select.select([proc.stdout], [], [], 0.2)
            if ready:
                chunk = proc.stdout.readline()
                if not chunk:
                    break
                event = json.loads(chunk)
                if "ironcalc" in event:
                    results[event["idx"]] = (event["gridcalc"], event["ironcalc"])
                else:
                    pending, since = event, time.monotonic()
                continue
            if proc.poll() is not None:
                break
            if time.monotonic() - since > MAX_SECONDS:
                reason = "timeout"
            elif rss_kb(proc.pid) > MAX_RSS_KB:
                reason = "memory"
            if reason:
                proc.kill()
                break
        proc.wait()
        if proc.returncode == 0 and len(results) and max(results) == len(corpus) - 1:
            break
        idx = pending["idx"]
        crash = ("crash", reason or f"exit {proc.returncode}")
        if pending["engine"] == "gridcalc":
            results[idx] = (crash, None)
        else:
            results[idx] = (pending["gridcalc"], crash)
        start = idx + 1
    return [
        {
            "corpus": "calls",
            "fn": fn,
            "formula": f,
            "gridcalc": results[k][0],
            "ironcalc": results[k][1],
        }
        for k, (fn, f) in enumerate(corpus)
    ]


def diff_fixtures() -> list[dict[str, Any]]:
    import ironcalc

    rows = []
    paths = sorted((ROOT / "tests" / "xlsx").glob("*.xlsx")) + sorted(
        (ROOT / "examples").glob("*.xlsx")
    )
    for path in paths:
        g = Grid()
        if g.xlsxload(str(path)) != 0:
            continue
        try:
            m = ironcalc.load_from_xlsx(str(path), "en", "UTC")
        except Exception as exc:  # noqa: BLE001 -- report and move on
            rows.append(
                {
                    "corpus": "fixtures",
                    "fn": path.name,
                    "formula": "(load)",
                    "gridcalc": "loaded",
                    "ironcalc": ("err", type(exc).__name__),
                }
            )
            continue
        m.evaluate()
        for si, sheet in enumerate(g.sheet_names()):
            g.set_active(sheet)
            for (c, r), cl in sorted(g._cells.items()):
                if cl.type != FORMULA:
                    continue
                rows.append(
                    {
                        "corpus": "fixtures",
                        "fn": f"{path.name}:{sheet}",
                        "formula": f"{chr(65 + c) if c < 26 else c}{r + 1} {cl.text}",
                        "gridcalc": norm(g._cell_lookup_value(c, r)),
                        "ironcalc": norm(m.get_cell_value(si, r + 1, c + 1)),
                    }
                )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", type=Path, help="write every row, classified, to this file")
    ap.add_argument("--worker", type=int, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.worker is not None:
        worker(args.worker)
        return
    rows = diff_calls() + diff_fixtures()
    for row in rows:
        row["class"] = classify(row["gridcalc"], row["ironcalc"])

    for corpus in ("calls", "fixtures"):
        counts = Counter(r["class"] for r in rows if r["corpus"] == corpus)
        print(f"{corpus}: {sum(counts.values())} formulas")
        for cls, n in counts.most_common():
            print(f"  {cls:22} {n}")
    by_fn: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r["class"] not in ("agree", "agree-error"):
            by_fn[r["class"]].append(r["fn"])
    for r in rows:
        if r["class"].endswith("crash"):
            print(f"{r['class']}: {r['formula']} {r['gridcalc']} {r['ironcalc']}")
    for cls in ("ironcalc-unsupported", "gridcalc-unsupported"):
        print(f"{cls}: {' '.join(sorted(set(by_fn[cls])))}")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
