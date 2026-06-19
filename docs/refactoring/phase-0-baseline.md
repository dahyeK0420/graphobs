# Phase 0 Baseline

Date: 2026-06-18

## Scope

Phase 0 established a pre-refactor baseline for the target package map
roadmap. No structural module move was started, no source module under
`src/graph_observability_kit/` was modified, and no dependency was added or
updated.

## Worktree Note

The worktree already contained unrelated local changes before Phase 0 edits.
Those changes were preserved and not reverted:

- `.gitignore`
- `uv.lock`
- `examples/*/trace_snippet.json`
- `.claude/PLAN (7).md`
- `docs/refactoring/target-package-map-roadmap.md`

## Validation Baseline

| Command | Exit | Result |
| --- | ---: | --- |
| `uv run pytest tests/test_import.py tests/test_docs_reference.py` | 0 | `15 passed in 0.09s` |
| `uv run ruff check .` | 0 | `All checks passed!` |
| `uv run ruff format --check .` | 0 | `39 files already formatted` |
| `uv run mypy .` | 0 | `Success: no issues found in 38 source files` |
| `uv run pytest` | 0 | `142 passed in 7.35s` |
| `uv run mkdocs build --strict` | 0 | Documentation built successfully in `site/` |
| `uv build` | 0 | Built source distribution and wheel in `dist/` |

`uv run mkdocs build --strict` and `uv build` first failed in the sandbox with
`Operation not permitted` while uv accessed its cache under the home directory.
Both commands passed when rerun with the same command and runtime approval.

The strict MkDocs build emitted an informational note that
`docs/refactoring/phase-0-baseline.md` and
`docs/refactoring/target-package-map-roadmap.md` exist outside the configured
navigation. It did not fail the build.

## Public Facade Line Counts

These counts provide the baseline for the final roadmap phase's large-module
comparison.

| Module | Lines |
| --- | ---: |
| `src/graph_observability_kit/contracts.py` | 456 |
| `src/graph_observability_kit/langgraph.py` | 627 |
| `src/graph_observability_kit/callbacks.py` | 352 |
| `src/graph_observability_kit/logging.py` | 611 |
| `src/graph_observability_kit/discovery.py` | 351 |
| `src/graph_observability_kit/demo.py` | 307 |
| `src/graph_observability_kit/tracing.py` | 311 |
| `src/graph_observability_kit/payloads.py` | 129 |

Total across these pre-cleanup public modules: 3,144 lines.

## Public Surface Guardrails

`tests/test_import.py` now pins exact `__all__` values for the package root and
the pre-cleanup public modules:

- `graph_observability_kit`
- `graph_observability_kit.contracts`
- `graph_observability_kit.langgraph`
- `graph_observability_kit.langgraph.callbacks`
- `graph_observability_kit.logging`
- `graph_observability_kit.discovery`
- `graph_observability_kit.demo`
- `graph_observability_kit.payloads`
- `graph_observability_kit.tracing`

`tests/test_docs_reference.py` pins generated API reference pages to public
pre-cleanup modules and rejects references to private
`graph_observability_kit._*` modules.

Existing tests already cover the main behavior-preservation points needed
before structural moves: public imports, callback projection, read auditing,
validation errors, public logger names, generated examples, tracing payload
shape, structured logging payloads, discovery behavior, package metadata, and
strict generated docs.
