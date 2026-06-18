# Graph Observability Kit

Graph Observability Kit is a Python library for contract-first observability in graph-based applications. It helps teams describe graph state boundaries once, then reuse those declarations for trace payloads, structured logs, and validation.

The `0.1.0` release is intentionally small. It includes the core contract model,
LangGraph integration helpers, backend-portable tracing helpers, and structured
logging helpers.

## Why This Exists

Graph applications often grow faster than their observability model. Node inputs, node outputs, trace payloads, and log events can drift into separate conventions, which makes debugging harder and increases the chance of recording more state than intended.

This project starts from one design rule: state contracts, trace contracts, and log payload boundaries should be designed together.

## Why This Instead Of Auto-Instrumentation?

Use auto-instrumentation first when you only need a zero-code execution trace.
It is the lowest-friction baseline.

Graph Observability Kit is for the next problem: deciding what each graph
boundary is allowed to expose, then using that same contract to validate writes
and curate OpenTelemetry/OpenInference payloads. Auto-instrumentors can show
what happened, but they cannot infer which state keys are public, which are local
scratch state, or whether a node wrote a key it should not own.

If your graph has fewer than three nodes or no noisy shared state, this library
may be more structure than you need. If traces are full of whole-state dumps,
private scratch values, or inconsistent node payloads, start by wrapping one
node and migrate outward.

## Why Not Agent Contracts Or PII Middleware?

[`agent-contracts`](https://github.com/yatarousan0227/agent-contracts) explores
declarative contracts for LangGraph agents, including graph construction and
runtime contract enforcement. Graph Observability Kit is narrower: keep your
existing LangGraph shape, then use contracts to drive curated trace payloads,
span attributes, structured logs, and write validation.

[LangChain PII middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
is useful when you need to detect, redact, mask, or block PII in agent messages
and tool outputs. Graph Observability Kit is not a PII detector. It reduces
overcollection by projecting only contract-declared graph state into telemetry
and by using compact payload summaries by default.

## Mental Model

- State is the working data a graph reads and writes.
- Logs record lifecycle events and correlation fields.
- Traces show execution flow, timing, inputs, outputs, attributes, and errors.
- Contracts define which parts of state are public at a graph boundary and which parts should stay local to an implementation detail.

## Quickstart

### Interactive notebook (recommended for new users)

Install the demo bundle and open the notebook:

```bash
pip install "graph-observability-kit[demo]"
jupyter lab examples/notebooks/quickstart.ipynb
```

The notebook walks through the full idea in two acts — no credentials required
for Act 1 (curated vs messy span contrast in an embedded viewer), and a
per-platform `.env` recipe for Act 2 (Arize Phoenix, LangSmith, MLflow, Langfuse).

### Library install from a checkout

Install the project in editable mode from a checkout:

```bash
uv sync --all-groups
uv run python -c "import graph_observability_kit; print(graph_observability_kit.__version__)"
```

Run the local checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
uv run mkdocs build --strict
uv build
```

## Examples

The `examples/` directory contains local-only synthetic examples that compare
raw LangGraph flows with contract-wrapped versions:

```bash
uv run python -m examples.simple_rag.app
uv run python -m examples.subgraph_boundary.app
uv run python -m examples.tool_agent.app
uv run python -m examples.backend_export.app
```

Each example prints deterministic JSON with raw spans, compact contract spans,
an intentional contract validation error, and lifecycle log summaries. Static
snippet files live beside the example code as `trace_snippet.json`.

## Current Package Surface

The package root exposes the headline adoption path. Lower-level projection,
logging, and tracing primitives remain available from focused submodules.

```python
from graph_observability_kit import NodeContract
from graph_observability_kit.contracts import project_input

contract = NodeContract(
    name="classify",
    reads=("request.text",),
    writes=("classification.label",),
)

state = {"request": {"text": "hello"}, "scratch": {"notes": "local"}}
public_input = project_input(contract, state)
```

The contract model is plain Python and has no graph runtime dependency.

LangGraph users can wrap a node without changing the node's business logic. The
decorator form is the shortest adoption path:

```python
from graph_observability_kit import NodeContract, contract_node

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

You can also wrap at registration time:

```python
from graph_observability_kit import NodeContract, contract_node

classify_contract = NodeContract(
    name="classify",
    reads=("request.text",),
    writes=("classification.label",),
)

graph.add_node("classify", contract_node(classify, classify_contract))
```

Tracing helpers emit OpenTelemetry spans with OpenInference semantic attributes.
Exporter configuration stays outside the library, so applications can choose any
OpenTelemetry-compatible backend.

```python
from graph_observability_kit.tracing import start_graph_span

with start_graph_span(
    "classify",
    "CHAIN",
    input=public_input,
    attributes={"graph.node": "classify"},
):
    ...
```

Payloads use compact structural summaries by default. Explicit full payload mode
is available for controlled debugging, but it is unsafe for sensitive production
data.

Structured logging helpers emit lifecycle events with correlation fields and
durations. They do not configure a logging backend or store full graph state.

```python
from graph_observability_kit import build_invoke_config
from graph_observability_kit.logging import LogContext

config = build_invoke_config(
    LogContext(session_id="session-1", request_id="request-1"),
)
graph.compile().invoke({"request": {"text": "hello"}}, config=config)
```

## Public Neutrality

All docs, tests, examples, fixtures, comments, and exported APIs must use synthetic, generic concepts. Do not include organization-specific, product-specific, deployment-specific, or private runtime details.

See [docs/concepts/public-neutrality.md](docs/concepts/public-neutrality.md) for the repository policy.

## Documentation

- [Quickstart Notebook](examples/notebooks/quickstart.ipynb)
- [Architecture](docs/architecture.md)
- [Examples](docs/examples.md)
- [State, Logs, And Traces](docs/concepts/state-logs-traces.md)
- [Public Vs Private Graph State](docs/concepts/public-vs-private-state.md)
- [Designing Node Contracts](docs/concepts/designing-node-contracts.md)
- [Payload Safety And Redaction](docs/concepts/payload-safety-redaction.md)
- [Backend Portability With OTel And OpenInference](docs/concepts/backend-portability.md)
- [Migrate One Node At A Time](docs/guides/migration-one-node-at-a-time.md)
- [Medium Companion](docs/articles/medium-companion.md)
- [0.1.0 Release Notes](docs/releases/v0.1.0.md)
- [Contracts API Reference](docs/reference/contracts.md)
- [LangGraph API Reference](docs/reference/langgraph.md)
- [Logging API Reference](docs/reference/logging.md)
- [Tracing API Reference](docs/reference/tracing.md)
- [Release And Versioning Notes](docs/release-versioning.md)

The MkDocs site can be built locally with:

```bash
uv run mkdocs build --strict
```
