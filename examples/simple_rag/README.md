# Simple RAG

This example compares a raw LangGraph retrieval flow with the same flow wrapped
in node contracts.

```bash
uv run python -m examples.simple_rag.app
```

The raw trace records the full synthetic graph state for comparison. The
contract-wrapped trace records only compact public span shape for
`classify_intent`, `retrieve_docs`, and `answer_question`.
