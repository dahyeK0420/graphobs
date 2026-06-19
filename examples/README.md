# Examples

Runnable examples are intentionally small, synthetic, and local-only. They show
the same graph idea as raw LangGraph and as a contract-wrapped graph.

Each richer example prints deterministic JSON with raw trace shape,
contract-wrapped trace shape, a contract validation error, and lifecycle log
summaries.

```bash
uv run python examples/minimal_import.py
uv run python examples/langgraph_contracts.py
uv run python -m examples.simple_rag.app
uv run python -m examples.subgraph_boundary.app
uv run python -m examples.tool_agent.app
uv run python -m examples.backend_export.app
```

Example tests assert the important trace-shape guarantees without requiring
checked-in fixture files.
