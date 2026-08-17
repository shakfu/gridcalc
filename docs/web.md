# Maturing the web frontend: spike -> product

Status: analysis / proposal. The web frontend (`gridcalc.web`) is an
experimental spike (`docs/gui.md`); this doc lays out what "product" would
actually require, the decisions that gate it, and a phased path. It is a plan
to argue with, not a committed roadmap.

## What has since landed

The body below is unchanged from when it was written; this section records
where the work actually got to, so the two do not silently diverge.

- **P0 is done.** The client is a real Vite/React/TypeScript app under a lint,
  type-check and test gate (`make web-qa`, now part of `make qa`), not the
  inline `_HTML` string Section 5c describes. There is an error/notification
  channel (Section 5d), plus a React error boundary and an
  `unhandledrejection` handler. The `NamedRange` structural-edit bug is fixed
  and per-sheet view state is kept across a tab switch; constraining `save`
  paths (Section 4) is **still open**.
- **P1 is done and then some.** `:opt`/`:goal` reached the GUI, and beyond the
  original sketch: persisted named models (the `:opt def/run/list/undef`
  surface, which Appendix A explicitly deferred as "not core P1"), a
  non-solving `infer_model_spec` so a model can be read off a block and
  corrected before it runs, a parametric sweep plotted with breakpoints marked,
  and a **grid annotation layer** that paints binding/slack constraints and
  shadow prices onto the sheet itself. Charts use Recharts, as Section 5c
  anticipated the renderer-agnostic `chart_data` shape would allow.
- **P2 is partial.** Formula bar, per-cell and global number formats, styles,
  and a status bar with selection aggregates exist. Row/column insert-delete,
  sheet add/rename/delete/reorder, persisted per-column widths, find, named
  ranges, sort, formula-mode switching, freeze panes, and a Ctrl-K command
  palette now ship too -- the last several came free with the shared command
  registry (`gridcalc/commands.py`), which both frontends dispatch by name.
- **P3 is untouched.** No frozen builds, no per-platform QA, no signing. The
  IME/CJK and accessibility claims from Section 5e remain unvalidated in a real
  webview; the grid still has no ARIA grid semantics.
- **Security is unchanged and deliberately so**: formulas-only, Section 5a
  option 1. No trust flow, no `load_code=True`.

## 1. The premise, challenged

"Polished product" is underspecified, and the ambiguity is not cosmetic -- it
changes almost every downstream decision. Two forks dominate:

- **Audience / deployment.** A single-user *desktop* app (pywebview shell,
  engine in-process) and a *shareable, multi-user web* app are different
  products with different security models, packaging, and persistence stories.
  `docs/gui.md` already flagged this as an open question; it must be closed
  before "product" means anything. **Recommendation: commit to single-user
  desktop.** It is what the pywebview choice already implies (no server, no
  port, in-process `js_api`), it sidesteps the multi-tenant security problem
  (Section 5a), and it matches a spreadsheet-optimization tool used by one
  analyst at a time. The multi-user web path is a *different* product; defer it
  explicitly rather than drift toward it.

- **Scope: TUI parity vs deliberately narrower.** The reflex is "make the web
  view do everything the TUI does." Challenge it. gridcalc's stated
  differentiator (`TODO.md`) is *optimization with spreadsheet semantics* --
  `:opt`/`:goal` over a live grid -- not commodity spreadsheet editing that
  Excel already owns. The web `Api` today exposes **none** of the optimization
  surface. So the highest-value gap is not prettier cell editing; it is
  bringing the differentiator to the GUI. A "polished" web gridcalc that can
  edit cells and draw bar charts but cannot run `:opt` is a *worse* gridcalc
  than the terminal one.

**Alternative framing (worth a real look):** the web view does not have to be
the product. It can be a deliberately-scoped *visual companion* -- open,
browse, light-edit, and above all *visualize and solve* (charts + `:opt`
results a terminal renders poorly) -- while the curses TUI stays the
power-editing surface. Under this framing "polish" means depth on charts and
optimization, not breadth across every `:` command. This is cheaper, ships
sooner, and plays to the browser's actual strength (rendering) rather than
re-implementing modal editing the TUI already does well.

## 2. Current state: what is solid, what is spike-grade

