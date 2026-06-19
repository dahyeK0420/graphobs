# Target Package Map Refactoring Roadmap

## Status

Superseded by the public implementation package cleanup.

The original target map preserved shallow root modules such as
`contracts.py`, `langgraph.py`, `callbacks.py`, `logging.py`, `discovery.py`,
and `demo.py` as legacy root files. The current package map removes those
legacy root files and promotes the implementation packages to public import
paths instead.

## Current Shape

```text
graph_observability_kit/
  __init__.py
  _version.py
  payloads.py
  tracing.py
  contracts/
    models.py
    projection.py
    validation.py
  state/
    observed_access.py
    paths.py
    policies.py
    read_tracking.py
  langgraph/
    callbacks.py
    execution.py
    nodes.py
    read_audit.py
    schemas.py
    subgraphs.py
  logging/
    callback.py
    context.py
    invoke_config.py
    lifecycle.py
  discovery/
    draft.py
    runner.py
  demo/
    span_records.py
    tracing_setup.py
  _observability/
    payload_policy.py
```

## Public Import Rule

Use the package root only for the headline adoption path:

- `NodeContract`
- `contract_node`
- `add_contract_node`
- `build_invoke_config`
- `__version__`

Use concrete implementation modules for lower-level primitives:

- Contract models: `graph_observability_kit.contracts.models`
- Contract projection: `graph_observability_kit.contracts.projection`
- Contract validation: `graph_observability_kit.contracts.validation`
- State helpers: `graph_observability_kit.state.paths`
- LangGraph nodes: `graph_observability_kit.langgraph.nodes`
- LangGraph subgraphs: `graph_observability_kit.langgraph.subgraphs`
- Callback projection: `graph_observability_kit.langgraph.callbacks`
- Structured logging context: `graph_observability_kit.logging.context`
- Structured logging callback: `graph_observability_kit.logging.callback`
- Invoke config: `graph_observability_kit.logging.invoke_config`
- Discovery draft model: `graph_observability_kit.discovery.draft`
- Discovery runner: `graph_observability_kit.discovery.runner`
- Demo tracing setup: `graph_observability_kit.demo.tracing_setup`
- Demo span records: `graph_observability_kit.demo.span_records`

The only remaining private observability helper is
`graph_observability_kit._observability.payload_policy`, which is intentionally
not part of the documented public interface.
