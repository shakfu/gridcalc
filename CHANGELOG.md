# Changelog

## Unreleased

## [0.5.1]

### Added

- **The desktop app asks before running a workbook's code.** A JSON workbook can carry a Python code block, and the web frontend loaded every one of them formulas-only with no way to say otherwise -- so `example_hybrid.json` opened as a grid of `#NAME?` and stayed that way. It now opens the same dialog decision the curses frontend prompts for: cell and formula counts, the modules named split into classified / I-O / unclassified / blocked, and the code itself, gathered by parsing the file rather than running it. `Run code`, `Formulas only`, `Cancel`, with unclassified modules needing their own answer (the prompt's `[u]`, for the same reason: approving a file vouches for what the lists know about, and "not blocked" was never the same claim as "safe").

  The bridge grew `inspect(path)` and `pending_trust()`, and `open_file(path, policy)` a second argument. Anything but an explicit `load_code` loads formulas only, so a client bug cannot run a workbook by accident, and a file needing a decision that has not been made comes back `needs_trust` with nothing loaded. A workbook named on the command line is already open, formulas-only, by the time a window exists to ask in -- so the dialog comes up over the sheet the user can already see, rather than in front of nothing.

- **`load_workbook` takes a `LoadPolicy`**, and `loader.needs_trust` decides when a frontend has to ask. With the sandbox off it answers "never": no prompt would be shown, and withholding the code would leave the workbook broken for the one user who has said they want it run. That was already the curses rule at startup; it is now in the loader, where both frontends get it.

### Fixed

- **An error stopped being an error when read through a reference.** `Grid._cell_lookup_value` returned `cl.val` -- the NaN standing in for the value an errored cell does not have -- and never looked at `cl.err`, so the code was dropped at the reference boundary. `=1-A1` over a `#NAME?` produced an untyped NaN that rendered as the bare string `ERROR`, `=SUM(A1:A3)` the same, and every function that reports on an error could only see a number: `ERROR.TYPE` answered `#N/A` whatever it was given, `ISNA` answered FALSE over an `#N/A`, `IFNA` did not fire. The evaluator was already written for this -- `_eval_range` returns an error the moment a cell read yields one -- so the fix is the reader honouring `err`, plus three consequences of errors now actually arriving: `ERROR.TYPE`/`TYPE` and the `ISBLANK`/`ISNUMBER`/`ISTEXT`/`ISLOGICAL` predicates see the error instead of being short-circuited by it (Excel answers FALSE, not the error), and the COUNT family reads its ranges error-tolerantly, since Excel's `COUNT` ignores error values in a reference where `SUM` propagates them. `ISERROR`'s NaN arm stays: it is not covering for a lost code but for the values Excel has no name for, such as a HYBRID `py.*` function returning `float("nan")`. 36 new tests.

- **A literal overwriting an errored formula inherited its error.** `_setcell_no_recalc` reset every other result field and left `err` behind, which was invisible while nothing read it. Breaking a reference cycle by typing a number into one of its cells left `#CIRC!` on that cell, and once references started reporting errors it would have poisoned everything downstream.

- **`sandbox = false` in `gridcalc.toml` did not reach the trust prompt or the SANDBOX OFF banner.** Both read a `SANDBOX_ENABLED` imported by name at module load, and `configure_sandbox` rebinds it in `sandbox` -- so config could never change it and only the environment variable worked, because that one is read before either module imports. Both now read it through the module.

### Changed

- **Both console scripts parse their arguments with argparse.** The hand-rolled `sys.argv` checks got every convention wrong: `gridcalc --help` exited 1 and printed to stderr (so `gridcalc --help | less` showed nothing) while `gridcalc-web --help` exited 0, `-h` was recognised only as the *sole* argument -- `gridcalc -h book.json` tried to open a workbook called `-h` -- `--version` did not exist and was read as a filename, and the usage line interpolated `sys.argv[0]`, printing the absolute path of the venv shim. Both now take one optional positional, `-h/--help`, and `-V/--version`; an unknown flag is an error rather than a filename. `scripts/drive_web.py` follows, with `--window`/`--screen` as a mutually exclusive pair and the check name constrained to what exists.

- **The version is declared once, in `pyproject.toml`.** `gridcalc.__version__` was a second copy, and `make release` bumps only pyproject -- so the new `--version` flag would have reported the release before the last one from the first bump onward. `__version__` now reads the installed distribution's metadata, which is what the build wrote from pyproject; an uninstalled source tree reports `0+unknown (not installed)` rather than guessing. The read costs ~5ms on a 36ms import, `importlib.metadata` being already loaded by the time it runs.

- **The range-arithmetic block in `example_excel.json` no longer renders as `#SPILL!`.** `=sales - targets` and `=sales * 0.95` each return four values and sat in adjacent rows of column B, so the first one's spill range ran into the second one's anchor and both refused. They are now side by side in B18 and D18 under their own headers, with four clear rows beneath each. The file is one of the six a new user is told to open, and two error tokens in it read as a broken engine.

- **`make web-drive` crops its screenshots to the app window.** `screencapture` grabbed the whole display, so every shot carried the dock, the menu bar and whatever sat behind the window. The driver now finds its own window in the Quartz on-screen list by pid and passes that id to `screencapture -l`. `SHOT=--screen` (`--screen` to the script) restores the full-display grab, which is the one to use when the question is where the window itself sits; a missing window id falls back to it on its own. Both modes still need Screen Recording permission for the terminal.

## [0.5.0]

### Added

- **Quoted sheet names work in formulas: `='My Sheet'!A1`.** A name containing a space or punctuation could be created, and arrived through xlsx import, but no formula could name it -- the sheet was reachable in the tab strip and nowhere else. A doubled apostrophe is a literal one (`='It''s'!A1`). A single quote had no other meaning in this grammar, so nothing had to be disambiguated to make room for it.

- **`TRUE()` and `FALSE()` are accepted alongside `TRUE` and `FALSE`.** The lexer resolves the bare words to boolean literals before a function name is considered, so the call spelling parsed as a literal followed by stray parentheses and evaluated to `#VALUE!`. Only the empty call form is the literal; `TRUE(1)` still refuses.

### Changed

- **A workbook can no longer pull in any installed module by naming it.** `load_modules` imported everything the blocklist did not name and the trust prompt approved everything not blocked, so `runpy`, which runs a Python file, and `sqlite3`, which writes one, were loaded on a workbook's say-so -- and neither appeared in the prompt as a risk, because the prompt only had labels for "blocked" and "I/O". Modules that no list classifies are now refused, and refused *before* the import, so one with an import-time side effect does not get to run either. The prompt lists them on their own line and `[u]` approves them as a separate answer to `[a]`, rather than making "not blocked" mean "safe" -- the blocklist names the dangers known when it was written, which is the argument against using it as the gate. A version-pinned spec (`numpy>=1.24`) was classified from the raw string and so counted as unknown; it is parsed first now. 4 new tests.

- **`docs/security-plan.md` records that there is no resource boundary.** Workbook code runs in the application's own process, and AST validation permits loops and large allocations because neither is distinguishable from legitimate computation by inspecting a syntax tree: `while True: pass` hangs the application. Containing it needs a worker process with wall-clock and memory limits, not a stricter validator, so this is documented rather than fixed. The same pass corrected the module categories and a stale file path. `docs/dev/sandbox-isolation.md` is a new design note recording what a process boundary would take, what it would and would not buy on each platform, and why a curated module facade is the cheaper first move.

### Verified (no fix needed)

- **The HiGHS constraint matrix is not missing a terminal offset.** A review reported that `_opt.cpp` builds `a_start` with `m` entries where row-wise CSR needs `m + 1`, and called the result undefined behaviour. The C API takes exactly `num_row` offsets and appends the nonzero count itself (`Highs.cpp:582-596`, and `:633-635` for the Hessian); its own documentation says the array is of length `[num_row]`. Appending the offset would be inert rather than harmful, but it is not a fix. Nothing had exercised the extension boundary directly, so the claim could only be settled by reading vendored source; 3 tests now pin it by observation -- a model whose *final* row binds, a Hessian whose second column carries the only term keeping a variable off its bound, and a cross term in the lower triangle. Each was checked against a deliberately truncated `Highs_passLp`/`Highs_passHessian` call and fails there.

- **Renaming a sheet does not lose the web grid's cursor.** The per-sheet view entry is keyed by sheet name, which a rename changes, so the entry looked stranded. It is not: the entry is written on unmount from the closure of the last render, so it lands under the new name. Pinned by a test, which passes against the code as it stood.

### Fixed

- **Inserting or deleting a row rewrote references to *other* sheets.** Both text scanners rewrote every reference in the active sheet's formulas whether or not it carried a sheet qualifier, and never looked at the other sheets at all. Inserting a row on Sheet1 turned `=Data!A2` into `=Data!A3`, silently repointing it at a cell Data never moved, while a formula on Data reading `=Sheet1!A2` was left behind pointing at the wrong row. Both scanners now move exactly the references that resolve against the edited sheet, across every sheet in the workbook -- the rule `_shift_names` already applied to named ranges, and the two scanners are now one function rather than two copies that could drift. Found while testing quoted sheet names, not in the review that prompted this batch. 7 new tests.

- **Structural edits rewrote the text inside string literals.** 0.4.0 taught `adjust_refs` and `_expand_ranges` to skip quoted regions but missed the two scanners behind insert, delete and swap, so swapping two rows turned `="A1"` into `="A2"` and `="hello A2 world"` into `="hello A1 world"`. Excel's doubled-quote escape is handled, as it already was on the copy path. 6 new tests.

- **Comparing an empty cell answered wrongly, or not at all.** An empty cell reaches the evaluator as `None`, which orders against nothing: `=A1<A2` on two empty cells raised a TypeError that surfaced as a bare NaN with no error set -- a value that reads as a number. `=A1=0` answered FALSE where Excel answers TRUE. An empty cell now takes the type of whatever it is compared against and that type's zero, which is what arithmetic on it already did. An ordering that is genuinely undefined reports `#VALUE!` rather than a valueless NaN. 17 new tests.

- **`ISFORMULA` kept its old answer after the cell it names changed.** It was classed address-only alongside `ROW`, whose answer cannot change when the referenced cell is edited -- but `ISFORMULA` reports the cell's *kind*, so turning `A1` from a literal into a formula left `=ISFORMULA(A1)` reading 0 until something forced a full recalc. Its argument now enters the dependency graph. `ROW`, `COLUMN`, `ROWS`, `COLUMNS`, `ISREF` and `AREAS` stay address-only, being purely positional. 5 new tests.

- **A cut marked the web workbook dirty before anything changed.** Cut and copy both only fill the engine's clipboard buffer; the source cells are cleared later, by the paste that consumes them. Routing cut through the mutation path meant cutting and then cancelling reported unsaved changes over an untouched workbook. Paste already reports its own mutation. 2 new tests.

- **Reopening a workbook at the same path kept the previous one's cursor.** The web grid was keyed on filename and sheet index, so a second open of the same path changed neither and the grid never remounted: it kept a cursor and scroll position describing a workbook that had been replaced. A load counter now participates in the key and clears the remembered per-sheet positions, which is what keying on the filename was meant to achieve. 1 new test.

- **`make qa` failed on a clean checkout.** mypy checks against `python_version` 3.10, where typeshed carries no stdlib `tomllib`, so it resolved the running interpreter's copy instead and reported it as an unstubbed package; the `# type: ignore[import-not-found]` guarding the import named the wrong code and was itself flagged unused. `tomli` is now an unconditional *dev* dependency -- as a runtime dependency its `python_version < '3.11'` marker correctly excludes it from the 3.11+ venv that mypy runs in, leaving the branch it type-checks with no module to resolve -- and the import is a `sys.version_info` test rather than try/except, which mypy evaluates statically to pick that branch. Python 3.10 support is unchanged, and `tomllib.load` keeps its real signature instead of degrading to `Any`.

- **Exporting a workbook whose first sheet is still named `Sheet1` merged it into the next sheet.** OpenXLSX also calls its auto-created sheet `Sheet1`, so the writer treated the first payload sheet as already present, left the default unclaimed, and then renamed it to the *second* sheet: both sheets' cells landed in one worksheet, the first sheet's values were overwritten, and nothing reported an error. Since `Sheet1` is the name nobody renames, the default configuration was the broken one. The default sheet is now tracked as consumed independently of what it is called. Empty sheets were dropped by the same function for a different reason -- they contribute nothing to a cell payload, so the writer never learned they existed -- so `xlsxsave` now passes the workbook's full sheet list, which also settles export order rather than letting it fall out of whichever sheet held the first non-empty cell. The existing multi-sheet test renamed `Sheet1` before exporting and so met neither bug. 3 new tests.

- **A malformed field in a workbook file crashed the loader after it had already cleared the workbook.** 0.4.0 type-checked every *structure* `jsonload` reaches into, but not the scalar fields: a JSON number in `code` reached `ast.parse` and a number inside `requires` reached the requirement regex, raising from below the reset -- so the file was refused and the open workbook was gone, out of a function documented to report failure by returning -1. Both are now checked above the reset. `inspect_file` had the same gap and mattered more because `:open` calls it first, before the load. Separately, `:open` cleared cells, names and code itself before calling `jsonload`, so any unreadable file emptied the workbook, including the files the loader was already careful to reject without mutating; that pre-clear is gone, `jsonload`'s own reset being a superset of it. 10 new tests.

- **An error value in a constraint cell tore down the TUI.** `_opt` reports a failed HiGHS call with `std::runtime_error`, which nanobind exposes as `RuntimeError` -- a type neither `opt.solve` nor the `:opt` handler catches, so it escaped the command loop and took curses and the unsaved sheet with it. Reaching it needs nothing exotic: a constraint whose right-hand side reads an error cell arrives as NaN and HiGHS rejects the whole model. Bounds were already checked for NaN; the objective and constraint rows now are too, and they name the offending cell instead of reporting `Highs_passLp failed`. Native failures are normalised to `OptError` at the single boundary that calls the extension, so the three call sites cannot diverge. 4 new tests.

- **`IF` evaluated both of its branches.** `=IF(A1=0, "n/a", B1/A1)` -- the standard guard against dividing by zero -- answered `#DIV/0!`, because the evaluator materialised every argument and then propagated the first error among them. `IF`, `IFS`, `SWITCH`, `IFERROR`, `IFNA` and `CHOOSE` now evaluate only the arguments their result depends on; an error in the *condition* still propagates. Dependency extraction is deliberately unchanged and still walks every branch, so a cell read only by the branch not taken remains a dependency, and a self-reference in an untaken branch is still circular: a graph whose shape depended on the current values could not be topologically ordered before evaluating it (`docs/topological.md`). 14 new tests.

## [0.4.0]

### Changed

- **The client toolchain runs on Bun; Node and npm are gone.** `make web-build` failed outright on a machine with `nodejs` installed but not `npm` -- the two are separate packages on Debian/Ubuntu -- and the fix was to stop needing either. Bun is both the package manager and the JavaScript runtime, so `bun install` replaces `npm ci` and `bun --bun run` replaces `npm run` in the Makefile and in `.github/actions/build-web-ui`, which now sets up Bun instead of Node. `bun.lock` replaces `package-lock.json` (67 kB against 136 kB, 205 packages either way). Installs drop from 3.0s to 1.7s and the produced `static/index.html` is byte-identical to the one npm built, verified by hash.

  `--bun` is structural rather than decorative: without it `bun run` honours the `#!/usr/bin/env node` shebang in `node_modules/.bin` and silently shells out to Node, which passes on a developer machine and fails in CI, where no Node is installed. Every step was verified with a fake `node`/`npm` on `PATH` that exits 127, so any hidden fallback fails loudly instead of quietly working.

- **The vitest suite runs in happy-dom instead of jsdom.** 99 tests in 1.71s against 2.70s, a 1.6x cut, and one fewer dependency tree (205 packages to 176). happy-dom implements the pointer-capture, `scrollIntoView` and `ResizeObserver` APIs that the Radix primitives reach for, so the twenty lines of stubs `test/setup.ts` carried for jsdom are gone -- verified inert before removal, since every one sat behind an `if (!...)` guard that could no longer fire.

  It changes what the component tests assert against, so the comments justifying the Playwright layer were rewritten rather than renamed: happy-dom does no layout either, every box measuring zero, but unlike jsdom it *stores* `scrollTop`, so the old claim that it "reports `scrollTop` as a permanent zero" had quietly become false in four places including a Playwright docstring that exists because of it.

  `bun test`, Bun's own runner, was measured as the alternative and rejected. It needs a shim layer -- a DOM registrator, a hand-rolled `vi` global for 59 `vi.fn` sites, `expect.extend` for jest-dom, and `DEV=true` because `src/bridge/mock.ts` guards on Vite's `import.meta.env.DEV` -- and returns 2.63s, slower than vitest on happy-dom. It also runs every file in one process with no isolation: before an explicit `afterEach(cleanup)` was added, the full suite grew to 4.35 GB and crashed Bun itself. The speed was never the runner; it was the DOM.

- **The development environment is pinned to Python 3.14.** A new `.python-version` (there was none, so uv picked 3.13 by default). This is what lets a virtualenv reach the system GTK bindings, which are compiled per interpreter version -- see the `make web-run` fix below. uv's managed builds ship the development headers the C++ extensions need; a distro interpreter usually splits them into a separate package, and building against one without it fails in CMake with `Could NOT find Python (missing: Interpreter Development.Module)`. CI still tests 3.10 and 3.12.

- **`Grid.insertrow` / `insertcol` return `bool`.** They refuse an insert that would push a populated line off the fixed sheet rather than performing it -- see below. Callers that ignore the result are unaffected.

### Fixed

- **A selection solve ignored the "write the solution to the sheet" checkbox and overwrote the decision cells anyway.** The checkbox sits in the same row as the button it did not govern: `solveModel` sent `apply: applyToSheet`, `solveSelection` sent only coordinates and a sense, and `_run_solve` defaults `apply` to true. Unchecking the box and clicking the adjacent "Solve selection" destroyed exactly the cells the user had just protected. `apply` is now threaded through `solve_selection`, the TypeScript bridge type, the call site, and both mocks, so the dev server and the Chromium suite reflect the real behaviour. 6 new tests across Python and TypeScript; the omission existed at both ends, so each half was checked against the unfixed code separately.

- **Clearing or replacing a PYTHON-mode code block did not revoke what it had defined.** `_recalc_python` executed user code straight into the persistent evaluation namespace, so definitions outlived the block that made them: define `f`, use `=f()`, delete the code, and the formula kept answering 42. A replacement block inherited whatever the previous one had defined but it did not, and a block rejected by validation left the earlier definitions live. The namespace is now derived fresh from a clean base on every pass -- the discipline `_build_py_registry` already used for HYBRID, which is why HYBRID never had this bug. A third symptom the review that found this did not mention: the polluted namespace is handed to EXCEL/HYBRID evaluation as `builtins`, so a mode switch carried the leaked names along. The `_injected_names` unbind pass added in 0.3.1 is deleted, since a fresh namespace makes stale bindings structurally impossible. 5 new tests, all checked against the unfixed code.

- **Valid JSON that is not a workbook crashed the loader instead of being rejected.** `jsonload` reports failure by returning -1, but `[]`, `null`, a bare number or a string all decode cleanly and then raised `AttributeError` off the first `.get()`. `names` as a list did the same on `.items()`, and `format` as a list on `.get()`. Two more the review did not list: a name whose range is a number raised from `"!" in rng`, and a non-numeric `width` from the `4 <= w <= 40` comparison. Every structure the loader reaches into is type-checked; a malformed *optional field* is skipped and the rest of the workbook still loads, matching how `libs`, `requires` and `models` already behaved. 11 new tests.

- **Undoing a structural edit put the cells back but left the named ranges and column widths shifted.** `save_grid` snapshotted cells, cursor, format and sheet name and nothing else, so inserting a row and undoing it returned the data to rows 0-4 while `block` stayed at rows 3-5 -- `=SUM(block)` then silently computed over the wrong region, the failure mode `docs` has called the worst available since 0.3.1. Snapshots now carry named ranges and column widths. Three details are structural: the copy is deep, because a structural edit rewrites `NamedRange` objects in place and would otherwise mutate the snapshot recording it; membership is restored as well as coordinates, because a range that loses every line it covered is dropped from the list entirely; and the rollback entry carries the metadata too, or undo would work and redo would silently diverge. Metadata rides only on grid-level snapshots, so undoing a one-cell edit does not revert an unrelated `:name`. 7 new tests in a new `tests/test_undo.py`.

- **Copying a formula rewrote the text inside its string literals.** `adjust_refs` and `_expand_ranges` scanned raw formula text for anything shaped like a cell reference, and prose is shaped identically: pasting `="A1"` one column right produced `="B1"`, `="col A1 total"` became `="col B1 total"`, and `"A1:B2"` in a legacy string was expanded into a `Vec(...)` call. Both transformers now skip quoted regions, handling Python backslash escapes, Excel doubled-quote escapes, and single quotes -- which delimit strings in PYTHON mode and sheet names in Excel, and should be rewritten in neither. An unterminated literal swallows the rest of the text, on the principle that adjusting nothing beats corrupting something. Real references outside literals still shift. 12 new tests.

- **Inserting near the end of the sheet silently destroyed the last row or column.** The sheet is a fixed 1024x256 grid, so an insert at the boundary had nowhere to put the final line and simply dropped it, while the command reported success. `insertrow`/`insertcol` now refuse without mutating, and `_insert_lines` checks the whole count up front via a new `Grid.can_insert`, so a three-row insert with room for two is refused entirely rather than half-applied, and no undo entry is recorded for an edit that never happened. Two existing tests asserted the old behaviour -- that the boundary cell was `EMPTY` afterwards, which is to say that the user's data had been destroyed -- and were rewritten. 5 new tests.

- **Loading a workbook merged into the open one instead of replacing it.** The v1 path wrote its cells into whichever sheet was already open, so anything outside the incoming payload survived: open a two-cell workbook over a populated one and the old data was still there. The code path was worse and is a trust-boundary failure -- `LoadPolicy.formulas_only()` exists to say "do not run this file's code", but because `jsonload` only assigned `code` when permitted, refusing left the *previous* workbook's code in place and still callable. A load now resets sheets, cells, the dep graph, names, models, libs, requires, code and the evaluation namespace before populating. The reset sits after every failure return, so a rejected file cannot leave a half-cleared workbook behind -- pinned by its own test. 6 new tests.

- **`Api.viewport` returned negative sizes for an out-of-range origin.** The origin was clamped at zero but the ends derived from the unclamped value, so `viewport(999999, 0, 10, 10)` answered `rows: -998975`. A virtualising client sizes its spacers from those numbers, and a bridge boundary should not hand back arithmetic that cannot describe a rectangle. 7 parametrized cases.

