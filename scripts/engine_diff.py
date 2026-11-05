"""Score gridcalc and a second engine against the values Excel saved.

    uv run python scripts/engine_diff.py --engine path/to/gridcraft-cli corpus/*.xlsx
    uv run python scripts/engine_diff.py --list files.txt --json out.json

The second engine is any program that takes the command line of
GridCraft's `gridcraft-cli`. It runs `run --in FILE --cmd 'sheet.read={...}'`
and prints one JSON result per line. Each cell is scored against Excel's
saved value with the rules in `excel_corpus.py`.
Results: `docs/dev/excel-corpus.md`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from excel_corpus import _a1, application, excel_values, functions, gridcalc_value, same

from gridcalc.engine import FORMULA
from gridcalc.loader import load_workbook

Key = tuple[str, int, int]
_READ_LIMIT = 1_000_000  # cells per `sheet.read` call that gridcraft-cli accepts
_TIMEOUT = 180


def _col(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _reads(keys: list[Key]) -> list[dict[str, str]]:
    """`sheet.read` params covering ``keys``: one box per sheet, or one call per
    cell when the box exceeds the engine's read limit."""
    boxes: dict[str, list[int]] = {}
    for s, c, r in keys:
        b = boxes.setdefault(s, [c, r, c, r])
        b[:] = [min(b[0], c), min(b[1], r), max(b[2], c), max(b[3], r)]
    out = []
    for s, (c1, r1, c2, r2) in boxes.items():
        if (c2 - c1 + 1) * (r2 - r1 + 1) <= _READ_LIMIT:
            out.append({"sheet": s, "range": f"{_a1(c1, r1)}:{_a1(c2, r2)}"})
        else:
            out += [{"sheet": s, "range": _a1(c, r)} for (ks, c, r) in keys if ks == s]
    return out


