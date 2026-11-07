"""Score gridcalc, GridCraft, pycel and formulas against Excel's saved values.

    uv run python scripts/engine_compare.py --list files.txt --out /tmp/compare
    uv run python scripts/engine_compare.py --engine path/to/gridcraft-cli corpus/*.xlsx

gridcalc and GridCraft are scored by `engine_diff.compare`. pycel and formulas
run `foreign_engine.py` once per file in their own `uv` environment, with a
time limit and a memory cap (`proc_guard.py`); results are cached in
``--out``, so a second run only rescores. A file an engine fails on scores 0
for it. Results: `docs/dev/comparison.md`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from engine_diff import compare
from excel_corpus import functions, same
from proc_guard import MEM_MB, default_jobs, run_guarded

HERE = Path(__file__).resolve().parent
WORKER = HERE / "foreign_engine.py"
# pycel 1.0b30 uses `ast.Str`, gone in Python 3.12, and reads defined names
# through an openpyxl API removed in 3.1.
UV_ENV = {
    "pycel": ["--python", "3.11", "--with", "pycel", "--with", "openpyxl==3.0.10"],
    "formulas": ["--with", "formulas", "--with", "openpyxl"],
}
# Workbooks that dominate cell totals.
LARGE = ("ARABIC_ROMAN.xlsx", "FLOOR_CEILING.xlsx")

Key = tuple[str, int, int]


def _cache(out: Path, eng: str, f: str) -> Path:
    return out / eng / (hashlib.sha1(f.encode()).hexdigest()[:16] + ".json")  # noqa: S324


def run_foreign(eng: str, f: str, out: Path, timeout: float, mem_mb: int) -> None:
    """Run one file in ``eng`` unless cached; record a failure beside the cache."""
    dst = _cache(out, eng, f)
    if dst.exists() or dst.with_suffix(".fail").exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["uv", "run", "--no-project", *UV_ENV[eng], "python", "-I", "-W", "ignore"]
    res = run_guarded(
        [*cmd, str(WORKER), eng, f, str(dst)],
        timeout=timeout,
        mem_mb=mem_mb,
        cwd=out,  # not beside the corpus or the repo
        capture_stdout=False,
    )
    reason = res.killed
    if reason is None and res.returncode != 0:
        reason = (res.stderr.strip().splitlines() or ["exit"])[-1]
    if reason is not None:
        dst.unlink(missing_ok=True)
        dst.with_suffix(".fail").write_text(json.dumps({"file": f, "reason": reason[:300]}))


def _load_foreign(out: Path, eng: str, f: str) -> tuple[dict[Key, Any] | None, str | None]:
    dst = _cache(out, eng, f)
    if not dst.exists():
        fail = dst.with_suffix(".fail")
        return None, json.loads(fail.read_text())["reason"] if fail.exists() else "missing"
    vals: dict[Key, Any] = {}
    for k, v in json.loads(dst.read_text())["values"].items():
        s, c, r = k.split("\t")
        vals[(s, int(c), int(r))] = tuple(v) if isinstance(v, list) else v
    return vals, None


def _key(cell: str) -> Key:
    s, a = cell.rsplit("!", 1)
    m = re.match(r"([A-Z]+)(\d+)", a)
    if m is None:
        raise ValueError(cell)
    col = 0
    for ch in m.group(1):
        col = col * 26 + ord(ch) - 64
    return s, col - 1, int(m.group(2)) - 1


def score(job: tuple[str, Path, str, float, tuple[str, ...]]) -> dict[str, Any]:
    f, out, gridcraft, rel, foreign_engines = job
    rep = compare((Path(f), gridcraft, rel))
    res: dict[str, Any] = {"file": f, "cells": [], "fail": {}}
    if not rep.get("cells"):
        res["fail"]["all"] = rep.get("error") or "no cells"
        return res
    for side, field in (("gridcalc", "gridcalc_error"), ("gridcraft", "other_error")):
        if rep.get(field):
            res["fail"][side] = rep[field]
    foreign = {}
    for eng in foreign_engines:
        foreign[eng], err = _load_foreign(out, eng, f)
        if err:
            res["fail"][eng] = err
    for c in rep["cells"]:
        row = {
            "cell": c["cell"],
            "formula": c["formula"],
            "gridcalc": c["gridcalc_ok"],
            "gridcraft": c["other_ok"],
        }
        k = _key(c["cell"])
        for eng, vals in foreign.items():
            row[eng] = vals is not None and same(c["excel"], vals.get(k), rel)
        res["cells"].append(row)
    return res


def _rate(rep: dict[str, Any], eng: str) -> float:
    return sum(c[eng] for c in rep["cells"]) / len(rep["cells"])


def _block(title: str, reps: list[dict[str, Any]], engines: list[str]) -> list[str]:
    cells = [c for r in reps for c in r["cells"]]
    n = len(cells)
    lines = [f"{title}: {len(reps)} files, {n} cells"]
    if not n:
        return lines
    for e in engines:
        ok = sum(c[e] for c in cells)
        mean = sum(_rate(r, e) for r in reps) / len(reps)
        lines.append(f"   {e:10s} {ok:6d} ({ok / n:6.1%})   mean per file {mean:6.1%}")
    return lines


def render(reps: list[dict[str, Any]], limit: int, engines: list[str]) -> str:
    scored = [r for r in reps if r["cells"]]
    empty = [r for r in reps if not r["cells"] and r["fail"]["all"] == "no cells"]
    lines = [
        f"!! {Path(r['file']).name}: {r['fail']['all']}"
        for r in reps
        if not r["cells"] and r not in empty
    ]
    if empty:
        lines.append(f"{len(empty)} files have no formula with a saved value")
    lines += _block("all", scored, engines)
    for e in engines:
        fails = Counter(
            r["fail"][e].split(":")[0]
            if r["fail"][e].startswith(("timeout", "memory"))
            else "error"
            for r in scored
            if e in r["fail"]
        )
        if fails:
            lines.append(f"   {e} failed files: {dict(fails)}")
    lines += _block(
        "without " + ", ".join(LARGE),
        [r for r in scored if not r["file"].endswith(LARGE)],
        engines,
    )
    lines += _block("files every engine finished", [r for r in scored if not r["fail"]], engines)
    for e in engines[1:]:
        for won, title in (
            (False, "wrong where gridcalc is right"),
            (True, "right where gridcalc is wrong"),
        ):
            by: Counter[str] = Counter()
            for r in scored:
                for c in r["cells"]:
                    if c[e] == won and c["gridcalc"] != won:
                        by.update(functions(c["formula"]))
            lines.append(f"== {e} {title}, by function: {by.most_common(limit)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*")
    parser.add_argument("--list", type=Path, help="file with one workbook path per line")
    parser.add_argument(
        "--out", type=Path, required=True, help="cache for pycel and formulas results"
    )
    parser.add_argument(
        "--engine",
        default=os.environ.get("GRIDCRAFT_CLI") or shutil.which("gridcraft-cli"),
        help="GridCraft's CLI (default: $GRIDCRAFT_CLI, then gridcraft-cli on PATH)",
    )
    parser.add_argument("--timeout", type=float, default=300, help="seconds per file and engine")
    parser.add_argument("--json", type=Path, help="write per-cell results here")
    parser.add_argument("--rel", type=float, default=1e-9, help="relative number tolerance")
    parser.add_argument("--limit", type=int, default=12, help="functions listed per section")
    parser.add_argument(
        "--engines",
        default="pycel,formulas",
        help="foreign engines to run, comma-separated (default: pycel,formulas)",
    )
    parser.add_argument("--mem-mb", type=int, default=MEM_MB, help="memory cap per engine process")
    parser.add_argument("--jobs", type=int, help="parallel files (default: fits half of RAM)")
    args = parser.parse_args()
    if not args.engine:
        parser.error("no GridCraft: pass --engine or set GRIDCRAFT_CLI")
    files = [str(Path(p).resolve()) for p in args.files]
    if args.list:
        files += [str(Path(p).resolve()) for p in args.list.read_text().splitlines() if p.strip()]
    if not files:
        parser.error("no workbooks given")
    foreign = tuple(e for e in args.engines.split(",") if e)
    if bad := set(foreign) - set(UV_ENV):
        parser.error(f"unknown engines: {', '.join(sorted(bad))}")
    jobs = args.jobs or default_jobs(args.mem_mb)
    out = args.out.resolve()
    with ThreadPoolExecutor(jobs) as ex:
        list(
            ex.map(
                lambda j: run_foreign(*j, out, args.timeout, args.mem_mb),
                [(e, f) for e in foreign for f in files],
            )
        )
    # Scored after the foreign runs finish, so gridcalc's recalc limit is not
    # met under their load.
    with Pool(jobs) as pool:
        reps = pool.map(
            score, [(f, out, args.engine, args.rel, foreign) for f in files], chunksize=1
        )
    if args.json:
        args.json.write_text(json.dumps(reps))
    print(render(reps, args.limit, ["gridcalc", "gridcraft", *foreign]))


if __name__ == "__main__":
    main()
