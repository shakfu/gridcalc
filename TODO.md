# TODO

Open tasks, ordered by priority within each section. Resolved items live in CHANGELOG.md.

## Critical

## High

### Security

- [ ] **Modules without a facade are handed over whole.** `pandas`, `matplotlib`, `xlsxwriter`, `scipy`, `sympy` and any approved unknown module are module objects, and a module object reaches every module it imported: `pd.io.common.os` is `os`. The prompt labels them unrestricted. A pandas facade would not make pandas safe: `apply`, `agg`, `aggregate` and `transform` dispatch a method named by a string, so `df.apply("to_csv", path_or_buf=...)` writes a file past the validator's attribute check (verified on pandas 3.0.2). It needs a runtime guard on that dispatch first. `scipy` needs its public names collected per submodule; it, `matplotlib` and `xlsxwriter` are not installed in the dev environment. `sympy` cannot take a facade: most of its functions `eval` a string argument.

## Medium

### Optimization

- [ ] **Sensitivity for quadratic models.** Withheld today: a QP's duals do not carry the shadow-price reading the report describes. HiGHS does return them, so this is a question of deciding what they mean to a spreadsheet user, not of plumbing.

### Web frontend

- [ ] **Load warnings for the startup file are dropped.** `web.run(path)` loads before the client exists, and no bridge call carries `load_warnings`, so only a later open shows them.

- [ ] **Move row and column (`swaprow`/`swapcol`).** Insert and delete now ship in both frontends; reordering does not. The engine primitives are ready, so this is a `gridcalc/commands.py` entry (which both frontends then get) plus a client gesture -- dragging a header.

- [ ] **Migrate the remaining shareable commands into the registry.** `:width` is the interesting one: the TUI means a uniform width in character cells and the web view means pixels per column, so it needs a decision about what the shared command *is* before it can move. Saving already goes through `loader.save_workbook`; the `:csv`/`:xlsx`/`:pd` load bodies could be shared the same way, with the path prompt left to each frontend.

- [ ] **The code-block / formula-mode surface (`:e`, `:mode`).** The *loading* half is done -- `loader.load_workbook` takes a `LoadPolicy` and `TrustDialog` supplies it, so a HYBRID or PYTHON workbook's code runs once approved. What is still missing is *authoring*: no editor for the `code` block (`:e`) and no way to switch formula mode from the GUI, so those workbooks can be opened and read in the web view but not written there.

- [ ] **Accessibility, and validating the reason web was chosen.** `docs/gui.md` justified the web bet partly on IME/CJK input and accessibility, and neither claim has been tested in a real webview -- only asserted. The grid is absolutely-positioned `div`s with no `role="grid"`/`gridcell`/`aria-rowindex` and a single focusable container, so the assertion is currently unbacked by the implementation too. Add ARIA grid semantics, then verify CJK/IME input on each platform's real webview (the Playwright suite is Chromium -- a faithful proxy, not the production engine).

- [ ] **Full spreadsheet keyboard model.** Missing: PageUp/PageDown, Ctrl+Home/End, Ctrl+arrow (jump to data edge), End, Ctrl+A, Escape, shift+space / ctrl+space (row/column select), F4 (toggle absolute in the editor). Today only `Home` exists (`Grid.tsx`).

- [ ] **Column widths are not refetched after an undo.** `Grid` is keyed by the active sheet's index. An undo that restores widths on the same sheet, or restores a different sheet at the same index, leaves the old `col_widths` on screen. Keying by sheet name fixes the second case.

- [ ] **Open decision: does the web view replace the TUI as the default, or complement it?** (`docs/web.md` §7.) This gates how much of the parity work above is worth doing at all. If it complements -- the TUI stays the power-editing frontend and the web view is the visualize-and-solve companion -- then breadth stops mattering and distribution becomes the next real question instead.

### Performance

- [ ] **Undo memory is bounded by entry count, not size.** A structural entry copies every sheet's cells: 6.4 MB on a 3-sheet workbook with 25k cells, so 64 entries can hold about 400 MB. Cap the stack by bytes if real workbooks reach that.

### Refactoring & code quality

- [ ] **Undo gaps.** `:e` code edits, `:opt def`/`:opt undef` and `:width` (web `set_col_width`) record no undo entry. A workbook-level undo also reverts any width change made after its snapshot.

- [ ] **Sheet names are validated only at xlsx export.** `add_sheet` and `rename_sheet` accept names Excel rejects (`a/b`, `Q?`, 32+ characters, `History`), so the workbook saves as JSON and fails as xlsx. Validate on creation and rename.