Solid, keep:

- **The `Api` boundary.** All engine<->view logic is a plain-Python class with
  no `webview` import (`web/__init__.py`), unit-tested without a display
  (`tests/test_web.py`). This is the right architecture and scales.
- **Headless regression testing of the JS/DOM.** The same page is driven in
  Chromium with the bridge mocked from real `Api` output
  (`tests/integration/test_web_playwright.py`). Rare and valuable for a webview
  app.
- **Shared formatting.** Cells format identically to the TUI via
  `display.cell_text` / `cell_right_aligned`. No divergence risk.
- **Virtualized rendering.** Only viewport cells enter the DOM, so the full
  256x1024 sheet scrolls without 260k nodes.

Spike-grade, must change:

- **A ~500-line inline HTML/JS string** (`_HTML` in `web/__init__.py`). No
  lint, no type-check, no module boundaries, no source maps -- invisible to
  every quality gate that guards the Python. This is the single biggest
  maintainability liability (Section 5c).
- **Security punted.** `open_file` hardcodes `LoadPolicy.formulas_only()`
  (`loader.py`); code blocks are never run, no trust UI, no `inspect_file`
  disclosure. Fine for a spike, a product-defining hole otherwise (Section 5a).
- **No error surface.** `Api` methods return `{ok: false}` shapes the client
  largely ignores; a failed save/open/recalc has no user-visible channel
  beyond an ad-hoc `flashSave`.
- **One hard-coded demo, no chrome.** No menu bar, no About, no keyboard-help,
  no recent-files, no window-title lifecycle beyond a best-effort retitle.

## 3. Feature gap: TUI vs web `Api`

Engine support already exists for nearly all of this; the gap is `Api` surface
+ client UI, not core work. Legend: [A] needs `Api` method, [C] needs client
UI, [E] needs engine/new work.

**The shared-command rows are no longer maintained by hand.** Commands in
`gridcalc/commands.py` are dispatched by name from both frontends, and
`tests/test_docs_conformance.py` fails if one of them is shadowed in the TUI or
dropped by the web bridge. What remains below is the part that is *not* shared:
per-frontend interaction, and capabilities one side simply does not have.

| TUI capability | Web today | Gap |
|---|---|---|
| Cell edit, nav, selection, copy/cut/paste, fill | Yes | -- |
| Undo/redo, save, open, paste-in | Yes | -- |
| Per-cell + global number format / style | Yes | -- |
| Row/column header selection | Yes | -- |
| Search (`/`, `n`, `N`) | Yes (find bar) | -- |
| Sheet add/del/rename/move | Yes | -- |
| Column width | Yes, per-column pixels | diverges from `:width` (uniform chars) by design |
| `:opt` LP/MIP, `:goal`, sensitivity, sweep | Yes | -- |
| Bar chart from range | Yes (inline SVG) | depth only |
| Shared registry (`:b :f :gf :ir :ic :dr :dc :name :names :unname :sort :mode :title :recalc`) | Yes, by name | enforced by test |
| Replicate (`replicatecell`) beyond fill down/right | Partial (fill only) | `[A]` `[C]` |
| Move row/column (`swaprow`/`swapcol`) | No | registry entry + drag gesture |
| Object editor for Vec/ndarray/DataFrame cells (`tui/objedit.py`) | No | `[A]` `[C]` larger |
| xlsx / csv / pandas import-export | save by ext; open JSON/xlsx/csv | `[A]` pandas, dialogs |
| Code block edit (`:e`) + trust prompt | No | `[E-security]` gated on 5a |

Takeaway: two clusters carry most of the product value -- **optimization
(`:opt`/`:goal`)** and **format/structure editing (rows, cols, styles, named
ranges)**. Both are almost entirely "wire an `Api` method to existing engine
calls + build client UI." The engine is ready.

## 4. Correctness gaps found while scoping (fix regardless of roadmap)

These are latent bugs the spike has not tripped yet; a product will.

- **`save` trusts a client-supplied path** (`Api.save`, web/__init__.py). In
  the in-process desktop model the "client" is local so the blast radius is
  small, but any move toward a served frontend makes this arbitrary-path write.
  Constrain now while it is cheap.
