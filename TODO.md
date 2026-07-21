# TODO

Open tasks, ordered by priority within each section. Resolved items live in
CHANGELOG.md.

## Direction

Excel-function parity is a race gridcalc cannot win and does not need to:
Excel has ~480 functions and every spreadsheet user already owns it. What
nothing else offers is **optimization with spreadsheet semantics in a
terminal** -- `:opt` and `:goal` over a live grid, scriptable, workbook-
persistent. Excel's Solver is a modal dialog with a famously unhelpful
failure mode; PuLP and pyomo make you write the model in code with no
spatial view of the data. That gap is the thing worth widening.

So: prefer work under **Optimization** below over work that closes an
Excel-coverage gap, unless the coverage gap is blocking a real sheet.
The parity items are kept because they are genuinely useful, not because
they are the strategy.

## Optimization

- [x] Sensitivity analysis (`:opt sens`) -- shadow prices, reduced costs,
      RHS and objective ranging. See CHANGELOG.
- [x] Infeasibility diagnosis -- irreducible conflicting constraint set
      reported automatically on `INFEASIBLE`. See CHANGELOG.
- [x] Unboundedness diagnosis -- names the runaway variable on
      `UNBOUNDED`. See CHANGELOG. (Note for future work: lp_solve has no
      extreme-ray accessor; `is_unbounded` reports a *declaration*, not a
      ray. The diagnosis re-solves per variable instead.)
- [x] Parametric RHS sweep (`:opt sweep`) -- re-solves across a range and
      flags where the marginal value changes. See CHANGELOG. Built on
      `solve(rhs_override=...)`, which is also usable directly.
- [ ] **Quadratic / convex objectives.** lp_solve is LP/MIP only, so this
      needs a second solver backend -- it is not an extension of the
      existing one. Scoping notes, so the decision is made with the cost
      visible rather than discovered halfway in:

      * **Vendor a QP solver.** OSQP (Apache-2.0, small C, ADMM-based) is
        the natural fit and would sit alongside `thirdparty/lp_solve_5.5`
        with its own CMake target and nanobind wrapper. Note the licence
        difference: lp_solve is LGPL, OSQP is Apache-2.0 -- check what the
        combination means for the wheel before starting.
      * **Extend the AST walker.** `extract_linear` rejects `A1*A2` as
        `NotLinear`. A QP needs an `extract_quadratic` producing a Q matrix
        plus a linear term, with convexity checked (a non-convex Q has no
        tractable global optimum and must be refused, not solved badly).
      * **Decide the surface.** Whether `:opt` silently routes quadratic
        objectives to the QP backend or the user opts in explicitly. Silent
        routing hides which solver produced an answer, which matters
        because the failure modes differ.
      * **Cross-platform build risk.** A second vendored C library has to
        build on macOS, Linux and Windows wheels; this is the part that
        cannot be validated locally and is the main schedule risk.

      Still gated on a real sheet needing it. Nothing in the current
      examples does.
- [x] `:opt` on a visual selection -- infers objective, decision cells and
      constraints from the selected block. See CHANGELOG.
- [x] Report sensitivity into cells (`:opt sens into <cell>`) -- writes
      NUM cells so shadow prices feed downstream formulas. See CHANGELOG.

## Performance

- [ ] **Range subscriber explosion (Phase E from `docs/topological.md`).**
  `SUM(A1:Z1000)` registers 26000 reverse-index entries. Replace with
  an interval representation (per-column interval tree, or aggregation
  nodes that fan out at change time). Defer until profiling shows
  large-range workloads as a hot spot.
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

- [ ] **`Cell.ast` cache invalidates by text equality.** For very large
  sheets where many formulas share text, hashing the text would cut
  cache lookups; not a priority but worth measuring.
- [ ] **Remaining `libs/xlsx.py` Excel-fidelity gaps.** The lookup /
  criteria / conditional-aggregate audit sweep is done (see CHANGELOG).
  Left open, each gated on a missing primitive or genuinely ambiguous in
  Excel: numeric-vs-text criteria coercion (`COUNTIF({1,2,"3"}, 3)`);
  date-string criteria like `">1/1/2020"` (needs date-aware criteria
  parsing -- gated on the date-type system below); and `SUMIF`/`COUNTIF`
  with a `sum_range` shorter than the criteria range (Excel resizes from
  the top-left, which needs reference rather than materialised-`Vec`
  semantics -- gated on the reference type the `OFFSET` item needs).
- [ ] **`OFFSET`** -- dynamic-ref function (already in `DYNAMIC_REF_FUNCS`
  for volatile flagging). Needs the evaluator to materialise a reference
  result (not just a value) so chained constructs like
  `SUM(OFFSET(A1, 1, 0, 5, 1))` work. Out of scope without a reference
  type in the value system.
- [ ] **`LAMBDA` and dynamic-array spill.** `LET` and 2D-aware
  `SORT`/`UNIQUE`/`FILTER` are done (see CHANGELOG). Still missing:
  `LAMBDA` -- needs a first-class function value type and call-on-
  expression in the grammar (`Call.name` is a string today, so only
  named calls exist), plus the higher-order helpers (MAP/REDUCE/BYROW/
  ...) that make it useful. And true spill into adjacent cells (writing
  array results into neighbouring cells rather than packing them into
  one cell's `arr`/`matrix`) remains the architectural piece. Minor:
  `deps` over-approximates when a `LET` name shadows a real named range
  (the range stays recorded as a dep) -- safe, just an occasional extra
  recalc; tighten only if it ever matters.
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
- [ ] **TUI keybindings system -- v2 generalisations.** All five
  contexts are wired (`grid`, `entry`, `visual`, `cmdline`, `search`)
  with curated action vocabularies; see `docs/keybindings.md`.
  Outstanding gaps for a future iteration:
  (a) **Removing hardcoded defaults.** `[keys.<ctx>] cancel = []`
      currently does *not* unbind Esc, because the hardcoded
      fallback chain still matches `ch == 27`. To make unbind work,
      the hardcoded chain has to migrate fully into
      `DEFAULT_KEYMAP` and the contexts must dispatch only via the
      action lookup. Mechanical but tedious.
  (b) **Bind-to-`:command`.** The action vocabulary is fixed at
      module load time. If users want `[keys.grid] save = [...]`
      where "save" runs `:w`, the schema has to grow a way to carry
      the command text alongside the key spec, and an
      `exec_command`-style action that takes parameters. Out of
      scope until someone asks.
  (c) **Pick-mode actions in entry.** The `KEY_UP`/`KEY_DOWN`
      cursor-pick sub-mode in `entry` is too tangled with local
      state to expose as actions today. Refactor it to a small
      state machine before binding it.
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
- [ ] **System clipboard -- follow-ups.** Core integration is done (see
  CHANGELOG). Remaining: full CSV-style quoting for cells containing
  tabs/newlines (currently sanitised to spaces), and verifying the
  Windows/Linux backends (`wl-clipboard`/`xclip`/`xsel`, `clip`/
  `Get-Clipboard`) on real hardware -- developed on macOS against a fake
  backend.
- [ ] **Mouse support** (curses mouse events for cell selection and
  scrolling).
- [ ] **Plugin interface.** Allow third-party packages to register
  custom functions, commands, and cell formats via entry points or a
  plugin API.

## Documentation & infrastructure

- [ ] **mkdocs documentation site** (mkdocs-material). Publish to
  GitHub Pages via `gh-pages` branch or GitHub Actions.
- [ ] **EXCEL grammar reference page.** Operators, precedence, error
  values, the function library, mode semantics. Lives in the docs
  site once it exists.
