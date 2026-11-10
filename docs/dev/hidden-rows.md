# Hidden and filtered rows: how Excel does it

Measured 2026-11-10 in Excel for Mac 16.114 on `tests/xlsx/hidden_input.xlsx` (`scripts/build_hidden_model.py`), recalculated and saved as `hidden_excel.xlsx`. Each of its five sheets hides rows 3, 5 and 9 of A2:A9, which hold 1, 2, 4, ..., 64 and `#N/A`.

| Sheet: what hid the rows | `SUBTOTAL(9,A2:A8)` | `SUBTOTAL(109,A2:A8)` | `SUBTOTAL(9,A2:A9)` |
|-|-|-|-|
| hidden by hand | 127 | 117 | `#N/A` |
| sheet `autoFilter` with a `filterColumn` | 117 | 117 | 117 |
| sheet `autoFilter`, no criterion | 127 | 117 | `#N/A` |
| table filter with a `filterColumn` | 117 | 117 | 117 |
| table, no criterion | 127 | 117 | `#N/A` |

Rules:
- xlsx marks every hidden row `hidden="1"`. A hidden row counts as filtered when it is under an `autoFilter` (the sheet's or a table's) that has a criterion.
- `SUBTOTAL` 1-11 skip filtered rows, and 101-111 skip every hidden row. A skipped row's error is skipped too.
- `AGGREGATE` options 1, 3, 5 and 7 skip every hidden row, in the reference form and in the array form over a reference. `AGGREGATE(15,5,A2:A8*1,2)` gives 2: a computed array has no rows to hide.
- Hidden columns are never skipped: `SUBTOTAL(109,E1:G1)` across a hidden F gives 111.

gridcalc saves hidden rows and the sheet's `autoFilter` back to xlsx. Excel recalculated gridcalc's save of the input to the same 95 values.

## Corpus

IronCalc's `tables.xlsx` went from 173 to 211 of 212 cells. On the 282-file IronCalc and pycel corpus, 78,904 rose to 78,942 of 79,661 cells, with no other file changed. Sheetpedia `5eaad2a5` (a table filter) went to 34 of 34.
