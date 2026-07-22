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

- **C++ extensions pin us to CPython.** `_core` (OpenXLSX) and `_opt` (lp_solve) are nanobind C++ modules. This rules out running the engine *in the browser* via Pyodide/WASM without an emscripten rebuild of both vendored libraries -- a large, separate effort. It does **not** affect any option that keeps the engine on a real CPython process.

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

Running the *engine itself* in the browser is blocked: `_core` (OpenXLSX) and `_opt` (lp_solve) are C++ extensions with no Pyodide build. Getting there means emscripten-compiling both vendored libraries, or shipping degraded pure-Python fallbacks that lose xlsx and optimization. Not worth it against the server-backed web option, which reuses the extensions unchanged.

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

## Open questions that change the answer

- **Audience:** a desktop tool for yourself, or something shareable / distributable? (Personal -> ImGui/Qt; shareable -> web.)

- **Editable now, or read-only-first for visualization?** (Editable pulls hard toward Qt or web; read-only-viz is happy in ImGui.)

- **Is the terminal build still first-class**, kept in parallel, or is the GUI the successor? (Decides how much shared-layer investment is worth.)

- **Acceptable to add a heavy optional dependency** and lose "runs in any terminal over SSH"? (All three GUI options trade that away.)
