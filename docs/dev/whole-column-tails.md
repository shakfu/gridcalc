# Whole-column arrays: the trimmed tail

`_eval_range` reads `B:B` over the used rows only. An array computed from it,
such as `(B:B="")*1`, records in `Vec.fill_to` the full shape and the one value
every left-out row holds (1 here). `_resolve_tails` in `formula/evaluator.py`
decides, per call, how a function sees those rows.

| Case | Functions | Handling |
|-|-|-|
| The rows cannot change the result | SUM over 0, SUMPRODUCT with a 0 factor, FILTER that drops them, an exact lookup whose value differs from the tail, CONCAT or TEXTJOIN over `""` | none |
| One copy gives the same result | MAX, MIN, MAXA, MINA, AND, OR | one element appended |
| The result combines per group | SUM, SUMSQ, PRODUCT, COUNT, COUNTA, AVERAGE, AVERAGEA, SUMPRODUCT, DEVSQ, VAR*, STDEV*, GEOMEAN, HARMEAN | the tail is `(value, count)` |
| Rank or distance from the mean | MEDIAN, MODE, AVEDEV, SKEW, SKEW.P, KURT | `(value, count)` pairs, `_weighted_stat` |
| Order statistic | LARGE, SMALL | `min(count, k)` copies |
| Text past 32767 characters | CONCAT, TEXTJOIN | `#CALC!`, as Excel |
| An error in the rows | most functions; COUNT skips it, COUNTA counts it, a lookup cannot match it | the error |
| Anything else | | padded to full size; over `MAX_ARRAY_CELLS` (one column), the used rows only |

Padding is correct but costs 0.3-0.4 s per million cells, so a function
earns a row above when it is common over whole columns.

A lazy tail on the padded Vec (data plus `(fill, n)`) was the alternative to
per-function rules. Library functions index and copy `.data`, so most would
materialise it anyway.

IF, IFERROR, IFNA and SWITCH carry the tail value through: `IF(B:B="",1,0)`
holds 1 on the left-out rows. An elementwise function lifted over trimmed
arrays does the same in `_lift_call`.

## Spill

A trimmed whole-row result is padded and spills in full (16384 cells). A
whole-column result keeps its full shape in `Cell.spill_full`: it gives
`#SPILL!` unless that whole rectangle fits on the sheet and is empty. Where it
fits, only the used rows are materialised. `Grid._spill_tails` records the
rest. An edit there, or another spill into it, re-checks the anchor, which then
gives `#SPILL!`; Excel 16.114 lets the other spill win in either order. Reading
those rows gives a blank, where Excel gives the tail value.
