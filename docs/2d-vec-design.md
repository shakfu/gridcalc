# 2D-aware Vec — design scope

## Goal

Make `Vec` carry shape (rows × cols) end-to-end so that:

1. `TRANSPOSE`, `LINEST`/`LOGEST`, multi-regressor `TREND`/`GROWTH`,
   `FREQUENCY`, true `HSTACK`, proper `CHOOSEROWS`/`CHOOSECOLS`/
   `WRAPROWS`/`WRAPCOLS` become implementable.
2. `CHISQ.TEST` on a 2D contingency table works (`df = (r-1)(c-1)`).
3. `TEXTSPLIT` `pad_with` becomes meaningful.
4. The `Vec` produced by `=A1:B3` round-trips through arithmetic and
   re-indexing — today `=A1:B3 + 1` drops `cols`, breaking later
   `INDEX(result, 1, 1)`.

This work does **not** include spill semantics. Spill is a separate
follow-up that depends on this; see "Out of scope" below.

## What already exists

- `Vec.data: list[Any]`, `Vec.cols: int | None`. Set by
  `formula/evaluator.py:_eval_range` when materialising a `RangeRef`.
- A handful of consumers already use `cols` correctly: `INDEX`,
  `VLOOKUP`, `HLOOKUP`, `_d_collect` (D-functions), `RANDARRAY`,
  `SEQUENCE`, `TEXTSPLIT`. These build or destructure 2D Vecs row-major.
- `Cell.arr: list[float] | None` is an **in-memory cache only** — it is
  not in the JSON save format. So no on-disk schema migration is
  required.
- ~23 `Vec(...)` construction sites in `libs/xlsx.py`, plus a few in
  `engine.py`. Finite audit surface.

## What's missing

1. **Shape doesn't survive arithmetic.** `Vec._binop` returns
   `Vec([...])` without forwarding `cols`. So `=A1:B3 + 1` produces a
   6-element 1D Vec.
2. **No 2D-row/column accessors.** Functions that want a row or column
   re-derive it from `data` and `cols` inline. Repeated, error-prone.
3. **Cell persistence drops shape.** `cl.arr` is `list[float]`;
   `engine.py:864` reconstructs `Vec(cl.arr)` with no `cols`. So a 2D
   Vec stored to a cell loses shape on next read.
4. **No 2D arithmetic shape rules.** Per-element ops just zip-pair the
   flat lists. Same flat length but different shapes silently produce
   wrong results.
5. **Many consumers assume 1D.** `_vec_data`, `_pair_numeric`,
   `_flatten_numeric`, plus per-function code, treat `Vec` as flat.
   Most stay correct (flattening is fine for `SUM`/`AVERAGE`/etc.) but
   need an audit.

## Phasing

Five phases, each independently testable. Phases 1–2 are mandatory
infrastructure; 3–5 are the user-visible payoff.

### Phase 1 — Shape API on Vec (~half day)

Pure additions; no behavior change.

- `Vec.rows: int` — `len(data) // cols if cols else len(data)`.
- `Vec.shape: tuple[int, int]` — `(rows, cols or 1)`.
- `Vec.is_2d: bool` — `cols is not None and cols > 0`.
- `Vec.row(i: int) -> Vec` — returns a 1D Vec of row `i`.
- `Vec.col(j: int) -> Vec` — returns a 1D Vec of column `j`.
- `Vec.at(r: int, c: int) -> Any` — single cell access.
- `Vec.iter_rows() -> Iterator[list[Any]]`.
- `__repr__` shows shape: `Vec[3x2]([...])` when 2D.

`__getitem__` and `__iter__` keep flat semantics (used by
`SUM`/`MIN`/etc. — no churn).

**Ship gate:** all 899 existing tests still pass; new accessor tests
prove shape behavior on hand-built 2D Vecs.

### Phase 2 — Shape preservation through arithmetic + persistence (~1 day)

