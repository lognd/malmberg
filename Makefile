.PHONY: build clean check test lint fmt release map

build:
	uv sync --dev

clean:
	rm -rf dist/ build/ .pytest_cache/ .testmondata .coverage htmlcov/ tests/manual/logs/
	find src tests -type d -name __pycache__ -exec rm -rf {} +

check:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/
	uv run ty check src/

lint:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

test:
	uv run pytest

fmt: lint

map:
	uv run python -m frob map src/

release: check test
	uv run python scripts/release.py
