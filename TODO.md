# TODO

Open tasks, ordered by priority within each section. Resolved items live in CHANGELOG.md.

## Critical

## High

- [ ] **Read the values cached for external links.** A formula with `[N]Sheet!A1` now shows the value Excel saved, so it stays fixed when a local input changes. Excel recalculates it from `xl/externalLinks/externalLinkN.xml`, which caches each linked cell. Reading those would make such cells live. 60 of 306 Sheetpedia files have links.

- [ ] **Corpus mismatches still open** (`docs/dev/excel-corpus.md`). Largest first:
  - Date text without a year (`"1/2"`) should read as that day this year, as Excel does; it gives `#VALUE!`.

  - A legacy formula keeps its rule only through copy and fill; pasting its text from the clipboard makes it dynamic. Excel keeps the `@` in the text instead.

  - About 800 cells remain (99.0% agree, 2026-11-05). Open, each needs a decision beyond one function:
    - `YEARFRAC` (20 cells) and `WEEKNUM` (5) check basis/return_type before an error argument; the evaluator propagates the first error argument before the function runs.

    - `TIMEVALUE("24:00")` is 0 and `DATEVALUE` takes hours of 24 and above; `dates.parse_time` rejects them, and it is shared with arithmetic.

    - Percent text (`"1600%"`) does not convert in `_to_number` (`BASE_DECIMAL.xlsx`, 4 cells).

    - `ROW(B:B)` is the full column while `B:B<>""` is trimmed to the used extent, so the shapes differ (`ROW_COLUM.xlsx`).

    - `INDEX(A1:A3,0.4)` (Excel `#VALUE!`), `MATCH(blank,...,-1)`, `XLOOKUP` with an omitted lookup value in binary mode, 4 `TEXT` format codes.

    - Solver precision: `XIRR` (12 cells), `IRR` (12), `ODDFYIELD` (3), `CUMPRINC` (2) differ from Excel near 1e-9 relative; gridcalc's roots have the smaller residual. `tests/test_excel_saved_models.py` has a strict xfail for the `XIRR` case, 7e-9 off.

    - Not engine bugs: `CHAR` of a control character (openpyxl reads `_x0001_`), `TODAY()` in templates, a `week()` UDF.

  - `HYPGEOM.DIST`'s cumulative form sums one term per success and has no closed form here; a sample of a billion runs that long.

  - `BESSELJ` order 1 and up, for |x| >= 8, differs from Excel in the sixth digit. gridcalc's value is the more accurate one.

  - `A1#` on a cell that does not spill should be `#REF!`.

  - `BINOM.DIST` with 1E30 trials is `#NUM!` in Excel; gridcalc gives 0. Excel saved no value for 1E10, so the limit is unknown.

- [ ] **Real-workbook survey gaps** (`docs/dev/excel-corpus.md`, survey section). By files: conditional formatting (178), data validation (118), comments (50), hyperlinks (30). The reference union `(A1:B2,C1:D2)` does not parse.

- [ ] **Tables:** editing a header cell should rename the column and rewrite the formulas that name it, as Excel does. A bare `[Qty]` inside a table is not read; `[@Qty]` is. `Table167[[#Totals],[ERP (T12m)]]` gives `#VALUE!` (Damodaran `ERPNov26.xlsx`, `ERPbymonth.xlsx`).

- [ ] **Evaluator speed on large array formulas.** Sheetpedia `802559d...` holds 7,676 copies of `AGGREGATE(15,6,ROW(H2:H10000)-ROW(H2)+1/(B2:B10000=Q$1)/...)`: about 380M element operations. A full recalc takes 232 s and matches Excel in every cell; under the 30 s limit most give `#CALC!`. At about 0.6 us per element no Python loop fits, so this needs native or vectorised element-wise operators. The C++ entry under Low weighs that.

- [ ] **Evaluator speed on large lambda formulas.** A `LET` over 12,516 rows with `BYROW`, `FILTER` and `MAP` per row (Sheetpedia `846882d...`) still reaches the 30 s limit. Element-wise operators and `IF` over Vecs dominate the profile.

- [ ] **OpenXLSX reads about 7 us per cell**: a 1M-cell sheet takes 7 s before any Python runs.

## Medium

### Optimization

- [ ] **Sensitivity for quadratic models.** Withheld today: a QP's duals do not carry the shadow-price reading the report describes. HiGHS does return them, so this is a question of deciding what they mean to a spreadsheet user, not of plumbing.

### Iterative calculation

- [ ] **Re-run the Damodaran models.** They were the case for this (1,515 of 8,002 cells `#CIRC!`), but are not in the working tree. Compare with a tolerance near `iterateDelta`: Excel's saved values depend on how many recalculations it ran.

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

- [ ] **A named-input case recalculates 6.6x slower than GridCraft.** 173 ms against 26 ms on 18,033 formulas (`docs/dev/comparison.md`). A sweep of 100k cases would take about 4.8 h against 45 min. Worth it only for sweep-sized workloads; the cost breakdown is under Low > Performance.

