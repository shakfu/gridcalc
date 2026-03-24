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

- **Project review** (`REVIEW.md`).

- 131 new tests (251 total) covering sandbox validation, module classification,
  module loading, load policies, file inspection, config parsing, config lookup
  order, and integration tests for blocked formulas, policy-aware loading, and
  requires roundtrips.

### Changed

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