def other_values(engine: str, path: Path, keys: list[Key]) -> tuple[dict[Key, Any], str | None]:
    """The second engine's value for each key, after a full recalculation."""
    cmds = ["--cmd", "formulas.calculateNow={}"]
    for p in _reads(keys):
        cmds += ["--cmd", "sheet.read=" + json.dumps(p)]
    # A scratch working directory: the engine is not ours and should not
    # write beside the corpus or the repo.
    with tempfile.TemporaryDirectory() as cwd:
        try:
            proc = subprocess.run(  # noqa: S603 -- the user names the engine
                [engine, "run", "--in", str(path), *cmds],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            return {}, f"timed out after {_TIMEOUT} s"
    err = None if proc.returncode == 0 else (proc.stderr.strip()[:300] or f"exit {proc.returncode}")
    values: dict[Key, Any] = {}
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        res = msg.get("result") if msg.get("command") == "sheet.read" else None
        if not res:
            continue
        m = re.match(r"([A-Z]+)(\d+)", res.get("range", "A1").split("!")[-1])
        c0, r0 = (_col(m.group(1)), int(m.group(2)) - 1) if m else (0, 0)
        for i, row in enumerate(res.get("values") or []):
            for j, v in enumerate(row):
                if isinstance(v, dict) and "error" in v:
                    v = ("error", v["error"])
                values[(res["sheet"], c0 + j, r0 + i)] = v
    return values, err


def compare(job: tuple[Path, str, float]) -> dict[str, Any]:
    """Score one workbook in both engines. Cells gridcalc imports as values
    are skipped, as in `excel_corpus.py`."""
    path, engine, rel = job
    rep: dict[str, Any] = {"file": str(path), "application": application(path)}
    try:
        formulas, saved = excel_values(path)
    except Exception as exc:  # noqa: BLE001 -- one bad file must not stop the run
        rep["error"] = f"{type(exc).__name__}: {exc}"
        return rep
    t = time.monotonic()
    try:
        g = load_workbook(path)
    except Exception as exc:  # noqa: BLE001
        g, rep["gridcalc_error"] = None, f"{type(exc).__name__}: {exc}"[:300]
    rep["gridcalc_s"] = time.monotonic() - t
    keys = [k for k in formulas if k in saved]
    if g is not None:
        sheets = {s.name: s for s in g.sheets}
        keys = [
            k
            for k in keys
            if (cl := sheets[k[0]]._cells.get(k[1:]) if k[0] in sheets else None) is not None
            and cl.type == FORMULA
        ]
    t = time.monotonic()
    other, rep["other_error"] = other_values(engine, path, keys)
    rep["other_s"] = time.monotonic() - t
    cells = []
    for k in keys:
        gv = gridcalc_value(g, k) if g is not None else None
        ov = other.get(k)
        cells.append(
            {
                "cell": f"{k[0]}!{_a1(k[1], k[2])}",
                "formula": formulas[k],
                "excel": saved[k],
                "gridcalc": gv,
                "other": ov,
                "gridcalc_ok": g is not None and same(saved[k], gv, rel),
                "other_ok": same(saved[k], ov, rel),
            }
        )
    rep["cells"] = cells
    return rep


def _rate(rep: dict[str, Any], side: str) -> float:
    cells = rep["cells"]
    return sum(c[side + "_ok"] for c in cells) / len(cells)


def _show(v: Any) -> str:
    return v[1] if isinstance(v, (tuple, list)) and len(v) == 2 and v[0] == "error" else repr(v)


def render(reports: list[dict[str, Any]], limit: int) -> str:
    scored = [r for r in reports if r.get("cells")]
    cells = [c for r in scored for c in r["cells"]]
    lines = []
    for r in reports:
        for k in ("error", "gridcalc_error", "other_error"):
            if r.get(k):
                lines.append(f"!! {r['file']}: {k}: {r[k]}")
    if not cells:
        return "\n".join([*lines, "no formula cells with saved values"])
    n = len(cells)
    gc = sum(c["gridcalc_ok"] for c in cells)
    ot = sum(c["other_ok"] for c in cells)
    gw = sum(_rate(r, "gridcalc") > _rate(r, "other") for r in scored)
    ow = sum(_rate(r, "other") > _rate(r, "gridcalc") for r in scored)
    lines += [
        f"{len(scored)} files, {n} formula cells with a saved value",
        f"   cells agreeing:   gridcalc {gc} ({gc / n:.1%})   other {ot} ({ot / n:.1%})",
        "   mean per file:    gridcalc {:.1%}   other {:.1%}".format(
            sum(_rate(r, "gridcalc") for r in scored) / len(scored),
            sum(_rate(r, "other") for r in scored) / len(scored),
        ),
        f"   files higher:     gridcalc {gw}   other {ow}   tie {len(scored) - gw - ow}",
        "   time:             gridcalc {:.1f} s   other {:.1f} s".format(
            sum(r.get("gridcalc_s", 0) for r in reports), sum(r.get("other_s", 0) for r in reports)
        ),
    ]
    for side, other, title in (
        ("gridcalc", "other", "gridcalc wrong, other right"),
        ("other", "gridcalc", "other wrong, gridcalc right"),
    ):
        hits = [
            (r["file"], c)
            for r in scored
            for c in r["cells"]
            if c[other + "_ok"] and not c[side + "_ok"]
        ]
        by_fn: Counter[str] = Counter()
        for _, c in hits:
            by_fn.update(functions(c["formula"]))
        lines.append(f"== {title}: {len(hits)} cells, by function")
        lines += [f"   {k:5d}  {name}" for name, k in by_fn.most_common(limit)]
        for f, c in hits[:limit]:
            lines.append(
                f"   {Path(f).name} {c['cell']}: {c['formula'][:60]}  excel={_show(c['excel'])}  "
                f"gridcalc={_show(c['gridcalc'])}  other={_show(c['other'])}"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--list", type=Path, help="file with one workbook path per line")
    parser.add_argument(
        "--engine",
        default=os.environ.get("GRIDCRAFT_CLI") or shutil.which("gridcraft-cli"),
        help="second engine's CLI (default: $GRIDCRAFT_CLI, then gridcraft-cli on PATH)",
    )
    parser.add_argument("--json", type=Path, help="write the full reports here")
    parser.add_argument("--rel", type=float, default=1e-9, help="relative number tolerance")
    parser.add_argument("--limit", type=int, default=20, help="rows listed per section")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()
    if not args.engine:
        parser.error("no engine: pass --engine or set GRIDCRAFT_CLI")
    files = list(args.files)
    if args.list:
        files += [Path(p) for p in args.list.read_text().splitlines() if p.strip()]
    if not files:
        parser.error("no workbooks given")
    jobs = [(p, args.engine, args.rel) for p in files]
    with Pool(args.jobs) as pool:
        reports = pool.map(compare, jobs, chunksize=1)
    if args.json:
        args.json.write_text(json.dumps(reports, indent=2, default=str))
    print(render(reports, args.limit))


if __name__ == "__main__":
    main()
