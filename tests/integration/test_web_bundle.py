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

BUNDLE = Path(__file__).resolve().parents[2] / "src" / "gridcalc" / "web" / "static" / "index.html"

# The pywebview window injects `window.pywebview.api`; here the test provides a
# stateful mock (records calls, a seeded cell store, switches sheets) and fires
# the ready event the app waits on.
_MOCK_BRIDGE = """
  window.__calls = {
    open_dialog: 0, save: 0, set_active: [], set_cell: [], clear_range: [],
    copy: [], paste: [], paste_text: [], fill: [], solve: [], goal: [], chart: [],
    set_format: [], set_global_format: [], save_model: [],
    sheet_ops: [], structural: [], col_widths: [], search: [], undo_calls: 0, commands: []
  };
  const sheets = { active: 0, names: ['Sheet1', 'Data'] };
  const cells = new Map();
  const styles = new Map();
  const models = new Map();
  const colWidths = {};
  const namedRanges = {};
  let dirty = false;
  const touch = () => { dirty = true; return { ok: true, dirty: true }; };
  const k = (r, c) => r + ',' + c;
  [[0,0,'gridcalc demo'],[2,0,'Item'],[2,1,'Qty'],[2,2,'Price'],
   [3,0,'Widget'],[3,1,'10'],[3,2,'2.5'],
   [4,0,'Gadget'],[4,1,'4'],[4,2,'9'],
   [5,0,'Gizmo'],[5,1,'7'],[5,2,'3.25']].forEach(([r,c,t]) => cells.set(k(r,c), t));
  const isNum = (s) => s !== '' && (!isNaN(Number(s)) || s.startsWith('='));
  const colName = (c) => {
    let s = ''; c += 1;
    while (c > 0) { c -= 1; s = String.fromCharCode(65 + (c % 26)) + s; c = Math.floor(c / 26); }
    return s;
  };
  // Structural edits, mock-side: slide every cell across the edit point so the
  // rendered grid actually changes and the test can see it, not just count calls.
  const shift = (axis, at, delta) => {
    const moved = new Map();
    for (const [key, text] of cells) {
      const [r, c] = key.split(',').map(Number);
      const along = axis === 'r' ? r : c;
      if (delta < 0 && along >= at && along < at - delta) continue;
      const to = along >= at ? along + delta : along;
      moved.set(axis === 'r' ? k(to, c) : k(r, to), text);
    }
    cells.clear();
    for (const [key, v] of moved) cells.set(key, v);
  };
  window.pywebview = { api: {
    dims: async () => ({ ncol: 256, nrow: 1024, filename: 'book.json', dirty }),
    sheets: async () => ({ ...sheets }),
    set_active: async (i) => {
      window.__calls.set_active.push(i); sheets.active = i; return { ...sheets };
    },
    search: async (pattern) => {
      const pat = (pattern || '').toLowerCase();
      if (!pat) return { matches: [], total: 0, truncated: false };
      const hits = [];
      for (const [key, text] of cells) {
        if (!text.toLowerCase().includes(pat)) continue;
        const [r, c] = key.split(',').map(Number);
        hits.push({ r, c, ref: colName(c) + (r + 1) });
      }
      hits.sort((a, b) => a.r - b.r || a.c - b.c);
      window.__calls.search.push(pattern);
      return { matches: hits, total: hits.length, truncated: false };
    },
    list_commands: async () => ({ commands: [
      { name: 'blank', aliases: ['b'], title: 'Clear cells', group: 'Edit',
        needs_selection: true, args: [] },
      { name: 'insrow', aliases: ['ir'], title: 'Insert rows', group: 'Insert',
        needs_selection: true, args: [] },
      { name: 'inscol', aliases: ['ic'], title: 'Insert columns', group: 'Insert',
        needs_selection: true, args: [] },
      { name: 'delrow', aliases: ['dr'], title: 'Delete rows', group: 'Insert',
        needs_selection: true, args: [] },
      { name: 'delcol', aliases: ['dc'], title: 'Delete columns', group: 'Insert',
        needs_selection: true, args: [] },
      { name: 'sort', aliases: [], title: 'Sort rows', group: 'Data', needs_selection: true,
        args: [{ name: 'column', help: 'column letter', required: false, kind: 'ref', choices: [] },
               { name: 'direction', help: 'asc or desc', required: false, kind: 'choice',
                 choices: ['asc', 'desc'] }] },
      { name: 'name', aliases: [], title: 'Define name for selection', group: 'Name',
        needs_selection: true,
        args: [{ name: 'name', help: 'the name to define', required: true,
                 kind: 'text', choices: [] },
               { name: 'range', help: 'defaults to the selection', required: false,
                 kind: 'range', choices: [] }] },
      { name: 'names', aliases: [], title: 'List named ranges', group: 'Name',
        needs_selection: false, args: [] },
      { name: 'recalc', aliases: [], title: 'Recalculate', group: 'Data',
        needs_selection: false, args: [] },
    ] }),
    run_command: async (name, args, selection) => {
      window.__calls.commands.push([name, args || [], selection]);
      if (name === 'name' && !/^[A-Za-z][A-Za-z0-9_]*$/.test((args || [])[0] || '')) {
        return { ok: false, changed: false, lines: [],
                 message: "not a usable name: '" + ((args || [])[0] || '') + "'" };
      }
      if (name === 'names') {
        return { ok: true, changed: false, lines: ['Demo = A1'], message: 'Demo=A1' };
      }
      if (name === 'recalc') {
        return { ok: true, changed: false, lines: [], message: 'recalculated' };
      }
      const sel = selection || { r0: 0, c0: 0, r1: 0, c1: 0 };
      const rows = sel.r1 - sel.r0 + 1, cols = sel.c1 - sel.c0 + 1;
      if (name === 'insrow') shift('r', sel.r0, rows);
      else if (name === 'inscol') shift('c', sel.c0, cols);
      else if (name === 'delrow') shift('r', sel.r0, -rows);
      else if (name === 'delcol') shift('c', sel.c0, -cols);
      touch();
      return { ok: true, changed: true, lines: [], message: name + ' ran', dirty: true };
    },
    col_widths: async () => ({ widths: { ...colWidths } }),
    set_col_width: async (col, px) => {
      window.__calls.col_widths.push([col, px]); colWidths[col] = px; return touch();
    },
    add_sheet: async (name) => {
      window.__calls.sheet_ops.push(['add', name]);
      if (sheets.names.includes(name)) {
        return { ...sheets, ok: false, error: "sheet '" + name + "' already exists" };
      }
      sheets.names.push(name); sheets.active = sheets.names.length - 1;
      touch(); return { ...sheets, ok: true };
    },
    delete_sheet: async (name) => {
      window.__calls.sheet_ops.push(['del', name]);
      const i = sheets.names.indexOf(name);
      if (i < 0) return { ...sheets, ok: false, error: 'no such sheet: ' + name };
      sheets.names.splice(i, 1);
      if (sheets.active >= sheets.names.length) sheets.active = sheets.names.length - 1;
      else if (sheets.active > i) sheets.active -= 1;
      touch(); return { ...sheets, ok: true };
    },
    rename_sheet: async (old, name) => {
      window.__calls.sheet_ops.push(['rename', old, name]);
      const i = sheets.names.indexOf(old);
      if (i < 0) return { ...sheets, ok: false, error: 'no such sheet: ' + old };
      sheets.names[i] = name; touch(); return { ...sheets, ok: true };
    },
    move_sheet: async (name, index) => {
      window.__calls.sheet_ops.push(['move', name, index]);
      const i = sheets.names.indexOf(name);
      const activeName = sheets.names[sheets.active];
      sheets.names.splice(i, 1); sheets.names.splice(index, 0, name);
      sheets.active = sheets.names.indexOf(activeName);
      touch(); return { ...sheets, ok: true };
    },
    undo: async () => { window.__calls.undo_calls++; return touch(); },
    redo: async () => touch(),
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
    stats: async (r0, c0, r1, c1) => {
      let count = 0; const nums = [];
      for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
        for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) {
          const t = cells.get(k(r, c));
          if (!t) continue;
          count++;
          const n = Number(t);
          if (isFinite(n)) nums.push(n);
        }
      }
      const sum = nums.length ? nums.reduce((a, b) => a + b, 0) : null;
      return {
        count, numeric: nums.length, sum,
        avg: sum === null ? null : sum / nums.length,
        min: nums.length ? Math.min(...nums) : null,
        max: nums.length ? Math.max(...nums) : null,
      };
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
      return touch();
    },
    set_global_format: async (fmt) => {
      window.__calls.set_global_format.push(fmt); return touch();
    },
    cell_source: async (r, c) => cells.get(k(r, c)) || '',
    set_cell: async (r, c, text) => {
      window.__calls.set_cell.push([r, c, text]);
      if (text) cells.set(k(r, c), text); else cells.delete(k(r, c));
      return touch();
    },
    clear_range: async (r0, c0, r1, c1) => {
      window.__calls.clear_range.push([r0, c0, r1, c1]);
      for (let r = Math.min(r0, r1); r <= Math.max(r0, r1); r++) {
        for (let c = Math.min(c0, c1); c <= Math.max(c0, c1); c++) cells.delete(k(r, c));
      }
      return touch();
    },
    copy: async (r0, c0, r1, c1, cut) => {
      window.__calls.copy.push([r0, c0, r1, c1, cut]);
      const t = cells.get(k(r0, c0)) || '';
      return { ok: true, tsv: t };
    },
    paste: async (r, c) => { window.__calls.paste.push([r, c]); return touch(); },
    paste_text: async (r, c, text) => {
      window.__calls.paste_text.push([r, c, text]); return touch();
    },
    fill: async (r0, c0, r1, c1, dir) => {
      window.__calls.fill.push([r0, c0, r1, c1, dir]); return touch();
    },
    solve_selection: async (r0, c0, r1, c1, sense) => {
      window.__calls.solve.push([r0, c0, r1, c1, sense]);
      models.set('default', { name: 'default', sense: 'max', objective: 'B2',
                              vars: 'A2:A3', constraints: 'C2:C4' });
      return { ok: true, status: 'OPTIMAL', optimal: true, objective: 36,
        values: { A2: 2, A3: 6 }, applied: true, quadratic: false,
        sensitivity: {
          variables: [{ cell: 'A2', value: 2, reduced_cost: 0, obj_coef: 3,
                        obj_from: 0, obj_till: 7.5 }],
          constraints: [{ cell: 'C3', shadow_price: 1.5, rhs: 12, activity: 12,
                          slack: 0, binding: true, rhs_from: 6, rhs_till: 18 }] } };
    },
    solve_model: async () => ({ ok: true, status: 'OPTIMAL', optimal: true, objective: 36,
      values: { A2: 2, A3: 6 }, applied: true, quadratic: false,
      sensitivity: {
        variables: [{ cell: 'A2', value: 2, reduced_cost: 0, obj_coef: 3,
                      obj_from: 0, obj_till: 7.5 }],
        constraints: [
          { cell: 'C2', shadow_price: 0, rhs: 4, activity: 2, slack: 2,
            binding: false, rhs_from: 2, rhs_till: null },
          { cell: 'C3', shadow_price: 1.5, rhs: 12, activity: 12, slack: 0,
            binding: true, rhs_from: 6, rhs_till: 18 }] } }),
    list_models: async () => ({
      models: [...models.values()].sort((a, b) => a.name.localeCompare(b.name)),
    }),
    save_model: async (name, spec) => {
      const key = String(name || '').trim();
      if (!key) return { ok: false, error: 'a model needs a name' };
      if (!spec.objective || !spec.vars || !spec.constraints) {
        return { ok: false, error: 'saved model missing required field' };
      }
      window.__calls.save_model.push(key);
      models.set(key, { name: key, ...spec });
      return { ...touch(), name: key };
    },
    delete_model: async (name) => {
      if (!models.has(name)) return { ok: false, error: 'no such model: ' + name };
      models.delete(name); return touch();
    },
    run_model: async (name) => {
      if (!models.has(name)) return { ok: false, error: 'no such model: ' + name };
      return { ok: true, status: 'OPTIMAL', optimal: true, objective: 36,
        values: { A2: 2, A3: 6 }, applied: true, quadratic: false };
    },
    infer_model_spec: async (r0, c0, r1, c1, sense) => ({
      ok: true, sense, objective: 'B2', vars: 'A2:A3', constraints: 'C2:C4' }),
    goal_seek: async (f, t, v) => {
      window.__calls.goal.push([f, t, v]);
      return { ok: true, converged: true, iterations: 12, var_value: t / 2,
        formula_value: t, residual: 0, applied: true };
    },
    opt_sweep: async () => ({ ok: true, points: [
      { rhs: 0, status: 'OPTIMAL', objective: 24, shadow_price: 1.5, delta: null,
        breakpoint: false },
      { rhs: 12, status: 'OPTIMAL', objective: 30, shadow_price: 1.5, delta: 6, breakpoint: false },
      { rhs: 24, status: 'OPTIMAL', objective: 36, shadow_price: 1, delta: 6, breakpoint: true },
    ] }),
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
    assert page.locator(".name-box").input_value() == "A4"


def test_arrow_keys_navigate_the_grid(page) -> None:
    page.locator(".cell-layer").get_by_text("gridcalc demo").click()  # A1
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowRight")
    assert page.locator(".name-box").input_value() == "B2"


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
    page.get_by_role("button", name="Solve selection").click()
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


def test_column_resize_persists_to_the_workbook(page) -> None:
    """The width is workbook state, not session state -- without the write-back
    a resize is lost the moment the sheet is reloaded."""
    handle = page.locator(".col-resize").first
    box = handle.bounding_box()
    page.mouse.move(box["x"] + 3, box["y"] + 11)
    page.mouse.down()
    page.mouse.move(box["x"] + 3 + 50, box["y"] + 11)
    page.mouse.up()
    page.wait_for_function("() => window.__calls.col_widths.length === 1")
    col, px = page.evaluate("() => window.__calls.col_widths[0]")
    assert col == 0
    assert px > 120
    # Written once, on release -- not on every frame of the drag.
    assert page.evaluate("() => window.__calls.col_widths.length") == 1


# --- command layer, status bar (Phase 3) -----------------------------------


def test_edit_menu_delete_reaches_the_grid(page) -> None:
    """The Edit items were disabled placeholders until the grid exposed an
    imperative handle; this proves the wiring survives the production build."""
    page.get_by_text("Widget").click()  # A4 becomes the cursor cell
    page.get_by_role("menuitem", name="Edit").click()
    page.get_by_role("menuitem", name="Delete", exact=True).click()
    page.wait_for_function("() => window.__calls.clear_range.length === 1")
    assert page.evaluate("() => window.__calls.clear_range[0]") == [3, 0, 3, 0]


def test_edit_menu_copy_and_paste_reach_the_grid(page) -> None:
    page.get_by_text("Widget").click()  # A4
    page.get_by_role("menuitem", name="Edit").click()
    page.get_by_role("menuitem", name=re.compile("Copy")).click()
    page.wait_for_function("() => window.__calls.copy.length === 1")
    assert page.evaluate("() => window.__calls.copy[0]") == [3, 0, 3, 0, False]


def test_status_bar_summarizes_the_selection(page) -> None:
    page.locator(".cell-layer").get_by_text("10", exact=True).click()  # B4
    page.keyboard.press("Shift+ArrowDown")
    page.keyboard.press("Shift+ArrowDown")  # B4:B6 = 10, 4, 7
    bar = page.locator(".statusbar")
    bar.get_by_text("B4:B6").wait_for()
    bar.get_by_text("sum 21").wait_for()
    bar.get_by_text("count 3").wait_for()


def test_an_edit_marks_the_workbook_modified(page) -> None:
    assert page.locator(".statusbar").get_by_text("modified").count() == 0
    page.get_by_text("Widget").click()
    page.keyboard.press("Delete")
    page.locator(".statusbar").get_by_text("modified").wait_for()


def test_the_formula_bar_edits_the_active_cell(page) -> None:
    page.get_by_text("Widget").click()  # A4
    bar = page.locator(".formula-src")
    assert bar.input_value() == "Widget"
    bar.fill("Doohickey")
    bar.press("Enter")
    page.wait_for_function("() => window.__calls.set_cell.length === 1")
    assert page.evaluate("() => window.__calls.set_cell[0]") == [3, 0, "Doohickey"]


def test_the_name_box_jumps_to_a_typed_reference(page) -> None:
    box = page.locator(".name-box")
    box.fill("C7")
    box.press("Enter")
    assert box.input_value() == "C7"


def test_data_sweep_opens_and_plots(page) -> None:
    page.get_by_role("menuitem", name="Data").click()
    page.get_by_role("menuitem", name=re.compile("Sweep")).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_placeholder("B2").fill("B2")
    dialog.get_by_placeholder("A2:A3").fill("A2:A3")
    dialog.get_by_placeholder("C3").fill("C3")
    dialog.get_by_placeholder("0", exact=True).fill("0")
    dialog.get_by_placeholder("24").fill("24")
    dialog.get_by_role("button", name="Run").click()
    page.wait_for_selector("[data-testid='sweep-table']")


# --- optimization depth: models + grid annotations (Phase 4) ---------------


def _open_optimize(page) -> None:
    page.get_by_role("menuitem", name="Data").click()
    page.get_by_role("menuitem", name=re.compile("Optimize")).click()


def test_a_solve_paints_the_sensitivity_onto_the_grid(page) -> None:
    """The tables say the same thing, but a shadow price sitting on the
    constraint row is the part a terminal cannot render."""
    page.get_by_text("Widget").click()
    _open_optimize(page)
    page.get_by_role("button", name="Solve selection").click()
    page.get_by_test_id("solve-result").wait_for()
    page.keyboard.press("Escape")

    page.wait_for_selector(".annot.decision")
    binding = page.locator(".annot.binding")
    binding.wait_for()
    assert "shadow price" in (binding.get_attribute("title") or "")


def test_editing_clears_a_stale_solution_from_the_grid(page) -> None:
    page.get_by_text("Widget").click()
    _open_optimize(page)
    page.get_by_role("button", name="Solve selection").click()
    page.get_by_test_id("solve-result").wait_for()
    page.keyboard.press("Escape")
    page.wait_for_selector(".annot.decision")

    page.get_by_text("Gadget").click()
    page.keyboard.press("Delete")
    page.wait_for_selector(".annot", state="detached")


def test_a_model_can_be_saved_and_reloaded_from_the_workbook(page) -> None:
    _open_optimize(page)
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Objective").fill("B2")
    dialog.get_by_label("Decision variables").fill("A2:A3")
    dialog.get_by_label("Constraints").fill("C2:C4")
    dialog.get_by_label("Model name").fill("wyndor")
    dialog.get_by_role("button", name="Save").click()
    dialog.get_by_text("saved wyndor").wait_for()
    assert page.evaluate("() => window.__calls.save_model") == ["wyndor"]

    # It is now workbook state: reloading it refills the fields.
    dialog.get_by_label("Objective").fill("")
    dialog.get_by_label("Saved models").select_option("wyndor")
    assert dialog.get_by_label("Objective").input_value() == "B2"


def test_reading_a_model_from_the_selection_does_not_solve(page) -> None:
    page.get_by_text("Widget").click()
    _open_optimize(page)
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("button", name="Read from selection").click()
    dialog.get_by_text(re.compile("read from")).wait_for()
    assert dialog.get_by_label("Objective").input_value() == "B2"
    assert page.get_by_test_id("solve-result").count() == 0


# --- structural edits + sheet management -----------------------------------


def test_insert_row_shifts_the_sheet_down(page) -> None:
    page.get_by_text("Widget").click()  # A4
    page.get_by_role("menuitem", name="Insert").click()
    page.get_by_role("menuitem", name=re.compile("Insert Row Above")).click()
    page.wait_for_function("() => window.__calls.commands.length === 1")
    name, args, sel = page.evaluate("() => window.__calls.commands[0]")
    assert name == "insrow" and args == []
    assert (sel["r0"], sel["r1"]) == (3, 3)
    # The grid refetched: A4 is now blank and Widget moved to A5.
    page.get_by_text("Widget").click()
    assert page.locator(".name-box").input_value() == "A5"


def test_delete_row_removes_the_selected_row(page) -> None:
    page.get_by_text("Widget").click()  # A4
    page.get_by_role("menuitem", name="Insert").click()
    page.get_by_role("menuitem", name=re.compile("^Delete Row")).click()
    page.wait_for_function("() => window.__calls.commands.length === 1")
    name, _, sel = page.evaluate("() => window.__calls.commands[0]")
    assert name == "delrow" and (sel["r0"], sel["r1"]) == (3, 3)
    page.get_by_text("Gadget").click()  # slid up into the freed row
    assert page.locator(".name-box").input_value() == "A4"


def test_insert_column_uses_the_selected_span(page) -> None:
    """A two-column selection inserts two columns -- the menu says so, and the
    call must agree with the label the user read."""
    page.get_by_text("Item").click()  # A3
    page.keyboard.press("Shift+ArrowRight")  # A3:B3
    page.get_by_role("menuitem", name="Insert").click()
    assert page.get_by_role("menuitem", name="Insert 2 Columns Left").is_visible()
    page.get_by_role("menuitem", name="Insert 2 Columns Left").click()
    page.wait_for_function("() => window.__calls.commands.length === 1")
    name, _, sel = page.evaluate("() => window.__calls.commands[0]")
    assert name == "inscol" and (sel["c0"], sel["c1"]) == (0, 1)


def test_new_sheet_dialog_creates_and_switches_to_the_sheet(page) -> None:
    page.get_by_role("menuitem", name="Sheet").click()
    page.get_by_role("menuitem", name=re.compile("New Sheet")).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("textbox").fill("Budget")
    dialog.get_by_role("button", name="Create").click()
    page.wait_for_function(
        '() => JSON.stringify(window.__calls.sheet_ops) === \'[["add","Budget"]]\''
    )
    # The tab strip picked up the new sheet and made it active.
    page.get_by_label("Active sheet").click()
    assert page.get_by_role("option", name="Budget").is_visible()


def test_rename_dialog_starts_from_the_current_name(page) -> None:
    page.get_by_role("menuitem", name="Sheet").click()
    page.get_by_role("menuitem", name=re.compile("Rename")).click()
    dialog = page.get_by_role("dialog")
    assert dialog.get_by_role("textbox").input_value() == "Sheet1"
    dialog.get_by_role("textbox").fill("Inputs")
    dialog.get_by_role("button", name="Rename").click()
    page.wait_for_function(
        '() => JSON.stringify(window.__calls.sheet_ops) === \'[["rename","Sheet1","Inputs"]]\''
    )


def test_delete_sheet_removes_the_active_one(page) -> None:
    page.get_by_label("Active sheet").click()
    page.get_by_role("option", name="Data").click()
    page.get_by_role("menuitem", name="Sheet").click()
    page.get_by_role("menuitem", name="Delete").click()
    page.wait_for_function(
        '() => JSON.stringify(window.__calls.sheet_ops) === \'[["del","Data"]]\''
    )


def test_move_right_reorders_the_active_sheet(page) -> None:
    page.get_by_role("menuitem", name="Sheet").click()
    page.get_by_role("menuitem", name="Move Right").click()
    page.wait_for_function(
        '() => JSON.stringify(window.__calls.sheet_ops) === \'[["move","Sheet1",1]]\''
    )
    # The dropdown reflects the new order without a reload.
    page.get_by_label("Active sheet").click()
    options = page.get_by_role("option").all_text_contents()
    assert options == ["Data", "Sheet1"]


def test_a_failed_sheet_operation_reports_instead_of_failing_silently(page) -> None:
    page.get_by_role("menuitem", name="Sheet").click()
    page.get_by_role("menuitem", name=re.compile("New Sheet")).click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_role("textbox").fill("Data")  # already exists
    dialog.get_by_role("button", name="Create").click()
    page.get_by_text(re.compile("already exists")).wait_for()


# --- header selection, find, focus guard -----------------------------------


def test_clicking_a_row_header_selects_the_whole_row(page) -> None:
    """The gesture the Insert/Delete Row menu items are built around."""
    page.locator(".gut", has_text="4").first.click()
    assert page.locator(".name-box").input_value() == "A4"
    page.get_by_role("menuitem", name="Insert").click()
    # A whole-row selection spans every column, so the row count stays 1.
    assert page.get_by_role("menuitem", name="Delete Row").is_visible()
    page.keyboard.press("Escape")
    assert "256 cells" in page.locator(".statusbar").text_content()


def test_clicking_a_column_header_selects_the_whole_column(page) -> None:
    page.locator(".hdr", has_text="B").first.click()
    assert page.locator(".name-box").input_value() == "B1"
    assert "1024 cells" in page.locator(".statusbar").text_content()


def test_shift_clicking_a_row_header_extends_over_a_span(page) -> None:
    page.locator(".gut", has_text="3").first.click()
    page.locator(".gut", has_text="5").first.click(modifiers=["Shift"])
    page.get_by_role("menuitem", name="Insert").click()
    assert page.get_by_role("menuitem", name="Delete 3 Rows").is_visible()


def test_a_row_header_selection_deletes_that_row(page) -> None:
    page.locator(".gut", has_text="4").first.click()  # the Widget row
    page.get_by_role("menuitem", name="Insert").click()
    page.get_by_role("menuitem", name=re.compile("^Delete Row")).click()
    page.wait_for_function("() => window.__calls.commands.length === 1")
    name, _, sel = page.evaluate("() => window.__calls.commands[0]")
    assert name == "delrow" and (sel["r0"], sel["r1"]) == (3, 3)


def test_find_jumps_to_a_match_and_steps_through(page) -> None:
    page.keyboard.press("Control+f")
    find = page.get_by_label("Find", exact=True)
    find.fill("g")  # Widget, Gadget, Gizmo, 'gridcalc demo'
    page.wait_for_function("() => window.__calls.search.length > 0")
    # Lands on the first hit without waiting for Enter.
    assert page.locator(".name-box").input_value() == "A1"
    find.press("Enter")
    assert page.locator(".name-box").input_value() == "A4"
    find.press("Shift+Enter")
    assert page.locator(".name-box").input_value() == "A1"


def test_find_reports_the_match_count_and_an_empty_result(page) -> None:
    page.keyboard.press("Control+f")
    find = page.get_by_label("Find", exact=True)
    find.fill("Widget")
    page.get_by_text("1 of 1").wait_for()
    find.fill("nothing-matches-this")
    page.get_by_text("no matches").wait_for()


def test_find_closes_on_escape_and_returns_focus_to_the_grid(page) -> None:
    page.keyboard.press("Control+f")
    page.get_by_label("Find", exact=True).fill("Gadget")
    page.get_by_label("Find", exact=True).press("Escape")
    page.wait_for_selector(".findbar", state="detached")
    # Focus is back on the sheet: arrow keys navigate rather than doing nothing.
    before = page.locator(".name-box").input_value()
    page.keyboard.press("ArrowDown")
    assert page.locator(".name-box").input_value() != before


def test_ctrl_z_in_a_dialog_field_does_not_undo_the_workbook(page) -> None:
    """The field owns its own undo. Before the guard, fixing a typo while
    typing a cell ref here reverted the sheet behind the dialog."""
    page.get_by_role("menuitem", name="Data").click()
    page.get_by_role("menuitem", name=re.compile("Goal Seek")).click()
    field = page.get_by_role("dialog").get_by_placeholder("A1")
    field.click()
    field.type("B7")
    page.keyboard.press("Control+z")
    assert page.evaluate("() => window.__calls.undo_calls || 0") == 0


def test_ctrl_z_on_the_grid_still_undoes(page) -> None:
    """The guard must not have disarmed the shortcut everywhere."""
    page.get_by_text("Widget").click()
    page.keyboard.press("Control+z")
    page.wait_for_function("() => window.__calls.undo_calls === 1")


# --- command palette -------------------------------------------------------


def _palette(page):
    page.keyboard.press("Control+k")
    return page.get_by_role("dialog")


def test_palette_opens_and_lists_commands(page) -> None:
    dialog = _palette(page)
    assert dialog.get_by_role("option", name=re.compile("Undo")).is_visible()
    assert dialog.get_by_role("option", name=re.compile("Goal seek")).is_visible()


def test_palette_filters_as_you_type_and_runs_on_enter(page) -> None:
    dialog = _palette(page)
    dialog.get_by_label("Command").fill("save")
    dialog.get_by_label("Command").press("Enter")
    page.wait_for_function("() => window.__calls.save === 1")
    page.wait_for_selector("[role='dialog']", state="detached")


def test_palette_matches_a_scattered_subsequence(page) -> None:
    """Typing letters that only appear in order still finds the command --
    the reason to type into a palette rather than read a menu."""
    dialog = _palette(page)
    dialog.get_by_label("Command").fill("fld")  # F-i-L-l D-own
    assert "Fill down" in dialog.get_by_role("option").first.text_content()


def test_palette_arrow_keys_move_the_highlight(page) -> None:
    dialog = _palette(page)
    dialog.get_by_label("Command").fill("sheet")
    first = dialog.get_by_role("option").first
    assert first.get_attribute("aria-selected") == "true"
    dialog.get_by_label("Command").press("ArrowDown")
    assert first.get_attribute("aria-selected") == "false"
    assert dialog.get_by_role("option").nth(1).get_attribute("aria-selected") == "true"


def test_palette_reports_when_nothing_matches(page) -> None:
    dialog = _palette(page)
    dialog.get_by_label("Command").fill("zzzzzz")
    assert dialog.get_by_text("No matching command").is_visible()


def test_a_command_needing_a_value_prompts_for_it(page) -> None:
    """The second step is what lets `:width`/`:name` live in the registry
    without a bespoke dialog each."""
    page.get_by_text("Widget").click()  # a selection for the name to cover
    dialog = _palette(page)
    dialog.get_by_label("Command").fill("define name")
    dialog.get_by_label("Command").press("Enter")
    field = dialog.get_by_label("Name")
    field.fill("Revenue")
    field.press("Enter")
    page.wait_for_function("() => window.__calls.commands.length === 1")
    name, args, _ = page.evaluate("() => window.__calls.commands[0]")
    assert name == "name" and args == ["Revenue"]


def test_escape_from_the_argument_step_returns_to_the_list(page) -> None:
    dialog = _palette(page)
    dialog.get_by_label("Command").fill("go to")
    dialog.get_by_label("Command").press("Enter")
    dialog.get_by_label("Reference").press("Escape")
    # Back to the command list, not out of the palette entirely.
    assert dialog.get_by_label("Command").is_visible()


def test_palette_go_to_moves_the_cursor(page) -> None:
    dialog = _palette(page)
    dialog.get_by_label("Command").fill("go to")
    dialog.get_by_label("Command").press("Enter")
    field = dialog.get_by_label("Reference")
    field.fill("C7")
    field.press("Enter")
    page.wait_for_selector("[role='dialog']", state="detached")
    assert page.locator(".name-box").input_value() == "C7"


def test_palette_recalculate_reaches_the_bridge(page) -> None:
    dialog = _palette(page)
    dialog.get_by_label("Command").fill("recalc")
    dialog.get_by_label("Command").press("Enter")
    page.wait_for_function("() => window.__calls.commands.some(c => c[0] === 'recalc')")


def test_a_refused_command_reports_rather_than_failing_silently(page) -> None:
    page.get_by_text("Widget").click()
    dialog = _palette(page)
    dialog.get_by_label("Command").fill("define name")
    dialog.get_by_label("Command").press("Enter")
    field = dialog.get_by_label("Name")
    field.fill("9bad")
    field.press("Enter")
    page.get_by_text(re.compile("not a usable name")).wait_for()
