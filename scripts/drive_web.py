"""Launch the real web app and drive it, headfully, with screenshots.

    make web-drive                # sheet switch preserves cursor and scroll
    make web-drive CHECK=solve    # a solve paints the grid, leaving clears it
    make web-drive SHOT=--screen  # grab the whole display, not just the window

Everything else that guards the web frontend runs against a substitute: vitest
in happy-dom, and the Chromium bundle suite against a mocked
`window.pywebview.api`.
This is the one thing that runs the shipped bundle against the shipped engine
in the production webview, which matters for two classes of claim the other
layers structurally cannot make:

* **Layout.** happy-dom does no layout -- every box measures zero, and
  `scrollTop` is a stored number with no scrolling behind it -- so the
  component tests can only assert which rows the grid *asks the bridge* for,
  never where it actually sits.
* **The real webview.** The Playwright suite is Chromium -- a faithful proxy
  for WKWebView / WebView2 / WebKitGTK, not the production engine.

It is a driver, not a test: it needs a display, it is not deterministic enough
to gate a build, and it is excluded from `make qa` deliberately. Reach for it
when changing anything positional in the grid, and when a reviewer would
reasonably ask "but did you *look* at it".

Mirrors `gridcalc.web.run()` -- same window, same real `Api` over a real
workbook -- but hands `webview.start` a driver thread that pokes the live
webview through `evaluate_js`.

Four things cost real time to work out. All are quirks of scripting this UI,
not app bugs, and they are the reason this file is worth keeping:

* Keydowns dispatched in one synchronous loop all read the same pre-render
  cursor, so only the last one appears to take. Space them (`key()` sleeps).
* Radix's Select and Menubar do not commit on synthesized pointer sequences.
  Drive them by keyboard: focus the trigger, Enter to open, then a first-letter
  typeahead (Select) or straight Enter (Menubar -- opening already highlights
  the first item, so an ArrowDown walks *past* it).
* Radix mounts dropdown content in a portal a tick or two after the trigger
  fires, and a typeahead sent before it exists is dropped silently -- which
  reads as "the app ignored the switch". Poll for the options; do not sleep.
* React ignores a plain `input.value = x`; go through the native setter and
  dispatch the event React listens for. See `SET_SELECT`.

Screenshots need macOS Screen Recording permission for the terminal running
this; without it `screencapture` fails with "could not create image from
display" and the run still completes, since the DOM probe is the real evidence.
They crop to the app window (`--window`, the default) so the output is usable
in the README; `--screen` grabs the whole display instead, which is what you
want when the bug is in where the window itself sits. Either way they are
Retina-sized -- `sips -Z 1400` before reading one.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import webview

from gridcalc.loader import load_workbook
from gridcalc.web import Api, _load_html

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scripts" / "out"  # gitignored: screenshots and a scratch workbook

# --- probes and gestures --------------------------------------------------

PROBE = """
(function () {
  var nb = document.querySelector('.name-box');
  var sc = document.querySelector('.grid-scroll');
  var tr = document.querySelector('[aria-label="Active sheet"]');
  var marks = Array.prototype.slice.call(document.querySelectorAll('.annot'));
  return JSON.stringify({
    cursor: nb ? nb.value : null,
    scrollTop: sc ? Math.round(sc.scrollTop) : null,
    sheet: tr ? tr.textContent.replace(/\\u25be/g, '').trim() : null,
    cells: document.querySelectorAll('.cell-layer .cell').length,
    firstRow: (function () {
      var g = document.querySelector('.gut');
      return g ? g.textContent.trim() : null;
    })(),
    annots: marks.length,
    roles: marks.map(function (e) { return e.className.replace('annot ', ''); }),
    firstTitle: marks.length ? marks[0].getAttribute('title') : null,
    dialog: (function () {
      var d = document.querySelector('[role="dialog"]');
      if (!d) return false;
      var h = d.querySelector('h1,h2,h3,.dialog-title');
      return h ? h.textContent.trim() : '(untitled)';
    })()
  });
})()
"""

KEY = """
(function () {
  var el = TARGET;
  if (!el) return 'no target';
  el.focus();
  el.dispatchEvent(new KeyboardEvent('keydown', {key: KEYNAME, bubbles: true, cancelable: true}));
  return 'ok';
})()
"""

OPTIONS = """
JSON.stringify(Array.prototype.slice.call(document.querySelectorAll('[role="option"]'))
  .map(function (e) { return e.textContent.trim(); }))
