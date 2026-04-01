.PHONY: test lint format typecheck run qa

test:
	@GRIDCALC_SANDBOX=1 uv run pytest tests/ -v

lint:
	@uv run ruff check gridcalc/ tests/

format:
	@uv run ruff format gridcalc/ tests/

typecheck:
	@uv run mypy gridcalc/

qa: lint typecheck test format

run:
	@uv run python -m gridcalc

