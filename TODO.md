# TODO

Open tasks, ordered by priority within each section. Resolved items live in CHANGELOG.md.

## Critical

## High

### Refactoring & code quality

- [ ] **`COUNT` and `COUNTA` count blank cells inside a range.** `=COUNT(A1:C3)` over a range holding one number, one label and seven empties answers 8 and `=COUNTA` answers 9; Excel answers 1 and 2. Blank cells materialise into the range `Vec` as `0.0`, so nothing downstream can tell an empty cell from a zero -- the fix is in range materialisation, not in the counting functions. Found while making the aggregates variadic. `=COUNTIF(A1:C3,"*")` answers 9 for the same reason; Excel counts text cells only.

- [ ] **TUI `:o` raises on a non-JSON file.** `cmd_open` calls `sandbox.inspect_file` outside any `try`, and `inspect_file` raises `UnicodeDecodeError` on an `.xlsx` or non-UTF-8 file and `RecursionError` on deeply nested JSON. `cmd_open` also always calls `jsonload`. Route it through `loader.load_workbook`, which already handles `.xlsx`, and make `inspect_file` return `None` for unreadable input.

- [ ] **Load warnings and I/O errors are not shown.** `Grid.load_warnings` counts shared formulas imported as values and cells dropped beyond 256x1024. `Grid.io_error` holds why a load or save failed. The CLI prints warnings and `Api.open_file` returns them, but the TUI shows neither, and the web client ignores `warnings`. TUI `:xlsx save` and friends print only "Failed to export", and `--convert` prints "could not write PATH" without the reason.

- [ ] **Deleting a sheet leaves references to it reading 0.** `=Sheet1!A2*2` on another sheet keeps its text and evaluates to 0 after `Sheet1` is removed. Excel rewrites the reference to `#REF!`.

- [ ] **A deleted reference shows `#NAME?` in PYTHON mode.** Deleting a referenced row rewrites `=A2*2` to `=#REF!*2`, which PYTHON-mode `eval()` cannot parse. EXCEL mode shows `#REF!`.

- [ ] **A label's display quote reaches formulas.** `_cell_lookup_value` returns a label's text with its leading `"`, so `=LEN(A1)` over the label `"abc` answers 4.

### Security

- [ ] **A PYTHON-mode formula can read process state without approval.** `validate_formula` inspects only `ast.Attribute` and `ast.Name` nodes. Attribute and item access written inside a string literal and performed by `str.format`, `%`, an f-string format spec or `format_map` is not seen. A formula can read module globals and `os.environ` this way. The file needs no code block, so no trust prompt appears. No call primitive has been shown. Options: reject `format`/`format_map` calls and dunder text in string constants, or treat every PYTHON-mode formula as code needing approval (see the next item).

- [ ] **A missing or unknown `mode` loads as PYTHON.** `{"cells":[["=(lambda:7)()"]]}` evaluates with `eval()` and no prompt; so does `"mode": "excel2"`. `LoadPolicy.formulas_only()` withholds only the code block, not PYTHON-mode formula evaluation. Default to EXCEL, or refuse an unrecognised mode. v1 files predate modes, so this needs a migration decision.

- [ ] **A `gridcalc.toml` in the working directory can disable the sandbox.** `find_config` reads the CWD before the user config, and `sandbox = false` there turns off validation and the trust prompt. A workbook shipped beside such a file runs its code block on open. Honour `sandbox` only from `$XDG_CONFIG_HOME/gridcalc/` or `GRIDCALC_SANDBOX`.

- [ ] **Curated module facade.** Approved workbook code is handed whole module objects, so `np.savetxt('/anywhere', ...)` writes any path with the sandbox on. Expose a facade (`np.array`, `np.mean`, `np.linalg.solve`) rather than the module. Portable, needs no IPC, and removes the severe outcome -- arbitrary file read and write -- at a fraction of the cost of isolation. Ongoing cost is curation: each newly approved module needs a facade, and an omission is silent.

### Documentation & infrastructure

- [ ] **The CI build matrix runs Python 3.14 on every leg.** `ci.yml` calls `uv python install ${{ matrix.python-version }}`, then `uv sync`, which follows `.python-version` (3.14). The 3.10 and 3.12 legs run 3.14.7. Pass `--python ${{ matrix.python-version }}` to `uv sync` or set `UV_PYTHON`.

