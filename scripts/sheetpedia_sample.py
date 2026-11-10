"""Draw a repeatable sample of formula-bearing workbooks from a Sheetpedia tree.

    uv run python scripts/sheetpedia_sample.py DIR --n 400 --out sample.txt
    uv run python scripts/sheetpedia_sample.py DIR --n 100 --glob '*__*.xlsx' --out enron.txt

DIR is the extracted `pii_processed_xlsx_0929` folder of `tianzl66/Sheetpedia_xlsx`
(Hugging Face, CC-BY-SA-4.0). Enron files are the ones named `owner__id__title.xlsx`.
Results: `docs/dev/comparison.md`.
"""

from __future__ import annotations

import argparse
import random
import re
import zipfile
from pathlib import Path

_FORMULA = re.compile(rb"<(?:\w+:)?f[ >/]")


def formula_count(path: Path) -> int:
    """Formula cells in the workbook's sheet parts, or -1 if it is not a readable zip."""
    try:
        with zipfile.ZipFile(path) as z:
            return sum(
                len(_FORMULA.findall(z.read(n)))
                for n in z.namelist()
                if n.startswith("xl/worksheets/sheet")
            )
    except (OSError, zipfile.BadZipFile, KeyError):
        return -1


def sample(
    root: Path,
    n: int,
    pattern: str = "*.xlsx",
    seed: int = 1,
    min_formulas: int = 10,
    max_bytes: int = 3_000_000,
) -> list[Path]:
    """The first ``n`` files, in a seeded shuffle, with enough formulas and under ``max_bytes``."""
    files = sorted(root.glob(pattern))
    random.Random(seed).shuffle(files)  # noqa: S311 -- a repeatable sample
    out: list[Path] = []
    for f in files:
        if f.stat().st_size <= max_bytes and formula_count(f) >= min_formulas:
            out.append(f)
            if len(out) == n:
                break
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root", type=Path)
    p.add_argument("--n", type=int, default=400)
    p.add_argument("--glob", default="*.xlsx", help="file pattern (Enron: '*__*.xlsx')")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--min-formulas", type=int, default=10)
    p.add_argument("--max-bytes", type=int, default=3_000_000)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    files = sample(a.root, a.n, a.glob, a.seed, a.min_formulas, a.max_bytes)
    a.out.write_text("".join(f"{f.resolve()}\n" for f in files))
    print(f"{len(files)} files -> {a.out}")


if __name__ == "__main__":
    main()