- **A refused bridge call was reported to the user as a successful edit.** The guards in `Grid` and `useWorkbook` catch a *rejected* call -- the marshalled Python call threw -- but a call can resolve normally and still report that it did nothing: `Api.paste` answers `{ok: false}` when there is no clipboard. Treating every non-null result as success marked the workbook dirty, bumped the revision and refetched the viewport for a mutation that never happened. A shared `failureOf` helper now distinguishes the two, and a refusal is reported like a rejection. 7 new tests.

- **Saving or deleting an optimization model left the status bar claiming a clean workbook.** Models are workbook state -- `jsonsave` serializes them -- and the bridge marks the workbook dirty on both, arming the *native* close guard. The dialog refreshed only the model list, so the status bar showed no unsaved-changes marker while closing the window then asked about unsaved work; a user trusting the status bar could discard a model they had just defined. 3 new tests, one of them asserting a *rejected* save still reports no change.

- **`make web-run` could not start the app.** It never passed `--extra web`, so `uv run` resolved an environment without pywebview and the entry point died on `import webview` -- while `web-drive`, two targets below, had always passed it and the target's own comment said it was needed. Fixing that exposed the real blocker: pywebview draws in the platform's native webview and needs a GTK or Qt backend, which is not a Python package uv can resolve. `web-run` and `web-drive` now probe for the system GTK bindings and add them to `PYTHONPATH` only when they genuinely import, so a mismatched virtualenv falls through to pywebview's own "install a backend" message rather than an `ImportError` traceback. The probe is lazily expanded, so it never runs for `make test`. `docs/install.md` documents the backend requirement, which `pip install 'gridcalc[web]'` alone does not satisfy on Linux.

- **A fresh checkout could not follow its own build instructions.** `docs/install.md` says to run `make build` then `make web-build`, but the packaging config force-includes the web bundle that `make web-build` produces, so `make build` failed on a clean clone with `FileNotFoundError: Force-include source 'src/gridcalc/web/static/index.html' not found`. `make build` now generates an inert placeholder when the bundle is absent, which keeps the terminal-only path buildable with no Bun installed. It cannot masquerade as a real build: `_load_html` refuses to open a window on its marker, it omits the `id="root"` mount point the CI action greps for, and the release workflow's distribution check now rejects it explicitly -- that check previously verified only that the bundle was *present*, so a placeholder would have shipped a wheel with a dead UI. 3 new tests, and the existing one rewritten -- it branched on whether the developer happened to have built the frontend, so it could not cover the new states.

- **`make test-stdlib` could pass against code that was no longer in the tree.** uv keys its built-wheel cache for a local path on the project metadata rather than the source files, so editing `src/gridcalc/*.py` did not invalidate it and the target happily reinstalled a wheel built hours earlier. `--refresh`, `--refresh-package`, `--reinstall` and `uv cache clean` all fail to evict it; only `--no-cache` does, at the cost of a full C++ rebuild (about 50s against 2s cached). A gate that can report a pass for deleted code is not a gate.

- **Several web dialog fields had no accessible name.** The goal-seek, sweep, chart and sheet dialogs labelled their inputs with a visually adjacent `<span>`, which is not an accessible name, so a screen reader announced a row of unnamed text boxes; the in-cell editor was unnamed too. Fifteen inputs gained `aria-label`s, the cell editor's naming the cell being edited. The radio and checkbox controls already wrapped their inputs in a `<label>` and were left alone. 3 new tests.

### Documentation

- **The web bridge's trust model is written down.** `Api.open_file` and `Api.save` take any path the caller passes, which a security review flagged as unenforced. Enforcing a permitted-directory policy would break the feature -- a spreadsheet saving where the user chose is the point -- so the module docstring now records what the freedom actually rests on: the window is created from an inlined HTML string rather than a URL, so the view never navigates and loads no remote code, and cell contents render as escaped React text nodes. It also names what would invalidate that: pointing the window at a URL, allowing remote assets, or rendering cell content as HTML would turn the bridge into an arbitrary local file read/write primitive and would need a path policy first.

### Known limitations

- **The web grid still lacks ARIA grid semantics.** The cell layer renders only non-empty cells as absolutely positioned siblings, with no row containers, and the ARIA grid pattern requires `role="row"` between the grid and its cells. Adding `role="gridcell"` to positioned siblings would be invalid ARIA and would report a broken grid to assistive technology rather than no grid at all, so this needs the virtualized renderer restructured into rows and is left as its own piece of work.

## [0.3.3]

### Added

- **A documentation site, and the end of the 585-line README.** `make docs` builds an MkDocs site (Material theme, `mkdocs.yml` at the root) from `docs/`; `make docs-serve` previews it with live reload, `make docs-deploy` publishes it to `gh-pages`, `make docs-clean` removes the build. The README had been the user manual and had grown past the length anyone reads in a scroll: install, tour, formulas, three-mode semantics, the entire optimization chapter with sensitivity and sweeps, formatting, import/export, the file format, config, and a command reference, in one file with in-page anchors doing the work of navigation. Those are now pages -- `index`, `install`, `tour`, `desktop`, `guide/{modes,formulas,sheets,optimization,goal-seek,formatting,import-export,config}`, `reference/{commands,file-format,limitations}` -- and the README is a ~110-line landing page that links to them. Nothing is documented twice: the prose moved rather than being copied, which is the only version of this split that does not immediately start drifting.

  The seven design notes stay flat at the top of `docs/` and are grouped by the nav instead of being moved into a subdirectory. CHANGELOG, TODO, and source comments cite them by repo-relative path (`docs/topological.md`, `docs/web.md`, and so on) in dozens of places, most of it history that should not be rewritten to tidy a directory listing. The changelog is pulled into the site by a pymdownx snippet include rather than copied under `docs/`.

  `reference/api/` is generated from the docstrings by mkdocstrings, covering `engine`, `formula`, `opt`, `goalseek`, `config`, and `sandbox`. `tui/`, `web/`, and the ~5000-line `libs/xlsx.py` are deliberately excluded: the first two are internal to their frontends, and a wall of one-line signatures describes the function library far worse than `docs/function_coverage.md` already does. Because mkdocstrings reads the sources statically through griffe, building the docs needs neither the compiled `_core`/`_opt` extensions nor an importable install.

  `tests/test_docs_conformance.py` moved with the prose. It parses the manual for every `:` command and every key and asserts the dispatcher implements each one, and vice versa -- the guard that exists because the `u`/`Ctrl-R` undo bug shipped out of exactly that drift -- so trimming the README would have quietly gutted it. It now reads README plus `docs/index|install|tour|desktop.md`, `docs/guide/*.md`, and `docs/reference/*.md`, globbed so a new page is covered the moment it lands. Design notes, the changelog, and the generated API pages are excluded: a command named in a proposal or a release note is not a promise to the user. The retargeted parsers were diffed against the old README's and extract exactly the same sets -- no command, plain key, or Ctrl binding gained or lost -- which is the evidence that the split dropped nothing the tests were watching.

  The site builds under `--strict`, so a broken cross-reference fails rather than shipping. That caught two on the first run. Docs dependencies live in a `docs` dependency group rather than `dev` -- `uv run --group docs` pulls them only when a docs target runs, keeping them out of the test and QA path -- and `mkdocs` is capped below 2.0, which Material's own release notes say removes the plugin system that mkdocstrings, search, and the theme all depend on. Nothing in CI publishes: `docs-deploy` commits and pushes, and that stays a deliberate manual step.

### Fixed

- **Resizing a column in the web frontend now marks the workbook unsaved.** Column widths are per-sheet state the workbook carries -- `Api.set_col_width` ends in `_touch()` and its docstring says so -- but the drag path in `Grid.tsx` persisted the width through `guard`, which only routes bridge rejections to the status channel, instead of `mutate`, which additionally tells the app the workbook changed. So the width was saved into the model and the dirty marker stayed clear: resize a column, see no unsaved indicator, close, and the close-confirmation never fires on a change that was real. The command-palette route to the same operation had always called `touched()` on success, which is why this only ever reproduced by dragging. 1 new `Grid` test, driving a real mousedown/mousemove/mouseup on the resize handle and asserting both the notification and the persisted width; it was checked against the unfixed code.

### Changed

- **`make docs` no longer points at a Sphinx build that never existed.** The target ran `sphinx-build -b html docs/ docs/_build/html`, but `sphinx` was not in any dependency group and `docs/` held no `conf.py`, no `index.rst`, and no toctree -- so the target had never once worked, and adding the dependency would only have installed a builder for a documentation tree that was not there. It is now the MkDocs build described above.

- **Ruff's project config excludes `thirdparty/`.** The Make and CI commands scope Ruff to the owned paths (`src/`, `tests/`, `scripts/`), so the vendored HiGHS and OpenXLSX checkouts were never linted there -- but a bare `uv run ruff check`, which is what an editor integration and a new contributor both run, reported 110 errors from HiGHS's Python example scripts. Config that only tells the truth when invoked through the Makefile is a trap; `[tool.ruff]` now carries the exclusion itself.

## [0.3.2]

### Added

- **`make web-drive` -- a driver that runs the real web app and screenshots it.** Both automated layers guarding the web frontend run against a substitute: vitest in jsdom, which does no layout and reports `scrollTop` as a permanent zero, and the Chromium bundle suite against a mocked bridge. Neither can answer "does it actually sit where it should, in the production webview". `scripts/drive_web.py` mirrors `web.run()` -- same window, same real `Api` over a real workbook -- but hands `webview.start` a driver thread that drives the live webview through `evaluate_js` and captures the screen at each step. It is not a test and is excluded from `make qa`: it needs a display and is not deterministic enough to gate a build. Two checks ship with it, `CHECK=sheets` and `CHECK=solve`, both written while verifying the fixes below.

  The reason it is committed rather than thrown away is its header. Scripting this particular UI has four non-obvious traps, each of which reads as an app bug until you find it: keydowns dispatched in one synchronous loop all read the same pre-render state, so only the last appears to take; Radix's Select and Menubar ignore synthesized pointer sequences and must be driven by keyboard; Radix mounts dropdown content in a portal a tick after the trigger fires, so a typeahead sent too early is dropped silently; and React ignores a plain `input.value = x`. `scripts/` joins `make lint` and `make format`, since a script outside the quality gate is the liability `docs/web.md` already complains about elsewhere. It is not under `make typecheck`, which would mostly be arguing with the pywebview stubs.

### Fixed

- **Switching sheets in the web frontend no longer throws away where you were.** The grid is remounted per sheet, and a remount reset the cursor, the selection and the scroll offset to A1 -- so returning to a sheet you were working three hundred rows down landed you at the top of it. The remount stays, because it is what makes mount the moment the incoming sheet's column widths are known and what keeps the outgoing sheet's cells from being painted under the new sheet's addresses; the view state is carried across it instead, stashed per sheet by the app.

  Keyed by sheet name rather than tab index, since an index does not identify a sheet across a reorder, and prefixed with the filename so a newly-opened workbook cannot inherit the previous one's positions. Two ordering details are structural: the scroll offset is restored before the mount effect that focuses the grid (focusing a container the browser considers scrolled-away scrolls it back), and the fetch position is seeded from the same state, so the first viewport request asks for the restored rows rather than row 0. 5 new tests -- 3 on `Grid`, 1 on `App`, 1 in the Chromium bundle suite, that last one because jsdom does no layout and its `scrollTop` is a permanent zero. All five were checked against the unfixed code.

- **A solve no longer follows the user to another sheet.** The marks a solve paints onto the grid -- objective, decision cells, binding constraints and their shadow prices -- were cleared by an edit but not by a sheet change. They are *addressed* in A1 and *painted* by position, and an A1 reference names a different cell on every sheet, so a tab switch did not merely show a stale result: it put the previous sheet's shadow prices on cells that had nothing to do with the model, hover text included. The rule was already right and only its second trigger was missing; both now clear through one function, keyed on workbook and sheet, so opening a different workbook clears them too. 1 new `App` test. Pre-existing since the annotation layer landed, and found by the view-state work above rather than caused by it.

## [0.3.1]

### Fixed

- **Named ranges now follow their cells across insert and delete.** `_shiftrefs` rewrote references written in cell *text* on a structural edit but nothing moved the rectangles held in `g.names`, so a name kept pointing at the coordinates it had before the edit: `Data = A2:A3`, insert a row above it, and `=SUM(Data)` silently returns the wrong number with no error to notice it by -- the worst failure mode available, and the reason `TODO.md` listed this as a hard prerequisite for structural editing in any frontend. A new `Grid._shift_names` is the sibling of `_shiftrefs` and is called from all four of `insertrow`/`insertcol`/`deleterow`/`deletecol`. The rules match a spreadsheet's: a line inserted above a range moves it, one inserted inside grows it, deletes mirror both. A delete that consumes every line a range covers drops the name, so a formula using it fails as an unknown name -- visible -- rather than resolving to a rectangle that no longer means anything; Excel shows `#REF!` here, and the difference is the error text, not the outcome. Only names resolving against the edited sheet move: a sheet-qualified name bound elsewhere is untouched, and a sheet-agnostic one follows the active sheet because that is where it resolves. The TUI's `:ir`/`:dr`/`:ic`/`:dc` inherit the fix. 9 new tests covering insert and delete above, inside, and below a range, the collapse case, columns, and both sheet-binding kinds.

  Fixing it exposed a second, narrower bug: PYTHON mode injects named ranges into eval globals that persist across recalcs, and nothing ever *unbound* a name that had gone away. A dropped name therefore kept resolving to the `Vec` injected on the previous pass, so the formula showed a stale answer where EXCEL and HYBRID correctly went to `nan`. `_recalc_python` now unbinds names that no longer exist; `:unname` benefits from the same fix.

- **Keyboard shortcuts no longer reach through a focused text field.** `App.tsx`'s window-level Ctrl/Cmd handler fired regardless of where focus was, so typing a cell reference into the Goal Seek dialog and pressing Ctrl+Z to fix a typo undid the *workbook* instead of the field, and Ctrl+B/I/U reformatted the sheet behind the open dialog. The grid's own editors stop propagation themselves; a dialog cannot, because the listener is on the window. Undo/redo and the format toggles now defer to any focused input, textarea, select, or `contentEditable` host. Open and save deliberately do not -- no text field lays claim to them, and losing Ctrl+S because focus sat in the name box would be its own small bug.

- **Undo history is sheet-aware.** `UndoEntry` recorded cell coordinates but not which sheet they came from, and cell keys are per-sheet -- so undoing after switching tabs restored the old cells into whichever sheet happened to be active, overwriting real data on a sheet the user had never edited. `is_grid` entries were worse, since they `clear_all()` first: an undo taken on the wrong tab wiped it. Every snapshot now records its sheet, and `_apply` switches back to it before restoring, which also puts the user's view where the change they are undoing actually happened. An entry whose sheet has since been deleted is dropped rather than misapplied. Pre-existing in both frontends; reachable far more often now that the web view can add and delete sheets.

### Changed

- **`:` commands moved into a shared, frontend-neutral registry.** Each command used to be implemented twice: as a branch of the TUI's `cmdexec` name dispatch, and again as a `web.Api` method plus a hand-written palette entry, with nothing tying the two together. Behaviour was duplicated, the parity table in `docs/web.md` was kept by hand, and a command added to one frontend was invisible to the other. `gridcalc/commands.py` now holds the operation -- name, aliases, argument specs, and a function over a `Context` -- and both frontends dispatch it by name over one implementation. `tests/test_architecture.py` keeps the module curses-free, as it does for `display.py` / `loader.py` / `undo.py` / `search.py`.

  **The seam is: the view resolves arguments, the registry does the work.** A terminal prompts on the status line or opens a range picker; a GUI opens a field; both then hand the same strings to the same function. Argument *collection* is the part that genuinely cannot be shared, so that is exactly where the split sits. Presentation stays per-frontend too, and deliberately differs: the TUI stops for a keypress on a failure or a query but says nothing after a mutation (the redrawn grid is the feedback), while the web view flashes every message in a status bar that does not block. `Result` carries both a one-line `message` and a `lines` listing so `:names` can be a pager in one frontend and a status line in the other without the *data* being derived twice.

  Fourteen commands moved: `:b`, `:f`, `:gf`, `:ir`, `:ic`, `:dr`, `:dc`, `:name`, `:names`, `:unname`, `:sort`, `:mode`, `:title` (with `:tv`/`:th`/`:tb`/`:tn` as argument-baked shorthands), and `:recalc` -- the last also being what `!` now runs, so the key and the command cannot drift. Commands whose whole body is interaction stay view-owned and that is not a gap: `:e` shells out to `$EDITOR`, `:view` draws a scrollable table, `:sheets` opens a picker, `:q` asks before quitting, `:m`/`:r` run modal range prompts, `:csv`/`:xlsx`/`:pd` prompt for a path. A GUI equivalent of those is a different interaction, not a shared function.

  **The web frontend gained `:sort`, `:mode`, and freeze panes for nothing** -- they were never implemented there, and arrived the moment the registry did, which is the return the refactor was for. `Api` lost seven methods (the four structural edits, three named-range methods, and `recalc`) in favour of `run_command`/`list_commands`; `set_format` and `clear_range` survive as keyboard entry points but now delegate to the shared bodies rather than repeating them. The palette builds its entries *from* `list_commands`, so registering a command needs no TypeScript edit at all.

  **Parity is now a test rather than a table.** Two guards replaced the hand-kept documentation: one fails if a view-owned `cmdexec` branch shadows a registry name (the registry runs first, so such a branch is unreachable and one of the two implementations is a lie), and one fails if the bridge filters the registry on its way to the client, with a vitest counterpart asserting the palette renders one entry per descriptor. Both were checked by deliberately breaking them -- an earlier draft of these tests enumerated the registry on both sides and so could never fail, which is worth noting as the failure mode a conformance test invites.

  Two behaviour changes fell out and are intentional. `:ir`/`:ic` now insert as many lines as the selection spans, matching what the delete side has always done and what the web menu label already promised; inserting one row while three were selected was the odd case out. And `:title` is now documented as a command in its own right, with the four shorthands as aliases.

### Added

- **A Ctrl-K command palette, and the commands that had nowhere else to live.** gridcalc's terminal frontend reaches everything through `:` commands. A GUI cannot inherit that modal line editor, but it should not lose the reach either -- menus only ever justify the *common* commands, which left `:width`, `:name`, `:names`, `:unname`, and `!` with no home in the web view at all. The palette is that home, and the cost of adding one is now a registry entry rather than a bespoke dialog.

  Two pieces make that true. Matching (`lib/commands.ts`) is subsequence-based rather than substring, so `fld` finds `Fill down` -- the reason to type into a palette instead of reading a menu -- with contiguous matches outranking scattered ones and title matches outranking group-name ones. And commands may declare an *argument*: the palette collects the value in a second step through the same input, so `Set column width`, `Define name`, `Delete named range`, `Go to reference`, and `Custom number format` all work without a dialog each. Escape from the argument step returns to the list rather than closing the palette, which has to be handled through Radix's `onEscapeKeyDown` -- Radix listens on the document, so stopping React's synthetic event never reaches it. Commands that cannot act right now (no selection, single sheet) are hidden rather than offered and then failed. Menu-backed commands are registered too: a palette that only knew the obscure half would be a worse menu rather than a faster one.

  Backing it, three new `Api` methods complete named-range management -- `list_names`, `set_name`, `delete_name` -- plus `recalc` for the TUI's `!`. Names are validated the way the TUI validates them (a letter, then letters/digits/underscores) and additionally refused when they read as a cell reference: `B7` as a name would make `=B7` ambiguous, and refusing is better than inventing a precedence rule the user has to learn. Deleting a name leaves formulas using it as visible unknown-name errors rather than rewriting them to a guess. `recalc` deliberately does not dirty the workbook, matching `!` -- asking for the values you already had is not an edit.

