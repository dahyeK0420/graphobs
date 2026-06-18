# Payload Safety And Redaction

Trace payloads are useful because they show what a graph step saw and produced.
They are risky when they record more state than intended.

Graph Observability Kit defaults to compact payloads. Compact payloads describe
shape, not full values.

Contracts, structured logs, and traces use the same internal shape-summary
rules so compact payloads do not drift across observability surfaces.

## Compact Mode

`TracePayloadMode.COMPACT` records summaries such as mapping size, keys, string
length, and sequence size.

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

Applications can provide a payload serializer callable when compact summaries
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

## Safety Checklist

- Prefer compact mode by default.
- Project state with contracts before recording span input or output.
- Keep logs to lifecycle and correlation fields.
- Avoid full state dumps in logs, span attributes, and examples.
- Test serializer behavior with synthetic payloads before enabling it broadly.