- [ ] **Whole-column paths that still cost a million rows.** Each is correct but slow on Excel's grid:
  - Fill down (`Api.fill`) over a header-selected column writes every row, as Excel does.

  - The solver's `_precedents` (`opt.py`) expands a range through `extract_refs`, one key per cell.

  - In PYTHON mode, one cell near row 1048576 sets the used extent, so a range over `TRIM_CELLS` (`_expand_ranges`, named-range injection) reads every position to it. EXCEL and HYBRID ranges read only stored cells.

- [ ] **Undo memory is bounded by entry count, not size.** A structural entry copies every sheet's cells: 6.4 MB on a 3-sheet workbook with 25k cells, so 64 entries can hold about 400 MB. Cap the stack by bytes if real workbooks reach that.

### Refactoring & code quality

- [ ] **Undo gaps.** `:e` code edits, `:opt def`/`:opt undef` and `:width` (web `set_col_width`) record no undo entry. A workbook-level undo also reverts any width change made after its snapshot.

- [ ] **xlsx styles: what is left.** Fonts, solid fills, borders, alignment, number formats, merged cells and row heights now round-trip (see CHANGELOG). Open:
  - No command sets a font, fill, border, alignment or merge; they arrive only from a file.

  - Neither view hides hidden rows, and no command hides or filters one. `SUBTOTAL` and `AGGREGATE` already read them (`docs/dev/hidden-rows.md`).

  - Neither view draws row heights, and the web view does not draw rotation. Variable row heights need the web grid's row positions as a prefix sum over 1M rows.

  - Pattern and gradient fills, diagonal borders and font effects (superscript, outline, shadow) are not modelled; saving over a file with them still asks.

  - Clearing a cell keeps its `xstyle` but drops bold, italic, underline and number format. Excel keeps all of them.

  - Selecting or editing inside a merged area treats each cell separately.

  - Not yet opened in Excel: run `scripts/style_check.py` (`docs/dev/excel-check.md`).

### Security

- [ ] **No run-time limit in PYTHON mode.** EXCEL and HYBRID formulas are capped at 8192 characters and 64 nesting levels, and a recalc stops after `RECALC_TIME_LIMIT` (see CHANGELOG). `=sum(range(10**12))` in an approved PYTHON-mode file still hangs: `eval` cannot be interrupted without a thread or a signal.

- [ ] **Arrays do not broadcast to an outer product.** `=SEQUENCE(3)*TRANSPOSE(SEQUENCE(3))` is `#VALUE!`; Excel gives a 3x3 array. A column against a row should expand both to their combined shape.

- [ ] **Unverified: the file can change between approval and load.** `inspect_file` and the later load read the file twice. Probe artefact exists; outcome not confirmed. (REVIEW.md unchecked lead.)

- [ ] **Unverified: `pager` or `editor` from `./gridcalc.toml` may reach a subprocess.** 0.7.0 says `editor` is ignored there. Probe artefact exists; outcome not confirmed. (REVIEW.md unchecked lead.)

- [ ] **Unverified: `allowed_modules` from `./gridcalc.toml`.** If still honoured there, a directory can pre-approve `pandas`, which is handed over whole (see the trust-prompt entry under Low). Probe artefact exists; outcome not confirmed. (REVIEW.md unchecked lead.)

### Documentation & infrastructure

- [ ] **Check the prior art for named-input/output runs before claiming the feature is distinctive.** SharePoint Excel Services published named cells as parameters, Coherent Spark marks I/O names by prefix (`Xi_`/`Xo_`, unverified), and `formulas` compiles a workbook into a callable with `compile(inputs, outputs)`. gridcraft-cli can script it with `run --cmd`, reading a name through `formulas.evaluate`. Its `cell.set` ignores a name and writes the active cell with exit 0. `--print` and `range.setValues` reject names, an error output exits 0, and text inputs starting with `=` become formulas. pycel takes addresses only; names must be resolved through `excel.defined_names`, which needs openpyxl < 3.1. Corpus and timing results, 2026-11-07: `docs/dev/comparison.md`. Open:
  - Check the Spark convention against its documentation.

  - Find out whether gridcraft-cli's `--script` can reset state between cases. If they pass, gridcalc's case rests on the CLI, exit codes and correctness, and the docs should say that.

- [ ] **Build the docs site in CI.** The site itself is done (`mkdocs.yml`, 30+ pages under `docs/`, `make docs` / `docs-serve` / `docs-deploy`), and publishing stays a deliberate manual `make docs-deploy` -- the Makefile says why. The gap is that `ci.yml` never runs `mkdocs build --strict`, so a broken cross-reference between pages lands on `main` and is only found by whoever next deploys. Adding the `docs` group and one `make docs` step to CI is the whole fix; it does not commit or push anything.

- [ ] **CI runs part of the test suite.** `web-qa` (`tsc`, vitest), the `tty` suite and the `browser` suite never run in CI. The build job builds a wheel but tests the editable install. CI lint omits `scripts/`.

- [ ] **The wheel matrix stops at cp313 while the classifiers claim 3.14.** A 3.14 user installs the cp312-abi3 wheel, which CI tested only on 3.12. `build-abi3.yml` calls those wheels build-only, yet five were published with 0.6.0.