- **Find in the web frontend, and search promoted below the view boundary.** The matching itself was already frontend-neutral but lived in `tui/search.py`, so reusing it meant importing the curses view -- the same shape as the `display.py` / `loader.py` / `undo.py` promotions before it. `gridcalc/search.py` now holds `find_matches` (case-insensitive substring over both a cell's source text *and* a formula's computed value, in reading order) and a pure `next_match` that reports where to go rather than moving a cursor, so a client-side selection can be driven from the same code as the TUI's `/` `n` `N`. `tui/search.py` keeps the curses-facing wrappers -- moving the grid cursor, rendering the `[3/12]` indicator -- and `tests/test_architecture.py` now pins the new module curses-free.

  On top of it, `Api.search` and a Ctrl-F find bar: incremental (it lands on the first hit as you type, as an editor's find does), Enter and Shift+Enter step forward and back with wrap, Escape closes and returns focus to the sheet. Searching engine-side is not an optimization but a requirement -- the client only ever holds the *formatted text* of the cells currently scrolled into view, so it cannot find `=SUM(A1:A9)` by its result, or anything at all off-screen. An empty pattern matches nothing rather than everything, since "find nothing" is the useful answer for an empty box. Long result lists are capped at 1000 and say so; `total` always reports the true count, so a capped list never reads as the whole story.

- **Row and column headers select their line.** Clicking a row number or column letter selects the whole line, shift-click extends the run, and dragging across headers sweeps it. This was the gesture the new Insert/Delete Row+Column items were built around and did not have: they act on the selection and label themselves with its span, so without it the only way to delete three rows was dragging across three rows of cells. The selection is an ordinary full-extent rectangle rather than a new "whole line" mode, so stats, clear, format, and the structural edits all understand it without changing. The cursor lands on the near end (A4 for row 4) with the anchor at the far end, matching a spreadsheet: the line is selected, but the *active* cell is the one you would start typing into.

- **The web frontend gets structural edits and sheet management.** The two largest remaining editing-parity gaps against the TUI, and the last permanently-disabled items in the menus. Four `Api` methods -- `insert_rows`, `insert_cols`, `delete_rows`, `delete_cols` -- wrap the ready engine primitives, scoped to the grid's selection so a three-row selection inserts three rows and deletes three; the menu labels count the span (`Delete 3 Rows`) so the item says what it will do. Deletes run bottom-up, as the TUI's `:delrow` does over a selection, since a top-down loop would see indices that had already shifted. Each batch is one `save_grid` snapshot and one recalc: insert and delete rewrite references across the whole sheet, so a rectangle snapshot would not be enough to undo them.

  Four more -- `add_sheet`, `delete_sheet`, `rename_sheet`, `move_sheet` -- expose the sheet operations behind a new Sheet menu, with a small dialog for the two that need a name. `rename_sheet` rewrites formula text referencing the old name and rebuilds the dependency graph before recalculating (graph keys carry sheet identity, so edges pointing at the old name would go stale), matching what `cmd_sheet` does in the TUI. All four return the new tab list alongside `ok`/`error` -- including on failure -- so one round trip both mutates and refreshes the tab strip, and a rejected operation still leaves the client able to redraw. Unlike the TUI's `:sheet add`, adding switches to the new sheet: the user reached for it through the tab strip, so landing on it is what the click meant.

- **Column widths persist with the workbook.** Dragging a column edge in the web view changed a `Map` in React state and nothing else, so the width was lost on save, on reload, and on every sheet switch (the grid remounts per sheet). Widths are now per-sheet workbook state: `Sheet.widths` maps a column index to a pixel width, serialized under an additive `widths` key in each sheet's JSON payload -- omitted when empty, so a workbook never touched by a graphical frontend serializes byte-for-byte as before, and older files load unchanged. Entries that are not in-range integers are dropped on load rather than trusted, since they come from a file the loader does not control.

  Pixels are deliberately *not* the same unit as `Grid.cw`, which is a uniform width in character cells: the curses renderer lays columns out by multiplying that one number (`GW + ci * g.cw`, plus overflow painting that assumes it) and has no notion of a per-column size, so it ignores the new field and `:width` keeps its existing meaning. Making per-column widths work in both frontends would mean rewriting the terminal renderer's column layout, which is a much larger change than the feature warrants. Column insert and delete shift the saved widths along with their columns, so a width stays on the column it was dragged on. The client writes on mouse release rather than per frame -- a drag is dozens of events and each is a round trip into Python.

- **The web frontend asks before discarding unsaved work.** Closing the window silently threw away every unsaved edit -- the dirty state was tracked and displayed, but nothing consulted it, while the TUI's `:q` has always refused on a dirty workbook. `Api._sync_close_guard` arms and disarms pywebview's own `confirm_close` flag as the workbook is edited and saved, and rewrites the window's `quitConfirmation` message so the prompt names the file. A clean workbook closes silently; a dirty one asks.

  The obvious-looking implementation deadlocks, and did: subscribing to the `closing` event and calling `create_confirmation_dialog` from the handler froze the application with no way out but a force quit. `closing` subscribers run synchronously on the UI thread (`Event(window, should_lock=True)`), and that method schedules its dialog *onto* the UI thread and then blocks waiting for it -- so the thread ends up waiting on work only it can run. Setting the flag hands the asking back to the toolkit, which does it on the right thread, and works across backends rather than only the one it was written against. Three regression tests pin it: one fails if the guard opens a dialog itself, one parses the module and fails on any attribute access to `closing` or `create_confirmation_dialog`, and one asserts `confirm_close` really is a settable attribute of a live `Window` -- mocking a window is exactly what let the broken version look correct.

- **A sheet-tab strip and an interactive `:sheets` picker.** A multi-sheet workbook previously advertised itself only through the status bar's `Sheet!A1` cell-reference prefix -- easy to miss, and it named just the active sheet. The bottom line (already reserved for transient messages, since the grid only ever draws rows `3..LINES-2`) now carries a tab strip whenever a workbook has more than one sheet: every sheet name in order, the active one reverse-highlighted against the blue chrome, and a right-aligned `i/n` position counter. The strip's mere presence is the "this is a multi-sheet workbook" signal -- a single-sheet workbook leaves that line clear, so its chrome is byte-for-byte unchanged. When the names overflow the terminal width the strip scrolls to keep the active tab visible. Drawn by `_draw_sheet_tabs` at the tail of `render.draw`; the existing status-bar prefix is retained, not replaced.

  `:sheets` (distinct from the existing `:sheet`) opens a full-screen picker positioned on the active sheet: `j`/`k` or the arrow keys move, `g`/`G` jump to first/last, Enter switches via `set_active`, and Esc/`q` cancels leaving the active sheet untouched. A single-sheet workbook has nothing to choose, so it just reports the lone sheet. The picker is backed by a new generic `select_from_list` helper in `tui/widgets.py` (a single-choice sibling of the existing `pager`), so later commands can reuse it. 4 new tests in `test_tui.py` (picker switch/cancel/single-sheet, and a `draw` assertion that the strip is absent for one sheet and shows both names plus `1/2` for two).

- **An experimental web-frontend spike (`gridcalc.web`).** Not the product -- the curses TUI remains the primary interface and gains no dependency. Behind the optional `web` extra, an editable grid runs the headless engine in-process on CPython and renders inside a **pywebview** window, calling Python directly through the `js_api` bridge (no server). All engine<->view logic is a plain-Python `Api` class, unit-tested without a display. This is the chosen GUI direction in `docs/gui.md`; an earlier read-only `imgui_bundle` spike was evaluated first and then removed with its `[gui]` extra, so only one direction is carried forward.

- **Optimization reaches the web frontend: `Solve` and `Goal`.** gridcalc's differentiator -- optimization with spreadsheet semantics -- is the first substantial feature the web spike carries beyond plain editing (`docs/web.md` argues this is the moat, not commodity cell editing). Four `Api` methods wrap the ready engine: `solve_selection` infers an LP/MIP from the current selection (`opt.infer_model`) and solves it; `solve_model` solves an explicit A1 model spec; `goal_seek` wraps `goalseek.seek`; and `opt_sweep` runs a what-if right-hand-side sweep. All translate at the bridge boundary -- A1 refs in and out, the engine's `(col, row)` keys stay internal -- turn `OptError`/`GoalSeekError` into `{ok: false, error}`, wrap applied solves in the shared `UndoManager` (dropping the guard snapshot when nothing was written, so a failed or non-optimal solve leaves no no-op undo step), and map non-finite ranging bounds to `null`, since JSON carries no infinity. A pure LP returns full sensitivity (shadow prices, reduced costs, objective and RHS ranging); a MIP returns none by design, because branch-and-bound duals describe a relaxation and would mislead.

  The client adds a `Solve` button with a max/min selector that opens a floating results panel -- status badge, objective, decision values, and the variable/constraint sensitivity tables, with INFEASIBLE/UNBOUNDED diagnostics naming the offending cells -- and a `Goal` button opening a goal-seek dialog prefilled with the active cell. Keystrokes in any toolbar or dialog field are now guarded (`_inField`), so typing a cell ref no longer leaks into grid navigation. 12 `Api` unit tests in `test_web.py` (a Wyndor LP end-to-end with write-back and sensitivity, infeasibility diagnostics with a clean undo stack, goal-seek solve/undo, a non-mutating sweep) and 6 headless-Chromium tests in `test_web_playwright.py` (the panel's objective and sensitivity render including a null bound shown as `inf`, the goal-seek dialog round-trip, and the field-guard regression).

- **Optimization depth in the web frontend: persisted models, and sensitivity painted onto the sheet.** The web view could solve, but each solve was a throwaway: the model existed only as text in a dialog, and its result only as a table. Both are now first-class. Five `Api` methods expose the workbook's model store (`grid.models`, the same objects the TUI's `:opt def/run/list/undef` uses, persisted under `models` in the JSON): `list_models`, `save_model`, `delete_model`, `run_model`, and `infer_model_spec`. The last is the deliberate non-solving one -- it reports what `solve_selection` *would* build from a block, so the client can prefill a model editor from the sheet's own layout and let the user see and correct the inference before anything is written. `solve_selection` now stores what it inferred as `default`, matching `:opt max` in the TUI, so a block only has to be selected once and is thereafter a re-runnable named object. Model specs are validated at save time but resolved at *run* time, so a model that outlives an edit to the cells it names still lists and reports a useful error when used, rather than being rejected while it was still valid or corrupting the listing.

  The client's Optimize dialog became a workspace: a saved-model dropdown, name/save/delete, `Read from selection` to infer without solving, the full spec fields (bounds, integers, binaries -- previously unreachable from the GUI at all), and an apply toggle for a dry run.

  **The differentiated half is the grid annotation layer.** A solve's result is now painted on the sheet: the objective cell, the decision cells, and -- the part that matters -- each constraint marked binding or slack, with the shadow price, its valid RHS range, and reduced costs in the hover text. The sensitivity tables say the same thing, but a shadow price means considerably more sitting on the constraint row it belongs to than in a column of cell references; which constraints bind, and therefore where the model is actually tight, becomes something read off the layout rather than reconstructed. This is the thing a terminal frontend cannot do, which is the argument `docs/web.md` made for leading with optimization rather than editing parity. Annotations are cleared the moment the grid is edited, because shadow prices describe the sheet as it was solved and leaving them painted after a change would be a lie.

  This also fixed a real gap in the shipped code: an applied solve or goal seek writes decision cells, but neither dialog told the app, so the grid kept rendering pre-solve values until something else happened to trigger a refetch. Both now report through a new `touched()` on the workbook hook, which marks the workbook dirty *and* bumps the revision the grid watches. `opt.cells_to_spec` was promoted from `tui/solve.py` down into `opt.py` (the same below-the-view-boundary move as `parse_cells`/`parse_bounds`, with `tui/solve.py` re-importing it under its old private name), since the web `Api` must not import `tui`. 11 new `Api` tests and 21 new client tests, including bundle tests that drive the built artifact in Chromium.

- **A grid command layer, so the web frontend's menus stop lying.** Six Edit menu items -- Cut, Copy, Paste, Delete, Fill Down, Fill Right -- shipped permanently disabled behind a "arrives in a later phase" tooltip, while all six had in fact worked from the keyboard since the grid landed. The cause was structural rather than cosmetic: `Grid` owned cursor, selection, clipboard and fill entirely in component-local state and exposed only `onSelectionChange` upward, so nothing outside the grid could act on the grid. `Grid` now publishes a `GridHandle` (`copy`/`cut`/`paste`/`clear`/`fillDown`/`fillRight`/`edit`/`goto`/`focus`) through a React 19 `ref` prop, and the menu drives those same commands -- a menu item and its shortcut can no longer drift apart. Cursor and selection deliberately stay inside the grid (they change on every mouse move; lifting them would re-render the whole shell), which is what makes an imperative handle the right seam rather than lifted state.

  Exposing the commands surfaced a latent ordering hazard: the `curRef`/`anchorRef` mirrors only caught up on re-render, so two commands issued in one tick (`goto('A4')` then `copy()`) had the second act on the stale cursor. Cursor moves now write through to the refs immediately, which is what "refs mirroring state so async handlers read current values" always claimed to mean. `Data > Sweep` is likewise no longer disabled -- `opt_sweep` had been fully wired through the bridge since the optimization work with no UI to reach it, and now opens a dialog that plots the objective against the swept right-hand side with breakpoints marked (the objective curve is piecewise linear and its slope is the shadow price, so the breakpoints are the interesting part). The only items still disabled are the structural edits (insert/delete row and column), which genuinely have no `Api` method; the tooltip now says so.

- **An error channel: failed bridge calls are reported instead of vanishing.** Every call into the pywebview bridge is a marshalled Python call that can reject, and the client awaited them bare -- a raising `set_cell` or `clear_range` became an unhandled rejection and the user was left looking at a silently stale grid. Both the grid and the workbook hook now route calls through a `guard` that turns a rejection into a user-visible message; the status line distinguishes errors from confirmations (and holds them longer), carries `role="status"` / `aria-live` so a failure is not a purely visual event, and a window-level `unhandledrejection` listener catches whatever still escapes. A React `ErrorBoundary` sits above the app, because a render crash inside a webview is otherwise invisible -- there is no devtools console the user will open. Failed opens and saves now report the engine's own error text rather than a generic "save failed".

- **Unsaved-change tracking, selection statistics, and an editable formula bar.** `Api` gained `_touch`, the single place every mutating method routes its result through: it marks the window title with a trailing `*`, keeps the engine's own `dirty` flag in step, and rides the state back to the client on the call that caused it, so no extra round trip is needed. A freshly loaded workbook is normalized to clean (the demo grid builds itself with `setcell` and so arrived pre-dirty), and an undo or redo against an empty history is explicitly a no-op that does *not* dirty the workbook. `Api.stats` aggregates a rectangle (count, numeric count, sum, avg, min, max) for the new status bar -- computed engine-side because the client only ever receives cells as formatted text, and only those currently scrolled into view. The formula bar and name box became real inputs: typing a reference in the name box jumps there, and the formula bar edits the active cell as an alternative to the in-cell editor, sharing one edit session (including formula point mode) so a formula can be written in whichever the user reaches for.

- **`set_global_format` is undoable.** Changing the workbook's default number format touches no cell, so `save_region` had nothing to snapshot and undo silently skipped a user-visible change. `UndoEntry` now carries the grid-level default format, recorded by every snapshot and restored on undo/redo, plus a new `UndoManager.save_global` for a change that is *only* grid-level state. The TUI inherits the same fix for `:gformat`.

### Changed

- **The web frontend's TypeScript/React layer joined the quality gate.** `make qa` was `lint typecheck test format` -- all Python -- while pytest's `addopts` excluded the `browser` marker, so the entire client could break without any gate noticing. That is exactly the failure mode `docs/web.md` §5c warned about for the old inline HTML string: the Vite build fixed the tooling but nothing had been wired into the gate. `make qa` now also runs `make web-qa` (`tsc --noEmit` plus the vitest suite), which skips cleanly rather than failing when Node is absent or the frontend has never been installed -- the web extra is optional and the curses TUI must stay buildable without it.

- **Cell display formatting extracted to a frontend-neutral `gridcalc/display.py`.** Groundwork for a future non-curses frontend, per the prerequisite in `docs/gui.md`: `fmtcell`, `cell_clip_value`, and the number-format helpers (`fmt_float` and friends) moved out of `tui/format.py` into a package-level `display.py` that imports only the engine. The functions were pure and curses-free already, but living under `tui/` meant importing them ran `tui/__init__.py`, which imports `curses` -- so no non-terminal view could reuse them. They now sit below the view boundary; a GUI (ImGui/Qt/web) can format cells without a terminal dependency. No behaviour change -- the code moved verbatim, the public `from gridcalc.tui import fmtcell` re-export still works, and internal callers (`render`, `undo`) now source it from `..display`.

  `tests/test_architecture.py` was extended to hold the new module to the same layering contract as the rest of the core: `display.py` is added to the static curses-free check (`CORE_MODULES`), to the "importing the core loads no curses" subprocess check (`CORE_IMPORTS`), and is required by the meta-test that every non-view module be classified -- so the guarantee can't silently regress. The solver-report formatters (`format_sensitivity`, `format_conflict`, `format_unbounded`, `format_sweep`, `sensitivity_block`) deliberately stayed in `tui/format.py`: they emit `list[str]` and status-bar strings shaped for the pager, which is TUI presentation a GUI would render differently. Undo and selection likewise stay put for now -- reusable in principle, but moving them is a larger separate step the prerequisite does not require.

- **Workbook loading and undo/redo promoted below the view boundary, alongside `display.py`.** The frontend-neutral extraction continued so the web frontend could reuse them rather than reimplement them. Workbook loading moved into a package-level `gridcalc/loader.py` (`load_workbook`, `demo_grid`), and the undo/redo history (`UndoManager`, `UndoEntry`, `UNDO_MAX`) moved out of `tui/undo.py` into `gridcalc/undo.py`. Both import only the engine (loader also `sandbox`), so a non-curses frontend can open files and offer undo without a terminal dependency. `load_workbook` reads `.json` (formulas-only -- a frontend never executes an embedded code block merely to open a file), `.xlsx`, and `.csv`, by extension. The curses TUI is unchanged: `tui/undo.py` now re-exports `UndoManager`/`UndoEntry`/`UNDO_MAX` from the new home so every existing `from .undo import UndoManager` / `from gridcalc.tui import UndoManager` importer keeps working, and the cell `Clipboard` (OS-clipboard interchange) deliberately stays in `tui/` because it is view-facing. `tests/test_architecture.py` holds both new modules to the same curses-free contract as the rest of the core (`CORE_MODULES`, `CORE_IMPORTS`, and the "every non-view module is classified" meta-test).

- **Cell-list / bounds spec parsing promoted from `tui/solve.py` into `opt.py`.** The prerequisite for the web optimization surface, following the same below-the-view-boundary pattern as `display.py` / `loader.py` / `undo.py`: `parse_cells` (`A1:B3` / `A1,A2,B5` -> `(col, row)` coordinates) and `parse_bounds` (`A1=lo:hi`) moved into `opt.py` so a frontend can name a model's cells without re-implementing the parsers or importing from `tui`. The curses TUI is unchanged -- `tui/solve.py` re-imports them under their old private names, and the `gridcalc.tui` re-exports now point at `opt` so the existing `from gridcalc.tui import _parse_cells` importers and tests keep working. `UndoManager` also gained `discard_last`, which drops the most recent snapshot when the mutation it guarded did not happen -- used by the web solve path so a raised or non-optimal solve leaves the undo history untouched.

## [0.3.0]

### Added

- **xlsx import now brings in defined names (named ranges), including cross-sheet ones.** A workbook's `<definedNames>` -- e.g. `SalesData = Data!$B$2:$B$4` -- previously vanished on import, so `=SUM(SalesData)` came back `#NAME?`. They now import as gridcalc named ranges and resolve. OpenXLSX exposes no public defined-names API, so the names are read straight from the xlsx zip's `xl/workbook.xml` in pure Python -- no C++ rebuild. Only simple single-area cell/range targets import; constants, formula-valued names, multi-area unions, and built-in `_xlnm.*` names are skipped.

  This required a real model change: `NamedRange` gained a `sheet` qualifier (it was sheet-agnostic, resolving against whichever sheet the referencing formula sat on), so an imported name like `Data!$B$2:$B$4` resolves to the *right* sheet even when used from another. The qualifier threads through `_build_named_ranges` (into the `CellRef`/`RangeRef` `sheet` field), the PYTHON-mode named-range injection, and JSON persistence -- a sheet-qualified name serialises as `Sheet!A1:B3` while a bare `A1:B3` stays sheet-agnostic, so old workbooks round-trip unchanged. Cross-sheet named ranges are now expressible generally, not just via import. `INDIRECT`-style dynamic names are not affected; this is static defined names only.

- **A reference value type, and the functions that need it: `OFFSET`, `FORMULATEXT`, `AREAS`, `LOOKUP`.** A formula value can now be a *location* (`Reference`) distinct from the value(s) it points at -- the last of the four architectural lifts the coverage audit called out (2D result type, lexical scope, cell spill, and this reference value type), leaving `INDIRECT`, external I/O, and cube/OLAP as the only deliberately-out-of-scope families. `OFFSET(reference, rows, cols, [height], [width])` returns a `Reference`; anywhere a plain value is expected — a normal function argument, an arithmetic operand, a formula's result — it materialises (`_deref`) to a scalar (1x1) or a `Vec`. `_deref` is a no-op for every value that is not a `Reference`, so formulas that never touch `OFFSET` are completely unaffected (all 1604 prior tests pass unchanged).

  This makes `OFFSET` compose the way Excel's does: `=SUM(OFFSET(A1,0,0,10,1))` sums a dynamically-sized range, `=OFFSET(A1,2,0)+1` reads a shifted cell, `=INDEX(OFFSET(...),3)` indexes it, `=OFFSET(A1,0,0,3,1)*2` even spills, and `=IFERROR(OFFSET(...),x)` catches an off-sheet `#REF!`. The reference-aware functions consume a `Reference` raw rather than a materialised value: `ROW`/`COLUMN`/`ROWS`/`COLUMNS`/`ISREF` were refactored onto a shared `Env.resolve_ref` (which resolves a cell ref, range ref, named range, or a nested reference-returning call), so `=ROWS(OFFSET(A1,0,0,5,1))` is 5. `FORMULATEXT(ref)` returns the referenced cell's formula text (tracked as a dependency, so it updates when that formula is edited); `AREAS(ref)` is 1 (union references are not expressible in this grammar). `OFFSET` is volatile — its read set depends on runtime offsets, so a change to any cell it reads recomputes it, matching Excel.

  `LOOKUP` (vector and array forms) is included in the same batch though it returns a value rather than a reference: it finds the largest entry `<= lookup_value` in an assumed-ascending vector and returns the aligned result. `INDIRECT` remains deliberately unimplemented — a string-built reference defeats the static dependency analysis the topological recalc depends on. 21 new tests in `TestReferenceFunctions`.

- **`FREQUENCY`.** `=FREQUENCY(data_array, bins_array)` returns a vertical array of counts of how many data values fall into each bin interval: element 0 counts values `<= bins[0]`, element *i* counts `bins[i-1] < x <= bins[i]`, and the final (bins + 1)th element counts values above the last bin. Non-numeric entries in either argument are ignored, an empty `bins_array` counts all data, and the counts sum to the data size. It was the last function blocked on the 2D-aware result type; with spill it lays its result column out down the sheet (`=SUM(D1#)` recovers the data size). Verified against Microsoft's documented example. 8 new tests in `TestFrequency`.

- **Dynamic-array cell spill (engine core).** A formula whose result is a multi-cell array now spills into neighbouring cells instead of being trapped in one cell: `=SEQUENCE(3)` in A1 fills A1:A3, `=SORT(A1:A3)` lays its result out where you can read each element, and 2D results (`=SEQUENCE(2,3)`) fill a rectangle. The anchor keeps the formula and the whole array; the extra values materialise as a new `SPILL` cell type owned by the anchor (`spill_parent`), and the anchor records its rectangle (`spill_shape`).

  **Read semantics follow Excel.** A bare `=A1` reads the anchor's top-left *scalar*; the whole array is reached with the new spill-range operator **`A1#`** (`=SUM(A1#)`). This is what lets a range that overlaps a spill — `=SUM(A1:A3)` — sum each cell once instead of double-counting the anchor's array against the materialised cells. `A1#` is a new lexer token (`#`, disambiguated from `#DIV/0!`-style error literals), a `SpillRef` AST node, and a dependency on the anchor so consumers recompute when the array changes. Confirmed safe by a survey of the suite: nothing cross-cell relied on the previous "reading an array cell yields the whole Vec" behaviour, and all 1556 prior tests pass unchanged.

  **`#SPILL!`** when the target rectangle is blocked by a foreign non-empty cell or would run off the sheet. Blocked anchors are tracked so that clearing whatever blocked them re-attempts the spill (a blocked anchor has no dependency on the cell blocking it, so any edit re-checks the — normally empty — blocked set). Typing into a spill cell turns it into a real cell and sends its anchor to `#SPILL!`, matching Excel.

  **Recalc is a bounded fixpoint.** Spill shape is only known after a formula evaluates, so a spill can create or destroy cells whose consumers were not in the current topological pass. `recalc` re-runs the pass over the changed spill positions until the topology stabilises (bounded like the PYTHON fixpoint engine); the common case — nothing spilled — is a single pass, so there is no regression. Spill cells carry a dependency edge to their anchor, so in steady state a consumer of a spilled cell is found and ordered normally. Structural edits (row/col insert/delete/swap) drop all spill cells up front and let the following recalc rebuild them, rather than shifting spill ownership in place.

  **Persistence** saves only the anchor formula; spill cells are rebuilt when the anchor recomputes on load. Value-only exports (CSV) include the spilled values as a flat grid; xlsx re-spills from the formula. 30 new tests in `test_spill.py`, plus lexer/parser coverage for `A1#`.

  **TUI.** A spilling anchor and the cells it painted share one subtle cyan tint (`CP_SPILL`), so a dynamic-array result reads as a single cohesive block; a blocked `#SPILL!` anchor renders red like any error. The anchor now shows its own top-left scalar rather than the `1[n]` array badge (the badge is retained for PYTHON mode, where arrays live in one cell and do not spill). The status bar names a spilled cell's origin (`(spill from A1)`) and explains a `#SPILL!` (`spill range blocked -- clear the target cells`). 5 new `MockStdscr` tests plus one real-curses PTY test.

- **`LAMBDA` and the lexical-scope higher-order functions (`MAP`, `REDUCE`, `SCAN`, `BYROW`, `BYCOL`, `MAKEARRAY`).** `LET` shipped in 0.2.0 but `LAMBDA` was deferred because it needs a first-class function value; that value now exists. `LAMBDA(param..., calculation)` evaluates to a `LambdaValue` -- a closure that snapshots the local scope stack where it was defined, so it closes over enclosing `LET` bindings. Calling it swaps that captured stack in for the body's evaluation and restores the caller's in a `finally`, which keeps lexical scoping and re-entrancy both correct; `refs_used` and the range cache stay on the shared `Env`, so a cell read inside a lambda body is a live dependency and edits to that cell recompute the consumer (a test asserts this).

  Three ways to reach a lambda, all supported: direct application `LAMBDA(x, x+1)(5)`, a `LET`-bound name used as a function `LET(inc, LAMBDA(x,x+1), inc(41))`, and as the higher-order argument to `MAP`/`REDUCE`/`SCAN`/`BYROW`/`BYCOL`/`MAKEARRAY`. Direct application required the one grammar change: a new `Apply` AST node and a postfix-call layer in the parser (`_postfix`), since a trailing `(...)` after any primary now applies the preceding expression rather than being a syntax error. `Apply` was threaded through every exhaustive AST walker -- dependency extraction (`deps._walk` and `has_dynamic_refs`) and, importantly, `engine._ast_has_pycall`, the HYBRID-mode security check: a `py.*` call hidden inside a directly-applied lambda body would otherwise have gone undetected.

  `LambdaValue` is a plain Python callable, so the six higher-order functions are ordinary builtins that just call it -- `MAP` element-wise across N equally-shaped arrays (preserving array1's shape, `#N/A` on a length mismatch), `REDUCE`/`SCAN` folding an accumulator (SCAN keeping the running series), `BYROW`/`BYCOL` passing each row/column as a 1D `Vec`, `MAKEARRAY` building a grid from 1-based `(row, col)` indices. `LET`/`LAMBDA` stay in the evaluator (their arguments are declarations, not eager values); the rest are registered in `BUILTINS`.

  Two limits, stated rather than hidden. **Recursion is not supported**: Excel recurses through a Name-Manager `LAMBDA` (a global name), but gridcalc's named ranges model only cell references, and more fundamentally `IF` here is an eager builtin that evaluates both branches, so a self-referential lambda cannot terminate. The evaluator resolves a syntactic named `LAMBDA` dynamically on each call -- so recursion would work the moment a lazy `IF` and Name-Manager lambdas exist -- but neither does today. **No spill**: a lambda that returns an array is held in one cell and consumed via `INDEX`/`SUM`, like the other dynamic-array functions. 23 new tests in `TestLambda`, 4 in `TestParseApply`.

- **Excel function coverage: complex numbers, numeral conversion, unit conversion, and the fringe/finance fill-ins (~68 new functions).** Three batches over `libs/xlsx.py`, taking the registered `BUILTINS` count from ~325 to 394 (~400 Excel-callable names counting engine aggregates). Every function was checked against Microsoft's published worked examples, and where an inverse or a round-trip exists it is asserted directly -- a stronger oracle than a single rounded reference value.

  - **Complex numbers (26).** `COMPLEX` plus the `IM*` family (`IMSUM`/`IMSUB`/`IMPRODUCT`/`IMDIV`/`IMPOWER`/`IMSQRT`/`IMEXP`/`IMLN`/`IMLOG2`/`IMLOG10`/`IMSIN`/`IMCOS`/`IMTAN`/`IMSINH`/`IMCOSH`/`IMSEC`/`IMCSC`/`IMCOT`/`IMSECH`/`IMCSCH`/`IMABS`/`IMARGUMENT`/`IMCONJUGATE`/`IMREAL`/`IMAGINARY`). Excel encodes a complex number as text (`"3+4i"`); the work is a parser/formatter around Python's `complex`/`cmath`. Results emit the `i` suffix (Excel's default); `j`-suffix propagation from inputs is not tracked. Number formatting matches Excel's integer-vs-decimal rule via `%.15g`.

  - **Numeral + engineering + date fill-ins (12).** `ROMAN` (classic form; concise forms 1-4 accepted but return classic), `ARABIC`, `BASE`, `DECIMAL`; `DELTA`, `GESTEP`; `NETWORKDAYS.INTL`, `WORKDAY.INTL` (weekend codes 1-7/11-17 and 7-char Mon-Sun masks, holiday lists); `FISHER`, `FISHERINV`, `TRIMMEAN`, `PEARSON` (alias of `CORREL`).

  - **Bond/Treasury finance (27).** The coupon schedule is generated backwards from maturity with end-of-month awareness, driving `COUPPCD`/`COUPNCD`/`COUPNUM`/`COUPDAYBS`/`COUPDAYS`/`COUPDAYSNC` and the coupon-period math in `PRICE`/`YIELD`/`DURATION`/`MDURATION`. `DURATION` computes its fractional-period offset from coupon day-counts (`DSC/E - 1`) rather than `YEARFRAC`, because this library's actual/actual `YEARFRAC` is an average-year-length approximation that diverges from Excel; the coupon-based form reproduces Excel's basis-1 example exactly. `YIELD`/`YIELDMAT` invert `PRICE`/`PRICEMAT` by bracketing bisection. `PRICE` switches to simple interest for the final stub period (`COUPNUM == 1`), matching Excel. Also `DISC`/`PRICEDISC`/`YIELDDISC`/`ACCRINT`/`ACCRINTM`/`RECEIVED`/`INTRATE`, the T-bills (`TBILLEQ`/`TBILLPRICE`/`TBILLYIELD`), and `DOLLARDE`/`DOLLARFR`/`RRI`/`PDURATION`/`ISPMT`. `ACCRINT`'s actual/actual quasi-coupon refinement is not modelled (exact for the 30/360 and actual/360-365 bases).

  - **`CONVERT` + last fringe stats (3).** `CONVERT` covers all thirteen Excel unit categories with SI decimal prefixes and binary prefixes for `bit`/`byte`; a prefix is tried only when the whole abbreviation is not itself a unit, so standalone units win their letter collisions (`min` = minute, `mi` = mile, `d` = day), and a prefix on a non-metric unit (`kft`) is refused with `#N/A` as Excel does. Temperature is handled separately for its offset conversions. `SKEW.P` (population skewness) and `F.TEST` (two-tailed variance test, reusing the existing F-distribution CDF). `Z.TEST.RT` from the coverage audit was **not** added -- it is not a real Excel function; `Z.TEST` is already right-tailed by default.

  The gap analysis in `docs/function_coverage.md` was also corrected: it listed the 2D-aware return types (`TRANSPOSE`/`LINEST`/`HSTACK`/...) as an unbuilt architectural blocker, but that lift had already landed on `Vec.cols`. The mechanical batches are now exhausted; what remains is architectural (cell spill, a reference value type, lexical scope). ~150 new tests across `TestComplexNumbers`, `TestNumeralConversion`, `TestBond*`, `TestConvert`, and others in `test_libs.py`.

- **Separable quadratic objectives, with no second solver.** Objectives may now contain squared decision variables (`=(A1-3)*(A1-3)`, `=A1^2+A2^2`, `=2*A1^2+3*A1`), covering least-squares fitting, quadratic cost curves, and target-tracking.

  lp_solve is LP/MIP only, and the obvious route -- vendoring a QP solver such as OSQP -- was **not** taken. It would add a second vendored C library with its own cross-platform wheel-build risk, and mixing OSQP's Apache-2.0 with lp_solve's LGPL in one distributed artefact is a licensing decision that belongs to the project owner rather than to an implementation choice. Instead the existing backend is reused: a convex function is the upper envelope of its tangents, so `x^2` becomes an auxiliary column `z` constrained by a fan of tangent lines `z >= 2*a*x - a^2`, and the model stays an LP. The tangent direction matters and is why the convexity check exists: only when the objective drives `z` *downward* (minimising with a positive coefficient, maximising with a negative one) does `z` settle onto the envelope. With the wrong sign the solver pushes `z` to its bound and returns a confident answer to a different problem, so that case is refused rather than approximated.

  Consequences, all reported rather than hidden. The answer is **approximate**, and the status bar states the bound (`(quadratic, within 0.0061)`); the bound is real, and a test asserts the error never exceeds it at 8, 64 and 512 segments. Accuracy is controlled by `quadratic_segments` (default 64) and improves with the square of the count. The **reported objective is the true value at the solved point**, not the relaxation's -- the point is feasible for the real problem, so its objective is achievable, whereas the relaxed value reads slightly better than reality.

  Refused with a message naming the cause: cross terms (`=A1*A2` -- separable only; covariance-style objectives need a real QP), maximising a convex objective or minimising a concave one, squared variables without finite bounds (tangents need a finite interval), and degree 3 or higher. Sensitivity and infeasibility diagnosis are withheld for quadratic models, since the duals belong to the approximating LP and its extra rows are not user constraints -- the same call made for MIPs.

  `NotQuadratic` subclasses `NotLinear` deliberately. Both walkers are the optimizer's sandbox boundary, accepting a closed whitelist of AST nodes so nothing reaching an evaluation path can be a security concern; callers written against that guarantee catch `NotLinear`, and widening the objective walker must not slip past those handlers. 16 new tests in `test_opt.py`.

- **`:opt max|min` over a visual selection infers the model from the block.** The spatial layout of a sheet already encodes the model; requiring it to be retyped as `vars A4:A5 st D4:D6` was asking the user to repeat themselves. Select the block with `v`, type `:opt max`, and the components are classified: a formula rooted in a comparison is a constraint, any other formula is the objective, a plain number is a decision variable, and labels and blanks are ignored.

  Blanks are deliberately not treated as decision variables even though `solve` accepts empty ones -- a selected rectangle is mostly whitespace, and silently promoting every gap to a variable would build a model the user never described. Exactly one non-comparison formula must be present; more than one reports the candidates by name rather than guessing. Cells come back in column-major order, matching how `_parse_cells` expands a typed range, so an inferred model and a typed one produce the same variable ordering.

  The inferred model is stored as `default` before running, like the inline form, so the block only has to be selected once and later `:opt` re-runs it. It is stored as *spec strings* (`"A2:A3"`, collapsing contiguous runs to range syntax) rather than coordinates, so it round-trips through the workbook JSON like any other saved model. Inference lives in `opt.infer_model`, so it is testable without curses. 10 new tests in `test_opt.py`, 9 in `test_tui.py`.

- **Sensitivity results can be written into cells: `:opt sens [<name>] into[!] <cell>`.** The paged report could be read but not used. Written into the grid, the numbers land as NUM cells, so `=G7*100` against a shadow price evaluates to 150 and the analysis becomes part of the sheet's own computation. Layout is fixed and documented, so formulas keep working when the block is refreshed in place.

  The write refuses to overwrite a non-empty cell and names the first one blocking it; `into!` forces, matching `:q!`. The report owns its whole bounding rectangle including the short separator row between the two tables -- checking and clearing only the populated positions would leave a stray value sitting inside the block, reading as report data. One undo step covers the whole write.

- **Parametric right-hand-side sweep via `:opt sweep <cell> <lo>:<hi> [steps] [name]`.** A shadow price answers "what is the next unit worth" and nothing more -- it is valid only inside its ranging interval, so it cannot answer the question users actually have, which is "how much more should I buy". The sweep re-solves across a range and shows where the marginal value changes:

  ```text
  D5 right-hand side from 6 to 24   (* = marginal value changed)
              rhs objective     delta    shadow  status
                6        27        --       2.5
     *          8        30         3       1.5
               18        45         3       1.5

     *         20        45         0         0
               24        45         0         0
  ```

  Read as: capacity is worth 1.5 per unit up to 18 and nothing beyond it.

  Built on a new public `solve(rhs_override={cell: value})`, which substitutes the constant of a constraint for one solve without touching the sheet. That is a useful primitive on its own for one-off what-if questions, and it is what keeps the sweep read-only: each point solves with `apply=False`, so a command that sounds like a question never silently moves the user's decision cells. Only the constant moves -- the constraint's coefficients still come from its formula.

  Points that fail are kept in the series with their status rather than dropped: discovering that a right-hand side is unattainable is a real answer. Breakpoints are flagged only where both the current and previous shadow prices are known, so a gap in the series reads as "not comparable" rather than "changed". `steps` counts intervals, giving `steps + 1` rows spanning the range inclusive.

  Model-spec resolution moved into a shared `_resolve_model` helper so `:opt run`, `:opt sens`, and `:opt sweep` cannot interpret the same saved model differently. 15 new tests in `test_opt.py`, 11 in `test_tui.py`, and a PTY test.

- **Unboundedness diagnosis: an unbounded `:opt` now names the runaway variable.** The mirror of the infeasibility work below, and the last of the three solver outcomes to report only a bare status:

  ```text
  opt: UNBOUNDED  unbounded: A5 -- add an upper bound or a constraint
  ```

  A variable is reported when the constraints allow it to move without limit in whichever direction improves the objective. That is established exactly, by re-solving over the same feasible region with a throwaway objective of just that variable and checking whether *that* problem is unbounded -- at most one solve per contributing variable, on the failure path only. Variables with a zero objective coefficient are skipped: moving them cannot change the objective, so they are not the cause even when they are themselves unbounded, and naming them would send the user to the wrong cell.

  lp_solve offers no help here: `is_unbounded(lp, col)` is the query counterpart to `set_unbounded` and reports whether a column was *declared* free, not which column carries the ray. There is no extreme-ray accessor.

  The first implementation was the textbook big-M approach -- bound the infinite directions with a large artificial box and look for variables pinned against it, at two box sizes to filter out legitimately large optima. It was **wrong**, and is recorded here because the failure mode is not obvious: the box has to be derived from the model's own magnitudes, so a variable whose genuine limit sits far above the largest number in the model (`1e-9*A1 <= 1`, capping A1 at 1e9 among coefficients of order 1) pins against the box and gets reported as a runaway when it is not. The two-scale check does not save it, because the box binds at both scales. Solving for the actual bound has no threshold to misjudge. Both behaviours are pinned by `test_unbounded_ignores_a_variable_capped_far_above_the_model_scale`.

  9 new tests in `test_opt.py`, 10 in `test_tui.py`, and a PTY test.

- **Infeasibility diagnosis: an infeasible `:opt` now names the contradictory constraints.** Previously the status bar said `opt: INFEASIBLE` and stopped, which tells the user their model is broken without giving them anywhere to look. It now reports an irreducible inconsistent subsystem:

  ```text
  opt: INFEASIBLE  conflict: D1, D2 (2 of 5 constraints)
  ```

  The reported set is minimal in both directions: it is still infeasible on its own, and dropping any single member restores feasibility. Both properties are asserted in tests, because "some infeasible subset" is easy and useless -- the value is entirely in the narrowing.

  Implemented as a deletion filter in `opt.py:_irreducible_conflict`: try removing each constraint in turn, and if what remains is still infeasible the constraint was not part of the conflict, so drop it permanently. Costs one solve per constraint, runs only on the failure path, and reuses the already-built matrices rather than re-parsing formulas. Because it tests subsets rather than pairs, a three-way conflict with no contradictory pair (`A1+A2 >= 10`, `A1 <= 2`, `A2 <= 2`) is reported correctly; a pairwise check would find nothing.

  Two subtleties worth recording. The subset test is specifically for `INFEASIBLE`, not for "not `OPTIMAL`" -- dropping a constraint can leave the problem `UNBOUNDED`, which means the feasible region is *non-empty*, so that constraint does belong to the conflict and the looser test would wrongly discard it. And variable bounds are held fixed rather than being candidates for deletion, so a constraint contradicting its variable's bounds is named as the conflict; the bounds are context the user did not type as a cell, the constraint is the thing they can point at. An empty conflict list would mean the bounds alone contradict, which is unreachable today because `lb > ub` is refused before any solve -- the branch is defensive and is documented as such rather than tested as a live path.

  Diagnosis is opt-in at the API (`solve(diagnose=True)`) and always on from the TUI, where the user is already stuck and the extra solves are free at spreadsheet scale. 9 new tests in `test_opt.py`, 8 in `test_tui.py`, and a PTY test that types a contradictory pair into empty cells and asserts the innocent constraints are excluded from the message.

- **Sensitivity analysis via `:opt sens [<name>]`.** The solver already computed dual values and discarded them at the boundary -- `Solution` in `_opt.cpp` carried only `status`, `objective`, and `x`. It now also carries shadow prices, reduced costs, and both ranging arrays, and `:opt sens` renders them as a report. This is the answer to the question a bare optimum cannot address: not "what is the best mix" but "what would change it, and what is a unit of each constraint actually worth".

  ```text
  Constraints   (* = binding)
     cell     shadow       rhs  activity     slack  rhs from  rhs till
     D4            0         4         2         2      -inf       inf
   * D5          1.5        12        12         0         6        18

   * D6            1        18        18         0        12        24
  ```

  Four layers. (1) `_opt.cpp` gained a `sensitivity` parameter, off by default: obtaining duals requires enabling `PRESOLVE_SENSDUALS` *before* the solve, which perturbs lp_solve's presolve, and callers that do not need sensitivity should neither pay for it nor risk the change. After a successful solve it reads `get_ptr_sensitivity_rhs` and `get_ptr_sensitivity_obj`. The `duals` array is one block of length `rows + columns` -- constraint duals first, then per-variable reduced costs -- which is not obvious from the header and was confirmed against lp_solve's own reporting code (`lp_report.c` `REPORT_lp`, which indexes it exactly that way) rather than from documentation.

  (2) `opt.py` assembles the raw arrays into `VarSensitivity` / `ConstraintSensitivity` records keyed by the *sheet cells the user typed*, so a caller can render the report without re-deriving the solver's column ordering. lp_solve's 1e30 infinity sentinel is converted to a real infinity at this boundary; leaking it would render as a meaningless `1e+30`. Bindingness is computed from slack (`|rhs - activity| <= 1e-9`) rather than from a non-zero shadow price, because a degenerate optimum can bind at a price of zero and calling that non-binding would be wrong.

  (3) `tui/format.py:format_sensitivity` renders the two tables as plain lines -- pure and curses-free, so the layout is directly testable. Every line stays under 78 characters: the pager truncates rather than wraps, and a silently clipped number is worse than a narrow column. The binding flag is a leading `*` rather than a trailing word for the same reason -- a trailing label is the first thing lost to truncation.

  (4) `tui/solve.py` dispatches `sens` alongside `run`. The solve still applies its result to the sheet, since the report describes the optimum that was just written; computing it without applying would describe a state the user cannot see. Undo behaves exactly as for `:opt run`.

  **Sensitivity is withheld for integer and binary models.** lp_solve will hand back numbers for a MIP, but a branch-and-bound dual is the dual of one LP relaxation, not of the integer problem -- there is no valid shadow-price reading. `SolveResult.sensitivity` stays `None` and the status line says why, which is better than a report that looks authoritative and is not. 11 new tests in `test_opt.py` (shadow prices checked against the analytically-known duals of the Wyndor Glass LP: 0, 3/2, 1), 11 in `test_tui.py`, and a PTY test driving the report through real curses.

- **Documentation-conformance tests (`tests/test_docs_conformance.py`).** Every `:` command and keybinding the README advertises must exist in the dispatch chain, and every command `cmdexec` accepts must be documented or declared an intentional alias in `UNDOCUMENTED_ALIASES`. This exists because the `u`/`Ctrl-R` bug below was a *documented* behaviour that was simply never implemented, and the curses layer is too thinly covered for a unit test to have caught it. Both chains are read statically via `ast` rather than executed -- dispatching them for real would quit, write files, and spawn `$EDITOR`. The extractors assert on the current `if`/`elif` structure and will need updating if either chain is refactored into a table.

- **Architectural fitness tests (`tests/test_architecture.py`).** The engine is a headless library and the TUI is a view over it; dependencies run one way. That held by habit, and nothing enforced it. Core modules are now checked for imports of `curses` or `gridcalc.tui`, an unclassified new module fails the suite, and a subprocess test asserts that importing the public core does not pull curses into `sys.modules` -- which catches the leak regardless of how it is spelled. `keys.py` is classified as a boundary module: parsing keyspecs is core work `config.py` needs, resolving them to keycodes needs a live curses runtime.

### Changed

- **Third-party licence texts now ship with the wheel.** gridcalc is MIT but statically links vendored lp_solve (LGPL-2.1) and OpenXLSX (BSD-3-Clause), so the binary contains their code. The wheel previously carried only gridcalc's own `LICENSE`, and the lp_solve tree had no licence text at all -- only `License terms: LGPL.` in per-file source headers. Added `thirdparty/lp_solve_5.5/LICENSE.LGPL-2.1.txt`, a `THIRD-PARTY-NOTICES.md` inventory, and extended `license-files` in `pyproject.toml` so all four travel in `dist-info/licenses/`. Verified against a built wheel rather than assumed.

  Also checked and cleared: `thirdparty/lp_solve_5.5/lp_rlp.c` carries a GPL notice, which looked alarming for an MIT project that compiles it into `lpsolve_static`. It is GNU Bison 2.3 output and carries Bison's **special exception** (added in Bison 2.2) permitting distribution of a larger work under terms of your choice. It imposes no GPL obligation on gridcalc. Recorded in `THIRD-PARTY-NOTICES.md` so the next person to notice it does not have to re-derive that.

  The static-linking question under LGPL section 6 is noted but not resolved -- it is a question for the project owner, and one that disappears entirely under the HiGHS migration now scoped in `TODO.md`.

- **The trust-prompt pager moved to `tui/widgets.py` as `pager(stdscr, title, lines)`.** It was general code with a hardcoded "Code block" header living in `commands.py`; `:opt sens` needed the same behaviour, and `commands` imports `solve`, so the dependency could not run that direction. `_view_code_block` is now a four-line call.

### Fixed

- **Trust prompt under-reported cell counts on every v2 workbook.** `sandbox.inspect_file` read cell data from the top-level `"cells"` key only. That key is the v1 layout; since the file format moved to v2 the cells live under `sheets[].cells` (`engine.py:2009`), so the prompt shown before loading an untrusted file reported `Cells: 0 (0 formulas)` for every multi-sheet workbook -- including ones carrying a code block. The code and `requires` detection were unaffected, so the prompt still flagged the actual threat, but a security prompt that displays visibly wrong numbers alongside correct ones erodes the user's reason to read any of it. Counting now walks each entry of `sheets` and falls back to the top-level key only when `sheets` is absent or empty, so v1 files still count correctly. The per-sheet accumulation moved into a `_count_cells` helper; malformed sheet entries (non-dict, or a `cells` value that isn't a list) are skipped rather than raised, matching how the loader itself tolerates partial corruption. Six new tests in `TestJsonInspect` covering v2, v2-with-code-and-requires, v2 styled cells, v1 fallback, an empty `sheets` list, and malformed entries.