- [ ] **miniz and pugixml are fetched at configure time and their licences are not shipped.** OpenXLSX's `CMakeLists.txt` git-fetches both, so the sdist does not build offline. Both are MIT and linked into `_core`, but neither licence is in `THIRD-PARTY-NOTICES.md` or `license-files`. Vendor them under `thirdparty/` and add their licences.

- [ ] **Tag names and the publish trigger disagree, so no tag has ever published.** Every tag in the repo is bare (`0.6.0`, `0.5.1`, ... ten of them), `make release` creates `v$version`, and `build-publish.yml` fires on `tags: - "v*"`. No existing tag matches the trigger. 0.6.0 is on PyPI, but the only Build and Publish run was a manual dispatch with its publish jobs skipped, so the upload happened outside CI. Pick one convention and make the Makefile and the workflow agree; the `v` prefix is the cheaper side to keep, since only the historical tags disagree with it. `v*` also matches the `v*-abi3` tags that `build-abi3.yml` builds, so narrow the pattern before pushing a `v` tag.

## Medium

### Optimization

- [ ] **Sensitivity for quadratic models.** Withheld today: a QP's duals do not carry the shadow-price reading the report describes. HiGHS does return them, so this is a question of deciding what they mean to a spreadsheet user, not of plumbing.

### Web frontend

- [ ] **Move row and column (`swaprow`/`swapcol`).** Insert and delete now ship in both frontends; reordering does not. The engine primitives are ready, so this is a `gridcalc/commands.py` entry (which both frontends then get) plus a client gesture -- dragging a header.

- [ ] **Migrate the remaining shareable commands into the registry.** `:width` is the interesting one: the TUI means a uniform width in character cells and the web view means pixels per column, so it needs a decision about what the shared command *is* before it can move. Saving already goes through `loader.save_workbook`; the `:csv`/`:xlsx`/`:pd` load bodies could be shared the same way, with the path prompt left to each frontend.

- [ ] **The code-block / formula-mode surface (`:e`, `:mode`).** The *loading* half is done -- `loader.load_workbook` takes a `LoadPolicy` and `TrustDialog` supplies it, so a HYBRID or PYTHON workbook's code runs once approved. What is still missing is *authoring*: no editor for the `code` block (`:e`) and no way to switch formula mode from the GUI, so those workbooks can be opened and read in the web view but not written there.

- [ ] **Accessibility, and validating the reason web was chosen.** `docs/gui.md` justified the web bet partly on IME/CJK input and accessibility, and neither claim has been tested in a real webview -- only asserted. The grid is absolutely-positioned `div`s with no `role="grid"`/`gridcell`/`aria-rowindex` and a single focusable container, so the assertion is currently unbacked by the implementation too. Add ARIA grid semantics, then verify CJK/IME input on each platform's real webview (the Playwright suite is Chromium -- a faithful proxy, not the production engine).

- [ ] **Full spreadsheet keyboard model.** Missing: PageUp/PageDown, Ctrl+Home/End, Ctrl+arrow (jump to data edge), End, Ctrl+A, Escape, shift+space / ctrl+space (row/column select), F4 (toggle absolute in the editor). Today only `Home` exists (`Grid.tsx`).

- [ ] **Column widths are not refetched after an undo.** `Grid` is keyed by the active sheet's index. An undo that restores widths on the same sheet, or restores a different sheet at the same index, leaves the old `col_widths` on screen. Keying by sheet name fixes the second case.

- [ ] **Open decision: does the web view replace the TUI as the default, or complement it?** (`docs/web.md` §7.) This gates how much of the parity work above is worth doing at all. If it complements -- the TUI stays the power-editing frontend and the web view is the visualize-and-solve companion -- then breadth stops mattering and distribution becomes the next real question instead.

### Performance

- [ ] **Range subscriber explosion (Phase E from `docs/topological.md`).** `SUM(A1:Z1000)` registers 26000 reverse-index entries. Replace with an interval representation (per-column interval tree, or aggregation nodes that fan out at change time). Defer until profiling shows large-range workloads as a hot spot.

- [ ] **Undo memory is bounded by entry count, not size.** A structural entry copies every sheet's cells: 6.4 MB on a 3-sheet workbook with 25k cells, so 64 entries can hold about 400 MB. Cap the stack by bytes if real workbooks reach that.

### Refactoring & code quality

- [ ] **Undo gaps.** `:e` code edits, `:opt def`/`:opt undef` and `:width` (web `set_col_width`) record no undo entry. A workbook-level undo also reverts any width change made after its snapshot.

