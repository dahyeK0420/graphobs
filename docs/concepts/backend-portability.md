# Backend Portability With OTel And OpenInference

graphobs emits spans through OpenTelemetry and uses
OpenInference semantic attributes where they fit graph execution. It does not
choose, configure, or replace an observability backend.

## What The Kit Owns

- Span names and span kinds for graph steps.
- Compact or explicit full input and output payload serialization.
- Flat searchable attributes.
- Error marking on failed spans.
- Contract-driven payload projection before values reach spans.

## What The Application Owns

- OpenTelemetry tracer provider setup.
- Exporter selection and credentials.
- Backend retention, sampling, and access policy.
- Hosted or local backend operation.

This split keeps the library portable. A graph can emit the same span shape to a
local in-memory exporter during tests and to an OTLP-compatible backend in an
application.

## OpenInference Shape

The tracing helpers use OpenInference attributes for span kind, input value,
input MIME type, output value, and output MIME type. This makes graph spans more
readable in tools that understand those conventions while staying compatible
with normal OpenTelemetry processing.

## Practical Adoption

1. Configure tracing in the application boundary.
2. Wrap one node with a contract.
3. Inspect span names, attributes, and compact payload shape locally.
4. Send the same spans to the backend your application already uses.

The kit complements LangGraph and observability backends. LangGraph still runs
the graph. OpenTelemetry still transports telemetry. The backend still stores
and queries telemetry.