"""

SET_SELECT = """
(function () {
  var el = document.querySelector('[aria-label="Saved models"]');
  if (!el) return 'no model select';
  var set = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  set.call(el, MODEL);
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return 'loaded ' + el.value;
})()
"""

CLICK = """
(function () {
  var hit = Array.prototype.slice.call(document.querySelectorAll('button'))
    .filter(function (b) { return b.textContent.trim() === LABEL && !b.disabled; })[0];
  if (!hit) return 'no enabled button ' + LABEL;
  hit.click();
  return 'clicked ' + LABEL;
})()
"""

TRIGGER = "document.querySelector('[aria-label=\"Active sheet\"]')"
ACTIVE = "document.activeElement"
GRID = "document.querySelector('.grid-scroll')"
DATA_MENU = (
    "Array.prototype.slice.call(document.querySelectorAll('[role=\"menuitem\"]'))"
    ".filter(function (e) { return e.textContent.trim() === 'Data'; })[0]"
)

log: list[str] = []


def say(msg: str) -> None:
    log.append(msg)
    print(msg, flush=True)


def probe(win) -> dict:
    return json.loads(win.evaluate_js(PROBE))


def key(win, target: str, name: str, pause: float = 0.3) -> str:
    out = win.evaluate_js(KEY.replace("TARGET", target).replace("KEYNAME", json.dumps(name)))
    time.sleep(pause)
    return out


def click(win, label: str, pause: float = 1.5) -> str:
    out = win.evaluate_js(CLICK.replace("LABEL", json.dumps(label)))
    time.sleep(pause)
    return out


def switch(win, name: str) -> bool:
    """Pick a sheet from the toolbar dropdown, keyboard-only."""
    key(win, TRIGGER, "Enter", pause=0.2)
    for _ in range(20):
        if name in json.loads(win.evaluate_js(OPTIONS)):
            break
        time.sleep(0.15)
    else:
        say(f"  dropdown never offered {name!r}")
        return False
    key(win, ACTIVE, name[0], pause=0.4)  # typeahead
    key(win, ACTIVE, "Enter", pause=0.2)
    for _ in range(20):
        if probe(win)["sheet"] == name:
            time.sleep(0.8)  # let the remount settle before probing for real
            return True
        time.sleep(0.15)
    say(f"  never landed on {name!r}")
    return False


def wait_ready(win) -> dict:
    st: dict = {}
    for _ in range(80):
        st = probe(win)
        if st["cursor"] and st["cells"]:
            return st
        time.sleep(0.25)
    return st


# Absolute so the call cannot be redirected by PATH, which is also what keeps
# ruff's S607 quiet. macOS-only; there is no screenshot on other platforms and
# the run reports that rather than failing.
SCREENCAPTURE = "/usr/sbin/screencapture"


WINDOW_ONLY = True  # --screen turns it off


def window_id() -> int | None:
    """CGWindowID of this process's window, for ``screencapture -l``.

    The webview runs in-process, so the window is ours: filter the on-screen
    list by our own pid and take the largest window on the normal layer (layer
    0 excludes the menu bar and any helper surfaces). Quartz comes with the
    pyobjc pywebview already needs on macOS; anywhere else the import fails
    and the caller falls back to a full-screen grab.
    """
    try:
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGNullWindowID,
            kCGWindowListOptionOnScreenOnly,
        )
    except ImportError:
        return None
    info = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []
    mine = [
        w
        for w in info
        if w.get("kCGWindowOwnerPID") == os.getpid() and w.get("kCGWindowLayer") == 0
    ]
    if not mine:
        return None

    def area(w: dict) -> float:
        b = w["kCGWindowBounds"]
        return float(b["Width"]) * float(b["Height"])

    return int(max(mine, key=area)["kCGWindowNumber"])


def shoot(tag: str) -> str:
    if not Path(SCREENCAPTURE).exists():
        return "skipped (no screencapture -- macOS only)"
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{tag}.png"
    # -o drops the drop shadow, which in window mode is a wide band of
    # semi-transparent desktop around the frame.
    argv = [SCREENCAPTURE, "-x", "-o"]
    scope = "screen"
    if WINDOW_ONLY:
        wid = window_id()
        if wid is None:
            scope = "screen (no window id)"
        else:
            argv += ["-l", str(wid)]
            scope = "window"
    r = subprocess.run(  # noqa: S603 -- fixed argv, no shell, no user input
        [*argv, str(out)], capture_output=True, text=True
    )
    if r.returncode == 0 and out.exists():
        return f"{out.relative_to(ROOT)} ({scope})"
    return f"FAILED ({(r.stderr or '').strip() or 'unknown'}) -- grant Screen Recording"


def report(checks: dict[str, bool]) -> bool:
    say("")
    for what, ok in checks.items():
        say(f"  [{'PASS' if ok else 'FAIL'}] {what}")
    ok = all(checks.values())
    say(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    return ok


# --- check: a sheet switch preserves the view -----------------------------


def check_sheets(win) -> None:
    say(f"booted:  {wait_ready(win)}")
    home = probe(win)["sheet"]

    say("--- move the cursor and scroll down ---")
    for k in ["ArrowDown"] * 5 + ["ArrowRight"] * 2:
        key(win, GRID, k)
    win.evaluate_js("document.querySelector('.grid-scroll').scrollTop = 1100")
    time.sleep(0.9)
    before = probe(win)
    say(f"before:  {before}")
    say(f"shot:    {shoot('01-before')}")

    other = "Inputs" if home != "Inputs" else "Metrics"
    say(f"--- switch to {other} (never visited) ---")
    switch(win, other)
    away = probe(win)
    say(f"away:    {away}")
    say(f"shot:    {shoot('02-away')}")

    say(f"--- switch back to {home} ---")
    switch(win, home)
    back = probe(win)
    say(f"back:    {back}")
    say(f"shot:    {shoot('03-back')}")

    report(
        {
            "left the sheet at all": away["sheet"] == other,
            "unvisited sheet starts at A1": away["cursor"] == "A1",
            "unvisited sheet starts at the top": away["scrollTop"] == 0,
            "returned to the right sheet": back["sheet"] == home,
            "cursor restored": back["cursor"] == before["cursor"],
            "scroll restored": back["scrollTop"] == before["scrollTop"],
        }
    )


# --- check: a solve does not follow the user to another sheet -------------


def check_solve(win) -> None:
    say(f"booted:  {wait_ready(win)}")

    say("--- Data > Optimize ---")
    key(win, DATA_MENU, "Enter", pause=0.8)
    key(win, ACTIVE, "Enter", pause=1.2)  # the first item is already highlighted
    say(f"dialog:  {probe(win)['dialog']}")

    say("--- load the saved `default` model and solve ---")
    say(f"  {win.evaluate_js(SET_SELECT.replace('MODEL', json.dumps('default')))}")
    time.sleep(0.5)
    say(f"  {click(win, 'Solve', pause=2.0)}")

    win.evaluate_js(
        "document.dispatchEvent(new KeyboardEvent('keydown',"
        "{key:'Escape',bubbles:true,cancelable:true}))"
    )
    time.sleep(0.8)
    painted = probe(win)
    say(f"painted: {painted}")
    say(f"shot:    {shoot('10-painted')}")

    say("--- switch to the other sheet ---")
    switch(win, "Notes")
    away = probe(win)
    say(f"away:    {away}")
    say(f"shot:    {shoot('11-away')}")

    say("--- and back ---")
    switch(win, "Sheet1")
    back = probe(win)
    say(f"back:    {back}")
    say(f"shot:    {shoot('12-back')}")

    report(
        {
            "the real solver painted the sheet": painted["annots"] > 0,
            "it marked binding constraints": "binding" in painted["roles"],
            "leaving the sheet clears the marks": away["annots"] == 0,
            "they do not come back on return": back["annots"] == 0,
            "the sheet switch itself worked": away["sheet"] == "Notes"
            and back["sheet"] == "Sheet1",
        }
    )


# --- entry ----------------------------------------------------------------


def lp_two_sheets() -> str:
    """The LP example plus an empty second sheet, so a solve has somewhere to
    be switched away from. Generated rather than committed -- it is derived."""
    g = load_workbook(str(ROOT / "examples" / "example_lp.json"))
    g.add_sheet("Notes")
    g.set_active(0)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "lp_two_sheets.json"
    g.jsonsave(str(out))
    return str(out)


CHECKS = {"sheets": check_sheets, "solve": check_solve}


def main() -> None:
    global WINDOW_ONLY

    p = argparse.ArgumentParser(
        prog="drive_web.py",
        description="Drive the shipped web bundle in a real webview, with screenshots.",
    )
    p.add_argument(
        "check",
        nargs="?",
        default="sheets",
        choices=sorted(CHECKS),
        help="which behaviour to drive (default: sheets)",
    )
    shot = p.add_mutually_exclusive_group()
    shot.add_argument(
        "--window",
        dest="window_only",
        action="store_true",
        default=True,
        help="crop shots to the app window (default)",
    )
    shot.add_argument(
        "--screen",
        dest="window_only",
        action="store_false",
        help="grab the whole display instead -- for when the question is where the window sits",
    )
    args = p.parse_args()
    WINDOW_ONLY = args.window_only
    which = args.check
    book = (
        str(ROOT / "examples" / "example_multisheet.json") if which == "sheets" else lp_two_sheets()
    )

    g = load_workbook(book)
    api = Api(g)
    win = webview.create_window(
        f"gridcalc - {Path(book).name}",
        html=_load_html(),
        js_api=api,
        width=1200,
        height=800,
        confirm_close=False,
    )
    api._window = win

    def drive(w) -> None:
        try:
            CHECKS[which](w)
        except Exception as exc:  # noqa: BLE001 -- a driver, not library code
            say(f"driver error: {exc!r}")
        finally:
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f"{which}.log").write_text("\n".join(log), encoding="utf-8")
            w.destroy()

    webview.start(drive, win)


if __name__ == "__main__":
    main()
