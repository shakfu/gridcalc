"""Survey real xlsx files: does gridcalc load them, and does a save keep them?

`excel_corpus.py` checks results against the values Excel saved, so it needs
files Excel saved. This needs only the files. For each it reports:

- whether it loads, and how long that takes;
- formulas that do not parse, and functions gridcalc lacks (`#NAME?`);
- what saving over it would drop (`loader.xlsx_extras`);
- what an xlsx save and reload changes: cell text, styles, merges, names.

    uv run python scripts/xlsx_survey.py --json out.json path/to/*.xlsx
    uv run python scripts/xlsx_survey.py --list files.txt --sample 2000
"""

from __future__ import annotations

import argparse
import collections
import json
import multiprocessing
import random
import re
import signal
import tempfile
import time
from pathlib import Path
from typing import Any

_CALL_RE = re.compile(r"\b([A-Z][A-Z0-9.]*)\(")
_TIMEOUT = 60


class _Timeout(Exception):
    pass


def _alarm(_sig: int, _frame: Any) -> None:
    raise _Timeout


def _known() -> set[str]:
    from gridcalc.engine import _make_eval_globals
    from gridcalc.libs.xlsx import BUILTINS

    return set(BUILTINS) | {k.upper() for k in _make_eval_globals()} | {"LET", "LAMBDA"}


def _snapshot(g: Any) -> dict[str, Any]:
    """What a save should keep, per sheet, in comparable form."""
    out: dict[str, Any] = {}
    for sh in g.sheets:
        cells = {}
        for pos, cl in sh._cells.items():
            if cl.type == 4:  # SPILL: rebuilt from its anchor
                continue
            cells[pos] = (
                cl.text,
                bool(cl.bold),
                bool(cl.italic),
                bool(cl.underline),
                cl.fmtstr,
                cl.xstyle,
            )
        out[sh.name] = (cells, sorted(sh.merges), dict(sh.heights))
    out["#names"] = sorted((n.name, n.sheet, n.c1, n.r1, n.c2, n.r2, n.formula) for n in g.names)
    return out


def survey(path: str) -> dict[str, Any]:
    from gridcalc.engine import FORMULA
    from gridcalc.loader import load_workbook, save_workbook, xlsx_extras

    rep: dict[str, Any] = {"file": path}
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(_TIMEOUT)
    try:
        t = time.perf_counter()
        g = load_workbook(path)
        rep["load_s"] = round(time.perf_counter() - t, 3)
        rep["warnings"] = list(g.load_warnings)
        known = _known() | {n.name.upper() for n in g.names}
        formulas = syntax = name_err = 0
        syntax_kinds: collections.Counter[str] = collections.Counter()
        syntax_samples: dict[str, str] = {}
        missing: collections.Counter[str] = collections.Counter()
        for sh in g.sheets:
            for cl in sh._cells.values():
                if cl.type != FORMULA:
                    continue
                formulas += 1
                msg = cl.err_msg or ""
                if msg.startswith("syntax error"):
                    syntax += 1
                    kind = _syntax_kind(cl.text, msg)
                    syntax_kinds[kind] += 1
                    syntax_samples.setdefault(kind, cl.text[:120])
                elif cl.err is not None and cl.err.value == "#NAME?":
                    name_err += 1
                    for fn in set(_CALL_RE.findall(cl.text.upper())):
                        if fn not in known:
                            missing[fn] += 1
        rep.update(
            formulas=formulas,
            syntax_errors=syntax,
            syntax_kinds=dict(syntax_kinds),
            syntax_samples=syntax_samples,
            name_errors=name_err,
            missing_functions=dict(missing),
            extras=xlsx_extras(path),
            sheets=len(g.sheets),
            cells=sum(len(s._cells) for s in g.sheets),
        )
        before = _snapshot(g)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "rt.xlsx"
            try:
                save_workbook(g, out)
                rt = load_workbook(out)
            except Exception as exc:  # noqa: BLE001 -- the failure is the finding
                rep["save_error"] = f"{type(exc).__name__}: {exc}"
            else:
                rep["roundtrip"] = _diff(before, _snapshot(rt))
    except _Timeout:
        rep["error"] = f"timeout after {_TIMEOUT} s"
    except Exception as exc:  # noqa: BLE001 -- one bad file must not stop the run
        rep["error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        signal.alarm(0)
    return rep


def _syntax_kind(text: str, msg: str) -> str:
    """A short class for an unparseable formula."""
    if re.search(r"\w\[|\[#", text):
        return "structured reference (Table[col])"
    if "[" in text and "]" in text:
        return "external workbook reference ([1]Sheet!A1)"
    if re.search(r"\w!\w+\s*:\s*\w+!", text):
        return "cross-sheet range"
    if re.search(r"\)\s*:\s*\w|\w\s*:\s*[A-Z]+\(", text):
        return "range operator with a function (A1:INDEX(...))"
    if re.search(r"\s[A-Z$]+\$?\d+\s", text) and " " in text.strip("= "):
        return "possible intersection operator (space)"
    return msg.split(":", 1)[-1].strip()[:40]


def _diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, int]:
    """Counts of what changed between two snapshots."""
    out: collections.Counter[str] = collections.Counter()
    if a["#names"] != b["#names"]:
        out["names"] += 1
    for sheet, entry in a.items():
        if sheet == "#names":
            continue
        cells, merges, heights = entry
        if sheet not in b:
            out["sheet lost"] += 1
            continue
        bcells, bmerges, bheights = b[sheet]
        out["merges"] += merges != bmerges
        out["row heights"] += heights != bheights
        for pos, v in cells.items():
            w = bcells.get(pos)
            if w is None:
                out["cell lost"] += 1
                continue
            for i, field in enumerate(("text", "bold", "italic", "underline", "fmtstr", "xstyle")):
                if v[i] != w[i]:
                    out[field] += 1
        out["cell added"] += len(set(bcells) - set(cells))
    return {k: v for k, v in out.items() if v}


