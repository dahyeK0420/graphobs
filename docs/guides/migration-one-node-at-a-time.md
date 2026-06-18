# Migrate One Node At A Time

You can adopt Graph Observability Kit without rewriting a graph. Start with one
node, prove the boundary, then repeat.

If your graph has fewer than three nodes or no noisy shared state, plain
LangGraph plus auto-instrumentation may be enough. Use this guide when traces
are hard to read because each span carries too much state, or when node writes
drift beyond the state keys a node should own.

## 1. Pick A Stable Node

Choose a node with clear input and output. A classifier, retriever, ranker, or
answering step is usually easier than a node that mutates many unrelated keys.

## 2. Declare The Contract

```python
from graph_observability_kit import NodeContract

classify_contract = NodeContract(
    name="classify",
    reads=("request.text",),
    writes=("classification.label",),
    span_kind="CHAIN",
)
```

The contract says what the node may read, what it may write, and what span kind
the wrapper should use.

## 3. Decorate The Existing Function

```python
from graph_observability_kit import contract_node


@contract_node(classify_contract)
def classify(state):
    return {"classification": {"label": "question"}}
```

The decorated node receives the projected execution input. It returns the same
kind of state update LangGraph expects.

If you prefer to leave the function definition untouched, wrap at registration
time instead:

```python
from graph_observability_kit import contract_node

graph.add_node("classify", contract_node(classify, classify_contract))
```

## 4. Run The Graph

Run the same graph invocation you already use. If the node returns an undeclared
path, `StateContractError` points to the boundary mismatch.

```python
from graph_observability_kit.contracts import StateContractError

try:
    app.invoke({"request": {"text": "hello"}})
except StateContractError as exc:
    print(exc.undeclared_paths)
```

## 5. Add Correlation When Useful

```python
from graph_observability_kit import build_invoke_config
from graph_observability_kit.logging import LogContext

config = build_invoke_config(
    LogContext(session_id="session-1", request_id="request-1"),
)
app.invoke({"request": {"text": "hello"}}, config=config)
```

Logs now carry lifecycle events and correlation fields. Traces still carry
curated span shape.

## 6. Repeat

Add contracts to adjacent nodes once the first boundary is stable. Keep each
contract small and review payload shape before using full payload mode.

## Quick Check

The first contract-wrapped node is complete when:

- The node receives only declared reads and private reads.
- The node returns only declared writes and private writes.
- Compact span input and output are useful without full state dumps.
- Existing graph behavior still passes its tests.