- [ ] **Editing an imported label re-parses it.** xlsx text such as `00123` or `=SUM(1,2)` imports as a label and saves with `"label": true`. Committing an edit to it in either frontend turns it back into a number or a formula. Neither frontend has label-entry syntax that maps to the `label` key.

- [ ] **xlsx styles gridcalc has no model for.** Number formats in the `[,][.N][f|e|%]` grammar, bold, italic, underline and left/right alignment cross both ways (see CHANGELOG). Font sizes, colours and faces, fills, borders, other alignments, merged cells, and number formats outside that grammar (currency symbols, colours, sections) are neither read nor written. Saving over a file that has them asks first. Adding any of them needs a place in `Cell` and in the JSON format.

### Security

- [ ] **No limit on formula size or run time.** `=SUM(SEQUENCE(100000000))` (EXCEL) hangs the load with no approval needed. `=sum(range(10**12))` (PYTHON) does too once the file is approved. Cap formula length and nesting depth, and bound evaluation.

- [ ] **Unverified: the file can change between approval and load.** `inspect_file` and the later load read the file twice. Probe artefact exists; outcome not confirmed. (REVIEW.md unchecked lead.)

- [ ] **Unverified: `pager` or `editor` from `./gridcalc.toml` may reach a subprocess.** 0.7.0 says `editor` is ignored there. Probe artefact exists; outcome not confirmed. (REVIEW.md unchecked lead.)

- [ ] **Unverified: `allowed_modules` from `./gridcalc.toml`.** If still honoured there, a directory can pre-approve `pandas`, which is handed over whole (see the facade entry above). Probe artefact exists; outcome not confirmed. (REVIEW.md unchecked lead.)

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

Measurements for this section: `docs/dev/ironcalc.md`. Per-formula figures are for a full recalc of 20k scalar formulas.

- [ ] **Remaining range scans in criteria and lookup functions.** `SUMIF`, `COUNTIF`, the `*IFS` family, exact `MATCH`, `VLOOKUP`, and forward `XLOOKUP`/`XMATCH` use the memos on a shared `Vec` (see CHANGELOG). Still scanning per consumer: `HLOOKUP`, last-to-first `XLOOKUP`/`XMATCH`, approximate matches, text and wildcard criteria, and the database functions. `SUMIF` over 1000 cells still costs about 60 us: one pass builds the hit list and one collects the matched numbers. A sorted copy with `bisect` could make approximate matches logarithmic; not measured.

- [ ] **A full `recalc()` rebuilds the dependency graph.** 2.2-2.9 us per formula, the largest piece of a full recalc. Undo, sort, the CLI and the solver's apply step write cells directly and rely on the rebuild (`docs/topological.md`). Skipping it needs each of them to write through `setcells_bulk`, or to pass a dirty set. Undo gains less: `Cell.copy_from` drops the AST, so a restored cell is re-parsed.

- [ ] **A function call costs 2-3 us before its body runs.** `_eval_call` lowers the name four times, checks LET locals and named lambdas before the builtins, and reads `_param_info` twice. Resolve the name once and look the builtin up first when no LET scope is open.

- [ ] **Recalc loop remainder.** Kahn ordering, the loop body, the result store and the spill check total about 2.5 us per formula. No single change is worth more than 0.5 us: Kahn allocates a default empty set and an intersection set per cell, the loop slices `text[1:]` per formula to validate the AST cache, and `_apply_spill` runs for scalar results.

- [ ] **C++ is not justified for the evaluator or the function library.** `evaluate()` is 13-41% of a full recalc, so a C++ tree walker with zero cost gains at most 1.2-1.7x. Scalar function bodies are 1-11% of a formula's cost, so porting `libs/xlsx.py` gains less. IronCalc's 0.4-0.8 us per formula, against 6-8 us here, needs the cell store, graph and values native too: `engine.py` and `formula/`, about 6k lines. PYTHON mode and `py.*` read that store from Python, and `RAW_ARG_FUNCS` receive `env` and AST nodes, so both must stay Python-visible. Reconsider for workbooks past about 1M formulas, or a loop that runs a full recalc per iteration. If native code is added, use C++: nanobind and CMake already build `_core.cpp` and `_opt.cpp`.

### Refactoring & code quality

- [ ] **`Cell.ast` cache invalidates by text equality.** For very large sheets where many formulas share text, hashing the text would cut cache lookups; not a priority but worth measuring.

- [ ] **A typed number keeps more than 15 digits.** Excel keeps 15 significant digits of a number literal or a typed cell value and zeroes the rest, so `=12345678901234567&""` is `12345678901234500` (`text-7`). gridcalc keeps the double. `num-1` in `excel-check.xlsx` confirms the cause.