- **Writing to an empty cell corrupted every empty cell in the process.** `cells[c][r]` returns a shared `_EMPTY_CELL` placeholder for coordinates that hold no cell, and `solve`'s write-back mutated whatever that expression returned. Decision cells are explicitly allowed to be empty, so `:opt` over a blank decision cell wrote through the singleton -- after which *every* empty cell, in that Grid and in every other Grid in the process, reported the written value. A brand-new `Grid()` came up with its empty cells already showing it. Silent, global, and reachable from documented-supported input.

  `solve` now goes through `Grid._ensure_cell`, which stores a real Cell in the sparse dict. To stop the class recurring, the placeholder is now a `_FrozenCell` whose `__setattr__` raises with a message naming the correct API: the failure is loud and immediate at the offending line instead of silent and global. It is built as a normal `Cell` and re-classed afterwards, so `Cell.__init__` can still populate the slots. Nothing in the existing suite tripped the freeze, which is precisely why the bug survived. 4 new tests in `test_engine.py`.

- **Infinity in a cell crashed the display.** `=1e308*10` overflows to infinity in every mode, and eight formatting sites used `v == int(v) and abs(v) < N`. Python evaluates `int(v)` before the magnitude guard can short-circuit, and `int(float('inf'))` raises OverflowError -- which propagated out of `draw()` and killed the session. NaN was guarded two lines away; infinity was missed. Rendering, clipboard copy, search, CSV export, the object editor, and JSON/xlsx save were all affected.

  Fixed by reordering the guard at every site so the magnitude test short-circuits first, plus an explicit infinity branch in `fmtcell` ahead of the format dispatch -- the `I` and `*` specs call `int()` unconditionally, so a guard inside the dispatch would not have covered them. Infinities now display as `inf` / `-inf`. Found while implementing the sensitivity-into-cells writer, which has to store unbounded ranging values. 13 new tests in `test_tui.py`.

