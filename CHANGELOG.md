# Changelog

All notable changes to this project will be documented in this file.

This project follows Semantic Versioning once public releases begin.

## Unreleased

## 0.2.1 - 2026-06-19

- Add pre-commit hooks that run `make lint` and `make test` before each commit,
  installed with `make hooks` and run across all files with `make pre-commit`.
- Remove the checked-in `trace_snippet.json` example fixtures; the example tests
  now assert trace-shape guarantees directly, so docs and examples no longer
  depend on static snapshot files.

## 0.2.0 - 2026-06-18

- Breaking: narrow package-root exports to the headline interface and keep
  lower-level primitives available from their focused submodules.
- Extract shared dotted state path and diff operations into one internal module.
- Add callback payload projection helpers with match diagnostics.
- Add contract discovery helpers for synthetic sample states.
- Add pass-through node execution and read auditing guardrails for migrations.
- Ship `py.typed` for typed downstream consumers.
- Document callback-first migration, reducer-managed namespaces, and heavy-path
  summarization.

## 0.1.0 - 2026-06-17

- Establish public repository foundation.
- Add package skeleton for `graphobs`.
- Add docs, tests, examples, and CI scaffolding.
- Add runtime-independent state contract models and projection helpers.
- Add OpenTelemetry/OpenInference tracing helpers with compact payloads.
- Add LangGraph node and subgraph contract wrappers.
- Add structured logging helpers for lifecycle events and correlation fields.
- Add synthetic LangGraph examples for simple retrieval, subgraph boundaries,
  tool-like flows, and local backend export shape.
- Add adoption, payload safety, backend portability, and release documentation.
