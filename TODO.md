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

- [ ] **Topological recalc.** The formula evaluator collects referenced
  cells during evaluation (`Env.refs_used`); a reverse dependency
  index keyed on those would let recalc evaluate only the transitive
  closure of changed cells, detect cycles structurally, and remove
  the 100-iteration convergence cap. AST caching is already in place
  (text-keyed on `Cell.ast`).
- [ ] **Memoize named-range Vecs within a recalc.** `Env` is built once
  per recalc but `_eval_name` re-fetches all cells of a range on every
  formula evaluation that mentions the name. Cache the materialised
  Vec keyed on the named range's text.
- [ ] **Phase 3: nanobind C++ port of the EXCEL evaluator** (lexer,
  parser, tree walker, cell store, dependency graph). HYBRID would
  cross back into Python only at the `py.*` gateway. Months of work;
  defer until the grammar and function library have soaked in real
  use.
- [ ] **Wrap OpenXLSX (C++) via nanobind for xlsx I/O.**
  [OpenXLSX](https://github.com/troldal/OpenXLSX) is a fast, header-
  capable C++ Excel reader/writer that doesn't depend on a Python xlsx
  stack. Replacing openpyxl with a nanobind-wrapped OpenXLSX would cut
  load/save time on large workbooks substantially and drop a heavy
  pure-Python dependency. Scope: thin nanobind module exposing
  `Workbook`, `Worksheet`, `Cell`-level read/write of value, formula,
  type, and the iter-rows path; gridcalc's `xlsxload`/`xlsxsave` swap
  to call it; openpyxl moves to an optional fallback or drops out.
  Couple to phase 3 -- if the EXCEL evaluator is going native, the
  xlsx codec might as well too. Risks: build matrix complexity (must
  ship wheels per platform), licensing audit (OpenXLSX is BSD-3),
  date/time and styled-cell coverage gaps vs. openpyxl.

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
  the supported set.
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
- [ ] **mkdocs documentation site** (mkdocs-material). Publish to
  GitHub Pages via `gh-pages` branch or GitHub Actions.
- [ ] **EXCEL grammar reference page.** Operators, precedence, error
  values, the function library, mode semantics. Lives in the docs
  site once it exists.
- [ ] **Document `INDIRECT` omission** in user-facing docs (deliberately
  unsupported because it defeats static analysis and recalc ordering).
