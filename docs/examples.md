# Examples

The examples are local, deterministic, and synthetic. They do not require hosted
observability services or additional dependencies.

Each example prints JSON with four useful sections:

- `raw`: a raw LangGraph version using full synthetic payloads for comparison.
- `contract_wrapped`: the same idea wrapped with contracts and compact span
  payloads.
- `validation`: an intentional `StateContractError` and matching error span.
- `logs`: lifecycle summaries that keep correlation and payload shape separate
  from trace input/output values.

## Run The Examples

```bash
uv run python -m examples.simple_rag.app
uv run python -m examples.subgraph_boundary.app
uv run python -m examples.tool_agent.app
uv run python -m examples.backend_export.app
```

## Example Index

| Example | Shows |
| --- | --- |
| `examples/simple_rag` | Classify intent, retrieve synthetic documents, answer |
| `examples/subgraph_boundary` | Parent graph calling a retriever subgraph with local scratch state |
| `examples/tool_agent` | Toy tool-calling flow with compact `TOOL` spans |
| `examples/backend_export` | Local in-memory and console span exporter setup |

## Validation

The example tests run the same code paths as the commands above and assert the
important trace-shape guarantees:

```bash
uv run pytest tests/test_examples.py
```

For adoption guidance, start with
[Migrate One Node At A Time](guides/migration-one-node-at-a-time.md), then use
these examples to compare raw and contract-wrapped span shape.
