.PHONY: install clean reset upgrade ready format lint type-check test test-cov run compile bump major minor patch

install:
	uv sync --all-extras
	uv run -- prek install
	cp .env.example .env

clean:
	rm -rf dist/ __pycache__/ .ruff_cache/ .pytest_cache/ .sqlparse/ src/__pycache__/
	rm -f .coverage

reset: clean
	uv venv --clear
	$(MAKE) install

upgrade:
	uv sync --upgrade --all-extras

run:
	rm -rf .sqlparse/
	uv run -- python main.py

ready: lint format type-check test-cov

format:
	uv run -- ruff format

lint:
	uv run -- ruff check --fix

type-check:
	uv run -- ty check

test:
	uv run -- pytest -v -n auto

test-cov:
	uv run -- pytest --cov=src --cov-report=term-missing

compile:
	rm -rf dist
	chmod +x .github/nuitka_build.sh
	./.github/nuitka_build.sh

bump:
	uv version --bump $(filter major minor patch,$(MAKECMDGOALS))

major minor patch:
	@:
