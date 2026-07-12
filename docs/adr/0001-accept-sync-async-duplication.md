# ADR 0001: Accept sync/async duplication in the integration adapters

- **Status:** Accepted
- **Date:** 2026-07-12

## Context

Several integration adapters expose a synchronous and an asynchronous variant
that differ only in whether the wrapped step is awaited:

- `graphobs.langgraph.execution.instrument_contract_run` /
  `instrument_contract_arun`
- the sync and async node wrappers built by
  `graphobs.langgraph.nodes.contract_node`
- the sync and async subgraph wrappers and compiled-graph invokers in
  `graphobs.langgraph.subgraphs`
- `graphobs.discovery.runner.discover_contract` / `adiscover_contract`, and the
  `assert_contract_matches` / `assert_contract_amatches` pair in
  `graphobs.discovery.drift`

Each pair is near-identical: the same span, validation, and projection
lifecycle and the same error handling, differing only in the `await`.

An architecture review flagged this as duplication and asked whether the pairs
should be collapsed into one implementation with thin sync and async drivers.

## Decision

Keep the sync and async variants as explicit twins. Do not collapse them.

## Rationale

- Python 3.11 has no first-class way to share one code path across sync and
  async callables without either running an event loop from synchronous code
  (unacceptable in a library) or generating one form from the other (a codegen
  build step this project deliberately avoids).
- The substantial, non-trivial logic already lives behind single homes:
  `ContractRunSpec` plus the run-spec builders, `contracts.conformance`,
  `contracts.projection`, and the `state` package. What remains duplicated in
  each twin is a thin orchestration shell — open span, call or await the step,
  validate, project, close span. The duplication is shallow and stable.
- Collapsing would add indirection (a step protocol plus two drivers) and carry
  behaviour-change risk on the async paths, for little gain in locality.

## Consequences

- A change to the run lifecycle must be applied to both members of each pair.
  This is mitigated by the shared `ContractRunSpec` (the lifecycle policy lives
  in one place) and by tests that exercise both the sync and async paths.
- Future architecture reviews should treat these specific twins as an accepted,
  documented decision rather than re-raising them as duplication to remove.
