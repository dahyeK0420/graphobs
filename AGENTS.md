# Agent Guidelines

This repository is intended to remain public, vendor-neutral, and example-driven.

## Project Standards

- Use `uv` for dependency management and command execution.
- Keep runtime dependencies minimal until a phase explicitly requires them.
- Put Python source under `src/graph_observability_kit/`.
- Keep public APIs typed, documented, and exported intentionally.
- Use synthetic examples and fixtures only.
- Do not include organization-specific, product-specific, deployment-specific, or private runtime details in public docs, examples, tests, package names, comments, or exported APIs.

## Validation

Before considering implementation complete, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
uv run mkdocs build --strict
uv build
```
