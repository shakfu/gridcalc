# GUI direction: analysis of alternatives

## Goal

Experiment with a graphical frontend to move beyond the curses TUI, with usability, charts, and data visualization as the motivating wins. This document analyzes the realistic options against gridcalc's actual architecture, recommends an order to try them in, and records what each one would and would not buy. It is an analysis, not a commitment.

## What the architecture already gives us

The expensive precondition for a second frontend is already paid:

- **The engine is a headless library.** `Grid`/`Sheet`/`Cell`, the formula evaluator, and both recalc engines have no view dependency, and `tests/test_architecture.py` *enforces* that core modules never import `curses` or `gridcalc.tui` -- the dependency runs one way, checked in CI. Any GUI is therefore **additive**: a new view over the same `Grid`, not a rewrite.

- **Render-from-state is cheap.** `recalc` runs only on mutation, not per frame. A frontend redrawing at 60 fps just *reads* `cl.val` / `cl.sval` / `cl.err` for the visible cells; it never recomputes. This suits an immediate-mode loop but is equally fine for a retained view.

- **Interaction state already lives in the app, not the toolkit.** The cursor, selection, vi-style modes, and undo are gridcalc's own state, not curses widgets. A GUI inherits that model regardless of paradigm.

Two frictions the current layout imposes on *any* non-curses frontend:

- **Display formatting is trapped under `tui/`.** `tui/format.py` is pure (`fmtcell`, `cell_clip_value`, number-format handling) and curses-free in itself, but importing it pulls `tui/__init__.py`, which imports `curses`. A GUI cannot reuse it as-is. This wants extraction (see Prerequisite).

- **Zero-runtime-dependency ethos.** The core install has no third-party runtime deps (numpy/pandas are optional extras). Every GUI option adds a heavy dependency; the containment strategy is an optional extra (`pip install gridcalc[gui]`), keeping the terminal build lean.

- **C++ extensions pin us to CPython.** `_core` (OpenXLSX) and `_opt` (HiGHS) are nanobind C++ modules. This rules out running the engine *in the browser* via Pyodide/WASM without an emscripten rebuild of both vendored libraries -- a large, separate effort. It does **not** affect any option that keeps the engine on a real CPython process.

## The alternatives

### 1. Dear ImGui, immediate mode (`imgui-bundle`)

The app rebuilds the UI each frame from `Grid` state; a table with a list clipper draws only visible rows.

- **Fit:** philosophically the closest. "You own the state, re-render from it each frame" is already how the TUI operates, so there is no binding layer and no model/view impedance.

- **First prototype:** lowest cost. One dependency, one script, direct `import gridcalc`, `imgui.begin_table` + `ListClipper`. ~100 lines to a scrollable read-only 256x1024 grid.

- **Charts (the goal):** strong. `imgui-bundle` **bundles ImPlot** -- GPU, real-time, interactive plots in the same tool. The chart data we already *import from xlsx but currently ignore* could actually render.

- **The hard spreadsheet UX -- weakest here.** Text editing with a caret, IME for CJK/accented input (which the xlsx corpus proves we handle in the data), selection rectangles, and focus are inherently *retained* per-widget state, exactly what immediate mode does not manage. The standard workaround ("only the active cell is a real `InputText`; everything else is drawn text") works but means hand-rolling editing and selection semantics.

- **Accessibility:** poor. Custom-drawn; no screen-reader story.

- **Deps/distribution:** heavy native stack (OpenGL + GLFW/SDL). Needs a display, so no headless/CI runs of the window. Contained as a `[gui]` extra.

- **Testability:** `imgui-bundle` exposes the ImGui Test Engine, and a null backend allows smoke tests, but it is a different world from the PTY harness.

- **Ceiling:** high for a bespoke, fast, chart-heavy *personal* tool; low for "feels like a native, accessible office app."

### 2. Qt model/view (`PySide6`)

A `QAbstractTableModel` adapter exposes `Grid` to a `QTableView`.

