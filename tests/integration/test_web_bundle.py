"""Headless-browser tests for the built React bundle.

Proves the Vite/React single-file build boots inside a real browser, completes
the pywebview bridge round-trip, and that the chrome (menubar, toolbar, sheet
select) and the virtualized grid (render, cursor, edit, delete) drive the
bridge. Same faithful-proxy approach as the other web DOM tests -- real
Chromium, a mocked `window.pywebview.api` -- but it loads the *built*
`static/index.html`, so it is skipped unless the frontend has been compiled
(`make web-build`).

Gated behind the `browser` marker (excluded from the default `make test`) and
skips cleanly when Playwright, its browser binary, or the build is absent.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

BUNDLE = (
    Path(__file__).resolve().parents[2] / "src" / "gridcalc" / "web" / "static" / "index.html"
)

# The pywebview window injects `window.pywebview.api`; here the test provides a
# stateful mock (records calls, a seeded cell store, switches sheets) and fires
# the ready event the app waits on.
_MOCK_BRIDGE = """
  window.__calls = {
    open_dialog: 0, save: 0, set_active: [], set_cell: [], clear_range: [],
    copy: [], paste: [], paste_text: [], fill: [], solve: [], goal: [], chart: [],
    set_format: [], set_global_format: []
  };
  const sheets = { active: 0, names: ['Sheet1', 'Data'] };
  const cells = new Map();
  const styles = new Map();
  const k = (r, c) => r + ',' + c;
  [[0,0,'gridcalc demo'],[2,0,'Item'],[2,1,'Qty'],[2,2,'Price'],
   [3,0,'Widget'],[3,1,'10'],[3,2,'2.5'],
   [4,0,'Gadget'],[4,1,'4'],[4,2,'9'],
   [5,0,'Gizmo'],[5,1,'7'],[5,2,'3.25']].forEach(([r,c,t]) => cells.set(k(r,c), t));
  const isNum = (s) => s !== '' && (!isNaN(Number(s)) || s.startsWith('='));
  window.pywebview = { api: {
    dims: async () => ({ ncol: 256, nrow: 1024, filename: 'book.json' }),
    sheets: async () => ({ ...sheets }),
    set_active: async (i) => {
      window.__calls.set_active.push(i); sheets.active = i; return { ...sheets };
    },
    undo: async () => ({ ok: true }),
    redo: async () => ({ ok: true }),
    save: async () => { window.__calls.save++; return { ok: true, path: 'book.json' }; },
    save_dialog: async () => ({ ok: true, path: 'book.json' }),
    open_dialog: async () => {
      window.__calls.open_dialog++; return { ok: true, filename: 'book.json' };
    },
    open_file: async (p) => ({ ok: true, filename: p }),
    viewport: async (r0, c0, rows, cols) => {
      const out = [];
      for (let r = r0; r < r0 + rows; r++) {
        for (let c = c0; c < c0 + cols; c++) {
          const t = cells.get(k(r, c));
          if (!t) continue;
          const cell = { r, c, text: t, align: isNum(t) ? 'r' : 'l' };
          const st = styles.get(k(r, c));
          if (st && st.bold) cell.bold = true;
          if (st && st.italic) cell.italic = true;
          if (st && st.underline) cell.underline = true;
          out.push(cell);
        }
      }
      return { r0, c0, rows, cols, cells: out };
    },
    set_format: async (r0, c0, r1, c1, spec) => {
      window.__calls.set_format.push([r0, c0, r1, c1, spec]);
      const s = spec || '';
      const style = s.length > 0 && [...s].every((ch) => 'bui'.includes(ch));
      const single = s.length === 1 && 'LRIGD$%*'.includes(s.toUpperCase());
      for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
        for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) {
          if (!cells.has(k(r, c))) continue;
          const cur = styles.get(k(r, c)) ||
            { bold: false, italic: false, underline: false, fmt: '', fmtstr: '' };
          if (style) {
            for (const ch of s) {
              if (ch === 'b') cur.bold = !cur.bold;
              else if (ch === 'u') cur.underline = !cur.underline;
              else if (ch === 'i') cur.italic = !cur.italic;
            }
          } else if (single) { cur.fmt = s.toUpperCase(); cur.fmtstr = ''; }
          else if (s) { cur.fmtstr = s.slice(0, 31); cur.fmt = ''; }
          styles.set(k(r, c), cur);
        }
      }
      return { ok: true };
    },
    set_global_format: async (fmt) => {
      window.__calls.set_global_format.push(fmt); return { ok: true };
    },
    cell_source: async (r, c) => cells.get(k(r, c)) || '',
    set_cell: async (r, c, text) => {
      window.__calls.set_cell.push([r, c, text]);
      if (text) cells.set(k(r, c), text); else cells.delete(k(r, c));
      return { ok: true };
    },
    clear_range: async (r0, c0, r1, c1) => {
      window.__calls.clear_range.push([r0, c0, r1, c1]);
      for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
        for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) cells.delete(k(r, c));
      }
      return { ok: true };
    },
    copy: async (r0, c0, r1, c1, cut) => {
      window.__calls.copy.push([r0, c0, r1, c1, cut]);
      const t = cells.get(k(r0, c0)) || '';
      return { ok: true, tsv: t };
    },
    paste: async (r, c) => { window.__calls.paste.push([r, c]); return { ok: true }; },
    paste_text: async (r, c, text) => {
      window.__calls.paste_text.push([r, c, text]); return { ok: true };
    },
    fill: async (r0, c0, r1, c1, dir) => {
      window.__calls.fill.push([r0, c0, r1, c1, dir]); return { ok: true };
    },
    solve_selection: async (r0, c0, r1, c1, sense) => {
      window.__calls.solve.push([r0, c0, r1, c1, sense]);
      return { ok: true, status: 'OPTIMAL', optimal: true, objective: 36,
        values: { A2: 2, A3: 6 }, applied: true, quadratic: false,
        sensitivity: {
          variables: [{ cell: 'A2', value: 2, reduced_cost: 0, obj_coef: 3,
                        obj_from: 0, obj_till: 7.5 }],
          constraints: [{ cell: 'C3', shadow_price: 1.5, rhs: 12, activity: 12,
                          slack: 0, binding: true, rhs_from: 6, rhs_till: 18 }] } };
    },
    solve_model: async () => ({ ok: true, status: 'OPTIMAL', optimal: true, objective: 36,
      values: {}, applied: false, quadratic: false }),
    goal_seek: async (f, t, v) => {
      window.__calls.goal.push([f, t, v]);
      return { ok: true, converged: true, iterations: 12, var_value: t / 2,
        formula_value: t, residual: 0, applied: true };
    },
    opt_sweep: async () => ({ ok: true, points: [] }),
    chart_data: async (spec) => {
      window.__calls.chart.push(spec);
      if (spec.includes(':')) {
        return { title: spec, labels: ['Widget', 'Gadget', 'Gizmo'],
          series: [{ name: 'B', values: [10, 4, 7] }, { name: 'C', values: [2.5, 9, 3.25] }] };
      }
      return { error: 'bad range: ' + spec };
    },
  }};
  window.dispatchEvent(new Event('pywebviewready'));
