.PHONY: test lint format typecheck run qa

test:
	@PYCALC_SANDBOX=1 uv run pytest tests/ -v

lint:
	@uv run ruff check pycalc/ tests/

format:
	@uv run ruff format pycalc/ tests/

typecheck:
	@uv run mypy pycalc/

qa: lint typecheck test format

run:
	@uv run python -m pycalc

