.PHONY: test lint format typecheck run qa build clean check publish publish-test

test:
	@GRIDCALC_SANDBOX=1 uv run pytest tests/ -v

lint:
	@uv run ruff check --fix src/gridcalc/ tests/

format:
	@uv run ruff format src/gridcalc/ tests/

typecheck:
	@uv run mypy src/gridcalc/

qa: lint typecheck test format

run:
	@uv run python -m gridcalc

build: clean
	@uv build
	@uv run twine check dist/*

clean:
	@rm -rf dist/ build/ *.egg-info

check:
	@uv run twine check dist/*

publish: check
	@uv run twine upload dist/*

publish-test: check
	@uv run twine upload --repository testpypi dist/*

