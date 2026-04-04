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
- [ ] Audit `chr`/`ord` availability in restricted builtins. The sandbox
  blocks `eval`, `exec`, `getattr`, etc., but `chr` and `ord` are available
  via Python's implicit builtins. A creative attacker could construct strings
  character by character to bypass name-based checks.

## Performance

- [ ] Dependency graph for recalc. Currently recalc iterates all populated
  formula cells up to 100 times until values stabilize. A topological sort
  on cell dependencies would allow single-pass evaluation for acyclic
  graphs and immediate cycle detection without the 100-iteration limit.

## Features

- [ ] Visual select: extend beyond `:f` -- support `:b` (blank range),
  `:dr`/`:dc` (delete selected rows/cols), `:r` (replicate into selection),
  copy/paste within selection.
- [ ] Clipboard: system clipboard integration for copy/paste (currently
  only internal replicate).
- [ ] Search: find cell by value or formula text (`:find` or `/`).
- [ ] CSV import/export alongside JSON.
- [ ] Multiple sheets / tabs within a single file.
- [ ] Mouse support (curses mouse events for cell selection and scrolling).
- [ ] Plugin interface for extending gridcalc. Allow third-party packages
  to register custom functions, commands, and cell formats via entry points
  or a plugin API.

## Documentation

- [ ] Add mkdocs documentation site (mkdocs-material). Publish to GitHub
  Pages via `gh-pages` branch or GitHub Actions.

## Code quality

- [ ] `tui.py` is 1,500+ lines. Consider splitting into modules: drawing,
  commands, entry/navigation, undo, visual mode.
- [ ] `recalc()` silently swallows all exceptions from code blocks via
  `contextlib.suppress(Exception)`. Consider logging or surfacing errors
  to help users debug their custom functions.
- [ ] `requires` field has no version pinning -- `"requires": ["numpy"]`
  loads whatever version is installed. Version constraints would improve
  reproducibility.
- [ ] README says "120 pytest tests" -- now 305. Update Development section.
