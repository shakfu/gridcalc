# Fix: preserve text/bool through range materialization

## Root cause

`formula/evaluator.py:_eval_range` calls `_to_number_or_zero(v)` on every
cell, flattening text/bool to `0`. `Vec` was originally typed
`list[float]` and downstream code assumes that. As a result, formulas
like `MATCH("be*", A1:A3, 0)` cannot find a text match because the
range arrives as `[0.0, 0.0, 0.0]`.

## What to change

### 1. `formula/evaluator.py:_eval_range` — preserve types

```
numeric    -> float
bool       -> bool          (kept; Excel ranges do not auto-coerce booleans)
str        -> str
None       -> 0.0           (empty cell, matches current "treat blank as 0")
ExcelError -> propagate     (unchanged)
```

### 2. `engine.py:Vec`

Change `data` typing from `list[float]` to `list[Any]`. No runtime
change to existing numeric paths.

### 3. `engine.py` core aggregates — make Excel-tolerant

- `SUM`, `AVG`, `MIN`, `MAX`: skip text and booleans-from-ranges
  (Excel rule for the non-`A` variants; the `A` variants already
  coerce text -> 0).
- `COUNT`: numerics only.
- `ABS`, `SQRT`, `INT`: keep numeric; non-numeric element ->
  `#VALUE!` for that element (or propagate scalar `#VALUE!` if input
  is scalar text).

### 4. `Vec` arithmetic (`__add__`, `__sub__`, etc.)

Per-element type guard: numeric pairs operate; any non-numeric pair
returns `ExcelError.VALUE` for that element. Matches Excel's
`=A1:A5*2` with mixed text returning `#VALUE!` only in the affected
rows.

### 5. Existing `xlsx.py` functions that take Vec data

Already partially filtered via `_vec_data`/`_flatten_numeric`.
Double-check that these all skip non-numerics consistently:

- `MEDIAN`, `GEOMEAN`, `HARMEAN`
- `STDEV`, `STDEVP`, `VAR`, `VARP`
- `MODE`, `MODE_MULT`
- `PERCENTILE`, `PERCENTILE_EXC`, `QUARTILE`, `QUARTILE_EXC`
- `RANK`, `RANK_AVG`, `LARGE`, `SMALL`
- `SUMPRODUCT`, `NPV`, `IRR`
- Tier 3 stats: `AVEDEV`, `DEVSQ`, `SLOPE`, `INTERCEPT`, `RSQ`,
  `STEYX`, `SKEW`, `KURT`, `PERCENTRANK`

Filter pattern:
`[v for v in data if isinstance(v, (int, float)) and not isinstance(v, bool)]`

## Risk areas

- **`_to_number_or_zero` was load-bearing** for the "blank/text counts
  as 0 in arithmetic" assumption. Some users may have relied on
  `=A1+B1` working when one cell is text. After the fix, that returns
  `#VALUE!` (correct Excel behavior, but a behavior change).
- **Vec equality and persistence**: `Cell.arr: list[float] | None` is
  used in JSON save/load and comparisons. Limit type widening to
  in-flight Vecs from `_eval_range`; do not store text in `arr`.
- **Legacy `_expand_ranges`** (the `eval()`-based path) uses
  `Vec([cell_names])` literally -- those identifiers come from
  `_eval_globals` which yields `cl.val` (numeric). That path stays
  numeric. Only the EXCEL/HYBRID evaluator path picks up the new
  behavior.
- **JSON test fixtures**: unaffected; they store source text, not
  Vec instances.

## Test plan

- Unit: text in `MATCH`/`VLOOKUP`/`COUNTIF`/`SUMIF` through a real
  Grid range (not just direct `Vec(["..."])` calls).
- `SUM(A1:A5)` with mixed text+numeric returns the numeric sum (text
  skipped).
- `=A1:A5+1` with text in A2 returns `Vec` with `#VALUE!` at index 1.
- Empty cells still treated as `0` in `SUM`.
- Existing 813 tests must remain green. The tightening to `#VALUE!`
  for text-arithmetic only triggers when text is actually present,
  which existing tests do not do.

## Scope estimate

- ~80-120 lines of code changes (small filters in ~10 aggregates +
  Vec ops).
- ~10 new tests.
- Files touched: `formula/evaluator.py`, `engine.py`, `libs/xlsx.py`,
  `tests/test_libs.py`.
