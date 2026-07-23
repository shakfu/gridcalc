"""Headless-browser regression tests for the web frontend's JS/DOM layer.

The `Api` bridge is unit-tested in Python (`tests/test_web.py`); this file
covers the part Python can't reach -- the actual DOM layout the browser
produces from `_HTML`. Playwright cannot drive the production pywebview window
(a native WebView), so instead the *same* `_HTML` is loaded in headless
Chromium with `window.pywebview.api` mocked. Crucially the mock is driven by
the real `gridcalc.web.Api` output (serialized to JSON), so the Python<->JS
data-shape contract is still exercised; only the transport is faked.

This catches the class of bug that shipped by eye earlier -- diagonally
staggered headers (a CSS `position` mistake) and a torn DOM from overlapping
async renders (dropped rows). It is Chromium, not the production WebView
engine, so it is a faithful-enough proxy, not proof of pixel-parity.

Gated behind the `browser` marker (excluded from the default `make test`) and
skips cleanly when Playwright or its browser binary is absent.
"""

from __future__ import annotations

import json

import pytest

from gridcalc.loader import demo_grid
from gridcalc.web import _HTML, Api

sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

# Layout constants mirrored from the page (kept in sync with `_HTML`).
GW = 52


def _bridge_init_script() -> str:
    """A JS ``window.pywebview.api`` mock backed by real ``Api`` fixtures."""
    g = demo_grid()
    api = Api(g)
    dims = api.dims()
    sheets = api.sheets()
    # A bounded viewport that covers the demo data; the JS mock filters it by
    # the rectangle the renderer requests.
    cells = api.viewport(0, 0, 64, 64)["cells"]
    sources = {f"{c['r']},{c['c']}": api.cell_source(c["r"], c["c"]) for c in cells}
    charts = {"A4:D6": api.chart_data("A4:D6")}

    template = """
      window.__setCalls = []; window.__clearCalls = [];
      window.__copyCalls = []; window.__pasteCalls = []; window.__fillCalls = [];
      window.__pasteTextCalls = []; window.__openDialogCalls = 0;
      window.__solveCalls = []; window.__goalCalls = [];
      window.__undoCalls = 0; window.__redoCalls = 0; window.__saveCalls = 0;
      const CELLS = __CELLS__, DIMS = __DIMS__, SHEETS = __SHEETS__, SOURCES = __SOURCES__;
      const CHARTS = __CHARTS__;
      window.pywebview = { api: {
        copy: async (r0, c0, r1, c1, cut) => {
          window.__copyCalls.push([r0, c0, r1, c1, cut]); return {ok: true, tsv: "x"};
        },
        paste: async (r, c) => { window.__pasteCalls.push([r, c]); return {ok: true}; },
        paste_text: async (r, c, text) => {
          window.__pasteTextCalls.push([r, c, text]); return {ok: true};
        },
        open_dialog: async () => {
          window.__openDialogCalls++; return {ok: true, filename: "other.json"};
        },
        solve_selection: async (r0, c0, r1, c1, sense) => {
          window.__solveCalls.push([r0, c0, r1, c1, sense]);
          return {ok: true, status: "OPTIMAL", optimal: true, objective: 36,
                  applied: true, quadratic: false, values: {A2: 2, A3: 6},
                  sensitivity: {
                    variables: [{cell: "A2", value: 2, reduced_cost: 0, obj_coef: 3,
                                 obj_from: 0, obj_till: 7.5}],
                    constraints: [
                      {cell: "C2", shadow_price: 0, rhs: 4, slack: 2, binding: false,
                       rhs_from: 2, rhs_till: null},
                      {cell: "C3", shadow_price: 1.5, rhs: 12, slack: 0, binding: true,
                       rhs_from: 6, rhs_till: 18},
                      {cell: "C4", shadow_price: 1, rhs: 18, slack: 0, binding: true,
                       rhs_from: 12, rhs_till: 24}]}};
        },
        goal_seek: async (fcell, target, vcell, lo, hi) => {
          window.__goalCalls.push([fcell, target, vcell, lo, hi]);
          return {ok: true, converged: true, iterations: 12, var_value: 5,
                  formula_value: 10, residual: 0, applied: true};
        },
        fill: async (r0, c0, r1, c1, dir) => {
          window.__fillCalls.push([r0, c0, r1, c1, dir]); return {ok: true};
        },
        undo: async () => { window.__undoCalls++; return {ok: true}; },
        redo: async () => { window.__redoCalls++; return {ok: true}; },
        save: async (path) => { window.__saveCalls++; return {ok: true, path: "demo.json"}; },
        dims: async () => DIMS,
        sheets: async () => SHEETS,
        set_active: async (i) => { SHEETS.active = i; return SHEETS; },
        viewport: async (r0, c0, rows, cols) => {
          const r1 = r0 + rows, c1 = c0 + cols;
          return { r0, c0, rows, cols,
            cells: CELLS.filter(x => x.r >= r0 && x.r < r1 && x.c >= c0 && x.c < c1) };
        },
        cell_source: async (r, c) => SOURCES[r + "," + c] || "",
        set_cell: async (r, c, text) => {
          window.__setCalls.push([r, c, text]); return {ok: true};
        },
        clear_range: async (r0, c0, r1, c1) => {
          window.__clearCalls.push([r0, c0, r1, c1]); return {ok: true};
        },
        chart_data: async (spec) =>
          CHARTS[spec.toUpperCase()] || {error: "bad range: " + spec}
      }};
    """
    return (
        template.replace("__CELLS__", json.dumps(cells))
        .replace("__DIMS__", json.dumps(dims))
        .replace("__SHEETS__", json.dumps(sheets))
        .replace("__SOURCES__", json.dumps(sources))
        .replace("__CHARTS__", json.dumps(charts))
    )


