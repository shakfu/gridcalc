# gridcalc vs. IronCalc: differential results

Status: **triaged, 2026-09-28.** Crash and semantic fixes shipped (CHANGELOG, Unreleased); two gridcalc items remain open.

`scripts/diff_ironcalc.py` evaluates the same formulas in both engines. Neither is ground truth. A disagreement marks a candidate bug; the verdicts below come from Excel's documented behaviour, or are marked *(inference)* where that is not established. No verdict was checked in Excel itself.

## Corpus

- **calls**: 431 gridcalc function names x 35 argument patterns over a fixed grid, 15,085 formulas. Numbers, text, fractions, date serials and signed integers in A:E.
- **fixtures**: 48 formula cells from `tests/xlsx/*.xlsx` and `examples/*.xlsx`. The fixtures come from openpyxl, so no file carries Excel-computed values.

Each formula runs in a worker subprocess. The parent kills it past 2 GB RSS or 30 s and records a crash. Both engines share one worker, so memory one engine leaves allocated counts against the other.

## Results

| Class | Formulas | Meaning |
|-|-|-|
| agree | 2,366 | Same value |
| agree-error | 1,285 | Same error |
| error-kind | 9,973 | Different errors. 7,822 are IronCalc `#ERROR!` (wrong argument count, which Excel rejects at entry) and 986 are `#N/IMPL!` |
| ironcalc-error | 586 | Only IronCalc errors |
| ironcalc-unsupported | 412 | IronCalc `#NAME?`: gridcalc extensions (`AVG`, `LOG2`, `FSUM`, ...) |
| gridcalc-error | 349 | Only gridcalc errors |
| value | 80 | Both values, different |
| ironcalc-crash | 19 | Rust panic, or over the memory limit. 2 were gridcalc's memory, counted against the shared worker |
| gridcalc-crash | 15 | Exception out of `setcell`, or over the memory limit |

Excluding arity, `#N/IMPL!` and `#NAME?`, 1,472 disagreements across 296 functions remain. After the crash fixes, a rerun gives 0 gridcalc crashes and 17 IronCalc panics.

## gridcalc: fixed

- `FACT`, `COMBINA`, `PERMUTATIONA`, `MULTINOMIAL` raised `OverflowError` out of `setcell`.
- `SEQUENCE(45292, 45416)` exhausted memory.
- `=VEC(A1:A10, 2)` crashed the spill code: formulas could call the `Vec` class.

## gridcalc: semantic fixes

All 16 items from the first triage are fixed (CHANGELOG, Unreleased). A third run, after the fixes:

| Class | First run | After |
|-|-|-|
| agree | 2,366 | 2,640 |
| agree-error | 1,285 | 1,798 |
| value | 80 | 38 |
| gridcalc-error | 349 | 119 |
| ironcalc-error | 586 | 1,062 |

`ironcalc-error` grew because gridcalc now lifts over arrays and IronCalc does not. 43 formulas that agreed in the first run disagree now. Each follows an intended change: lifting (`LOOKUP`, `MATCH`, `XLOOKUP`, `COUNTIF` over array criteria), typed text as `#VALUE!` (`AND`, `SUMSQ`, `PERCENTILE`), typed logicals counted (`SUMSQ`).

The fixes exposed four latent gridcalc bugs, also fixed:

- `HEX2DEC(-4)` gave -4: `int("-4", 16)` accepts a sign. The old `"-4.0"` failed only by accident.
- `FILTER` ignored an `include` of the wrong length and took text in it as TRUE.
- `SORT` ignored an invalid `sort_order`, and a 1D `sort_index`.
- `TOCOL`/`TOROW` accepted any `ignore`.

## gridcalc: still open

- **`EOMONTH` into February 1900** gives 59; Excel likely gives 60, the phantom 1900-02-29 *(inference)*.
- **`ISFORMULA(range)`** does not lift. It takes raw references, outside the lifting path.

## IronCalc: candidate upstream reports

1. **Panics** (index out of bounds): `SUBSTITUTE` with 2 arguments (`base/src/functions/text/common.rs:1104`) and `XNPV` with 2 arguments (`base/src/functions/financial/mod.rs:936`).
2. **1900 date system.** `DAY(3)` gives 2, and `EDATE` and `YEARFRAC` are one day off near the start of 1900. Excel serial 3 is 1900-01-03.
3. **Typed logicals ignored** by `STDEV`, `VAR`, `AVEDEV`, `DEVSQ`, `SKEW.P`. Excel's documentation counts them.
4. **`MINA` ignores text in references.** Excel counts it as 0.
5. **`ISNUMBER(A1:A10)`** gives FALSE; no lifting.
6. **`DATE(3, 1, 4)`** gives `#NUM!`. Excel adds 1900 to years below 1900.
7. **`WEEKDAY`, `YEAR`, `MONTH`, `DAY` of a serial below 1** give `#NUM!`. Excel accepts serial 0.
8. **`COUNTIF`/`SUMIF` over a one-cell range** give `#VALUE!`.
9. **`LARGE(3, 1)`** gives `#NUM!`.
10. **`IM*` functions** return `"inf"` and `"NaNNaNi"` as text.
11. **`#N/IMPL!`** for 238 functions under some argument shape, including `ROUND`, `LEN`, `VLOOKUP`. No function gives it for every pattern, so it is an argument-shape gap *(inference)*.

## Unresolved

`MOD(3, 0.1)` float residue; `IMSQRT(-4)` exact vs polar; `FREQUENCY` with unsorted bins; `OR`/`XOR` with a text literal; `MATCH` approximate over unsorted data; `DAYS` with fractional serials; `TEXT(3, 1)`; `=sales - targets` over named ranges (gridcalc spills, IronCalc applies implicit intersection).

Settling these needs Excel-computed values: an xlsx saved by Excel with its cached results, read back by both engines.
