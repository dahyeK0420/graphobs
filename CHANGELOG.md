# Changelog

All notable changes to this project will be documented in this file.

This project follows Semantic Versioning once public releases begin.

## 0.3.0 - 2026-07-11

- Breaking: strict `contract_node` execution now enforces declared reads. A read
  outside the contract raises `StateContractError` (or warns under
  `on_violation=ContractViolationAction.WARN`) instead of silently resolving to
  a projected default value. During migration, use `pass_through_state=True`
  with `audit_reads=True` to surface undeclared reads without raising.
- Add a `read`/`write` access kind to `StateContractError`; its message now
  reads "read" or "wrote", and the `access` attribute records which occurred.
- Document and test node reducer-safety: `contract_node` passes partial updates
  through, so parent reducers such as `add_messages` and
  `Annotated[list, operator.add]` apply exactly once.
- Document a `contract_subgraph` reducer boundary: parent output supports
  last-value-wins channels only; non-deduplicating accumulating reducers
  double-apply the seeded input, so model those channels with node-level
  contracts.
- Clarify that omitting `reads` or `writes` declares an empty boundary, not
  "all state".

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