@pytest.fixture
def page():
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except sync_api.Error as exc:  # browser binary not installed
            pytest.skip(f"chromium not available: {exc}")
        pg = browser.new_page(viewport={"width": 1200, "height": 800})
        pg.set_content(_HTML)
        # The page's script only *uses* the bridge inside its `pywebviewready`
        # handler, so defining the mock after load (then firing the event) is
        # enough -- and unlike `add_init_script`, it actually applies to
        # `set_content`.
        pg.evaluate(_bridge_init_script())
        pg.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
        # Wait until the first render has populated headers and the demo cells.
        pg.wait_for_function(
            "() => document.querySelectorAll('.hdr').length > 0"
            " && [...document.querySelectorAll('.cell')].some(e => e.textContent === 'Widget')"
        )
        yield pg
        browser.close()


def test_column_headers_form_one_horizontal_row(page) -> None:
    """Regression: headers must share a single top edge, not stagger diagonally
    (the `position: sticky` bug)."""
    tops = page.eval_on_selector_all(
        ".hdr", "els => els.map(e => Math.round(e.getBoundingClientRect().top))"
    )
    assert len(tops) > 3
    assert len(set(tops)) == 1, f"headers are not on one row (tops: {sorted(set(tops))})"


def test_gutter_row_numbers_are_contiguous(page) -> None:
    """Regression: every visible row gets a gutter label -- no gaps from a torn
    DOM (the overlapping-render bug)."""
    labels = sorted(
        page.eval_on_selector_all(".gut", "els => els.map(e => parseInt(e.textContent, 10))")
    )
    assert labels[0] == 1
    assert labels == list(range(labels[0], labels[0] + len(labels))), f"gaps in gutter: {labels}"


def test_numeric_cell_is_right_aligned_and_positioned(page) -> None:
    info = page.evaluate(
        """() => {
            const cells = [...document.querySelectorAll('.cell')];
            const num = cells.find(e => e.textContent === '25');   // D4 = B4*C4
            const label = cells.find(e => e.textContent === 'Widget');  // A4
            return {
              numRight: num.classList.contains('r'),
              labelLeft: !label.classList.contains('r'),
              labelLeftPx: Math.round(parseFloat(label.style.left)),
            };
        }"""
    )
    assert info["numRight"] is True
    assert info["labelLeft"] is True
    assert info["labelLeftPx"] == GW  # column A starts just past the gutter


