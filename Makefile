.PHONY: all sync build rebuild test test-stdlib lint format typecheck qa clean  \
       distclean wheel wheel-abi3 build-abi3 sdist dist dist-abi3 check \
       publish-test publish upgrade coverage coverage-html docs release \
       bench bench-clean web-build web-dev web-jstest web-qa web-run help

# Default target
all: build

# Sync environment (initial setup, installs dependencies + package)
sync:
	@uv sync

# Build/rebuild the extension after code changes
build:
	@uv sync --reinstall-package gridcalc

# Alias for build
rebuild: build

# Run tests (excludes PTY/curses integration tests; see test-tty for those)
test:
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

# Build the React web frontend (web/frontend) into a single self-contained
# static/index.html that the pywebview window serves. Requires Node/npm.
web-build:
	@npm --prefix src/gridcalc/web/frontend install --no-audit --no-fund
	@npm --prefix src/gridcalc/web/frontend run build

# Run the frontend dev server (browser + mock bridge, hot reload) for fast UI
# iteration without launching pywebview.
web-dev:
	@npm --prefix src/gridcalc/web/frontend run dev

# Run the frontend component tests (vitest + React Testing Library).
web-jstest:
	@npm --prefix src/gridcalc/web/frontend run test

# Launch the desktop web app (serves the built static/index.html in a pywebview
# window). Run `make web-build` first. Needs the `web` extra (pywebview).
web-run:
	@GRIDCALC_SANDBOX=1 uv run gridcalc-web

# Run tests in an isolated environment without the optional extras
# (numpy / pandas). Verifies the optional-dep skipif guards work and
# the core engine operates without any third-party runtime deps.
# Pygments arrives transitively via pytest -- harmless; tui.py guards
# its use with try/except.
test-stdlib:
	@GRIDCALC_SANDBOX=1 uv run --isolated --no-project --with pytest --with . \
		pytest tests/ -v

# Lint with ruff
lint:
	@uv run ruff check --fix src/ tests/

# Format with ruff
format:
	@uv run ruff format src/ tests/

# Type check with mypy
typecheck:
	@uv run mypy src/gridcalc/ --exclude '.venv'

# Type-check and test the web frontend. The whole TypeScript/React layer was
# previously outside every quality gate -- `make qa` guarded the Python and
# nothing guarded the client, which is the failure mode docs/web.md warned
# about for the old inline HTML string. Skipped (not failed) when Node is
# absent or the frontend has never been `npm install`ed, since the web extra is
# optional and the curses TUI must stay buildable without it.
web-qa:
	@if ! command -v npm >/dev/null 2>&1; then \
		echo "web-qa: skipped (npm not found)"; \
	elif [ ! -d src/gridcalc/web/frontend/node_modules ]; then \
		echo "web-qa: skipped (run 'make web-build' first)"; \
	else \
		npm --prefix src/gridcalc/web/frontend run typecheck && \
		npm --prefix src/gridcalc/web/frontend run test; \
	fi

# Run a full quality assurance check
qa: lint typecheck test web-qa format

# Build wheel (per-version, current Python)
wheel:
	@uv build --wheel

# Build a stable-ABI wheel (cp312-abi3). Installs unchanged on
# Python 3.12+; requires Python>=3.12 to build. Two config settings
# are needed: `cmake.define.GRIDCALC_STABLE_ABI=ON` switches the
# nanobind module to STABLE_ABI mode (Limited API SO); `wheel.py-api=cp312`
# tells scikit-build-core to tag the wheel as `cp312-abi3-<platform>`
# instead of the running Python's per-version tag.
wheel-abi3:
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
sdist:
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

# Build documentation (requires sphinx in dev dependencies)
docs:
	@uv run sphinx-build -b html docs/ docs/_build/html

# Create a release (bump version, tag, push)
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
	@echo "  docs         - Build documentation with Sphinx"
	@echo "  release      - Bump version, tag, and prepare release"
	@echo "  clean        - Remove build artifacts"
	@echo "  distclean    - Remove all generated files"
	@echo "  help         - Show this help message"