- **Shared, persistent eval globals** (`_eval_globals`, exec into `g` on
  PYTHON recalc). Single-process desktop is fine; it is a hard blocker for any
  multi-tenant path -- another reason to decide Section 1 early.

## 5. The hard problems (what actually separates spike from product)

### 5a. Security / trust model -- the decisive one

The spike is safe precisely because it does nothing: `formulas_only()` never
stores or runs a workbook's `code` block, so cells depending on it show errors
by design. A product has to choose, and the choice is load-bearing:

1. **Stay formulas-only forever.** Simplest, honestly safe. Cost: PYTHON and
   HYBRID workbooks are second-class in the GUI -- their computed cells are
   dead. Defensible if the web view is the "safe viewer/solver" and code-block
   authoring stays in the TUI.
2. **Full trust flow, ported.** Reproduce `inspect_file` -> `FileInfo`
   disclosure (blocked / side-effect modules, code preview) -> a consent dialog
   equivalent to `tui/commands.py trust_prompt` -> `LoadPolicy(load_code=True,
   ...)`. This is real product work and, critically, `validate_code`
   (sandbox.py) is a *denylist, not a container* -- once it passes, code runs
   with the process's full privileges. On the desktop that is the same trust
   the TUI already asks for, so it is acceptable *with an honest consent UI*.
   It is not acceptable on a served/multi-user deployment without OS-level
   isolation (subprocess, container, seccomp), which is out of scope for the
   recommended desktop product.

**Recommendation:** ship P0/P1 as formulas-only (option 1), then add option 2's
consent flow as an explicit, well-labelled feature -- not silently. Never wire
`load_code=True` without a trust dialog. This is the one area where "polish"
means *restraint*, not features.

### 5b. Distribution / packaging

A pywebview app is not `pip install` for end users. Product means a
double-clickable artifact:

- **Bundler:** PyInstaller or Briefcase around pywebview + the C++ extensions
  (`_core`, the HiGHS `_opt`). The native extensions and platform webview
  (WebKit / WebView2 / GTK-WebKit) are the risk; test the frozen build on all
  three OSes, not just `uv run`.
- **Platform webview parity.** macOS WKWebView, Windows WebView2 (Edge/Chromium
  runtime dependency), Linux WebKitGTK render and expose `navigator.clipboard`
  differently. The Playwright suite is *Chromium*, a faithful proxy, not the
  production engine -- clipboard, IME, and CSS edge cases need a manual pass per
  platform.
- **Signing / notarization** (macOS Gatekeeper, Windows SmartScreen) if
  distributed beyond yourself. This alone can dominate the effort budget and is
  a reason the "personal tool" audience is materially cheaper.

### 5c. Client architecture

The inline `_HTML` string was right for a spike and is wrong for a product:

- **Extract** the JS/CSS to real files (still framework-free, still no build
  step to start) so `eslint`/`prettier`/type-checking (JSDoc or a light TS
  pass) can guard it the way `ruff`/`mypy` guard the Python.
- **Decide on a build step deliberately.** Framework-free hand-rolled DOM is
  fine and dependency-light today. It gets painful at "object editor, dialogs,
  chart library, i18n." A small bundler (esbuild) or a minimal reactive layer
  (Preact/lit) is a reversible bet; a full SPA framework is probably
  over-scoped for a single-window desktop tool.
- **A real charting library** (Plotly/ECharts) replaces the inline SVG. `Api.chart_data`
  already returns a renderer-agnostic `{title, labels, series}` shape, so this
  is a client-only swap -- the deliberate seam pays off here.
- **A real data-grid** only if the hand-rolled virtualized grid gets painful
  (frozen panes beyond row/col headers, cell merging, rich in-cell widgets).
  Do not adopt one preemptively.

### 5d. UX chrome and error handling

Product table stakes the spike lacks: a menu/command surface (open, save,
save-as, recent files, About, keyboard-shortcut help), a real notification /
error channel (not just the save flash), a formula bar showing the active
cell's source, cell-format and named-range dialogs, a status line
(mode, selection stats), and window-title/dirty-state lifecycle. A discoverable
command palette (Ctrl-K) mapping the TUI's `:` commands is a natural bridge --
it reuses the mental model without forcing modal `:` typing into a GUI.

