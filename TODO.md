# TODO

Open tasks, ordered by priority within each section. Resolved items live in
CHANGELOG.md.

## Performance

- [ ] **Range subscriber explosion (Phase E from `docs/topological.md`).**
  `SUM(A1:Z1000)` registers 26000 reverse-index entries. Replace with
  an interval representation (per-column interval tree, or aggregation
  nodes that fan out at change time). Defer until profiling shows
  large-range workloads as a hot spot.
- [ ] **Delete the legacy fixed-point recalc path** (`Grid._recalc_formula`).
  Topo recalc is the default; the fixed-point loop is retained one
  release as a fallback gated by `_use_topo_recalc = False` /
  `GRIDCALC_TOPO=0`. After a soak period, drop the fallback, the env
  hook in `tests/conftest.py`, and the `_use_topo_recalc` flag.
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
- [ ] **`Cell.ast` cache invalidates by text equality.** For very large
  sheets where many formulas share text, hashing the text would cut
  cache lookups; not a priority but worth measuring.
- [ ] **Audit `libs/xlsx.py` against the Excel spec.** Especially
  `VLOOKUP`/`HLOOKUP` approximate-match, `MATCH` with non-default
  `match_type`, and `SUMIF`/`COUNTIF` criteria edge cases.
- [ ] **`OFFSET`** -- dynamic-ref function (already in `DYNAMIC_REF_FUNCS`
  for volatile flagging). Needs the evaluator to materialise a reference
  result (not just a value) so chained constructs like
  `SUM(OFFSET(A1, 1, 0, 5, 1))` work. Out of scope without a reference
  type in the value system.
- [ ] **Excel 365 dynamic arrays -- gaps and spill audit.**
  `XLOOKUP`, `XMATCH`, `FILTER`, `SORT`, `UNIQUE`, `SEQUENCE`,
  `RANDARRAY`, `TRANSPOSE` are already implemented in `libs/xlsx.py`
  (returning `Vec`). Still missing: `LET`, `LAMBDA` (need parser/eval
  support for local bindings and user-defined inline functions, not
  just a function entry). Audit the implemented ones for true spill
  semantics -- e.g. `SORT` docstring notes 2D is "reserved and
  ignored", so multi-column behaviour likely doesn't match Excel.
  Spill into adjacent cells (writing results into neighbouring cells
  rather than packing into one cell's `arr`/`matrix`) is still
  unimplemented and is the architectural piece.
- [ ] **Date type system in xlsx I/O.** `_core.xlsx_read` collapses
  date serials into `XLValueType::Float`. Need to read the cell's
  number format to distinguish dates from numbers, and a per-cell
  `Cell.fmtstr` extension to render serials as formatted dates in
  the TUI.

## Features

- [ ] **3D range references (`Sheet1:Sheet3!A1:B2`).** Currently
  unsupported: `_expand_ranges` (engine.py:582) only recognises the
  `<ref>:<ref>` shape, so a sheet-span prefix passes through unexpanded
  and the formula evaluates to `nan`. Workaround in user files is to
  expand manually, e.g. `=SUM(Jan!B2:B3)+SUM(Feb!B2:B3)` instead of
  `=SUM(Jan:Feb!B2:B3)` (see `examples/example_multisheet.xlsx`). To
  implement: (1) extend `ref`/`refabs` (engine.py:529, 552) to recognise
  the `<sheet>:<sheet>!<cell>[:<cell>]` shape; (2) add a pre-pass (or
  branch in `_expand_ranges`) that enumerates sheets between the two
  named endpoints in workbook order and emits a `Vec([...])` over
  every (sheet, cell) pair; (3) decide rebind semantics on
  `move_sheet`/`rename_sheet` -- Excel binds 3D refs to sheet
  *position* between the endpoints, so reordering changes which sheets
  are summed, while renaming an endpoint should rewrite the formula
  text the same way `_rewrite_sheet_prefix` (engine.py:731) handles
  single-sheet refs; (4) extend dependency tracking so cells in the
  spanned sheets register as subscribers, and a `move_sheet`/`add_sheet`
  between the endpoints invalidates the cached recalc.
- [ ] **TUI keybindings system.** A separate effort to design the
  custom-keybinding story (config file? schema? sane defaults? a
  conflict-detection layer?). Sheet cycling (e.g. PgUp/PgDn in the
  main grid) is one candidate user; the broader question is how
  users opt into custom keymaps without forking the source.
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

- [ ] **Wheel build matrix -- aarch64 / manylinux variants.** Linux
  (ubuntu-latest), macOS (macos-latest), and Windows (windows-latest)
  wheels for cp39-cp313 are already built by
  `.github/workflows/build-publish.yml` via cibuildwheel. Verify the
  resulting matrix actually covers manylinux x86_64 *and* aarch64,
  and macOS arm64 (the `runs-on: macos-latest` runner produces arm64
  but x86_64 may need a separate job). Once confirmed end-to-end,
  drop the documented build prerequisites note.
- [ ] **mkdocs documentation site** (mkdocs-material). Publish to
  GitHub Pages via `gh-pages` branch or GitHub Actions.
- [ ] **EXCEL grammar reference page.** Operators, precedence, error
  values, the function library, mode semantics. Lives in the docs
  site once it exists.
