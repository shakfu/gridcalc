# TODO

Open tasks, ordered by priority within each section. Resolved items live in
CHANGELOG.md.

## Robustness & safety

- [ ] **LEGACY recalc swallows code-block exceptions.** The
  `contextlib.suppress(Exception)` in `_recalc_legacy` hides every
  failure from custom functions. EXCEL/HYBRID already produce typed
  `ExcelError` values; bring the legacy path in line by adding a
  per-cell error field that the TUI can render uniformly.
- [ ] **`chr`/`ord` reachable from LEGACY formulas.** Affects LEGACY
  mode only (EXCEL/HYBRID don't use `eval()`). Drop them from the
  restricted globals, or reject `getattr` with a non-literal second
  argument so that runtime-constructed dunder names can't slip past
  the AST blocklist.
- [ ] **Mutable shared `__builtins__` in LEGACY recalc.** `_eval_globals`
  is reused across all formula evaluations within a recalc, so a single
  successful escape that mutates `g['__builtins__']` poisons every
  subsequent formula. Wrap with `types.MappingProxyType` or build a
  fresh globals dict per cell.
- [ ] **No persistent banner when sandbox is disabled.** A user with
  `sandbox = false` in config gets no on-screen reminder that loaded
  code is running unrestricted. Render a banner in the status row.
- [ ] **Trust prompt shows truncated code preview.** The user authorises
  based on `info.code_preview` but the full block is what executes.
  Either page through the full block or refuse to run blocks longer
  than the preview.
- [ ] **Undo/redo apply is non-atomic.** `_apply` mutates the grid
  before the reverse-entry capture completes, so a partial failure
  mid-restore can drift the stack and the grid out of sync. Wrap in
  try/except and reject the operation atomically rather than partially
  restoring.
- [ ] **Config loader silently accepts garbage.** `tomllib.TOMLDecodeError`
  is swallowed, unknown keys are ignored, and out-of-range numeric
  values pass through. Validate width and other numeric bounds; warn
  on unknown keys; surface TOML parse errors to stderr.

## Performance

- [ ] **Range subscriber explosion (Phase E from `docs/topological.md`).**
  `SUM(A1:Z1000)` registers 26000 reverse-index entries. Replace with
  an interval representation (per-column interval tree, or aggregation
  nodes that fan out at change time). Defer until profiling shows
  large-range workloads as a hot spot.
- [ ] **Use `#REF!` (or a dedicated `#CIRC!`) for cycle cells**
  instead of NaN. Cosmetic but matches Excel semantics; would require
  surfacing an error type into `Cell.val` or a parallel error field.
- [ ] **Delete the legacy fixed-point recalc path** (`Grid._recalc_formula`).
  Topo recalc is the default; the fixed-point loop is retained one
  release as a fallback gated by `_use_topo_recalc = False` /
  `GRIDCALC_TOPO=0`. After a soak period, drop the fallback, the env
  hook in `tests/conftest.py`, and the `_use_topo_recalc` flag.
- [ ] **Memoize named-range Vecs within a recalc.** `Env` is built once
  per recalc but `_eval_name` re-fetches all cells of a range on every
  formula evaluation that mentions the name. Cache the materialised
  Vec keyed on the named range's text.
- [ ] **Targeted C++ acceleration for measured hot spots.** A full
  C++ evaluator port (lexer + parser + tree walker + cell store +
  dep graph) is not justified by current benchmarks: topological
  recalc closed the gap that originally motivated it. Surgical edits
  on 10k-cell sheets are <0.1 ms; xlsxload of 5k cells is ~12 ms;
  long-chain edits are single-digit ms. A wholesale port would
  duplicate the function library in C++, complicate the HYBRID
  `py.*` gateway with three-way Python<->C++ bouncing, and slow
  development velocity (rebuild required for every formula-system
  change). If a real workload exposes a hot spot, C++ that single
  component (Vec arithmetic in `engine.py:87-129`, range
  materialization in `_expand_ranges`, or the closure BFS in
  `_recalc_topo`) -- a few hundred lines, not thousands. See git
  history for the original "Phase 3" entry if scope ever shifts.

## Refactoring & code quality

- [ ] **`tui.py` is 2,500+ lines.** Split into modules: drawing,
  commands, entry/navigation, undo, visual mode. Five near-duplicate
  input loops in `cmdline()`, `nav()`, `selectrange()`, `_resolve_fmt()`,
  and `replcmd()` should collapse into a single
  `read_line(prompt, validator)` helper.
- [ ] **`refabs` returns an unnamed 5-tuple.** Promote to a `NamedTuple`
  or small dataclass so call sites self-document.
- [ ] **`Cell.ast` cache invalidates by text equality.** For very large
  sheets where many formulas share text, hashing the text would cut
  cache lookups; not a priority but worth measuring.
- [ ] **Audit `libs/xlsx.py` against the Excel spec.** Especially
  `VLOOKUP`/`HLOOKUP` approximate-match, `MATCH` with non-default
  `match_type`, and `SUMIF`/`COUNTIF` criteria edge cases.
- [ ] **`ADDRESS`** -- mostly mechanical: build an A1-style string from
  `(row, col, [abs_num], [r1c1_style], [sheet])`. No evaluator change
  needed. Defer until someone needs it.
- [ ] **Tier 3 function round-out (~50 functions, mechanical).**
  Mostly-mechanical fill-ins that complete common categories without
  architectural change. Group as a single PR when prioritized:
    - **Aggregates**: `COUNTA`, `COUNTBLANK`, `PRODUCT`, `AVERAGEA`,
      `MAXA`, `MINA`.
    - **Stats (modern names)**: `STDEV.S`, `STDEV.P`, `VAR.S`, `VAR.P`,
      `MODE.SNGL`, `MODE.MULT`, `COVARIANCE.P`, `COVARIANCE.S`,
      `PERCENTILE.INC`, `PERCENTILE.EXC`, `QUARTILE.INC`,
      `QUARTILE.EXC`, `RANK.EQ`, `RANK.AVG`. (Aliases for existing
      implementations; needs name-with-dot support in the parser/lexer
      -- check if `.` is already accepted in function names.)
    - **Stats (additional)**: `AVEDEV`, `DEVSQ`, `SLOPE`, `INTERCEPT`,
      `RSQ`, `STEYX`, `SKEW`, `KURT`, `PERCENTRANK`.
    - **Date**: `DAYS`, `DAYS360`, `WEEKNUM`, `ISOWEEKNUM`, `YEARFRAC`.
    - **Information**: `ERROR.TYPE`, `TYPE`, `ISFORMULA`, `ISREF`,
      `ISNONTEXT` (`CELL` deferred -- needs format/style metadata
      surface).
    - **Text**: `CLEAN`, `NUMBERVALUE`, `FIXED`, `DOLLAR`, `T`,
      `UNICHAR`, `UNICODE`.
    - **Math**: `COMBIN`, `COMBINA`, `PERMUT`, `PERMUTATIONA`,
      `MULTINOMIAL`, `QUOTIENT`, `CEILING.MATH`, `FLOOR.MATH`,
      `RADIANS`, `DEGREES` (last two need uppercase aliases for the
      `math.radians`/`math.degrees` already in `_eval_globals`).
    - **Math (paired sums)**: `SUMSQ`, `SUMX2MY2`, `SUMX2PY2`, `SUMXMY2`.
    - **Hyperbolic trig**: `SINH`, `COSH`, `TANH`, `ASINH`, `ACOSH`,
      `ATANH`.
    - **Bitwise**: `BITAND`, `BITOR`, `BITXOR`, `BITLSHIFT`, `BITRSHIFT`.
    - **Random (volatile)**: `RAND`, `RANDBETWEEN` -- must register in
      `formula.deps.DYNAMIC_REF_FUNCS` (or a new `VOLATILE_FUNCS` set)
      so the topo path adds them to the closure on every recalc.
  `TRANSPOSE` is *not* in this list -- it returns a reshaped array,
  which requires a 2D-aware result type; defer to dynamic-array work.
- [ ] **`OFFSET`** -- dynamic-ref function (already in `DYNAMIC_REF_FUNCS`
  for volatile flagging). Needs the evaluator to materialise a reference
  result (not just a value) so chained constructs like
  `SUM(OFFSET(A1, 1, 0, 5, 1))` work. Out of scope without a reference
  type in the value system.
- [ ] **Excel 365 dynamic arrays**: `FILTER`, `SORT`, `UNIQUE`,
  `SEQUENCE`, `RANDARRAY`, `LET`, `LAMBDA`, `XLOOKUP`, `XMATCH`.
  These spill into adjacent cells and need architectural support
  beyond just adding functions.
- [ ] **Date type system in xlsx I/O.** `_core.xlsx_read` collapses
  date serials into `XLValueType::Float`. Need to read the cell's
  number format to distinguish dates from numbers, and a per-cell
  `Cell.fmtstr` extension to render serials as formatted dates in
  the TUI.
- [ ] **`requires` field has no version pinning.**
  `"requires": ["numpy"]` loads whatever version is installed. Version
  constraints would improve reproducibility.

## Features

- [ ] **Multiple sheets / tabs within a single file.** Unblocks
  multi-sheet xlsx import and sheet-qualified references.
- [ ] **Multi-sheet xlsx interop.** Currently `xlsxload` reads only
  the active sheet; subsequent sheets are dropped silently. Blocked
  on multi-sheet support.
- [ ] **Sheet-qualified references (`Sheet1!A1`).** Parser does not
  recognise them; they currently produce `#NAME?`. Blocked on
  multi-sheet support.
- [ ] **xlsx interop level (c): round-trip formulas, not just values.**
  Requires the EXCEL grammar to be a strict subset of Excel's and the
  `xlsx` library's function semantics to match Excel bug-for-bug for
  the supported set. The `_core.xlsx_write` path currently writes
  evaluated values only; formula write-through needs `cell.formula().set()`
  and a serialiser for the EXCEL AST back to Excel-grammar text.
- [ ] **Date/time and styled-cell coverage in `_core` xlsx I/O.**
  `XLValueType` does not distinguish date serials from floats; styles
  and number formats are not read or written. openpyxl-backed gridcalc
  did not handle these either, so this is a known gap to plan, not a
  regression.
- [ ] **Migration tool `gridcalc migrate file.json`.** Attempts to
  upgrade a LEGACY file to HYBRID by reparsing each formula with the
  EXCEL grammar and reporting the unparseable ones.
- [ ] **Visual-select operations.** Extend beyond `:f` -- support
  `:b` (blank range), `:dr`/`:dc` (delete selected rows/cols),
  `:r` (replicate into selection), copy/paste within selection.
- [ ] **System clipboard integration** for copy/paste (currently only
  internal replicate).
- [ ] **Mouse support** (curses mouse events for cell selection and
  scrolling).
- [ ] **Plugin interface.** Allow third-party packages to register
  custom functions, commands, and cell formats via entry points or a
  plugin API.

## Documentation & infrastructure

- [ ] **CI workflow running `make qa` on push.** One-file change;
  catches regressions and prevents lint findings (e.g. the `S101`
  that lived for releases) from sneaking back in.
- [ ] **Wheel build matrix.** scikit-build-core + the vendored OpenXLSX
  mean sdist installs require a C++17 toolchain, CMake, and network
  access for the FetchContent of pugixml/miniz/nowide. Ship prebuilt
  wheels for macOS (x86_64, arm64), Linux (manylinux x86_64, aarch64),
  and Windows so `pip install gridcalc` works without a compiler. Once
  wheels exist, drop the documented build prerequisites note.
- [ ] **mkdocs documentation site** (mkdocs-material). Publish to
  GitHub Pages via `gh-pages` branch or GitHub Actions.
- [ ] **EXCEL grammar reference page.** Operators, precedence, error
  values, the function library, mode semantics. Lives in the docs
  site once it exists.
- [ ] **Document `INDIRECT` omission** in user-facing docs (deliberately
  unsupported because it defeats static analysis and recalc ordering).
