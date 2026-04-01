# Changelog

## Unreleased

### Added

- **Security sandbox** (`pycalc/sandbox.py`):
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
  - `PYCALC_SANDBOX=1` env var or `sandbox = true` in config to enable checks.
    Off by default during development; tests run with sandbox enabled.
  - `Grid.jsoninspect()` extracts file metadata (cell/formula counts, code
    block preview, required modules, blocked module warnings) without executing.
  - `Grid.jsonload()` accepts an optional `LoadPolicy` controlling whether code
    blocks and modules are loaded.
  - See `docs/security-plan.md` for full threat model and architecture.

- **Configuration file** (`pycalc/config.py`):
  - TOML-based config via `pycalc.toml`.
  - Lookup order: `./pycalc.toml` (CWD, project-local) then
    `$XDG_CONFIG_HOME/pycalc/pycalc.toml` (user-level, defaults to
    `~/.config/pycalc/pycalc.toml`). CWD overrides user config.
  - Settings: `editor` (default editor for `:e`, overridden by `EDITOR` env
    var), `sandbox` (enable security checks), `width` (default column width),
    `format` (default number format), `allowed_modules` (pre-approved modules
    for formulas).
  - See `pycalc.toml.example` for all options.

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

- **Project review** (`REVIEW.md`).

- **TUI tests** (`tests/test_tui.py`): 47 new tests for `UndoManager`
  (undo/redo, empty-to-populated transitions, stack limits, style preservation,
  grid and region undo), `cmdexec` command dispatcher (quit, blank, clear,
  width, insert/delete row/col, save, format, title commands, unknown commands),
  and visual-select range formatting (dollar, bold, fmtstr, percent, combined
  styles, empty-cell skipping, undo, interactive picker) using a mock stdscr.

- 185 new tests (305 total) covering sandbox validation, module classification,
  module loading, load policies, file inspection, config parsing, config lookup
  order, integration tests for blocked formulas, policy-aware loading, requires
  roundtrips, circular reference detection, undo/redo, command dispatch, and
  visual select range formatting.

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
- `Grid.jsonload()` signature extended with optional `policy` parameter
  (backward compatible -- `None` trusts all, matching prior behavior).
- `Grid.jsonsave()` writes `requires` field when present.
- Formula evaluation in `recalc()` runs AST validation before `eval()` when
  sandbox is enabled.
- Editor command resolution: `EDITOR` env var > config `editor` > `"vi"`.
- Makefile `test` target sets `PYCALC_SANDBOX=1` so sandbox tests exercise
  real checks.

### Dependencies

- Added `tomli >= 1.0` (conditional, Python < 3.11 only) for TOML config
  parsing. Python 3.11+ uses stdlib `tomllib`.

## 0.1.0 - 2026-03-23

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
  - JSON file format (files are interchangeable between pktcalc and pycalc).
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