- **Fit:** the best fit *for a spreadsheet specifically*. The model/view pattern maps directly onto a headless grid: a ~100-150 line adapter (`data()`, `rowCount()`, `columnCount()`, `setData()`, header roles) and the view provides virtualized scrolling, in-place editing, selection, clipboard, IME, and accessibility **for free**.

- **First prototype:** moderate. More concepts up front (model roles, delegates) than the imgui script, but the payoff is that the hard UX is solved by the framework rather than by us.

- **Charts:** QtCharts, or embed `pyqtgraph`/matplotlib. Good for static/interactive charts; heavier than ImPlot for real-time streaming (not a spreadsheet concern).

- **The hard UX:** best in class -- editing, IME, selection, a11y, and native clipboard are all framework-provided.

- **Deps/distribution:** heaviest footprint (Qt is ~100+ MB), but mature wheels and LGPL (`PySide6`). Contained as a `[gui]` extra.

- **Testability:** `pytest-qt` / `QTest` drive widgets in-process; decent.

- **Ceiling:** highest for a "real desktop spreadsheet."

### 3. Web: local server + browser frontend

The engine runs server-side (reused verbatim, C++ extensions and all); the browser is a pure view over a JSON viewport protocol.

- **Fit:** clean separation, but introduces a **network/serialization boundary** and a **second language/toolchain**. A viewport request returns the visible cell rectangle; edits POST back and trigger `recalc`.

- **First prototype:** highest cost of the interactive options -- server (FastAPI/Flask) + a data protocol + a grid component. The grid itself is not free in the browser either; a real one uses a canvas data-grid (Glide Data Grid, ag-Grid, Handsontable) or is hand-rolled.

- **Charts/viz (the goal):** the **strongest ecosystem** -- D3, Plotly, ECharts, Observable. Also the only option that is inherently *shareable* and *embeddable*.

- **The hard UX:** the browser handles IME, accessibility, and text natively; grid editing comes from the chosen JS grid library.

- **Deps/distribution:** engine stays on CPython (extensions intact); the frontend is an npm/JS stack. Ships as "run a local server, open a browser," or wrapped as a desktop app via `pywebview`/Tauri.

- **Testability:** Playwright/Cypress for the UI; ordinary API tests for the server.

- **Ceiling:** highest for sharing, collaboration, embedding, and visualization -- and the **most surface area**, being a two-stack, two-language system.

### 4. Web in the browser via WASM/Pyodide -- rejected (for now)

Running the *engine itself* in the browser is blocked: `_core` (OpenXLSX) and `_opt` (HiGHS) are C++ extensions with no Pyodide build. Getting there means emscripten-compiling both vendored libraries, or shipping degraded pure-Python fallbacks that lose xlsx and optimization. Not worth it against the server-backed web option, which reuses the extensions unchanged.

### 5. Terminal graphics (Kitty / iTerm image protocol, sixel) -- complementary

Not a "break free of the TUI" answer, but the cheapest way to get the *one* thing the TUI structurally cannot do: render a chart or image inline. Render a plot to PNG (matplotlib) and emit it via the terminal's graphics protocol.

- **Fit:** keeps the "terminal spreadsheet" identity intact.

- **Cost:** low-moderate; protocol detection + PNG emission. Does nothing for grid usability -- only visualization.

- **Role:** a complementary quick win for charts, and a hedge if the GUI push stalls; not a substitute for a real GUI.

## Prerequisite for options 1-3: a frontend-neutral display layer

Before any non-curses view, extract the pure display logic out of `tui/`:

- Move `fmtcell` / `cell_clip_value` / number-format handling into a package-level `gridcalc/display.py` (or similar) that imports only the engine, never `curses`.

- Extend `tests/test_architecture.py` to keep that module curses-free, the same way the core is guarded today.

- Decide what else in `tui/` is genuinely frontend-neutral. Selection and undo are arguably engine-adjacent and reusable; input handling and the render loop are frontend-specific and should stay put.

This is small, unblocks all three GUI paths, and is worth doing first regardless of which frontend wins.

## Decision matrix

