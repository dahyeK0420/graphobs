# Tracing

The tracing module contains backend-portable OpenTelemetry helpers. These APIs
emit OpenInference semantic attributes, but they do not configure exporters or
select an observability backend.

Payloads are compact by default. `TracePayloadMode.FULL` records complete
JSON-compatible payloads and should be used only for controlled debugging data
that is safe to store in traces.
`TracePayloadMode`, `PayloadSerializer`, and `default_payload_serializer` are
public tracing APIs for selecting and customizing payload serialization.

::: graph_observability_kit.tracing
