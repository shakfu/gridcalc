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
    copy: [], paste: [], paste_text: [], fill: []
  };
  const sheets = { active: 0, names: ['Sheet1', 'Data'] };
  const cells = new Map();
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
          if (t) out.push({ r, c, text: t, align: isNum(t) ? 'r' : 'l' });
        }
      }
      return { r0, c0, rows, cols, cells: out };
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