def summarise(reports: list[dict[str, Any]]) -> str:
    n = len(reports)
    ok = [r for r in reports if "error" not in r]
    lines = [f"{n} files; {len(ok)} loaded, {n - len(ok)} failed"]
    errs = collections.Counter(r["error"].split(":")[0] for r in reports if "error" in r)
    lines += [f"   {c:5d}  {e}" for e, c in errs.most_common(10)]
    with_f = [r for r in ok if r["formulas"]]
    tf = sum(r["formulas"] for r in ok)
    lines.append(
        f"{len(with_f)} with formulas; {tf} formulas, "
        f"{sum(r['syntax_errors'] for r in ok)} unparseable, "
        f"{sum(r['name_errors'] for r in ok)} #NAME?"
    )
    for title, key in (
        ("unparseable, by kind", "syntax_kinds"),
        ("missing functions", "missing_functions"),
    ):
        files: collections.Counter[str] = collections.Counter()
        cells: collections.Counter[str] = collections.Counter()
        for r in ok:
            for k, v in r[key].items():
                files[k] += 1
                cells[k] += v
        lines.append(f"== {title} (files, cells)")
        lines += [f"   {files[k]:5d} {cells[k]:7d}  {k}" for k, _ in files.most_common(25)]
    extras: collections.Counter[str] = collections.Counter(e for r in ok for e in r["extras"])
    lines.append("== a save would drop (files)")
    lines += [f"   {c:5d}  {e}" for e, c in extras.most_common()]
    rt: collections.Counter[str] = collections.Counter()
    rt_cells: collections.Counter[str] = collections.Counter()
    for r in ok:
        for k, v in r.get("roundtrip", {}).items():
            rt[k] += 1
            rt_cells[k] += v
    saves = collections.Counter(r["save_error"].split(":")[0] for r in ok if "save_error" in r)
    same = sum(1 for r in ok if not r.get("roundtrip") and "save_error" not in r)
    lines.append(f"== xlsx round trip: {same} unchanged")
    lines += [f"   {rt[k]:5d} {rt_cells[k]:7d}  {k}" for k, _ in rt.most_common()]
    lines += [f"   {c:5d}  save failed: {e}" for e, c in saves.most_common()]
    slow = sorted((r["load_s"], r["file"]) for r in ok)[-3:]
    lines.append("slowest loads: " + ", ".join(f"{s}s" for s, _ in slow))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*")
    parser.add_argument("--list", type=Path, help="a file naming one xlsx per line")
    parser.add_argument("--sample", type=int, help="survey this many, chosen at random (seed 1)")
    parser.add_argument("--json", type=Path, help="write every report here")
    parser.add_argument("--jobs", type=int, default=multiprocessing.cpu_count())
    args = parser.parse_args()
    files = list(args.files)
    if args.list:
        files += [line.strip() for line in args.list.read_text().splitlines() if line.strip()]
    if args.sample and args.sample < len(files):
        files = random.Random(1).sample(files, args.sample)  # noqa: S311 -- a repeatable sample
    with multiprocessing.Pool(args.jobs, maxtasksperchild=50) as pool:
        reports = list(pool.imap_unordered(survey, files, chunksize=4))
    if args.json:
        args.json.write_text(json.dumps(reports, indent=1, default=str))
    print(summarise(reports))


if __name__ == "__main__":
    main()