### 5e. Performance, accessibility, i18n

- **Perf at scale.** Virtualized DOM is fine; the cost is `viewport()`
  round-trips per scroll frame across the bridge. Profile with a full sheet and
  fast scroll; batch/debounce if the bridge is the bottleneck.
- **The reason web was chosen was IME/CJK + accessibility** (`docs/gui.md`).
  That claim is still *unvalidated* in the actual pywebview window -- only
  asserted. A product must prove CJK/IME input and basic screen-reader/keyboard
  accessibility on each platform's real webview, or the central justification
  for the web bet is unconfirmed.

## 6. Recommended path

Assumes the two recommended decisions: **single-user desktop**, and **lead with
the differentiator (optimization + visualization), not blanket TUI parity.**

- **P0 -- Harden the spike (no new features).** Extract JS/CSS to files under a
  lint/format/type gate. Add an error/notification channel. Constrain `save`
  paths. Fix the `NamedRange` structural-edit bug (Section 4). Keep
  formulas-only. Outcome: the current feature set becomes maintainable and
  honest.
- **P1 -- The differentiator.** Wire `Api.solve` / `Api.goal` to `opt.solve` /
  `goalseek.seek`; build the client UI to define a model from a selection
  (`opt.infer_model`), run it, and render results + sensitivity. Swap inline
  SVG for a real charting library. Outcome: the web view does the thing that
  makes gridcalc gridcalc, better than the terminal can.
- **P2 -- Editing parity essentials.** Row/col insert/delete/move, per-cell and
  global number format + styles, named-range management, search, sheet
  management, a formula bar, and a command palette over the `:` set. Outcome:
  the web view is a credible primary editor, not just a viewer.
- **P3 -- Product distribution.** Frozen, signed, double-clickable builds on
  macOS/Windows/Linux; per-platform manual QA of clipboard/IME/accessibility;
  About/help/recent-files. Optionally, the gated code-block trust flow
  (Section 5a option 2). Outcome: shippable to someone who is not you.

Ordering rationale: P1 before P2 deliberately. Editing polish is commodity;
optimization-in-a-GUI is the moat. If the budget runs out after P1, you still
have something no other tool offers. If it runs out after P2-of-parity-first,
you have a mediocre Excel.

## 7. Open decisions (need your call)

1. **Audience:** personal desktop tool, or eventually shareable/distributed?
   (Drives Section 5a and 5b, and how much P3 costs.)
2. **Scope:** TUI feature-parity, or the narrower "visualize + solve companion"
   framing from Section 1? (Drives whether P2 is breadth or depth.)
3. **Code blocks in the GUI:** never (formulas-only forever), or behind an
   explicit ported trust flow? (Security posture.)
4. **Client stack:** stay hand-rolled framework-free, or adopt a small build
   step / reactive layer at P2 when dialogs and the object editor arrive?
5. **Does the web view replace the TUI as the default, or complement it?** If
   complement, parity matters less and the companion framing wins.

## 8. Effort / risk summary

- **Lowest-risk, highest-value first move:** P1 optimization wiring. Engine is
  ready (`opt.solve`, `goalseek.seek`); it is `Api` + client UI, and it is the
  differentiator.
- **Most underestimated cost:** P3 distribution (native extensions + three
  platform webviews + signing). Budget it as its own project.
- **Biggest latent trap:** the security fork (5a). Cheap to keep closed
  (formulas-only), expensive and dangerous to open carelessly. Decide
  explicitly; never let `load_code` creep in silently.
- **Cheapest thing that most improves maintainability:** extracting `_HTML` and
  putting the client under a quality gate (P0).

---

Want more depth on any section -- a packaging spike plan or a security-consent
UI design -- say which and I will expand it. The P1 optimization endpoints are
sketched in Appendix A.

## Appendix A -- P1 optimization `Api` endpoints (sketch)

The differentiator wiring from Section 6 (P1). The engine is ready
(`opt.solve`, `opt.sweep`, `opt.infer_model`, `goalseek.seek`); this is `Api`
surface + coordinate translation, plus one small shared refactor.

### Design rules

