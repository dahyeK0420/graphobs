# Tool Agent

This example compares a raw toy tool-calling graph with a contract-wrapped
version that emits a compact `TOOL` span.

```bash
uv run python -m examples.tool_agent.app
```

The raw trace includes the full synthetic tool call and response. The
contract-wrapped trace keeps tool input and output to compact public shape.