- [ ] **Confirm what `"<>"` criteria count.** gridcalc counts only numbers for `"<>3"`; Excel may also count text and blanks (`crit-8`, `crit-9`). Also unconfirmed: whether a D-function propagates an error in a matched row, as gridcalc does (`db-3`, `db-4`).

- [ ] **Confirm where number-to-text switches to scientific form.** gridcalc uses plain decimals for exponents -10 to 19. Excel checked only at -10, 20 and -16 (`misc-2`). Cases `text-9`..`text-14` probe the rest.

- [ ] **`YEARFRAC` bases 0 and 1.** Basis 0 misses the US 30/360 end-of-February rules: Feb 29 to Feb 28, and Feb 28 to Feb 29, each give 1 in Excel. Basis 1 averages year lengths for dates under a year apart; Excel uses 366 there when the span includes Feb 29 (`yf-2`, `yf-5`..`yf-7`). That rule is inferred from 4 cases; `yf-9`..`yf-20` test it and the 30/360 day rules.

- [ ] **Excel disagreements found by `excel-check.xlsx`.** Each is a case id in `docs/dev/excel-check.md`.
  - `FREQUENCY` with unsorted bins (`arr-2`): Excel gives `2,2,1`, gridcalc `4,0,1`.
  - `TEXT(3,1)` (`misc-6`): Excel reads the number as the format code `"1"` and gives `"1"`.
  - `OR`/`XOR` with a text literal (`misc-3`, `misc-4`): Excel gave `TRUE` inside an array formula. `misc-7` and `misc-8` check them as plain formulas.
  - `IMSQRT("-4")` (`misc-2`): Excel gives `1.22464679914735E-16+2i`. Matching the residue is probably not worth it.

- [ ] **`deps` over-approximates a shadowed named range.** When a `LET` name shadows a real named range the range stays recorded as a dep -- safe, just an occasional extra recalc; tighten only if it ever matters. (`LAMBDA`, the higher-order helpers, and true spill all shipped -- see CHANGELOG.)

### Features

- [ ] **Reconsider polars for DataFrame cells.** pandas backs `pd.DataFrame` formulas and `:pd`. Polars has no index, which matches how gridcalc reads a frame (shape, column names, cell access, row iteration). Measured 2026-09-17 on macOS arm64, polars 1.44.2 against pandas 3.0.5:

  - Warm import: about 75 ms against 200-230 ms.

  - Installed: 164 MB against 73 MB for pandas plus numpy. numpy stays for ndarray cells, so `[extras]` would grow to about 188 MB.

  - Python: one abi3 wheel for 3.10+; pandas 3 needs 3.11+.

  Costs of switching:
  - Strict column dtypes. `pl.DataFrame({"a": [1, 3.5]})` raises, so `objedit` literals break, and range-to-frame conversion needs a coercion rule for mixed columns.

  - `null` exists alongside NaN, so `cmd_view`'s `pd.isna` check changes.

  - polars needs a `SIDE_EFFECT_MODULES` entry: `read_csv` takes URLs and `pl.plugins.register_plugin_function` loads a native library.

  - `pd.` workbooks break: `examples/example.json`, 11 tests, `docs/guide/formulas.md`.

  Decide first whether DataFrame growth means a richer formula API or grid integration (range to frame, spilling a frame), and whether frames get their own extra.

- [ ] **3D range references (`Sheet1:Sheet3!A1:B2`).** Currently unsupported: `_expand_ranges` only recognises the `<ref>:<ref>` shape, so a sheet-span prefix passes through unexpanded and the formula evaluates to `nan`. Workaround in user files is to expand manually, e.g. `=SUM(Jan!B2:B3)+SUM(Feb!B2:B3)` instead of `=SUM(Jan:Feb!B2:B3)` (see `examples/example_multisheet.xlsx`). To implement: (1) extend `ref`/`refabs` to recognise the `<sheet>:<sheet>!<cell>[:<cell>]` shape; (2) add a pre-pass (or branch in `_expand_ranges`) that enumerates sheets between the two named endpoints in workbook order and emits a `Vec([...])` over every (sheet, cell) pair; (3) decide rebind semantics on `move_sheet`/`rename_sheet` -- Excel binds 3D refs to sheet *position* between the endpoints, so reordering changes which sheets are summed, while renaming an endpoint should rewrite the formula text the same way `_rewrite_sheet_prefix` handles single-sheet refs; (4) extend dependency tracking so cells in the spanned sheets register as subscribers, and a `move_sheet`/`add_sheet` between the endpoints invalidates the cached recalc.