- **A1 in, A1 out.** The client already computes `selRef()`; never push raw
  coords across the bridge. `opt`/`goalseek` use `CellKey = (col, row)` while
  the web `Api` is `(r, c)`/A1 -- translate at the boundary, one place.
- **Errors become data.** Catch `OptError` (with `NotLinear`/`NotQuadratic`
  subclasses) and `GoalSeekError` -> `{ok: false, error}`; the messages are
  written to be user-facing.
- **Applied solves are undo-wrapped.** `opt.solve(apply=True)` overwrites
  decision cells and recalcs dependents; `goalseek.seek` overwrites the var
  cell. Snapshot first; drop the snapshot when nothing was written.
- **No `Infinity` in JSON.** Ranging bounds (`obj_from/till`, `rhs_from/till`)
  are legitimately `+-inf`; JSON has no such literal and the bridge chokes.
  Map non-finite -> `null` (client renders "inf").
- **Reuse the engine's spec parsers, not the TUI's** -- the `Api` must not
  import `tui`.

### Prerequisite refactor (same pattern as display/loader/undo)

Promote `_parse_cells` / `_parse_bounds` / `_parse_bound_value` from
`tui/solve.py` down to `opt.py` as public `parse_cells` / `parse_bounds` (with
`_parse_bound_value` a module helper); `tui/solve.py` re-imports them under the
old private names so existing TUI callers and `gridcalc.tui` re-exports keep
working. Add one helper to `UndoManager`:

```python
def discard_last(self) -> None:
    """Drop the most recent snapshot when the mutation it guarded didn't happen."""
    if self.undo_stack:
        self.undo_stack.pop()
```

### Endpoints

Coordinate/serialization helpers: `_key(a1) -> (c, r)` (rejecting trailing
garbage), `_a1((c, r)) -> "B4"`, `_num(x)` (non-finite -> None).

- `solve_selection(r0, c0, r1, c1, sense="max")` -- `opt.infer_model` over the
  selection, then solve with sensitivity + diagnostics on. Mirrors `:opt
  max`/`:opt min` over a visual selection.
- `solve_model(spec)` -- explicit A1 model:
  `{sense, objective:'B2', vars:'A2:A3', constraints:'C2:C4', bounds?, integers?,
  binaries?, sensitivity?, diagnose?, apply?}`.
- `goal_seek(formula_ref, target, var_ref, lo?, hi?, apply?)` -- `goalseek.seek`.
- `opt_sweep(spec)` -- parametric RHS sweep (`opt.sweep`); never mutates the
  sheet, so no undo snapshot.

All applied paths route through a shared `_run_solve` that snapshots, calls
`opt.solve`, and on `OptError` or a non-applied result (INFEASIBLE/UNBOUNDED)
calls `discard_last`. Results serialize through `_solve_json` (CellKeys ->
A1 strings, ranging floats through `_num`).

### Client-facing return contract

```
SolveResponse =
  { ok: true, status: "OPTIMAL"|"INFEASIBLE"|"UNBOUNDED"|"SUBOPTIMAL",
    optimal: bool, objective: number|null,
    values: {A1: number},            // already written to the sheet
    applied: bool, quadratic: bool,
    sensitivity?: { variables: [...], constraints: [...] },  // absent for MIPs
    conflict?: [A1], unbounded?: [A1] }
  | { ok: false, error: string }
```

### Decisions carried into implementation

- `apply=True` mutates the sheet -- the UI must make a solve feel like an
  action, not a preview (`apply:false` gives a dry run for `solve_model`).
- Snapshot/redo caveat: `save_grid` clears the redo stack, so a *failed*
  applied solve still wipes redo after `discard_last`. Acceptable; tighten by
  saving/restoring the redo stack in `discard_last` if it matters.
- Sensitivity is `None` for MIPs by design (integer duals mislead) -- the
  client renders "no sensitivity for integer models," not an empty table.
- The web view renders the returned `sensitivity` object in a panel rather than
  writing it into cells (the TUI's `:opt sens into <cell>`); grid write-back can
  be an opt-in later.
- Persisted models (`grid.models: dict[str, OptModel]`, the `:opt def/run/list`
  path) are a natural extension -- `list_models`/`run_model`/`save_model` over
  `OptModel.to_json`/`from_json` -- but not core P1.