Scores are relative (`+` weak ... `+++` strong); "hard UX" = editing, IME, selection, accessibility.

| Option | First-prototype cost | Reuses engine directly | Hard UX | Charts / viz | Deps / distribution | Ceiling |
|---|---|---|---|---|---|---|
| ImGui (`imgui-bundle`) | lowest | yes (in-process) | + (hand-rolled) | +++ (ImPlot bundled) | heavy GL, `[gui]` extra | bespoke personal tool |
| Qt (`PySide6`) | moderate | yes (in-process) | +++ (framework) | ++ (QtCharts/pyqtgraph) | heaviest, mature wheels | real desktop app |
| Web (server + JS) | highest | via JSON boundary | +++ (browser + grid lib) | +++ (D3/Plotly/ECharts) | two stacks; shareable | sharing / collaboration |
| WASM/Pyodide | n/a | blocked by C++ ext | -- | -- | -- | rejected for now |
| Terminal graphics | low | yes | n/a (viz only) | ++ (static PNG) | none new | complementary |

## Recommendation

1. **Do the display-layer extraction first** (Prerequisite). Small, and it unblocks everything.

2. **Start with the ImGui read-only grid** as the immediate experiment. It is the cheapest way to answer the two questions that actually decide the direction -- *large-grid performance with the clipper* and *IME/CJK input* -- and it serves the charts goal directly through ImPlot. Read-only first; navigation and one editable cell next.

3. **Gate on that spike.** If render-from-engine feels good and perf/IME are acceptable, the fork is:

   - lean, chart-heavy, personal tool -> continue in ImGui and accept hand-rolling editing/selection;

   - a real editable application -> pivot to a **Qt model/view** spike, because Qt gives you exactly the hard UX you would otherwise build by hand, for a ~150-line adapter.

4. **Defer web** until *sharing / distribution / collaboration* is an explicit goal -- that is what justifies its two-stack cost, and it is the clearly best option once it is.

5. **Consider terminal graphics in parallel** as a cheap charts win that keeps the existing product moving while the GUI is explored.

The through-line: the engine is ready, so the decision is not really "immediate vs retained" -- it is **what the GUI must unlock**. Mouse and resizable panes are nice-to-haves; *rendering the charts we already import* and richer visualization are the structural wins, and they point at ImPlot (fastest to try) now and web (richest, shareable) later.

## Status

- **Prerequisite (display-layer extraction): done.** Cell formatting moved to the frontend-neutral `gridcalc/display.py` (`fmtcell`, `cell_clip_value`, number formatting), guarded curses-free by `tests/test_architecture.py`.

- **Step 2 (ImGui read-only grid): evaluated, then removed.** An `imgui_bundle` spike (`gridcalc/gui/`, a scrollable read-only `Grid` view drawn with `imgui.begin_table` + a `ListClipper`) confirmed that large-grid rendering was tractable and that cell formatting could be shared with the TUI via `display.fmtcell`. But it stopped short of the editing/selection and IME/CJK-input questions that actually decide a frontend, and hand-rolling those in immediate mode is exactly the cost the web direction avoids. Once web was chosen the ImGui spike was dead weight, so it and its heavy native `[gui]` extra were dropped -- the code, the `gridcalc-gui` script, and the `imgui-bundle` dependency are gone. The design comparison above is kept as the reasoning that led here.

- **Direction chosen: web, editable, desktop-shell.** Rather than hand-roll editing/selection in ImGui, the frontend goes to web technology -- the browser gives native text/IME/accessibility and the strongest charting ecosystem. For a single-user offline app the shell is **pywebview**, not Tauri: the engine stays in-process on CPython (C++ extensions intact) and the browser view calls Python directly through pywebview's `js_api` bridge, so there is no HTTP server, port, or serialization boundary -- just in-process method calls. (Tauri would add Rust plus a Python sidecar with real IPC, justified only when shipping a signed binary to others.)