- [ ] **TUI keybindings system -- v2 generalisations.** All five contexts are wired (`grid`, `entry`, `visual`, `cmdline`, `search`) with curated action vocabularies; see `docs/keybindings.md`. Outstanding gaps for a future iteration: (a) **Removing hardcoded defaults.** `[keys.<ctx>] cancel = []` currently does *not* unbind Esc, because the hardcoded fallback chain still matches `ch == 27`. To make unbind work, the hardcoded chain has to migrate fully into `DEFAULT_KEYMAP` and the contexts must dispatch only via the action lookup. Mechanical but tedious. (b) **Bind-to-`:command`.** The action vocabulary is fixed at module load time. If users want `[keys.grid] save = [...]` where "save" runs `:w`, the schema has to grow a way to carry the command text alongside the key spec, and an `exec_command`-style action that takes parameters. Out of scope until someone asks. (c) **Pick-mode actions in entry.** The `KEY_UP`/`KEY_DOWN` cursor-pick sub-mode in `entry` is too tangled with local state to expose as actions today. Refactor it to a small state machine before binding it. (d) **Keymap warnings are erased.** They print inside the alternate screen, and the first draw clears them.

- [ ] **xlsx interop level (c) for HYBRID and PYTHON mode.** EXCEL mode round-trips formulas today: `Grid.xlsxsave` emits kind `'f'` with the formula text and a cached value, and `_core.xlsx_write` sets `cell.formula()`. The remaining gap is the other two modes, whose syntax (`**`, list comprehensions, `py.*`) is not Excel grammar -- they still export values. Closing it needs a serialiser from the gridcalc AST to Excel-grammar text, and is only worth it for the subset that has an Excel equivalent.

- [ ] **xlsx constant cells.** xlsx booleans import as `=TRUE`/`=FALSE` and error values as `=#N/A`-style formulas, because the engine has no boolean or error constant cell.

- [ ] **xlsx export writes newer functions without their `_xlfn.` prefix.** Import strips `_xlfn.`, `_xlws.` and `_xlpm.`; export adds none back. Excel then likely reads `=XLOOKUP(...)` from a gridcalc file as an unknown name (`#NAME?`), which `scripts/excel_check.py` works around with its own prefix table. Not yet checked in Excel. Needs the list of functions Excel stores prefixed.

- [ ] **Shared formulas past a shifted whole-column reference.** `adjust_refs` shifts `A1`-style references but not `B:B` or `1:1`, so a shared formula that uses one keeps the master's columns in every cell.

- [ ] **Migration tool `gridcalc migrate file.json`.** Attempts to upgrade a PYTHON-mode file to HYBRID by reparsing each formula with the EXCEL grammar and reporting the unparseable ones.

- [ ] **Visual-select operations.** Extend beyond `:f` -- support `:b` (blank range), `:dr`/`:dc` (delete selected rows/cols), `:r` (replicate into selection), copy/paste within selection.

- [ ] **System clipboard -- follow-ups.** Core integration and RFC 4180 quoting are done (see CHANGELOG). Remaining: verifying the Windows/Linux backends (`wl-clipboard`/`xclip`/`xsel`, `clip`/ `Get-Clipboard`) on real hardware -- developed on macOS against a fake backend.

- [ ] **Mouse support** (curses mouse events for cell selection and scrolling).

- [ ] **Plugin interface.** Allow third-party packages to register custom functions, commands, and cell formats via entry points or a plugin API.

### Security

- [ ] **Process isolation for PYTHON-mode recalc.** Only worth building if running untrusted workbook code becomes a supported feature; `LoadPolicy.formulas_only()` is the current answer everywhere but the TUI trust prompt. Buys a resource ceiling on every platform but filesystem confinement mainly on Linux. HYBRID's `py.*` gateway is a separate decision -- it is called mid-expression from the evaluator in the parent.

### Documentation & infrastructure

- [ ] **Review the areas REVIEW.md did not cover.** `libs/xlsx.py`; solver, goal seek and the C++ extensions; TUI, web `Api` and React client; packaging (sdist and wheel contents).

- [ ] **EXCEL grammar reference page.** Operators, precedence, error values, the function library, mode semantics. Add it to the docs site.

- [ ] **Pin GitHub Actions to commit SHAs.** `checkout@v7`, `cibuildwheel`, `setup-bun@v2`, `codecov@v5` and `pypi-publish@release/v1` are movable tags, used in jobs with `id-token: write`.

- [ ] **The Makefile `.PHONY` list and `help` omit targets.** Missing: `test-tty`, `test-web`, `test-stdlib`, the `web-*` targets and `bench`.
