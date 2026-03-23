# Changelog

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