- **A reversed or non-numeric `bounds` clause crashed the TUI.** `:opt ... bounds A1=20:10` tore the session down with an uncaught `ValueError` and lost the user's unsaved sheet. Three separate gaps lined up: `_parse_bound_value` ends in a bare `float(s)`, so `nan` parses happily; `solve` passed the bounds straight through to the `_opt` bridge, which rejects `lb > ub` with `ValueError("lb[j] > ub[j]")` -- naming a column index the user never typed, in an exception type this module's callers have no reason to expect; and `_execute_model` caught only `OptError`, so the `ValueError` escaped, killed curses, and left a dangling `save_grid` entry that made the next `u` a silent no-op.

  `solve` now validates bounds itself and raises `OptError` naming the cell and the offending values (`bounds for A1 are reversed: lower 20 exceeds upper 10`). Equal bounds (`lo == hi`, pinning a variable) and infinite bounds remain valid -- only `lo > hi` and NaN are refused. `_execute_model` additionally catches `ValueError` as defence in depth: the bridge enforces further invariants that way, and a TUI should report an unexpected error rather than destroy an unsaved sheet over it. 5 new tests in `test_opt.py`, 3 in `test_tui.py` (including one asserting the undo stack is left clean).

- **Importing `gridcalc.config` no longer requires curses.** `config.py` imports `keys.py` for keyspec parsing, and `keys.py` imported `curses` at module scope -- so `import gridcalc.config`, a core module with no terminal involvement, pulled the view layer's only hard dependency into every library consumer of the engine, including on platforms where curses is not available at all. Only `resolve_key` and `_scan_keyname` actually touch curses, and `keys.py`'s own docstring already stated that parsing is curses-free; the module-level import contradicted the design it documented. The import is now function-local in those two functions. Found by the new architecture tests on their first run, not by inspection.

- **`u` and `Ctrl-R` now actually undo and redo.** The README documented the vi bindings (`README.md:94`) but `mainloop` only bound `Ctrl-Z` / `Ctrl-Y`, and `u` fell through to the `32 <= ch < 127` printable-character branch -- so pressing `u` on the grid silently opened label entry with the letter `u` in the buffer. The grid keyloop now dispatches `u` for undo and `Ctrl-R` for redo, tested before the printable fallthrough (order matters here; placing the case after it is a no-op). `Ctrl-Z` / `Ctrl-Y` are retained as aliases, so no existing muscle memory breaks. The code was changed to match the documentation rather than the reverse: the app is vi-styled throughout, `Ctrl-Z` is conventionally SIGTSTP, and the PTY harness's `drain()` helper was written citing "`u` for undo" as its motivating use case (`tests/integration/conftest.py:104`) -- the test it was built for had never been written.

  **Behaviour change:** `u` is no longer available to begin a label. This matches `y`, `p`, `v`, `e`, `E`, `n`, and `N`, which are already consumed the same way; use the `"` label prefix to type a label starting with any of them.

  New `test_undo_redo_via_vi_keys` in the PTY suite, which is the only layer that can reach grid key dispatch (`tui/__init__.py` sits at ~15% line coverage). Verified to fail against the pre-fix binding with the bug visible in the render snapshot as `ENTRY  [PYTHON]\n> u_`.

### Infrastructure

- **A committed `.xlsx` import corpus in `tests/xlsx/`.** Ten small fixture files exercise the OpenXLSX-backed importer across the behaviours it actually has to get right: scalar types (`types.xlsx` -- ints/floats/negatives/scientific, and booleans which import as the text labels `TRUE`/`FALSE`), formulas re-evaluated by gridcalc (`formulas.xlsx`, including a divide-by-zero that must resolve to `#DIV/0!`), multi-sheet workbook order with a cross-sheet formula and a space in a sheet name (`multisheet.xlsx`), sparse layout with cells exactly on and one past the 256-column / 1024-row bound to prove out-of-range cells are dropped rather than crashing (`sparse.xlsx`), the text-vs-number interpretation where numeric-looking strings like `"007"` become numbers while `"123abc"` stays a label (`text_and_numbers.xlsx`), dates importing as their Excel serials (`dates.xlsx`), a unicode sheet name and content -- accents/CJK/Cyrillic/math symbols, no emoji (`unicode.xlsx`), an entirely empty workbook (`empty.xlsx`), defined names across sheets (`named_ranges.xlsx` -- cross-sheet/single-cell/same-sheet names, and a formula-valued name that must be skipped), and a table + embedded chart (`table_and_chart.xlsx` -- the import must not choke on the table/chart parts, the underlying cells load as plain data, a plain-range formula works, and a structured `SalesTable[Amount]` reference is pinned as unsupported).

  Unlike `test_xlsx_io.py`, which builds files with openpyxl in `tmp_path`, `test_xlsx_fixtures.py` loads pre-built files, so the reader is testable with no third-party dependency and the corpus doubles as a persistent regression baseline. `tests/xlsx/generate_fixtures.py` reproduces every file deterministically (no timestamps or random values in the content) and documents what each one holds. 43 tests.

## [0.2.0]

### Added

- **`LET` local bindings in EXCEL/HYBRID formulas.** `LET(name1, value1, [name2, value2, ...], calculation)` binds intermediate results to names, so a subexpression is written (and computed) once and reused: `=LET(x, SUM(A1:A9), x/COUNT(A1:A9))`. Implemented entirely in the AST evaluator (`formula/evaluator.py`), not the flat builtins dict, because the binding form breaks the two assumptions the normal dispatch rests on -- eager call-by-value and a flat, read-only namespace. `Env` grew a lexical scope stack (`push_scope`/`pop_scope`/`lookup_local`); `_eval_name` resolves locals before named ranges; and `_eval_let` binds each `(name, value)` pair into a pushed scope -- later pairs may reference earlier ones -- before evaluating the final calculation, popping the scope in a `finally` so the stack stays balanced even on error. Malformed arity (an even argument count) or a non-name binding target yields `#VALUE!`. No parser change was needed: `LET(x, 5, x+1)` already parsed to a `Call` with a `Name` binding target, and dependency extraction already ignores unknown names. `LAMBDA` remains unimplemented -- it needs a first-class function value type and call-on-expression in the grammar. 10 new tests in `TestLet`.

- **System clipboard integration.** Copy/paste now exchanges data with other programs, not just within gridcalc. New `tui/osclip.py` provides `SystemClipboard`, which shells out to the platform tool (pbcopy / pbpaste on macOS; wl-clipboard, xclip, or xsel on Linux; clip / `Get-Clipboard` on Windows) and degrades to a no-op when none is on `PATH`, so the TUI never crashes on a headless box. Yanking a region additionally pushes a TSV of display *values* to the OS clipboard (the interchange convention); pasting pulls in content copied from another program -- detected as OS-clipboard text differing from what gridcalc last pushed -- and writes it as values, while gridcalc's own copies still round-trip through the full-fidelity internal store with formulas and formatting intact. OS access is injected into `Clipboard`, so `Clipboard()` with no backend stays internal-only and nothing shells out under test. TSV encode/decode and the new `cell_clip_value` display helper (`tui/format.py`) are pure. 12 new tests (`TestTsvSerialization`, `TestSystemClipboard`). The non-macOS backends are written but unverified on real hardware.

- **2D-aware dynamic arrays (`SORT`, `UNIQUE`, `FILTER`).** These previously flattened a 2D range to a single list; `SORT` additionally raised `TypeError` on any mixed-type column. They now operate on whole rows (or columns) and preserve the result shape: `SORT` orders rows by the `sort_index` column (or columns by row when `by_col` is set) with an Excel type-ordered, blanks-last comparator; `UNIQUE` de-duplicates whole rows/columns; `FILTER` selects whole rows or columns depending on whether `include` matches the row or column count (`#VALUE!` when it matches neither). All carry the result `cols` so downstream `INDEX` and further composition stay correct. New `TestArrayFunctions2D`.

- **Excel-style label overflow.** A LABEL cell whose text exceeds the column width now visually spills into adjacent empty cells to the right, matching the long-established spreadsheet convention. Implemented as a second rendering pass (`_paint_label_overflow` in `tui.py`) that runs after each row's standard per-cell render and overpaints only the overflow portion -- chars from offset `cw` onward -- into the empty neighbors. The two-pass split keeps the main loop's cursor / selection / mark / lock / style handling unchanged.

  Spillover stops on the first neighbor that holds content (NUM, LABEL, FORMULA) or carries cursor / selection / mark state, so those cells keep their own visual state. The leading `"` label-prefix is stripped before measuring length, so labels typed as `"foo` are sized by their visible content. Off-by-default would not match user expectations on first launch -- the feature is always-on; cells that fit their own column are unaffected.

- **Goal-seek via `:goal`.** One-dimensional root-find that adjusts a variable cell to make a formula cell evaluate to a target value -- the spreadsheet what-if pattern most often used in practice ("what input makes this output equal X?"). Invocation:

  ```text
  :goal <formula_cell> = <target> by <var_cell> [in <lo>:<hi>]
  ```

  The variable cell must hold a value (not a formula, mirroring the decision-cell rule in `:opt`). When the `in <lo>:<hi>` clause is omitted, `goalseek._auto_bracket` walks geometrically outward from the variable's current value until f changes sign. The search uses plain bisection (`src/gridcalc/goalseek.py`); Brent's method would converge faster but adds edge cases that aren't justified at spreadsheet scale where each iteration is a full `Grid.recalc()` and 30-ish iterations run in milliseconds.

  On success the variable cell holds the solved value and the rest of the sheet recalculates to reflect it; the pre-search snapshot lives on the undo stack so `u` rolls back. Failure paths (non-convergence, no sign change in the bracket, variable doesn't influence target, bad cell selection) restore the variable cell to its original value and pop the undo entry. Unlike `:opt`, goal-seek isn't persisted in the workbook -- it's a one-shot operation whose entire state is the three short args, so retyping is faster than naming. Reference: `examples/example_goal.json` (a 2-cell `=2*A1+3` demo with three try-these one-liners on the sheet).

- **Linear and mixed-integer programming via `:opt`.** New sheet-level optimizer that builds an LP (or MIP) from cells in the active sheet and solves it via a vendored lp_solve 5.5. The user-facing model is sheet-resident: one objective cell containing a linear formula, a list of decision variable cells holding numeric values, and a list of constraint cells containing comparison formulas (e.g. `=A1+A2<=10`). The constraint cells also evaluate normally during recalc, so the sheet shows live feasibility (`TRUE`/`FALSE`) before and after the solve. Models are **workbook-persistent**: the spec the user types is stored in the JSON file under `"models": {<name>: {...}}` and re-runnable across sessions without retyping. The `:opt` dispatcher has six forms:

  ```text
  :opt                                       # run the saved 'default' model
  :opt max|min <cell> vars <cells> st <cells> [bounds <spec>] [int <cells>] [bin <cells>]
                                             # solve inline AND save as 'default'
  :opt def <name> max|min <cell> ...         # save under <name>; does NOT execute
  :opt run [<name>]                          # execute saved model (default: 'default')
  :opt list                                  # show saved model names
  :opt undef <name>                          # remove a saved model
  ```

  The optional `int` and `bin` clauses flag decision variables as integer-valued or binary (0/1) respectively, routing the solve through lp_solve's branch-and-bound. `bin` clamps bounds to `[0, 1]` regardless of the `bounds` clause; a variable in both `int` and `bin` is rejected as a programming error. Clauses can appear in any order after `st`.

  Cell lists accept ranges (`A1:A5`) or comma-separated refs (`A1,A3,B5`); bounds are `A1=lo:hi,B2=lo:hi` with `inf`/`-inf` accepted for unbounded sides. On `OPTIMAL`/`SUBOPTIMAL`, the decision cells are overwritten with the optimal values, `Grid.recalc()` propagates through the rest of the sheet, and the status bar shows `opt: OPTIMAL  obj=<value>`. The pre-solve grid snapshot is recorded via `UndoManager.save_grid` so `u` rolls the optimization back; failure paths (infeasible, unbounded, malformed command) pop the undo entry so it isn't a no-op surprise.

  Saved models live on `Grid.models: dict[str, OptModel]`, parallel to `Grid.names` for named ranges. `OptModel` (in `src/gridcalc/opt.py`) stores the *spec strings* the user typed (`"A4:A5"`, `"D4:D6"`, `"A1=-inf:10"`) rather than pre-resolved cell coordinates, so range and list syntax round-trip through save/load verbatim and parse errors surface at `:opt run` time, not silently at load. Malformed `models` entries in a loaded JSON file are skipped (not raised) so one bad entry can't block opening the rest of the workbook.

  The optimizer is built from four layers. (1) Vendored lp_solve 5.5 in `thirdparty/lp_solve_5.5/` with a hand-written `CMakeLists.txt` that mirrors the canonical source list from `lpsolve55/ccc`, picks the LUSOL inverse engine (`INVERSE_ACTIVE=INVERSE_LUSOL`), and suppresses lp_solve's own warnings (`-w`) so they don't drown the project's. The static archive `lpsolve_static` is `EXCLUDE_FROM_ALL` and only pulled into the wheel via `_opt`. (2) A minimal nanobind bridge `src/gridcalc/_opt.cpp` exposing one entry point `solve_lp(c, A, sense, rhs, lb, ub, maximize=False, integer_vars=[], binary_vars=[]) -> Solution` with dense matrices, plus the `LE`/`GE`/`EQ` and status constants (`OPTIMAL`, `INFEASIBLE`, `UNBOUNDED`, etc.). `set_int` and `set_binary` are applied after the bounds dispatch (binary clamps bounds to [0,1] so order matters); the bridge rejects a column appearing in both sets. Variable bounds dispatch on infinity-ness to four lp_solve calls (`set_bounds` / `set_lowbo` / `set_upbo` / `set_unbounded`) because `set_bounds(lp, j, -1e30, 1e30)` stores literal-1e30 finite bounds rather than treating them as ±inf, which produces feasible-but-huge optima on otherwise unbounded problems. A post-solve guard normalizes lp_solve's degenerate-presolve case (a free variable unreferenced in any constraint reported as `OPTIMAL` with the objective pinned at 1e30) to `UNBOUNDED`. (3) `src/gridcalc/opt.py` is the Python orchestrator. Its core is a linearity walker over gridcalc's formula AST: cell references that resolve to decision variables become coefficients, every other cell is folded into the constant term using its currently evaluated value, and the whitelisted node set (`Number`, `CellRef`, `BinOp` with `+ - * /`,
  `UnaryOp`, `Percent`, `Call("SUM", RangeRef|expr)`) rejects
  everything else with `NotLinear`. The walker is the safety boundary for the optimizer -- nodes that could be a sandbox concern (`Name`, `PyCall`, arbitrary `Call`, ranges outside SUM) never reach any eval path. Constraint extraction splits a comparison-rooted formula into LHS/RHS linear forms and rebalances them into `(coeffs, sense, rhs)`; `<>` is rejected explicitly. Cross-sheet references (`Sheet2!A1`) are rejected up-front via `_check_sheet` rather than silently treated as referring to the active sheet, which would produce wrong coefficients. `solve()` orchestrates the whole pipeline, refusing formula cells as decision variables so the operator never silently destroys live computation, and adding back the objective formula's constant term to the reported objective value. The walker parses cell formulas on-demand when `cell.ast` is `None` (which is the default in LEGACY mode, where the engine evaluates via Python `eval` of transformed text rather than through the AST). (4) The TUI integration in `cmd_opt` is a small dispatcher on subcommands (`def`/`run`/`list`/`undef`/inline); shared parsing lives in `_parse_opt_inline` and shared execution in `_execute_model` so the inline-and-store path and the def/run paths cannot drift apart. The inline form (`:opt max ...`) always stores the model under `default` before running, so the very first invocation captures the LP in the workbook -- a `:w` after that persists it and bare `:opt` re-runs it on reopen. Reference: `examples/example_lp.json` (ships with three pre-saved models -- `default`, `with_caps`, `integer_mip` -- so `:open ... :opt` works out of the box and `:opt run integer_mip` demonstrates an integer solution differing from the continuous relaxation).

- **Headless PTY harness for the curses TUI.** New `tests/integration/` directory with a `TuiSession` fixture that spawns the real `gridcalc` binary attached to a `pty.openpty()` pair, drives it via keystroke bytes written to the master fd, and asserts on ANSI-stripped rendered output. This is the only test layer that exercises curses end-to-end -- input handling, rendering, redraw -- which `MockStdscr`-based unit tests cannot reach. The harness is gated behind a `tty` pytest marker and excluded from the default `make test` run via `addopts = "-m 'not tty'"` in `pyproject.toml`; it is invoked explicitly via the new `make test-tty` target. Auto-skips on platforms without `pty` (Windows) and when the built entry point is missing. Smoke tests currently cover the `:opt` command's OPTIMAL path against `example_lp.json`, bare `:opt` re-running a workbook-saved `default` model, the malformed-command and bad-constraint-cell error paths, and the `:goal` command's full flow against `example_goal.json`.

- **User-configurable keybindings.** All five TUI contexts (`grid`, `entry`, `visual`, `cmdline`, `search`) dispatch through a config-driven keymap before falling back to hardcoded defaults. Bindings live in `gridcalc.toml` under `[keys.<context>]`:

  ```toml
  [keys.grid]
  next_sheet = ["Tab", "F4"]
  prev_sheet = ["S-Tab", "F3"]
  cursor_left  = ["Left", "h"]
  cursor_down  = ["Down", "j"]
  cursor_up    = ["Up", "k"]
  cursor_right = ["Right", "l"]
  ```

  No defaults are shipped -- every binding is opt-in, so the hardcoded fallback chain (arrow keys, `Tab`-as-cursor-right, etc.) is unaffected for users who don't write a `[keys]` block. New module `src/gridcalc/keys.py` parses an emacs-short grammar (`Tab`, `S-Tab`, `C-x`, `C-Right`, `F3`, literal chars) and rejects combinations with no portable terminal encoding (`C-Tab`, `M-<anything>`, `C-<punctuation>`, `S-<anything-but-Tab>`) at config load with structured warnings on stderr; resolution to a curses keycode is deferred to `mainloop` entry so terminfo-derived caps like `kRIT5` (`C-Right`) can fail soft on terminals that don't define them. Action vocabulary is curated per context (~25 actions total) and frozen at module load time. `[keys.entry]`, `[keys.cmdline]`, and `[keys.search]` are text-input contexts: printable bytes (`32 <= ch < 127`) bypass the dispatcher and self-insert into the buffer regardless of any binding -- so a stray `[keys.entry] cancel = ["a"]` cannot lock the user out of typing the letter `a`. `Config.keys: dict[str, dict[str, list[ParsedKey]]]` carries the parsed (but unresolved) bindings; `keys.build_resolved_keymap` does the curses-bound resolution and conflict detection. Reference: `docs/keybindings.md`.

- **`Grid.next_sheet()` / `Grid.prev_sheet()`.** Engine helpers that advance / retreat the active sheet with wrap-around at the ends and a no-op on a single-sheet workbook. Used by the `next_sheet` / `prev_sheet` actions in the new keybindings system, but standalone-callable as well.

- **xlsx export now preserves formula text alongside cached values in EXCEL mode.** `Grid.xlsxsave` (engine.py) now emits formula cells with both the formula string and a cached numeric value rather than only the evaluated number. The native writer (`src/gridcalc/_core.cpp`) gained a `kind == "f"` payload that calls `cell.formula() = ...` and (optionally) sets the cached value; the leading `=` is stripped before handing the string to OpenXLSX. Only `Mode.EXCEL` opts in -- gridcalc's LEGACY/HYBRID formula syntax is not guaranteed to be valid Excel, so emitting formula text in those modes risks producing files Excel can't evaluate. The reader path was already capable of preserving formulas; this closes the export-side gap. New `examples/example_multisheet.xlsx` fixture and `test_example_multisheet_xlsx_roundtrip_preserves_formulas` verify a real `.xlsx` file round-trips with formulas intact and a cached value that openpyxl returns under `data_only=True`.

