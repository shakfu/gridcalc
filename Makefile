.PHONY: all sync build rebuild test test-stdlib lint format typecheck qa clean  \
       distclean wheel wheel-abi3 build-abi3 sdist dist dist-abi3 check \
       publish-test publish upgrade coverage coverage-html release \
       docs docs-serve docs-deploy docs-clean \
       bench bench-clean web-build web-dev web-jstest web-qa web-run \
       web-drive help

# Default target
all: build

# The packaging config force-includes the web bundle (pyproject.toml), so the
# file must exist before ANY package build -- and docs/install.md tells a fresh
# checkout to run `make build` BEFORE `make web-build`. Without the rule below
# those two deadlock: the build needs the file that web-build produces, and a
# clone cannot follow its own instructions.
#
# So generate a placeholder when the bundle is absent. It keeps the terminal-only
# path buildable with no Bun installed, `web-build` overwrites it with the real
# thing, and it is deliberately inert: it carries a marker that `_load_html()`
# refuses to open a window on, and omits the `id="root"` mount point that CI
# greps for, so a placeholder cannot pass for a bundle in a distribution.
BUNDLE = src/gridcalc/web/static/index.html

$(BUNDLE):
	@mkdir -p $(dir $(BUNDLE))
	@printf '%s\n' \
		'<!doctype html>' \
		'<!-- gridcalc:placeholder-bundle -->' \
		'<meta charset="utf-8">' \
		'<title>gridcalc: web UI not built</title>' \
		'<p>Placeholder, not the compiled client. Run <code>make web-build</code>.' \
		> $(BUNDLE)

# Sync environment (initial setup, installs dependencies + package)
sync: $(BUNDLE)
	@uv sync

# Build/rebuild the extension after code changes
build: $(BUNDLE)
	@uv sync --reinstall-package gridcalc

# Alias for build
rebuild: build

# Run tests (excludes PTY/curses integration tests; see test-tty for those)
test: $(BUNDLE)
	@GRIDCALC_SANDBOX=1 uv run pytest tests/ -v

# Run only the PTY-driven curses integration tests. These spawn a real
# gridcalc subprocess on a pseudo-terminal and assert on rendered output,
# so they require the built binary (run `make build` first) and a usable
# xterm-256color terminfo entry.
test-tty:
	@GRIDCALC_SANDBOX=1 uv run pytest tests/integration/ -v -m tty

# Run the Playwright web-frontend tests. These load the web view in headless
# Chromium with a mocked pywebview bridge and assert on the DOM, so they need
# `pip install gridcalc[web]` plus `uv run playwright install chromium`. The
# bundle smoke additionally needs `make web-build` (else it skips).
test-web:
	@GRIDCALC_SANDBOX=1 uv run pytest tests/integration/ -v -m browser

# The client toolchain runs on Bun -- one binary that is both the package
# manager and the runtime, so no Node/npm is required. `--bun` is load-bearing:
# without it `bun run` honours the `#!/usr/bin/env node` shebang in
# node_modules/.bin and silently shells out to Node, which defeats the point
# and fails on a machine that has none.
FRONTEND = src/gridcalc/web/frontend

# Build the React web frontend (web/frontend) into a single self-contained
# static/index.html that the pywebview window serves. Requires Bun.
web-build:
	@bun install --cwd $(FRONTEND)
	@bun --bun run --cwd $(FRONTEND) build

# Run the frontend dev server (browser + mock bridge, hot reload) for fast UI
# iteration without launching pywebview.
web-dev:
	@bun --bun run --cwd $(FRONTEND) dev

# Run the frontend component tests (vitest + React Testing Library).
web-jstest:
	@bun --bun run --cwd $(FRONTEND) test

# pywebview draws in a *native* webview, so beyond the `web` extra it needs a
# GTK or Qt backend -- which is not a Python package uv can resolve. On
# Debian/Ubuntu the GTK side is the system `python3-gi` plus the WebKit2
# typelib, and a uv venv cannot see system site-packages. Those bindings are a
# compiled extension, so they only load when the venv's Python is the same minor
# version as the system interpreter that built them.
#
# Hence the probe: add the system path only when `gi` genuinely imports under
# the venv. A mismatched venv then falls through to pywebview's own "install a
# backend" message instead of an ImportError traceback, and a machine with no
# system bindings at all is unaffected. Lazily expanded (`=`, not `:=`) so the
# probe runs only for the two targets that open a window, never on `make test`.
SYS_SITE ?= /usr/lib/python3/dist-packages
GTK_PATH = $(shell PYTHONPATH=$(SYS_SITE) uv run --extra web python -c 'import gi' \
        >/dev/null 2>&1 && echo $(SYS_SITE))

