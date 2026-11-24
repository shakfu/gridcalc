# Install

Two options:

```sh
pip install gridcalc            # core: zero third-party runtime deps
pip install 'gridcalc[extras]'  # adds numpy, pandas, pygments
```

Or with [uv](https://docs.astral.sh/uv/): `uv tool install 'gridcalc[extras]'`.

## The core install

The **core** install has **zero third-party runtime dependencies on Linux and macOS**. The full 300+ Excel function library -- statistical distributions, financial functions, `LINEST`/`TREND` regression, and the rest -- works on the standard library alone.

Two exceptions, neither of them optional features:

- The 3.10 wheel pulls `tomli` for config-file parsing; 3.11 and later use the stdlib `tomllib`.

- On Windows only, `windows-curses` is pulled in, because curses is not in the Windows standard library.

## The `[extras]` bundle

One bundle rather than several, because the features overlap. It enables, all at once:

- `np.array(...)` in formulas, LAPACK-backed solvers, and a faster `LINEST`.

- `pd.DataFrame(...)`, the `:pd load`/`:pd save` commands, and DataFrame cell display.

- Pygments syntax highlighting in the load-time trust prompt.

## The `[web]` extra

The desktop frontend needs a native webview stack, deliberately kept out of the lean terminal build:

```sh
pip install 'gridcalc[web]'
gridcalc-web                    # demo workbook, or: gridcalc-web book.json
```

The extra installs `pywebview`, which draws in the platform's *native* webview rather than bundling a browser. macOS and Windows supply that themselves (WKWebView, WebView2), but on Linux it needs a GTK or Qt backend that is not a Python package. For GTK on Debian/Ubuntu:

```sh
sudo apt install python3-gi gir1.2-webkit2-4.1
```

Those bindings are compiled against the system interpreter, so a virtualenv only loads them when it is the same Python minor version; otherwise install a Qt backend into the environment instead (`pip install pyqt6 pyqt6-webengine`). Without a backend, `gridcalc-web` exits saying it needs QT or GTK. `make web-run` probes for the system bindings and adds them to `PYTHONPATH` when they work.

See [Desktop app](desktop.md) for what it does and what it does not do yet. The curses app has no such dependency.

## The `[pulp]` extra

Runs sheet models under the PuLP library and its solvers, instead of the builtin subset on HiGHS ([Cross-tab models](guide/models.md#solvers)):

```sh
pip install 'gridcalc[pulp]'
```

It installs PuLP 2 or 3, which bundles the CBC solver. PuLP 4 is a different API and is not supported.

## The `[pyomo]` extra

Runs sheet models written with [Pyomo](https://www.pyomo.org) ([Cross-tab models](guide/models.md#solvers)):

```sh
pip install 'gridcalc[pyomo]'
```

Pyomo bundles no solver. Install one it can start, such as `glpsol` from GLPK ([below](#gmpl-models)) or `cbc`, or `pip install highspy` for its in-process `appsi_highs`. For nonlinear models, install Ipopt (`brew install ipopt`, `apt install coinor-libipopt-dev` and its `ipopt` program, or a COIN-OR build); `bonmin` and `couenne` are also allowed.

## GMPL models

Models in GMPL (GNU MathProg) run under `glpsol` from GLPK, which is not a Python package and is not bundled: GLPK is GPL-3, and gridcalc only starts it as a program. Install it with `brew install glpk`, `apt install glpk-utils`, or a Windows build, so that `glpsol` is on `PATH`.

## From a source checkout

The desktop app loads a compiled React bundle that is a build artifact and is not in git, so build it before running from a checkout:

```sh
make build       # C++ extensions (_core, _opt)
make web-build   # React client -> src/gridcalc/web/static/index.html
```

`make web-build` needs [Bun](https://bun.sh), which serves as both the package manager and the JavaScript runtime for the client; Node and npm are not required. Only the desktop frontend needs it -- the terminal app builds and runs without any JavaScript toolchain.

`make build` compiles C++ extensions, so it needs the Python development headers. A distro interpreter usually splits those into a separate package, and building against one without it fails in CMake with `Could NOT find Python (missing: Interpreter Development.Module)`. So `pyproject.toml` sets `python-preference = "only-managed"`: uv downloads its own interpreter, which always ships the headers, and a fresh clone needs nothing installed but uv. `.python-version` chooses the version. To build against your own interpreter instead, install its `-dev` package and pass `--python-preference system`.

A checkout that has not run `make web-build` exits with a message telling you to. Released wheels and sdists ship the bundle already built.