- [ ] **Sheet names are validated only at xlsx export.** `add_sheet` and `rename_sheet` accept names Excel rejects (`a/b`, `Q?`, 32+ characters, `History`), so the workbook saves as JSON and fails as xlsx. Validate on creation and rename.

- [ ] **Editing an imported label re-parses it.** xlsx text such as `00123` or `=SUM(1,2)` imports as a label and saves with `"label": true`. Committing an edit to it in either frontend turns it back into a number or a formula. Neither frontend has label-entry syntax that maps to the `label` key.

- [ ] **Non-date number formats in xlsx I/O.** Dates are done (see CHANGELOG): `_core.xlsx_read` reports each cell's number format, `Cell.fmtstr` carries it, both frontends render it, and `xlsxsave` writes it back. What is still dropped on import is every *other* number format -- currency, percent, thousands -- which arrives as a bare number, and cell styles (fonts, fills, borders) which are neither read nor written. The reading half is nearly free now that the format code crosses the boundary; the open question is how much of Excel's format language to implement against gridcalc's own `LRIGD$%*` / Python-spec vocabulary.

### Security

- [ ] **Terminal escapes in the startup trust prompt.** `startup_trust_prompt` prints the code preview raw. A comment holding `\x1b[2K\r` erases the preceding statement on screen, and the line still runs on approval. Strip control characters before printing.

- [ ] **`classify_module` classifies a submodule by its top-level package.** `numpy.ctypeslib` classifies as safe and loads under a plain approve, which exposes `ctypes`. Classify by full dotted name.

- [ ] **No limit on formula size or run time.** `=SUM(SEQUENCE(100000000))` (EXCEL) and `=sum(range(10**12))` (PYTHON) hang the load with no approval needed. Cap formula length and nesting depth, and bound evaluation.

### Documentation & infrastructure

- [ ] **Build the docs site in CI.** The site itself is done (`mkdocs.yml`, 30+ pages under `docs/`, `make docs` / `docs-serve` / `docs-deploy`), and publishing stays a deliberate manual `make docs-deploy` -- the Makefile says why. The gap is that `ci.yml` never runs `mkdocs build --strict`, so a broken cross-reference between pages lands on `main` and is only found by whoever next deploys. Adding the `docs` group and one `make docs` step to CI is the whole fix; it does not commit or push anything.

- [ ] **CI runs part of the test suite.** `web-qa` (`tsc`, vitest), the `tty` suite and the `browser` suite never run in CI. The build job builds a wheel but tests the editable install. CI lint omits `scripts/`.

- [ ] **The wheel matrix stops at cp313 while the classifiers claim 3.14.** A 3.14 user installs the cp312-abi3 wheel, which CI tested only on 3.12. `build-abi3.yml` calls those wheels build-only, yet five were published with 0.6.0.

## Low

### Optimization

- [ ] **Integer + quadratic together.** HiGHS does not support integrality with a Hessian. Currently the combination is simply refused.

- [ ] **HiGHS wheel size and build time.** Linux x86_64, Linux aarch64 and Windows AMD64 wheels build and pass the suite, including `test_opt.py` (Build and Publish run 34385123899). Build time and wheel size are unmeasured. `highs_extras` must stay a static lib -- the shared build dlopens it at runtime, which will not work from inside a wheel.

### Web frontend

- [ ] **Light theme.** `styles.css` is a single dark `:root` with no `prefers-color-scheme` support, and a few hex values leak out of it into component props (`ChartDialog.tsx` hands literal colours to Recharts; `SweepDialog.tsx` already uses CSS variables, so that is the pattern to follow). A light-mode user currently gets a forced dark app.

- [ ] **Viewport fetch cost.** `viewport()` fires per scroll event, coalesced only by in-flight dedup (`Grid.tsx`). No debounce and no client-side block cache, so fast scrolling issues a round trip per frame, newly-scrolled rows stay blank until each returns, and scrolling back refetches from scratch. Not urgent in-process on a 256x1024 sheet; an LRU of fetched blocks is the cheap fix when it bites. `docs/web.md` §5e.

- [ ] **Distribution (P3).** Frozen, signed, double-clickable builds for macOS/Windows/Linux around pywebview plus the C++ extensions, and per- platform manual QA of clipboard/IME/rendering. `docs/web.md` §5b calls this the most underestimated cost in the plan; budget it as its own project, not a task. Only worth starting once the decision below is answered.

- [ ] **The bridge is described three times by hand.** `bridge/types.ts`, `bridge/mock.ts` and `_MOCK_BRIDGE` in `tests/integration/test_web_bundle.py` are maintained separately. The mocks return source text where `viewport`, `copy` and `search` return values, do not model sheet undo, and differ on `chart_data` and `fill` edge cases. Add a contract test that checks each `Api` method's return keys and types against one schema.

### Performance

- [ ] **Targeted C++ acceleration for measured hot spots.** A full C++ evaluator port (lexer + parser + tree walker + cell store + dep graph) is not justified by current benchmarks: topological recalc closed the gap that originally motivated it. Surgical edits on 10k-cell sheets are <0.1 ms; xlsxload of 5k cells is ~12 ms; long-chain edits are single-digit ms. A wholesale port would duplicate the function library in C++, complicate the HYBRID `py.*` gateway with three-way Python<->C++ bouncing, and slow development velocity (rebuild required for every formula-system change). If a real workload exposes a hot spot, C++ that single component (`Vec` arithmetic, range materialization in `_expand_ranges`, or the closure BFS in `_recalc_topo`) -- a few hundred lines, not thousands. See git history for the original "Phase 3" entry if scope ever shifts.

### Refactoring & code quality

- [ ] **`Cell.ast` cache invalidates by text equality.** For very large sheets where many formulas share text, hashing the text would cut cache lookups; not a priority but worth measuring.

- [ ] **Remaining `libs/xlsx.py` Excel-fidelity gaps.** The lookup / criteria / conditional-aggregate audit sweep is done (see CHANGELOG). Left open:
  - Numeric-vs-text criteria coercion (`COUNTIF({1,2,"3"}, 3)`).
  - `SUMIF`/`COUNTIF` with a `sum_range` shorter than the criteria range. Excel resizes from the top-left, which needs reference rather than materialised-`Vec` semantics -- now unblocked, since `OFFSET` brought the `Reference` type into the value system.
  - Array criteria: `=SUMIF(A1:A3,{"a","b"},B1:B3)` answers `nan`.
  - D-functions (`DSUM`, `DCOUNT`, ...) return an error from any row of the database, not only from matched rows. Microsoft does not document the rule.
  - `=ROWS(FILTER(...))` answers `#VALUE!`.
  - Number-to-text uses 15 significant digits with `%g` notation, so `=0.00001&""` gives `1e-05`; Excel gives `0.00001`.
  - `YEARFRAC` bases 0 and 1 across year boundaries, and `POWER(0,0)` (gridcalc 1, Excel `#NUM!`). Confirm against Excel before changing.

- [ ] **Open decision: `^` associativity.** `=2^3^2` answers 512 (right-associative, chosen deliberately); Excel evaluates left to right and answers 64. Decide whether EXCEL mode follows Excel here, since the grammar is described as Excel-compatible.

- [ ] **`deps` over-approximates a shadowed named range.** When a `LET` name shadows a real named range the range stays recorded as a dep -- safe, just an occasional extra recalc; tighten only if it ever matters. (`LAMBDA`, the higher-order helpers, and true spill all shipped -- see CHANGELOG.)

### Features

- [ ] **3D range references (`Sheet1:Sheet3!A1:B2`).** Currently unsupported: `_expand_ranges` only recognises the `<ref>:<ref>` shape, so a sheet-span prefix passes through unexpanded and the formula evaluates to `nan`. Workaround in user files is to expand manually, e.g. `=SUM(Jan!B2:B3)+SUM(Feb!B2:B3)` instead of `=SUM(Jan:Feb!B2:B3)` (see `examples/example_multisheet.xlsx`). To implement: (1) extend `ref`/`refabs` to recognise the `<sheet>:<sheet>!<cell>[:<cell>]` shape; (2) add a pre-pass (or branch in `_expand_ranges`) that enumerates sheets between the two named endpoints in workbook order and emits a `Vec([...])` over every (sheet, cell) pair; (3) decide rebind semantics on `move_sheet`/`rename_sheet` -- Excel binds 3D refs to sheet *position* between the endpoints, so reordering changes which sheets are summed, while renaming an endpoint should rewrite the formula text the same way `_rewrite_sheet_prefix` handles single-sheet refs; (4) extend dependency tracking so cells in the spanned sheets register as subscribers, and a `move_sheet`/`add_sheet` between the endpoints invalidates the cached recalc.

