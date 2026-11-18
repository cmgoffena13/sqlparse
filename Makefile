.PHONY: install clean reset upgrade ready format lint type-check test test-cov run compile bump major minor patch

install:
	uv sync --all-extras
	uv run -- prek install
	cp .env.example .env

clean:
	rm -rf dist/ __pycache__/ .ruff_cache/ .pytest_cache/ .sqlparse/
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
	uv run --no-dev -- nuitka src/app.py \
		--standalone \
		--onefile \
		--lto=yes \
		--assume-yes-for-downloads \
		--output-filename=sqlparse \
		--python-flag=no_warnings \
		--include-package=src \
		--include-package=certifi \
		--include-package-data=certifi \
		--include-distribution-metadata=caio \
		--include-distribution-metadata=aiofile \
		--nofollow-import-to=pytest \
		--nofollow-import-to=fastmcp.cli \
		--include-data-files=pyproject.toml=pyproject.toml \
		--include-data-files=src/schema.sql=src/schema.sql \
		--include-data-files=src/drop_schema.sql=src/drop_schema.sql \
		--output-dir=dist/

bump:
	uv version --bump $(filter major minor patch,$(MAKECMDGOALS))

major minor patch:
	@:
