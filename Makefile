.DEFAULT_GOAL := default
.PHONY: default install fmt check test build clean

default: install check test

install:
	uv sync --all-extras

fmt:
	uv run ruff check --fix
	uv run ruff format

check:
	uv run ruff check
	uv run ruff format --check
	uv run basedpyright

test:
	uv run pytest

build:
	uv build

clean:
	rm -rf dist .pytest_cache .ruff_cache .venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