def test_double_click_edits_cell_and_commits(page) -> None:
    """The editable round-trip: double-click loads the source into an editor,
    and Enter commits it through `set_cell` with the right coordinates."""
    box = page.evaluate(
        """() => {
            const cells = [...document.querySelectorAll('.cell')];
            const el = cells.find(e => e.textContent === 'Widget');
            const r = el.getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
        }"""
    )
    page.mouse.dblclick(box["x"], box["y"])
    page.wait_for_selector("#editor", state="visible")

    assert page.eval_on_selector("#editor", "e => e.value") == "Widget"  # source, not value

    page.fill("#editor", "Doohickey")
    page.keyboard.press("Enter")
    calls = page.evaluate("() => window.__setCalls")
    assert calls == [[3, 0, "Doohickey"]]  # (row 3, col 0) = A4
    assert page.text_content("#cellref") == "A5"  # Enter advances the cursor down


CW = 90
CH = 22


def test_arrow_keys_move_the_active_cell(page) -> None:
    page.click("text=Item")  # A3
    assert page.text_content("#cellref") == "A3"
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowRight")
    assert page.text_content("#cellref") == "B4"
    pos = page.evaluate(
        "() => { const e = document.getElementById('cursor');"
        " return { left: parseInt(e.style.left), top: parseInt(e.style.top) }; }"
    )
    assert pos == {"left": GW + 1 * CW, "top": CH + 3 * CH}  # B4


def test_shift_arrows_extend_a_rectangular_selection(page) -> None:
    page.click("text=Item")  # A3 (anchor)
    page.keyboard.press("Shift+ArrowRight")
    page.keyboard.press("Shift+ArrowDown")
    assert page.input_value("#chartRange") == "A3:B4"  # selection drives the chart range
    sel = page.evaluate(
        "() => { const e = document.getElementById('selrect');"
        " return { w: parseInt(e.style.width), h: parseInt(e.style.height),"
        " shown: e.style.display !== 'none' }; }"
    )
    assert sel == {"w": 2 * CW, "h": 2 * CH, "shown": True}


def test_delete_clears_the_selection(page) -> None:
    page.click("text=Item")  # A3
    page.keyboard.press("Shift+ArrowRight")  # select A3:B3
    page.keyboard.press("Delete")
    page.wait_for_function("() => window.__clearCalls.length > 0")
    assert page.evaluate("() => window.__clearCalls") == [[2, 0, 2, 1]]  # (r0,c0,r1,c1)


def test_formula_point_mode_click_and_shift_build_a_range(page) -> None:
    """Editing a formula and pointing at the grid inserts a reference:
    `=SUM(` + click A4 + shift-click A6 -> `=SUM(A4:A6)`."""
    page.keyboard.press("=")  # begin a formula in the active cell (A1)
    page.keyboard.type("SUM(")
    page.click("text=Widget")  # A4 -> inserts A4
    assert page.input_value("#editor") == "=SUM(A4"
    page.click("text=Gizmo", modifiers=["Shift"])  # A6 -> extends to A4:A6
    assert page.input_value("#editor") == "=SUM(A4:A6"
    page.keyboard.type(")")
    page.keyboard.press("Enter")
    assert page.evaluate("() => window.__setCalls") == [[0, 0, "=SUM(A4:A6)"]]


def test_copy_and_paste_call_the_api(page) -> None:
    page.click("text=Item")  # A3
    page.keyboard.press("Shift+ArrowRight")  # select A3:B3
    page.keyboard.press("Control+c")
    page.wait_for_function("() => window.__copyCalls.length > 0")
    assert page.evaluate("() => window.__copyCalls") == [[2, 0, 2, 1, False]]  # (r0,c0,r1,c1,cut)

    page.keyboard.press("ArrowDown")  # collapse selection, move to B4
    page.keyboard.press("Control+v")
    page.wait_for_function("() => window.__pasteCalls.length > 0")
    assert page.evaluate("() => window.__pasteCalls") == [[3, 1]]  # paste at active cell B4


def test_cut_passes_the_cut_flag(page) -> None:
    page.click("text=Widget")  # A4
    page.keyboard.press("Control+x")
    page.wait_for_function("() => window.__copyCalls.length > 0")
    assert page.evaluate("() => window.__copyCalls") == [[3, 0, 3, 0, True]]  # cut flag set


def test_undo_and_redo_keys_call_the_api(page) -> None:
    page.click("text=Item")  # focus the grid
    page.keyboard.press("Control+z")
    page.wait_for_function("() => window.__undoCalls === 1")
    page.keyboard.press("Control+Shift+z")  # redo
    page.wait_for_function("() => window.__redoCalls === 1")
    page.keyboard.press("Control+y")  # redo (Windows-style)
    page.wait_for_function("() => window.__redoCalls === 2")
    assert page.evaluate("() => window.__undoCalls") == 1