"""


@pytest.fixture
def page():
    if not BUNDLE.exists():
        pytest.skip("web bundle not built; run `make web-build`")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except sync_api.Error as exc:  # browser binary not installed
            pytest.skip(f"chromium not available: {exc}")
        pg = browser.new_page(viewport={"width": 1200, "height": 800})
        pg.set_content(BUNDLE.read_text(encoding="utf-8"))
        pg.evaluate(_MOCK_BRIDGE)
        pg.wait_for_selector(".cell-layer .cell")  # grid rendered from the bridge
        yield pg
        browser.close()


# --- boot + chrome (Phase 0/1) --------------------------------------------


def test_menubar_renders_the_full_structure(page) -> None:
    for label in ("File", "Edit", "Insert", "Data", "Help"):
        assert page.get_by_role("menuitem", name=label).is_visible()


def test_file_open_menu_item_calls_the_bridge(page) -> None:
    page.get_by_role("menuitem", name="File").click()
    page.get_by_role("menuitem", name=re.compile("Open")).click()
    page.wait_for_function("() => window.__calls.open_dialog === 1")


def test_toolbar_save_button_calls_the_bridge(page) -> None:
    page.get_by_role("button", name="Save").click()
    page.wait_for_function("() => window.__calls.save === 1")


def test_sheet_select_switches_the_active_sheet(page) -> None:
    page.get_by_label("Active sheet").click()
    page.get_by_role("option", name="Data").click()
    page.wait_for_function("() => JSON.stringify(window.__calls.set_active) === '[1]'")


def test_help_about_opens_a_modal_dialog(page) -> None:
    page.get_by_role("menuitem", name="Help").click()
    page.get_by_role("menuitem", name=re.compile("About")).click()
    dialog = page.get_by_role("dialog")
    assert dialog.is_visible()
    assert "gridcalc" in dialog.text_content()
    page.keyboard.press("Escape")
    page.wait_for_selector("[role='dialog']", state="detached")


# --- the grid (Phase 2) ----------------------------------------------------


def test_grid_renders_seeded_cells(page) -> None:
    assert page.get_by_text("Widget").is_visible()
    assert page.get_by_text("Price").is_visible()


def test_clicking_a_cell_moves_the_cursor(page) -> None:
    page.get_by_text("Widget").click()  # A4
    assert page.locator(".name-box").text_content() == "A4"


def test_arrow_keys_navigate_the_grid(page) -> None:
    page.locator(".cell-layer").get_by_text("gridcalc demo").click()  # A1
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowRight")
    assert page.locator(".name-box").text_content() == "B2"


def test_double_click_edits_and_commits_through_set_cell(page) -> None:
    page.get_by_text("Widget").dblclick()  # A4
    editor = page.locator(".cell-editor")
    editor.wait_for(state="visible")
    assert editor.input_value() == "Widget"
    editor.fill("Doohickey")
    page.keyboard.press("Enter")
    page.wait_for_function("() => window.__calls.set_cell.length === 1")
    assert page.evaluate("() => window.__calls.set_cell[0]") == [3, 0, "Doohickey"]
    assert page.get_by_text("Doohickey").is_visible()


def test_delete_clears_the_active_cell(page) -> None:
    page.get_by_text("Widget").click()  # A4
    page.keyboard.press("Delete")
    page.wait_for_function("() => window.__calls.clear_range.length === 1")
    assert page.evaluate("() => window.__calls.clear_range[0]") == [3, 0, 3, 0]
    page.wait_for_selector("text=Widget", state="detached")


# --- clipboard, fill, point mode (Phase 2b) --------------------------------


def test_copy_then_paste_calls_the_bridge(page) -> None:
    page.get_by_text("Widget").click()  # A4
    page.keyboard.press("Control+c")
    page.wait_for_function("() => window.__calls.copy.length === 1")
    assert page.evaluate("() => window.__calls.copy[0]") == [3, 0, 3, 0, False]
    page.keyboard.press("ArrowRight")  # move to B4
    page.keyboard.press("Control+v")
    # Clipboard read is blocked in this context, so paste uses the internal buffer.
    page.wait_for_function("() => window.__calls.paste.length === 1")
    assert page.evaluate("() => window.__calls.paste[0]") == [3, 1]


def test_cut_passes_the_cut_flag(page) -> None:
    page.get_by_text("Widget").click()  # A4
    page.keyboard.press("Control+x")
    page.wait_for_function("() => window.__calls.copy.length === 1")
    assert page.evaluate("() => window.__calls.copy[0][4]") is True


def test_paste_in_external_clipboard_text(page) -> None:
    page.evaluate(
        "() => {"
        "  if (!navigator.clipboard) {"
        "    Object.defineProperty(navigator, 'clipboard', {value: {}, configurable: true});"
        "  }"
        "  navigator.clipboard.writeText = async () => {};"
        "  navigator.clipboard.readText = async () => 'x\\ty';"
        "}"
    )
    page.get_by_text("Widget").click()  # A4 is the paste anchor
    page.keyboard.press("Control+v")
    page.wait_for_function("() => window.__calls.paste_text.length === 1")
    assert page.evaluate("() => window.__calls.paste_text[0]") == [3, 0, "x\ty"]


def test_ctrl_d_fills_the_selection_down(page) -> None:
    page.get_by_text("Widget").click()  # A4
    page.get_by_text("Gizmo").click(modifiers=["Shift"])  # extend to A4:A6
    page.keyboard.press("Control+d")
    page.wait_for_function("() => window.__calls.fill.length === 1")
    assert page.evaluate("() => window.__calls.fill[0]") == [3, 0, 5, 0, "down"]


def test_drag_fill_handle_fills_down(page) -> None:
    page.get_by_text("Widget").click()  # A4 (single-cell selection)
    box = page.locator(".fill-handle").bounding_box()
    page.mouse.move(box["x"] + 4, box["y"] + 4)
    page.mouse.down()
    page.mouse.move(box["x"] + 4, box["y"] + 4 + 2 * 22)  # drag down ~2 rows
    page.mouse.up()
    page.wait_for_function("() => window.__calls.fill.length === 1")
    fill = page.evaluate("() => window.__calls.fill[0]")
    assert fill[0] == 3 and fill[4] == "down"  # starts at A4, fills down


def test_formula_point_mode_inserts_references(page) -> None:
    page.locator(".cell-layer").get_by_text("gridcalc demo").click()  # A1 active
    page.keyboard.press("=")  # start a formula
    editor = page.locator(".cell-editor")
    editor.wait_for(state="visible")
    page.keyboard.type("SUM(")
    page.get_by_text("Widget").click()  # A4 -> inserts A4
    assert editor.input_value() == "=SUM(A4"
    page.get_by_text("Gizmo").click(modifiers=["Shift"])  # -> A4:A6
    assert editor.input_value() == "=SUM(A4:A6"


# --- feature dialogs (Phase 3) ---------------------------------------------


def test_data_optimize_solves_the_selection(page) -> None:
    page.get_by_text("Widget").click()  # A4 selection
    page.get_by_role("menuitem", name="Data").click()
    page.get_by_role("menuitem", name=re.compile("Optimize")).click()
    page.get_by_role("button", name="Solve").click()
    result = page.get_by_test_id("solve-result")
    result.wait_for()
    txt = result.text_content()
    assert "OPTIMAL" in txt
    assert "objective = 36" in txt
    assert "1.5" in txt  # C3 shadow price in the sensitivity table


def test_data_goal_seek_runs(page) -> None:
    page.get_by_role("menuitem", name="Data").click()
    page.get_by_role("menuitem", name=re.compile("Goal")).click()
    page.get_by_placeholder("B1").fill("B1")
    page.get_by_placeholder("0", exact=True).fill("10")
    page.get_by_placeholder("A1").fill("A1")
    page.get_by_role("button", name="Run").click()
    page.wait_for_function("() => window.__calls.goal.length === 1")
    assert page.evaluate("() => window.__calls.goal[0]") == ["B1", 10, "A1"]
    assert "A1 = 5" in page.locator(".goal-result").text_content()


def test_data_chart_draws_bars(page) -> None:
    page.get_by_text("Widget").click()  # A4
    page.get_by_role("menuitem", name="Data").click()
    page.get_by_role("menuitem", name=re.compile("Chart")).click()
    page.get_by_placeholder("A4:D6").fill("A4:C6")
    page.get_by_role("button", name="Draw").click()
    page.wait_for_selector(".recharts-bar-rectangle")
    # 2 numeric series (B, C) x 3 groups (Widget/Gadget/Gizmo) = 6 bars.
    assert page.locator(".recharts-bar-rectangle").count() == 6


# --- formatting (Phase 4) --------------------------------------------------


def test_toolbar_bold_formats_the_active_cell(page) -> None:
    page.get_by_text("Widget").click()  # A4
    page.get_by_role("button", name="B", exact=True).click()
    page.wait_for_function("() => window.__calls.set_format.length === 1")
    assert page.evaluate("() => window.__calls.set_format[0]") == [3, 0, 3, 0, "b"]
    # The cell re-renders bold.
    page.wait_for_function(
        "() => { const c = [...document.querySelectorAll('.cell')]"
        ".find(e => e.textContent === 'Widget'); return !!c && c.classList.contains('b'); }"
    )


def test_format_menu_currency_sets_the_number_format(page) -> None:
    page.get_by_text("Widget").click()  # A4
    page.get_by_role("menuitem", name="Format").click()
    page.get_by_role("menuitem", name="Number: Currency").click()
    page.wait_for_function("() => window.__calls.set_format.length === 1")
    assert page.evaluate("() => window.__calls.set_format[0]") == [3, 0, 3, 0, "$"]


def test_format_menu_default_currency_sets_the_global_format(page) -> None:
    page.get_by_role("menuitem", name="Format").click()
    page.get_by_role("menuitem", name="Default: Currency").click()
    page.wait_for_function("() => window.__calls.set_global_format.length === 1")
    assert page.evaluate("() => window.__calls.set_global_format[0]") == "$"


def test_column_resize_widens_the_column(page) -> None:
    handle = page.locator(".col-resize").first  # column A's right edge
    box = handle.bounding_box()
    page.mouse.move(box["x"] + 3, box["y"] + 11)
    page.mouse.down()
    page.mouse.move(box["x"] + 3 + 50, box["y"] + 11)  # drag right ~50px
    page.mouse.up()
    info = page.evaluate(
        "() => {"
        "  const a = [...document.querySelectorAll('.hdr')].find(e => e.textContent === 'A');"
        "  const right = a.getBoundingClientRect().right;"
        "  const lines = [...document.querySelectorAll('.vline')]"
        ".map(v => v.getBoundingClientRect().left);"
        "  return { width: a.getBoundingClientRect().width,"
        "           lineTracks: lines.some(l => Math.abs(l - right) < 2) };"
        "}"
    )
    assert info["width"] > 120  # was the default 90px
    # a vertical gridline sits at the widened column's right edge (tracks resize)
    assert info["lineTracks"] is True