- [ ] **TUI keybindings system -- v2 generalisations.** All five contexts are wired (`grid`, `entry`, `visual`, `cmdline`, `search`) with curated action vocabularies; see `docs/keybindings.md`. Outstanding gaps for a future iteration: (a) **Removing hardcoded defaults.** `[keys.<ctx>] cancel = []` currently does *not* unbind Esc, because the hardcoded fallback chain still matches `ch == 27`. To make unbind work, the hardcoded chain has to migrate fully into `DEFAULT_KEYMAP` and the contexts must dispatch only via the action lookup. Mechanical but tedious. (b) **Bind-to-`:command`.** The action vocabulary is fixed at module load time. If users want `[keys.grid] save = [...]` where "save" runs `:w`, the schema has to grow a way to carry the command text alongside the key spec, and an `exec_command`-style action that takes parameters. Out of scope until someone asks. (c) **Pick-mode actions in entry.** The `KEY_UP`/`KEY_DOWN` cursor-pick sub-mode in `entry` is too tangled with local state to expose as actions today. Refactor it to a small state machine before binding it. (d) **Keymap warnings are erased.** They print inside the alternate screen, and the first draw clears them.

- [ ] **xlsx interop level (c) for HYBRID and PYTHON mode.** EXCEL mode round-trips formulas today: `Grid.xlsxsave` emits kind `'f'` with the formula text and a cached value, and `_core.xlsx_write` sets `cell.formula()`. The remaining gap is the other two modes, whose syntax (`**`, list comprehensions, `py.*`) is not Excel grammar -- they still export values. Closing it needs a serialiser from the gridcalc AST to Excel-grammar text, and is only worth it for the subset that has an Excel equivalent.

- [ ] **xlsx shared formulas and constant cells.** Shared and array formulas import as their cached values, because OpenXLSX does not expose the shared formula's `si` and `ref` attributes. xlsx booleans import as `=TRUE`/`=FALSE` and error values as `=#N/A`-style formulas, because the engine has no boolean or error constant cell.

- [ ] **Migration tool `gridcalc migrate file.json`.** Attempts to upgrade a PYTHON-mode file to HYBRID by reparsing each formula with the EXCEL grammar and reporting the unparseable ones.

- [ ] **Visual-select operations.** Extend beyond `:f` -- support `:b` (blank range), `:dr`/`:dc` (delete selected rows/cols), `:r` (replicate into selection), copy/paste within selection.

- [ ] **System clipboard -- follow-ups.** Core integration and RFC 4180 quoting are done (see CHANGELOG). Remaining: verifying the Windows/Linux backends (`wl-clipboard`/`xclip`/`xsel`, `clip`/ `Get-Clipboard`) on real hardware -- developed on macOS against a fake backend.

- [ ] **Mouse support** (curses mouse events for cell selection and scrolling).

- [ ] **Plugin interface.** Allow third-party packages to register custom functions, commands, and cell formats via entry points or a plugin API.

### Security

- [ ] **TUI `:o` reads the sandbox flag at import time.** `tui/commands.py` imports `SANDBOX_ENABLED` by value, so `configure_sandbox` from `gridcalc.toml` does not reach it. With `sandbox = false`, `:o` still shows the trust prompt; startup and `loader` read `sandbox.SANDBOX_ENABLED` and do not. The error is on the safe side, but the two paths disagree.

- [ ] **Process isolation for PYTHON-mode recalc.** Only worth building if running untrusted workbook code becomes a supported feature; `LoadPolicy.formulas_only()` is the current answer everywhere but the TUI trust prompt. Buys a resource ceiling on every platform but filesystem confinement mainly on Linux. HYBRID's `py.*` gateway is a separate decision -- it is called mid-expression from the evaluator in the parent.

### Documentation & infrastructure

- [ ] **EXCEL grammar reference page.** Operators, precedence, error values, the function library, mode semantics. Add it to the docs site.

- [ ] **Pin GitHub Actions to commit SHAs.** `checkout@v7`, `cibuildwheel`, `setup-bun@v2`, `codecov@v5` and `pypi-publish@release/v1` are movable tags, used in jobs with `id-token: write`.

- [ ] **`make build` removes optional dependencies from `.venv`.** It runs `uv sync --reinstall-package gridcalc`, which uninstalls the `web` extra and the `docs` group. `make web-drive` then lacks pywebview. `uv sync --extra web --group docs` restores them. The Makefile `.PHONY` list and `help` also omit `test-tty`, `test-web`, `test-stdlib`, the `web-*` targets and `bench`.
