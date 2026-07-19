.PHONY: build clean check test lint fmt release map deploy deploy-check

build:
	uv sync --dev

clean:
	rm -rf dist/ build/ .pytest_cache/ .testmondata .coverage htmlcov/ tests/manual/logs/
	find src tests -type d -name __pycache__ -exec rm -rf {} +

check:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/
	uv run ty check src/ --ignore unresolved-import

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

# Regenerate deploy/{install,status,uninstall}.sh from design/malmberg.strata.
deploy:
	frob deploy generate .

# CI gate: fail if the committed deploy scripts drift from the design model.
deploy-check:
	frob deploy generate . --check
