# Engine comparison

gridcalc against three other engines that calculate an xlsx file without Excel: GridCraft, pycel and formulas. Two questions:

1. How often does each engine agree with the values Excel saved?
2. Can each run a workbook as a function of its defined names, and how fast?

Run 2026-11-07 on macOS arm64, 8 cores.

| Engine | Version | Notes |
|-|-|-|
| gridcalc | main after `8891b64`, with the sparse-range fix (CHANGELOG) | |
| GridCraft | 0.5.0 `gridcraft-cli` | closed source, Rust |
| pycel | 1.0b30 | needs Python 3.11 (it uses `ast.Str`) and openpyxl 3.0.10 (it reads defined names through an API openpyxl 3.1 removed) |
| formulas | 1.3.4 | Python 3.14 |

```sh
uv run python scripts/engine_compare.py --list files.txt --out /tmp/compare --engine path/to/gridcraft-cli
uv run python scripts/named_io_bench.py --out /tmp/nio --engine path/to/gridcraft-cli
```

`engine_compare.py` starts pycel and formulas through `foreign_engine.py`, one process per file, each in its own `uv` environment.

## Named inputs and outputs

| | Set an input by name | Read an output by name | Error in an output | Text input starting with `=` |
|-|-|-|-|-|
| gridcalc | `--set Rate=0.04`, `Book.run` | `--get Payment` | exit 2 | stays text |
| GridCraft | no: `cell.set` ignores the name and writes the active cell, exit 0 | `formulas.evaluate={"formula":"=Payment"}`; `--print Payment` is refused | exit 0 | becomes a formula |
| pycel | no: addresses only | no: resolve `excel.defined_names` by hand | returned as a value | not tested |
| formulas | `compile(inputs=["'[book.xlsx]'!RATE"])` | same form in `outputs` | returned as a value | not tested |

The book part of a formulas key is case-sensitive: `'[book.xlsx]'!RATE` works and `'[BOOK.XLSX]'!RATE` is unreachable.

GridCraft's `cell.set` fails silently. Given `"cell": "Rate"` or `"cell": "Bogus"`, it writes the active cell and reports success. A misspelled input name therefore overwrites whichever cell is selected.

Prior art outside these four, not tested here:

- SharePoint Excel Services published named cells as parameters, set through its REST and SOAP APIs.
- Coherent Spark exposes a workbook as an API and marks I/O names by prefix (`Xi_`, `Xo_`). This comes from memory, not from its documentation.
- SpreadsheetGear, Aspose.Cells and GcExcel resolve `Names["X"]`. The caller writes the I/O contract.

## Agreement with Excel

The 279 IronCalc and pycel test workbooks (`excel-corpus.md`). The cell set is `engine_diff.py`'s: formula cells with a saved value that gridcalc imports as formulas. Each foreign engine has 300 s per file. A file an engine fails on scores 0 for that engine.

| | gridcalc | GridCraft | pycel | formulas |
|-|-|-|-|-|
| cells agreeing, 79,598 | 78,795 (99.0%) | 76,500 (96.1%) | 22,241 (27.9%) | 60,416 (75.9%) |
| mean per file, 268 files | 92.8% | 93.5% | 40.6% | 69.5% |
| cells, without `ARABIC_ROMAN` and `FLOOR_CEILING` (27,752) | 97.1% | 92.7% | 48.4% | 72.2% |
| cells, 256 files every engine finished (65,626) | 98.9% | 97.2% | 18.9% | 92.1% |
| files failed | 0 | 0 | 1 timeout | 8 timeouts, 4 errors |

- **pycel** returns a formula's cached value until an input changes. Setting every cached `<v>` to 12345 returned 12345 for every cell, so a naive run scores Excel against itself (98.8%). `foreign_engine.py` calls `ExcelCompiler.recalculate()`, and the same tamper test then returns no 12345. After that, 53,151 cells raise `UnknownFunction`, mostly `ROMAN` and `ARABIC`.
- **formulas** times out on `FLOOR_CEILING.xlsx` (11,460 cells), `COUNTIF.xlsx` and 6 others. It scores 92.1% on the files it finishes.
- **GridCraft** scores higher per file. gridcalc scores higher per cell, and higher still once the two large files are excluded. The functions behind each side's misses are printed by `engine_compare.py`; GridCraft's are listed in `excel-corpus.md`.
- **gridcalc** scored 78,695 on one earlier run that day. `INDIRECT.xlsx` took 30-36 s and sometimes stopped at the 30 s recalc limit. The sparse-range fix (CHANGELOG) brought it to 1.7 s.

## Time per named-I/O case

`named_io_bench.py` builds an amortization model with named inputs `Rate` and `Principal` and named outputs `Payment`, `TotalInterest` and `EndBalance`. `small` is one 360-row block (1,806 formulas). `big` is ten blocks (18,033). Each case changes both inputs, so every formula recalculates. There are 20 cases. The payment uses a closed form, because pycel has no `PMT`. Every engine matches gridcalc's outputs within 1e-15 relative.

| | load, small | per case, small | load, big | per case, big |
|-|-|-|-|-|
| gridcalc `Book.run_many` | 0.07 s | 8.0 ms | 0.59 s | 173 ms |
| gridcalc CLI `--inputs`, whole process / 20 | - | 20.8 ms | - | 160 ms |
| GridCraft, one process, cases in sequence | 0.01 s | 2.9 ms | 0.08 s | 26.2 ms |
| GridCraft, one process per case | - | 14.8 ms | - | 78.2 ms |
| pycel `set_value` / `evaluate` | 0.75 s | 15.2 ms | 5.3 s | 126 ms |
| formulas `compile`, then call | 2.7 s | 219 ms | 21.0 s | 3,352 ms |

Each GridCraft case sets every input, so it needs no reset between cases. Whether `--script` can reset is not checked. On `big`, GridCraft computes a case 6.6x faster than gridcalc, and pycel 1.4x faster. One process per case, with its own load, GridCraft is still 2.2x faster than gridcalc's in-process batch.

The timings vary by run. A run under memory pressure was 4-8x slower for every engine. An earlier run the same day gave gridcalc 182 ms and GridCraft 32.6 ms per case on `big`.
