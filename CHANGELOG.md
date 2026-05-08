# Changelog

## Unreleased

### Added

- **CLI accepts `.xlsx` files directly.** `gridcalc model.xlsx`
  dispatches to `Grid.xlsxload` (the OpenXLSX-backed C++ path)
  instead of `jsonload`. Detection is by extension match. Sandbox
  trust prompt is skipped for xlsx (no code-block surface). Help
  string updated to ``Usage: gridcalc <sheet.json | sheet.xlsx>``.

- **Per-recalc range materialisation cache.** `Env._range_cache`
  (evaluator.py) memoises the materialised `Vec` for each
  ``(c1, r1, c2, r2)`` range encountered during a single recalc pass.
  `_eval_range` checks the cache before walking cells; subsequent
  references to the same range reuse the result. Topological recalc
  evaluates in dep order so source cells finalise before any consumer
  reads them — cache liveness is bounded by the closure pass and
  remains sound. The legacy fixed-point `_recalc_formula` clears the
  cache between iterations because values can change across passes.
  Hit rate on range-heavy sheets is ~10×; on a 25K-cell range-heavy
  benchmark this cuts full recalc 871 ms → 259 ms (-70%) and
  surgical edits 23 ms → 10 ms (-57%).

- **Skip redundant `_rebuild_dep_graph` on cold load.** `jsonload`'s
  per-cell `_setcell_no_recalc` already populates `_dep_of` /
  `_subscribers` / `_volatile` via incremental `_refresh_deps` calls.
  The subsequent `recalc()` previously walked every formula AST a
  second time to rebuild the same graph from scratch. New
  `Grid._dep_graph_built` flag tracks whether the graph is consistent;
  set True at the end of `_rebuild_dep_graph` and at the end of
  `jsonload` when mode is non-LEGACY. `_recalc_topo` checks the flag
  and skips the rebuild when the graph is current. Cold load on
  ranges sheet: 1267 ms → 677 ms (-47%); typical mixed sheet: 662 ms
  → 476 ms (-28%).

- **`benches/` profiler harness.** New `benches/gen_sheet.py` produces
  four representative sheet shapes (wide independent formulas, long
  chains, range-heavy aggregates, realistic mix) at ~30K cells each.
  `benches/run.py` wraps `cProfile` around four operations (cold load,
  full recalc, surgical edit, save) per shape and prints top-N
  hotspots plus a one-page summary. `make bench` runs end-to-end;
  `make bench-clean` removes fixtures. Used to identify the two
  optimisations above.

- **2D-aware `Vec` (Phases 1-4 of `docs/2d-vec-design.md`).** Foundation
  for `TRANSPOSE`/`LINEST`/`HSTACK`/2D `CHISQ.TEST`/spill semantics.
  - **Phase 1 — shape API on `Vec`** (`engine.py`): new `is_2d`, `rows`,
    `shape`, `at(r, c)` (1-based), `row(i)`, `col(j)`, `iter_rows()`.
    `__repr__` now shows shape: `Vec[2x3]([...])`. `__iter__`/`__len__`/
    `__getitem__` keep flat semantics so existing `SUM`/`AVG`/etc.
    consumers stay correct. A 1D `Vec` is a column vector (shape `(n, 1)`).
    11 new tests in `TestVecShapeAPI`.
  - **Phase 2 — shape preservation through arithmetic + persistence.**
    `Vec._binop`/`_rbinop`/`__neg__`/`__abs__` and the evaluator's
    `_vec_apply2`/`_vec_apply1` now forward `cols` whenever inputs share
    or imply a shape. Mismatched 2D shapes emit per-element `#VALUE!`
    instead of silently zip-pairing. New `Cell.arr_cols: int | None`
    slot; `_store_formula_result` stores `result.cols` alongside
    `arr`, and `_cell_lookup_value` rebuilds `Vec(cl.arr, cols=cl.arr_cols)`.
    All ~12 `cl.arr = ...` write sites updated to keep `arr_cols` in
    lockstep. JSON format unchanged (saves cell *text*, not computed
    arrays — recalc rebuilds shape from formulas on load).
    Ship gate: `=INDEX(A1:B2 + 1, 2, 2)` now picks the bottom-right of
    a 2D arithmetic result (was broken: `cols` dropped through `+`). 8
    new tests in `TestVecShapePreservation`.
  - **Phase 3 — TRANSPOSE + reshape consumers (12 new functions).**
    `TRANSPOSE` (1D column → 1×n row, 2D row/col swap, round-trip
    correct), `CHOOSEROWS`/`CHOOSECOLS` (1-based index lists with
    negative-from-end, accept `Vec`/list of indices via
    `_normalize_indices`), `TOROW`/`TOCOL` (flatten with `ignore`
    flags for blanks/errors and `scan_by_column` order; `TOCOL`
    returns a 1D column vector), `WRAPROWS`/`WRAPCOLS` (reshape 1D
    into 2D with target row/col length; pad short final chunks
    `#N/A` by default), `EXPAND` (pad to target shape; smaller
    target → `#VALUE!`), `TAKE`/`DROP` (positive from start, negative
    from end, along rows + cols), `HSTACK`/`VSTACK` (proper row
    interleaving + concatenation, mismatched dims pad `#N/A` to the
    widest/tallest). 20 new tests in `TestReshape2D`.
    Ship gate: `=INDEX(TRANSPOSE(A1:C2), 1, 2) == 4` end-to-end.
  - **Phase 4 — `LINEST` family with multi-regressor support (4 new
    functions).** Hand-rolled `_solve_linear_system` (Gauss-Jordan
    with partial pivoting, `1e-15` singularity tolerance) on the
    normal-equations matrix `X'Xβ = X'y`; `_linest_core` builds the
    design matrix with optional intercept; `_linest_stats_matrix`
    builds the 5×p Excel stats matrix (row 1 coefficients in Excel
    order `m_k…m_1, b`; row 2 standard errors via
    `sqrt(σ²·diag((X'X)⁻¹))`; rows 3-5 r² / standard error / F /
    df / SS_reg / SS_resid). `LINEST` (single + multi regressor;
    `const=FALSE` forces through origin; `stats=TRUE` returns the
    5×p matrix), `LOGEST` (`LINEST` on `ln(y)` then exp of
    coefficients), `TREND` (replaces the prior `TREND_SCALAR`,
    accepts scalar/1D/2D `new_x`), `GROWTH` (TREND on log-scale).
    Recovers `y = 1 + 2·x₁ + 3·x₂` synthetic to ~1e-9 over 6
    observations. 12 new tests in `TestRegressionFamily`.

