.DEFAULT_GOAL := help
.PHONY: help setup test lint fmt check clean docs-check

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup:  ## Create the venv and install all workspace packages
	uv sync --all-packages

test:  ## Run the test suite
	uv run pytest

lint:  ## Lint without fixing
	uv run ruff check .

fmt:  ## Format and autofix
	uv run ruff format . && uv run ruff check --fix .

docs-check:  ## Validate scope.yaml, sources.yaml, and the response schema
	uv run pytest tests/test_scope.py tests/test_response_contract.py tests/test_sources.py -v

check: lint test  ## Lint + test

clean:  ## Remove caches
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