- **Step 3 (web editable grid): started.** `gridcalc/web/` is the spike, behind the optional `web` extra:

  ```sh
  pip install gridcalc[web]        # or: uv pip install pywebview
  gridcalc-web                      # demo workbook
  gridcalc-web path/to/book.json    # or an .xlsx
  python -m gridcalc.web            # equivalent
  ```

  A `pywebview` window renders a virtualized grid (only cells inside the scrolled viewport enter the DOM, so the full 256x1024 sheet scrolls without 260k nodes) and edits a single cell: double-click, edit the source, Enter commits -> `setcell` + `recalc` + re-render, proving the editable round-trip over the bridge. All engine<->view logic is the plain-Python `Api` class (`dims`/`viewport`/`cell_source`/`set_cell`/`sheets`), imported and unit-tested without a display (`tests/test_web.py`); the JS is thin, framework-free, no build step. Cell formatting reuses `display.cell_text`/`cell_right_aligned`, shared with the TUI.

  **Charts landed too.** A toolbar range box + `Chart` button plot a range as a bar chart. The data path is the reusable part: `Api.chart_data("A4:D6")` returns a renderer-agnostic `{title, labels, series:[{name, values}]}` -- leftmost text column becomes categories, each remaining column a numeric series -- exactly what Plotly/ECharts would consume. It is currently drawn as dependency-free inline SVG (offline, no CDN, no build step); swapping in a real charting library changes only the JS renderer, not `Api`. Because `set_cell` recalcs, editing a cell and re-charting reflects the new values.

  **Selection and keyboard navigation.** An active-cell cursor moves with the arrow keys, Tab, and Home; shift-move (or shift-click) extends a rectangular selection; the selection's A1 ref appears in the toolbar and prefills the chart range, so `Chart` plots whatever is selected. Enter/F2/double-click/typing edits the active cell (Enter commits and advances the cursor down, Tab commits and moves right); Delete blanks the selection via `Api.clear_range`. A plain cursor move only repositions the persistent selection/cursor overlay divs -- it does *not* rebuild the cell DOM, which both keeps navigation cheap and avoids replacing the element under the pointer mid-double-click (a bug the headless tests caught).

  **Formula point mode.** While editing a formula (the editor holds a `=...`), clicking or dragging the grid inserts a reference at the caret instead of moving the selection -- `=SUM(` then dragging A1:A3 gives `=SUM(A1:A3`, and shift-click extends the pointed range. A drag/click replaces the previously pointed reference (tracked as a span in the editor); typing any character finalizes it so the next click starts a fresh reference. This is a pure-view feature -- no `Api` change -- built on the same `mousedown`/`mousemove` plumbing as selection, gated on `editor.value.startsWith('=')`; `mousedown` calls `preventDefault` so the grid click does not blur the editor.

  **Copy / cut / paste** (Ctrl/Cmd+C/X/V over the selection). Paste preserves formulas and adjusts their relative references by the paste offset (absolute `$` refs stay put) -- `Api.copy` snapshots the source cells' text into an internal buffer, `Api.paste` rewrites each via `engine.adjust_refs` (the same reference-shift `replicatecell` uses, extracted so both share it). Cut clears the source cells the paste did not overwrite. Copy also returns the selection's values as TSV, which the client best-effort writes to the OS clipboard (`navigator.clipboard`, wrapped so a blocked clipboard is harmless) for pasting into other apps. Pasting *in* from another app (reading the OS clipboard) is deferred -- it needs reliable clipboard-read permission in the webview.

  **Fill** down and right -- Ctrl+D / Ctrl+R fill the selection from its top row / left column, and a drag-fill handle at the selection's bottom-right corner extends and fills (locked to the dominant axis). Both call `Api.fill`, which reuses `adjust_refs` so `=A1` filled down becomes `=A2`, `=A3`, ...

  **Undo / redo** (Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y) reuse the engine-adjacent `UndoManager`, which was promoted out of `tui/undo.py` into a frontend-neutral `gridcalc/undo.py` (guarded curses-free, like `display.py` / `loader.py`; the TUI re-imports it). The `Api` holds one `UndoManager` and saves state before each mutation -- a cell snapshot before `set_cell`, the region before `clear_range`/`fill`, a full-grid snapshot before `paste` -- and undo recomputes derived cells through `recalc`, so a formula's dependents revert correctly.

  **Save** (Ctrl+S). `Api.save(path)` writes the workbook via the engine's `jsonsave`/`xlsxsave`/`csvsave` (format by extension) to the given path or the loaded filename; the demo (no filename) returns `needs_path`, and the client falls back to `Api.save_dialog`, which opens pywebview's native save dialog (`create_file_dialog`, using the window handle `run()` stashes on the `Api`). A short "saved" flashes in the toolbar. Round-trip is real: a unit test saves through the `Api` and reloads the file, confirming edits and formulas survive.

  **Open a different workbook** (Ctrl+O). `Api.open_dialog` opens pywebview's native open dialog and `Api.open_file(path)` swaps the loaded model in via the shared `loader.load_workbook` (now `.json`/`.xlsx`/`.csv`, formulas-only for JSON so opening a file never runs code). Because a different sheet is now in scope, `open_file` resets the per-workbook UI state that would otherwise dangle -- the `UndoManager` and the copy buffer -- and best-effort retitles the window; the client re-fetches `dims`, redraws the tabs, and moves the cursor back to A1. A bad path returns `{ok: false, error}` and leaves the current workbook untouched.

  **Paste-in from the OS clipboard** (the previously deferred half of paste). On Ctrl+V the client reads `navigator.clipboard`; when it holds text that is *not* the app's own last copy -- i.e. a TSV block from another application -- it routes to `Api.paste_text(r, c, text)`, which splits rows on newline and columns on tab and writes the values verbatim at the active cell (no reference adjustment, since external data carries no gridcalc-relative intent; a leading `=` still becomes a formula, matching a spreadsheet paste), snapshotting the target rectangle as one undo step. When the clipboard matches the last in-app copy, or is unreadable/blocked, Ctrl+V falls back to the internal buffer's formula-preserving, reference-adjusting `Api.paste`.

  **The JS is regression-tested headlessly.** Playwright cannot drive the native pywebview window, so `tests/integration/test_web_playwright.py` loads the *same* `_HTML` in headless Chromium with `window.pywebview.api` mocked from real `Api` output, and asserts on the DOM: headers form one row (not the diagonal stagger an early CSS bug produced), gutter rows are contiguous, numbers right-align, double-click -> edit -> Enter commits through `set_cell` and advances the cursor, arrows move the active cell, shift-arrows extend the selection (and drive the chart range), Delete calls `clear_range`, formula point mode inserts a reference from a click/shift-click and from a drag, copy/cut/paste keys call the Api with the right coordinates and cut flag, Ctrl+D and a drag of the fill handle both fill down, Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y call undo/redo, Ctrl+S saves and flashes status, Ctrl+O routes to the open dialog and resets the cursor, Ctrl+V of external clipboard text routes to `paste_text`, and a range renders the right number of SVG bars. Gated behind the `browser` marker (excluded from the default `make test`; run `make test-web`), skips when Chromium is absent. It is Chromium, not the production WebView, so a faithful proxy rather than pixel-parity -- but it catches the layout/logic failure modes that otherwise only showed up by eye.

  Next increments: a real charting library and interactivity if the SVG proves the value; a real data-grid library only if the hand-rolled grid gets painful. JSON loads formulas-only (no code execution); the window is local and in-process, so there is no network surface to secure yet.

## Open questions that change the answer

- **Audience:** a desktop tool for yourself, or something shareable / distributable? (Personal -> ImGui/Qt; shareable -> web.)

- **Editable now, or read-only-first for visualization?** (Editable pulls hard toward Qt or web; read-only-viz is happy in ImGui.)

- **Is the terminal build still first-class**, kept in parallel, or is the GUI the successor? (Decides how much shared-layer investment is worth.)

- **Acceptable to add a heavy optional dependency** and lose "runs in any terminal over SSH"? (All three GUI options trade that away.)