- **Heavier stat distributions (Tier 4, batch 2; ~25 new dotted names
  + 17 pre-2010 aliases).** Builds on the regularised incomplete beta
  (`_incbeta`) infra from batch 1 plus a new regularised lower
  incomplete gamma (`_gser`/`_gcf`/`_incgamma`, Numerical Recipes).
  Inverses use 200-step bisection on the CDF (1e-12 in p; ~10
  decimal-digit accuracy in x).
  - **F**: `F.DIST`, `F.DIST.RT`, `F.INV`, `F.INV.RT`.
  - **Chi-square**: `CHISQ.DIST`, `CHISQ.DIST.RT`, `CHISQ.INV`,
    `CHISQ.INV.RT`, `CHISQ.TEST` (1D arrays, `df = n − 1`; 2D
    contingency form blocked on 2D Vec).
  - **Gamma family**: `GAMMA`, `GAMMALN`, `GAMMALN.PRECISE`,
    `GAMMA.DIST`, `GAMMA.INV`.
  - **Beta**: `BETA.DIST` (with `[a, b]` bounds), `BETA.INV`.
  - **Lognormal**: `LOGNORM.DIST`, `LOGNORM.INV`.
  - **Weibull**: `WEIBULL.DIST`.
  - **Hypergeometric / negative binomial / inverse binomial**:
    `HYPGEOM.DIST` (with cumulative), `NEGBINOM.DIST`, `BINOM.INV`.
  - **Hypothesis tests**: `T.TEST` (paired / equal-var / Welch),
    `Z.TEST` (one-tailed; sample stdev when σ omitted), `CONFIDENCE.T`.
  - **Other**: `STANDARDIZE`, `PHI`, `PROB`.
  - **Pre-2010 aliases**: `FDIST`/`FINV` (right-tail), `CHIDIST`,
    `CHIINV`, `CHITEST`, `GAMMADIST`, `GAMMAINV`, `BETADIST`, `BETAINV`,
    `LOGNORMDIST`, `LOGINV`, `WEIBULL`, `HYPGEOMDIST`, `NEGBINOMDIST`,
    `CRITBINOM`, `TTEST`, `ZTEST`.
  - 19 new tests cross-checked against Excel reference values
    (≥5–9 sig figs).

- **Mechanical fill-in batch (~32 new functions).**
  - **Math**: `ERF` (one- and two-arg), `ERFC` via `math.erf`/`erfc`.
  - **Tier 4 text parsing**: `TEXTSPLIT` (1D/2D, with `ignore_empty`/
    `match_mode`), `TEXTBEFORE`, `TEXTAFTER` (full Excel 365 signatures
    including negative `instance` from end, list-of-delimiters,
    `match_end`, `if_not_found`).
  - **Number-base conversion** (12): `DEC2BIN`/`OCT`/`HEX`,
    `BIN2DEC`/`OCT2DEC`/`HEX2DEC`, plus all six cross conversions.
    Excel-style 10-digit two's-complement for negatives; per-base range
    validation; `places` padding with `#NUM!` on overflow.
  - **Scalar forecasting**: `FORECAST`, `FORECAST.LINEAR`, `TREND`
    (scalar + 1D Vec of new x-values; default `known_x = {1, 2, 3, ...}`
    when omitted). All reuse `_linreg`. Multi-regressor / array forms
    blocked on 2D Vec.
  - **D-functions** (12): `DSUM`, `DAVERAGE`, `DCOUNT`, `DCOUNTA`,
    `DGET`, `DMAX`, `DMIN`, `DPRODUCT`, `DSTDEV`, `DSTDEVP`, `DVAR`,
    `DVARP`. Shared driver: `_vec_table` decomposes a 2D `Vec` into
    header + rows, `_resolve_field` accepts column name or 1-based
    index, `_row_matches_criteria` ANDs across columns within a row
    and ORs across rows (Excel semantics). 25 new tests.

- **Financial Tier 4 (12 new functions).**
  - **Depreciation**: `SLN`, `SYD`, `DB` (3-decimal rate rounding +
    month proration), `DDB` (factor-decline, salvage clamp), `VDB`
    (DDB with optional SL switch; integer periods only — fractional
    `start`/`end` returns `#NUM!`).
  - **Rate conversion**: `EFFECT`, `NOMINAL`.
  - **Cumulative**: `CUMIPMT`, `CUMPRINC` (sum existing `IPMT`/`PPMT`
    over a period range).
  - **Date-based & modified IRR**: `XNPV`, `XIRR` (365-day basis,
    Newton's method); `MIRR` (closed form on negative-flow PV vs
    positive-flow FV).
  - 14 new tests cross-checked against Excel docs reference values
    (`SLN(10000,1000,5)=1800`; `DB(1e6,1e5,6,1,7)=186083.33`;
    `DDB(2400,300,10,1)=480`; `EFFECT(0.0525,4)=0.05354266…`;
    `MIRR` Excel example = `0.126094`; `XNPV(0.09,…)=2086.65`,
    `XIRR=0.37336` from Excel docs example).