# Launch the desktop web app (serves the built static/index.html in a pywebview
# window). Run `make web-build` first. `--extra web` is required: pywebview is
# an optional dependency, so a plain `uv run` resolves an environment without it
# and the entry point dies on `import webview`.
web-run:
	@GRIDCALC_SANDBOX=1 PYTHONPATH=$(GTK_PATH) uv run --extra web gridcalc-web

# Launch the real app and drive it, with screenshots into scripts/out/.
# `CHECK=sheets` (default) verifies a sheet switch preserves cursor and scroll;
# `CHECK=solve` verifies a solve paints the grid and that leaving clears it.
# Deliberately not part of `make qa`: it needs a display and is a driver rather
# than a test. It is the only layer that runs the shipped bundle in the real
# webview -- the vitest layer does no layout, and the Playwright suite is
# Chromium rather than the shipped webview.
# Shots crop to the app window; `SHOT=--screen` grabs the whole display.
CHECK ?= sheets
SHOT ?= --window
web-drive:
	@GRIDCALC_SANDBOX=1 PYTHONPATH=$(GTK_PATH) uv run --extra web python scripts/drive_web.py $(CHECK) $(SHOT)

# Run tests in an isolated environment without the optional extras
# (numpy / pandas). Verifies the optional-dep skipif guards work and
# the core engine operates without any third-party runtime deps.
# Pygments arrives transitively via pytest -- harmless; tui.py guards
# its use with try/except.
#
# `--no-cache` is not optional here. uv keys its built-wheel cache for a local
# path on the project metadata, not on the source files, so editing
# src/gridcalc/*.py does NOT invalidate it: without this the target happily
# reinstalls a wheel built hours ago and reports a pass for code that is no
# longer in the tree. (`--refresh`, `--refresh-package` and `--reinstall` all
# fail to evict it; only `--no-cache` does.) The price is a full C++ rebuild --
# about 50s against ~2s cached -- which is why this is an occasional gate and
# not part of `make qa`.
test-stdlib:
	@GRIDCALC_SANDBOX=1 uv run --isolated --no-project --no-cache \
		--with pytest --with . pytest tests/ -v

# Lint with ruff
lint:
	@uv run ruff check --fix src/ tests/ scripts/

# Format with ruff
format:
	@uv run ruff format src/ tests/ scripts/

# Type check with mypy
typecheck:
	@uv run mypy src/gridcalc/ --exclude '.venv'

# Type-check and test the web frontend. The whole TypeScript/React layer was
# previously outside every quality gate -- `make qa` guarded the Python and
# nothing guarded the client, which is the failure mode docs/web.md warned
# about for the old inline HTML string. Skipped (not failed) when Bun is
# absent or the frontend has never been `bun install`ed, since the web extra is
# optional and the curses TUI must stay buildable without it.
web-qa:
	@if ! command -v bun >/dev/null 2>&1; then \
		echo "web-qa: skipped (bun not found)"; \
	elif [ ! -d $(FRONTEND)/node_modules ]; then \
		echo "web-qa: skipped (run 'make web-build' first)"; \
	else \
		bun --bun run --cwd $(FRONTEND) typecheck && \
		bun --bun run --cwd $(FRONTEND) test; \
	fi

# Run a full quality assurance check
qa: lint typecheck test web-qa format

# Build wheel (per-version, current Python)
# The web UI bundle is a build artifact that must be present in the source
# tree before packaging, since `wheel.packages` copies whatever is there. CI
# does the same via .github/actions/build-web-ui -- keep the two in step, or a
# locally built wheel will differ from a released one.
wheel: web-build
	@uv build --wheel

# Build a stable-ABI wheel (cp312-abi3). Installs unchanged on
# Python 3.12+; requires Python>=3.12 to build. Two config settings
# are needed: `cmake.define.GRIDCALC_STABLE_ABI=ON` switches the
# nanobind module to STABLE_ABI mode (Limited API SO); `wheel.py-api=cp312`
# tells scikit-build-core to tag the wheel as `cp312-abi3-<platform>`
# instead of the running Python's per-version tag.
wheel-abi3: web-build
	@uv build --wheel \
	    --config-setting=cmake.define.GRIDCALC_STABLE_ABI=ON \
	    --config-setting=wheel.py-api=cp312

# Rebuild the in-place extension with STABLE_ABI on (for local
# dev/testing of abi3 behaviour without producing a wheel).
build-abi3:
	@uv sync --reinstall-package gridcalc \
	    --config-setting=cmake.define.GRIDCALC_STABLE_ABI=ON \
	    --config-setting=wheel.py-api=cp312

# Build source distribution
sdist: web-build
	@uv build --sdist

