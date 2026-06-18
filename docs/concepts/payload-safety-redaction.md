# Payload Safety And Redaction

Trace payloads are useful because they show what a graph step saw and produced.
They are risky when they record more state than intended.

Graph Observability Kit defaults to compact payloads. Compact payloads describe
shape, not full values.

Contracts, structured logs, and traces use the public
`graph_observability_kit.payloads.shape_summary` helper so compact payloads do
not drift across observability surfaces.

```python
from graph_observability_kit.payloads import shape_summary

summary = shape_summary({"request": {"text": "hello"}})
```

## Compact Mode

`TracePayloadMode`, `PayloadSerializer`, and `default_payload_serializer` are
public APIs from `graph_observability_kit.tracing`. `TracePayloadMode.COMPACT`
records summaries such as mapping size, keys, string length, and sequence size.

```python
from graph_observability_kit.tracing import start_graph_span

with start_graph_span("classify", "CHAIN", input={"request": {"text": "hello"}}):
    ...
```

The span input is JSON, but it stores compact structure rather than the complete
state value.

## Full Mode

`TracePayloadMode.FULL` records complete JSON-compatible values. Use it only for
controlled debugging data that is safe to store in the selected trace backend.

```python
from graph_observability_kit.tracing import TracePayloadMode, start_graph_span

with start_graph_span(
    "debug_classify",
    "CHAIN",
    input={"request": {"text": "synthetic example"}},
    mode=TracePayloadMode.FULL,
):
    ...
```

Do not use full mode for sensitive production payloads.

## Custom Serializers

Applications can provide a `PayloadSerializer` callable when compact summaries
need project-specific rules.

```python
import json

from graph_observability_kit.tracing import (
    TracePayloadMode,
    default_payload_serializer,
)


def redacting_serializer(
    value: object,
    *,
    mode: TracePayloadMode = TracePayloadMode.COMPACT,
) -> str:
    if mode is TracePayloadMode.COMPACT and isinstance(value, dict):
        return json.dumps(
            {"type": "mapping", "redacted": "secret" in value},
            sort_keys=True,
            separators=(",", ":"),
        )
    return default_payload_serializer(value, mode=mode)
```

Keep serializer behavior deterministic. The goal is to make safe payload shape
repeatable across local tests and observability backends.

## Callback Boundaries

Contract wrappers curate the input passed into the inner node function and the
kit spans emitted around that node. LangGraph callback handlers can still see
the runtime's outer chain payload for node events.

Wrap callbacks with `project_callback_payloads` when a downstream callback
should receive contract-projected node inputs and outputs:

```python
from graph_observability_kit.callbacks import project_callback_payloads

config = {
    "callbacks": [
        project_callback_payloads(callback, [answer_contract], diagnostics=True),
    ],
}
```

The helper matches LangGraph node events by `metadata["langgraph_node"]`.
Iterable contracts are keyed by `contract.label`; pass an explicit mapping when
the graph node name differs from the contract label. Root graph events and
unknown nodes pass through unchanged. If a matched payload cannot be projected,
the helper logs a warning and forwards a compact shape summary instead of the
full value.

During migration, use `diagnostics=True` and inspect
`wrapper.projection_stats()` to confirm which LangGraph node names were
observed, matched, unmatched, or still missing. This is useful when subgraphs or
custom graph construction change node metadata names.

## Safety Checklist

- Prefer compact mode by default.
- Project state with contracts before recording span input or output.
- Wrap callbacks when they should observe the contract-projected node payload.
- Keep logs to lifecycle and correlation fields.
- Avoid full state dumps in logs, span attributes, and examples.
- Test serializer behavior with synthetic payloads before enabling it broadly.
