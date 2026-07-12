# Tracing

The tracing module contains backend-portable OpenTelemetry helpers. These APIs
emit OpenInference semantic attributes, but they do not configure exporters or
select an observability backend.

Payloads are compact by default. `TracePayloadMode.FULL` records complete
JSON-compatible payloads and should be used only for controlled debugging data
that is safe to store in traces. Pass `mode=TracePayloadMode.COMPACT` or
`mode=TracePayloadMode.FULL` to select payload serialization per span.

::: graphobs.tracing