def test_ctrl_s_saves_and_flashes_status(page) -> None:
    page.click("text=Item")  # focus the grid
    page.keyboard.press("Control+s")
    page.wait_for_function("() => window.__saveCalls === 1")
    page.wait_for_function("() => document.getElementById('saveStatus').textContent === 'saved'")


def test_ctrl_d_fills_the_selection_down(page) -> None:
    page.click("text=Item")  # A3
    page.keyboard.press("Shift+ArrowDown")  # select A3:A4
    page.keyboard.press("Control+d")
    page.wait_for_function("() => window.__fillCalls.length > 0")
    assert page.evaluate("() => window.__fillCalls") == [[2, 0, 3, 0, "down"]]


def test_drag_fill_handle_fills_down(page) -> None:
    page.click("text=Widget")  # A4 (single-cell selection)
    box = page.evaluate(
        "() => { const e = document.getElementById('fillhandle');"
        " const r = e.getBoundingClientRect();"
        " return { x: r.x + r.width / 2, y: r.y + r.height / 2 }; }"
    )
    page.mouse.move(box["x"], box["y"])
    page.mouse.down()
    page.mouse.move(box["x"], box["y"] + 2 * CH)  # drag down two rows -> A6
    page.mouse.up()
    page.wait_for_function("() => window.__fillCalls.length > 0")
    assert page.evaluate("() => window.__fillCalls") == [[3, 0, 5, 0, "down"]]  # A4:A6 down


