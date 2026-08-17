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

See [Desktop app](desktop.md) for what it does and what it does not do yet. The curses app has no such dependency.

## From a source checkout

The desktop app loads a compiled React bundle that is a build artifact and is not in git, so build it before running from a checkout:

```sh
make build       # C++ extensions (_core, _opt)
make web-build   # React client -> src/gridcalc/web/static/index.html
```

A checkout that has not run `make web-build` exits with a message telling you to. Released wheels and sdists ship the bundle already built.
