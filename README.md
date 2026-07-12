# graphobs

**Contract-first observability for graph-based Python apps.**

graphobs helps teams describe graph state boundaries once, then reuse those declarations for trace payloads, structured logs, and validation.

The `0.4.0` release is a complexity-reduction pass: it makes `ProjectionPolicy`
include-only, consolidates the internal contract and policy protocols, flattens
the contract execution lifecycle, and makes contract drift checks advisory by
default — all with no change to the package-root interface. It builds on the core
contract model, LangGraph integration helpers, callback payload projection,
backend-portable tracing helpers, and structured logging helpers.

## Why This Exists

Graph applications often grow faster than their observability model. Node inputs, node outputs, trace payloads, and log events can drift into separate conventions, which makes debugging harder and increases the chance of recording more state than intended.

This project starts from one design rule: state contracts, trace contracts, and log payload boundaries should be designed together.

## Why This Instead Of Auto-Instrumentation?

Use auto-instrumentation first when you only need a zero-code execution trace.
It is the lowest-friction baseline.

graphobs is for the next problem: deciding what each graph
boundary is allowed to expose, then using that same contract to validate writes
and curate OpenTelemetry/OpenInference payloads. Auto-instrumentors can show
what happened, but they cannot infer which state keys are public, which are local
scratch state, or whether a node wrote a key it should not own.

If your graph has fewer than three nodes or no noisy shared state, this library
may be more structure than you need. If traces are full of whole-state dumps,
private scratch values, or inconsistent node payloads, start with callback
payload projection or one contract and migrate outward.

## Why Not Agent Contracts Or PII Middleware?

[`agent-contracts`](https://github.com/yatarousan0227/agent-contracts) explores
declarative contracts for LangGraph agents, including graph construction and
runtime contract enforcement. graphobs is narrower: keep your
existing LangGraph shape, then use contracts to drive curated trace payloads,
span attributes, structured logs, and write validation.

[LangChain PII middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
is useful when you need to detect, redact, mask, or block PII in agent messages
and tool outputs. graphobs is not a PII detector. It reduces
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
pip install "graphobs[demo]"
jupyter lab examples/notebooks/quickstart.ipynb
```

The notebook walks through the full idea in two acts — no credentials required
for Act 1 (curated vs messy span contrast in an embedded viewer), and a
per-platform `.env` recipe for Act 2 (Arize Phoenix, LangSmith, MLflow, Langfuse).

### Library install from a checkout

Install the project in editable mode from a checkout:

```bash
uv sync --all-groups
uv run python -c "import graphobs; print(graphobs.__version__)"
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
an intentional contract validation error, and lifecycle log summaries.

## Current Package Surface

The package root exposes the headline adoption path. Lower-level projection,
logging, and tracing primitives remain available from focused submodules.

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

The contract model is plain Python and has no graph runtime dependency.

For an existing LangGraph app, choose the adoption path by risk. `contract_node`
takes one `mode` from `NodeContractMode`:

- Want cleaner callback payloads without changing execution? Start with
  `project_callback_payloads`.
- Want cleaner spans and read/write warnings while preserving current node
  behavior? Use `contract_node(..., mode=NodeContractMode.OBSERVE)` or
  `NodeContractMode.AUDIT`.
- Want strict contract-shaped execution for a stable node? Use the default
  `contract_node` wrapper (`NodeContractMode.ENFORCE`).

Callback projection is the lowest-risk migration path because the node still
receives the graph state LangGraph would normally provide:

```python
from graphobs.langgraph.callbacks import project_callback_payloads

config = {
    "callbacks": [
        project_callback_payloads(callback, [classify_contract], diagnostics=True),
    ],
}
```

The strict LangGraph wrapper projects the node's execution input before the
node runs:

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

For migration guardrails without execution filtering, wrap at registration time
in `AUDIT` mode, which keeps the node on the full graph state and logs
undeclared reads and writes:

```python
from graphobs import NodeContract, NodeContractMode, contract_node

classify_contract = NodeContract(
    name="classify",
    reads=("request.text",),
    writes=("classification.label",),
)

graph.add_node(
    "classify",
    contract_node(
        classify,
        classify_contract,
        mode=NodeContractMode.AUDIT,
    ),
)
```

To instrument a whole graph in one step, register every node at once and
promote nodes to `ENFORCE` individually as their boundaries stabilize:

```python
from graphobs import NodeContractMode, add_contract_nodes

add_contract_nodes(
    graph,
    [(classify_contract, classify), (answer_contract, answer)],
    mode=NodeContractMode.OBSERVE,
)
```

Tracing helpers emit OpenTelemetry spans with OpenInference semantic attributes.
Exporter configuration stays outside the library, so applications can choose any
OpenTelemetry-compatible backend.

```python
from graphobs.tracing import start_graph_span

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
from graphobs import build_invoke_config
from graphobs.logging.context import LogContext

config = build_invoke_config(
    LogContext(session_id="session-1", request_id="request-1"),
)
graph.compile().invoke({"request": {"text": "hello"}}, config=config)
```

## Public Neutrality

All docs, tests, examples, fixtures, comments, and exported APIs must use synthetic, generic concepts. Do not include organization-specific, product-specific, deployment-specific, or private runtime details.

See [docs/concepts/public-neutrality.md](https://github.com/dahyeK0420/graphobs/blob/main/docs/concepts/public-neutrality.md) for the repository policy.

## Documentation

- [Quickstart Notebook](https://github.com/dahyeK0420/graphobs/blob/main/examples/notebooks/quickstart.ipynb)
- [Architecture](https://github.com/dahyeK0420/graphobs/blob/main/docs/architecture.md)
- [Examples](https://github.com/dahyeK0420/graphobs/blob/main/docs/examples.md)
- [State, Logs, And Traces](https://github.com/dahyeK0420/graphobs/blob/main/docs/concepts/state-logs-traces.md)
- [Public Vs Private Graph State](https://github.com/dahyeK0420/graphobs/blob/main/docs/concepts/public-vs-private-state.md)
- [Designing Node Contracts](https://github.com/dahyeK0420/graphobs/blob/main/docs/concepts/designing-node-contracts.md)
- [Payload Safety And Redaction](https://github.com/dahyeK0420/graphobs/blob/main/docs/concepts/payload-safety-redaction.md)
- [Backend Portability With OTel And OpenInference](https://github.com/dahyeK0420/graphobs/blob/main/docs/concepts/backend-portability.md)
- [Migrate One Node At A Time](https://github.com/dahyeK0420/graphobs/blob/main/docs/guides/migration-one-node-at-a-time.md)
- [Medium Companion](https://github.com/dahyeK0420/graphobs/blob/main/docs/articles/medium-companion.md)
- [0.4.0 Release Notes](https://github.com/dahyeK0420/graphobs/blob/main/docs/releases/v0.4.0.md)
- [Contracts API Reference](https://github.com/dahyeK0420/graphobs/blob/main/docs/reference/contracts.md)
- [LangGraph API Reference](https://github.com/dahyeK0420/graphobs/blob/main/docs/reference/langgraph.md)
- [Logging API Reference](https://github.com/dahyeK0420/graphobs/blob/main/docs/reference/logging.md)
- [Tracing API Reference](https://github.com/dahyeK0420/graphobs/blob/main/docs/reference/tracing.md)
- [Release And Versioning Notes](https://github.com/dahyeK0420/graphobs/blob/main/docs/release-versioning.md)

The MkDocs site can be built locally with:

```bash
uv run mkdocs build --strict
```
