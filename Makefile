# graphobs — developer task runner.
#
# Thin wrappers around the `uv` commands documented in README.md, CONTRIBUTING.md,
# and docs/. Run `make` or `make help` to list available targets.

UV ?= uv

.DEFAULT_GOAL := help

.PHONY: help install sync hooks pre-commit version \
        lint format format-check typecheck test test-examples \
        docs docs-serve build check examples \
        example-simple-rag example-subgraph example-tool-agent example-backend \
        notebook clean

help: ## Show this help.
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

## --- Setup ---------------------------------------------------------------

install: ## Install all dependency groups into the virtualenv.
	$(UV) sync --all-groups

sync: install ## Alias for `install`.

hooks: ## Install pre-commit hooks.
	$(UV) run pre-commit install

pre-commit: ## Run pre-commit hooks against all files.
	$(UV) run pre-commit run --all-files

version: ## Print the installed package version.
	$(UV) run python -c "import graphobs; print(graphobs.__version__)"

## --- Quality gates -------------------------------------------------------

lint: ## Lint with ruff.
	$(UV) run ruff check .

format: ## Apply ruff formatting in place.
	$(UV) run ruff format .

format-check: ## Verify formatting without changing files.
	$(UV) run ruff format --check .

typecheck: ## Type-check with mypy.
	$(UV) run mypy .

test: ## Run the test suite.
	$(UV) run pytest

test-examples: ## Run only the example tests.
	$(UV) run pytest tests/test_examples.py

docs: ## Build the MkDocs site (strict).
	$(UV) run mkdocs build --strict

docs-serve: ## Serve the docs site locally with live reload.
	$(UV) run mkdocs serve

build: ## Build the sdist and wheel.
	$(UV) build

check: lint format-check typecheck test docs build ## Run all quality gates (matches CONTRIBUTING.md).

## --- Examples ------------------------------------------------------------

examples: example-simple-rag example-subgraph example-tool-agent example-backend ## Run all example apps.

example-simple-rag: ## Run the simple RAG example.
	$(UV) run python -m examples.simple_rag.app

example-subgraph: ## Run the subgraph boundary example.
	$(UV) run python -m examples.subgraph_boundary.app

example-tool-agent: ## Run the tool agent example.
	$(UV) run python -m examples.tool_agent.app

example-backend: ## Run the backend export example.
	$(UV) run python -m examples.backend_export.app

## --- Misc ----------------------------------------------------------------

notebook: ## Open the quickstart notebook (needs the `demo` extras installed).
	$(UV) run jupyter lab examples/notebooks/quickstart.ipynb

clean: ## Remove build artifacts and generated docs/cache directories.
	rm -rf build dist site .mypy_cache .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
