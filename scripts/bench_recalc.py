"""Time EXCEL-mode recalc on synthetic workbooks.

    uv run python scripts/bench_recalc.py                  # 10k and 100k, all workloads
    uv run python scripts/bench_recalc.py 10000 -w ranges  # one size, one workload
    uv run --with ironcalc python scripts/bench_recalc.py -e ironcalc -r 3

Workloads, with n the formula count:

* chain:  cell k is `=<cell k-1>+1`, one dependency chain of depth n.
* flat:   n constants and n formulas `=X*2+1`, each reading one constant.
* ranges: 1000 constants in A1:A1000 and n formulas `=SUM(A1:A1000)+k`.

IronCalc has no incremental recalc, so each of its edits is `set_user_input`
followed by a full `evaluate()`.

Results and analysis: `docs/dev/ironcalc.md`.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable

from gridcalc.engine import NROW, Grid, Mode

Cells = list[tuple[int, int, str]]
Pos = tuple[int, int]
Workload = tuple[Cells, Pos, Pos]  # cells, root constant, last formula


def ref(c: int, r: int) -> str:
    s = ""
    c += 1
    while c:
        c, m = divmod(c - 1, 26)
        s = chr(65 + m) + s
    return f"{s}{r + 1}"


def pos(k: int) -> Pos:
    return k // NROW, k % NROW  # column-major


def chain(n: int) -> Workload:
    cells = [(0, 0, "1")]
    for k in range(1, n):
        c, r = pos(k)
        cells.append((c, r, f"={ref(*pos(k - 1))}+1"))
    return cells, (0, 0), pos(n - 1)


def flat(n: int) -> Workload:
    cells = []
    for k in range(n):
        c, r = pos(2 * k)
        cells.append((c, r, str(k)))
        cells.append((*pos(2 * k + 1), f"={ref(c, r)}*2+1"))
    return cells, (0, 0), pos(2 * n - 1)


def ranges(n: int) -> Workload:
    cells = [(0, r, str(r)) for r in range(1000)]
    for k in range(n):
        cells.append((*pos(NROW + k), f"=SUM(A1:A1000)+{k}"))
    return cells, (0, 0), pos(NROW + n - 1)


WORKLOADS: dict[str, Callable[[int], Workload]] = {
    "chain": chain,
    "flat": flat,
    "ranges": ranges,
}


def timed(fn: Callable[[], None]) -> float:
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def run_gridcalc(cells: Cells, root: Pos, last: Pos) -> tuple[float, ...]:
    g = Grid()
    g.mode = Mode.EXCEL
    load = timed(lambda: g.setcells_bulk(cells))
    full = timed(g.recalc)
    edit_root = timed(lambda: g.setcell(*root, "2"))
    edit_leaf = timed(lambda: g.setcell(*last, "=1+1"))
    return load, full, edit_root, edit_leaf


def run_ironcalc(cells: Cells, root: Pos, last: Pos) -> tuple[float, ...]:
    import ironcalc  # type: ignore[import-not-found]

    m = ironcalc.create("bench", "en", "UTC")

    def put(c: int, r: int, text: str) -> None:
        m.set_user_input(0, r + 1, c + 1, text)  # rows and columns are 1-based

    def load_all() -> None:
        for c, r, text in cells:
            put(c, r, text)
        m.evaluate()

    def edit(p: Pos, text: str) -> None:
        put(*p, text)
        m.evaluate()

    load = timed(load_all)
    full = timed(m.evaluate)
    edit_root = timed(lambda: edit(root, "2"))
    edit_leaf = timed(lambda: edit(last, "=1+1"))
    return load, full, edit_root, edit_leaf


ENGINES = {"gridcalc": run_gridcalc, "ironcalc": run_ironcalc}


def run(engine: str, name: str, n: int, repeat: int) -> None:
    work = WORKLOADS[name](n)
    runs = [ENGINES[engine](*work) for _ in range(repeat)]
    load, full, edit_root, edit_leaf = (min(col) for col in zip(*runs, strict=True))
    print(
        f"{engine:8} {name:7} n={n:>6}  load {load:8.3f}s  full {full:8.3f}s  "
        f"edit-root {edit_root:8.3f}s  edit-leaf {edit_leaf * 1e3:8.2f}ms",
        flush=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("sizes", nargs="*", type=int, default=[10_000, 100_000])
    ap.add_argument("-w", "--workload", action="append", choices=list(WORKLOADS))
    ap.add_argument("-e", "--engine", action="append", choices=list(ENGINES))
    ap.add_argument("-r", "--repeat", type=int, default=1, help="report the best of N runs")
    args = ap.parse_args()
    for n in args.sizes:
        for name in args.workload or WORKLOADS:
            for engine in args.engine or ["gridcalc"]:
                run(engine, name, n, args.repeat)


if __name__ == "__main__":
    main()