- `Vec._binop` and `_rbinop`: when both operands have matching `cols`,
  forward `cols` to the result. When one is 1D scalar-ish (length 1 or
  not a Vec), forward the other's `cols`. When 2D shapes mismatch,
  return per-element `#VALUE!` (matches Excel).
- `Vec.__neg__` / `__abs__`: preserve `cols`.
- `Cell.arr_cols: int | None` — new `__slots__` field. Default `None`.
- `engine.py:_store_formula_result`: when result is a 2D Vec, store
  `cl.arr_cols = result.cols`.
- `engine.py:_cell_lookup_value`: rebuild as `Vec(cl.arr, cols=cl.arr_cols)`.
- JSON save/load: extend cell schema with optional `arr_cols` field;
  reads without it default to 1D (forward-compatible).
- `_pair_numeric`, `_vec_data`, `_flatten_numeric`: unchanged — flat
  semantics is correct for these.

**Ship gate:** `=A1:B3 + 1` round-trips through `INDEX(result, 2, 2)`.
JSON round-trip preserves shape for a 2D Vec stored in a cell.

### Phase 3 — TRANSPOSE + 2D reshape consumers (~1 day)

Add functions that produce or consume 2D shape:

- `TRANSPOSE(rng)` — swap rows and columns.
- `CHOOSEROWS(rng, *idx)`, `CHOOSECOLS(rng, *idx)` — index-list along
  one axis.
- `TOROW(rng, ignore=0, scan_by_column=0)`, `TOCOL(rng, ...)` —
  flatten to a single row/column with optional empty/error skipping.
- `WRAPROWS(vec, count, [pad])`, `WRAPCOLS(vec, count, [pad])` —
  reshape 1D into 2D with padding.
- `EXPAND(rng, rows, [cols], [pad])` — pad to a target shape.

Fix existing `HSTACK` and `VSTACK` so they truly stack 2D ranges
(today they only concatenate flat data).

**Ship gate:** `TRANSPOSE(TRANSPOSE(A1:B3)) == A1:B3` value-by-value.
2D `HSTACK([[a,b],[c,d]], [[e,f],[g,h]])` produces `[[a,b,e,f],[c,d,g,h]]`
as a 2x4 Vec.

### Phase 4 — LINEST family + array forecasting (~1 day)

- `LINEST(known_y, [known_x], [const], [stats])` — single regressor:
  returns `[slope, intercept]` (1×2) or 5×2 stats matrix when `stats=TRUE`.
- `LOGEST` — same on `ln(y)`.
- Multi-regressor versions need real linear algebra (Gauss–Jordan or QR
  on a small matrix). Hand-roll a tiny solver — no NumPy.
- Array forms of `TREND`/`GROWTH` accepting 2D `known_x`.

**Ship gate:** `LINEST(y, x)` matches the existing `_linreg` slope/intercept;
stats matrix matches Excel reference values for a small known dataset.

### Phase 5 — Refit 2D-blocked items (~half day)

- `CHISQ.TEST` on a 2D contingency table: compute row/col sums →
  expected matrix → chi² → `df = (r-1)(c-1)`. 1D path stays as-is for
  back-compat (when `actual.cols is None`).
- `TEXTSPLIT` `pad_with`: when `row_delimiter` is given and rows have
  unequal lengths, pad with `pad_with` instead of empty string.
- `FREQUENCY(data, bins)` — returns column vector of bin counts.

**Ship gate:** Excel-cross-checked tests for each.

### Out of scope (separate follow-up)

- **Spill semantics.** Excel 365 spills 2D results into adjacent
  cells. This requires a `Cell` field tracking "spilled-into-by-(c,r)",
  recalc invalidation across spills, `#SPILL!` errors when a target
  cell is occupied, TUI rendering of spilled values, JSON round-trip
  of spill provenance. ~2 weeks of work, dependent on Phase 2 being
  done. Worth doing only if the 2D functions land first and a real
  user wants spill.

- **Excel-365 broadcast arithmetic** (`{1;2;3} * {10,20,30}` produces
  outer product 3×3). Cleanly modelled but additional rules. Phase 2
  errors out on shape mismatch; broadcasting is an additive change
  later if asked.

