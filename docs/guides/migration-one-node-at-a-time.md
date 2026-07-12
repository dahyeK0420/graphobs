# Migrate One Node At A Time

You can adopt graphobs without rewriting a graph. Start with one
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
from graphobs import NodeContract

classify_contract = NodeContract(
    name="classify",
    reads=("request.text",),
    writes=("classification.label",),
    span_kind="CHAIN",
)
```

The contract says what the node may read, what it may write, and what span kind
the wrapper should use.

## 3. Choose The First Integration Mode

For existing graphs, start with the least invasive mode that answers your
current question. `contract_node` and `add_contract_node` take a single
`mode` from `NodeContractMode`:

| Goal | Start here | Execution changes? |
| --- | --- | --- |
| Cleaner callback payloads only | `project_callback_payloads` | No |
| Cleaner spans, no execution change | `contract_node(..., mode=NodeContractMode.OBSERVE)` | No |
| Read and write warnings during migration | `contract_node(..., mode=NodeContractMode.AUDIT)` | No input filtering |
| Strict contract-shaped execution | `contract_node(...)` (default `ENFORCE`) | Yes |

### Callback Projection Only

Use callback projection when the node should continue receiving the same state
as before, but downstream callbacks should see contract-projected payloads:

```python
from graphobs.langgraph.callbacks import project_callback_payloads

config = {
    "callbacks": [
        project_callback_payloads(
            callback,
            [classify_contract],
            diagnostics=True,
        ),
    ],
}
```

The wrapper matches LangGraph node events by `metadata["langgraph_node"]`.
Set `diagnostics=True` during migration and inspect `projection_stats()` when
subgraphs or custom node names might change the metadata value.

### Observe Or Audit Execution

Use `OBSERVE` or `AUDIT` when an existing node may read fallback keys or
namespace-managed state that is not fully declared yet:

```python
from graphobs import NodeContractMode, contract_node

graph.add_node(
    "classify",
    contract_node(
        classify,
        classify_contract,
        mode=NodeContractMode.AUDIT,
    ),
)
```

In both modes the node receives the original state, while span input and output
stay contract-projected, and undeclared writes are logged as warnings and still
forwarded. `AUDIT` additionally logs undeclared read paths (without logging
state values); `OBSERVE` leaves reads unaudited when you only want cleaner
spans.

### Strict Projected Execution

Use strict mode once the boundary is stable or when you want the contract to
shape what the node receives:

```python
from graphobs import contract_node


@contract_node(classify_contract)
def classify(state):
    return {"classification": {"label": "question"}}
```

The decorated node receives only declared public reads plus declared private
reads. It returns the same kind of state update LangGraph expects.

If you prefer to leave the function definition untouched, wrap at registration
time instead:

```python
from graphobs import contract_node

graph.add_node("classify", contract_node(classify, classify_contract))
```

The convenience helper registers the node with `contract.label`, which is the
same value supplied as `NodeContract(name=...)`:

```python
from graphobs import add_contract_node

add_contract_node(graph, classify_contract, classify)
```

Use this form when the graph node name should come directly from the contract.
The default `mode` is `NodeContractMode.ENFORCE`, so both forms above enforce
the contract unless you pass `OBSERVE` or `AUDIT`.

During early adoption, use `OBSERVE` or `AUDIT` to log undeclared writes and
continue instead of raising immediately. Warning modes log the same
`StateContractError` message that `ENFORCE` would raise.

### Adopt Several Nodes At Once

`add_contract_nodes` registers many nodes with one call and one shared mode,
which suits instrumenting a whole graph in `OBSERVE` before promoting
individual nodes to `ENFORCE`:

```python
from graphobs import NodeContractMode, add_contract_nodes

add_contract_nodes(
    graph,
    [
        (classify_contract, classify),
        (answer_contract, answer),
    ],
    mode=NodeContractMode.OBSERVE,
)
```

## 4. Run The Graph

Run the same graph invocation you already use. If the node returns an undeclared
path, `StateContractError` points to the boundary mismatch.

```python
from graphobs.contracts.models import StateContractError

try:
    app.invoke({"request": {"text": "hello"}})
except StateContractError as exc:
    print(exc.undeclared_paths)
```

## 5. Add Correlation When Useful

```python
from graphobs import build_invoke_config
from graphobs.logging.context import LogContext

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

## Namespaces And Custom Reducers

Graphs that use custom reducers often write a top-level namespace key whose
nested shape is owned by reducer logic. During migration, prefer one of these
patterns:

- Declare the reducer-owned namespace broadly, such as `writes=("tools",)`, when
  nested marker keys are implementation details of the reducer.
- Use `private_writes` for local namespace state that should be validated but
  not projected publicly.
- Start with `mode=NodeContractMode.AUDIT` while confirming which reducer
  marker keys appear in real updates.
- Heavy namespace values are kept compact automatically by the default trace
  serializer, so declaring the namespace broadly is enough.

Strict dotted write paths are best for stable public state. Broad namespace
paths are often clearer for reducer-managed state that changes as one unit.

Node wrappers are reducer-safe: `contract_node` returns the node's partial
update unchanged, so a parent reducer such as `add_messages` or
`Annotated[list, operator.add]` applies exactly once.

`contract_subgraph` is different. It cannot see the parent graph's channel
reducers, so it returns the subgraph's full projected value. That is correct
for last-value-wins (overwrite) channels, but a non-deduplicating accumulating
reducer re-applies the value and duplicates the seeded input. Keep accumulating
channels on node-level contracts, or exclude them from `parent_output` and let
the subgraph own them privately.

## Quick Check

The first migrated node is complete when:

- Callback projection, observe, or audit mode preserves existing graph behavior.
- Enforce mode nodes receive only declared reads and private reads.
- The node returns only declared writes and private writes.
- Compact span input and output are useful without full state dumps.
- Existing graph behavior still passes its tests.
