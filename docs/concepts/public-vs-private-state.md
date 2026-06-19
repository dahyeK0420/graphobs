# Public Vs Private Graph State

Graph state often mixes data that belongs in a public boundary with details that
only one implementation step needs. graphobs keeps those ideas
separate in the contract.

## Public State

Public state is the state a node or subgraph intentionally exposes at a graph
boundary. Public reads describe the input a node needs. Public writes describe
the update a node is allowed to return.

Use public state for values that another graph step may depend on, values that
belong in curated trace payloads, and values that should appear in examples or
debugging views.

## Private State

Private state is local working state. It may be useful for a node or subgraph,
but it should not appear in parent-boundary projections or curated span output.

Private reads and writes are still declared so validation can catch accidental
state drift. They are not a security boundary. Sensitive data still needs normal
application controls, careful payload selection, and backend retention choices.

## Boundary Checklist

- Put stable cross-node values in public reads and writes.
- Put local scratch values in private reads and writes.
- Avoid broad public writes such as entire top-level state objects.
- Prefer dotted paths that describe the smallest useful state shape.
- Treat private state as a modeling boundary, not as permission control.

## Example

```python
from graphobs import NodeContract

contract = NodeContract(
    name="rank_documents",
    reads=("request.query", "retrieval.candidates"),
    writes=("answer.sources",),
    private_reads=("scratch.ranking_notes",),
    private_writes=("scratch.ranking_notes",),
)
```

The public output can show which sources were selected. The local ranking notes
remain implementation detail.