- **`MAKEARRAY` / `BYROW` / `BYCOL` / `MAP` / `REDUCE` / `SCAN`** —
  these need lexical scope in the evaluator (separate architectural
  lift). 2D Vec is a prerequisite but not sufficient.

## Risks

| Risk | Mitigation |
|---|---|
| Hidden 1D assumptions in xlsx.py consumers | Phase 1 is no-op; Phase 2 audit walks all 23 `Vec(...)` sites + `_vec_data`/`_pair_numeric`. Most are correctly flat-aware (e.g. `SUM`). The ones that need shape (`INDEX`/`VLOOKUP` etc.) already use it. |
| Arithmetic semantics change breaks tests | Phase 2 only *adds* shape preservation; same flat length still pairs element-wise. Mismatched shapes today silently produced wrong results — failing loudly with `#VALUE!` is strictly better. |
| JSON forward-compat | `cl.arr_cols` is optional on read; absent → `None` → 1D. Old saves load fine. New saves only emit it when non-None. |
| `cl.matrix` collision | Orthogonal — `cl.matrix` is for ndarray/DataFrame round-tripping. 2D Vec uses `cl.arr` + `cl.arr_cols`. |
| Phase 4 numerical accuracy | Hand-rolled small-matrix solver risks ill-conditioning. Test with a known multi-regressor dataset against Excel; if precision is poor, fall back to scipy *only* in `LINEST`/`LOGEST`. |
| Scope creep into spill | Hard line: phases 1–5 deliberately exclude spill. Don't merge work that touches `Cell` rendering or recalc graph for spill purposes during this lift. |

## Files touched

- `src/gridcalc/engine.py` — `Vec` class (Phase 1), arithmetic
  (Phase 2), `Cell.__slots__` + persistence (Phase 2), maybe `Grid`
  recalc helpers if `arr_cols` round-trip needs them.
- `src/gridcalc/formula/evaluator.py` — `_eval_range` already correct;
  no changes expected.
- `src/gridcalc/libs/xlsx.py` — Phase 3–5 functions; audit existing
  `Vec(...)` constructors to forward `cols` where appropriate.
- `tests/test_libs.py` — new test classes per phase.
- `tests/test_engine.py` — Vec shape API + persistence round-trip.

## Estimate

| Phase | Effort | Risk |
|---|---|---|
| 1. Shape API | half day | low |
| 2. Arith + persistence | 1 day | medium — audit work |
| 3. Reshape functions | 1 day | low |
| 4. LINEST family | 1 day | medium — solver accuracy |
| 5. Refit blocked items | half day | low |
| **Total** | **~4 days** | |

Phases 1–2 are infrastructure; phases 3–5 are independent and could be
done in any order or parallelised.

## Open questions

1. **Should `__iter__` over a 2D Vec yield flat values or rows?** Flat
   matches existing usage (`for v in vec.data` is everywhere). Rows
   would break `SUM`/`MIN`/etc. **Recommendation: flat. Add
   `iter_rows()` for explicit row iteration.**

2. **Should we forward shape through `_vec_apply2`/`_vec_apply1` in
   `evaluator.py` too?** Currently those wrap arithmetic at a different
   layer. **Recommendation: yes — Phase 2 fix in evaluator wrapper as
   well.**

3. **Inverse of stacking — should `INDEX(rng, r, 0)` return a row Vec
   that's a 1×n 2D Vec or a 1D Vec?** Excel returns a 1D-looking value
   that behaves as a row in further operations.
   **Recommendation: 1D (matches today). Functions that genuinely need
   row vs column distinction (`HSTACK`/`VSTACK`) should construct
   shape explicitly.**

4. **`SORT`/`UNIQUE` on 2D — sort rows, treat row-equality?** Excel
   does. **Recommendation: ship Phase 1–2 with current 1D behaviour;
   add 2D `SORT`/`UNIQUE` as a Phase 3 follow-up only if asked.**
