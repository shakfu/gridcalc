# Changelog

## Unreleased

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
