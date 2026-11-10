# Iterative calculation: how Excel does it

Measured 2026-11-10 in Excel for Mac 16.114 through AppleScript: formulas entered in a new workbook, calculation manual, one `calculate`, then values read back. Maximum iterations 50, maximum change 1e-4. `tests/test_iterate.py` checks gridcalc against each result.

| Probe | Excel | Rule |
|-|-|-|
| `B1: =B1+1` | 50 per calculation; 200 after four | A sweep runs every cell once. Every recalculation sweeps every cycle again, even if no input changed. |
| `B2: =COS(B2)` alone | 0.739054790747 | Stop at the first sweep where no cell changes by more than the maximum change. |
| `B2` with `B1: =B1+1` in the same workbook | 0.739085133922, the 51st iterate | The stop is over all cycles together; one cycle that keeps moving keeps all of them going. |
| `B5: =0.5*B5+1`, `C5: =1e6*B5` | B5 = 2 - 2^-34 | A cell that only reads a cycle counts toward the stop. B5 alone stops near 2 - 2^-14. |
| `C3`, `B3` entered in that order | B3 before C3 | Sweep order is by position, not entry order. |
| `C7`, `B8` | C7 before B8 | Row-major. |
| `Sheet2!A1`, `Sheet1!B2` | Sheet1 first | Sheets in workbook order. |
| `B1:C1` cycle reading the `B5:C5` cycle; `D1: =C5*1000` | Matches row-major only | Order ignores dependencies: a reader above a cycle sees the previous sweep. |

A cycle starts from the cells' current values. Entering a formula evaluates it once, so a typed probe starts one step in. On open, the start is the saved value. openpyxl saves a formula as `<v />`, which Excel reads as `""`, so `=B1+1` gives `#VALUE!` and keeps it. `scripts/build_iterate_model.py` saves 0 instead.

Saving through AppleScript recalculates more than once: open-and-save gave 100 sweeps, and `calculate full rebuild` then save gave 150, with or without `fullCalcOnLoad`. The fixture test reads the count from its `=B1+1` cell and recalculates gridcalc that many times; all 24 formulas then match to 0 relative difference.

## Corpus

On the 11 Sheetpedia files that set `iterate="1"` (`comparison.md`), agreement went from 798 to 1,216 of 1,281 cells. One file, `5440aefe`, went from 2 to 410 of 410. The 65 cells still wrong are `RANDBETWEEN` (two files), a `SUBTOTAL` over hidden rows, and one file with no saved values.

The Damodaran models that motivated this were not re-run; they are not in the working tree.