def test_formula_point_mode_drag_selects_a_range(page) -> None:
    """Dragging over the grid during formula entry inserts the dragged range."""
    page.keyboard.press("=")
    page.keyboard.type("SUM(")
    # Drag from A4 (r3) down to A6 (r5), column A. Screen coords: topbar=27,
    # header row=CH, then r*CH; +CH/2 to hit cell centres; +GW/2 for column A.
    x = GW + CW // 2
    page.mouse.move(x, 27 + CH + 3 * CH + CH // 2)  # A4
    page.mouse.down()
    page.mouse.move(x, 27 + CH + 5 * CH + CH // 2)  # A6
    page.mouse.up()
    assert page.input_value("#editor") == "=SUM(A4:A6"


def test_ctrl_o_opens_the_native_file_dialog(page) -> None:
    """Ctrl+O routes through `open_dialog`; the view then redraws against the
    workbook the Api reports it loaded."""
    page.click("text=Item")  # focus the grid
    page.keyboard.press("Control+o")
    page.wait_for_function("() => window.__openDialogCalls === 1")
    # The cursor resets to A1 after a workbook swap.
    assert page.text_content("#cellref") == "A1"


def test_ctrl_v_pastes_external_clipboard_text(page) -> None:
    """A Ctrl+V with OS-clipboard text we did not copy in-app routes to
    `paste_text` (paste-in from another application), verbatim."""
    # Stub the OS clipboard read deterministically -- `navigator.clipboard`
    # may be absent in this insecure test context, so define it if needed.
    page.evaluate(
        "() => {"
        "  if (!navigator.clipboard) {"
        "    Object.defineProperty(navigator, 'clipboard', {value: {}, configurable: true});"
        "  }"
        "  navigator.clipboard.readText = async () => '1\\t2\\n3\\t4';"
        "}"
    )
    page.click("text=Item")  # A3 (r=2, c=0) -- the active cell / paste anchor
    page.keyboard.press("Control+v")
    page.wait_for_function("() => window.__pasteTextCalls.length > 0")
    assert page.evaluate("() => window.__pasteTextCalls") == [[2, 0, "1\t2\n3\t4"]]
    assert page.evaluate("() => window.__pasteCalls") == []  # not the internal buffer


def test_solve_button_optimizes_the_selection(page) -> None:
    """The Solve toolbar action passes the current selection and sense to
    `solve_selection` and surfaces the returned objective."""
    page.click("text=Item")  # A3 (r2, c0)
    page.keyboard.press("Shift+ArrowRight")  # select A3:B3
    page.click("#solveBtn")
    page.wait_for_function("() => window.__solveCalls.length > 0")
    assert page.evaluate("() => window.__solveCalls") == [[2, 0, 2, 1, "max"]]
    page.wait_for_function("() => document.getElementById('optStatus').textContent === 'max = 36'")


def test_solve_button_uses_the_sense_selector(page) -> None:
    """Switching the sense selector to 'min' flows through to the Api call."""
    page.select_option("#optSense", "min")
    page.click("text=Widget")  # A4 (single-cell selection at r3, c0)
    page.click("#solveBtn")
    page.wait_for_function("() => window.__solveCalls.length > 0")
    assert page.evaluate("() => window.__solveCalls") == [[3, 0, 3, 0, "min"]]


def test_solve_opens_a_results_panel_with_sensitivity(page) -> None:
    """Solve opens the results panel showing the objective and the LP
    sensitivity tables (variables + constraints), with a null ranging bound
    rendered as 'inf'."""
    page.click("text=Item")
    page.keyboard.press("Shift+ArrowRight")
    page.click("#solveBtn")
    page.wait_for_selector("#optPanel", state="visible")
    txt = page.text_content("#optPanel")
    assert "OPTIMAL" in txt
    assert "objective = 36" in txt
    assert "1.5" in txt  # C3 shadow price rendered
    assert "inf" in txt  # C2 rhs_till came back null -> shown as inf
    # The last table is the constraints table: header + three constraint rows.
    rows = page.eval_on_selector_all("#optPanel table:last-of-type tr", "els => els.length")
    assert rows == 4


def test_solve_panel_closes(page) -> None:
    page.click("text=Item")
    page.click("#solveBtn")
    page.wait_for_selector("#optPanel", state="visible")
    page.click("#optPanel .panelClose")
    page.wait_for_selector("#optPanel", state="hidden")


def test_goal_dialog_prefills_active_cell_and_runs(page) -> None:
    """Goal opens a dialog prefilled with the active cell; Run calls
    `goal_seek` with the entered (cell, target, var) and surfaces the result."""
    page.click("text=Item")  # A3 becomes the active cell
    page.click("#goalBtn")
    page.wait_for_selector("#goalDialog", state="visible")
    assert page.input_value("#goalCell") == "A3"  # prefilled with the active cell

    page.fill("#goalCell", "B1")
    page.fill("#goalTarget", "10")
    page.fill("#goalVar", "A1")
    page.click("#goalRun")
    page.wait_for_function("() => window.__goalCalls.length > 0")
    assert page.evaluate("() => window.__goalCalls") == [["B1", 10, "A1", None, None]]
    page.wait_for_function(
        "() => document.getElementById('goalResult').textContent.includes('A1 = 5')"
    )


def test_goal_dialog_typing_does_not_navigate_the_grid(page) -> None:
    """Regression: keystrokes in a dialog field must not drive grid navigation
    or start a cell edit (the `_inField` guard)."""
    page.click("text=Item")  # A3
    page.click("#goalBtn")
    page.wait_for_selector("#goalDialog", state="visible")
    page.click("#goalVar")
    page.keyboard.type("A1")
    # The grid cursor stayed put and no in-cell editor opened.
    assert page.text_content("#cellref") == "A3"
    assert page.is_visible("#editor") is False  # no cell edit was started
    assert page.input_value("#goalVar") == "A1"


def test_chart_renders_bars_from_a_range(page) -> None:
    """Typing a range and pressing Chart draws one SVG bar per (group, series)
    -- the demo's A4:D6 is 3 rows x 3 numeric columns (B, C, D) = 9 bars."""
    page.fill("#chartRange", "A4:D6")
    page.click("#chartBtn")
    page.wait_for_selector("#chart", state="visible")
    page.wait_for_function("() => document.querySelectorAll('#chartSvg rect').length > 0")

    bars = page.eval_on_selector_all("#chartSvg rect[data-series]", "els => els.length")
    assert bars == 9

    # The tallest bar is D5 = 36 (the max value), so it reaches the plot floor.
    heights = page.eval_on_selector_all(
        "#chartSvg rect[data-series]", "els => els.map(e => +e.getAttribute('height'))"
    )
    assert max(heights) > min(h for h in heights if h > 0)  # bars are scaled, not uniform

    title = page.eval_on_selector_all("#chartSvg text", "els => els.map(e => e.textContent)")
    assert "A4:D6" in title
