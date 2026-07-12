# graphobs

graphobs is a Python package for contract-first observability in graph-based applications.

The project helps users align three related surfaces:

- State boundaries that describe what a graph node may read or write.
- Trace payloads that show curated inputs, outputs, attributes, and errors.
- Structured logs that record lifecycle events and correlation fields.

The `0.4.0` package contains the core typed contract model with enforced
strict-mode reads, LangGraph integration helpers, callback payload projection,
backend-portable tracing helpers, structured logging helpers, and neutral
runnable examples.

## Quickstart

```bash
uv sync --all-groups
uv run python -c "import graphobs; print(graphobs.__version__)"
```

## Minimal Contract

```python
from graphobs import NodeContract
from graphobs.contracts.projection import project_input

contract = NodeContract(
    name="classify",
    reads=("request.text",),
    writes=("classification.label",),
)

state = {"request": {"text": "hello"}, "scratch": {"notes": "local"}}
public_input = project_input(contract, state)
```

## Minimal Span

```python
from graphobs.logging.context import LogContext
from graphobs.tracing import start_graph_span

log_context = LogContext(session_id="session-1", request_id="request-1")

with start_graph_span(
    "classify",
    "CHAIN",
    input=public_input,
    attributes=log_context.as_metadata(),
):
    ...
```

Tracing helpers emit OpenTelemetry spans and use OpenInference semantic
attributes for span kind, input value, and output value. Payloads are compact by
default.

## Minimal LangGraph Node

For existing graphs, start with callback payload projection when you only need
cleaner traces and callback payloads. Use `contract_node` when you are ready for
execution-time contract guardrails.

```python
from graphobs import NodeContract, contract_node

@contract_node(
    NodeContract(
        name="classify",
        reads=("request.text",),
        writes=("classification.label",),
    )
)
def classify(state):
    return {"classification": {"label": "question"}}
```

For the full adoption path, see
[Migrate One Node At A Time](guides/migration-one-node-at-a-time.md).

## Minimal Structured Logs

```python
from graphobs import build_invoke_config
from graphobs.logging.context import LogContext

config = build_invoke_config(LogContext(session_id="session-1"))
graph.compile().invoke({"request": {"text": "hello"}}, config=config)
```

Structured logs record lifecycle events, correlation fields, durations, and
compact input/output shape summaries. They avoid full state payloads; traces are
the right place for curated payloads.

## Local Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
uv run mkdocs build --strict
uv build
```

## Examples

```bash
uv run python -m examples.simple_rag.app
uv run python -m examples.subgraph_boundary.app
uv run python -m examples.tool_agent.app
uv run python -m examples.backend_export.app
```

See [Examples](examples.md) for the full index and validation workflow.

## Deeper Docs

- [State, Logs, And Traces](concepts/state-logs-traces.md)
- [Public Vs Private Graph State](concepts/public-vs-private-state.md)
- [Designing Node Contracts](concepts/designing-node-contracts.md)
- [Payload Safety And Redaction](concepts/payload-safety-redaction.md)
- [Backend Portability With OTel And OpenInference](concepts/backend-portability.md)
- [API Reference](reference/index.md)
