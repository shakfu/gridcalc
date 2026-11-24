"""The model panel and overlay in a real browser, against the real Python `Api`.

`test_web_bundle.py` mocks the bridge in JavaScript. Here each bridge call is
forwarded to a live `gridcalc.web.Api` through Playwright's `expose_function`,
so CodeMirror, the background solve and the overlay run end to end.
"""

from __future__ import annotations

import inspect
import json

import pytest

from gridcalc.web import Api

from .test_web_bundle import BUNDLE, _bundle_built

sync_api = pytest.importorskip("playwright.sync_api")

pytestmark = pytest.mark.browser

_BRIDGE = """
  (names) => {
    const api = {};
    for (const n of names) {
      api[n] = async (...args) => JSON.parse(await window.__py(n, JSON.stringify(args)));
    }
    window.pywebview = { api };
    window.dispatchEvent(new Event('pywebviewready'));
  }
"""


@pytest.fixture
def page(beer):
    if not _bundle_built():
        pytest.skip("web bundle not built; run `make web-build`")
    api = Api(beer)
    names = [n for n, f in inspect.getmembers(Api, inspect.isfunction) if not n.startswith("_")]

    def call(name: str, args: str) -> str:
        return json.dumps(getattr(api, name)(*json.loads(args)))

    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except sync_api.Error as exc:
            pytest.skip(f"chromium not available: {exc}")
        pg = browser.new_page(viewport={"width": 1400, "height": 800})
        pg.expose_function("__py", call)
        pg.set_content(BUNDLE.read_text(encoding="utf-8"))
        pg.evaluate(_BRIDGE, names)
        pg.wait_for_selector(".cell-layer .cell")
        pg.api = api  # type: ignore[attr-defined]
        yield pg
        browser.close()


def _menu(page, item: str) -> None:
    page.get_by_role("menuitem", name="Data").click()
    page.get_by_role("menuitem", name=item).click()


def test_edit_solve_and_overlay_end_to_end(page) -> None:
    from tests.test_lpmodel import BEER_MODEL

    _menu(page, "Model Editor")
    editor = page.locator(".model-panel .cm-content")
    editor.wait_for()
    assert editor.get_attribute("data-language") == "python"

    # Typed through CodeMirror's real input path, then saved after the pause.
    editor.click()
    page.keyboard.insert_text(BEER_MODEL)
    page.wait_for_function(
        "() => document.querySelector('.model-panel .cm-content').textContent.includes('LpProblem')"
    )
    page.wait_for_timeout(800)
    assert page.api._g._active.model_text == BEER_MODEL

    # Syntax highlighting: keywords are styled spans, not plain text.
    assert page.locator(".model-panel .cm-content span").count() > 10

    page.get_by_role("button", name="Solve").click()
    page.get_by_text("Optimal, objective 8400, 11 cells written").first.wait_for(timeout=20_000)
    assert page.api._g._active._cells[(1, 13)].text == "Optimal"
    page.locator(".cell-layer .cell", has_text="Optimal").wait_for()

    page.get_by_label("Show model").check()
    box = page.locator('[data-testid="model-box-costs"]')
    box.wait_for()
    assert box.inner_text() == "costs[Warehouses,Bars]"
    assert page.locator(".model-box").count() == 7


def test_failed_model_puts_the_cursor_on_its_line(page) -> None:
    page.api.set_model("x = 1\nraise ValueError('bad')\n")
    _menu(page, "Model Editor")
    page.locator(".model-panel .cm-content").wait_for()
    page.get_by_role("button", name="Solve").click()
    page.get_by_text("line 2: ValueError: bad").first.wait_for(timeout=20_000)
    active = page.locator(".model-panel .cm-activeLine")
    assert "raise ValueError" in active.inner_text()


def test_grid_stays_usable_while_a_model_runs(page) -> None:
    page.api.set_model("while True:\n    pass\n")
    _menu(page, "Model Editor")
    page.get_by_role("button", name="Solve").click()
    page.get_by_role("button", name="Cancel").wait_for()
    # An edit goes through while the model runs.
    page.locator(".cell-layer .cell", has_text="Warehouses").first.click()
    page.api.set_cell(20, 0, "typed")
    assert page.api.cell_source(20, 0) == "typed"
    page.get_by_role("button", name="Cancel").click()
    page.get_by_text("model cancelled").first.wait_for(timeout=10_000)
    page.get_by_role("button", name="Solve").wait_for()


def test_data_items_dialog_jumps_to_an_item(page) -> None:
    page.get_by_role("menuitem", name="Data").click()
    page.get_by_role("menuitem", name="Data Items…").click()
    page.get_by_role("button", name="Sheet1!C4:G5").click()
    page.wait_for_function("() => document.querySelector('.name-box').value === 'C4'")
    assert page.locator(".sel-rect").count() == 1
