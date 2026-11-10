"""Group gridcalc's root mismatches against Excel's saved values by cause.

    uv run python scripts/excel_gaps.py --list saved.txt --json gaps.json
    uv run python scripts/excel_gaps.py --from-json gaps.json --show "gridcalc #VALUE!"

Each workbook is scored by `excel_corpus.compare`. A root mismatch reads no
other wrong cell. Causes are guessed from the formula text and the two
values. Results: `docs/dev/remaining-gaps.md`.
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from excel_corpus import compare

_VOLATILE = re.compile(r"\b(RAND|RANDBETWEEN|RANDARRAY|NOW)\(", re.IGNORECASE)
_EXTERNAL = re.compile(r"\[\d+\]")


def _kind(v: Any) -> str:
    if isinstance(v, (list, tuple)) and len(v) == 2 and v[0] == "error":
        return str(v[1])
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    return "none" if v is None else "text"


def cause(formula: str, excel: Any, got: Any) -> str:
    """A short label for why one root mismatch differs."""
    f, e, g = formula.upper(), _kind(excel), _kind(got)
    if _VOLATILE.search(f):
        return "volatile RAND/NOW"
    if _EXTERNAL.search(f):
        return "external workbook ref"
    if "CHAR(" in f or "CODE(" in f:
        return "CHAR/CODE (Mac charset)"
    if g in ("#CALC!", "#SPILL!", "#NAME?", "#CIRC!", "#REF!", "#VALUE!", "#N/A") and g != e:
        return f"gridcalc {g}"
    if g == e == "num":
        r = abs(excel - got) / max(abs(excel), abs(got), 1e-300)
        return "number, rel diff < 1e-6" if r < 1e-6 else "number, wrong"
    return f"excel {e}, gridcalc {g}"


def _job(path: str) -> dict[str, Any]:
    rep = compare(Path(path))
    try:
        with zipfile.ZipFile(path) as z:
            wb = z.read("xl/workbook.xml").decode("utf-8", "replace")
            rep["external_links"] = any(n.startswith("xl/externalLinks/") for n in z.namelist())
            rep["iterate"] = bool(re.search(r'iterate="(1|true)"', wb))
    except (OSError, KeyError, zipfile.BadZipFile):
        pass
    return rep


def render(reps: list[dict[str, Any]], show: list[str]) -> str:
    scored = [r for r in reps if r.get("compared")]
    n = sum(r["compared"] for r in scored)
    ok = sum(r["agree"] for r in scored)
    lines = [
        f"{len(scored)} files, {n} cells, {n - ok} wrong, "
        f"{sum(r['agree'] < r['compared'] for r in scored)} files with a wrong cell"
    ]
    cells: Counter[str] = Counter()
    files: defaultdict[str, set[str]] = defaultdict(set)
    examples: defaultdict[str, list[str]] = defaultdict(list)
    for r in scored:
        for x in r["roots"]:
            c = cause(x["formula"], x["excel"], x["gridcalc"])
            cells[c] += 1
            if r["file"] not in files[c]:
                examples[c].append(
                    f"  {Path(r['file']).name} {x['cell']}: {x['formula'][:90]!r} "
                    f"excel={str(x['excel'])[:30]} gridcalc={str(x['gridcalc'])[:30]}"
                )
            files[c].add(r["file"])
    lines.append(f"root mismatches: {sum(cells.values())}")
    lines += [f"{k:6d} {len(files[c]):4d} files  {c}" for c, k in cells.most_common()]
    for c in show:
        lines += [f"## {c}", *examples.get(c, [])]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("files", nargs="*")
    p.add_argument("--list", type=Path, help="one workbook path per line")
    p.add_argument("--json", type=Path, help="write the per-file reports here")
    p.add_argument("--from-json", type=Path, help="regroup reports written by --json")
    p.add_argument("--show", action="append", default=[], help="list one example per file")
    p.add_argument("--jobs", type=int, default=6)
    a = p.parse_args()
    if a.from_json:
        reps = json.loads(a.from_json.read_text())
    else:
        files = list(a.files) + [
            s for s in (a.list.read_text().splitlines() if a.list else []) if s.strip()
        ]
        if not files:
            p.error("no workbooks given")
        with Pool(a.jobs) as pool:
            reps = pool.map(_job, files, chunksize=1)
        if a.json:
            a.json.write_text(json.dumps(reps, default=str))
    print(render(reps, a.show))


if __name__ == "__main__":
    main()
