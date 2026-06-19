# Contributing

Thanks for considering a contribution to graphobs.

## Development Setup

```bash
uv sync --all-groups
uv run pytest
```

## Quality Gates

Run these checks before opening a pull request:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
uv run mkdocs build --strict
uv build
```

## Contribution Rules

- Keep changes focused on one purpose.
- Add or update tests for new behavior.
- Update docs when setup, behavior, or public APIs change.
- Use synthetic examples and fixtures only.
- Keep docs, tests, examples, comments, and public APIs free of organization-specific, product-specific, deployment-specific, and private runtime details.

## Commit Style

Use Conventional Commits for commit messages:

```text
feat: add projection policy model
fix: reject undeclared writes
docs: clarify trace payload safety
```

## Pull Request Checklist

- The change has tests or a clear reason tests are not needed.
- The quality gates pass locally.
- Public docs and examples remain neutral and synthetic.
- New public APIs have type hints and Google-style docstrings.
