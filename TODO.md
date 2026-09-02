# TODO

Open tasks, ordered by priority within each section. Resolved items live in CHANGELOG.md.

## Direction

Excel-function parity is a race gridcalc cannot win and does not need to: Excel has ~480 functions and every spreadsheet user already owns it. What nothing else offers is **optimization with spreadsheet semantics in a terminal** -- `:opt` and `:goal` over a live grid, scriptable, workbook- persistent. Excel's Solver is a modal dialog with a famously unhelpful failure mode; PuLP and pyomo make you write the model in code with no spatial view of the data. That gap is the thing worth widening.

So: prefer work under **Optimization** below over work that closes an Excel-coverage gap, unless the coverage gap is blocking a real sheet. The parity items are kept because they are genuinely useful, not because they are the strategy.

## Optimization

- [x] Sensitivity analysis (`:opt sens`) -- shadow prices, reduced costs, RHS and objective ranging. See CHANGELOG.

- [x] Infeasibility diagnosis -- irreducible conflicting constraint set reported automatically on `INFEASIBLE`. See CHANGELOG.

- [x] Unboundedness diagnosis -- names the runaway variable on `UNBOUNDED`. See CHANGELOG. (The diagnosis re-solves per variable rather than reading an extreme ray, which no backend has exposed.)

- [x] Parametric RHS sweep (`:opt sweep`) -- re-solves across a range and flags where the marginal value changes. See CHANGELOG. Built on `solve(rhs_override=...)`, which is also usable directly.

- [x] Separable quadratic objectives -- squared decision variables solved via a tangent-envelope relaxation on the existing LP backend, no second solver. See CHANGELOG.

- [x] Migrated the solver backend from lp_solve to HiGHS -- MIT instead of LGPL, native convex QP (including cross terms), and a real infinity instead of a 1e30 sentinel. See CHANGELOG.

- [ ] **Verify the HiGHS build on Linux and Windows CI.** Validated on macOS/arm64 only. HiGHS is a much larger C++ tree than lp_solve; watch build time and wheel size. `highs_extras` must stay a static lib -- the shared build dlopens it at runtime, which will not work from inside a wheel.

- [ ] **Sensitivity for quadratic models.** Withheld today: a QP's duals do not carry the shadow-price reading the report describes. HiGHS does return them, so this is a question of deciding what they mean to a spreadsheet user, not of plumbing.

- [ ] **Integer + quadratic together.** HiGHS does not support integrality with a Hessian. Currently the combination is simply refused.

## Web frontend

The editable pywebview/React frontend (`gridcalc.web`). `docs/web.md` holds the full analysis and a "what has since landed" status section reconciling its P0-P3 roadmap with reality; this list is only what is still open, ordered by priority. The consent UI landed: `Api.inspect` / `pending_trust` disclose what a file would run, `TrustDialog` asks, and the answer becomes the `LoadPolicy` -- the same decision the curses prompt takes. An *unanswered* open is still formulas-only, which is the safe default, not an oversight.

- [ ] **Move row and column (`swaprow`/`swapcol`).** Insert and delete now ship in both frontends; reordering does not. The engine primitives are ready, so this is a `gridcalc/commands.py` entry (which both frontends then get) plus a client gesture -- dragging a header.

- [ ] **Migrate the remaining shareable commands into the registry.** `:width` is the interesting one: the TUI means a uniform width in character cells and the web view means pixels per column, so it needs a decision about what the shared command *is* before it can move. `:csv`/`:xlsx`/`:pd` could share their load/save bodies with the path prompt left to each frontend.

- [ ] **The code-block / formula-mode surface (`:e`, `:mode`).** The *loading* half is done -- `loader.load_workbook` takes a `LoadPolicy` and `TrustDialog` supplies it, so a HYBRID or PYTHON workbook's code runs once approved. What is still missing is *authoring*: no editor for the `code` block (`:e`) and no way to switch formula mode from the GUI, so those workbooks can be opened and read in the web view but not written there.

- [ ] **Accessibility, and validating the reason web was chosen.** `docs/gui.md` justified the web bet partly on IME/CJK input and accessibility, and neither claim has been tested in a real webview -- only asserted. The grid is absolutely-positioned `div`s with no `role="grid"`/`gridcell`/`aria-rowindex` and a single focusable container, so the assertion is currently unbacked by the implementation too. Add ARIA grid semantics, then verify CJK/IME input on each platform's real webview (the Playwright suite is Chromium -- a faithful proxy, not the production engine).

- [ ] **Full spreadsheet keyboard model.** Missing: PageUp/PageDown, Ctrl+Home/End, Ctrl+arrow (jump to data edge), End, Ctrl+A, Escape, shift+space / ctrl+space (row/column select), F4 (toggle absolute in the editor). Today only `Home` exists (`Grid.tsx`).

- [ ] **Light theme.** `styles.css` is a single dark `:root` with no `prefers-color-scheme` support, and a few hex values leak out of it into component props (`ChartDialog.tsx` hands literal colours to Recharts; `SweepDialog.tsx` already uses CSS variables, so that is the pattern to follow). A light-mode user currently gets a forced dark app.

