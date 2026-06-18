# Changelog

All notable changes to this project will be documented in this file.

This project follows Semantic Versioning once public releases begin.

## Unreleased

- Breaking: narrow package-root exports to the headline interface and keep
  lower-level primitives available from their focused submodules.
- Extract shared dotted state path and diff operations into one internal module.

## 0.1.0 - 2026-06-17

- Establish public repository foundation.
- Add package skeleton for `graph_observability_kit`.
- Add docs, tests, examples, and CI scaffolding.
- Add runtime-independent state contract models and projection helpers.
- Add OpenTelemetry/OpenInference tracing helpers with compact payloads.
- Add LangGraph node and subgraph contract wrappers.
- Add structured logging helpers for lifecycle events and correlation fields.
- Add synthetic LangGraph examples for simple retrieval, subgraph boundaries,
  tool-like flows, and local backend export shape.
- Add adoption, payload safety, backend portability, and release documentation.