- [ ] **Windows on 3.15 is excluded.** `windows-curses` 2.4.2 has no cp315 wheel and no sdist, so `pip install gridcalc` fails there ([PyPI](https://pypi.org/project/windows-curses/#files)). When a cp315 wheel ships, drop the `exclude` in `ci.yml` and `cp315-win*` from `CIBW_SKIP` in `build-publish.yml`.

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

- [ ] **Confirm whether a row insert on one sheet shifts a 3D reference.** gridcalc leaves `Jan:Mar!B2` unchanged. The `3d-1` hand check in `docs/dev/excel-check.md` settles it.

- [ ] **`IMSQRT("-4")` keeps no residue.** Excel computes it in polar form and gives `1.22464679914735E-16+2i`; gridcalc gives `2i` (`misc-2`). Matching the residue is probably not worth it.

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

- [ ] **TUI keybindings system -- v2 generalisations.** All five contexts are wired (`grid`, `entry`, `visual`, `cmdline`, `search`) with curated action vocabularies; see `docs/keybindings.md`. Outstanding gaps for a future iteration: (a) **Removing hardcoded defaults.** `[keys.<ctx>] cancel = []` currently does *not* unbind Esc, because the hardcoded fallback chain still matches `ch == 27`. To make unbind work, the hardcoded chain has to migrate fully into `DEFAULT_KEYMAP` and the contexts must dispatch only via the action lookup. Mechanical but tedious. (b) **Bind-to-`:command`.** The action vocabulary is fixed at module load time. If users want `[keys.grid] save = [...]` where "save" runs `:w`, the schema has to grow a way to carry the command text alongside the key spec, and an `exec_command`-style action that takes parameters. Out of scope until someone asks. (c) **Pick-mode actions in entry.** The `KEY_UP`/`KEY_DOWN` cursor-pick sub-mode in `entry` is too tangled with local state to expose as actions today. Refactor it to a small state machine before binding it. (d) **Keymap warnings are erased.** They print inside the alternate screen, and the first draw clears them.

- [ ] **xlsx interop level (c) for HYBRID and PYTHON mode.** EXCEL mode round-trips formulas today: `Grid.xlsxsave` emits kind `'f'` with the formula text and a cached value, and `_core.xlsx_write` sets `cell.formula()`. The remaining gap is the other two modes, whose syntax (`**`, list comprehensions, `py.*`) is not Excel grammar -- they still export values. Closing it needs a serialiser from the gridcalc AST to Excel-grammar text, and is only worth it for the subset that has an Excel equivalent.

- [ ] **Migration tool `gridcalc migrate file.json`.** Attempts to upgrade a PYTHON-mode file to HYBRID by reparsing each formula with the EXCEL grammar and reporting the unparseable ones.

- [ ] **Visual-select operations.** Extend beyond `:f` -- support `:b` (blank range), `:dr`/`:dc` (delete selected rows/cols), `:r` (replicate into selection), copy/paste within selection.

- [ ] **System clipboard -- follow-ups.** Core integration and RFC 4180 quoting are done (see CHANGELOG). Remaining: verifying the Windows/Linux backends (`wl-clipboard`/`xclip`/`xsel`, `clip`/ `Get-Clipboard`) on real hardware -- developed on macOS against a fake backend.

- [ ] **Mouse support** (curses mouse events for cell selection and scrolling).

- [ ] **Plugin interface.** Allow third-party packages to register custom functions, commands, and cell formats via entry points or a plugin API.

### Security

- [ ] **Say what approving a whole module means at the trust prompt.** Modules in `SIDE_EFFECT_MODULES` are handed over whole by design, and the trust prompt is the boundary: approving one approves code execution (`pd.read_pickle`, `pd.io.common.os`). A facade cannot contain pandas, since `df.agg("to_pickle", ...)` dispatches by string. The prompts label these modules only "unrestricted" (`tui/__init__.py`, `tui/commands.py`, `TrustDialog.tsx`); say they can run any code.

- [ ] **Process isolation for PYTHON-mode recalc.** Only worth building if running untrusted workbook code becomes a supported feature; `LoadPolicy.formulas_only()` is the current answer everywhere but the TUI trust prompt. Buys a resource ceiling on every platform but filesystem confinement mainly on Linux. HYBRID's `py.*` gateway is a separate decision -- it is called mid-expression from the evaluator in the parent.

### Documentation & infrastructure

- [ ] **Review the areas REVIEW.md did not cover.** `libs/xlsx.py`; solver, goal seek and the C++ extensions; TUI, web `Api` and React client; packaging (sdist and wheel contents).

- [ ] **EXCEL grammar reference page.** Operators, precedence, error values, the function library, mode semantics. Add it to the docs site.

- [ ] **Pin GitHub Actions to commit SHAs.** `checkout@v7`, `cibuildwheel`, `setup-bun@v2`, `codecov@v5` and `pypi-publish@release/v1` are movable tags, used in jobs with `id-token: write`.

- [ ] **The Makefile `.PHONY` list and `help` omit targets.** Missing: `test-tty`, `test-web`, `test-stdlib`, the `web-*` targets and `bench`.