- [ ] **Viewport fetch cost.** `viewport()` fires per scroll event, coalesced only by in-flight dedup (`Grid.tsx`). No debounce and no client-side block cache, so fast scrolling issues a round trip per frame, newly-scrolled rows stay blank until each returns, and scrolling back refetches from scratch. Not urgent in-process on a 256x1024 sheet; an LRU of fetched blocks is the cheap fix when it bites. `docs/web.md` §5e.

- [ ] **Distribution (P3).** Frozen, signed, double-clickable builds for macOS/Windows/Linux around pywebview plus the C++ extensions, and per- platform manual QA of clipboard/IME/rendering. `docs/web.md` §5b calls this the most underestimated cost in the plan; budget it as its own project, not a task. Only worth starting once the decision below is answered.

- [ ] **Open decision: does the web view replace the TUI as the default, or complement it?** (`docs/web.md` §7.) This gates how much of the parity work above is worth doing at all. If it complements -- the TUI stays the power-editing frontend and the web view is the visualize-and-solve companion -- then breadth stops mattering and distribution becomes the next real question instead.

## Performance

- [ ] **Range subscriber explosion (Phase E from `docs/topological.md`).** `SUM(A1:Z1000)` registers 26000 reverse-index entries. Replace with an interval representation (per-column interval tree, or aggregation nodes that fan out at change time). Defer until profiling shows large-range workloads as a hot spot.

- [ ] **Targeted C++ acceleration for measured hot spots.** A full C++ evaluator port (lexer + parser + tree walker + cell store + dep graph) is not justified by current benchmarks: topological recalc closed the gap that originally motivated it. Surgical edits on 10k-cell sheets are <0.1 ms; xlsxload of 5k cells is ~12 ms; long-chain edits are single-digit ms. A wholesale port would duplicate the function library in C++, complicate the HYBRID `py.*` gateway with three-way Python<->C++ bouncing, and slow development velocity (rebuild required for every formula-system change). If a real workload exposes a hot spot, C++ that single component (Vec arithmetic in `engine.py:87-129`, range materialization in `_expand_ranges`, or the closure BFS in `_recalc_topo`) -- a few hundred lines, not thousands. See git history for the original "Phase 3" entry if scope ever shifts.

## Refactoring & code quality

- [ ] **`Cell.ast` cache invalidates by text equality.** For very large sheets where many formulas share text, hashing the text would cut cache lookups; not a priority but worth measuring.

- [ ] **Remaining `libs/xlsx.py` Excel-fidelity gaps.** The lookup / criteria / conditional-aggregate audit sweep is done (see CHANGELOG). Left open, each gated on a missing primitive or genuinely ambiguous in Excel: numeric-vs-text criteria coercion (`COUNTIF({1,2,"3"}, 3)`); date-string criteria like `">1/1/2020"` (needs date-aware criteria parsing -- gated on the date-type system below); and `SUMIF`/`COUNTIF` with a `sum_range` shorter than the criteria range (Excel resizes from the top-left, which needs reference rather than materialised-`Vec` semantics -- now unblocked, since `OFFSET` brought the `Reference` type into the value system).

- [ ] **The aggregates take exactly one argument.** `SUM`, `MIN`, `MAX`, `COUNT` (`engine.py`) and `AVERAGE` (`libs/xlsx.py`) are all `def f(x)`, so `=SUM(A1:A3, B1:B3)` and `=SUM(A1, 5)` -- among the most common things anyone writes in a spreadsheet -- answer `#VALUE!` where Excel sums them. Excel takes up to 255 arguments and flattens ranges, values and nested arrays together; `AVERAGEA`/`MAXA`/`MINA` in the library are already variadic, so the shape to copy is in the tree. Found while validating the docs against the engine, not by a failing test: nothing in the suite calls an aggregate with two arguments, which is why it has stayed invisible. Not listed in `docs/reference/limitations.md` either -- add it there if it is not going to be fixed soon, since silence reads as support.

- [ ] **`deps` over-approximates a shadowed named range.** When a `LET` name shadows a real named range the range stays recorded as a dep -- safe, just an occasional extra recalc; tighten only if it ever matters. (`LAMBDA`, the higher-order helpers, and true spill all shipped -- see CHANGELOG.)

- [ ] **Date type system in xlsx I/O.** `_core.xlsx_read` collapses date serials into `XLValueType::Float`. Need to read the cell's number format to distinguish dates from numbers, and a per-cell `Cell.fmtstr` extension to render serials as formatted dates in the TUI.

## Features

