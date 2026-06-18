# Subgraph Boundary

This example compares a raw parent graph with a contract-wrapped parent graph
that calls a synthetic retriever subgraph.

```bash
uv run python -m examples.subgraph_boundary.app
```

The retriever subgraph can use `scratch` locally, but the contract-wrapped
parent trace only exposes the parent input and output boundary.