- **Multi-sheet workbook support.** `Grid` now models a workbook of named sheets rather than a single flat cell store. Formulas can reference cells on other sheets (`=Sheet2!A1`, `=SUM(Sheet2!A1:A10)`); the dep graph tracks subscribers across sheets so cross-sheet recalc works. JSON and xlsx I/O round-trip every sheet. Five-phase rollout, all shipped:

  - **Phase 1 — `Sheet` class.** New `Sheet` (`engine.py`) owns `_cells`, `_circular`, and the cursor (`cc`, `cr`). `Grid` gains `sheets: list[Sheet]`, `active: int`, and an `_active` shortcut. `Grid._cells` / `Grid.cells` / `Grid.cc` / `Grid.cr` / `Grid._circular` are now properties that delegate to the active sheet, so all existing single-sheet code keeps working unchanged. Sheet-management API: `add_sheet`, `remove_sheet`, `rename_sheet`, `set_active`, `sheet_names()`. Six obsolete `self.cells = _CellsProxy(self._cells)` rebinds in insert/delete/replicate paths removed (now redundant -- `cells` is a property returning a fresh proxy on each access). 14 new tests in `TestSheetClass`.

  - **Phase 2a — sheet-qualified reference syntax.** Lexer adds `BANG = "!"` token; cellref-shaped tokens followed by `!` now defer to `IDENT` (so `Sheet1!A1` lexes as `IDENT BANG CELLREF`).
    AST: `CellRef.sheet: str | None` (frozen-dataclass default
    `None`; equality/hashing preserved). Parser handles
    `IDENT BANG CELLREF` → sheeted `CellRef`, and
    `IDENT BANG CELLREF COLON [IDENT BANG] CELLREF` → sheeted
    `RangeRef`. Cross-sheet ranges (`Sheet1!A1:Sheet2!B5`) are
    rejected at parse time with `ParseError("cross-sheet ranges are
    not supported")` -- matches Excel.

  - **Phase 2b — cross-sheet evaluation and recalc.** `Env.get_cell` grows a `sheet` parameter; the engine callback `_cell_lookup_value(c, r, sheet=None)` dispatches via a new `_sheet_cells(sheet)` helper (active sheet when `sheet is None`, looked-up sheet otherwise; unknown sheet returns an empty store so unsheeted-cell semantics apply). `_eval_range` cache key becomes `(sheet, c1, r1, c2, r2)`. The dep graph (`_dep_of`/`_subscribers`/`_volatile`) is now workbook-wide with 3-tuple `(sheet, c, r)` keys; `extract_refs` takes `formula_sheet` and emits fully qualified refs (unsheeted refs inherit the formula's home sheet). `_rebuild_dep_graph`, `_refresh_deps`, `_clear_deps`, `_register_deps`, and `_recalc_topo` updated accordingly. `_recalc_topo` swaps `self.active` per formula during evaluation (then restores) so unsheeted refs in formulas on Sheet2 resolve against Sheet2. Cross-sheet subscriber edges now recalc the dependent formula when the source cell on another sheet changes. 6 new tests in `TestCrossSheet` end-to-end (read, recalc on source change, cross-sheet `SUM` over a range, sheet-keyed subscribers proving same-coord cells on different sheets don't collide).

  - **Phase 3 — TUI sheet UX.** Status bar now shows `<sheet>!<cell>` whenever the workbook has more than one sheet (single-sheet workbooks keep the original ` A1 ` chrome unchanged). New `:sheet` command suite handled in `cmdexec` (`tui.py`):

    - `:sheet` / `:sheet list` -- print all sheets, active marked `*`.

    - `:sheet add NAME` -- append a new sheet (does not switch).

    - `:sheet del NAME` -- remove sheet (refuses the last one).

    - `:sheet rename OLD NEW` -- rename, then rebuild the dep graph (since dep keys carry sheet names).

    - `:sheet NAME` / `:sheet N` -- switch active sheet by name or zero-based index. Known limitation: `:sheet rename` does not yet rewrite formula text that references the old name; that's tracked as a phase 4 follow-up. Keybindings (e.g. PgUp/PgDn for sheet cycling) are deferred until a broader keymap-customisation story exists. 9 new tests in `TestCmdSheet`.

  - **Phase 4 — JSON v2 format.** `FILE_VERSION` bumped to 2. `jsonsave` now writes a per-sheet payload:

    ```json
    {
      "version": 2,
      "mode": "EXCEL",
      "active": "Sheet1",
      "sheets": [
        {"name": "Sheet1", "cells": [...]},
        {"name": "Other",  "cells": [...]}
      ],
      "names": {...}, "code": "...", "libs": [...], "requires": [...]
    }
    ```

    `jsonload` accepts both: a v1 file (no `sheets` key, top-level
    `cells`) loads into the auto-created Sheet1; a v2 file replaces
    the auto-created sheet with the saved set, restores the
    `active` sheet by name (defaults to first sheet when missing or
    unknown). Cell encoding/decoding extracted to
    `_encode_sheet_rows` / `_load_cells_into_active` helpers shared
    by both paths. Cross-sheet recalc survives a save/load cycle.
    5 new tests in `TestJsonV2MultiSheet`.

  - **`:sheet rename` now rewrites formula text.** Phase 3 left formulas referencing the old name returning empty; phase 4 adds `_rewrite_sheet_prefix` (engine.py) and wires it into `Grid.rename_sheet`. The rewriter walks every formula on every sheet, replaces `<old>!` prefixes with `<new>!`, and invalidates the cached AST so the next recalc re-parses. Skips matches inside double-quoted string literals (gridcalc's only string syntax) and requires a non-identifier boundary on the left so `=MyOther!A1` is unaffected when renaming `Other`. 5 new tests in `TestRewriteSheetPrefix`.

  - **Phase 5 — xlsx multi-sheet I/O.** `_core.xlsx_read` (C++/OpenXLSX) now iterates every sheet and returns `list[(sheet_name, col, row, text)]` in workbook order; `_core.xlsx_write` accepts `list[(sheet_name, col, row, kind, value)]` and creates worksheets lazily by renaming the default sheet on first use and `addWorksheet`-ing thereafter. Python wrappers `_xlsx_read_cells` / `_xlsx_write_cells` and `Grid.xlsxload` / `Grid.xlsxsave` updated to per-sheet payloads: load groups by sheet preserving workbook order (first xlsx sheet becomes active and replaces the auto-created `Sheet1`); save iterates `g.sheets` and emits each cell with its sheet name. ``.pyi`` stub updated. xlsx still stores evaluated values rather than formulas (formula round-trip is a separate TODO item), but cross-sheet formula *values* survive a save/load cycle. 3 new tests in ``tests/test_xlsx_io.py``: multi-sheet load preserves sheet names + per-sheet cells; multi-sheet save writes every sheet; cross-sheet formula round-trip preserves the evaluated value.

  Multi-sheet rollout complete. Single-sheet workbooks behave identically (1031 tests pass with no behavioural regressions). Remaining xlsx-compat work (formula round-trip, dates, styles) is tracked separately.

  - **`:sheet move NAME N`** reorders a sheet to a zero-based position (`Grid.move_sheet`). Active-sheet identity is preserved -- if the moved sheet is active it follows; if some other sheet is active, its index is recomputed so the same sheet stays active. Dep graph keys carry sheet *names*, so reordering does not invalidate the graph -- no rebuild needed. 7 new engine tests in ``TestSheetClass`` plus 3 TUI tests in ``TestCmdSheet``.

  - **Multi-sheet example**: ``examples/example_multisheet.json`` is a 3-sheet EXCEL-mode budget model (`Inputs`, `Metrics`, `Summary`) that demonstrates cross-sheet formulas (`=Inputs!B2-Inputs!C2`), cross-sheet aggregates (`=SUM(Inputs!B2:B5)`), and `INDEX`/`MATCH` on Metrics columns to pick the best/worst quarter. Loaded by `TestExampleMultiSheet::test_loads_and_computes` as a smoke test for the multi-sheet load path.

- **Typed per-cell errors with `Cell.err` and `Cell.err_msg`.** New
  `Cell.err: ExcelError | None` and `Cell.err_msg: str | None` slots
  capture the Excel error code and a human-readable message for any failed formula. `_store_formula_result` records `ExcelError` returns from EXCEL/HYBRID; `_recalc_legacy` maps validation failures to `#NAME?` (with the validator's reason in `err_msg`) and `eval` exceptions to `#VALUE!` (with `TypeName: msg` in `err_msg`). An `ExcelError` returned through LEGACY's `eval()` (e.g. from a `VLOOKUP` returning `#N/A`) is now stored verbatim instead of being flattened to NaN. Errors propagate through `Cell.copy_from` / `snapshot()` so undo/redo preserves them. TUI rendering: `fmtcell` shows the error code (e.g. `#VALUE!`) right-aligned in the cell, and the status bar appends the `err_msg` when the cursor is on an error cell. New `ExcelError.CIRC = "#CIRC!"` distinguishes structural cycles from generic `#VALUE!`; all three cycle-flagging sites (`_recalc_legacy`, EXCEL/HYBRID fixed-point, `_recalc_topo` unresolved-closure path) now set `cl.err = ExcelError.CIRC`. 10 new tests across `TestCodeBlockError`, `TestCellError`, `TestCircularError`.

- **Code-block exec failures surfaced via `Grid.code_error`.** New
  `Grid.code_error: str | None` captures the exception type and
  message when a user code block fails to load. Previously `contextlib.suppress(Exception)` silently dropped exec failures in both `_recalc_legacy` (engine.py:948) and `_build_py_registry` (engine.py:1109, HYBRID's `py.*` gateway), leaving the user with NaN cells and no diagnostic. Both sites now `try`/`except`, store the message, and clear it on success / no-code. The TUI status bar appends `[CODE ERR: <msg>]` whenever `g.code_error` is set, so the failure is visible until the user fixes the block. `contextlib` import dropped (no remaining uses).

- **Persistent "SANDBOX OFF" banner in the status row.** When the sandbox is disabled (`GRIDCALC_SANDBOX=0` or `sandbox = false` in config), the top status row renders a red-on-default reverse-bold `SANDBOX OFF` indicator right-aligned over the existing chrome. The user has continuous on-screen evidence that loaded code is running unrestricted; previously there was no indication after the trust prompt closed.

- **Trust-prompt code-block pager.** The `v` viewer in the trust prompt previously truncated to `curses.LINES - 2` with no scrolling, so any block longer than ~50 lines authorised invisible code at the tail. New `_view_code_block` helper paginates with j/k (line), space/b (page), g/G (top/bottom), q (back); footer shows `lines N-M/total` and the keymap.

- **Atomic two-phase undo/redo apply.** `UndoManager._apply` now builds the rollback snapshot in phase 1 (read-only — no stack mutation if it raises), then commits the restore in phase 2 inside a try/except that rolls back from the snapshot on failure and leaves the source entry on the stack so the user can retry. The prior implementation pushed the reverse entry to `to_stack` *before* the mutation loop, so a mid-restore failure could drift both stack and grid. New `test_undo_atomic_on_apply_failure` injects a failing `Cell.copy_from` and verifies stacks/grid stay consistent.

- **Config loader diagnostics.** `Config.warnings: list[str]` collects: TOML parse errors (previously swallowed), unknown top-level keys (typo guard), out-of-range numeric values, and wrong-type entries. New `emit_warnings(cfg)` prints each as `gridcalc: config warning: <msg>` to stderr; called once from `tui.main` after `load_config`. 5 new tests covering parse-error capture, unknown-key warnings, width out-of-range, format validation, and the no-warning happy path.

- **`requires` field accepts version specifiers.** `load_modules` now parses each spec as `name`, `name==1.2.3`, `name>=1.0`, `name<=`, `name>`, `name<`, or `name~=`. Version is checked against `importlib.metadata.version(name)`; mismatches surface as `'name': installed X does not satisfy >=Y` errors. Bare names keep prior behavior. Stdlib modules with no distribution metadata report `metadata not found` when pinned. New `_parse_requirement`, `_version_tuple`, `_check_version` helpers in `sandbox.py`; sites that classified raw `requires` strings (`FileInfo` blocked / side-effect lists) now strip the spec first. 8 new tests across `TestLoadModules` and `TestParseRequirement`.

- **CLI accepts `.xlsx` files directly.** `gridcalc model.xlsx` dispatches to `Grid.xlsxload` (the OpenXLSX-backed C++ path) instead of `jsonload`. Detection is by extension match. Sandbox trust prompt is skipped for xlsx (no code-block surface). Help
  string updated to ``Usage: gridcalc <sheet.json | sheet.xlsx>``.

- **Per-recalc range materialisation cache.** `Env._range_cache` (evaluator.py) memoises the materialised `Vec` for each ``(c1, r1, c2, r2)`` range encountered during a single recalc pass. `_eval_range` checks the cache before walking cells; subsequent references to the same range reuse the result. Topological recalc evaluates in dep order so source cells finalise before any consumer reads them — cache liveness is bounded by the closure pass and remains sound. The legacy fixed-point `_recalc_formula` clears the cache between iterations because values can change across passes. Hit rate on range-heavy sheets is ~10×; on a 25K-cell range-heavy benchmark this cuts full recalc 871 ms → 259 ms (-70%) and surgical edits 23 ms → 10 ms (-57%).

- **Skip redundant `_rebuild_dep_graph` on cold load.** `jsonload`'s per-cell `_setcell_no_recalc` already populates `_dep_of` / `_subscribers` / `_volatile` via incremental `_refresh_deps` calls. The subsequent `recalc()` previously walked every formula AST a second time to rebuild the same graph from scratch. New `Grid._dep_graph_built` flag tracks whether the graph is consistent; set True at the end of `_rebuild_dep_graph` and at the end of `jsonload` when mode is non-LEGACY. `_recalc_topo` checks the flag and skips the rebuild when the graph is current. Cold load on ranges sheet: 1267 ms → 677 ms (-47%); typical mixed sheet: 662 ms → 476 ms (-28%).

- **`benches/` profiler harness.** New `benches/gen_sheet.py` produces four representative sheet shapes (wide independent formulas, long chains, range-heavy aggregates, realistic mix) at ~30K cells each. `benches/run.py` wraps `cProfile` around four operations (cold load, full recalc, surgical edit, save) per shape and prints top-N hotspots plus a one-page summary. `make bench` runs end-to-end; `make bench-clean` removes fixtures. Used to identify the two optimisations above.

- **2D-aware `Vec` (Phases 1-4 of `docs/2d-vec-design.md`).** Foundation for `TRANSPOSE`/`LINEST`/`HSTACK`/2D `CHISQ.TEST`/spill semantics.

  - **Phase 1 — shape API on `Vec`** (`engine.py`): new `is_2d`, `rows`, `shape`, `at(r, c)` (1-based), `row(i)`, `col(j)`, `iter_rows()`. `__repr__` now shows shape: `Vec[2x3]([...])`. `__iter__`/`__len__`/ `__getitem__` keep flat semantics so existing `SUM`/`AVG`/etc. consumers stay correct. A 1D `Vec` is a column vector (shape `(n, 1)`). 11 new tests in `TestVecShapeAPI`.

  - **Phase 2 — shape preservation through arithmetic + persistence.** `Vec._binop`/`_rbinop`/`__neg__`/`__abs__` and the evaluator's `_vec_apply2`/`_vec_apply1` now forward `cols` whenever inputs share or imply a shape. Mismatched 2D shapes emit per-element `#VALUE!`
    instead of silently zip-pairing. New `Cell.arr_cols: int | None`
    slot; `_store_formula_result` stores `result.cols` alongside
    `arr`, and `_cell_lookup_value` rebuilds `Vec(cl.arr, cols=cl.arr_cols)`.
    All ~12 `cl.arr = ...` write sites updated to keep `arr_cols` in
    lockstep. JSON format unchanged (saves cell *text*, not computed
    arrays — recalc rebuilds shape from formulas on load).
    Ship gate: `=INDEX(A1:B2 + 1, 2, 2)` now picks the bottom-right of
    a 2D arithmetic result (was broken: `cols` dropped through `+`). 8
    new tests in `TestVecShapePreservation`.

  - **Phase 3 — TRANSPOSE + reshape consumers (12 new functions).** `TRANSPOSE` (1D column → 1×n row, 2D row/col swap, round-trip correct), `CHOOSEROWS`/`CHOOSECOLS` (1-based index lists with negative-from-end, accept `Vec`/list of indices via `_normalize_indices`), `TOROW`/`TOCOL` (flatten with `ignore` flags for blanks/errors and `scan_by_column` order; `TOCOL` returns a 1D column vector), `WRAPROWS`/`WRAPCOLS` (reshape 1D into 2D with target row/col length; pad short final chunks `#N/A` by default), `EXPAND` (pad to target shape; smaller target → `#VALUE!`), `TAKE`/`DROP` (positive from start, negative from end, along rows + cols), `HSTACK`/`VSTACK` (proper row interleaving + concatenation, mismatched dims pad `#N/A` to the widest/tallest). 20 new tests in `TestReshape2D`. Ship gate: `=INDEX(TRANSPOSE(A1:C2), 1, 2) == 4` end-to-end.

  - **Phase 4 — `LINEST` family with multi-regressor support (4 new functions).** Hand-rolled `_solve_linear_system` (Gauss-Jordan with partial pivoting, `1e-15` singularity tolerance) on the normal-equations matrix `X'Xβ = X'y`; `_linest_core` builds the design matrix with optional intercept; `_linest_stats_matrix` builds the 5×p Excel stats matrix (row 1 coefficients in Excel order `m_k…m_1, b`; row 2 standard errors via `sqrt(σ²·diag((X'X)⁻¹))`; rows 3-5 r² / standard error / F / df / SS_reg / SS_resid). `LINEST` (single + multi regressor; `const=FALSE` forces through origin; `stats=TRUE` returns the 5×p matrix), `LOGEST` (`LINEST` on `ln(y)` then exp of coefficients), `TREND` (replaces the prior `TREND_SCALAR`, accepts scalar/1D/2D `new_x`), `GROWTH` (TREND on log-scale). Recovers `y = 1 + 2·x₁ + 3·x₂` synthetic to ~1e-9 over 6 observations. 12 new tests in `TestRegressionFamily`.

- **Heavier stat distributions (Tier 4, batch 2; ~25 new dotted names

  - 17 pre-2010 aliases).** Builds on the regularised incomplete beta (`_incbeta`) infra from batch 1 plus a new regularised lower incomplete gamma (`_gser`/`_gcf`/`_incgamma`, Numerical Recipes). Inverses use 200-step bisection on the CDF (1e-12 in p; ~10 decimal-digit accuracy in x).

  - **F**: `F.DIST`, `F.DIST.RT`, `F.INV`, `F.INV.RT`.

  - **Chi-square**: `CHISQ.DIST`, `CHISQ.DIST.RT`, `CHISQ.INV`, `CHISQ.INV.RT`, `CHISQ.TEST` (1D arrays, `df = n − 1`; 2D contingency form blocked on 2D Vec).

  - **Gamma family**: `GAMMA`, `GAMMALN`, `GAMMALN.PRECISE`, `GAMMA.DIST`, `GAMMA.INV`.

  - **Beta**: `BETA.DIST` (with `[a, b]` bounds), `BETA.INV`.

  - **Lognormal**: `LOGNORM.DIST`, `LOGNORM.INV`.

  - **Weibull**: `WEIBULL.DIST`.

  - **Hypergeometric / negative binomial / inverse binomial**: `HYPGEOM.DIST` (with cumulative), `NEGBINOM.DIST`, `BINOM.INV`.

  - **Hypothesis tests**: `T.TEST` (paired / equal-var / Welch), `Z.TEST` (one-tailed; sample stdev when σ omitted), `CONFIDENCE.T`.

  - **Other**: `STANDARDIZE`, `PHI`, `PROB`.

  - **Pre-2010 aliases**: `FDIST`/`FINV` (right-tail), `CHIDIST`, `CHIINV`, `CHITEST`, `GAMMADIST`, `GAMMAINV`, `BETADIST`, `BETAINV`, `LOGNORMDIST`, `LOGINV`, `WEIBULL`, `HYPGEOMDIST`, `NEGBINOMDIST`, `CRITBINOM`, `TTEST`, `ZTEST`.

  - 19 new tests cross-checked against Excel reference values (≥5–9 sig figs).

- **Mechanical fill-in batch (~32 new functions).**

  - **Math**: `ERF` (one- and two-arg), `ERFC` via `math.erf`/`erfc`.

  - **Tier 4 text parsing**: `TEXTSPLIT` (1D/2D, with `ignore_empty`/ `match_mode`), `TEXTBEFORE`, `TEXTAFTER` (full Excel 365 signatures including negative `instance` from end, list-of-delimiters, `match_end`, `if_not_found`).

  - **Number-base conversion** (12): `DEC2BIN`/`OCT`/`HEX`, `BIN2DEC`/`OCT2DEC`/`HEX2DEC`, plus all six cross conversions. Excel-style 10-digit two's-complement for negatives; per-base range validation; `places` padding with `#NUM!` on overflow.

  - **Scalar forecasting**: `FORECAST`, `FORECAST.LINEAR`, `TREND` (scalar + 1D Vec of new x-values; default `known_x = {1, 2, 3, ...}` when omitted). All reuse `_linreg`. Multi-regressor / array forms blocked on 2D Vec.

  - **D-functions** (12): `DSUM`, `DAVERAGE`, `DCOUNT`, `DCOUNTA`, `DGET`, `DMAX`, `DMIN`, `DPRODUCT`, `DSTDEV`, `DSTDEVP`, `DVAR`, `DVARP`. Shared driver: `_vec_table` decomposes a 2D `Vec` into header + rows, `_resolve_field` accepts column name or 1-based index, `_row_matches_criteria` ANDs across columns within a row and ORs across rows (Excel semantics). 25 new tests.

- **Financial Tier 4 (12 new functions).**

  - **Depreciation**: `SLN`, `SYD`, `DB` (3-decimal rate rounding + month proration), `DDB` (factor-decline, salvage clamp), `VDB` (DDB with optional SL switch; integer periods only — fractional `start`/`end` returns `#NUM!`).

  - **Rate conversion**: `EFFECT`, `NOMINAL`.

  - **Cumulative**: `CUMIPMT`, `CUMPRINC` (sum existing `IPMT`/`PPMT` over a period range).

  - **Date-based & modified IRR**: `XNPV`, `XIRR` (365-day basis, Newton's method); `MIRR` (closed form on negative-flow PV vs positive-flow FV).

  - 14 new tests cross-checked against Excel docs reference values (`SLN(10000,1000,5)=1800`; `DB(1e6,1e5,6,1,7)=186083.33`; `DDB(2400,300,10,1)=480`; `EFFECT(0.0525,4)=0.05354266…`; `MIRR` Excel example = `0.126094`; `XNPV(0.09,…)=2086.65`, `XIRR=0.37336` from Excel docs example).

- **Statistical distributions (Tier 4, batch 1; 13 new dotted names + 10 legacy aliases).** Stdlib-only implementation. Helpers: `_norm_pdf`/`_norm_cdf` via `math.erf`; `_norm_s_inv` via Acklam's rational approximation (max relative error ~1.15e-9); `_betacf` (Lentz CF) and `_incbeta` for the regularised incomplete beta; `_t_cdf` and `_t_inv`/`_t_inv_2tail` (bisection); `_binom_pmf`, `_pois_pmf` via `math.lgamma`. Functions: `NORM.DIST`/`NORM.INV`, `NORM.S.DIST`/`NORM.S.INV`, `T.DIST`/`T.DIST.2T`/`T.DIST.RT`/ `T.INV`/`T.INV.2T`, `BINOM.DIST`, `POISSON.DIST`, `EXPON.DIST`, `CONFIDENCE.NORM`. Pre-2010 aliases: `NORMDIST`, `NORMINV`, `NORMSDIST` (1-arg, always cumulative), `NORMSINV`, `TDIST` (legacy 3-arg right/two-tail), `TINV` (legacy two-tailed), `BINOMDIST`, `POISSON`, `EXPONDIST`, `CONFIDENCE`. 17 new tests cross-checked against Excel reference values to ≥5 sig figs.

- **Excel function library: Tier 1 + Tier 2 (~60 new functions).**

  - **Multi-criteria aggregates**: `SUMIFS`, `COUNTIFS`, `AVERAGEIFS`, `MAXIFS`, `MINIFS`.

  - **Date/time**: `NOW`, `TODAY`, `DATE`, `TIME`, `DATEVALUE`, `TIMEVALUE`, `YEAR`, `MONTH`, `DAY`, `HOUR`, `MINUTE`, `SECOND`, `WEEKDAY`, `EDATE`, `EOMONTH`, `DATEDIF`, `NETWORKDAYS`, `WORKDAY`. Excel epoch (1899-12-30) so serials match Excel's 1900-leap-year convention.

  - **Information**: `ISNUMBER`, `ISTEXT`, `ISBLANK`, `ISERROR`, `ISNA`, `ISERR`, `ISLOGICAL`, `ISEVEN`, `ISODD`, `NA`, `N`.

  - **Text utilities**: `FIND`, `SEARCH`, `REPLACE`, `TEXTJOIN`, `CHAR`, `CODE`, `VALUE`, `TEXT` (subset of Excel format strings).

  - **Statistical**: `STDEV`, `STDEVP`, `VAR`, `VARP`, `CORREL`, `COVAR`, `RANK`, `PERCENTILE`, `QUARTILE`, `MODE`, `GEOMEAN`, `HARMEAN`.

  - **Financial**: `PV`, `FV`, `PMT`, `NPER`, `RATE`, `NPV`, `IRR`, `IPMT`, `PPMT`. `RATE` and `IRR` use Newton's method.

  - **Math**: `CEILING`, `FLOOR`, `MROUND`, `ODD`, `EVEN`, `FACT`, `GCD`, `LCM`, `TRUNC`.

  - **Logical**: `IFS`, `SWITCH`, `IFNA`, `XOR`.

  - **Reference subset**: `CHOOSE`. (`ADDRESS`, `OFFSET` deferred -- `OFFSET` needs dynamic-ref handling.)

  - 39 new tests in `tests/test_libs.py` exercising these via direct calls and end-to-end formula evaluation.

- **`ROW`, `COLUMN`, `ROWS`, `COLUMNS`** via a new raw-args path in the evaluator. Functions registered in `RAW_ARG_FUNCS` (`evaluator.py`) receive AST nodes (`CellRef`, `RangeRef`) plus `Env`, instead of evaluated values. `Env.current_cell` is populated by recalc loops before each formula eval so `ROW()`/`COLUMN()` can report the calling cell. `formula.deps.extract_refs` and `engine._ast_uses_cell` both treat these functions as address-only, so e.g. `=ROWS(A1:B10)` written into a cell inside the range does not register a spurious self-cycle. 8 new tests in `TestRowColumnFunctions`. Total function count: ~108.

- **Topological recalc graph stays consistent across structural edits.** `Grid._rebuild_dep_graph()` walks all formula cells and reconstructs `_dep_of`/`_subscribers`/`_volatile`; called from `insertrow`, `insertcol`, `deleterow`, `deletecol`, `swaprow`, `swapcol`, and at the top of `_recalc_topo` on full-recalc paths (handles LEGACY -> EXCEL/HYBRID mode switches and initial loads). `replicatecell` was refactored to route through `_setcell_no_recalc` so the destination cell's deps are tracked. New `TestTopoGraphInvariants` (7 tests) exercises each path with a forward/reverse-index consistency check.

- **`jsonload` uses bulk-set semantics**: was N x O(formulas) per-cell recalcs; now single recalc at the end. 5000-cell load: ~18 ms.

- **LEGACY mode skips dep-graph maintenance.** `_refresh_deps` returns early in LEGACY mode -- the graph is unused there (fixed-point recalc). Removes the parsing overhead per cell-write in LEGACY.

- **Topological recalc** (default ON): replaces the fixed-point recalc loop with a dependency-graph traversal. `Grid` now maintains forward (`_dep_of`) and reverse (`_subscribers`) indexes built from each formula's AST via `formula.deps.extract_refs`. `recalc(dirty)` computes the transitive closure of changed cells through the reverse index, topologically sorts via Kahn's algorithm, and evaluates each cell exactly once. Cells containing `INDIRECT`/`OFFSET`/`INDEX`/`PyCall` are flagged volatile and unconditionally added to the closure. Surgical edit benchmark (1 source change in a 10,000-cell sheet, 5000 formulas): 7.4 ms -> <0.1 ms. Cycle detection is now structural (Kahn's leftover) rather than "didn't converge in 100 iterations". Design rationale and remaining phases in `docs/topological.md`. The legacy fixed-point path (`Grid._recalc_formula`) remains in the codebase one release as a fallback, gated by `_use_topo_recalc = False` per-instance or `GRIDCALC_TOPO=0` for the test suite.

- **`docs/topological.md`**: design note covering the algorithmic motivation, current cost model, the static dep extractor, hard parts (dynamic refs, range explosion, named ranges, py.* gateway, graph mutation, LEGACY mode), the phased implementation plan, open questions, and triggers for when to revisit.

- **Native xlsx I/O via OpenXLSX** (nanobind `_core` extension): xlsx read and write now go through a C++ binding around vendored [OpenXLSX](https://github.com/troldal/OpenXLSX). On a 5000-cell grid, `_core.xlsx_read` parses in ~4 ms vs. ~80 ms for the prior Python loop. `xlsx_read` iterates `wks.rows() -> row.cells()`, skipping cells that are both empty and formula-free.

- **Build system migration to scikit-build-core + nanobind**: `pyproject.toml` uses `scikit-build-core` as the build backend; CMake builds the `_core` extension and links the OpenXLSX subdirectory under `thirdparty/OpenXLSX/`. `CMAKE_POLICY_VERSION_MINIMUM=3.5` is set so the fetched `miniz` dependency configures under CMake 4.

- **`Grid.setcells_bulk(cells)`**: bulk-set API that defers `recalc()` until all cells are written. Loading 5000 cells via `setcells_bulk` is ~810x faster (5 ms vs 4070 ms) than calling `setcell` N times. `xlsxload` now uses it; combined with the C++ read path, end-to-end load is ~72x faster (12 ms vs 839 ms for 5000 cells).

- **`src/gridcalc/_core.pyi`**: type stubs for the nanobind extension so mypy resolves `_core.xlsx_read` / `_core.xlsx_write`.

### Infrastructure

- **Cross-platform wheel builds and CI fixed end-to-end.** Every target now builds and tests green across `ci.yml`, `build-publish.yml`, and `build-abi3.yml`: manylinux x86_64 + aarch64, macOS x86_64 + arm64, and Windows AMD64. Each failure was platform-specific and had been masked by the one before it:

  - **Linux link failure.** `CMAKE_POSITION_INDEPENDENT_CODE ON` in `CMakeLists.txt`. The static dependencies OpenXLSX fetches (miniz, pugixml) were compiled without `-fPIC`, so GNU ld refused to link `libminiz.a` into the shared `_core` module (`relocation R_X86_64_PC32 ... recompile with -fPIC`). macOS links non-PIC static objects fine, so the break was Linux-only.

  - **Windows compile failure.** `lp_lib.h` defines `isnan` as a macro (`-> _isnan`) on MSVC, turning `_opt.cpp`'s `std::isnan(...)` into `std::_isnan(...)` (`error C2039`). `_opt.cpp` now `#undef`s the macro after the lp_solve include; lp_solve's own sources compile separately and keep theirs.

  - **Windows runtime.** `windows-curses` added as a `sys_platform == 'win32'` dependency -- curses is not in the Windows stdlib and the console entry point is the curses TUI, so the shipped Windows wheel previously crashed on launch.

  - **macOS build failure.** `MACOSX_DEPLOYMENT_TARGET=10.15` on the macOS wheel jobs. cibuildwheel defaults the x86_64 wheel to 10.9, which lacks both nanobind's C++17 aligned `new`/`delete` (10.13+) and OpenXLSX's `std::filesystem` (10.15+). Local builds never hit this because they target the host SDK, not 10.9.

  - **aarch64 timeout.** Linux wheels split into an x86_64 job on `ubuntu-latest` and an aarch64 job on the native `ubuntu-24.04-arm` runner. Building aarch64 under QEMU emulation compiled OpenXLSX so slowly that the job hit the 6h limit and was auto-cancelled.

  - **CI QA job.** mypy now checks `src/gridcalc/` only (it had been checking `tests/` under `strict = true`, emitting 1746 errors); the build matrix moved 3.9 -> 3.10 to match `requires-python`; and `pytest-cov` joined the dev group so the `--cov` test step runs.

  - **Test portability.** `tests/test_tui.py` resolves its example fixture relative to `__file__` instead of the process CWD, so the suite passes under cibuildwheel, which runs pytest from a temporary directory where the old relative path silently missed and left the grid empty.

- **Stable-ABI (cp312-abi3) wheel build path.** A new `.github/workflows/build-abi3.yml` produces a single `cp312-abi3-<platform>` wheel per OS / arch that installs unchanged on every Python >= 3.12. Driven by an opt-in CMake flag (`GRIDCALC_STABLE_ABI=ON`) plus scikit-build-core's `wheel.py-api=cp312`; both passed via `CIBW_CONFIG_SETTINGS`. The CMake side now also requests the optional `Development.SABIModule` component so nanobind's STABLE_ABI mode actually engages (otherwise nanobind silently downgrades it). Local equivalents in the Makefile: `make wheel-abi3` (build the abi3 wheel), `make build-abi3` (in-place dev install with STABLE_ABI on), `make dist-abi3` (abi3 wheel + sdist + twine check). The default `make wheel` / `make build` paths keep emitting per-version artifacts unchanged.

- **`build-publish.yml` corrections.** Pinned all three OS jobs to `pypa/cibuildwheel@v3.4.1` (was a mix of v3.3.1 and v2.23). Dropped `cp39-*` from `CIBW_BUILD` (mismatched `pyproject.toml:requires-python = ">=3.10"`). Fixed a `cp313-*-*` pattern typo. Added `CIBW_ENVIRONMENT: GRIDCALC_SANDBOX=1` so the test command runs with the same sandbox state the local Makefile uses.

### Changed

- **Renamed `LEGACY` mode to `PYTHON`.** The mode is the Python-eval flavor (full expressions, code-block functions reachable without the `py.` prefix, ndarray / DataFrame / list-comprehension support); "LEGACY" implied deprecation, which was never the intent. Changes:

  - `Mode.LEGACY` → `Mode.PYTHON` (integer value unchanged at 3, so `"mode": 3` in JSON keeps working without translation).

  - JSON files containing `"mode": "LEGACY"` continue to load -- `Mode.parse` accepts both `"legacy"` and `"python"` (case- insensitive). New saves always write `"PYTHON"`.

  - `:mode legacy` continues to work; `:mode python` is the canonical form. The invalid-input error message lists `python`.

  - Status bar now shows `[PYTHON]` instead of `[LEGACY]`.

  - Internal renames: `Grid._recalc_legacy` -> `Grid._recalc_python`; docstring and comment references updated across `engine.py`, `opt.py`, `libs/xlsx.py`.

  - Example files `example_lp.json` and `example_goal.json` rewritten to use the new canonical name.

- **`__builtins__` in the LEGACY eval namespace is now read-only.** `_make_eval_globals` wraps the inner allowlisted-builtins dict with `types.MappingProxyType` so a sandbox escape that obtains a reference to `__builtins__` cannot inject `eval`/`__import__`/etc. to poison subsequent formulas in the same recalc. The outer `_eval_globals` stays mutable (lib loading, per-iteration cell-value injection), and the HYBRID `_build_py_registry` shallow copy still works because the proxy points at the same underlying dict, which exec cannot mutate via the proxy. 4 new tests in `TestBuiltinsFrozen` (proxy type, write rejection, name resolution through the proxy, outer-globals mutability).

- **`refabs` returns a named `RefMatch` tuple.** Promoted the unnamed 5-tuple `(chars_consumed, col, row, abs_col, abs_row)` to a `NamedTuple` so call sites self-document. Existing tuple-unpacking call sites (`n, rc, rr, ac, ar = result`) continue to work unchanged.

- **Zero third-party runtime dependencies for the core install.** `numpy`, `pandas`, and `pygments` moved out of `[project.dependencies]` into `[project.optional-dependencies]` as the `[numpy]`, `[pandas]` (implies numpy), `[viz]`, and `[all]` extras. All 300+ Excel functions — including the full statistical-distribution suite, financial functions, the regression family, and the 2D-Vec reshape consumers — work on stdlib alone. `tomli` is the only remaining runtime dep, conditional on Python <3.11. Existing duck-typing helpers (`_is_ndarray`/`_is_dataframe`/ `_is_series`) continue to gate ndarray/DataFrame-aware paths without importing the relevant module.

  - **Optional numpy speedup in regression**: `_solve_linear_system` now tries `numpy.linalg.solve` first (LAPACK-backed; ~100× faster on large systems and more accurate on ill-conditioned designs) and falls back to the existing pure-Python Gauss-Jordan elimination when numpy isn't installed. `_linest_core`'s `X'X` build similarly upgrades to `X.T @ X` when numpy is available.

  - **Pygments fallback**: the trust-prompt code preview (`tui._highlight_code`) falls back to plain (uncoloured) text when Pygments isn't installed.

  - **Tests**: numpy/pandas-dependent classes are now guarded with `@pytest.mark.skipif(not _HAS_NUMPY/PANDAS, ...)`. New `make test-stdlib` target runs the suite in a `uv --isolated` environment with no extras, exercising the optional-import paths. 897 / 46 split (passing / skipped) without extras; full 951 passing with `[all]`.

- **`openpyxl` is now a dev-only dependency**: moved from `[project.dependencies]` to `[dependency-groups].dev`. Runtime xlsx I/O goes through the OpenXLSX-backed `_core`; failures surface as return code -1 (no silent fallback). `openpyxl` is retained in tests as an independent oracle for fixture construction.

- **`engine.setcell` refactored**: per-cell parsing/typing extracted to `_setcell_no_recalc`; `setcell` composes that helper with `recalc()`.

- **`tui.py` split into a `tui/` package.** The 3364-line single-file TUI was the largest module in the tree and mixed every concern -- cell formatting, undo/clipboard, curses rendering, the full `:`-command set, the opt/goal CLI parsing, and the interactive input modes plus the event loop. It is now a package organized by concern, behavior-preserving and verified against the unchanged suite (1219 passing; the 6 PTY integration tests exercise the real curses render path):

  - `format.py` (cell display formatting), `undo.py` (`UndoManager` / `Clipboard`), `render.py` (`draw`, colors, label overflow), `widgets.py` (generic curses input/output helpers), `search.py` (grid search), `objedit.py` (the Vec/ndarray/DataFrame sub-editor), `solve.py` (`:opt` / `:goal`), `commands.py` (all `cmd_*`, `cmdexec`, the interactive cursor commands), and `_state.py` (shared `_cfg`).

  - The public import surface is unchanged: `tui/__init__.py` re-exports every previously module-level name, so `from gridcalc.tui import ...` keeps working.

  - The interactive controller -- `cmdline`, `entry`, `visual_mode`, `mainloop`, the keymap state `_resolved_keymap`, and `_action_for` -- stays in `tui/__init__.py` by design rather than moving to a submodule. The test-suite patches `gridcalc.tui.draw` and rebinds `gridcalc.tui._resolved_keymap` then drives `cmdline`; Python resolves a function's free variables in its *defining* module, so the patched names and their tested callers must share the package namespace for the patches to be observed.

  - Note for the editable install: scikit-build-core pins a module->file map in `_gridcalc_editable.py`, which still pointed `gridcalc.tui` at the old `tui.py`. `make build` (`uv sync --reinstall-package gridcalc`) regenerates it; a rebuild is required after pulling this change.

- **Deduplicated repeated TUI patterns** (alongside the package split, behavior-preserving):

  - `widgets._flash` -- the no-wait bottom-line status message (vs the wait-for-key `show_error`), replacing ~5 inline copies in `solve.py`.

  - `widgets._line_input` -- one single-line edit loop now backs `prompt_filename`, `cmd_width`, `cmd_name`, `cmd_unname`, and the object-editor's mini-input; callers pass an `accept(ch, buf)` predicate to keep their per-field rules (digits-only, identifier rules, ...).

  - `commands._io_command` -- unifies `:csv`, `:xlsx`, and `:pd`, which differed only in default save extension, whether a load clears the grid first, and whether a load marks it dirty.

  - `commands._arrow_move` -- the identical clamped arrow-key cursor move shared by `selectrange` and `replcmd`.

  - `render._fmt_collection` -- the DataFrame / ndarray / Vec status-bar rendering shared by `draw`'s NUM and FORMULA branches.

  - `widgets._line_input` generalized to also back the keybinding-aware prompts. It grew optional hooks -- a `dispatch(ch)` callback (the `_action_for` keymap lookup), a `transform` for typed chars, extra `commit_keys`, and `maxlen` -- so `cmdline()`, `search_prompt()`, `nav()` (live cell-ref validation, Tab-commits, upper-casing), and the `_resolve_fmt()` Python-spec sub-loop now share the one edit loop. The `selectrange()`/`replcmd()` arrow-pick loops are deliberately left standalone: they interleave grid navigation with text entry and aren't a line reader (only the clamped move is shared, as `_arrow_move`).

### Fixed

- **Excel lookup and criteria audit.** A systematic pass over `libs/xlsx.py` against Excel semantics fixed several divergences:

  - `SUMIF`/`COUNTIF` with the not-blank criterion `"<>"` counted blank (`None`) cells as non-blank. `"<>"` is now the exact complement of the blank predicate, and `"="` (like `""`) matches blanks -- so a blank cell is consistently either blank or non-blank across the pair.

  - `AVERAGEIF` with no matching numeric values returned `0.0`; Excel returns `#DIV/0!` (division by a zero count), which already matched `AVERAGEIFS`.

  - `MATCH` returned `#VALUE!` for an out-of-domain `match_type` such as `2` or `-2`; Excel is lenient and clamps by sign (any positive behaves as `1`, any negative as `-1`). Documented `1/0/-1` usage is unchanged.

  - `INDEX(rng, 0, 0)` returned `#REF!`/`#VALUE!`; Excel returns the whole reference. It now returns the entire range as a `Vec` (preserving `cols`), consistent with the existing whole-row / whole- column behaviour for a single zero index.

  - `XLOOKUP` with a 2D `return_array` returned an arbitrary scalar; it now returns the whole matching row as a `Vec`, matching Excel's multi-column spill. A 1D `return_array` still returns a scalar.

  Verified-correct-and-locked with tests (no change needed): `MATCH` `0`/`1`/`-1`, `VLOOKUP`/`HLOOKUP` approximate match, `XLOOKUP`/`XMATCH` next-smaller/next-larger, and bool-vs-number / case-insensitive criteria. Left intentionally (each needs a missing primitive or is genuinely ambiguous in Excel): numeric-vs-text criteria coercion (`COUNTIF({1,2,"3"}, 3)`), date-string criteria, and `SUMIF` with a `sum_range` shorter than the criteria range. New tests across `TestCriteriaAuditFixes`, `TestLookupAuditFixes`, and `TestConditionalAggregates`.

- **Text and booleans now survive range materialization.** `formula/evaluator.py:_eval_range` previously called `_to_number_or_zero` on every cell, flattening text and bools to `0.0`. This silently broke `MATCH("be*", A1:A3, 0)` and similar over real Grid ranges (the lookup column arrived as `[0.0, 0.0, 0.0]`). `_eval_range` now preserves type per cell: numeric -> float, bool -> bool, str -> str, None -> 0.0, ExcelError -> propagate. `Vec.data` widened to `list[Any]`. `Vec` arithmetic (`__add__`/`__sub__`/..., `__neg__`/`__abs__`) goes through new `_vec_elem_op`/`_unary_or_error` helpers that emit per-element `#VALUE!` for non-numeric pairs and propagate `ExcelError`. `SUM`/`AVG`/`MIN`/`MAX` skip strings and bools-from-ranges (Excel's non-`A` aggregate rule); `COUNT` counts numerics only; `ABS`/`SQRT`/`INT` propagate per-element `#VALUE!` for non-numerics. `libs/xlsx.py` audited: `_vec_data` filters numerics; new `_pair_numeric` for paired stats; `CORREL`/`COVAR`/ `_linreg`/`RSQ`/`STEYX`/`_covariance`/`_paired_data`/`RANK`/ `PERCENTILE`/`PERCENTILE_EXC`/`RANK_AVG`/`PERCENTRANK`/`NPV`/`IRR`/ `SUMIF`/`AVERAGEIF`/`_multi_criteria`/`GCD`/`LCM`/`SUMPRODUCT`/ `AVERAGE`/`MEDIAN`/`LARGE`/`SMALL` all skip non-numerics. 10 new tests in `TestRangeTextBool`.

- **`IPMT` sign convention.** Returned positive when paying interest on a positive `pv` (a loan); Excel convention is negative. Fix: `interest = fv_at * rate` (was `-fv_at * rate`); when `when=1` and `period > 1`, discount by one period. `PPMT` and the new `CUMIPMT`/`CUMPRINC` inherit the fix. No existing tests broke (there were no IPMT/PPMT tests before).

### Removed

- **`openpyxl` from sandbox allowlist** (`SIDE_EFFECT_MODULES`): now that it is no longer a runtime dependency, user formulas can no longer `import openpyxl`.

- **Internal `_xlsx_cell_to_text` helper**: no longer needed once the openpyxl read path was removed.

- **Vendored OpenXLSX trimmed** (2.8M -> 1.5M): dropped `Benchmarks/`, `Documentation/`, `Examples/`, `Tests/`, `gnu-make-crutch/`, `Notes/`, `Scripts/`, `Makefile.GNU`, `vcpkg.json`, and `README.md` from `thirdparty/OpenXLSX/`. Retained `CMakeLists.txt`, `cmake/`, `OpenXLSX/`, and `LICENSE.md` (BSD-3 attribution).

- **Legacy fixed-point recalc path** (`Grid._recalc_formula`). Topological recalc (`_recalc_topo`) has been the default for EXCEL/HYBRID modes; the old fixed-point loop -- iterate the whole sheet up to 100 times until values stabilize -- was retained one release as a fallback behind the `_use_topo_recalc` flag and the `GRIDCALC_TOPO=0` env override. With the soak period elapsed, the fallback is gone: `recalc()` dispatches straight to `_recalc_topo` (non-PYTHON modes) or `_recalc_python`, and the `_use_topo_recalc` flag, the now-orphaned `_ast_uses_cell` AST helper (the fixed-point path's direct self-reference detector; topo uses the dep graph), and the `tests/conftest.py` env hook were all removed. Behavior is unchanged -- the topo path was already exercised by the full suite.

## [0.1.3]

### Added

- **Three formula modes** (`EXCEL`, `HYBRID`, `LEGACY`): Each spreadsheet now carries an explicit mode controlling how formulas are evaluated. `EXCEL` uses a strict Excel-compatible grammar (no `eval()`, no Python). `HYBRID` layers a `py.<name>(...)` gateway on top of the Excel grammar so functions defined in the code block remain reachable while keeping the Python boundary visible in every formula that crosses it. `LEGACY` preserves the original Python-eval path with full numpy/pandas/list-comprehension
  support. Mode is persisted in the JSON file as `"mode": "EXCEL"|"HYBRID"|
  "LEGACY"`; files without the field load as `LEGACY` for back-compat.

- **Excel formula evaluator** (`gridcalc.formula` package): New lexer, recursive-descent parser, and tree-walking evaluator implementing Excel-style grammar -- operators (`^` right-assoc, `&` concat, `<>`, `<=`, `>=`, `%` postfix), error literals (`#DIV/0!`, `#N/A`, `#NAME?`, `#REF!`, `#VALUE!`, `#NUM!`, `#NULL!`), error propagation through arithmetic, range broadcasting, named ranges, and the `py.*` gateway in `HYBRID`. Replaces `eval()` for `EXCEL` and `HYBRID` cells; `LEGACY` cells still use `eval()`.

- **AST cache on `Cell`**: Parsed-formula ASTs are cached per cell and invalidated on text change, eliminating per-iteration re-parsing in the recalc loop.

- **xlsx interop** (`:xlsx save [file]`, `:xlsx load [file]`): Read and write `.xlsx` files via openpyxl. `:xlsx load` translates Excel formulas into the gridcalc EXCEL grammar, switches the grid to `EXCEL` mode, and auto-loads the Excel function library. `:xlsx save` writes computed values to a single worksheet. Sheet-qualified refs (`Sheet1!A1`), `INDIRECT`, and multi-sheet workbooks are not supported.

- **`:mode [excel|hybrid|legacy]`**: Show or set the current mode.
  Switching validates every formula with the target evaluator first and refuses the change with a one-line error pointing at the first offender if anything fails. `EXCEL` also rejects switches that would leave a code block in place.

- **Auto-loaded Excel function library**: When mode is `EXCEL` or `HYBRID`, the `xlsx` library (`IF`, `IFERROR`, `AND`, `OR`, `NOT`, `ROUND`, `AVERAGE`, `MEDIAN`, `SUMIF`, `COUNTIF`, `AVERAGEIF`, `VLOOKUP`, `HLOOKUP`, `INDEX`, `MATCH`, `LEFT`, `RIGHT`, `MID`, `LEN`, `TRIM`, `UPPER`, `LOWER`, `SUBSTITUTE`, etc.) is loaded automatically. Previously the library required a manual `g.load_lib("xlsx")`.

- **Mode tag in TUI status bar**: The current mode is shown in the top-right region (`[EXCEL]`, `[HYBRID]`, `[LEGACY]`) using the mode-color attribute.

- **New TUI files default to `HYBRID`**: A fresh TUI session (no file argument) creates a grid in `HYBRID` mode with the xlsx library pre-loaded. Loaded files keep whatever mode their JSON specifies. The library default `Grid()` constructor stays `LEGACY` for back-compat with programmatic users.

- **Example files**: `example_excel.json` (quarterly sales report demonstrating `IF`, `SUM`/`AVG`/`MAX`/`MIN`, `MATCH`, `IFERROR`, named ranges, and range arithmetic) and `example_hybrid.json` (progressive tax calculator using a Python `py.progressive_tax()` alongside Excel formulas for aggregation, plus compound-interest and loan-payment demos).

- **Visual mode delete** (`d` / `Backspace`): In visual selection mode, press `d` or `Backspace` to clear all cells in the selection. Each cell is saved to undo before clearing. A count message is shown in the status bar.

- **Cell edit mode** (`e` / `F2`): Press `e` or `F2` on a non-empty cell to enter edit mode with the existing cell content pre-loaded in the input buffer. Modify the text and press Enter to save, or Escape to cancel. Previously, entering data always started from scratch.

- **Object editor** (`E`): Press `E` on a cell containing a Vec, NumPy array, or DataFrame to open an interactive sub-grid editor. Navigate with arrow keys, edit individual elements with Enter, add/remove rows and columns, and edit DataFrame column headers. `w` saves and exits, `Esc` discards changes. Writes back a literal formula (`=Vec([...])`, `=np.array([...])`, or `=pd.DataFrame({...})`). Supports viewport scrolling for large objects.

- 10 new tests for `_fmt_val` and `_build_formula` covering Vec, ndarray, and DataFrame formula generation with roundtrip verification.

- 162 new tests covering the formula package (lexer, parser, evaluator), mode persistence and dispatch, AST cache, `py.*` gateway, validate-on- mode-change, auto-loaded library, and xlsx round-trip I/O. Total test count: 676 (was 514).

### Changed

- **`openpyxl>=3.1`** added as a runtime dependency for the new xlsx I/O.

- **`Cell.__slots__`** gained `ast` and `ast_text` for the per-cell parsed- formula cache.

- **`Grid.recalc()`** now dispatches by mode: `EXCEL`/`HYBRID` cells go through the new tree-walking evaluator; `LEGACY` cells continue to use `eval()`. Self-reference detection in the new path is structural (AST walk) rather than regex.

- **`IFERROR`** now recognizes the new `ExcelError` enum in addition to `NaN`/`inf`. Previously, errors short-circuited before reaching the function so the fallback was never taken; the evaluator now exempts error-aware functions (`IFERROR`, `IFNA`, `ISERROR`, `ISERR`, `ISNA`) from automatic error propagation on their arguments.

### Fixed

- **String-returning formulas no longer display as `nan`.** Added
  `Cell.sval: str | None` slot, populated by `_store_formula_result`
  when a formula returns a string or bool. The TUI render path (`fmtcell`, status bar) prefers `sval` over `val` for FORMULA cells. Bool results also write `val=1/0` so aggregate functions still see a number. `IF(A1>0, "yes", "no")`, `="x" & "y"`, and `=1=1` all render correctly now.

- **`tui.py:1906`** pre-existing `assert headers is not None` replaced with an explicit None guard. Resolves the lone `S101` lint finding the repo had been carrying.

### Verified (no fix needed)

- **`_fixrefs` row/column swap semantics.** REVIEW.md flagged a suspected double-correction; tests in `test_swap_refs.py` confirm the unconditional rewrite is exactly how value-preservation works through `swaprow`/ `swapcol`. Every formula computes the same value before and after a swap, including outside-swap formulas and absolute references.

- **Search direction coordinate ordering.** REVIEW.md flagged a suspected `(r, c)` vs `(col, row)` mismatch; tests in `test_search_direction.py` show both sides of the comparison are `(row, col)` and forward/backward search across same-row and cross-row matches behaves correctly.

- **Backwards-range auto-swap (`B1:A1` -> `A1:B1`).** Matches Excel. Comments added at both swap sites (`_expand_ranges` for LEGACY, `_eval_range` for EXCEL/HYBRID) marking the normalisation as intentional.

## [0.1.2]

### Added

- **Pandas DataFrame support in formulas**: Formulas that return pandas DataFrames or Series are stored on `Cell.matrix`. DataFrames display as `df[3x2]` in the grid, with column names shown in the status bar. Series results are automatically converted to DataFrames via `.to_frame()`. DataFrame equality uses `.equals()` for recalc convergence. Cells holding DataFrames with non-numeric first elements no longer display as ERROR.

- **`:view` command**: View the DataFrame or ndarray in the current cell as a scrollable table with column headers, row numbers, and keyboard navigation (arrows, PgUp/PgDn, Home/End). Works for both DataFrames and NumPy matrices.

- **`:pd load`/`:pd save` commands**: Import and export grid data using pandas. Auto-detects file format from extension: CSV, TSV, Excel (.xlsx/.xls), JSON, and Parquet. `:pd load` places column headers in row 1 and data below. `:pd save` uses row 1 as column headers. Full undo support on load.

- **CSV import/export** (`:csv save [file]`, `:csv load [file]`): Plain CSV export writes evaluated cell values (not formulas). Import parses numbers as NUM cells and text as LABELs. Full undo support on load.

- **Search** (`/`, `n`, `N`): Press `/` to enter a search pattern (case-insensitive substring match against cell text and evaluated numeric values). `n` jumps to the next match, `N` to the previous, both wrapping around. The status bar shows a `[3/12]` position indicator when the cursor is on a match.

- **Cell copy/paste** (`y`/`p`): `y` yanks the current cell (or visual selection) to an internal clipboard. `p` pastes at the cursor. Paste copies cell text verbatim (no reference adjustment, unlike `:r`), preserving styles (bold, underline, format). Full undo support.

- **`:sort` command**: Sort rows by a column. `:sort B` sorts all data rows by column B ascending. `:sort B desc` for descending. Numbers sort before labels; labels sort alphabetically; empties sort last. In visual mode, only the selected rows are sorted (useful for preserving headers). Full undo support.

- **Extended visual selection operations**: `:b` blanks all cells in the selection. `:dr` deletes all selected rows. `:dc` deletes all selected columns. `y` yanks the selection, `p` pastes at the selection origin. All operations support undo.

- **NumPy ndarray support in formulas**: Formulas that return numpy arrays (1-D or N-D) are stored in a new `Cell.matrix` field. Built-in spreadsheet functions (SUM, AVG, MIN, MAX, COUNT, ABS, SQRT, INT) now accept ndarrays in addition to `Vec` and scalar inputs. Matrix cells display a shape summary (e.g. `[3x3]`, `[5]`) in the grid and show element previews in the status bar. Matrix multiplication (`@`), `np.linalg.inv`, `np.linalg.det`, and other numpy operations work across cell references. 0-D arrays are transparently collapsed to scalars. Deep copy on `Cell.copy_from()` and proper cleanup on `setcell()` / `clear()` prevent stale matrix state. Convergence detection in `recalc()` correctly compares ndarrays to avoid false circular-reference marks.

- **Code block validation** (`sandbox.validate_code()`): AST-based security validation for code blocks (multi-statement `exec` mode), applying the same checks as formula validation (dunder access, dangerous names/attributes) plus import blocking for disallowed modules.

- **Syntax-highlighted code preview on load**: The startup trust prompt now displays the file's code block with Pygments syntax highlighting before asking the user to approve. The prompt options were simplified to `[l]oad code`, `[s]kip code`, `[q]uit`.

- 77 new tests: DataFrame formula evaluation (creation, column access, describe, filtering, groupby, Series conversion, recalc stability), pandas load/save (CSV, TSV, JSON, round-trip, no-header mode, error handling), DataFrame display formatting, CSV import/export (basic, empty grid, NaN, labels/numbers, round-trip, error paths), search (labels, numbers, formula values, case-insensitive, next/prev/wrap), search indicator, clipboard (yank/paste single/range, style preservation, formula verbatim copy, undo, empty noop), sort (by column, descending, labels, mixed types, visual selection, undo, invalid column), visual selection blank/delete (range blank, partial, row/col delete, undo), `:pd` and `:csv` command dispatch. 504 tests total.

- 17 new numpy/matrix tests in `test_engine.py` covering basic ndarray formulas, identity matrices, cell references, matmul, linalg operations, 0-D scalar collapse, 1-D arrays, built-in function dispatch, cell display formatting, deep copy isolation, convergence stability, stale matrix cleanup, and circular matrix detection.

- 34 new sandbox tests in `test_sandbox.py` covering `validate_code()` for blocked imports, dunder access, dangerous names, and valid code acceptance.

### Changed

- **Sandbox enabled by default**: `GRIDCALC_SANDBOX` now defaults to enabled. Set `GRIDCALC_SANDBOX=0` to disable (previously required `=1` to enable).

- Added `numpy >= 1.24` and `pandas >= 2.0` as project dependencies. Added `types-Pygments` and `pandas-stubs` as dev dependencies for mypy.

## [0.1.1]

### Added

- **Security sandbox** (`gridcalc/sandbox.py`):

  - AST validation blocks dunder attribute access (`__class__`, `__subclasses__`, `__globals__`, etc.), dangerous names (`eval`, `exec`, `getattr`, `open`, `type`, etc.), and known internal attributes used in sandbox escape chains.

  - Module classification system: safe (numpy, scipy, etc.), side-effect (matplotlib, pandas), and blocked (os, subprocess, socket, pickle, etc.).

  - `load_modules()` imports approved third-party libraries into the formula eval namespace with standard aliases (numpy -> np, pandas -> pd, etc.).

  - Trust gate on file load: files containing code blocks or `requires` prompt the user before executing. Options: approve, formulas only, view code, cancel. Works in both curses (`:o` command) and plain terminal (startup).

  - `GRIDCALC_SANDBOX=1` env var or `sandbox = true` in config to enable checks. Off by default during development; tests run with sandbox enabled.

  - `Grid.jsoninspect()` extracts file metadata (cell/formula counts, code block preview, required modules, blocked module warnings) without executing.

  - `Grid.jsonload()` accepts an optional `LoadPolicy` controlling whether code blocks and modules are loaded.

  - See `docs/security-plan.md` for full threat model and architecture.

- **Configuration file** (`gridcalc/config.py`):

  - TOML-based config via `gridcalc.toml`.

  - Lookup order: `./gridcalc.toml` (CWD, project-local) then `$XDG_CONFIG_HOME/gridcalc/gridcalc.toml` (user-level, defaults to `~/.config/gridcalc/gridcalc.toml`). CWD overrides user config.

  - Settings: `editor` (default editor for `:e`, overridden by `EDITOR` env var), `sandbox` (enable security checks), `width` (default column width), `format` (default number format), `allowed_modules` (pre-approved modules for formulas).

  - See `gridcalc.toml.example` for all options.

- **Third-party module support**:

  - JSON file format extended with `"requires": ["numpy", ...]` field.

  - Modules listed in `allowed_modules` config or file `requires` are imported and injected into the formula eval namespace at startup/load.

  - Formulas can use library APIs directly: `=np.mean(A1:A10)`, `=decimal.Decimal('3.14')`, etc.

- **Circular reference detection**: `recalc()` now detects circular references via two strategies: oscillation detection (values that never stabilize across 100 iterations) and static self-reference detection (formula text containing its own cell name). Circular cells are marked as NaN/ERROR and tracked in `Grid._circular`. The TUI status bar shows "CIRC" instead of "ERR 0" when the cursor is on a circular cell.

- **Visual select mode**: Press `v` to enter visual selection. Arrow keys extend the selection from the anchor cell; selected cells are highlighted in magenta. Press `:` to enter command mode with the selection active. `:f <fmt>` applies formatting to all non-empty cells in the selection. ESC cancels. Range formatting is undoable.

- **Format picker dialog**: `:f` with no argument now opens a modal picker listing all format options (bold, underline, italic, dollar, percent, integer, comma, bar chart, left/right align, general, use global) with descriptions for each. Navigate with arrow keys + Enter, press a key directly, or type a Python format spec (e.g. `,.2f`).

- **Formula libs** (`gridcalc/libs/`): pluggable function libraries for the formula eval namespace. Libs are composable (multiple can be active at once), registered in `libs/__init__.py`, and loaded via `Grid.load_lib()`. Configurable via `libs = ["xlsx"]` in `gridcalc.toml` or `"libs": ["xlsx"]` in the JSON file.

- **xlsx lib** (`gridcalc/libs/xlsx.py`): Excel-compatible functions:

  - Logical: IF, AND, OR, NOT, IFERROR

  - Math: ROUND, ROUNDUP, ROUNDDOWN, MOD, POWER, SIGN

  - Aggregates: AVERAGE, MEDIAN, SUMPRODUCT, LARGE, SMALL

  - Conditional: SUMIF, COUNTIF, AVERAGEIF (with criteria strings like `">5"`, `"<=10"`, `"<>0"`, wildcard `"*"`)

  - Lookup: VLOOKUP, HLOOKUP, INDEX, MATCH

  - Text: CONCATENATE, CONCAT, LEFT, RIGHT, MID, LEN, TRIM, UPPER, LOWER, PROPER, SUBSTITUTE, REPT, EXACT

- **Project review** (`REVIEW.md`).

- **TUI tests** (`tests/test_tui.py`): 47 new tests for `UndoManager` (undo/redo, empty-to-populated transitions, stack limits, style preservation, grid and region undo), `cmdexec` command dispatcher (quit, blank, clear, width, insert/delete row/col, save, format, title commands, unknown commands), and visual-select range formatting (dollar, bold, fmtstr, percent, combined styles, empty-cell skipping, undo, interactive picker) using a mock stdscr.

- 256 new tests (376 total) covering sandbox validation, module classification, module loading, load policies, file inspection, config parsing, config lookup order, integration tests for blocked formulas, policy-aware loading, requires roundtrips, circular reference detection, undo/redo, command dispatch, visual select range formatting, and xlsx mode functions.

- Added `tomli >= 1.0` (conditional, Python < 3.11 only) for TOML config parsing. Python 3.11+ uses stdlib `tomllib`.

### Changed

- **Sparse grid storage**: `Grid` now stores cells in a flat `dict[(col, row) -> Cell]` instead of pre-allocating a 256x1024 array of 262,144 Cell objects. Only populated cells consume memory. A `_CellsProxy` compatibility layer preserves the `g.cells[c][r]` access pattern.

- **recalc() performance**: formula evaluation, cell value injection, and reference fixup now iterate only populated cells instead of scanning the full grid. Typical speedup is 100-200x for sparse sheets (test suite: 22s to 0.11s).

- **Insert/delete/swap row/col**: O(populated cells) via key remapping on the sparse dict, replacing O(NCOL * NROW) element-by-element shifting.

- **Undo/redo**: `save_grid` snapshots only populated cells. Grid-level undo restores via `clear_all()` + replay instead of full-grid iteration. Cell-level undo now records empty-cell state so undo correctly restores emptiness after edits.

- **Cell format type**: `Cell.fmt` changed from `int` (ord values like `ord("$")`) to `str` (`"$"`, `"%"`, `"I"`, etc., or `""` for none). Removes all `ord()`/`chr()` conversions in engine, TUI, and tests.

- **Comma format shorthand**: `:f ,` now formats as comma-thousands with zero decimal places (e.g. `1,234,567`) instead of the previous 6-decimal default. Explicit precision still works (`:f ,.2f` gives `1,234.50`).

- **File format version**: `jsonsave()` now writes `"version": 1` to output. `jsonload()` rejects files with a version higher than the current `FILE_VERSION`. Missing version is treated as 1 (backward compatible).

- **MAXCODE constant**: `cmd_edit` code block truncation now uses the `MAXCODE` constant (8192) instead of the magic expression `MAXIN * 32`.

- **Save deduplication**: `cmd_save` and `cmd_savequit` now share a single `_do_save()` helper for filename resolution, writing, and state update.

- **File inspection moved to sandbox**: `Grid.jsoninspect()` static method moved to `sandbox.inspect_file()`. It had zero Grid state access and only used sandbox types (`FileInfo`, `classify_module`). `engine.py` no longer imports `FileInfo` or `classify_module` -- its only sandbox dependency is `validate_formula` and `load_modules`.

- **Cell formatting moved to TUI**: `Grid.fmtcell()`, `fmt_float()`, and `_insert_commas()` moved from `engine.py` to `tui.py`. `fmtcell` is now a standalone function `fmtcell(cl, cw, global_fmt="")` -- a presentation concern that belongs alongside the display code, not the data model.

- `Grid.jsonload()` signature extended with optional `policy` parameter (backward compatible -- `None` trusts all, matching prior behavior).

- `Grid.jsonsave()` writes `requires` field when present.

- Formula evaluation in `recalc()` runs AST validation before `eval()` when sandbox is enabled.

- Editor command resolution: `EDITOR` env var > config `editor` > `"vi"`.

- Makefile `test` target sets `GRIDCALC_SANDBOX=1` so sandbox tests exercise real checks.

- **Strict mypy**: enabled `strict = true` in mypy config. Added type annotations to all functions, methods, and classes across engine.py, tui.py, config.py, and sandbox.py. Zero mypy errors under strict mode.

- **Renamed project**: pycalc -> gridcalc. Package directory, imports, config filename (`gridcalc.toml`), config paths (`~/.config/gridcalc/`), env var (`GRIDCALC_SANDBOX`), entry point, and all references updated.

## [0.1.0]

Initial release. Pure Python reimplementation of [pktcalc](https://github.com/sa/pktcalc).

### Changed (vs pktcalc)

- Replaced C + pocketpy with pure Python. No compiled dependencies.

- Formula evaluation uses Python's `eval()` directly instead of an embedded pocketpy interpreter. Same formula syntax, same semantics.

- JSON load/save uses Python's `json` module instead of pocketpy's JSON API.

- Build/run via `uv` instead of CMake.

### Preserved

- Full feature parity with pktcalc:

  - Curses TUI with identical keybindings and vim-style command line.

  - JSON file format (files are interchangeable between pktcalc and gridcalc).

  - Python formulas with cell references (`A1`, `$A$1`), range syntax (`A1:A10`), named ranges, and custom code blocks.

  - Vec type for element-wise array arithmetic.

  - Built-in spreadsheet functions: SUM, AVG, MIN, MAX, COUNT, ABS, SQRT, INT.

  - Preloaded math functions: sin, cos, tan, exp, log, floor, ceil, etc.

  - Cell formatting: bold, underline, italic, number formats ($, %, I, *, L, R, G, D), Python format specs (e.g. `,.2f`, `.1%`).

  - Row/column insert, delete, swap, move, and replicate with automatic reference adjustment (relative and absolute refs).

  - Undo/redo (Ctrl-Z / Ctrl-Y) with 64-entry stack.

  - Title row/column locking.

  - Cell point-mode during formula entry (arrow keys insert refs).

  - Color scheme: blue chrome, cyan gutter, green cursor, yellow locked cells, magenta marks, red errors, per-mode status colors.

- 120 pytest tests covering expressions, recalc, vectors, ranges, cell references, JSON round-trips, swap/fixrefs, insert/delete, replicate, formatting, styles, and boundary conditions.
