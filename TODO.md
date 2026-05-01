# TODO

## Security

- [x] Default sandbox to enabled before any public release. Currently off by
  default -- untrusted `.json` files execute arbitrary Python (code blocks,
  `eval()` formulas) without a trust prompt unless `GRIDCALC_SANDBOX=1` or
  `sandbox = true` in config.
- [x] Validate code blocks with AST checks when sandbox is on. Currently
  `exec(self.code, g)` runs the code block with no AST validation -- only
  formulas go through `validate_formula()`. The trust prompt gates loading,
  but once loaded, code runs unrestricted with every recalc.
- [ ] Audit `chr`/`ord` availability in restricted builtins. Affects LEGACY
  mode only -- EXCEL and HYBRID modes do not use `eval()`. The sandbox blocks
  `eval`, `exec`, `getattr`, etc., but `chr` and `ord` are available via
  Python's implicit builtins, so a creative attacker could construct strings
  character by character to bypass name-based checks. Mitigation: encourage
  HYBRID for sheets that need user-defined functions; reserve LEGACY for
  trusted local sheets.

## Performance

- [ ] Topological recalc. The formula evaluator collects referenced cells
  during evaluation (`Env.refs_used`); a reverse dependency index would let
  recalc evaluate the transitive closure of changed cells in one pass and
  detect cycles structurally rather than by failing to converge in 100
  iterations. AST caching is already in place (text-keyed on `Cell.ast`).
- [ ] Phase 3: nanobind C++ port of the EXCEL evaluator (lexer, parser,
  tree walker, cell store, dependency graph). HYBRID mode would call back
  into Python only at the `py.*` gateway. Months of work; defer until the
  grammar and function library are stable.

## Modes & interop

- [ ] xlsx interop level (c): round-trip formulas, not just values. Requires
  the EXCEL grammar to be a strict subset of Excel's and the `xlsx` library's
  function semantics to match Excel bug-for-bug for the supported set.
- [ ] Multi-sheet xlsx workbooks. Currently `xlsxload` reads only the active
  sheet; subsequent sheets are dropped silently. Needs a multi-sheet model
  in `Grid` first.
- [ ] Sheet-qualified references (`Sheet1!A1`). Parser does not recognise
  them; they currently produce `#NAME?`. Blocked on multi-sheet support.
- [ ] `INDIRECT` is deliberately omitted (defeats static analysis and
  recalc ordering). Document the omission in user-facing docs.
- [ ] Migration tool `gridcalc migrate file.json`: attempts to upgrade a
  LEGACY file to HYBRID by reparsing each formula with the EXCEL grammar
  and reporting the unparseable ones.

## Features

- [ ] Visual select: extend beyond `:f` -- support `:b` (blank range),
  `:dr`/`:dc` (delete selected rows/cols), `:r` (replicate into selection),
  copy/paste within selection.
- [ ] Clipboard: system clipboard integration for copy/paste (currently
  only internal replicate).
- [x] Search: find cell by value or formula text (`/`).
- [x] CSV import/export alongside JSON.
- [ ] Multiple sheets / tabs within a single file (also unblocks multi-sheet
  xlsx interop).
- [ ] Mouse support (curses mouse events for cell selection and scrolling).
- [ ] Plugin interface for extending gridcalc. Allow third-party packages
  to register custom functions, commands, and cell formats via entry points
  or a plugin API.

## Documentation

- [ ] Add mkdocs documentation site (mkdocs-material). Publish to GitHub
  Pages via `gh-pages` branch or GitHub Actions.
- [ ] Document the EXCEL grammar (operators, precedence, error values,
  function library) in a dedicated reference page.

## Code quality

- [ ] `tui.py` is 2,500+ lines. Split into modules: drawing, commands,
  entry/navigation, undo, visual mode. Five near-duplicate input loops
  could be extracted into a single `read_line(prompt, validator)` helper.
- [ ] `recalc()` silently swallows code-block exceptions via
  `contextlib.suppress(Exception)`. Surface errors so users can debug
  custom functions. The EXCEL/HYBRID path already converts errors to
  `ExcelError` values, but the legacy path is still silent.
- [ ] `requires` field has no version pinning -- `"requires": ["numpy"]`
  loads whatever version is installed. Version constraints would improve
  reproducibility.
- [ ] Audit `libs/xlsx.py` against the Excel spec for the functions it
  claims (especially `VLOOKUP`/`HLOOKUP` approximate-match, `MATCH` with
  `match_type`, `SUMIF`/`COUNTIF` criteria edge cases).
- [ ] `Cell.ast` cache is invalidated by text comparison; consider hashing
  for very large sheets where many formulas share text.
- [ ] README mentions an outdated test count -- update on every release.

## Known correctness issues (from REVIEW.md)

- [ ] `_fixrefs` row/column swap rewrites references regardless of which
  row the formula lives in -- likely a double-correction. Add tests that
  exercise "formula references a swapped row from outside the swap" and
  fix the semantics.
- [ ] Search direction comparison (`tui.py:1840-1856`) mixes `(r, c)` vs
  `(col, row)` between the two sides of the tuple comparison. Add a test
  that searches forward across multiple matches on the same row.
- [ ] Backwards-range auto-swap (`B1:A1` -> `A1:B1`) silently changes user
  intent. Document or warn.