- **Statistical distributions (Tier 4, batch 1; 13 new dotted names +
  10 legacy aliases).** Stdlib-only implementation. Helpers:
  `_norm_pdf`/`_norm_cdf` via `math.erf`; `_norm_s_inv` via Acklam's
  rational approximation (max relative error ~1.15e-9); `_betacf`
  (Lentz CF) and `_incbeta` for the regularised incomplete beta;
  `_t_cdf` and `_t_inv`/`_t_inv_2tail` (bisection); `_binom_pmf`,
  `_pois_pmf` via `math.lgamma`. Functions: `NORM.DIST`/`NORM.INV`,
  `NORM.S.DIST`/`NORM.S.INV`, `T.DIST`/`T.DIST.2T`/`T.DIST.RT`/
  `T.INV`/`T.INV.2T`, `BINOM.DIST`, `POISSON.DIST`, `EXPON.DIST`,
  `CONFIDENCE.NORM`. Pre-2010 aliases: `NORMDIST`, `NORMINV`,
  `NORMSDIST` (1-arg, always cumulative), `NORMSINV`, `TDIST` (legacy
  3-arg right/two-tail), `TINV` (legacy two-tailed), `BINOMDIST`,
  `POISSON`, `EXPONDIST`, `CONFIDENCE`. 17 new tests cross-checked
  against Excel reference values to ≥5 sig figs.

- **Excel function library: Tier 1 + Tier 2 (~60 new functions).**
  - **Multi-criteria aggregates**: `SUMIFS`, `COUNTIFS`, `AVERAGEIFS`,
    `MAXIFS`, `MINIFS`.
  - **Date/time**: `NOW`, `TODAY`, `DATE`, `TIME`, `DATEVALUE`,
    `TIMEVALUE`, `YEAR`, `MONTH`, `DAY`, `HOUR`, `MINUTE`, `SECOND`,
    `WEEKDAY`, `EDATE`, `EOMONTH`, `DATEDIF`, `NETWORKDAYS`, `WORKDAY`.
    Excel epoch (1899-12-30) so serials match Excel's 1900-leap-year
    convention.
  - **Information**: `ISNUMBER`, `ISTEXT`, `ISBLANK`, `ISERROR`, `ISNA`,
    `ISERR`, `ISLOGICAL`, `ISEVEN`, `ISODD`, `NA`, `N`.
  - **Text utilities**: `FIND`, `SEARCH`, `REPLACE`, `TEXTJOIN`, `CHAR`,
    `CODE`, `VALUE`, `TEXT` (subset of Excel format strings).
  - **Statistical**: `STDEV`, `STDEVP`, `VAR`, `VARP`, `CORREL`, `COVAR`,
    `RANK`, `PERCENTILE`, `QUARTILE`, `MODE`, `GEOMEAN`, `HARMEAN`.
  - **Financial**: `PV`, `FV`, `PMT`, `NPER`, `RATE`, `NPV`, `IRR`,
    `IPMT`, `PPMT`. `RATE` and `IRR` use Newton's method.
  - **Math**: `CEILING`, `FLOOR`, `MROUND`, `ODD`, `EVEN`, `FACT`,
    `GCD`, `LCM`, `TRUNC`.
  - **Logical**: `IFS`, `SWITCH`, `IFNA`, `XOR`.
  - **Reference subset**: `CHOOSE`. (`ADDRESS`, `OFFSET` deferred --
    `OFFSET` needs dynamic-ref handling.)
  - 39 new tests in `tests/test_libs.py` exercising these via direct
    calls and end-to-end formula evaluation.

- **`ROW`, `COLUMN`, `ROWS`, `COLUMNS`** via a new raw-args path in
  the evaluator. Functions registered in `RAW_ARG_FUNCS` (`evaluator.py`)
  receive AST nodes (`CellRef`, `RangeRef`) plus `Env`, instead of
  evaluated values. `Env.current_cell` is populated by recalc loops
  before each formula eval so `ROW()`/`COLUMN()` can report the
  calling cell. `formula.deps.extract_refs` and `engine._ast_uses_cell`
  both treat these functions as address-only, so e.g. `=ROWS(A1:B10)`
  written into a cell inside the range does not register a spurious
  self-cycle. 8 new tests in `TestRowColumnFunctions`. Total function
  count: ~108.

- **Topological recalc graph stays consistent across structural edits.**
  `Grid._rebuild_dep_graph()` walks all formula cells and reconstructs
  `_dep_of`/`_subscribers`/`_volatile`; called from `insertrow`,
  `insertcol`, `deleterow`, `deletecol`, `swaprow`, `swapcol`, and at
  the top of `_recalc_topo` on full-recalc paths (handles
  LEGACY -> EXCEL/HYBRID mode switches and initial loads).
  `replicatecell` was refactored to route through `_setcell_no_recalc`
  so the destination cell's deps are tracked. New
  `TestTopoGraphInvariants` (7 tests) exercises each path with a
  forward/reverse-index consistency check.

- **`jsonload` uses bulk-set semantics**: was N x O(formulas) per-cell
  recalcs; now single recalc at the end. 5000-cell load: ~18 ms.

- **LEGACY mode skips dep-graph maintenance.** `_refresh_deps` returns
  early in LEGACY mode -- the graph is unused there (fixed-point
  recalc). Removes the parsing overhead per cell-write in LEGACY.

