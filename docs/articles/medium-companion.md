# Medium Companion

This page is the practical companion for the Medium article:

[Your LangGraph traces are a mess, and it is not the tracer's fault](https://medium.com/@dahye.k94420/your-langgraph-traces-are-a-mess-and-its-not-the-tracer-s-fault-1bd6c1ad2146)

The article explains the design problem. These docs show the adoption path.

## Start Here

- [Migrate one node at a time](../guides/migration-one-node-at-a-time.md)
- [Design node contracts](../concepts/designing-node-contracts.md)
- [Understand state, logs, and traces](../concepts/state-logs-traces.md)
- [Keep payloads safe](../concepts/payload-safety-redaction.md)
- [Use portable OTel/OpenInference spans](../concepts/backend-portability.md)

## Minimal Wrapper

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

The wrapper leaves LangGraph in charge of graph execution. The contract controls
state projection, validation, and curated trace payload shape.