- [ ] **3D range references (`Sheet1:Sheet3!A1:B2`).** Currently unsupported: `_expand_ranges` (engine.py:582) only recognises the `<ref>:<ref>` shape, so a sheet-span prefix passes through unexpanded and the formula evaluates to `nan`. Workaround in user files is to expand manually, e.g. `=SUM(Jan!B2:B3)+SUM(Feb!B2:B3)` instead of `=SUM(Jan:Feb!B2:B3)` (see `examples/example_multisheet.xlsx`). To implement: (1) extend `ref`/`refabs` (engine.py:529, 552) to recognise the `<sheet>:<sheet>!<cell>[:<cell>]` shape; (2) add a pre-pass (or branch in `_expand_ranges`) that enumerates sheets between the two named endpoints in workbook order and emits a `Vec([...])` over every (sheet, cell) pair; (3) decide rebind semantics on `move_sheet`/`rename_sheet` -- Excel binds 3D refs to sheet *position* between the endpoints, so reordering changes which sheets are summed, while renaming an endpoint should rewrite the formula text the same way `_rewrite_sheet_prefix` (engine.py:731) handles single-sheet refs; (4) extend dependency tracking so cells in the spanned sheets register as subscribers, and a `move_sheet`/`add_sheet` between the endpoints invalidates the cached recalc.

- [ ] **TUI keybindings system -- v2 generalisations.** All five contexts are wired (`grid`, `entry`, `visual`, `cmdline`, `search`) with curated action vocabularies; see `docs/keybindings.md`. Outstanding gaps for a future iteration: (a) **Removing hardcoded defaults.** `[keys.<ctx>] cancel = []` currently does *not* unbind Esc, because the hardcoded fallback chain still matches `ch == 27`. To make unbind work, the hardcoded chain has to migrate fully into `DEFAULT_KEYMAP` and the contexts must dispatch only via the action lookup. Mechanical but tedious. (b) **Bind-to-`:command`.** The action vocabulary is fixed at module load time. If users want `[keys.grid] save = [...]` where "save" runs `:w`, the schema has to grow a way to carry the command text alongside the key spec, and an `exec_command`-style action that takes parameters. Out of scope until someone asks. (c) **Pick-mode actions in entry.** The `KEY_UP`/`KEY_DOWN` cursor-pick sub-mode in `entry` is too tangled with local state to expose as actions today. Refactor it to a small state machine before binding it.

- [ ] **xlsx interop level (c) for HYBRID and PYTHON mode.** EXCEL mode round-trips formulas today: `Grid.xlsxsave` emits kind `'f'` with the formula text and a cached value, and `_core.xlsx_write` sets `cell.formula()`. The remaining gap is the other two modes, whose syntax (`**`, list comprehensions, `py.*`) is not Excel grammar -- they still export values. Closing it needs a serialiser from the gridcalc AST to Excel-grammar text, and is only worth it for the subset that has an Excel equivalent.

- [ ] **Date/time and styled-cell coverage in `_core` xlsx I/O.** `XLValueType` does not distinguish date serials from floats; styles and number formats are not read or written. openpyxl-backed gridcalc did not handle these either, so this is a known gap to plan, not a regression.

- [ ] **Migration tool `gridcalc migrate file.json`.** Attempts to upgrade a LEGACY file to HYBRID by reparsing each formula with the EXCEL grammar and reporting the unparseable ones.

- [ ] **Visual-select operations.** Extend beyond `:f` -- support `:b` (blank range), `:dr`/`:dc` (delete selected rows/cols), `:r` (replicate into selection), copy/paste within selection.

- [ ] **System clipboard -- follow-ups.** Core integration is done (see CHANGELOG). Remaining: full CSV-style quoting for cells containing tabs/newlines (currently sanitised to spaces), and verifying the Windows/Linux backends (`wl-clipboard`/`xclip`/`xsel`, `clip`/ `Get-Clipboard`) on real hardware -- developed on macOS against a fake backend.

- [ ] **Mouse support** (curses mouse events for cell selection and scrolling).

- [ ] **Plugin interface.** Allow third-party packages to register custom functions, commands, and cell formats via entry points or a plugin API.

## Security

`docs/dev/sandbox-isolation.md` holds the analysis behind both items, including why isolation is not first.

- [ ] **Curated module facade.** Approved workbook code is handed whole module objects, so `np.savetxt('/anywhere', ...)` writes any path with the sandbox on. Expose a facade (`np.array`, `np.mean`, `np.linalg.solve`) rather than the module. Portable, needs no IPC, and removes the severe outcome -- arbitrary file read and write -- at a fraction of the cost of isolation. Ongoing cost is curation: each newly approved module needs a facade, and an omission is silent.

- [ ] **Process isolation for PYTHON-mode recalc.** Only worth building if running untrusted workbook code becomes a supported feature; `LoadPolicy.formulas_only()` is the current answer everywhere but the TUI trust prompt. Buys a resource ceiling on every platform but filesystem confinement mainly on Linux. HYBRID's `py.*` gateway is a separate decision -- it is called mid-expression from the evaluator in the parent.

## Documentation & infrastructure

- [ ] **Build the docs site in CI.** The site itself is done (`mkdocs.yml`, 30+ pages under `docs/`, `make docs` / `docs-serve` / `docs-deploy`), and publishing stays a deliberate manual `make docs-deploy` -- the Makefile says why. The gap is that `ci.yml` never runs `mkdocs build --strict`, so a broken cross-reference between pages lands on `main` and is only found by whoever next deploys. Adding the `docs` group and one `make docs` step to CI is the whole fix; it does not commit or push anything.

- [ ] **EXCEL grammar reference page.** Operators, precedence, error values, the function library, mode semantics. Lives in the docs site once it exists.
