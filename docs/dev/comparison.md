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

Rerun 2026-11-17 on the same machine (Apple M1, 16 GB, 73% of memory free): gridcalc 0.13.0 plus the unreleased changes, GridCraft 0.19.1, pycel 1.0b30, formulas 1.3.4. Two runs agreed within 3%; the table gives the second, and formulas the first.

| | load, small | per case, small | load, big | per case, big |
|-|-|-|-|-|
| gridcalc `Book.run_many` | 0.08 s | 4.0 ms | 0.34 s | 43.6 ms |
| gridcalc CLI `--inputs`, whole process / 20 | - | 11.0 ms | - | 67.2 ms |
| GridCraft, one process, cases in sequence | 0.03 s | 2.6 ms | 0.06 s | 25.3 ms |
| GridCraft, one process per case | - | 13.3 ms | - | 81.4 ms |
| pycel `set_value` / `evaluate` | 0.46 s | 7.2 ms | 2.73 s | 83.8 ms |
| formulas `compile`, then call | 26.7 s | 164 ms | 10.5 s | 1,837 ms |

Each GridCraft case sets every input, so it needs no reset between cases. Whether `--script` can reset is not checked.

- On `big`, GridCraft computes a case 1.7x faster than gridcalc. On 2026-11-05 it was 6.6x: 26.2 ms against 173 ms. The gain is gridcalc's (`docs/dev/261110-perf.md`); GridCraft is within 1 ms of its old figure.
- gridcalc is now 1.9x faster than pycel per case on `big`. pycel was 1.4x faster.
- `Book.run_many(..., workers=4)` on `big`, 400 cases: 12.2 ms per case of throughput, 2.1x GridCraft's rate in one process. 1, 2 and 8 workers: 40.8, 22.1 and 10.4 ms. Outputs are identical at every count.
- formulas' small-model load (26.7 s) is longer than its big one (10.5 s). It likely includes building its `uv` environment on first use; not checked.
- The first run gave the gridcalc CLI 33.2 ms on `small`, against 11.0 ms in the second, probably a cold start.

Earlier figures, 2026-11-05 (gridcalc 0.11.0, GridCraft 0.5.0): gridcalc `run_many` 8.0 and 173 ms, CLI 20.8 and 160 ms, GridCraft 2.9 and 26.2 ms, GridCraft per process 14.8 and 78.2 ms, pycel 15.2 and 126 ms, formulas 219 and 3,352 ms, per case on `small` and `big`. A run under memory pressure was 4-8x slower for every engine.

## Agreement on untuned workbooks

Run 2026-11-09 on 306 Sheetpedia files (`tianzl66/Sheetpedia_xlsx`, CC-BY-SA-4.0) that no fix was tuned on. openpyxl had re-saved them without values, so Excel for Mac 16.114 recalculated and saved each one, with external links not updated. The sample is 400 random files with at least 10 formulas and under 3 MB, plus 100 Enron files (seed 1). Excel saved 307 of the first 327 before the run stopped. It refused to open 22, and 4 timed out. 275 of the 306 scored are forum attachments, 18 Enron files and 13 of unknown origin, so financial models are few.

| | gridcalc | GridCraft |
|-|-|-|
| cells agreeing, 226,621 | 96.5% | 96.8% |
| mean per file | 91.2% | 93.2% |
| files higher | 23 | 42 |
| files with every cell right | 236 | |

gridcalc's total varies by about 2,000 cells between runs (96.2-97.1%). One file stops at the 30 s recalc limit, and how far it gets depends on load.

Root mismatches by cause:

| Cause | Root cells | Files |
|-|-|-|
| References into another workbook. Excel reads the values cached in `xl/externalLinks`; gridcalc does not. 60 of the 306 files have links. | 2,066 | 16 |
| 30 s recalc limit: 7,676 `AGGREGATE` formulas over 10,000 rows (first guessed as `COUNTIFS`); 232 s without the limit | about 2,400 | 1 |
| Single-cell legacy array formulas (`SMALL(IF(...))`) give `#SPILL!` or 0. 79 files hold array formulas. | 544 | 22 |
| `#VALUE!` from date-time text (`"06/24/2022 00:00"`, `"2-5-2024"*1`), `LET`/`BYROW`/`SCAN` | 839 | 15 |
| Exact `VLOOKUP` of a blank matches a blank cell; Excel gives `#N/A` | 60 | 1 |
| `TEXT` of serials 1-60 and of `"hh"` | about 70 | 3 |
| `IF` without a false branch gives 0, not FALSE | 18 | 2 |
| `RAND`, `NOW`; `CHAR` on Mac uses Mac Roman | 84 | 12 |

11 files set `iterate="1"`. 61% of their 1,281 cells agree; with iterative calculation, 94.9% (`iteration.md`).

Two harness bugs inflated the first count: openpyxl reads a `[h]:mm` value as a `timedelta`, and rounds every date and time to the millisecond (CHANGELOG).

The `IF`, `TEXT` and blank-lookup fixes (CHANGELOG) raised agreement from 97.15% to 97.64% of the 223,000 cells outside the time-limit file. About 395 of the 1,074-cell gain is `RANDBETWEEN` noise in one file. Part of the legacy-array count above was the `IF` bug: `SMALL(IF(..))` ranked the zeros an omitted false branch gave. The IronCalc and pycel corpus (282 files) went from 98.97% to 99.04%.

After the `IF` fix, 78 root mismatches remain in array formulas, in 13 files. Most are not about array semantics: `OFFSET` with array arguments, `LET` and `FILTER`, external references. openpyxl drops the dynamic-array flag (`cm`), so Excel re-saved every Sheetpedia array formula as a legacy one. Fitting a legacy formula's result to its range (CHANGELOG) fixed 2 cells here and 4 in the IronCalc and pycel corpus.

Using Excel's saved value for every formula that reads another workbook (CHANGELOG) raised agreement outside the time-limit file from 97.64% to 99.07%. About 2,066 of the 3,184 cells gained are the link formulas, which now match by construction; the rest read them.

Reading date-time text (CHANGELOG) raised it to 99.44%.