# Check distributions with twine
check:
	@uv run twine check dist/*

# Build both wheel and sdist
dist: wheel sdist check

# abi3 dist (stable-ABI wheel + sdist). Useful for inspecting the
# `cp312-abi3` artifact locally before relying on the
# build-abi3.yml CI workflow.
dist-abi3: wheel-abi3 sdist check

# Publish to TestPyPI
publish-test: check
	@uv run twine upload --repository testpypi dist/*

# Publish to PyPI
publish: check
	@uv run twine upload dist/*

# Upgrade all dependencies
upgrade:
	@uv lock --upgrade
	@uv sync

# Run tests with coverage
coverage:
	@GRIDCALC_SANDBOX=1 uv run pytest tests/ -v --cov=src/gridcalc --cov-report=term-missing

# Generate HTML coverage report
coverage-html:
	@GRIDCALC_SANDBOX=1 uv run pytest tests/ -v --cov=src/gridcalc --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

# Run cProfile-instrumented benchmarks across the four sheet shapes.
# Generates fixtures (bench_*.json) on first run; reuse on subsequent.
bench:
	@GRIDCALC_SANDBOX=1 uv run python -m benches.run

# Remove benchmark fixtures.
bench-clean:
	@rm -f bench_*.json bench_*.json.out

# Documentation site (MkDocs + Material + mkdocstrings). The dependencies are
# in the `docs` dependency group rather than `dev`, so they are pulled only
# when a docs target runs. `docs` is a directory as well as a target name, so
# these are declared .PHONY at the top of the file -- without that, make sees
# an up-to-date directory and does nothing.
#
# Build strictly: a broken cross-reference is a real defect in a site whose
# pages link to each other constantly, and the split of README.md into pages
# makes that easy to do by accident.
docs:
	@uv run --group docs mkdocs build --strict
	@echo "Site: site/index.html"

# Live-reloading preview.
docs-serve:
	@uv run --group docs mkdocs serve

# Publish to the gh-pages branch. This commits and pushes -- a deliberate
# manual step, which is why no CI workflow does it.
docs-deploy:
	@uv run --group docs mkdocs gh-deploy --strict

docs-clean:
	@rm -rf site/

# Create a release (bump version, tag, push).
# pyproject is the only place the version is written -- `gridcalc --version`
# reads it back from the installed metadata -- so this one line is the whole
# bump.
release:
	@echo "Current version: $$(grep '^version' pyproject.toml | head -1)"
	@read -p "New version: " version; 	sed -i '' "s/^version = .*/version = \"$$version\"/" pyproject.toml; 	git add pyproject.toml; 	git commit -m "Bump version to $$version"; 	git tag -a "v$$version" -m "Release $$version"; 	echo "Tagged v$$version. Run 'git push && git push --tags' to publish."

# Clean build artifacts
clean:
	@rm -rf build/
	@rm -rf dist/
	@rm -rf *.egg-info/
	@rm -rf src/*.egg-info/
	@rm -rf .pytest_cache/
	@find . -name "*.so" -delete
	@find . -name "*.pyd" -delete
	@find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Clean everything including CMake cache
distclean: clean
	@rm -rf CMakeCache.txt CMakeFiles/

# Show help
help:
	@echo "Available targets:"
	@echo "  all          - Build/rebuild the extension (default)"
	@echo "  sync         - Sync environment (initial setup)"
	@echo "  build        - Rebuild extension after code changes"
	@echo "  rebuild      - Alias for build"
	@echo "  test         - Run tests"
	@echo "  lint         - Lint with ruff"
	@echo "  format       - Format with ruff"
	@echo "  typecheck    - Type check with mypy"
	@echo "  qa           - Run full quality assurance (test, lint, typecheck, format)"
	@echo "  wheel        - Build wheel distribution (per-version, current Python)"
	@echo "  wheel-abi3   - Build stable-ABI wheel (cp312-abi3; needs Python>=3.12)"
	@echo "  build-abi3   - Rebuild in-place with STABLE_ABI (local dev)"
	@echo "  sdist        - Build source distribution"
	@echo "  dist         - Build per-version wheel + sdist + check"
	@echo "  dist-abi3    - Build abi3 wheel + sdist + check"
	@echo "  check        - Check distributions with twine"
	@echo "  publish-test - Publish to TestPyPI"
	@echo "  publish      - Publish to PyPI"
	@echo "  upgrade      - Upgrade all dependencies"
	@echo "  coverage     - Run tests with coverage"
	@echo "  coverage-html- Generate HTML coverage report"
	@echo "  docs         - Build the MkDocs site into site/"
	@echo "  docs-serve   - Preview the docs with live reload"
	@echo "  docs-deploy  - Publish the docs to the gh-pages branch"
	@echo "  docs-clean   - Remove the built site"
	@echo "  release      - Bump version, tag, and prepare release"
	@echo "  clean        - Remove build artifacts"
	@echo "  distclean    - Remove all generated files"
	@echo "  help         - Show this help message"