- **Topological recalc** (default ON): replaces the fixed-point recalc
  loop with a dependency-graph traversal. `Grid` now maintains forward
  (`_dep_of`) and reverse (`_subscribers`) indexes built from each
  formula's AST via `formula.deps.extract_refs`. `recalc(dirty)`
  computes the transitive closure of changed cells through the reverse
  index, topologically sorts via Kahn's algorithm, and evaluates each
  cell exactly once. Cells containing `INDIRECT`/`OFFSET`/`INDEX`/`PyCall`
  are flagged volatile and unconditionally added to the closure.
  Surgical edit benchmark (1 source change in a 10,000-cell sheet,
  5000 formulas): 7.4 ms -> <0.1 ms. Cycle detection is now structural
  (Kahn's leftover) rather than "didn't converge in 100 iterations".
  Design rationale and remaining phases in `docs/topological.md`. The
  legacy fixed-point path (`Grid._recalc_formula`) remains in the
  codebase one release as a fallback, gated by `_use_topo_recalc =
  False` per-instance or `GRIDCALC_TOPO=0` for the test suite.

- **`docs/topological.md`**: design note covering the algorithmic
  motivation, current cost model, the static dep extractor, hard
  parts (dynamic refs, range explosion, named ranges, py.* gateway,
  graph mutation, LEGACY mode), the phased implementation plan, open
  questions, and triggers for when to revisit.



- **Native xlsx I/O via OpenXLSX** (nanobind `_core` extension): xlsx read
  and write now go through a C++ binding around vendored
  [OpenXLSX](https://github.com/troldal/OpenXLSX). On a 5000-cell grid,
  `_core.xlsx_read` parses in ~4 ms vs. ~80 ms for the prior Python loop.
  `xlsx_read` iterates `wks.rows() -> row.cells()`, skipping cells that
  are both empty and formula-free.

- **Build system migration to scikit-build-core + nanobind**: `pyproject.toml`
  uses `scikit-build-core` as the build backend; CMake builds the `_core`
  extension and links the OpenXLSX subdirectory under
  `thirdparty/OpenXLSX/`. `CMAKE_POLICY_VERSION_MINIMUM=3.5` is set so
  the fetched `miniz` dependency configures under CMake 4.

- **`Grid.setcells_bulk(cells)`**: bulk-set API that defers `recalc()`
  until all cells are written. Loading 5000 cells via `setcells_bulk` is
  ~810x faster (5 ms vs 4070 ms) than calling `setcell` N times.
  `xlsxload` now uses it; combined with the C++ read path, end-to-end
  load is ~72x faster (12 ms vs 839 ms for 5000 cells).

- **`src/gridcalc/_core.pyi`**: type stubs for the nanobind extension so
  mypy resolves `_core.xlsx_read` / `_core.xlsx_write`.

### Changed

- **Zero third-party runtime dependencies for the core install.**
  `numpy`, `pandas`, and `pygments` moved out of
  `[project.dependencies]` into `[project.optional-dependencies]` as
  the `[numpy]`, `[pandas]` (implies numpy), `[viz]`, and `[all]`
  extras. All 300+ Excel functions — including the full
  statistical-distribution suite, financial functions, the regression
  family, and the 2D-Vec reshape consumers — work on stdlib alone.
  `tomli` is the only remaining runtime dep, conditional on Python
  <3.11. Existing duck-typing helpers (`_is_ndarray`/`_is_dataframe`/
  `_is_series`) continue to gate ndarray/DataFrame-aware paths
  without importing the relevant module.
  - **Optional numpy speedup in regression**: `_solve_linear_system`
    now tries `numpy.linalg.solve` first (LAPACK-backed; ~100× faster
    on large systems and more accurate on ill-conditioned designs)
    and falls back to the existing pure-Python Gauss-Jordan elimination
    when numpy isn't installed. `_linest_core`'s `X'X` build similarly
    upgrades to `X.T @ X` when numpy is available.
  - **Pygments fallback**: the trust-prompt code preview
    (`tui._highlight_code`) falls back to plain (uncoloured) text when
    Pygments isn't installed.
  - **Tests**: numpy/pandas-dependent classes are now guarded with
    `@pytest.mark.skipif(not _HAS_NUMPY/PANDAS, ...)`. New
    `make test-stdlib` target runs the suite in a `uv --isolated`
    environment with no extras, exercising the optional-import paths.
    897 / 46 split (passing / skipped) without extras; full 951
    passing with `[all]`.

- **`openpyxl` is now a dev-only dependency**: moved from
  `[project.dependencies]` to `[dependency-groups].dev`. Runtime xlsx I/O
  goes through the OpenXLSX-backed `_core`; failures surface as return
  code -1 (no silent fallback). `openpyxl` is retained in tests as an
  independent oracle for fixture construction.

- **`engine.setcell` refactored**: per-cell parsing/typing extracted to
  `_setcell_no_recalc`; `setcell` composes that helper with `recalc()`.

### Fixed

- **Text and booleans now survive range materialization.**
  `formula/evaluator.py:_eval_range` previously called
  `_to_number_or_zero` on every cell, flattening text and bools to
  `0.0`. This silently broke `MATCH("be*", A1:A3, 0)` and similar over
  real Grid ranges (the lookup column arrived as `[0.0, 0.0, 0.0]`).
  `_eval_range` now preserves type per cell: numeric -> float, bool ->
  bool, str -> str, None -> 0.0, ExcelError -> propagate. `Vec.data`
  widened to `list[Any]`. `Vec` arithmetic (`__add__`/`__sub__`/...,
  `__neg__`/`__abs__`) goes through new `_vec_elem_op`/`_unary_or_error`
  helpers that emit per-element `#VALUE!` for non-numeric pairs and
  propagate `ExcelError`. `SUM`/`AVG`/`MIN`/`MAX` skip strings and
  bools-from-ranges (Excel's non-`A` aggregate rule); `COUNT` counts
  numerics only; `ABS`/`SQRT`/`INT` propagate per-element `#VALUE!`
  for non-numerics. `libs/xlsx.py` audited: `_vec_data` filters
  numerics; new `_pair_numeric` for paired stats; `CORREL`/`COVAR`/
  `_linreg`/`RSQ`/`STEYX`/`_covariance`/`_paired_data`/`RANK`/
  `PERCENTILE`/`PERCENTILE_EXC`/`RANK_AVG`/`PERCENTRANK`/`NPV`/`IRR`/
  `SUMIF`/`AVERAGEIF`/`_multi_criteria`/`GCD`/`LCM`/`SUMPRODUCT`/
  `AVERAGE`/`MEDIAN`/`LARGE`/`SMALL` all skip non-numerics. 10 new
  tests in `TestRangeTextBool`.

- **`IPMT` sign convention.** Returned positive when paying interest
  on a positive `pv` (a loan); Excel convention is negative. Fix:
  `interest = fv_at * rate` (was `-fv_at * rate`); when `when=1` and
  `period > 1`, discount by one period. `PPMT` and the new
  `CUMIPMT`/`CUMPRINC` inherit the fix. No existing tests broke
  (there were no IPMT/PPMT tests before).

### Removed

- **`openpyxl` from sandbox allowlist** (`SIDE_EFFECT_MODULES`): now that
  it is no longer a runtime dependency, user formulas can no longer
  `import openpyxl`.

- **Internal `_xlsx_cell_to_text` helper**: no longer needed once the
  openpyxl read path was removed.

- **Vendored OpenXLSX trimmed** (2.8M -> 1.5M): dropped `Benchmarks/`,
  `Documentation/`, `Examples/`, `Tests/`, `gnu-make-crutch/`, `Notes/`,
  `Scripts/`, `Makefile.GNU`, `vcpkg.json`, and `README.md` from
  `thirdparty/OpenXLSX/`. Retained `CMakeLists.txt`, `cmake/`,
  `OpenXLSX/`, and `LICENSE.md` (BSD-3 attribution).

## [0.1.3]

### Added

- **Three formula modes** (`EXCEL`, `HYBRID`, `LEGACY`): Each spreadsheet now
  carries an explicit mode controlling how formulas are evaluated. `EXCEL`
  uses a strict Excel-compatible grammar (no `eval()`, no Python). `HYBRID`
  layers a `py.<name>(...)` gateway on top of the Excel grammar so functions
  defined in the code block remain reachable while keeping the Python
  boundary visible in every formula that crosses it. `LEGACY` preserves the
  original Python-eval path with full numpy/pandas/list-comprehension
  support. Mode is persisted in the JSON file as `"mode": "EXCEL"|"HYBRID"|
  "LEGACY"`; files without the field load as `LEGACY` for back-compat.

- **Excel formula evaluator** (`gridcalc.formula` package): New lexer,
  recursive-descent parser, and tree-walking evaluator implementing
  Excel-style grammar -- operators (`^` right-assoc, `&` concat, `<>`,
  `<=`, `>=`, `%` postfix), error literals (`#DIV/0!`, `#N/A`, `#NAME?`,
  `#REF!`, `#VALUE!`, `#NUM!`, `#NULL!`), error propagation through
  arithmetic, range broadcasting, named ranges, and the `py.*` gateway in
  `HYBRID`. Replaces `eval()` for `EXCEL` and `HYBRID` cells; `LEGACY`
  cells still use `eval()`.

- **AST cache on `Cell`**: Parsed-formula ASTs are cached per cell and
  invalidated on text change, eliminating per-iteration re-parsing in the
  recalc loop.

- **xlsx interop** (`:xlsx save [file]`, `:xlsx load [file]`): Read and
  write `.xlsx` files via openpyxl. `:xlsx load` translates Excel formulas
  into the gridcalc EXCEL grammar, switches the grid to `EXCEL` mode, and
  auto-loads the Excel function library. `:xlsx save` writes computed
  values to a single worksheet. Sheet-qualified refs (`Sheet1!A1`),
  `INDIRECT`, and multi-sheet workbooks are not supported.

- **`:mode [excel|hybrid|legacy]`**: Show or set the current mode.
  Switching validates every formula with the target evaluator first and
  refuses the change with a one-line error pointing at the first offender
  if anything fails. `EXCEL` also rejects switches that would leave a
  code block in place.

- **Auto-loaded Excel function library**: When mode is `EXCEL` or `HYBRID`,
  the `xlsx` library (`IF`, `IFERROR`, `AND`, `OR`, `NOT`, `ROUND`,
  `AVERAGE`, `MEDIAN`, `SUMIF`, `COUNTIF`, `AVERAGEIF`, `VLOOKUP`,
  `HLOOKUP`, `INDEX`, `MATCH`, `LEFT`, `RIGHT`, `MID`, `LEN`, `TRIM`,
  `UPPER`, `LOWER`, `SUBSTITUTE`, etc.) is loaded automatically. Previously
  the library required a manual `g.load_lib("xlsx")`.

- **Mode tag in TUI status bar**: The current mode is shown in the
  top-right region (`[EXCEL]`, `[HYBRID]`, `[LEGACY]`) using the
  mode-color attribute.

- **New TUI files default to `HYBRID`**: A fresh TUI session (no file
  argument) creates a grid in `HYBRID` mode with the xlsx library
  pre-loaded. Loaded files keep whatever mode their JSON specifies.
  The library default `Grid()` constructor stays `LEGACY` for back-compat
  with programmatic users.

- **Example files**: `example_excel.json` (quarterly sales report
  demonstrating `IF`, `SUM`/`AVG`/`MAX`/`MIN`, `MATCH`, `IFERROR`, named
  ranges, and range arithmetic) and `example_hybrid.json` (progressive
  tax calculator using a Python `py.progressive_tax()` alongside Excel
  formulas for aggregation, plus compound-interest and loan-payment
  demos).

- **Visual mode delete** (`d` / `Backspace`): In visual selection mode,
  press `d` or `Backspace` to clear all cells in the selection. Each cell
  is saved to undo before clearing. A count message is shown in the
  status bar.

- **Cell edit mode** (`e` / `F2`): Press `e` or `F2` on a non-empty cell
  to enter edit mode with the existing cell content pre-loaded in the
  input buffer. Modify the text and press Enter to save, or Escape to
  cancel. Previously, entering data always started from scratch.

- **Object editor** (`E`): Press `E` on a cell containing a Vec, NumPy
  array, or DataFrame to open an interactive sub-grid editor. Navigate
  with arrow keys, edit individual elements with Enter, add/remove
  rows and columns, and edit DataFrame column headers. `w` saves and
  exits, `Esc` discards changes. Writes back a literal formula
  (`=Vec([...])`, `=np.array([...])`, or `=pd.DataFrame({...})`).
  Supports viewport scrolling for large objects.

- 10 new tests for `_fmt_val` and `_build_formula` covering Vec, ndarray,
  and DataFrame formula generation with roundtrip verification.

- 162 new tests covering the formula package (lexer, parser, evaluator),
  mode persistence and dispatch, AST cache, `py.*` gateway, validate-on-
  mode-change, auto-loaded library, and xlsx round-trip I/O. Total test
  count: 676 (was 514).

### Changed

- **`openpyxl>=3.1`** added as a runtime dependency for the new xlsx I/O.

- **`Cell.__slots__`** gained `ast` and `ast_text` for the per-cell parsed-
  formula cache.

- **`Grid.recalc()`** now dispatches by mode: `EXCEL`/`HYBRID` cells go
  through the new tree-walking evaluator; `LEGACY` cells continue to use
  `eval()`. Self-reference detection in the new path is structural (AST
  walk) rather than regex.

- **`IFERROR`** now recognizes the new `ExcelError` enum in addition to
  `NaN`/`inf`. Previously, errors short-circuited before reaching the
  function so the fallback was never taken; the evaluator now exempts
  error-aware functions (`IFERROR`, `IFNA`, `ISERROR`, `ISERR`, `ISNA`)
  from automatic error propagation on their arguments.

### Fixed

- **String-returning formulas no longer display as `nan`.** Added
  `Cell.sval: str | None` slot, populated by `_store_formula_result`
  when a formula returns a string or bool. The TUI render path
  (`fmtcell`, status bar) prefers `sval` over `val` for FORMULA cells.
  Bool results also write `val=1/0` so aggregate functions still see a
  number. `IF(A1>0, "yes", "no")`, `="x" & "y"`, and `=1=1` all render
  correctly now.

- **`tui.py:1906`** pre-existing `assert headers is not None` replaced
  with an explicit None guard. Resolves the lone `S101` lint finding the
  repo had been carrying.

### Verified (no fix needed)

- **`_fixrefs` row/column swap semantics.** REVIEW.md flagged a suspected
  double-correction; tests in `test_swap_refs.py` confirm the unconditional
  rewrite is exactly how value-preservation works through `swaprow`/
  `swapcol`. Every formula computes the same value before and after a
  swap, including outside-swap formulas and absolute references.
- **Search direction coordinate ordering.** REVIEW.md flagged a suspected
  `(r, c)` vs `(col, row)` mismatch; tests in `test_search_direction.py`
  show both sides of the comparison are `(row, col)` and forward/backward
  search across same-row and cross-row matches behaves correctly.
- **Backwards-range auto-swap (`B1:A1` -> `A1:B1`).** Matches Excel.
  Comments added at both swap sites (`_expand_ranges` for LEGACY,
  `_eval_range` for EXCEL/HYBRID) marking the normalisation as intentional.

## [0.1.2]

### Added

- **Pandas DataFrame support in formulas**: Formulas that return pandas
  DataFrames or Series are stored on `Cell.matrix`. DataFrames display as
  `df[3x2]` in the grid, with column names shown in the status bar. Series
  results are automatically converted to DataFrames via `.to_frame()`.
  DataFrame equality uses `.equals()` for recalc convergence. Cells holding
  DataFrames with non-numeric first elements no longer display as ERROR.

- **`:view` command**: View the DataFrame or ndarray in the current cell as
  a scrollable table with column headers, row numbers, and keyboard
  navigation (arrows, PgUp/PgDn, Home/End). Works for both DataFrames and
  NumPy matrices.

- **`:pd load`/`:pd save` commands**: Import and export grid data using
  pandas. Auto-detects file format from extension: CSV, TSV, Excel
  (.xlsx/.xls), JSON, and Parquet. `:pd load` places column headers in
  row 1 and data below. `:pd save` uses row 1 as column headers. Full
  undo support on load.

- **CSV import/export** (`:csv save [file]`, `:csv load [file]`): Plain
  CSV export writes evaluated cell values (not formulas). Import parses
  numbers as NUM cells and text as LABELs. Full undo support on load.

- **Search** (`/`, `n`, `N`): Press `/` to enter a search pattern
  (case-insensitive substring match against cell text and evaluated numeric
  values). `n` jumps to the next match, `N` to the previous, both wrapping
  around. The status bar shows a `[3/12]` position indicator when the
  cursor is on a match.

- **Cell copy/paste** (`y`/`p`): `y` yanks the current cell (or visual
  selection) to an internal clipboard. `p` pastes at the cursor. Paste
  copies cell text verbatim (no reference adjustment, unlike `:r`),
  preserving styles (bold, underline, format). Full undo support.

- **`:sort` command**: Sort rows by a column. `:sort B` sorts all data
  rows by column B ascending. `:sort B desc` for descending. Numbers sort
  before labels; labels sort alphabetically; empties sort last. In visual
  mode, only the selected rows are sorted (useful for preserving headers).
  Full undo support.

- **Extended visual selection operations**: `:b` blanks all cells in the
  selection. `:dr` deletes all selected rows. `:dc` deletes all selected
  columns. `y` yanks the selection, `p` pastes at the selection origin.
  All operations support undo.

- **NumPy ndarray support in formulas**: Formulas that return numpy arrays
  (1-D or N-D) are stored in a new `Cell.matrix` field. Built-in spreadsheet
  functions (SUM, AVG, MIN, MAX, COUNT, ABS, SQRT, INT) now accept ndarrays
  in addition to `Vec` and scalar inputs. Matrix cells display a shape summary
  (e.g. `[3x3]`, `[5]`) in the grid and show element previews in the status
  bar. Matrix multiplication (`@`), `np.linalg.inv`, `np.linalg.det`, and
  other numpy operations work across cell references. 0-D arrays are
  transparently collapsed to scalars. Deep copy on `Cell.copy_from()` and
  proper cleanup on `setcell()` / `clear()` prevent stale matrix state.
  Convergence detection in `recalc()` correctly compares ndarrays to avoid
  false circular-reference marks.

- **Code block validation** (`sandbox.validate_code()`): AST-based security
  validation for code blocks (multi-statement `exec` mode), applying the same
  checks as formula validation (dunder access, dangerous names/attributes)
  plus import blocking for disallowed modules.

- **Syntax-highlighted code preview on load**: The startup trust prompt now
  displays the file's code block with Pygments syntax highlighting before
  asking the user to approve. The prompt options were simplified to
  `[l]oad code`, `[s]kip code`, `[q]uit`.

- 77 new tests: DataFrame formula evaluation (creation, column access,
  describe, filtering, groupby, Series conversion, recalc stability),
  pandas load/save (CSV, TSV, JSON, round-trip, no-header mode, error
  handling), DataFrame display formatting, CSV import/export (basic,
  empty grid, NaN, labels/numbers, round-trip, error paths), search
  (labels, numbers, formula values, case-insensitive, next/prev/wrap),
  search indicator, clipboard (yank/paste single/range, style preservation,
  formula verbatim copy, undo, empty noop), sort (by column, descending,
  labels, mixed types, visual selection, undo, invalid column), visual
  selection blank/delete (range blank, partial, row/col delete, undo),
  `:pd` and `:csv` command dispatch. 504 tests total.

- 17 new numpy/matrix tests in `test_engine.py` covering basic ndarray
  formulas, identity matrices, cell references, matmul, linalg operations,
  0-D scalar collapse, 1-D arrays, built-in function dispatch, cell display
  formatting, deep copy isolation, convergence stability, stale matrix
  cleanup, and circular matrix detection.

- 34 new sandbox tests in `test_sandbox.py` covering `validate_code()` for
  blocked imports, dunder access, dangerous names, and valid code acceptance.

### Changed

- **Sandbox enabled by default**: `GRIDCALC_SANDBOX` now defaults to enabled.
  Set `GRIDCALC_SANDBOX=0` to disable (previously required `=1` to enable).

- Added `numpy >= 1.24` and `pandas >= 2.0` as project dependencies.
  Added `types-Pygments` and `pandas-stubs` as dev dependencies for mypy.

## [0.1.1]

### Added

- **Security sandbox** (`gridcalc/sandbox.py`):
  - AST validation blocks dunder attribute access (`__class__`, `__subclasses__`,
    `__globals__`, etc.), dangerous names (`eval`, `exec`, `getattr`, `open`,
    `type`, etc.), and known internal attributes used in sandbox escape chains.
  - Module classification system: safe (numpy, scipy, etc.), side-effect
    (matplotlib, pandas), and blocked (os, subprocess, socket, pickle, etc.).
  - `load_modules()` imports approved third-party libraries into the formula
    eval namespace with standard aliases (numpy -> np, pandas -> pd, etc.).
  - Trust gate on file load: files containing code blocks or `requires` prompt
    the user before executing. Options: approve, formulas only, view code,
    cancel. Works in both curses (`:o` command) and plain terminal (startup).
  - `GRIDCALC_SANDBOX=1` env var or `sandbox = true` in config to enable checks.
    Off by default during development; tests run with sandbox enabled.
  - `Grid.jsoninspect()` extracts file metadata (cell/formula counts, code
    block preview, required modules, blocked module warnings) without executing.
  - `Grid.jsonload()` accepts an optional `LoadPolicy` controlling whether code
    blocks and modules are loaded.
  - See `docs/security-plan.md` for full threat model and architecture.

- **Configuration file** (`gridcalc/config.py`):
  - TOML-based config via `gridcalc.toml`.
  - Lookup order: `./gridcalc.toml` (CWD, project-local) then
    `$XDG_CONFIG_HOME/gridcalc/gridcalc.toml` (user-level, defaults to
    `~/.config/gridcalc/gridcalc.toml`). CWD overrides user config.
  - Settings: `editor` (default editor for `:e`, overridden by `EDITOR` env
    var), `sandbox` (enable security checks), `width` (default column width),
    `format` (default number format), `allowed_modules` (pre-approved modules
    for formulas).
  - See `gridcalc.toml.example` for all options.

- **Third-party module support**:
  - JSON file format extended with `"requires": ["numpy", ...]` field.
  - Modules listed in `allowed_modules` config or file `requires` are imported
    and injected into the formula eval namespace at startup/load.
  - Formulas can use library APIs directly: `=np.mean(A1:A10)`,
    `=decimal.Decimal('3.14')`, etc.

- **Circular reference detection**: `recalc()` now detects circular references
  via two strategies: oscillation detection (values that never stabilize across
  100 iterations) and static self-reference detection (formula text containing
  its own cell name). Circular cells are marked as NaN/ERROR and tracked in
  `Grid._circular`. The TUI status bar shows "CIRC" instead of "ERR 0" when
  the cursor is on a circular cell.

- **Visual select mode**: Press `v` to enter visual selection. Arrow keys
  extend the selection from the anchor cell; selected cells are highlighted
  in magenta. Press `:` to enter command mode with the selection active.
  `:f <fmt>` applies formatting to all non-empty cells in the selection.
  ESC cancels. Range formatting is undoable.

- **Format picker dialog**: `:f` with no argument now opens a modal picker
  listing all format options (bold, underline, italic, dollar, percent,
  integer, comma, bar chart, left/right align, general, use global) with
  descriptions for each. Navigate with arrow keys + Enter, press a key
  directly, or type a Python format spec (e.g. `,.2f`).

- **Formula libs** (`gridcalc/libs/`): pluggable function libraries for the
  formula eval namespace. Libs are composable (multiple can be active at
  once), registered in `libs/__init__.py`, and loaded via `Grid.load_lib()`.
  Configurable via `libs = ["xlsx"]` in `gridcalc.toml` or `"libs": ["xlsx"]`
  in the JSON file.

- **xlsx lib** (`gridcalc/libs/xlsx.py`): Excel-compatible functions:
  - Logical: IF, AND, OR, NOT, IFERROR
  - Math: ROUND, ROUNDUP, ROUNDDOWN, MOD, POWER, SIGN
  - Aggregates: AVERAGE, MEDIAN, SUMPRODUCT, LARGE, SMALL
  - Conditional: SUMIF, COUNTIF, AVERAGEIF (with criteria strings like
    `">5"`, `"<=10"`, `"<>0"`, wildcard `"*"`)
  - Lookup: VLOOKUP, HLOOKUP, INDEX, MATCH
  - Text: CONCATENATE, CONCAT, LEFT, RIGHT, MID, LEN, TRIM, UPPER,
    LOWER, PROPER, SUBSTITUTE, REPT, EXACT

- **Project review** (`REVIEW.md`).

- **TUI tests** (`tests/test_tui.py`): 47 new tests for `UndoManager`
  (undo/redo, empty-to-populated transitions, stack limits, style preservation,
  grid and region undo), `cmdexec` command dispatcher (quit, blank, clear,
  width, insert/delete row/col, save, format, title commands, unknown commands),
  and visual-select range formatting (dollar, bold, fmtstr, percent, combined
  styles, empty-cell skipping, undo, interactive picker) using a mock stdscr.

- 256 new tests (376 total) covering sandbox validation, module classification,
  module loading, load policies, file inspection, config parsing, config lookup
  order, integration tests for blocked formulas, policy-aware loading, requires
  roundtrips, circular reference detection, undo/redo, command dispatch,
  visual select range formatting, and xlsx mode functions.

- Added `tomli >= 1.0` (conditional, Python < 3.11 only) for TOML config
  parsing. Python 3.11+ uses stdlib `tomllib`.

### Changed

- **Sparse grid storage**: `Grid` now stores cells in a flat
  `dict[(col, row) -> Cell]` instead of pre-allocating a 256x1024 array of
  262,144 Cell objects. Only populated cells consume memory. A `_CellsProxy`
  compatibility layer preserves the `g.cells[c][r]` access pattern.
- **recalc() performance**: formula evaluation, cell value injection, and
  reference fixup now iterate only populated cells instead of scanning the
  full grid. Typical speedup is 100-200x for sparse sheets (test suite: 22s
  to 0.11s).
- **Insert/delete/swap row/col**: O(populated cells) via key remapping on the
  sparse dict, replacing O(NCOL * NROW) element-by-element shifting.
- **Undo/redo**: `save_grid` snapshots only populated cells. Grid-level undo
  restores via `clear_all()` + replay instead of full-grid iteration. Cell-level
  undo now records empty-cell state so undo correctly restores emptiness after
  edits.
- **Cell format type**: `Cell.fmt` changed from `int` (ord values like
  `ord("$")`) to `str` (`"$"`, `"%"`, `"I"`, etc., or `""` for none).
  Removes all `ord()`/`chr()` conversions in engine, TUI, and tests.
- **Comma format shorthand**: `:f ,` now formats as comma-thousands with zero
  decimal places (e.g. `1,234,567`) instead of the previous 6-decimal default.
  Explicit precision still works (`:f ,.2f` gives `1,234.50`).
- **File format version**: `jsonsave()` now writes `"version": 1` to output.
  `jsonload()` rejects files with a version higher than the current
  `FILE_VERSION`. Missing version is treated as 1 (backward compatible).
- **MAXCODE constant**: `cmd_edit` code block truncation now uses the `MAXCODE`
  constant (8192) instead of the magic expression `MAXIN * 32`.
- **Save deduplication**: `cmd_save` and `cmd_savequit` now share a single
  `_do_save()` helper for filename resolution, writing, and state update.
- **File inspection moved to sandbox**: `Grid.jsoninspect()` static method
  moved to `sandbox.inspect_file()`. It had zero Grid state access and only
  used sandbox types (`FileInfo`, `classify_module`). `engine.py` no longer
  imports `FileInfo` or `classify_module` -- its only sandbox dependency is
  `validate_formula` and `load_modules`.
- **Cell formatting moved to TUI**: `Grid.fmtcell()`, `fmt_float()`, and
  `_insert_commas()` moved from `engine.py` to `tui.py`. `fmtcell` is now a
  standalone function `fmtcell(cl, cw, global_fmt="")` -- a presentation
  concern that belongs alongside the display code, not the data model.
- `Grid.jsonload()` signature extended with optional `policy` parameter
  (backward compatible -- `None` trusts all, matching prior behavior).
- `Grid.jsonsave()` writes `requires` field when present.
- Formula evaluation in `recalc()` runs AST validation before `eval()` when
  sandbox is enabled.
- Editor command resolution: `EDITOR` env var > config `editor` > `"vi"`.
- Makefile `test` target sets `GRIDCALC_SANDBOX=1` so sandbox tests exercise
  real checks.
- **Strict mypy**: enabled `strict = true` in mypy config. Added type
  annotations to all functions, methods, and classes across engine.py,
  tui.py, config.py, and sandbox.py. Zero mypy errors under strict mode.
- **Renamed project**: pycalc -> gridcalc. Package directory, imports, config
  filename (`gridcalc.toml`), config paths (`~/.config/gridcalc/`), env var
  (`GRIDCALC_SANDBOX`), entry point, and all references updated.

## [0.1.0]

Initial release. Pure Python reimplementation of
[pktcalc](https://github.com/sa/pktcalc).

### Changed (vs pktcalc)

- Replaced C + pocketpy with pure Python. No compiled dependencies.
- Formula evaluation uses Python's `eval()` directly instead of an
  embedded pocketpy interpreter. Same formula syntax, same semantics.
- JSON load/save uses Python's `json` module instead of pocketpy's
  JSON API.
- Build/run via `uv` instead of CMake.

### Preserved

- Full feature parity with pktcalc:
  - Curses TUI with identical keybindings and vim-style command line.
  - JSON file format (files are interchangeable between pktcalc and gridcalc).
  - Python formulas with cell references (`A1`, `$A$1`), range syntax
    (`A1:A10`), named ranges, and custom code blocks.
  - Vec type for element-wise array arithmetic.
  - Built-in spreadsheet functions: SUM, AVG, MIN, MAX, COUNT, ABS,
    SQRT, INT.
  - Preloaded math functions: sin, cos, tan, exp, log, floor, ceil, etc.
  - Cell formatting: bold, underline, italic, number formats ($, %, I,
    *, L, R, G, D), Python format specs (e.g. `,.2f`, `.1%`).
  - Row/column insert, delete, swap, move, and replicate with automatic
    reference adjustment (relative and absolute refs).
  - Undo/redo (Ctrl-Z / Ctrl-Y) with 64-entry stack.
  - Title row/column locking.
  - Cell point-mode during formula entry (arrow keys insert refs).
  - Color scheme: blue chrome, cyan gutter, green cursor, yellow locked
    cells, magenta marks, red errors, per-mode status colors.
- 120 pytest tests covering expressions, recalc, vectors, ranges, cell
  references, JSON round-trips, swap/fixrefs, insert/delete, replicate,
  formatting, styles, and boundary conditions.
